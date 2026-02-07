#!/usr/bin/env python3
"""
Claude Remote - JSONL-to-SQLite Indexer

Scans ~/.claude/projects/ for session JSONL files and indexes them into
~/.claude-remote/index.db for fast querying by the server.

Supports incremental indexing (skips unchanged files) and full-text search.
"""

import json
import logging
import os
import platform
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("indexer")

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
INDEX_DIR = Path.home() / ".claude-remote"
INDEX_DB = INDEX_DIR / "index.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    slug           TEXT,
    project_dir    TEXT,
    working_dir    TEXT,
    git_branch     TEXT,
    model          TEXT,
    version        TEXT,
    first_message  TEXT,
    last_message   TEXT,
    message_count  INTEGER DEFAULT 0,
    user_msg_count INTEGER DEFAULT 0,
    asst_msg_count INTEGER DEFAULT 0,
    total_input_tokens    INTEGER DEFAULT 0,
    total_output_tokens   INTEGER DEFAULT 0,
    total_cache_read      INTEGER DEFAULT 0,
    total_cache_create    INTEGER DEFAULT 0,
    file_size_bytes       INTEGER DEFAULT 0,
    jsonl_path            TEXT,
    indexed_at            TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    uuid           TEXT PRIMARY KEY,
    session_id     TEXT,
    parent_uuid    TEXT,
    role           TEXT,
    content_text   TEXT,
    model          TEXT,
    input_tokens   INTEGER DEFAULT 0,
    output_tokens  INTEGER DEFAULT 0,
    cache_read     INTEGER DEFAULT 0,
    cache_create   INTEGER DEFAULT 0,
    has_thinking   INTEGER DEFAULT 0,
    thinking_text  TEXT,
    tool_uses_json TEXT,
    timestamp      TEXT,
    seq_num        INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS tool_uses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_use_id    TEXT,
    session_id     TEXT,
    message_uuid   TEXT,
    tool_name      TEXT,
    input_summary  TEXT,
    timestamp      TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS file_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT,
    file_path      TEXT,
    event_type     TEXT,
    timestamp      TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS index_meta (
    jsonl_path     TEXT PRIMARY KEY,
    file_mtime     REAL,
    file_size      INTEGER,
    indexed_at     TEXT
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint       TEXT UNIQUE,
    p256dh_key     TEXT,
    auth_key       TEXT,
    user_agent     TEXT,
    created_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_last ON sessions(last_message DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_dir);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq_num);
CREATE INDEX IF NOT EXISTS idx_tool_uses_session ON tool_uses(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_uses_name ON tool_uses(tool_name);
CREATE INDEX IF NOT EXISTS idx_file_events_session ON file_events(session_id);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content_text,
    thinking_text,
    content='messages',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content_text, thinking_text)
    VALUES (new.rowid, new.content_text, new.thinking_text);
END;
"""

# Tool name -> file event type mapping
TOOL_EVENT_MAP = {
    "Read": "read",
    "Glob": "read",
    "Grep": "read",
    "Write": "create",
    "Edit": "edit",
    "Bash": "bash",
}

# Tool name -> which input field to summarize
TOOL_SUMMARY_MAP = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Bash": "command",
    "Grep": "pattern",
    "Glob": "pattern",
    "Task": "subject",
    "TaskCreate": "subject",
    "TaskUpdate": "description",
}


def _get_db() -> sqlite3.Connection:
    """Get a database connection, creating schema if needed."""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INDEX_DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    # Create tables
    conn.executescript(SCHEMA_SQL)
    # FTS table and trigger - separate because virtual tables can't be in executescript easily
    for stmt in FTS_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # trigger/table may already exist
    conn.commit()
    return conn


def _extract_tool_summary(tool_name: str, tool_input: dict) -> str:
    """Generate a short summary string from tool use input."""
    if not isinstance(tool_input, dict):
        return ""
    field = TOOL_SUMMARY_MAP.get(tool_name)
    if not field:
        # For unknown tools, try common fields
        for f in ("subject", "description", "file_path", "command", "query"):
            if f in tool_input:
                val = str(tool_input[f])
                return val[:80]
        return ""
    val = tool_input.get(field, "")
    if not val:
        # Fallback for TaskUpdate which may use subject or description
        if tool_name in ("Task", "TaskCreate", "TaskUpdate"):
            val = tool_input.get("subject", "") or tool_input.get("description", "")
    val = str(val)
    if tool_name == "Bash":
        return val[:80]
    if tool_name in ("Task", "TaskCreate", "TaskUpdate"):
        return val[:60]
    return val


def _extract_file_path_from_tool(tool_name: str, tool_input: dict) -> Optional[str]:
    """Extract the file path from a tool use for file_events."""
    if not isinstance(tool_input, dict):
        return None
    if tool_name in ("Read", "Write", "Edit"):
        return tool_input.get("file_path")
    if tool_name in ("Glob", "Grep"):
        return tool_input.get("path")
    return None


def _working_dir_from_project_dir(project_dir_name: str) -> str:
    """Convert project directory name back to a path.
    e.g., '-Users-cmericli-workspace' -> '/Users/cmericli/workspace'
    """
    stripped = project_dir_name.lstrip("-")
    return "/" + stripped.replace("-", "/")


def _project_name_from_working_dir(working_dir: str) -> str:
    """Extract project name (last path component) from working_dir."""
    if not working_dir:
        return "unknown"
    return Path(working_dir).name or "unknown"


def estimate_cost(input_tokens: int, output_tokens: int, cache_read: int,
                  cache_create: int, model: str = "claude-opus-4-6") -> float:
    """Estimate cost based on Anthropic pricing."""
    model_lower = (model or "").lower()
    if "opus" in model_lower:
        input_price = 15.0
        output_price = 75.0
        cache_read_price = 1.5
        cache_create_price = 18.75
    elif "sonnet" in model_lower:
        input_price = 3.0
        output_price = 15.0
        cache_read_price = 0.30
        cache_create_price = 3.75
    else:  # haiku or unknown
        input_price = 0.80
        output_price = 4.0
        cache_read_price = 0.08
        cache_create_price = 1.0

    cost = (
        (input_tokens / 1_000_000) * input_price
        + (output_tokens / 1_000_000) * output_price
        + (cache_read / 1_000_000) * cache_read_price
        + (cache_create / 1_000_000) * cache_create_price
    )
    return round(cost, 2)


def index_session(jsonl_path: str, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Index a single session JSONL file into the database.

    Returns dict with counts of what was indexed.
    """
    path = Path(jsonl_path)
    if not path.exists():
        return {"error": f"File not found: {jsonl_path}"}

    close_conn = conn is None
    if conn is None:
        conn = _get_db()

    stat = path.stat()
    session_id = path.stem
    project_dir_name = path.parent.name
    # Derive working_dir from project directory name
    working_dir = _working_dir_from_project_dir(project_dir_name)

    # Clear existing data for this session
    # Note: FTS with external content table will be rebuilt after all indexing
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM tool_uses WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM file_events WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    # Parse the JSONL file
    slug = None
    git_branch = None
    model = None
    version = None
    first_timestamp = None
    last_timestamp = None
    cwd_from_entry = None
    message_count = 0
    user_msg_count = 0
    asst_msg_count = 0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_create = 0
    seq_num = 0

    messages_batch = []
    tool_uses_batch = []
    file_events_batch = []

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(entry, dict):
                    continue

                entry_type = entry.get("type", "")
                timestamp = entry.get("timestamp", "")

                # Extract session-level metadata from any entry that has it
                if not slug and entry.get("slug"):
                    slug = entry["slug"]
                if not git_branch and entry.get("gitBranch"):
                    git_branch = entry["gitBranch"]
                if not version and entry.get("version"):
                    version = entry["version"]
                if not cwd_from_entry and entry.get("cwd"):
                    cwd_from_entry = entry["cwd"]

                # Track timestamps
                if timestamp:
                    if first_timestamp is None or timestamp < first_timestamp:
                        first_timestamp = timestamp
                    if last_timestamp is None or timestamp > last_timestamp:
                        last_timestamp = timestamp

                # Only index user/assistant messages
                if entry_type not in ("user", "assistant"):
                    continue

                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role") or entry_type
                if role not in ("user", "assistant"):
                    continue

                uuid = entry.get("uuid", f"{session_id}-{seq_num}")
                parent_uuid = entry.get("parentUuid")
                msg_model = msg.get("model")
                if msg_model and not model:
                    model = msg_model

                # Extract content
                content = msg.get("content", "")
                content_text = ""
                thinking_text = ""
                tool_uses = []

                if isinstance(content, str):
                    content_text = content
                elif isinstance(content, list):
                    text_parts = []
                    thinking_parts = []
                    for block in content:
                        if not isinstance(block, dict):
                            if isinstance(block, str):
                                text_parts.append(block)
                            continue
                        block_type = block.get("type", "")
                        if block_type == "text":
                            text_parts.append(block.get("text", ""))
                        elif block_type == "thinking":
                            thinking_parts.append(block.get("thinking", ""))
                        elif block_type == "tool_use":
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            tool_id = block.get("id", "")
                            summary = _extract_tool_summary(tool_name, tool_input)
                            tool_uses.append({
                                "id": tool_id,
                                "name": tool_name,
                                "input_summary": summary,
                            })
                            # Record tool_use in batch
                            tool_uses_batch.append((
                                tool_id, session_id, uuid, tool_name,
                                summary, timestamp
                            ))
                            # Record file event if applicable
                            event_type = TOOL_EVENT_MAP.get(tool_name)
                            if event_type:
                                fpath = _extract_file_path_from_tool(tool_name, tool_input)
                                if fpath:
                                    file_events_batch.append((
                                        session_id, fpath, event_type, timestamp
                                    ))
                                elif tool_name == "Bash":
                                    cmd = (tool_input.get("command", "") or "")[:200]
                                    if cmd:
                                        file_events_batch.append((
                                            session_id, cmd, "bash", timestamp
                                        ))
                        elif block_type == "tool_result":
                            # Tool results are in user messages; skip content
                            pass
                    content_text = "\n".join(text_parts)
                    thinking_text = "\n".join(thinking_parts)

                # Extract token usage
                usage = msg.get("usage", {})
                if not isinstance(usage, dict):
                    usage = {}
                input_tokens = usage.get("input_tokens", 0) or 0
                output_tokens = usage.get("output_tokens", 0) or 0
                cache_read = usage.get("cache_read_input_tokens", 0) or 0
                cache_create = usage.get("cache_creation_input_tokens", 0) or 0

                total_input += input_tokens
                total_output += output_tokens
                total_cache_read += cache_read
                total_cache_create += cache_create

                has_thinking = 1 if thinking_text.strip() else 0
                tool_uses_json = json.dumps(
                    [{"name": t["name"], "input_summary": t["input_summary"]} for t in tool_uses]
                ) if tool_uses else None

                messages_batch.append((
                    uuid, session_id, parent_uuid, role, content_text,
                    msg_model or model, input_tokens, output_tokens,
                    cache_read, cache_create, has_thinking, thinking_text or None,
                    tool_uses_json, timestamp, seq_num
                ))

                message_count += 1
                if role == "user":
                    user_msg_count += 1
                elif role == "assistant":
                    asst_msg_count += 1
                seq_num += 1

    except Exception as e:
        logger.error(f"Error parsing {jsonl_path}: {e}")
        return {"error": str(e)}

    # Use cwd from entries if available (more accurate)
    if cwd_from_entry:
        working_dir = cwd_from_entry

    project_name = _project_name_from_working_dir(working_dir)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Insert session
    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (session_id, slug, project_dir, working_dir, git_branch, model, version,
            first_message, last_message, message_count, user_msg_count, asst_msg_count,
            total_input_tokens, total_output_tokens, total_cache_read, total_cache_create,
            file_size_bytes, jsonl_path, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, slug, project_name, working_dir, git_branch, model, version,
         first_timestamp, last_timestamp, message_count, user_msg_count, asst_msg_count,
         total_input, total_output, total_cache_read, total_cache_create,
         stat.st_size, str(path), now_iso)
    )

    # Batch insert messages
    conn.executemany(
        """INSERT OR REPLACE INTO messages
           (uuid, session_id, parent_uuid, role, content_text, model,
            input_tokens, output_tokens, cache_read, cache_create,
            has_thinking, thinking_text, tool_uses_json, timestamp, seq_num)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        messages_batch
    )

    # Batch insert tool_uses
    if tool_uses_batch:
        conn.executemany(
            """INSERT INTO tool_uses
               (tool_use_id, session_id, message_uuid, tool_name, input_summary, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            tool_uses_batch
        )

    # Batch insert file_events
    if file_events_batch:
        conn.executemany(
            """INSERT INTO file_events
               (session_id, file_path, event_type, timestamp)
               VALUES (?, ?, ?, ?)""",
            file_events_batch
        )

    # Update index_meta
    conn.execute(
        """INSERT OR REPLACE INTO index_meta (jsonl_path, file_mtime, file_size, indexed_at)
           VALUES (?, ?, ?, ?)""",
        (str(path), stat.st_mtime, stat.st_size, now_iso)
    )

    conn.commit()

    if close_conn:
        conn.close()

    return {
        "session_id": session_id,
        "messages": message_count,
        "tool_uses": len(tool_uses_batch),
        "file_events": len(file_events_batch),
    }


def reindex_all(force: bool = False) -> dict:
    """Scan all JSONL files and index new or changed ones.

    Args:
        force: If True, reindex all files regardless of mtime/size.

    Returns dict with summary stats.
    """
    t0 = time.time()
    conn = _get_db()

    # Load existing index metadata for incremental checks
    existing_meta = {}
    if not force:
        rows = conn.execute("SELECT jsonl_path, file_mtime, file_size FROM index_meta").fetchall()
        for r in rows:
            existing_meta[r["jsonl_path"]] = (r["file_mtime"], r["file_size"])

    # Find all JSONL files (skip subagents)
    jsonl_files = []
    if CLAUDE_PROJECTS_DIR.exists():
        for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                jsonl_files.append(jsonl_file)

    sessions_indexed = 0
    sessions_skipped = 0
    total_messages = 0

    for jsonl_file in jsonl_files:
        path_str = str(jsonl_file)
        stat = jsonl_file.stat()

        # Incremental: skip if unchanged
        if not force and path_str in existing_meta:
            old_mtime, old_size = existing_meta[path_str]
            if abs(stat.st_mtime - old_mtime) < 0.01 and stat.st_size == old_size:
                sessions_skipped += 1
                continue

        result = index_session(path_str, conn)
        if "error" not in result:
            sessions_indexed += 1
            total_messages += result.get("messages", 0)
        else:
            logger.warning(f"Failed to index {path_str}: {result['error']}")

    # Clean up sessions whose files no longer exist
    all_paths = {str(f) for f in jsonl_files}
    db_paths = conn.execute("SELECT jsonl_path FROM index_meta").fetchall()
    for row in db_paths:
        if row["jsonl_path"] not in all_paths:
            # Find session_id and clean up
            sess = conn.execute(
                "SELECT session_id FROM sessions WHERE jsonl_path = ?",
                (row["jsonl_path"],)
            ).fetchone()
            if sess:
                sid = sess["session_id"]
                conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
                conn.execute("DELETE FROM tool_uses WHERE session_id = ?", (sid,))
                conn.execute("DELETE FROM file_events WHERE session_id = ?", (sid,))
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM index_meta WHERE jsonl_path = ?", (row["jsonl_path"],))

    conn.commit()

    # Rebuild FTS index to ensure consistency with content table
    # This is required because FTS5 with external content tables can get
    # out of sync during bulk delete+reinsert operations
    if sessions_indexed > 0:
        try:
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS rebuild failed: {e}")

    conn.close()

    duration_ms = int((time.time() - t0) * 1000)
    result = {
        "sessions_indexed": sessions_indexed,
        "sessions_skipped": sessions_skipped,
        "messages_indexed": total_messages,
        "duration_ms": duration_ms,
    }
    logger.info(f"Reindex complete: {result}")
    return result


# ─── Query functions used by the server ───────────────────────────────────────


def get_active_session_ids() -> set:
    """Detect running Claude sessions. Works on Linux and macOS."""
    if platform.system() == "Linux":
        return _detect_linux()
    elif platform.system() == "Darwin":
        return _detect_macos()
    return set()


def _detect_linux() -> set:
    """Detect sessions via /proc on Linux."""
    active = set()
    try:
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                cmdline_path = pid_dir / "cmdline"
                cmdline = cmdline_path.read_text().replace("\0", " ")
                if "claude" not in cmdline.lower():
                    continue
                if "--chrome-native-host" in cmdline or "server.py" in cmdline:
                    continue

                cwd = os.readlink(str(pid_dir / "cwd"))
                session_id = _extract_session_id_from_cmdline(cmdline, cwd)
                if session_id:
                    active.add(session_id)
            except (PermissionError, FileNotFoundError, OSError):
                continue
    except Exception:
        pass
    return active


def _detect_macos() -> set:
    """Detect sessions via ps on macOS."""
    active = set()
    try:
        ps_output = subprocess.check_output(["ps", "aux"], text=True, timeout=5)
        for line in ps_output.splitlines():
            if "claude" not in line.lower():
                continue
            if "grep" in line or "server.py" in line:
                continue
            if "--chrome-native-host" in line or "--claude-in-chrome-mcp" in line:
                continue

            # Try to extract session ID from command line
            session_id = _extract_session_id_from_cmdline(line, None)
            if session_id:
                active.add(session_id)
                continue

            # For --continue or plain claude, try to find cwd via lsof
            parts = line.split()
            if len(parts) < 2:
                continue
            pid = parts[1]
            if not pid.isdigit():
                continue

            try:
                lsof_output = subprocess.check_output(
                    ["lsof", "-p", pid, "-Fn"],
                    text=True, timeout=5, stderr=subprocess.DEVNULL
                )
                cwd = None
                for lsof_line in lsof_output.splitlines():
                    if lsof_line.startswith("n") and "/cwd" not in lsof_line:
                        # lsof -Fn shows 'n' prefix for name field
                        pass
                # Fallback: parse the ps command line for path hints
                # or find most recent session
                cwd = _guess_cwd_from_ps_line(line)
                if cwd:
                    session_id = _find_most_recent_session_in_dir(cwd)
                    if session_id:
                        active.add(session_id)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    return active


def _extract_session_id_from_cmdline(cmdline: str, cwd: Optional[str] = None) -> Optional[str]:
    """Extract session ID from a command line string."""
    # Check for --resume UUID
    match = re.search(r"--resume\s+([a-f0-9-]{36})", cmdline)
    if match:
        return match.group(1)
    # Check for --session-id UUID
    match = re.search(r"--session-id\s+([a-f0-9-]{36})", cmdline)
    if match:
        return match.group(1)
    # For --continue or plain claude, use cwd to find most recent
    if cwd:
        return _find_most_recent_session_in_dir(cwd)
    return None


def _guess_cwd_from_ps_line(line: str) -> Optional[str]:
    """Try to guess working directory from ps output line."""
    # Look for common path patterns in the command
    # e.g., "claude --continue /some/path" or just the user's home
    parts = line.split()
    for part in reversed(parts):
        if part.startswith("/") and os.path.isdir(part):
            return part
    return None


def _find_most_recent_session_in_dir(cwd: str) -> Optional[str]:
    """Find the most recently modified session file for a given working directory."""
    project_dir = "-" + cwd.replace("/", "-").lstrip("-")
    projects_path = CLAUDE_PROJECTS_DIR / project_dir
    if not projects_path.exists():
        return None
    sessions = list(projects_path.glob("*.jsonl"))
    if not sessions:
        return None
    sessions.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return sessions[0].stem


def get_tmux_session_ids() -> set:
    """Get set of short IDs for tmux sessions matching our prefix."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return set()
        ids = set()
        for line in result.stdout.strip().splitlines():
            if line.startswith("claude-remote-"):
                ids.add(line.replace("claude-remote-", ""))
        return ids
    except Exception:
        return set()


def get_dashboard_data(active_ids: set, tmux_ids: set) -> dict:
    """Return dashboard data structure per API spec."""
    conn = _get_db()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()

    # Active sessions (running or recently active)
    rows = conn.execute(
        """SELECT * FROM sessions ORDER BY last_message DESC LIMIT 50"""
    ).fetchall()

    active_sessions = []
    for r in rows:
        sid = r["session_id"]
        is_running = sid in active_ids
        is_in_tmux = sid[:8] in tmux_ids
        if not is_running and not is_in_tmux:
            continue
        total_tokens = (r["total_input_tokens"] + r["total_output_tokens"]
                        + r["total_cache_read"] + r["total_cache_create"])
        # Duration in minutes
        duration = 0
        if r["first_message"] and r["last_message"]:
            try:
                t0 = datetime.fromisoformat(r["first_message"].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(r["last_message"].replace("Z", "+00:00"))
                duration = int((t1 - t0).total_seconds() / 60)
            except (ValueError, TypeError):
                pass

        # Get last message preview
        last_msg = conn.execute(
            """SELECT content_text FROM messages
               WHERE session_id = ? AND role = 'assistant' AND content_text != ''
               ORDER BY seq_num DESC LIMIT 1""",
            (sid,)
        ).fetchone()
        preview = ""
        if last_msg and last_msg["content_text"]:
            preview = last_msg["content_text"][:120]

        active_sessions.append({
            "session_id": sid,
            "slug": r["slug"],
            "project": r["project_dir"],
            "working_dir": r["working_dir"],
            "model": r["model"],
            "git_branch": r["git_branch"],
            "is_running": is_running,
            "is_in_tmux": is_in_tmux,
            "last_message": r["last_message"],
            "last_message_preview": preview,
            "message_count": r["message_count"],
            "total_tokens": total_tokens,
            "duration_minutes": duration,
        })

    # Recent activity (last 20 tool uses across all sessions)
    recent_tools = conn.execute(
        """SELECT tu.session_id, tu.tool_name, tu.input_summary, tu.timestamp,
                  s.slug, s.project_dir
           FROM tool_uses tu
           JOIN sessions s ON tu.session_id = s.session_id
           ORDER BY tu.timestamp DESC LIMIT 20"""
    ).fetchall()

    recent_activity = []
    for r in recent_tools:
        recent_activity.append({
            "session_id": r["session_id"],
            "slug": r["slug"],
            "project": r["project_dir"],
            "type": "tool_use",
            "tool_name": r["tool_name"],
            "summary": r["input_summary"],
            "timestamp": r["timestamp"],
        })

    # Stats
    today_row = conn.execute(
        """SELECT COUNT(DISTINCT session_id) as cnt,
                  SUM(total_input_tokens) as inp, SUM(total_output_tokens) as outp,
                  SUM(total_cache_read) as cr, SUM(total_cache_create) as cc,
                  AVG(model) as model
           FROM sessions WHERE last_message >= ?""",
        (today_start,)
    ).fetchone()

    week_row = conn.execute(
        """SELECT COUNT(DISTINCT session_id) as cnt,
                  SUM(total_input_tokens) as inp, SUM(total_output_tokens) as outp,
                  SUM(total_cache_read) as cr, SUM(total_cache_create) as cc
           FROM sessions WHERE last_message >= ?""",
        (week_start,)
    ).fetchone()

    total_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM sessions"
    ).fetchone()

    # Cache hit rate across all sessions
    cache_row = conn.execute(
        """SELECT SUM(total_cache_read) as cr, SUM(total_cache_create) as cc,
                  SUM(total_input_tokens) as inp
           FROM sessions"""
    ).fetchone()

    cache_total = (cache_row["cr"] or 0) + (cache_row["cc"] or 0) + (cache_row["inp"] or 0)
    cache_hit_rate = round((cache_row["cr"] or 0) / cache_total, 2) if cache_total > 0 else 0

    today_cost = estimate_cost(
        today_row["inp"] or 0, today_row["outp"] or 0,
        today_row["cr"] or 0, today_row["cc"] or 0
    )
    week_cost = estimate_cost(
        week_row["inp"] or 0, week_row["outp"] or 0,
        week_row["cr"] or 0, week_row["cc"] or 0
    )

    today_tokens = sum(v or 0 for v in [
        today_row["inp"], today_row["outp"], today_row["cr"], today_row["cc"]
    ])
    week_tokens = sum(v or 0 for v in [
        week_row["inp"], week_row["outp"], week_row["cr"], week_row["cc"]
    ])

    stats = {
        "today_sessions": today_row["cnt"] or 0,
        "today_tokens": today_tokens,
        "today_cost_estimate": today_cost,
        "week_sessions": week_row["cnt"] or 0,
        "week_tokens": week_tokens,
        "week_cost_estimate": week_cost,
        "total_sessions": total_row["cnt"] or 0,
        "cache_hit_rate": cache_hit_rate,
    }

    conn.close()
    return {
        "active_sessions": active_sessions,
        "recent_activity": recent_activity,
        "stats": stats,
    }


def get_sessions(active_ids: set, tmux_ids: set, status: str = "all",
                 project: Optional[str] = None, limit: int = 30,
                 offset: int = 0) -> dict:
    """Get filtered session list per API spec."""
    conn = _get_db()

    where_clauses = []
    params = []

    if project:
        where_clauses.append("project_dir = ?")
        params.append(project)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Get total count
    count_row = conn.execute(
        f"SELECT COUNT(*) as cnt FROM sessions {where_sql}", params
    ).fetchone()
    total = count_row["cnt"]

    # Get sessions
    rows = conn.execute(
        f"""SELECT * FROM sessions {where_sql}
            ORDER BY last_message DESC LIMIT ? OFFSET ?""",
        params + [limit, offset]
    ).fetchall()

    sessions = []
    for r in rows:
        sid = r["session_id"]
        is_running = sid in active_ids
        is_in_tmux = sid[:8] in tmux_ids

        # Apply status filter
        if status == "running" and not is_running:
            continue
        if status == "stopped" and is_running:
            continue

        total_tokens = (r["total_input_tokens"] + r["total_output_tokens"]
                        + r["total_cache_read"] + r["total_cache_create"])
        cost = estimate_cost(
            r["total_input_tokens"], r["total_output_tokens"],
            r["total_cache_read"], r["total_cache_create"],
            r["model"] or ""
        )

        sessions.append({
            "session_id": sid,
            "slug": r["slug"],
            "project": r["project_dir"],
            "working_dir": r["working_dir"],
            "model": r["model"],
            "git_branch": r["git_branch"],
            "first_message": r["first_message"],
            "last_message": r["last_message"],
            "message_count": r["message_count"],
            "user_msg_count": r["user_msg_count"],
            "asst_msg_count": r["asst_msg_count"],
            "total_tokens": total_tokens,
            "cost_estimate": cost,
            "file_size_mb": round(r["file_size_bytes"] / 1024 / 1024, 2),
            "is_running": is_running,
            "is_in_tmux": is_in_tmux,
        })

    conn.close()
    return {
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_session_detail(session_id: str, active_ids: set, tmux_ids: set) -> Optional[dict]:
    """Get full session detail per API spec."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()

    if not row:
        conn.close()
        return None

    is_running = session_id in active_ids
    is_in_tmux = session_id[:8] in tmux_ids
    total_tokens = (row["total_input_tokens"] + row["total_output_tokens"]
                    + row["total_cache_read"] + row["total_cache_create"])
    cost = estimate_cost(
        row["total_input_tokens"], row["total_output_tokens"],
        row["total_cache_read"], row["total_cache_create"],
        row["model"] or ""
    )

    session = {
        "session_id": session_id,
        "slug": row["slug"],
        "project": row["project_dir"],
        "working_dir": row["working_dir"],
        "model": row["model"],
        "git_branch": row["git_branch"],
        "first_message": row["first_message"],
        "last_message": row["last_message"],
        "message_count": row["message_count"],
        "user_msg_count": row["user_msg_count"],
        "asst_msg_count": row["asst_msg_count"],
        "total_tokens": total_tokens,
        "cost_estimate": cost,
        "file_size_mb": round(row["file_size_bytes"] / 1024 / 1024, 2),
        "is_running": is_running,
        "is_in_tmux": is_in_tmux,
    }

    # Files touched
    file_rows = conn.execute(
        """SELECT file_path, event_type, COUNT(*) as cnt
           FROM file_events WHERE session_id = ?
           GROUP BY file_path, event_type
           ORDER BY cnt DESC LIMIT 100""",
        (session_id,)
    ).fetchall()

    files_touched = [
        {"path": r["file_path"], "event_type": r["event_type"], "count": r["cnt"]}
        for r in file_rows
    ]

    # Tool summary
    tool_rows = conn.execute(
        """SELECT tool_name, COUNT(*) as cnt
           FROM tool_uses WHERE session_id = ?
           GROUP BY tool_name ORDER BY cnt DESC""",
        (session_id,)
    ).fetchall()

    tool_summary = {r["tool_name"]: r["cnt"] for r in tool_rows}

    # Token breakdown
    token_breakdown = {
        "input": row["total_input_tokens"],
        "output": row["total_output_tokens"],
        "cache_read": row["total_cache_read"],
        "cache_create": row["total_cache_create"],
    }

    conn.close()
    return {
        "session": session,
        "files_touched": files_touched,
        "tool_summary": tool_summary,
        "token_breakdown": token_breakdown,
    }


def get_conversation(session_id: str, limit: int = 200, offset: int = 0) -> Optional[dict]:
    """Get conversation messages with rich content per API spec."""
    conn = _get_db()

    # Check session exists
    sess = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not sess:
        conn.close()
        return None

    total_row = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?", (session_id,)
    ).fetchone()
    total = total_row["cnt"]

    rows = conn.execute(
        """SELECT * FROM messages WHERE session_id = ?
           ORDER BY seq_num ASC LIMIT ? OFFSET ?""",
        (session_id, limit, offset)
    ).fetchall()

    messages = []
    for r in rows:
        msg = {
            "uuid": r["uuid"],
            "role": r["role"],
            "content_text": r["content_text"],
            "timestamp": r["timestamp"],
            "seq_num": r["seq_num"],
        }
        if r["role"] == "assistant":
            msg["model"] = r["model"]
            msg["output_tokens"] = r["output_tokens"]
            msg["has_thinking"] = bool(r["has_thinking"])
            if r["has_thinking"] and r["thinking_text"]:
                msg["thinking_text"] = r["thinking_text"]
            if r["tool_uses_json"]:
                try:
                    tool_uses = json.loads(r["tool_uses_json"])
                    msg["tool_uses"] = [
                        {"name": t["name"], "summary": t["input_summary"]}
                        for t in tool_uses
                    ]
                except json.JSONDecodeError:
                    msg["tool_uses"] = []
        messages.append(msg)

    conn.close()
    return {
        "session_id": session_id,
        "messages": messages,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def search(query: str, project: Optional[str] = None,
           after: Optional[str] = None, before: Optional[str] = None,
           limit: int = 20) -> dict:
    """Full-text search across all sessions per API spec."""
    conn = _get_db()

    # Build FTS query - escape special chars for FTS5
    fts_query = query.replace('"', '""')
    # Use simple prefix matching for better results
    fts_terms = fts_query.split()
    fts_expr = " ".join(f'"{t}"' for t in fts_terms if t)
    if not fts_expr:
        conn.close()
        return {"query": query, "results": [], "total": 0}

    # Join FTS results with messages and sessions
    sql = """
        SELECT m.uuid, m.session_id, m.role, m.content_text, m.timestamp, m.seq_num,
               s.slug, s.project_dir,
               snippet(messages_fts, 0, '>>>>', '<<<<', '...', 40) as snip
        FROM messages_fts
        JOIN messages m ON messages_fts.rowid = m.rowid
        JOIN sessions s ON m.session_id = s.session_id
        WHERE messages_fts MATCH ?
    """
    params: list[Any] = [fts_expr]

    if project:
        sql += " AND s.project_dir = ?"
        params.append(project)
    if after:
        sql += " AND m.timestamp >= ?"
        params.append(after)
    if before:
        sql += " AND m.timestamp <= ?"
        params.append(before)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning(f"FTS query failed: {e}")
        conn.close()
        return {"query": query, "results": [], "total": 0}

    results = []
    for r in rows:
        snippet = r["snip"] or ""
        # Clean up FTS snippet markers
        snippet = snippet.replace(">>>>", "").replace("<<<<", "")
        results.append({
            "session_id": r["session_id"],
            "slug": r["slug"],
            "project": r["project_dir"],
            "message_uuid": r["uuid"],
            "role": r["role"],
            "snippet": snippet[:200],
            "timestamp": r["timestamp"],
        })

    conn.close()
    return {
        "query": query,
        "results": results,
        "total": len(results),
    }


def get_token_analytics(period: str = "7d", group_by: str = "day") -> dict:
    """Token analytics per API spec."""
    conn = _get_db()
    now = datetime.now(timezone.utc)

    days = 7
    if period == "30d":
        days = 30
    elif period == "90d":
        days = 90

    start = (now - timedelta(days=days)).isoformat()

    if group_by == "project":
        rows = conn.execute(
            """SELECT project_dir as label,
                      SUM(total_input_tokens) as input,
                      SUM(total_output_tokens) as output,
                      SUM(total_cache_read) as cache_read,
                      SUM(total_cache_create) as cache_create,
                      AVG(model) as model
               FROM sessions WHERE last_message >= ?
               GROUP BY project_dir ORDER BY output DESC""",
            (start,)
        ).fetchall()
    else:
        # Group by day - use the date part of last_message
        rows = conn.execute(
            """SELECT SUBSTR(last_message, 1, 10) as label,
                      SUM(total_input_tokens) as input,
                      SUM(total_output_tokens) as output,
                      SUM(total_cache_read) as cache_read,
                      SUM(total_cache_create) as cache_create,
                      AVG(model) as model
               FROM sessions WHERE last_message >= ?
               GROUP BY SUBSTR(last_message, 1, 10) ORDER BY label ASC""",
            (start,)
        ).fetchall()

    data = []
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "cost_estimate": 0}

    for r in rows:
        inp = r["input"] or 0
        outp = r["output"] or 0
        cr = r["cache_read"] or 0
        cc = r["cache_create"] or 0
        cost = estimate_cost(inp, outp, cr, cc)
        data.append({
            "label": r["label"],
            "input": inp,
            "output": outp,
            "cache_read": cr,
            "cache_create": cc,
            "cost_estimate": cost,
        })
        totals["input"] += inp
        totals["output"] += outp
        totals["cache_read"] += cr
        totals["cache_create"] += cc
        totals["cost_estimate"] += cost

    totals["cost_estimate"] = round(totals["cost_estimate"], 2)

    conn.close()
    return {
        "period": period,
        "group_by": group_by,
        "data": data,
        "totals": totals,
    }


def get_tool_analytics(period: str = "7d") -> dict:
    """Tool usage analytics per API spec."""
    conn = _get_db()
    now = datetime.now(timezone.utc)

    days = 7
    if period == "30d":
        days = 30
    elif period == "90d":
        days = 90

    start = (now - timedelta(days=days)).isoformat()

    rows = conn.execute(
        """SELECT tool_name, COUNT(*) as cnt
           FROM tool_uses WHERE timestamp >= ?
           GROUP BY tool_name ORDER BY cnt DESC""",
        (start,)
    ).fetchall()

    total_count = sum(r["cnt"] for r in rows) or 1  # avoid div by zero

    tools = []
    for r in rows:
        tools.append({
            "name": r["tool_name"],
            "count": r["cnt"],
            "percentage": round(r["cnt"] / total_count * 100, 1),
        })

    conn.close()
    return {
        "period": period,
        "tools": tools,
    }


def save_push_subscription(endpoint: str, p256dh: str, auth: str, user_agent: str = "") -> bool:
    """Store a push notification subscription."""
    conn = _get_db()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO push_subscriptions
               (endpoint, p256dh_key, auth_key, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (endpoint, p256dh, auth, user_agent, now_iso)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_push_subscriptions() -> list[dict]:
    """Get all push subscriptions."""
    conn = _get_db()
    rows = conn.execute("SELECT endpoint, p256dh_key, auth_key FROM push_subscriptions").fetchall()
    conn.close()
    return [{"endpoint": r["endpoint"], "p256dh": r["p256dh_key"], "auth": r["auth_key"]} for r in rows]


def delete_push_subscription(endpoint: str):
    """Remove a stale push subscription."""
    conn = _get_db()
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()


def get_session_working_dir(session_id: str) -> Optional[str]:
    """Look up a session's working directory from the index."""
    conn = _get_db()
    row = conn.execute(
        "SELECT working_dir FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    conn.close()
    return row["working_dir"] if row else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = reindex_all()
    print(f"Indexing complete: {json.dumps(result, indent=2)}")
