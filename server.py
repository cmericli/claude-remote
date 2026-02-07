#!/usr/bin/env python3
"""
Claude Remote v3.0 - The Living Dashboard for Claude Code sessions.

FastAPI server with:
- JSONL indexing and full-text search (SQLite + FTS5)
- Rich conversation viewer with thinking/tool data
- Token analytics and cost estimation
- Platform-adaptive process detection (Linux + macOS)
- tmux session management with interactive/spectator WebSocket terminals
- Join session: one-click resume/attach from conversation view (v3.0)
- Live streaming: Server-Sent Events for real-time dashboard/conversation updates (v3.0)
- EventBus: async pub/sub with JSONL file watcher and needs-input detection (v3.0)
- PWA: Progressive Web App with service worker and push notifications (v3.0)
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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import indexer

# ─── Configuration ────────────────────────────────────────────────────────────

CLAUDE_BIN = Path.home() / ".local/bin/claude"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
DEFAULT_PORT = 7860
SESSION_PREFIX = "claude-remote-"
REINDEX_INTERVAL = 60  # seconds
VAPID_KEYS_PATH = Path.home() / ".claude-remote" / "vapid_keys.json"
PUSH_RATE_LIMIT_SEC = 300  # 5 minutes per session
PUSH_GLOBAL_LIMIT_HOUR = 10

logger = logging.getLogger("server")

# ─── VAPID Key Management ────────────────────────────────────────────────────

_vapid_private_key: Optional[str] = None
_vapid_public_key: Optional[str] = None
_push_timestamps: dict[str, float] = {}  # session_id -> last push time
_push_hour_count: int = 0
_push_hour_start: float = 0


def _init_vapid_keys():
    """Generate or load VAPID keys for Web Push."""
    global _vapid_private_key, _vapid_public_key
    VAPID_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if VAPID_KEYS_PATH.exists():
        try:
            data = json.loads(VAPID_KEYS_PATH.read_text())
            _vapid_private_key = data.get("private_key")
            _vapid_public_key = data.get("public_key")
            if _vapid_private_key and _vapid_public_key:
                return
        except Exception:
            pass

    # Generate new keys
    try:
        from py_vapid import Vapid
        vapid = Vapid()
        vapid.generate_keys()
        _vapid_private_key = vapid.private_pem().decode("utf-8")
        _vapid_public_key = vapid.public_key_urlsafe_base64()
        VAPID_KEYS_PATH.write_text(json.dumps({
            "private_key": _vapid_private_key,
            "public_key": _vapid_public_key,
        }, indent=2))
        logger.info("Generated new VAPID keys")
    except ImportError:
        logger.warning("pywebpush not installed - push notifications disabled")
    except Exception as e:
        logger.warning(f"VAPID key generation failed: {e}")


def _send_push_notification(session_id: str, title: str, body: str):
    """Send Web Push to all subscribers with rate limiting."""
    global _push_hour_count, _push_hour_start

    if not _vapid_private_key:
        return

    now = time.time()

    # Per-session rate limit
    last_push = _push_timestamps.get(session_id, 0)
    if now - last_push < PUSH_RATE_LIMIT_SEC:
        return

    # Global hourly rate limit
    if now - _push_hour_start > 3600:
        _push_hour_count = 0
        _push_hour_start = now
    if _push_hour_count >= PUSH_GLOBAL_LIMIT_HOUR:
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return

    subscriptions = indexer.get_push_subscriptions()
    if not subscriptions:
        return

    payload = json.dumps({
        "title": title,
        "body": body,
        "session_id": session_id,
        "tag": "claude-remote-" + session_id[:8],
    })

    _push_timestamps[session_id] = now
    _push_hour_count += 1

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=_vapid_private_key,
                vapid_claims={"sub": "mailto:claude-remote@localhost"},
            )
        except Exception as e:
            err_str = str(e)
            # Clean up stale subscriptions (410 Gone)
            if "410" in err_str or "Gone" in err_str:
                indexer.delete_push_subscription(sub["endpoint"])
                logger.info(f"Removed stale push subscription")
            else:
                logger.debug(f"Push send failed: {e}")

# ─── EventBus (SSE pub/sub) ──────────────────────────────────────────────────


class EventBus:
    """Async pub/sub event bus for SSE streaming."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = []
            self._subscribers[topic].append(queue)
        return queue

    async def unsubscribe(self, topic: str, queue: asyncio.Queue):
        async with self._lock:
            if topic in self._subscribers:
                try:
                    self._subscribers[topic].remove(queue)
                except ValueError:
                    pass
                if not self._subscribers[topic]:
                    del self._subscribers[topic]

    async def publish(self, topic: str, event: dict):
        async with self._lock:
            queues = list(self._subscribers.get(topic, []))
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event to make room
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def publish_global(self, event: dict):
        """Publish to __global__ topic (dashboard stream)."""
        await self.publish("__global__", event)


event_bus = EventBus()

# ─── JSONL File Watcher ──────────────────────────────────────────────────────

# Track file positions for incremental reading
_file_positions: dict[str, int] = {}
_watcher_task: Optional[asyncio.Task] = None


def _is_fuse_mount(path: Path) -> bool:
    """Check if path is on a FUSE filesystem (like Google Drive)."""
    path_str = str(path)
    return "GoogleDrive" in path_str or "Google Drive" in path_str or "CloudStorage" in path_str


def _read_new_jsonl_lines(jsonl_path: str) -> list[dict]:
    """Read new lines from a JSONL file since last known position."""
    path = Path(jsonl_path)
    if not path.exists():
        return []

    try:
        current_size = path.stat().st_size
    except OSError:
        return []

    last_pos = _file_positions.get(jsonl_path, 0)
    if current_size <= last_pos:
        return []

    new_entries = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(last_pos)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict):
                        new_entries.append(entry)
                except json.JSONDecodeError:
                    continue
            _file_positions[jsonl_path] = f.tell()
    except Exception as e:
        logger.debug(f"Error reading {jsonl_path}: {e}")

    return new_entries


async def _jsonl_watcher():
    """Background task that watches JSONL files for changes and emits SSE events."""
    poll_interval = 2.0  # seconds (stat-based polling, works on FUSE)
    batch_delay = 0.5  # accumulate events before emitting

    # Initialize positions for all existing files
    if CLAUDE_PROJECTS_DIR.exists():
        for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                path_str = str(jsonl_file)
                try:
                    _file_positions[path_str] = jsonl_file.stat().st_size
                except OSError:
                    pass

    while True:
        try:
            if not CLAUDE_PROJECTS_DIR.exists():
                await asyncio.sleep(poll_interval)
                continue

            pending_events: list[tuple[str, dict]] = []

            for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
                if not project_dir.is_dir():
                    continue
                for jsonl_file in project_dir.glob("*.jsonl"):
                    path_str = str(jsonl_file)
                    session_id = jsonl_file.stem
                    new_entries = await asyncio.get_event_loop().run_in_executor(
                        None, _read_new_jsonl_lines, path_str
                    )
                    for entry in new_entries:
                        entry_type = entry.get("type", "")
                        if entry_type in ("user", "assistant"):
                            msg = entry.get("message", {})
                            role = msg.get("role", entry_type) if isinstance(msg, dict) else entry_type
                            # Extract preview text
                            content = msg.get("content", "") if isinstance(msg, dict) else ""
                            preview = ""
                            if isinstance(content, str):
                                preview = content[:120]
                            elif isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        preview = block.get("text", "")[:120]
                                        break

                            event = {
                                "type": "new_message",
                                "session_id": session_id,
                                "role": role,
                                "preview": preview,
                                "timestamp": entry.get("timestamp", ""),
                            }

                            # Check for tool uses
                            tool_names = []
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "tool_use":
                                        tool_names.append(block.get("name", ""))
                            if tool_names:
                                event["tool_uses"] = tool_names

                            pending_events.append((session_id, event))

            # Batch emit
            if pending_events:
                await asyncio.sleep(batch_delay)
                for session_id, event in pending_events:
                    await event_bus.publish(session_id, event)
                    await event_bus.publish_global(event)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"JSONL watcher error: {e}")

        await asyncio.sleep(poll_interval)


# ─── Needs-Input Detector ────────────────────────────────────────────────────

_needs_input_sessions: set = set()
_needs_input_cooldown: dict[str, float] = {}
_needs_input_task: Optional[asyncio.Task] = None
NEEDS_INPUT_COOLDOWN_SEC = 300  # 5 minutes


async def _needs_input_detector():
    """Detect sessions that appear to be waiting for user input."""
    check_interval = 15  # seconds
    stale_threshold = 30  # seconds since last assistant message

    while True:
        try:
            active_ids = await asyncio.get_event_loop().run_in_executor(
                None, indexer.get_active_session_ids
            )

            now = time.time()
            newly_needs_input = set()

            for session_id in active_ids:
                # Check cooldown
                last_notified = _needs_input_cooldown.get(session_id, 0)
                if now - last_notified < NEEDS_INPUT_COOLDOWN_SEC:
                    continue

                # Check JSONL for last message
                conv = await asyncio.get_event_loop().run_in_executor(
                    None, indexer.get_conversation, session_id, 1, 0
                )
                if not conv or not conv.get("messages"):
                    continue

                # Get the most recent message (we need to check last, not first)
                total = conv.get("total", 0)
                if total > 1:
                    conv = await asyncio.get_event_loop().run_in_executor(
                        None, indexer.get_conversation, session_id, 1, total - 1
                    )
                    if not conv or not conv.get("messages"):
                        continue

                last_msg = conv["messages"][-1]
                if last_msg.get("role") != "assistant":
                    continue

                # Check if message is old enough
                ts = last_msg.get("timestamp", "")
                if not ts:
                    continue
                try:
                    msg_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age_sec = (datetime.now(msg_time.tzinfo) - msg_time).total_seconds()
                    if age_sec > stale_threshold:
                        newly_needs_input.add(session_id)
                except (ValueError, TypeError):
                    continue

            # Emit events for newly detected
            for session_id in newly_needs_input:
                if session_id not in _needs_input_sessions:
                    event = {
                        "type": "needs_input",
                        "session_id": session_id,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                    await event_bus.publish(session_id, event)
                    await event_bus.publish_global(event)
                    _needs_input_cooldown[session_id] = now
                    logger.info(f"Session {session_id[:8]}... needs input")
                    # Send push notification in background
                    await asyncio.get_event_loop().run_in_executor(
                        None, _send_push_notification,
                        session_id, "Session needs input",
                        f"Session {session_id[:8]}... is waiting for your response"
                    )

            _needs_input_sessions.clear()
            _needs_input_sessions.update(newly_needs_input)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Needs-input detector error: {e}")

        await asyncio.sleep(check_interval)


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
    global _reindex_task, _watcher_task, _needs_input_task
    logger.info("Initializing VAPID keys...")
    _init_vapid_keys()
    logger.info("Starting initial reindex...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, indexer.reindex_all)
    logger.info("Initial reindex complete. Starting background tasks.")
    _reindex_task = asyncio.create_task(_periodic_reindex())
    _watcher_task = asyncio.create_task(_jsonl_watcher())
    _needs_input_task = asyncio.create_task(_needs_input_detector())
    yield
    for task in [_reindex_task, _watcher_task, _needs_input_task]:
        if task:
            task.cancel()
            try:
                await task
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


def find_tmux_for_session(session_id: str) -> Optional[str]:
    """Find a tmux session that is running claude --resume for the given session_id."""
    for tmux_sess in list_tmux_sessions():
        name = tmux_sess["name"]
        pid = tmux_sess.get("pid")
        if not pid:
            continue
        try:
            # Check child processes for --resume with this session_id
            result = run_cmd(["ps", "-o", "args=", "-p", str(pid)])
            cmdline = result.stdout.strip()
            if f"--resume {session_id}" in cmdline:
                return name
            # Also check children of the tmux pane process
            children = run_cmd(["pgrep", "-P", str(pid)])
            for child_pid in children.stdout.strip().splitlines():
                child_pid = child_pid.strip()
                if child_pid:
                    child_result = run_cmd(["ps", "-o", "args=", "-p", child_pid])
                    if f"--resume {session_id}" in child_result.stdout:
                        return name
        except Exception:
            continue
    return None


def inject_to_tmux(session_name: str, text: str) -> bool:
    """Send keystrokes to a tmux session."""
    result = run_cmd(["tmux", "send-keys", "-t", session_name, text, "Enter"])
    return result.returncode == 0


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


@app.post("/api/sessions/{session_id}/join")
async def join_session(session_id: str):
    """Join (resume) a Claude session in a tmux terminal."""
    # Check if a tmux session already exists for this Claude session
    existing_tmux = find_tmux_for_session(session_id)
    if existing_tmux:
        short_id = existing_tmux.replace(SESSION_PREFIX, "")
        return {"action": "attached", "tmux_session": existing_tmux, "tmux_id": short_id}

    # Look up working directory from indexer
    loop = asyncio.get_event_loop()
    working_dir = await loop.run_in_executor(None, indexer.get_session_working_dir, session_id)
    if not working_dir or not os.path.isdir(working_dir):
        working_dir = os.path.expanduser("~")

    # Create a new tmux session with --resume
    short_id = str(uuid4())[:8]
    tmux_name = f"{SESSION_PREFIX}{short_id}"
    if not create_tmux_session(tmux_name, working_dir, resume_id=session_id):
        raise HTTPException(status_code=500, detail="Failed to create tmux session")

    return {"action": "created", "tmux_session": tmux_name, "tmux_id": short_id}


@app.post("/api/terminal/{session_id}/inject")
async def inject_terminal(session_id: str, body: dict = None):
    """Inject text into a tmux session's terminal."""
    if not body or "text" not in body:
        raise HTTPException(status_code=400, detail="Missing 'text' field in body")

    text = body["text"].rstrip("\n")  # tmux send-keys adds Enter separately
    tmux_name = f"{SESSION_PREFIX}{session_id}"

    if not tmux_session_exists(tmux_name):
        # Try to find by full session_id (resume match)
        tmux_name = find_tmux_for_session(session_id)
        if not tmux_name:
            raise HTTPException(status_code=404, detail="No tmux session found")

    if not inject_to_tmux(tmux_name, text):
        raise HTTPException(status_code=500, detail="Failed to inject text")

    return {"status": "ok", "text": text, "tmux_session": tmux_name}


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


# ─── API Routes: SSE Streaming ──────────────────────────────────────────────

MAX_SSE_CONNECTIONS = 5
_sse_connection_count = 0


@app.get("/api/sessions/{session_id}/stream")
async def session_stream(session_id: str, request: Request):
    """SSE stream for a specific session's events."""
    global _sse_connection_count
    if _sse_connection_count >= MAX_SSE_CONNECTIONS:
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    async def event_generator():
        global _sse_connection_count
        _sse_connection_count += 1
        queue = await event_bus.subscribe(session_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.unsubscribe(session_id, queue)
            _sse_connection_count -= 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/dashboard/stream")
async def dashboard_stream(request: Request):
    """SSE stream for global dashboard events."""
    global _sse_connection_count
    if _sse_connection_count >= MAX_SSE_CONNECTIONS:
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    async def event_generator():
        global _sse_connection_count
        _sse_connection_count += 1
        queue = await event_bus.subscribe("__global__")
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.unsubscribe("__global__", queue)
            _sse_connection_count -= 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/needs-input")
async def api_needs_input():
    """Return set of session IDs that currently need user input."""
    return {"sessions": list(_needs_input_sessions)}


# ─── API Routes: Push Notifications ─────────────────────────────────────────


@app.get("/api/push/vapid-key")
async def get_vapid_key():
    """Return the VAPID public key for push subscription."""
    if not _vapid_public_key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": _vapid_public_key}


@app.post("/api/push/subscribe")
async def push_subscribe(body: dict = None):
    """Store a push notification subscription."""
    if not body or "endpoint" not in body:
        raise HTTPException(status_code=400, detail="Invalid subscription")

    endpoint = body["endpoint"]
    keys = body.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Missing subscription keys")

    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(
        None, indexer.save_push_subscription, endpoint, p256dh, auth, ""
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save subscription")

    return {"status": "subscribed"}


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
