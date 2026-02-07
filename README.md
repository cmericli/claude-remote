# Claude Remote

**The Mission Control for AI-Augmented Development**

Web-based dashboard for monitoring, searching, and interacting with Claude Code sessions. Access your entire Claude Code universe from any browser — or your phone.

**Repository:** https://github.com/cmericli/claude-remote

## What It Does

You have an AI collaborator generating thousands of tokens across multiple sessions. Claude Remote gives you visibility and control over all of it:

- **Dashboard** — See all sessions at a glance: what's running, what's waiting, what finished
- **Rich Conversations** — Browse session history with markdown, syntax highlighting, collapsible thinking blocks, and tool use visualization
- **Live Streaming** — Real-time SSE updates. Dashboard cards update live. Conversation view appends messages as they arrive
- **Join Session** — One click to jump from reading a conversation to driving the terminal
- **Search** — Full-text search across every conversation you've ever had with Claude
- **Analytics** — Token usage, cost estimation, tool breakdown, session patterns
- **Mobile PWA** — Add to Home Screen on iOS/Android. Push notifications when sessions need input
- **Terminal** — Full xterm.js terminal with interactive and spectator modes

## Quick Start

```bash
cd ~/workspace/claude-remote
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python server.py
```

Then open `http://your-machine:7860` in your browser.

## Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │            Claude Remote Server               │
                    │                                               │
Browser ──────────→ │  FastAPI                                      │
  (xterm.js)        │    ├── WebSocket /terminal/{id}  ←→ tmux     │
  (vanilla JS)      │    ├── REST /api/* (sessions, search, etc.)  │
  (Chart.js)        │    ├── SSE  /api/*/stream (live updates)     │
                    │    └── Push /api/push/* (web push)           │
                    │                                               │
                    │  JSONL Indexer (background)                   │
                    │    ├── Parses ~/.claude/projects/*.jsonl      │
                    │    ├── Indexes into SQLite with FTS5          │
                    │    └── Reindexes every 60 seconds             │
                    │                                               │
                    │  Event System (background)                    │
                    │    ├── JSONL file watcher (stat-polling)      │
                    │    ├── EventBus (async pub/sub)               │
                    │    ├── Needs-input detector (15s interval)    │
                    │    └── Push notification sender               │
                    │                                               │
                    │  Process Monitor                              │
                    │    ├── Detects running Claude processes       │
                    │    └── Platform-adaptive (Linux + macOS)      │
                    │                                               │
                    └──────────────────────────────────────────────┘
                                        │
                                        ▼
                    ┌──────────────────────────────────────────────┐
                    │  Data Layer                                    │
                    │  ~/.claude/projects/**/*.jsonl  (source)      │
                    │  ~/.claude-remote/index.db      (SQLite)      │
                    │  ~/.claude-remote/vapid_keys.json (push keys) │
                    └──────────────────────────────────────────────┘
```

## Features

### Dashboard
- Session cards with live status (running/waiting/stopped)
- Last message preview, token counts, duration
- Real-time updates via Server-Sent Events
- Notification badge for sessions needing input
- Activity feed, quick stats, session history

### Session View
| Tab | What You See |
|-----|-------------|
| **Conversation** | Rich message rendering with markdown, syntax highlighting, thinking blocks, tool use |
| **Terminal** | Full xterm.js terminal (interactive or spectator mode) |
| **Files** | Files read/written/edited during the session |
| **Stats** | Token breakdown, tool usage, cost estimate |

### Join Session
One-click transition from browsing to interacting:

| Session State | Button | What Happens |
|--------------|--------|-------------|
| Running in tmux | Green "Attach" | Connects to existing tmux session |
| Running (no tmux) | Amber "Take Over" | Shows session info for manual takeover |
| Stopped | Blue "Resume" | Creates tmux session with `--resume` |

### Live Streaming (SSE)
- Dashboard cards update in real-time
- Conversation view appends new messages live
- "Needs input" detection (session idle >30s after assistant message)
- Browser notifications (opt-in)
- JSONL file watcher with 500ms event batching

### Search
- Full-text search across all sessions (SQLite FTS5)
- Filter by project, date range
- Results with context snippets
- Click to jump to the conversation

### Analytics
- Token usage over time (daily/weekly charts)
- Breakdown by project and model
- Tool usage distribution
- Cost estimation (Opus/Sonnet/Haiku pricing)
- Cache hit rate

### Mobile (PWA)
- Progressive Web App — installable on iOS/Android
- Service worker with offline caching
- Push notifications via Web Push (VAPID)
- Chat-like mobile conversation view
- Quick action buttons (Continue, Looks good, Stop)

## API Endpoints

### Core
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/dashboard` | GET | Dashboard data (sessions, activity, stats) |
| `/api/sessions` | GET | List sessions with filtering |
| `/api/sessions/{id}` | GET | Session detail with file/tool summaries |
| `/api/sessions/{id}/conversation` | GET | Paginated conversation messages |
| `/api/existing-sessions` | GET | All sessions from disk |

### Session Control
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions` | POST | Create new tmux session |
| `/api/sessions/{id}` | DELETE | Terminate session |
| `/api/sessions/{id}/join` | POST | Join/resume session (creates tmux if needed) |
| `/api/terminal/{id}/inject` | POST | Send text to tmux session |
| `/api/terminal/{id}` | WS | Terminal WebSocket (interactive/spectator) |

### Live Updates
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions/{id}/stream` | GET (SSE) | Per-session event stream |
| `/api/dashboard/stream` | GET (SSE) | Dashboard-wide event stream |
| `/api/needs-input` | GET | Sessions currently needing input |

### Search & Analytics
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search` | GET | Full-text search (?q=, ?project=, ?after=, ?before=) |
| `/api/analytics/tokens` | GET | Token usage (?period=7d, ?group_by=day) |
| `/api/analytics/tools` | GET | Tool usage breakdown |

### Push Notifications
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/push/vapid-key` | GET | VAPID public key for subscription |
| `/api/push/subscribe` | POST | Store push subscription |

### Admin
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reindex` | POST | Force full reindex |

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

This wraps Claude in tmux automatically, making all sessions web-attachable and joinable.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `DEFAULT_PORT` | 7860 | Server port |
| `SESSION_PREFIX` | `claude-remote-` | Prefix for tmux sessions |
| `CLAUDE_BIN` | `~/.local/bin/claude` | Path to Claude binary |
| `REINDEX_INTERVAL` | 60s | How often to re-scan JSONL files |
| `PUSH_RATE_LIMIT_SEC` | 300s | Min interval between pushes per session |
| `PUSH_GLOBAL_LIMIT_HOUR` | 10 | Max push notifications per hour |

## Security

- **Network trust**: No authentication — designed for Tailscale/private networks
- **No cloud**: Everything runs locally. Your data never leaves your network
- **Read-only indexing**: JSONL files are source of truth, never modified
- **VAPID push**: Direct browser push, no Firebase or third-party services

## Files

```
claude-remote/
├── server.py              # FastAPI server (~1036 lines)
├── indexer.py             # JSONL-to-SQLite indexer (~1348 lines)
├── requirements.txt       # Python dependencies
├── static/
│   ├── index.html         # HTML shell with navigation
│   ├── manifest.json      # PWA manifest
│   ├── sw.js              # Service worker (cache + push)
│   ├── css/
│   │   └── styles.css     # Design system
│   ├── js/
│   │   ├── app.js         # State, API, router, SSE, push
│   │   ├── dashboard.js   # Dashboard view
│   │   ├── conversation.js # Conversation renderer + join
│   │   ├── terminal.js    # Terminal (xterm.js)
│   │   ├── search.js      # Search UI
│   │   └── analytics.js   # Analytics charts
│   └── icons/             # PWA icons (72-512px)
├── README.md
├── CHANGELOG.md           # Version history with design rationale
├── PRODUCT_VISION.md      # Product philosophy and design language
└── IMPLEMENTATION_SPEC.md # API contracts and data formats
```

## Dependencies

- Python 3.10+
- tmux
- FastAPI, uvicorn, websockets, watchdog, pywebpush

## Version History

| Version | Date | Codename | What |
|---------|------|----------|------|
| v3.0 | 2026-02-07 | "The Living Dashboard" | Join session, live SSE streaming, PWA + push notifications |
| v2.0 | 2026-02-07 | "Mission Control" | JSONL indexer, rich conversations, search, analytics |
| v0.5 | 2026-02-06 | "The Keyhole" | Session detection, browse history, unified tabs |
| v0.1 | 2026-02-06 | "First Light" | Initial tmux + WebSocket terminal |

See [CHANGELOG.md](CHANGELOG.md) for detailed release notes with design rationale.
