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
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Configuration
CLAUDE_BIN = Path.home() / ".local/bin/claude"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude/projects"
DEFAULT_PORT = 7860
SESSION_PREFIX = "claude-remote-"

app = FastAPI(title="Claude Remote", version="0.5.0")


def run_cmd(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def get_active_session_ids() -> set[str]:
    """Get set of session IDs currently running based on process command lines."""
    active_sessions = set()
    
    try:
        ps_output = subprocess.check_output(['ps', 'aux'], text=True)
        for line in ps_output.splitlines():
            if 'claude' not in line.lower() or 'grep' in line or 'server.py' in line:
                continue
            if '--chrome-native-host' in line or '--claude-in-chrome-mcp' in line:
                continue
            
            parts = line.split()
            if len(parts) < 2:
                continue
            pid = parts[1]
            
            try:
                with open(f'/proc/{pid}/cmdline', 'r') as f:
                    cmdline = f.read().replace('\0', ' ')
                cwd = os.readlink(f'/proc/{pid}/cwd')
            except:
                continue
            
            session_id = None
            
            # Check for --resume or --session-id in command line
            match = re.search(r'--resume\s+([a-f0-9-]{36})', cmdline)
            if match:
                session_id = match.group(1)
            else:
                match = re.search(r'--session-id\s+([a-f0-9-]{36})', cmdline)
                if match:
                    session_id = match.group(1)
            
            # For --continue or plain claude, find most recent session in cwd
            if not session_id and cwd:
                project_dir = '-' + cwd.replace('/', '-').lstrip('-')
                projects_path = CLAUDE_PROJECTS_DIR / project_dir
                if projects_path.exists():
                    sessions = list(projects_path.glob('*.jsonl'))
                    if sessions:
                        sessions.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                        session_id = sessions[0].stem
            
            if session_id:
                active_sessions.add(session_id)
    
    except subprocess.CalledProcessError:
        pass
    
    return active_sessions


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


def get_tmux_session_ids() -> set[str]:
    sessions = list_tmux_sessions()
    return {s["name"].replace(SESSION_PREFIX, "") for s in sessions}


def create_tmux_session(session_name: str, working_dir: str, resume_id: Optional[str] = None, cols: int = 120, rows: int = 36) -> bool:
    cmd = str(CLAUDE_BIN)
    if resume_id:
        cmd = f"{CLAUDE_BIN} --resume {resume_id}"
    
    result = run_cmd(["tmux", "new-session", "-d", "-s", session_name, "-x", str(cols), "-y", str(rows), "-c", working_dir, cmd])
    return result.returncode == 0


def kill_tmux_session(session_name: str) -> bool:
    result = run_cmd(["tmux", "kill-session", "-t", session_name])
    return result.returncode == 0


def set_winsize(fd: int, rows: int, cols: int):
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def resize_tmux_session(session_name: str, cols: int, rows: int):
    run_cmd(["tmux", "resize-window", "-t", session_name, "-x", str(cols), "-y", str(rows)])


def parse_session_history(session_path: Path, limit: int = 200) -> list[dict]:
    messages = []
    try:
        with open(session_path, 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("type") not in ("user", "assistant"):
                        if "message" not in entry:
                            continue
                    
                    msg = entry.get("message", {})
                    role = msg.get("role") or entry.get("type")
                    if role not in ("user", "assistant"):
                        continue
                    
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict):
                                if part.get("type") == "text":
                                    text_parts.append(part.get("text", ""))
                                elif part.get("type") == "tool_use":
                                    text_parts.append(f"[Tool: {part.get('name', 'unknown')}]")
                            elif isinstance(part, str):
                                text_parts.append(part)
                        content = "\n".join(text_parts)
                    
                    if content and content.strip():
                        messages.append({
                            "role": role,
                            "content": content[:5000],
                            "timestamp": entry.get("timestamp", ""),
                        })
                        if len(messages) >= limit:
                            break
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error parsing session: {e}")
    return messages


@dataclass 
class ExistingSession:
    session_id: str
    project_dir: str
    working_dir: str
    last_modified: datetime
    size_bytes: int
    is_running: bool = False
    is_in_tmux: bool = False
    
    def to_dict(self):
        return {
            "session_id": self.session_id,
            "project_dir": self.project_dir,
            "working_dir": self.working_dir,
            "last_modified": self.last_modified.isoformat(),
            "size_mb": round(self.size_bytes / 1024 / 1024, 2),
            "is_running": self.is_running,
            "is_in_tmux": self.is_in_tmux,
        }


def discover_existing_sessions(limit: int = 30) -> list[ExistingSession]:
    sessions_found = []
    active_session_ids = get_active_session_ids()
    tmux_ids = get_tmux_session_ids()
    
    if not CLAUDE_PROJECTS_DIR.exists():
        return sessions_found
    
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        
        working_dir = "/" + project_dir.name.lstrip("-").replace("-", "/")
        session_files = list(project_dir.glob("*.jsonl"))
        session_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        
        for session_file in session_files[:5]:
            session_id = session_file.stem
            stat = session_file.stat()
            
            sessions_found.append(ExistingSession(
                session_id=session_id,
                project_dir=project_dir.name,
                working_dir=working_dir,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
                size_bytes=stat.st_size,
                is_running=session_id in active_session_ids,
                is_in_tmux=session_id[:8] in tmux_ids,
            ))
    
    sessions_found.sort(key=lambda s: s.last_modified, reverse=True)
    return sessions_found[:limit]


# API Routes

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("static/index.html")


@app.get("/api/sessions")
async def list_sessions():
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
async def list_existing_sessions(limit: int = 30):
    existing = discover_existing_sessions(limit=limit)
    return {"sessions": [s.to_dict() for s in existing]}


@app.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 200):
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        session_file = project_dir / f"{session_id}.jsonl"
        if session_file.exists():
            messages = parse_session_history(session_file, limit)
            return {
                "session_id": session_id,
                "project_dir": project_dir.name,
                "message_count": len(messages),
                "messages": messages,
            }
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions")
async def create_session(name: str = "Claude Session", working_dir: str = "~", resume_id: Optional[str] = None, rows: int = 36, cols: int = 120):
    wd = os.path.expanduser(working_dir)
    if not os.path.isdir(wd):
        raise HTTPException(status_code=400, detail=f"Invalid directory: {wd}")
    
    session_id = str(uuid4())[:8]
    tmux_name = f"{SESSION_PREFIX}{session_id}"
    
    if not create_tmux_session(tmux_name, wd, resume_id, cols, rows):
        raise HTTPException(status_code=500, detail="Failed to create tmux session")
    
    return {"id": session_id, "name": name, "working_dir": wd, "tmux_session": tmux_name, "resume_id": resume_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    tmux_name = f"{SESSION_PREFIX}{session_id}"
    if not tmux_session_exists(tmux_name):
        raise HTTPException(status_code=404, detail="Session not found")
    kill_tmux_session(tmux_name)
    return {"status": "terminated"}


@app.websocket("/api/terminal/{session_id}")
async def terminal_websocket(websocket: WebSocket, session_id: str, mode: str = Query(default="interactive")):
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
    
    process = subprocess.Popen(attach_cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, env=env, preexec_fn=os.setsid)
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
            except:
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
        except:
            pass
    
    read_task = asyncio.create_task(read_pty())
    write_task = asyncio.create_task(write_pty())
    
    try:
        await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
        for task in [read_task, write_task]:
            task.cancel()
    except:
        pass
    finally:
        try:
            os.close(master_fd)
        except:
            pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except:
            pass


app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    if not shutil.which("tmux"):
        print("ERROR: tmux is required")
        exit(1)
    print(f"Starting Claude Remote on http://0.0.0.0:{DEFAULT_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_PORT)
