#!/usr/bin/env python3
"""
Claude Remote - Web terminal for Claude Code sessions.

Uses tmux for session management, allowing attach/detach from anywhere.
"""

import asyncio
import fcntl
import json
import os
import pty
import re
import shutil
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Configuration
CLAUDE_BIN = Path.home() / ".local/bin/claude"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude/projects"
DEFAULT_PORT = 7860
SESSION_PREFIX = "claude-remote-"

app = FastAPI(title="Claude Remote", version="0.2.0")


def run_cmd(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return result."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def tmux_session_exists(session_name: str) -> bool:
    """Check if a tmux session exists."""
    result = run_cmd(["tmux", "has-session", "-t", session_name])
    return result.returncode == 0


def list_tmux_sessions() -> list[dict]:
    """List all claude-remote tmux sessions."""
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


def create_tmux_session(
    session_name: str,
    working_dir: str,
    resume_id: Optional[str] = None,
    cols: int = 120,
    rows: int = 36,
) -> bool:
    """Create a new tmux session running Claude."""
    cmd = str(CLAUDE_BIN)
    if resume_id:
        cmd = f"{CLAUDE_BIN} --resume {resume_id}"
    
    # Create detached tmux session
    result = run_cmd([
        "tmux", "new-session",
        "-d",  # detached
        "-s", session_name,
        "-x", str(cols),
        "-y", str(rows),
        "-c", working_dir,
        cmd
    ])
    
    return result.returncode == 0


def kill_tmux_session(session_name: str) -> bool:
    """Kill a tmux session."""
    result = run_cmd(["tmux", "kill-session", "-t", session_name])
    return result.returncode == 0


def set_winsize(fd: int, rows: int, cols: int):
    """Set terminal window size."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def resize_tmux_session(session_name: str, cols: int, rows: int):
    """Resize tmux session."""
    run_cmd(["tmux", "resize-window", "-t", session_name, "-x", str(cols), "-y", str(rows)])


@dataclass 
class ExistingSession:
    """Represents an existing Claude session found on disk."""
    session_id: str
    project_dir: str
    working_dir: str
    last_modified: datetime
    size_bytes: int
    
    def to_dict(self):
        return {
            "session_id": self.session_id,
            "project_dir": self.project_dir,
            "working_dir": self.working_dir,
            "last_modified": self.last_modified.isoformat(),
            "size_mb": round(self.size_bytes / 1024 / 1024, 2),
        }


def discover_existing_sessions(limit: int = 20) -> list[ExistingSession]:
    """Discover existing Claude sessions from disk."""
    sessions_found = []
    
    if not CLAUDE_PROJECTS_DIR.exists():
        return sessions_found
    
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        
        # Convert project dir name back to path
        working_dir = "/" + project_dir.name.lstrip("-").replace("-", "/")
        
        # Find session files (.jsonl)
        session_files = list(project_dir.glob("*.jsonl"))
        session_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        for session_file in session_files[:3]:
            session_id = session_file.stem
            stat = session_file.stat()
            
            sessions_found.append(ExistingSession(
                session_id=session_id,
                project_dir=project_dir.name,
                working_dir=working_dir,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
                size_bytes=stat.st_size,
            ))
    
    sessions_found.sort(key=lambda s: s.last_modified, reverse=True)
    return sessions_found[:limit]


# Track active WebSocket connections per session
active_connections: dict[str, list[WebSocket]] = {}


# API Routes

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the web UI."""
    return FileResponse("static/index.html")


@app.get("/api/sessions")
async def list_sessions():
    """List all active tmux-managed Claude sessions."""
    tmux_sessions = list_tmux_sessions()
    
    sessions = []
    for ts in tmux_sessions:
        session_id = ts["name"].replace(SESSION_PREFIX, "")
        sessions.append({
            "id": session_id,
            "name": ts["name"],
            "working_dir": ts["cwd"],
            "created": datetime.fromtimestamp(ts["created"]).isoformat() if ts["created"] else None,
            "pid": ts["pid"],
            "tmux_session": ts["name"],
        })
    
    return {"sessions": sessions}


@app.get("/api/existing-sessions")
async def list_existing_sessions(limit: int = 20):
    """List existing Claude sessions found on disk."""
    existing = discover_existing_sessions(limit=limit)
    return {"sessions": [s.to_dict() for s in existing]}


@app.post("/api/sessions")
async def create_session(
    name: str = "Claude Session",
    working_dir: str = "~",
    resume_id: Optional[str] = None,
    rows: int = 36,
    cols: int = 120,
):
    """Create a new Claude Code session in tmux."""
    # Expand home directory
    wd = os.path.expanduser(working_dir)
    if not os.path.isdir(wd):
        raise HTTPException(status_code=400, detail=f"Invalid directory: {wd}")
    
    # Generate session ID and tmux session name
    session_id = str(uuid4())[:8]
    tmux_name = f"{SESSION_PREFIX}{session_id}"
    
    # Create tmux session
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
    """Terminate a session."""
    tmux_name = f"{SESSION_PREFIX}{session_id}"
    if not tmux_session_exists(tmux_name):
        raise HTTPException(status_code=404, detail="Session not found")
    
    kill_tmux_session(tmux_name)
    return {"status": "terminated"}


@app.websocket("/api/terminal/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for terminal I/O via tmux attach."""
    tmux_name = f"{SESSION_PREFIX}{session_id}"
    
    if not tmux_session_exists(tmux_name):
        await websocket.close(code=4004, reason="Session not found")
        return
    
    await websocket.accept()
    
    # Create PTY and attach to tmux session
    master_fd, slave_fd = pty.openpty()
    
    # Make master non-blocking
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    
    # Spawn tmux attach
    process = subprocess.Popen(
        ["tmux", "attach-session", "-t", tmux_name],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        preexec_fn=os.setsid,
    )
    
    os.close(slave_fd)
    
    async def read_pty():
        """Read from PTY and send to WebSocket."""
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
            except WebSocketDisconnect:
                break
            except Exception:
                break
    
    async def write_pty():
        """Receive from WebSocket and write to PTY."""
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.receive":
                    if "bytes" in message:
                        data = message["bytes"]
                    elif "text" in message:
                        try:
                            msg = json.loads(message["text"])
                            if msg.get("type") == "resize":
                                rows, cols = msg["rows"], msg["cols"]
                                set_winsize(master_fd, rows, cols)
                                resize_tmux_session(tmux_name, cols, rows)
                                continue
                        except json.JSONDecodeError:
                            data = message["text"].encode()
                    else:
                        continue
                    
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        break
                elif message["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
    
    read_task = asyncio.create_task(read_pty())
    write_task = asyncio.create_task(write_pty())
    
    try:
        done, pending = await asyncio.wait(
            [read_task, write_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except Exception:
        pass
    finally:
        # Clean up - detach but don't kill the tmux session
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            # Send detach signal to tmux attach process
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            pass


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    
    # Check for tmux
    if not shutil.which("tmux"):
        print("ERROR: tmux is required but not found")
        exit(1)
    
    print(f"Starting Claude Remote on http://0.0.0.0:{DEFAULT_PORT}")
    print(f"Using tmux for session management")
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
