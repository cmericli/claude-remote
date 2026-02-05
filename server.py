#!/usr/bin/env python3
"""
Claude Remote - Web terminal for Claude Code sessions.

Exposes Claude Code sessions via WebSocket for browser-based access.
"""

import asyncio
import fcntl
import json
import os
import pty
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
SESSIONS_DIR = Path.home() / ".claude-remote/sessions"
DEFAULT_PORT = 7860

app = FastAPI(title="Claude Remote", version="0.1.0")


@dataclass
class Session:
    """Represents a Claude Code session."""
    id: str
    name: str
    working_dir: str
    master_fd: int
    pid: int
    created_at: datetime = field(default_factory=datetime.now)
    claude_resume_id: Optional[str] = None
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "working_dir": self.working_dir,
            "pid": self.pid,
            "created_at": self.created_at.isoformat(),
            "claude_resume_id": self.claude_resume_id,
        }


# In-memory session store
sessions: dict[str, Session] = {}


def set_winsize(fd: int, rows: int, cols: int):
    """Set terminal window size."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


async def spawn_claude_session(
    name: str,
    working_dir: str,
    resume_id: Optional[str] = None,
    rows: int = 24,
    cols: int = 80,
) -> Session:
    """Spawn a new Claude Code session in a PTY."""
    session_id = str(uuid4())[:8]
    
    # Build command
    cmd = [str(CLAUDE_BIN)]
    if resume_id:
        cmd.extend(["--resume", resume_id])
    
    # Create PTY
    master_fd, slave_fd = pty.openpty()
    set_winsize(master_fd, rows, cols)
    
    # Make master non-blocking
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    
    # Spawn process
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    
    process = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=working_dir,
        env=env,
        preexec_fn=os.setsid,
    )
    
    os.close(slave_fd)  # Close slave in parent
    
    session = Session(
        id=session_id,
        name=name,
        working_dir=working_dir,
        master_fd=master_fd,
        pid=process.pid,
        claude_resume_id=resume_id,
    )
    
    sessions[session_id] = session
    return session


def cleanup_session(session_id: str):
    """Clean up a terminated session."""
    if session_id in sessions:
        session = sessions[session_id]
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        try:
            os.kill(session.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        del sessions[session_id]


# API Routes

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the web UI."""
    return FileResponse("static/index.html")


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    # Clean up dead sessions
    dead = []
    for sid, session in sessions.items():
        try:
            os.kill(session.pid, 0)  # Check if process exists
        except ProcessLookupError:
            dead.append(sid)
    for sid in dead:
        cleanup_session(sid)
    
    return {"sessions": [s.to_dict() for s in sessions.values()]}


@app.post("/api/sessions")
async def create_session(
    name: str = "Claude Session",
    working_dir: str = "~",
    resume_id: Optional[str] = None,
    rows: int = 24,
    cols: int = 80,
):
    """Create a new Claude Code session."""
    # Expand home directory
    wd = os.path.expanduser(working_dir)
    if not os.path.isdir(wd):
        raise HTTPException(status_code=400, detail=f"Invalid directory: {wd}")
    
    session = await spawn_claude_session(name, wd, resume_id, rows, cols)
    return session.to_dict()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Terminate a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    cleanup_session(session_id)
    return {"status": "terminated"}


@app.websocket("/api/terminal/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for terminal I/O."""
    if session_id not in sessions:
        await websocket.close(code=4004, reason="Session not found")
        return
    
    session = sessions[session_id]
    await websocket.accept()
    
    loop = asyncio.get_event_loop()
    
    async def read_pty():
        """Read from PTY and send to WebSocket."""
        while True:
            try:
                await asyncio.sleep(0.01)  # Small delay to batch reads
                try:
                    data = os.read(session.master_fd, 4096)
                    if data:
                        await websocket.send_bytes(data)
                except BlockingIOError:
                    continue
                except OSError:
                    break
            except WebSocketDisconnect:
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
                        # Handle resize messages
                        try:
                            msg = json.loads(message["text"])
                            if msg.get("type") == "resize":
                                set_winsize(
                                    session.master_fd,
                                    msg["rows"],
                                    msg["cols"]
                                )
                                continue
                        except json.JSONDecodeError:
                            data = message["text"].encode()
                    else:
                        continue
                    
                    try:
                        os.write(session.master_fd, data)
                    except OSError:
                        break
                elif message["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass
    
    # Run both tasks concurrently
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
        read_task.cancel()
        write_task.cancel()


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    
    # Ensure sessions directory exists
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Starting Claude Remote on http://0.0.0.0:{DEFAULT_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
