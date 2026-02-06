#!/usr/bin/env python3
"""
Claude Remote v2.0 - Mission Control for Claude Code sessions.

Enhanced FastAPI server with:
- JSONL indexing and full-text search
- Rich conversation viewer with thinking/tool data
- Token analytics and cost estimation
- Platform-adaptive process detection (Linux + macOS)
- tmux session management with interactive/spectator WebSocket terminals
"""

import asyncio
import fcntl
import json
import logging
import os
import pty
import re
import shutil
import signal
import struct
import subprocess
import termios
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import indexer

# ─── Configuration ────────────────────────────────────────────────────────────

CLAUDE_BIN = Path.home() / ".local/bin/claude"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_PORT = 7860
SESSION_PREFIX = "claude-remote-"
REINDEX_INTERVAL = 60  # seconds

logger = logging.getLogger("server")

# ─── Background tasks ────────────────────────────────────────────────────────

_reindex_task: Optional[asyncio.Task] = None


async def _periodic_reindex():
    """Background task that reindexes periodically."""
    while True:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, indexer.reindex_all)
        except Exception as e:
            logger.error(f"Periodic reindex failed: {e}")
        await asyncio.sleep(REINDEX_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    global _reindex_task
    logger.info("Starting initial reindex...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, indexer.reindex_all)
    logger.info("Initial reindex complete. Starting periodic reindex.")
    _reindex_task = asyncio.create_task(_periodic_reindex())
    yield
    if _reindex_task:
        _reindex_task.cancel()
        try:
            await _reindex_task
        except asyncio.CancelledError:
            pass


# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="Claude Remote", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def run_cmd(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _get_active_and_tmux_ids() -> tuple[set, set]:
    """Get both active session IDs and tmux session IDs."""
    active = indexer.get_active_session_ids()
    tmux = indexer.get_tmux_session_ids()
    return active, tmux


# ─── tmux session management (preserved from v0.5) ───────────────────────────


def tmux_session_exists(session_name: str) -> bool:
    result = run_cmd(["tmux", "has-session", "-t", session_name])
    return result.returncode == 0


def list_tmux_sessions() -> list[dict]:
    result = run_cmd([
        "tmux", "list-sessions", "-F",
        "#{session_name}|#{session_created}|#{pane_current_path}|#{pane_pid}"
    ])
    sessions = []
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if not line or not line.startswith(SESSION_PREFIX):
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                sessions.append({
                    "name": parts[0],
                    "created": int(parts[1]) if parts[1].isdigit() else 0,
                    "cwd": parts[2],
                    "pid": int(parts[3]) if parts[3].isdigit() else None,
                })
    return sessions


def create_tmux_session(session_name: str, working_dir: str,
                        resume_id: Optional[str] = None,
                        cols: int = 120, rows: int = 36) -> bool:
    cmd = str(CLAUDE_BIN)
    if resume_id:
        cmd = f"{CLAUDE_BIN} --resume {resume_id}"
    result = run_cmd([
        "tmux", "new-session", "-d", "-s", session_name,
        "-x", str(cols), "-y", str(rows), "-c", working_dir, cmd
    ])
    return result.returncode == 0


def kill_tmux_session(session_name: str) -> bool:
    result = run_cmd(["tmux", "kill-session", "-t", session_name])
    return result.returncode == 0


def set_winsize(fd: int, rows: int, cols: int):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def resize_tmux_session(session_name: str, cols: int, rows: int):
    run_cmd(["tmux", "resize-window", "-t", session_name,
             "-x", str(cols), "-y", str(rows)])


# ─── API Routes: Static / Index ──────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index_page():
    static_dir = Path(__file__).parent / "static"
    index_html = static_dir / "index.html"
    if index_html.exists():
        return FileResponse(str(index_html))
    return HTMLResponse("<h1>Claude Remote v2.0</h1><p>Static files not found.</p>")


# ─── API Routes: Dashboard ───────────────────────────────────────────────────


@app.get("/api/dashboard")
async def api_dashboard():
    active_ids, tmux_ids = _get_active_and_tmux_ids()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, indexer.get_dashboard_data, active_ids, tmux_ids
    )
    return data


# ─── API Routes: Sessions ────────────────────────────────────────────────────


@app.get("/api/sessions")
async def api_sessions(
    status: str = Query(default="all"),
    project: Optional[str] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    active_ids, tmux_ids = _get_active_and_tmux_ids()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, indexer.get_sessions, active_ids, tmux_ids, status, project, limit, offset
    )
    return data


@app.get("/api/sessions/{session_id}")
async def api_session_detail(session_id: str):
    active_ids, tmux_ids = _get_active_and_tmux_ids()
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, indexer.get_session_detail, session_id, active_ids, tmux_ids
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@app.get("/api/sessions/{session_id}/conversation")
async def api_conversation(
    session_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, indexer.get_conversation, session_id, limit, offset
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


# ─── API Routes: tmux session management (preserved from v0.5) ───────────────


@app.post("/api/sessions")
async def create_session(
    name: str = "Claude Session",
    working_dir: str = "~",
    resume_id: Optional[str] = None,
    rows: int = 36,
    cols: int = 120,
):
    wd = os.path.expanduser(working_dir)
    if not os.path.isdir(wd):
        raise HTTPException(status_code=400, detail=f"Invalid directory: {wd}")

    session_id = str(uuid4())[:8]
    tmux_name = f"{SESSION_PREFIX}{session_id}"

    if not create_tmux_session(tmux_name, wd, resume_id, cols, rows):
        raise HTTPException(status_code=500, detail="Failed to create tmux session")

    return {
        "id": session_id,
        "name": name,
        "working_dir": wd,
        "tmux_session": tmux_name,
        "resume_id": resume_id,
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    tmux_name = f"{SESSION_PREFIX}{session_id}"
    if not tmux_session_exists(tmux_name):
        raise HTTPException(status_code=404, detail="Session not found")
    kill_tmux_session(tmux_name)
    return {"status": "terminated"}


# ─── API Routes: Search ──────────────────────────────────────────────────────


@app.get("/api/search")
async def api_search(
    q: str = Query(default=""),
    project: Optional[str] = Query(default=None),
    after: Optional[str] = Query(default=None),
    before: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    if not q.strip():
        return {"query": q, "results": [], "total": 0}
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, indexer.search, q, project, after, before, limit
    )
    return data


# ─── API Routes: Analytics ───────────────────────────────────────────────────


@app.get("/api/analytics/tokens")
async def api_token_analytics(
    period: str = Query(default="7d"),
    group_by: str = Query(default="day"),
):
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, indexer.get_token_analytics, period, group_by
    )
    return data


@app.get("/api/analytics/tools")
async def api_tool_analytics(
    period: str = Query(default="7d"),
):
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, indexer.get_tool_analytics, period
    )
    return data


# ─── API Routes: Reindex ─────────────────────────────────────────────────────


@app.post("/api/reindex")
async def api_reindex():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, indexer.reindex_all, True)
    return {"status": "ok", **result}


# ─── WebSocket Terminal (preserved from v0.5) ────────────────────────────────


@app.websocket("/api/terminal/{session_id}")
async def terminal_websocket(
    websocket: WebSocket,
    session_id: str,
    mode: str = Query(default="interactive"),
):
    tmux_name = f"{SESSION_PREFIX}{session_id}"

    if not tmux_session_exists(tmux_name):
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    read_only = (mode == "spectator")

    master_fd, slave_fd = pty.openpty()
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    attach_cmd = ["tmux", "attach-session", "-t", tmux_name]
    if read_only:
        attach_cmd.append("-r")

    process = subprocess.Popen(
        attach_cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    async def read_pty():
        while True:
            try:
                await asyncio.sleep(0.01)
                try:
                    data = os.read(master_fd, 4096)
                    if data:
                        await websocket.send_bytes(data)
                except BlockingIOError:
                    continue
                except OSError:
                    break
            except Exception:
                break

    async def write_pty():
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.receive":
                    if "bytes" in message:
                        data = message["bytes"]
                    elif "text" in message:
                        try:
                            msg = json.loads(message["text"])
                            if msg.get("type") == "resize" and not read_only:
                                set_winsize(master_fd, msg["rows"], msg["cols"])
                                resize_tmux_session(tmux_name, msg["cols"], msg["rows"])
                                continue
                        except json.JSONDecodeError:
                            data = message["text"].encode()
                    else:
                        continue
                    if not read_only:
                        try:
                            os.write(master_fd, data)
                        except OSError:
                            break
                elif message["type"] == "websocket.disconnect":
                    break
        except Exception:
            pass

    read_task = asyncio.create_task(read_pty())
    write_task = asyncio.create_task(write_pty())

    try:
        await asyncio.wait(
            [read_task, write_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in [read_task, write_task]:
            task.cancel()
    except Exception:
        pass
    finally:
        try:
            os.close(master_fd)
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            pass


# ─── Static files mount (must be last) ───────────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if not shutil.which("tmux"):
        print("WARNING: tmux not found - terminal features will be unavailable")

    print(f"Starting Claude Remote v2.0 on http://0.0.0.0:{DEFAULT_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
