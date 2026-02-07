# Claude Remote v3.0 - Implementation Specification

This is the shared contract between backend and frontend. Both must adhere to these interfaces exactly.

**v3.0 additions:** Join Session, Live SSE Streaming, PWA + Push Notifications.

## 1. File Structure

```
claude-remote/
├── server.py              # FastAPI server (enhanced)
├── indexer.py             # JSONL-to-SQLite indexer module
├── requirements.txt       # Python dependencies
├── static/
│   ├── index.html         # HTML shell with navigation
│   ├── css/
│   │   └── styles.css     # Complete design system
│   └── js/
│       ├── app.js         # State management, API client, router, init
│       ├── dashboard.js   # Dashboard view
│       ├── conversation.js # Conversation renderer
│       ├── terminal.js    # Terminal management (xterm.js)
│       ├── search.js      # Search UI
│       └── analytics.js   # Analytics charts
```

## 2. SQLite Schema

Database location: `~/.claude-remote/index.db`

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    slug           TEXT,
    project_dir    TEXT,
    working_dir    TEXT,
    git_branch     TEXT,
    model          TEXT,
    version        TEXT,
    first_message  TEXT,  -- ISO8601
    last_message   TEXT,  -- ISO8601
    message_count  INTEGER DEFAULT 0,
    user_msg_count INTEGER DEFAULT 0,
    asst_msg_count INTEGER DEFAULT 0,
    total_input_tokens    INTEGER DEFAULT 0,
    total_output_tokens   INTEGER DEFAULT 0,
    total_cache_read      INTEGER DEFAULT 0,
    total_cache_create    INTEGER DEFAULT 0,
    file_size_bytes       INTEGER DEFAULT 0,
    jsonl_path            TEXT,
    indexed_at            TEXT  -- ISO8601
);

CREATE TABLE IF NOT EXISTS messages (
    uuid           TEXT PRIMARY KEY,
    session_id     TEXT,
    parent_uuid    TEXT,
    role           TEXT,  -- 'user', 'assistant', 'system'
    content_text   TEXT,  -- plain text for display & search
    model          TEXT,
    input_tokens   INTEGER DEFAULT 0,
    output_tokens  INTEGER DEFAULT 0,
    cache_read     INTEGER DEFAULT 0,
    cache_create   INTEGER DEFAULT 0,
    has_thinking   INTEGER DEFAULT 0,
    thinking_text  TEXT,
    tool_uses_json TEXT,  -- JSON array of {name, input_summary}
    timestamp      TEXT,  -- ISO8601
    seq_num        INTEGER,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS tool_uses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_use_id    TEXT,
    session_id     TEXT,
    message_uuid   TEXT,
    tool_name      TEXT,
    input_summary  TEXT,  -- short description of what the tool did
    timestamp      TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS file_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT,
    file_path      TEXT,
    event_type     TEXT,  -- 'read', 'write', 'edit', 'bash', 'create'
    timestamp      TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content_text,
    thinking_text,
    content='messages',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content_text, thinking_text)
    VALUES (new.rowid, new.content_text, new.thinking_text);
END;

CREATE INDEX IF NOT EXISTS idx_sessions_last ON sessions(last_message DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_dir);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq_num);
CREATE INDEX IF NOT EXISTS idx_tool_uses_session ON tool_uses(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_uses_name ON tool_uses(tool_name);
CREATE INDEX IF NOT EXISTS idx_file_events_session ON file_events(session_id);
```

## 3. JSONL Data Format Reference

Each line in a session .jsonl file is a JSON object. Key types:

### Entry types:
- `type: "user"` - User message. `message.content` is string or array
- `type: "assistant"` - Assistant message. `message.content` is array of blocks
- `type: "system"` - System event. `subtype: "turn_duration"`, `durationMs: int`
- `type: "progress"` - Hook progress. `data.type: "hook_progress"`
- `type: "file-history-snapshot"` - File backup tracking
- `type: "queue-operation"` - Task queue events

### Common fields on user/assistant entries:
```json
{
  "parentUuid": "uuid|null",
  "sessionId": "uuid",
  "version": "2.1.33",
  "gitBranch": "main",
  "slug": "robust-noodling-reef",
  "cwd": "/path/to/working/dir",
  "type": "user|assistant",
  "uuid": "uuid",
  "timestamp": "2026-02-06T06:46:54.810Z"
}
```

### Assistant message content blocks:
```json
{
  "message": {
    "model": "claude-opus-4-6",
    "role": "assistant",
    "content": [
      {"type": "thinking", "thinking": "reasoning text..."},
      {"type": "text", "text": "visible response text..."},
      {"type": "tool_use", "id": "toolu_xxx", "name": "Read", "input": {"file_path": "/path"}}
    ],
    "stop_reason": "end_turn|tool_use",
    "usage": {
      "input_tokens": 10,
      "output_tokens": 500,
      "cache_read_input_tokens": 15000,
      "cache_creation_input_tokens": 5000
    }
  }
}
```

### User message with tool results:
```json
{
  "message": {
    "role": "user",
    "content": [
      {"type": "tool_result", "tool_use_id": "toolu_xxx", "content": "result text..."}
    ]
  }
}
```

### Tool name → event_type mapping:
- Read, Glob, Grep → "read"
- Write → "create"
- Edit → "edit"
- Bash → "bash"

### Tool input → summary mapping:
- Read: `input.file_path` (just the filename)
- Write: `input.file_path`
- Edit: `input.file_path`
- Bash: `input.command` (first 80 chars)
- Grep: `input.pattern`
- Glob: `input.pattern`
- Task/TaskCreate/TaskUpdate: `input.subject` or `input.description` (first 60 chars)

## 4. API Endpoints

### GET /api/dashboard
Returns dashboard data.
```json
{
  "active_sessions": [
    {
      "session_id": "uuid",
      "slug": "robust-noodling-reef",
      "project": "mantis",
      "working_dir": "/path/to/project",
      "model": "claude-opus-4-6",
      "git_branch": "main",
      "is_running": true,
      "is_in_tmux": true,
      "last_message": "2026-02-06T06:46:54Z",
      "last_message_preview": "Building the LeVO Gen2 model...",
      "message_count": 50,
      "total_tokens": 21500000,
      "duration_minutes": 135
    }
  ],
  "recent_activity": [
    {
      "session_id": "uuid",
      "slug": "robust-noodling-reef",
      "project": "mantis",
      "type": "tool_use",
      "tool_name": "Write",
      "summary": "verification/levo_gen2/build_levo.py",
      "timestamp": "2026-02-06T07:45:00Z"
    }
  ],
  "stats": {
    "today_sessions": 5,
    "today_tokens": 12400000,
    "today_cost_estimate": 8.20,
    "week_sessions": 23,
    "week_tokens": 89200000,
    "week_cost_estimate": 59.00,
    "total_sessions": 119,
    "cache_hit_rate": 0.89
  }
}
```

### GET /api/sessions?status=all|running|stopped&project=name&limit=30&offset=0
List sessions with filtering.
```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "slug": "robust-noodling-reef",
      "project": "mantis",
      "working_dir": "/path",
      "model": "claude-opus-4-6",
      "git_branch": "main",
      "first_message": "2026-02-06T06:46:00Z",
      "last_message": "2026-02-06T08:00:00Z",
      "message_count": 50,
      "user_msg_count": 10,
      "asst_msg_count": 40,
      "total_tokens": 21500000,
      "cost_estimate": 14.20,
      "file_size_mb": 3.1,
      "is_running": true,
      "is_in_tmux": true
    }
  ],
  "total": 119,
  "limit": 30,
  "offset": 0
}
```

### GET /api/sessions/{session_id}
Get full session detail.
```json
{
  "session": { /* same as list item above */ },
  "files_touched": [
    {"path": "/path/to/file.py", "event_type": "edit", "count": 3}
  ],
  "tool_summary": {"Read": 24, "Bash": 28, "Edit": 21, "Write": 4},
  "token_breakdown": {
    "input": 673,
    "output": 14568,
    "cache_read": 19753222,
    "cache_create": 1783255
  }
}
```

### GET /api/sessions/{session_id}/conversation?limit=200&offset=0
Get conversation messages with rich content.
```json
{
  "session_id": "uuid",
  "messages": [
    {
      "uuid": "msg-uuid",
      "role": "user",
      "content_text": "Implement the following plan...",
      "timestamp": "2026-02-06T06:46:54Z",
      "seq_num": 0
    },
    {
      "uuid": "msg-uuid-2",
      "role": "assistant",
      "content_text": "Hello! Let me start building...",
      "thinking_text": "The user wants me to...",
      "has_thinking": true,
      "tool_uses": [
        {"name": "Read", "summary": "fr10v6_standalone.xml"},
        {"name": "Bash", "summary": "python3 extract_urdf_params.py"}
      ],
      "model": "claude-opus-4-6",
      "output_tokens": 1500,
      "timestamp": "2026-02-06T06:47:10Z",
      "seq_num": 1
    }
  ],
  "total": 361,
  "limit": 200,
  "offset": 0
}
```

### GET /api/search?q=text&project=name&after=2026-01-01&before=2026-02-07&limit=20
Full-text search across all sessions.
```json
{
  "query": "mounting optimization",
  "results": [
    {
      "session_id": "uuid",
      "slug": "calm-silver-fox",
      "project": "mantis",
      "message_uuid": "msg-uuid",
      "role": "assistant",
      "snippet": "...the optimal mounting position is 0.98m...",
      "timestamp": "2026-02-05T10:30:00Z"
    }
  ],
  "total": 5
}
```

### GET /api/analytics/tokens?period=7d|30d&group_by=day|project
Token analytics.
```json
{
  "period": "7d",
  "group_by": "day",
  "data": [
    {"label": "2026-02-01", "input": 500, "output": 50000, "cache_read": 5000000, "cache_create": 500000, "cost_estimate": 8.50},
    {"label": "2026-02-02", "input": 300, "output": 40000, "cache_read": 4000000, "cache_create": 400000, "cost_estimate": 6.20}
  ],
  "totals": {"input": 800, "output": 90000, "cache_read": 9000000, "cache_create": 900000, "cost_estimate": 14.70}
}
```

### GET /api/analytics/tools?period=7d
Tool usage analytics.
```json
{
  "period": "7d",
  "tools": [
    {"name": "Read", "count": 245, "percentage": 32.1},
    {"name": "Bash", "count": 210, "percentage": 27.5},
    {"name": "Edit", "count": 168, "percentage": 22.0}
  ]
}
```

### POST /api/sessions (existing - keep as-is)
### DELETE /api/sessions/{id} (existing - keep as-is)
### WS /api/terminal/{id}?mode=interactive|spectator (existing - keep as-is)

### POST /api/reindex
Force a full reindex.
```json
{"status": "ok", "sessions_indexed": 119, "messages_indexed": 8500, "duration_ms": 2500}
```

### POST /api/sessions/{session_id}/join (v3.0)
Join or resume a session. Creates tmux if needed.
```json
// Request: no body required

// Response (session stopped → created new tmux):
{"action": "created", "tmux_session": "claude-remote-abc12", "tmux_id": "abc12"}

// Response (already in tmux → attach):
{"action": "attached", "tmux_session": "claude-remote-abc12", "tmux_id": "abc12"}

// Response (running but not in tmux):
{"action": "running_no_tmux", "message": "Session is running in a terminal outside tmux"}

// 404 if session not found
```

### POST /api/terminal/{session_id}/inject (v3.0)
Send text to a session's tmux terminal (for quick actions).
```json
// Request:
{"text": "yes, continue"}

// Response:
{"status": "ok"}

// 404 if no tmux session found for this session
```

### GET /api/sessions/{session_id}/stream (v3.0 - SSE)
Server-Sent Events stream for a single session.
```
// Event types:
data: {"type": "new_message", "session_id": "uuid", "role": "assistant", "preview": "Let me check...", "timestamp": "..."}
data: {"type": "tool_use", "session_id": "uuid", "tool_name": "Read", "summary": "server.py"}
data: {"type": "status_change", "session_id": "uuid", "status": "completed"}

// 30-second keepalive:
: heartbeat

// Max 5 concurrent SSE connections. Oldest dropped when limit hit.
```

### GET /api/dashboard/stream (v3.0 - SSE)
Server-Sent Events stream for dashboard-wide updates.
```
// Event types:
data: {"type": "new_message", "session_id": "uuid", "preview": "...", "timestamp": "..."}
data: {"type": "session_started", "session_id": "uuid"}
data: {"type": "session_completed", "session_id": "uuid"}
data: {"type": "needs_input", "session_id": "uuid", "slug": "robust-noodling-reef", "last_message_preview": "Should I proceed?"}
```

### GET /api/needs-input (v3.0)
Returns sessions currently waiting for user input.
```json
{
  "sessions": [
    {"session_id": "uuid", "slug": "robust-noodling-reef", "last_message_preview": "Should I proceed?", "idle_seconds": 45}
  ]
}
```

### GET /api/push/vapid-key (v3.0)
Returns VAPID public key for push subscription.
```json
{"vapid_key": "BLxxxxxxx...base64url"}
```

### POST /api/push/subscribe (v3.0)
Store a push notification subscription.
```json
// Request:
{
  "endpoint": "https://fcm.googleapis.com/fcm/send/...",
  "keys": {
    "p256dh": "BNxxxx...",
    "auth": "xxxx..."
  }
}

// Response:
{"status": "ok"}
```

## 4b. SQLite Schema Additions (v3.0)

```sql
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint       TEXT UNIQUE NOT NULL,
    p256dh_key     TEXT NOT NULL,
    auth_key       TEXT NOT NULL,
    user_agent     TEXT,
    created_at     TEXT  -- ISO8601
);
```

## 4c. EventBus Architecture (v3.0)

```python
class EventBus:
    """Async pub/sub for SSE streaming."""
    # Topics: session_id strings for per-session, "__global__" for dashboard
    # subscribe(topic) → asyncio.Queue
    # unsubscribe(topic, queue)
    # publish(topic, event_dict) → fans out to all subscribers

# Background tasks (started in lifespan):
# 1. _periodic_reindex() — every 60s, runs indexer
# 2. _jsonl_watcher() — stat-polls JSONL files every 2s, emits events on change
# 3. _needs_input_detector() — every 15s, checks for stale assistant messages
```

## 4d. JSONL File Watcher (v3.0)

```python
# Watches ~/.claude/projects/ for JSONL file changes
# Uses stat-polling (not inotify/kqueue) for FUSE compatibility
# Tracks file sizes in memory, reads only new bytes
# Parses new JSONL lines, extracts role/preview/tool_name
# Publishes events to EventBus (session-specific + __global__)
# 500ms batch window to avoid flooding during rapid tool use
# Detects FUSE mounts via path heuristic (/Google, /CloudStorage)
```

## 4e. Push Notification Pipeline (v3.0)

```python
# VAPID keys: generated on first run, stored at ~/.claude-remote/vapid_keys.json
# Triggered by needs_input_detector when session idle >30s after assistant message
# Rate limits:
#   - Per session: 5-minute cooldown (PUSH_RATE_LIMIT_SEC = 300)
#   - Global: 10 per hour (PUSH_GLOBAL_LIMIT_HOUR = 10)
# Stale subscriptions auto-cleaned on 410 Gone response
# Uses pywebpush library for Web Push protocol
```

## 5. Frontend Architecture

### Global Namespace
All JS modules attach to `window.CR`:
```javascript
window.CR = {
    state: {},     // app.js
    api: {},       // app.js
    router: {},    // app.js
    dashboard: {}, // dashboard.js
    conversation: {}, // conversation.js
    terminal: {},  // terminal.js
    search: {},    // search.js
    analytics: {}  // analytics.js
};
```

### State (app.js)
```javascript
CR.state = {
    currentView: 'dashboard', // 'dashboard'|'session'|'search'|'analytics'
    currentSessionId: null,
    currentSessionTab: 'conversation', // 'conversation'|'terminal'|'files'|'stats'
    sessions: [],
    dashboardData: null,
    isConnected: false,
    ws: null,
    term: null,
    fitAddon: null,
    needsInputSessions: new Set()  // v3.0: sessions needing user input
};
```

### API Client (app.js)
```javascript
CR.api = {
    getDashboard() → fetch('/api/dashboard'),
    getSessions(params) → fetch('/api/sessions?...'),
    getSession(id) → fetch('/api/sessions/{id}'),
    getConversation(id, limit, offset) → fetch('/api/sessions/{id}/conversation?...'),
    search(q, filters) → fetch('/api/search?...'),
    getTokenAnalytics(period, groupBy) → fetch('/api/analytics/tokens?...'),
    getToolAnalytics(period) → fetch('/api/analytics/tools?...'),
    createSession(opts) → fetch('/api/sessions', POST),
    deleteSession(id) → fetch('/api/sessions/{id}', DELETE),
    reindex() → fetch('/api/reindex', POST),
    joinSession(id) → fetch('/api/sessions/{id}/join', POST),        // v3.0
    injectTerminal(id, text) → fetch('/api/terminal/{id}/inject', POST)  // v3.0
};
```

### SSE Client (app.js, v3.0)
```javascript
CR.sse = {
    _dashboardSource: null,   // EventSource for dashboard stream
    _sessionSource: null,     // EventSource for per-session stream
    _reconnectTimer: null,

    connectDashboard(),       // GET /api/dashboard/stream → routes to dashboard.updateSessionCard()
    connectSession(id),       // GET /api/sessions/{id}/stream → routes to conversation.appendMessage()
    disconnectSession(),      // Close per-session EventSource
    _updateBadge()           // Update needsInputBadge count in nav
};
// Auto-reconnect on error with 5-second delay
// Router calls connectDashboard() on dashboard view, connectSession() on session view
```

### Notifications (app.js, v3.0)
```javascript
CR.notifications = {
    requestPermission(),     // Notification.requestPermission()
    show(title, body, sessionId)  // new Notification() with click → navigate
};
// Only fires if document is not focused
```

### Push Subscription (app.js, v3.0)
```javascript
CR.push = {
    async init(),            // Register SW, subscribe to push, send to server
    _urlBase64ToUint8Array(base64String)  // VAPID key conversion helper
};
// Flow: register SW → get VAPID key → PushManager.subscribe → POST /api/push/subscribe
```

### Router (app.js)
Hash-based routing:
```
#/                    → dashboard
#/session/{id}        → session view (conversation tab)
#/session/{id}/terminal → session view (terminal tab)
#/session/{id}/files  → session view (files tab)
#/session/{id}/stats  → session view (stats tab)
#/search              → search
#/search?q=text       → search with query
#/analytics           → analytics
```

### Script Load Order in HTML
```html
<!-- Libraries (CDN) -->
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css">
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/highlight.min.js"></script>

<!-- App modules (order matters) -->
<script src="/static/js/app.js"></script>
<script src="/static/js/dashboard.js"></script>
<script src="/static/js/conversation.js"></script>
<script src="/static/js/terminal.js"></script>
<script src="/static/js/search.js"></script>
<script src="/static/js/analytics.js"></script>
```

## 6. HTML Element IDs

These are the container elements that each JS module targets:

```html
<!-- Navigation -->
<nav id="mainNav">
    <a href="#/" data-view="dashboard">Dashboard</a>
    <a href="#/search" data-view="search">Search</a>
    <a href="#/analytics" data-view="analytics">Analytics</a>
</nav>

<!-- View containers (only one visible at a time) -->
<div id="view-dashboard" class="view"></div>
<div id="view-session" class="view"></div>
<div id="view-search" class="view"></div>
<div id="view-analytics" class="view"></div>

<!-- Session view sub-containers -->
<!-- Inside #view-session: -->
<div id="session-header"></div>
<div id="session-tabs"></div>
<div id="session-conversation" class="session-panel"></div>
<div id="session-terminal" class="session-panel"></div>
<div id="session-files" class="session-panel"></div>
<div id="session-stats" class="session-panel"></div>

<!-- Terminal container (inside session-terminal) -->
<div id="terminal-container"></div>

<!-- Status bar -->
<div id="statusBar">
    <span id="statusDot" class="status-dot"></span>
    <span id="statusText">Ready</span>
</div>

<!-- Mobile menu toggle -->
<button id="mobileMenuBtn" class="mobile-only">☰</button>

<!-- New session modal -->
<div id="newSessionModal" class="modal"></div>
```

## 7. CSS Design Tokens

```css
:root {
    /* Backgrounds */
    --bg-base: #0a0a0f;
    --bg-surface: #141420;
    --bg-raised: #1e1e30;
    --bg-overlay: rgba(0, 0, 0, 0.6);
    --border: #2a2a3a;

    /* Primary palette */
    --primary: #f97316;        /* warm amber */
    --primary-dim: #c25e10;
    --secondary: #6366f1;      /* indigo */

    /* Status */
    --success: #22c55e;
    --warning: #eab308;
    --danger: #ef4444;
    --info: #3b82f6;

    /* Text */
    --text: #f0f0f5;
    --text-secondary: #8888a0;
    --text-dim: #555570;

    /* Code */
    --code-bg: #0d1117;

    /* Sizing */
    --radius: 8px;
    --radius-sm: 4px;

    /* Transitions */
    --transition: 150ms ease-out;
}
```

## 8. Cost Estimation Formula

Based on Anthropic pricing (approximate, for display purposes):
```python
def estimate_cost(input_tokens, output_tokens, cache_read, cache_create, model="claude-opus-4-6"):
    # Opus pricing per million tokens
    if "opus" in model:
        input_price = 15.0
        output_price = 75.0
        cache_read_price = 1.5   # 90% discount
        cache_create_price = 18.75  # 25% surcharge
    elif "sonnet" in model:
        input_price = 3.0
        output_price = 15.0
        cache_read_price = 0.30
        cache_create_price = 3.75
    else:  # haiku
        input_price = 0.80
        output_price = 4.0
        cache_read_price = 0.08
        cache_create_price = 1.0

    cost = (
        (input_tokens / 1_000_000) * input_price +
        (output_tokens / 1_000_000) * output_price +
        (cache_read / 1_000_000) * cache_read_price +
        (cache_create / 1_000_000) * cache_create_price
    )
    return round(cost, 2)
```

## 9. Responsive Breakpoints

```css
/* Mobile: < 768px - single column, chat-like */
/* Tablet: 768px - 1024px - compact dashboard */
/* Desktop: > 1024px - full layout with sidebar */
```

## 10. Process Detection (Platform-Adaptive)

```python
import platform

def get_active_session_ids():
    """Detect running Claude sessions. Works on Linux and macOS."""
    if platform.system() == 'Linux':
        return _detect_linux()  # /proc based
    elif platform.system() == 'Darwin':
        return _detect_macos()  # ps + lsof based
    return set()

def _detect_linux():
    # Parse /proc/{pid}/cmdline for --resume UUID or --session-id UUID
    # For --continue, read /proc/{pid}/cwd and find most recent session
    pass

def _detect_macos():
    # Use: ps aux | grep claude
    # Parse command line args directly from ps output
    # Use lsof -p PID to get cwd
    pass
```
