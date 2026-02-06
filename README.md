# Claude Remote

Web-based terminal access for Claude Code sessions. Access your Claude Code sessions from any browser on your network.

**Repository:** https://github.com/cmericli/claude-remote

## Features

- **Web Terminal**: Full xterm.js-based terminal in your browser
- **Session Management**: Create, list, and attach to Claude Code sessions
- **tmux-based**: Sessions persist independently, attachable from anywhere
- **Spectator Mode**: Watch sessions read-only without interfering
- **Conversation Browser**: Read past session history without resuming
- **Session Detection**: Automatically detects running Claude sessions
- **Mobile Friendly**: Responsive UI works on phones

## Quick Start

```bash
# On your server (e.g., feynman)
cd ~/workspace/claude-remote
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python server.py
```

Then open `http://feynman:7860` in your browser.

## Architecture

```
Browser (xterm.js) <--WebSocket--> FastAPI <--PTY--> tmux <---> Claude Code
```

### Session Types

| Type | Badge | Description | Actions |
|------|-------|-------------|---------|
| tmux | 🟢 green | Session started via web UI or with tmux wrapper | View, Attach |
| terminal | 🟣 purple | Running in regular terminal (not tmux) | Browse, Take Over |
| stopped | - | Not currently running | Browse, Resume |

### Tabs

- **Active**: All currently running sessions (tmux + terminal)
- **History**: Stopped sessions from disk (past conversations)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/sessions` | GET | List active tmux sessions |
| `/api/sessions` | POST | Create new session (`name`, `working_dir`, `resume_id`) |
| `/api/sessions/{id}` | DELETE | Terminate session |
| `/api/existing-sessions` | GET | List all sessions from disk |
| `/api/sessions/{id}/history` | GET | Get conversation transcript |
| `/api/terminal/{id}?mode=` | WS | Terminal WebSocket (`interactive` or `spectator`) |

## Session Detection

The server detects running Claude sessions by:
1. Parsing `/proc/{pid}/cmdline` for `--resume {uuid}` or `--session-id {uuid}`
2. For `--continue` or plain `claude`, finding the most recent session in that working directory
3. Matching against `.jsonl` files in `~/.claude/projects/`

## Making All Sessions tmux-based

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
claude() {
    if [[ -n "$TMUX" ]]; then
        ~/.local/bin/claude "$@"
        return
    fi
    local session_name="claude-remote-$(date +%s | tail -c 5)"
    tmux new-session -s "$session_name" "~/.local/bin/claude $*"
}
```

This wraps Claude in tmux automatically, making all sessions web-attachable.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `DEFAULT_PORT` | 7860 | Server port |
| `SESSION_PREFIX` | `claude-remote-` | Prefix for tmux sessions |
| `CLAUDE_BIN` | `~/.local/bin/claude` | Path to Claude binary |

## Security

- **Network trust**: No authentication - designed for Tailscale/private networks
- **Read-only mode**: Spectator mode prevents accidental input
- Sessions are isolated per tmux session

## Files

```
~/workspace/claude-remote/
├── server.py           # FastAPI server with tmux/PTY management
├── static/index.html   # Web UI (xterm.js)
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## Dependencies

- Python 3.10+
- tmux
- FastAPI, uvicorn, websockets

## Future Ideas

- [ ] Auto-start (systemd service)
- [ ] Multi-machine dashboard (query all Tailscale hosts)
- [ ] Session naming/labeling
- [ ] Notifications when session needs attention
- [ ] Authentication option for non-private networks
