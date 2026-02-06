# Claude Remote: Product Vision

**The Mission Control for AI-Augmented Development**

---

## I. The Fundamental Problem

You have an AI collaborator that is, by any measure, remarkable. It reads your codebase, writes code, runs tests, debugs failures, and thinks through complex architecture. It works across multiple sessions, on multiple machines, on multiple projects. It generates thousands of tokens per interaction. It maintains rich conversation histories with embedded reasoning.

And you have **zero visibility** into any of it.

Right now, your relationship with Claude Code looks like this:

```
You ─── one terminal window ─── one session ─── on one machine
```

Walk away from that terminal, and the session is gone. Pick up your phone and you're blind. Open your laptop and you have no idea what your other machine's Claude session accomplished overnight. Want to find that conversation from three days ago where you solved the mounting optimization? Good luck scrolling through terminal output that no longer exists.

**The data is there.** Every conversation, every tool call, every thinking block, every file change, every token spent - all meticulously logged in JSONL files across `~/.claude/projects/`. On your machines right now: 119 sessions, 298 MB of rich structured data. It's the complete record of your AI-augmented development practice.

Nobody is looking at it. Nobody can.

## II. The Insight

The terminal is a keyhole. You're peering through it at something vast.

Claude Remote v0.5 widened the keyhole slightly: you can now peek at sessions from a browser. That's necessary but nowhere near sufficient. The question isn't "how do I see my terminal from my phone?" The question is:

> **"How do I stay connected to, aware of, and in control of all my AI development work, from anywhere, at any time?"**

This reframing changes everything. We're not building a remote terminal. We're building the **nervous system** that connects a developer to their fleet of AI sessions.

## III. Product Principles

### 1. Awareness Before Control
The most valuable thing Claude Remote can do is keep you **aware**. What's running? What finished? What needs attention? What happened while you were sleeping? Control (interactive terminal) is important but secondary. Most of the time, you want to **see**, not **type**.

### 2. The Right Interface for the Context
A terminal is perfect when you're at your desk with a keyboard. It's useless on a phone. On a phone, you want a **chat-like conversation view** with status indicators and quick actions. The same data, completely different presentation. Claude Remote must be two products that feel like one.

### 3. Make the Invisible Visible
21 million tokens in a single session. 28 Bash commands. 24 file reads. 21 edits. A `turn_duration` of 282 seconds. This data tells a story: how your AI works, what it costs, where time goes. Surface it. Make it beautiful. Make it useful.

### 4. Progressive Disclosure
The dashboard shows session cards. Click one and you see the conversation. Expand a message and you see the thinking. Click a tool use and you see what happened. Drill into analytics and you see token breakdowns. Never overwhelm. Always invite deeper exploration.

### 5. Zero Configuration
It works on your Tailscale network. No auth to configure. No databases to set up. One `python server.py` and your entire Claude Code universe is visible. The complexity is in what we show you, not in what we ask you to do.

## IV. The Product

### Layer 0: Infrastructure (v0.5 - DONE)
tmux session management, WebSocket terminal, process detection. The plumbing.

### Layer 1: The Dashboard - "What's Happening"
A single screen that answers:
- What sessions are running right now? (across all machines)
- What are they doing? (last message preview, current activity)
- What needs my attention? (waiting for input, completed, errored)
- What happened recently? (activity feed)

### Layer 2: The Session View - "Deep Dive"
Drill into any session and see:
- Rich conversation with markdown rendering, syntax-highlighted code blocks
- Collapsible thinking blocks (Claude's reasoning, toggleable)
- Tool use timeline (what Claude did, visualized)
- Files changed in this session (with diffs)
- Token usage for this session
- Session metadata (project, branch, model, duration)

### Layer 3: The Terminal - "Direct Control"
When you need hands-on:
- Full bidirectional xterm.js terminal (existing)
- Spectator mode (existing)
- **Quick Actions from conversation view** (new) - buttons for "Continue", "Stop", "Approve" that inject text into the terminal
- Split view: terminal + conversation side-by-side (desktop)

### Layer 4: Intelligence - "Understand Your Practice"
Analytics that help you work better:
- Token spending: per session, per project, per day, trending
- Session patterns: duration distribution, time of day, most active projects
- Tool usage: which tools Claude uses most, failure rates
- Cross-session search: find any conversation by content
- Cost estimation: approximate $ based on token counts and model pricing

### Layer 5: Fleet - "Multi-Machine" (Future)
For developers with multiple machines:
- Each machine runs Claude Remote as an agent
- A coordinator aggregates all machines into one view
- Jump to any session on any machine seamlessly

---

## V. Information Architecture

```
Claude Remote
├── Dashboard (home)
│   ├── Status Bar (machines online, active sessions, tokens today)
│   ├── Active Sessions (cards with live status)
│   │   ├── [Running] Session card → click → Session View
│   │   ├── [Waiting] Session card → click → Session View
│   │   └── [Completed] Session card → click → Session View
│   ├── Activity Feed (recent events across all sessions)
│   └── Quick Stats (tokens today, sessions today, active time)
│
├── Session View (per-session deep dive)
│   ├── Header (project, branch, model, status, duration)
│   ├── Conversation Tab
│   │   ├── Message bubbles (user / assistant)
│   │   ├── Thinking blocks (collapsible, dimmed)
│   │   ├── Tool use blocks (collapsible, with results)
│   │   └── System events (compaction, hooks)
│   ├── Terminal Tab (full xterm.js)
│   ├── Files Tab (files touched, with inline diffs)
│   ├── Timeline Tab (chronological activity visualization)
│   └── Stats Tab (tokens, tools, duration breakdown)
│
├── Search (cross-session)
│   ├── Full-text search across all conversations
│   ├── Filter by project, date range, model
│   └── Results with context snippets
│
├── Analytics (aggregate insights)
│   ├── Token Usage (charts: daily, weekly, by project)
│   ├── Session Patterns (heatmap, duration histogram)
│   ├── Tool Usage (bar chart, success rates)
│   └── Project Activity (most active, trends)
│
└── Settings
    ├── Machines (add/remove Tailscale hosts)
    ├── Display (theme, conversation density)
    └── Notifications (session complete, error, etc.)
```

## VI. Screen Designs

### A. Dashboard (Desktop)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ◉ Claude Remote          zapphood ● feynman ●     🔍 Search...    │
│─────────────────────────────────────────────────────────────────────│
│                                                                     │
│  ┌─ Active Sessions ──────────────────────────────────────────────┐ │
│  │                                                                 │ │
│  │  ┌─────────────────────┐  ┌─────────────────────┐             │ │
│  │  │ 🟢 mantis            │  │ 🟡 workspace          │             │ │
│  │  │ zapphood · opus-4-6  │  │ feynman · opus-4-6   │             │ │
│  │  │                      │  │                       │             │ │
│  │  │ "Building LeVO Gen2  │  │ ⏳ Waiting for input  │             │ │
│  │  │  MuJoCo model..."    │  │ "Should I proceed     │             │ │
│  │  │                      │  │  with the refactor?"  │             │ │
│  │  │ ██████░░ 45min       │  │                       │             │ │
│  │  │ 3.2M tokens          │  │ 12min idle            │             │ │
│  │  │                      │  │ 890K tokens           │             │ │
│  │  │ [View] [Attach]      │  │ [View] [Attach]       │             │ │
│  │  └─────────────────────┘  └─────────────────────┘             │ │
│  │                                                                 │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌─ Recent Activity ──────────────────────────────────────────────┐ │
│  │  2:45 AM  mantis · Wrote verification/levo_gen2/build_levo.py  │ │
│  │  2:43 AM  mantis · Ran 162 test assertions (all passed)        │ │
│  │  2:38 AM  mantis · Read 12 URDF files                          │ │
│  │  2:30 AM  workspace · Session paused - waiting for input       │ │
│  │  2:15 AM  mantis · Started new session                         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌─ Today ────────┐  ┌─ This Week ──────┐  ┌─ Projects ─────────┐ │
│  │  5 sessions     │  │  23 sessions      │  │  mantis    87%     │ │
│  │  12.4M tokens   │  │  89.2M tokens     │  │  workspace 11%     │ │
│  │  ~$8.20 est.    │  │  ~$59 est.        │  │  driver     2%     │ │
│  └─────────────────┘  └──────────────────┘  └───────────────────┘ │
│                                                                     │
│─────────────────────────────────────────────────────────────────────│
│  ┌─ Session History ──────────────────────────────────────────────┐ │
│  │  robust-noodling-reef     mantis    2h ago   50.2MB  [Browse]  │ │
│  │  dreamy-jade-orchid       mantis    5h ago   12.1MB  [Browse]  │ │
│  │  calm-silver-fox          workspace 1d ago    3.2MB  [Browse]  │ │
│  │  ...show all 119 sessions                                      │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### B. Session View - Conversation (Desktop)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ← Dashboard    robust-noodling-reef                    🟢 Running  │
│  mantis · main · claude-opus-4-6 · 2h 15min · 21.5M tokens         │
│─────────────────────────────────────────────────────────────────────│
│  [Conversation]  [Terminal]  [Files (7)]  [Timeline]  [Stats]       │
│─────────────────────────────────────────────────────────────────────│
│                                                                     │
│                              ┌──────────────────────────────────┐   │
│                              │ 👤 You              6:46 AM      │   │
│                              │                                  │   │
│                              │ Implement the following plan:    │   │
│                              │ # Plan: Build Verified LeVO...   │   │
│                              │ [expand full message]            │   │
│                              └──────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                   │
│  │ 🤖 Claude                        6:46 AM     │                   │
│  │                                               │                   │
│  │ ▶ Thinking... (click to expand)               │                   │
│  │                                               │                   │
│  │ Hello Çetin! It's Friday, February 6th at     │                   │
│  │ 1:46 AM EST and I'm running on zapphood.      │                   │
│  │                                               │                   │
│  │ Let me dive into implementing this plan.      │                   │
│  │                                               │                   │
│  │ ┌─ 📖 Read ─────────────────────────────────┐ │                   │
│  │ │ verification/fr10v6/fr10v6_standalone.xml  │ │                   │
│  │ └───────────────────────────────────────────┘ │                   │
│  │ ┌─ 📖 Read ─────────────────────────────────┐ │                   │
│  │ │ verification/assembly/build_arm_hand.py    │ │                   │
│  │ └───────────────────────────────────────────┘ │                   │
│  │ ┌─ 🔨 Bash ─────────────────────────────────┐ │                   │
│  │ │ python3 extract_urdf_params.py             │ │                   │
│  │ │ ✅ exit 0 (click to expand output)         │ │                   │
│  │ └───────────────────────────────────────────┘ │                   │
│  │                                               │                   │
│  │ The URDF extraction confirms the following    │                   │
│  │ parameters for the LeVO Gen2...               │                   │
│  │                                               │                   │
│  │ ```python                                     │                   │
│  │ # Build script for LeVO Gen2 base             │                   │
│  │ import mujoco                                 │                   │
│  │ from dm_control import mjcf                   │                   │
│  │ ```                                           │                   │
│  │                                               │                   │
│  └──────────────────────────────────────────────┘                   │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ 💬 Quick: [Continue] [Looks good] [Stop] [Custom message...] │  │
│  └───────────────────────────────────────────────────────────────┘  │
│─────────────────────────────────────────────────────────────────────│
│  🟢 Connected · 21.5M tokens · 2h 15min                            │
└─────────────────────────────────────────────────────────────────────┘
```

### C. Session View - Files Tab (Desktop)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ← Dashboard    robust-noodling-reef                    🟢 Running  │
│─────────────────────────────────────────────────────────────────────│
│  [Conversation]  [Terminal]  [Files (7)]  [Timeline]  [Stats]       │
│─────────────────────────────────────────────────────────────────────│
│                                                                     │
│  Files modified in this session:                                    │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 📝 verification/levo_gen2/build_levo_mujoco.py    +285 -0   │   │
│  │    Created · 285 lines · Python                              │   │
│  │    [View Full] [View Diff]                                   │   │
│  ├──────────────────────────────────────────────────────────────│   │
│  │ 📝 verification/assembly/build_mantis.py          +142 -23  │   │
│  │    Modified · 3 hunks · Python                               │   │
│  │    [View Full] [View Diff]                                   │   │
│  ├──────────────────────────────────────────────────────────────│   │
│  │ 📖 verification/fr10v6/fr10v6_standalone.xml      (read)    │   │
│  │ 📖 verification/ehand6/ehand6_left_collision.xml  (read)    │   │
│  │ 📖 verification/reachability/optimal_mounts.json  (read)    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### D. Dashboard (Mobile)

```
┌───────────────────────┐
│ ◉ Claude Remote  🔍   │
│───────────────────────│
│                       │
│ ┌───────────────────┐ │
│ │ 🟢 mantis          │ │
│ │ zapphood · opus    │ │
│ │ "Building LeVO..." │ │
│ │ 45min · 3.2M tok   │ │
│ │         [Open →]   │ │
│ └───────────────────┘ │
│                       │
│ ┌───────────────────┐ │
│ │ 🟡 workspace       │ │
│ │ feynman · opus     │ │
│ │ ⏳ Waiting...       │ │
│ │ 12min · 890K tok   │ │
│ │         [Open →]   │ │
│ └───────────────────┘ │
│                       │
│ ── Recent ─────────── │
│ 📝 Wrote build_levo   │
│ ✅ 162 tests passed   │
│ 📖 Read 12 URDFs      │
│ ⏸ Waiting for input   │
│                       │
│ ── History ────────── │
│ robust-noodling  2h   │
│ dreamy-jade      5h   │
│ calm-silver      1d   │
│                       │
│───────────────────────│
│ Today: 5 sessions     │
│ 12.4M tokens · ~$8    │
└───────────────────────┘
```

### E. Session View (Mobile) - Chat Mode

This is the killer mobile experience. It looks and feels like iMessage or WhatsApp, because that's the natural metaphor for a conversation with an AI.

```
┌───────────────────────┐
│ ← mantis   🟢 Live    │
│───────────────────────│
│                       │
│       ┌─────────────┐ │
│       │ 👤 Implement │ │
│       │ the plan:    │ │
│       │ Build LeVO...│ │
│       └─────────────┘ │
│                       │
│ ┌──────────────────┐  │
│ │ 🤖               │  │
│ │ ▶ Thinking...    │  │
│ │                  │  │
│ │ Starting the     │  │
│ │ LeVO Gen2 build. │  │
│ │                  │  │
│ │ 📖 Read 3 files  │  │
│ │ 🔨 Ran script ✅  │  │
│ │ 📝 Wrote 2 files │  │
│ │                  │  │
│ │ The model is now │  │
│ │ loading in...    │  │
│ └──────────────────┘  │
│                       │
│ ┌──────────────────┐  │
│ │ 🤖 All 162 tests │  │
│ │ passed. The LeVO │  │
│ │ model is ready.  │  │
│ │ Should I proceed │  │
│ │ with the arm...  │  │
│ └──────────────────┘  │
│                       │
│───────────────────────│
│ [Continue] [Stop]     │
│ [Type a message...  ] │
└───────────────────────┘
```

### F. Analytics View (Desktop)

```
┌─────────────────────────────────────────────────────────────────────┐
│  ◉ Claude Remote          Analytics                                 │
│─────────────────────────────────────────────────────────────────────│
│                                                                     │
│  Token Usage (Last 7 Days)                 Sessions per Day         │
│  ┌────────────────────────────┐           ┌──────────────────────┐  │
│  │         ▄                  │           │     ▄                │  │
│  │    ▄   ██                  │           │  ▄ ▄█▄    ▄          │  │
│  │   ██▄  ██   ▄              │           │  █▄███   ▄█          │  │
│  │  ████▄ ██  ██▄             │           │  █████▄  ██          │  │
│  │  █████ ██  ███  ▄          │           │  ██████▄ ██   ▄      │  │
│  │  █████ ██▄ ████ █          │           │  ███████▄██  ██      │  │
│  │  Mo Tu We Th Fr Sa Su      │           │  Mo Tu We Th Fr Sa   │  │
│  └────────────────────────────┘           └──────────────────────┘  │
│                                                                     │
│  ┌─ By Project ──────────────┐  ┌─ By Tool ────────────────────┐   │
│  │  mantis       ████████ 87%│  │  Read     ████████████  32%  │   │
│  │  workspace    █        11%│  │  Bash     ██████████    28%  │   │
│  │  driver       ░         2%│  │  Edit     ████████      22%  │   │
│  └───────────────────────────┘  │  Write    ████           11% │   │
│                                  │  Grep     ███             8% │   │
│  ┌─ Model Usage ─────────────┐  │  Glob     █               3% │   │
│  │  opus-4-6     ██████  72% │  └──────────────────────────────┘   │
│  │  sonnet-4-5   ████    28% │                                      │
│  └───────────────────────────┘                                      │
│                                                                     │
│  ┌─ Cost Estimate ───────────────────────────────────────────────┐  │
│  │  Today: ~$8.20  │  This Week: ~$59  │  This Month: ~$187     │  │
│  │  Avg/session: ~$1.60  │  Cache hit rate: 89%                 │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## VII. Technical Architecture

### Current (v0.5)
```
Browser ──WebSocket──→ FastAPI ──PTY──→ tmux ──→ Claude Code
                         │
                         └──→ ~/.claude/projects/*.jsonl (read-only)
```

### Target (v2.0)
```
                    ┌──────────────────────────────────────────────┐
                    │            Claude Remote Server              │
                    │                                              │
Browser ──────────→ │  FastAPI                                     │
  (xterm.js)        │    ├── WebSocket /terminal/{id}  ←→ tmux    │
  (React/Solid)     │    ├── REST /api/sessions                   │
  (Chart.js)        │    ├── REST /api/analytics                  │
                    │    ├── SSE  /api/events (live feed)         │
                    │    └── REST /api/search                     │
                    │                                              │
                    │  Session Indexer (background)                │
                    │    ├── Watches ~/.claude/projects/ (inotify) │
                    │    ├── Parses JSONL → structured data        │
                    │    ├── Extracts: messages, tools, tokens     │
                    │    ├── Indexes for full-text search          │
                    │    └── Writes → SQLite cache                 │
                    │                                              │
                    │  Process Monitor (background)                │
                    │    ├── Polls running Claude processes        │
                    │    ├── Detects session state changes         │
                    │    └── Emits events via SSE                  │
                    │                                              │
                    │  Agent Discovery (future)                    │
                    │    ├── Queries other Tailscale hosts         │
                    │    └── Aggregates multi-machine data         │
                    │                                              │
                    └──────────────────────────────────────────────┘
                                        │
                                        ▼
                    ┌──────────────────────────────────────────────┐
                    │  Data Layer                                   │
                    │                                              │
                    │  ~/.claude/projects/**/*.jsonl  (source)     │
                    │  ~/.claude-remote/index.db      (SQLite)     │
                    │  ~/.claude-remote/config.json   (settings)   │
                    │                                              │
                    └──────────────────────────────────────────────┘
```

### Key Architectural Decisions

**1. SQLite as the index, JSONL as the source of truth.**
We never modify the JSONL files. We build a read-only index that accelerates queries. The indexer watches for file changes (inotify/fswatch) and incrementally updates. If the index is lost, rebuild from JSONL. This is the "derived data" pattern - safe, fast, rebuildable.

**2. Server-Sent Events for real-time updates.**
The dashboard needs live updates without polling. SSE is simpler than WebSocket for one-way data flow. Reserve WebSocket for the terminal (which needs bidirectional). The process monitor detects state changes and pushes events.

**3. Single-file frontend initially, then graduate to a build step.**
Start with a single `index.html` that loads libraries from CDN (current approach). This is simple and works. When complexity demands it, introduce a lightweight build (Vite + Solid/Preact). But resist this as long as possible - every build step is friction.

**4. No database server. SQLite only.**
SQLite is perfect for this: single-user, read-heavy, local data. No PostgreSQL, no Redis, no Docker. One file. If the file gets corrupted, delete it and rebuild from JSONL in seconds.

**5. Multi-machine via HTTP API, not shared filesystem.**
Each machine runs its own Claude Remote. Cross-machine aggregation happens by one instance querying others' APIs over Tailscale. No shared state, no distributed systems complexity.

## VIII. Data Model (SQLite Index)

```sql
-- Core session metadata (extracted from JSONL)
CREATE TABLE sessions (
    session_id     TEXT PRIMARY KEY,
    slug           TEXT,
    project_dir    TEXT,
    working_dir    TEXT,
    git_branch     TEXT,
    model          TEXT,
    version        TEXT,
    first_message  TIMESTAMP,
    last_message   TIMESTAMP,
    message_count  INTEGER,
    user_msg_count INTEGER,
    asst_msg_count INTEGER,
    total_input_tokens    INTEGER DEFAULT 0,
    total_output_tokens   INTEGER DEFAULT 0,
    total_cache_read      INTEGER DEFAULT 0,
    total_cache_create    INTEGER DEFAULT 0,
    file_size_bytes       INTEGER,
    is_running            BOOLEAN DEFAULT FALSE,
    is_in_tmux            BOOLEAN DEFAULT FALSE,
    indexed_at            TIMESTAMP
);

-- Individual messages for conversation view and search
CREATE TABLE messages (
    uuid           TEXT PRIMARY KEY,
    session_id     TEXT REFERENCES sessions(session_id),
    parent_uuid    TEXT,
    role           TEXT,  -- 'user', 'assistant', 'system'
    content_text   TEXT,  -- extracted plain text (for display & search)
    content_json   TEXT,  -- full content array as JSON (for rich rendering)
    model          TEXT,
    input_tokens   INTEGER DEFAULT 0,
    output_tokens  INTEGER DEFAULT 0,
    has_thinking   BOOLEAN DEFAULT FALSE,
    thinking_text  TEXT,  -- extracted thinking content
    timestamp      TIMESTAMP,
    seq_num        INTEGER  -- ordering within session
);

-- Tool uses (extracted from assistant message content blocks)
CREATE TABLE tool_uses (
    tool_use_id    TEXT PRIMARY KEY,
    session_id     TEXT REFERENCES sessions(session_id),
    message_uuid   TEXT REFERENCES messages(uuid),
    tool_name      TEXT,  -- 'Read', 'Bash', 'Edit', 'Write', etc.
    input_json     TEXT,  -- tool input parameters
    timestamp      TIMESTAMP
);

-- Files touched (from file-history-snapshot and tool_uses)
CREATE TABLE file_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT REFERENCES sessions(session_id),
    file_path      TEXT,
    event_type     TEXT,  -- 'read', 'write', 'edit', 'create'
    timestamp      TIMESTAMP
);

-- Full-text search index
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content_text,
    thinking_text,
    content='messages',
    content_rowid='rowid'
);

-- Indexes for common queries
CREATE INDEX idx_sessions_last_message ON sessions(last_message DESC);
CREATE INDEX idx_sessions_project ON sessions(project_dir);
CREATE INDEX idx_messages_session ON messages(session_id, seq_num);
CREATE INDEX idx_messages_timestamp ON messages(timestamp);
CREATE INDEX idx_tool_uses_session ON tool_uses(session_id);
CREATE INDEX idx_tool_uses_name ON tool_uses(tool_name);
CREATE INDEX idx_file_events_session ON file_events(session_id);
CREATE INDEX idx_file_events_path ON file_events(file_path);
```

## IX. API Design (v2.0)

```
# Dashboard
GET  /api/dashboard
     → { active_sessions, recent_activity, today_stats, week_stats }

# Sessions
GET  /api/sessions
     → { sessions: [...] }  (with filters: ?status=running&project=mantis)
GET  /api/sessions/:id
     → { session metadata + summary stats }
GET  /api/sessions/:id/conversation
     → { messages: [...] }  (paginated, with thinking/tools inline)
GET  /api/sessions/:id/files
     → { files: [{ path, event_type, timestamp }] }
GET  /api/sessions/:id/stats
     → { tokens: {}, tools: {}, duration, turns }

# Terminal (existing, enhanced)
WS   /api/terminal/:id?mode=interactive|spectator
POST /api/terminal/:id/inject
     → Send text to terminal (for quick actions)

# Search
GET  /api/search?q=mounting+optimization&project=mantis&after=2026-01-01
     → { results: [{ session_id, message_uuid, snippet, timestamp }] }

# Analytics
GET  /api/analytics/tokens?period=7d&group_by=day
GET  /api/analytics/tokens?period=30d&group_by=project
GET  /api/analytics/tools?period=7d
GET  /api/analytics/sessions?period=30d
GET  /api/analytics/cost?period=30d

# Events (real-time)
SSE  /api/events
     → stream of { type: 'session_started|message|completed|error', data }

# Session management (existing, enhanced)
POST /api/sessions
     → Create new tmux session
POST /api/sessions/:id/resume
     → Resume a stopped session in tmux
DELETE /api/sessions/:id
     → Terminate session

# Multi-machine (future)
GET  /api/machines
     → { machines: [{ hostname, status, session_count, last_seen }] }
GET  /api/machines/:hostname/sessions
     → Proxy to remote machine's session list
```

## X. Implementation Phases

### Phase 1: Rich Conversation View (1-2 days)
**Goal**: Transform the conversation browser from raw text dump into a beautiful, readable experience.

- Parse JSONL fully: extract thinking blocks, tool uses, code blocks
- Render markdown in messages (use marked.js)
- Syntax highlight code blocks (use highlight.js)
- Collapsible thinking blocks (dimmed, toggle to expand)
- Collapsible tool use blocks (icon + name, toggle for details)
- Proper message layout (user right-aligned, assistant left-aligned)
- Timestamp display
- Auto-scroll with "jump to bottom" button
- Session metadata header (project, model, branch, duration)

**Why first**: This is the highest-impact, lowest-risk improvement. It transforms the existing browse feature from "technically works" to "genuinely useful." And it's the foundation for the mobile experience.

### Phase 2: SQLite Indexer + Dashboard (2-3 days)
**Goal**: Build the session index and the dashboard that queries it.

- Write the JSONL-to-SQLite indexer (Python, runs on startup + watches for changes)
- Extract all session metadata, message content, tool uses, token counts
- Build the dashboard API endpoints
- Build the dashboard UI: session cards with status, activity feed, quick stats
- Session cards show: project name, slug, model, last message preview, duration, token count
- Activity feed shows: recent tool uses and messages across all sessions
- Quick stats: tokens today, sessions today, estimated cost

**Why second**: The dashboard is the "home screen" - the first thing you see. It requires the index to be fast. Building the indexer unlocks everything else.

### Phase 3: Mobile-Optimized Chat View (1-2 days)
**Goal**: Make the session conversation view work beautifully on phones.

- Responsive layout that switches to full-width chat on narrow screens
- Touch-friendly message bubbles
- Swipe between sessions
- Quick action buttons at bottom ("Continue", "Stop", "Looks good")
- Pull-to-refresh for live sessions
- Condensed tool use display (just icon + name, expandable)

**Why third**: This fulfills the original vision - checking on your AI from your phone. The rich conversation view (Phase 1) provides the content; this phase optimizes the container.

### Phase 4: Full-Text Search (1 day)
**Goal**: Find any conversation across all sessions.

- SQLite FTS5 for full-text search across message content and thinking
- Search UI with filters (project, date range, model)
- Results with context snippets and timestamps
- Click result to jump to that point in the conversation

**Why fourth**: As session count grows, findability becomes critical. This makes the entire history useful, not just recent sessions.

### Phase 5: Analytics (1-2 days)
**Goal**: Understand your AI development patterns.

- Token usage charts (daily, weekly, by project) using Chart.js
- Session pattern visualization (time-of-day heatmap, duration histogram)
- Tool usage breakdown (bar chart with counts)
- Cost estimation based on model pricing
- Cache hit rate (cache_read vs total input)

**Why fifth**: Analytics are "nice to have" but not critical. They become more valuable as data accumulates. By this point we'll have the index and the UI framework to build on.

### Phase 6: Live Session Streaming (1-2 days)
**Goal**: Watch active sessions update in real-time without terminal.

- Server-Sent Events endpoint for live session updates
- Dashboard cards update automatically (new messages, status changes)
- Conversation view streams new messages as they appear
- "Session completed" / "Waiting for input" notifications
- Optional browser notifications (with user opt-in)

**Why sixth**: This is the "magic" that makes it feel alive. But it requires everything else to be working first.

### Phase 7: Multi-Machine Aggregation (2-3 days)
**Goal**: See all machines in one view.

- Each machine runs Claude Remote as a lightweight agent
- Coordinator queries agents over Tailscale HTTP
- Unified dashboard aggregates all machines
- Machine selector in header
- Cross-machine session list with machine badges
- Proxy terminal connections to remote machines

**Why last**: Most complex, requires the full stack to be solid first.

## XI. What Makes This Special

### 1. It's not a terminal emulator - it's a conversation viewer
The terminal is a 1970s metaphor. Claude Code conversations are rich structured data with thinking, tool use, code, and reasoning. We render them as such. Reading a Claude session should feel like reading a beautifully typeset technical conversation, not staring at VT100 escape codes.

### 2. The thinking blocks
No other tool shows you Claude's thinking. We have it in the JSONL data. A single toggle reveals the reasoning behind every response. This is unprecedented transparency into AI decision-making. For review, for learning, for debugging - this is invaluable.

### 3. Session as first-class object
A Claude Code session isn't just a terminal window. It's a unit of work: it has a project, a branch, a model, a token budget, a set of files touched, a conversation history. We treat it as such. You can search across sessions, compare sessions, understand patterns across sessions.

### 4. Cost awareness
Developers have no idea what their AI usage costs. We show it. Not as a scary number, but as useful information: "This session used 21M tokens (~$14). Your cache hit rate is 89%, saving you ~$110." This builds trust and helps make informed decisions about model selection.

### 5. The mobile experience isn't a degraded desktop
On mobile, you don't get a shrunken terminal. You get a purpose-built chat interface that's actually better for reading conversations than the terminal ever was. Quick actions let you guide your AI without typing code. It's a different product for a different context, sharing the same data.

## XII. Design Language

### Colors
```
Background:     #0a0a0f (near-black with slight blue)
Surface:        #141420 (cards, panels)
Surface-raised: #1e1e30 (hover states, active items)
Border:         #2a2a3a (subtle separators)

Primary:        #f97316 (warm amber - the Anthropic/Claude warmth)
Secondary:      #6366f1 (indigo - for links, interactive elements)
Success:        #22c55e (green - running, connected)
Warning:        #eab308 (yellow - waiting, attention needed)
Danger:         #ef4444 (red - errors, stopped)
Info:           #3b82f6 (blue - spectator, informational)

Text-primary:   #f0f0f5 (near-white)
Text-secondary: #8888a0 (muted)
Text-dim:       #555570 (timestamps, metadata)

Code-bg:        #0d1117 (GitHub-dark-like for code blocks)
```

### Typography
```
UI:         Inter (or system -apple-system stack)
Code:       JetBrains Mono (or Menlo/Monaco fallback)
Sizes:      13px body, 12px metadata, 14px headings, 11px badges
```

### Spacing
```
Base unit:  4px
Card padding: 16px
Section gap: 24px
Message gap: 12px
```

### Motion
```
Transitions:    150ms ease-out (hover states, panel slides)
Skeleton:       Shimmer animation for loading states
New message:    Slide up + fade in
Status change:  Pulse on indicator dot
```

## XIII. Technical Requirements

### Server
- Python 3.10+
- FastAPI + uvicorn
- SQLite3 (standard library)
- watchdog (file system monitoring)
- tmux (session management)

### Frontend
- Vanilla JS initially (no build step)
- xterm.js (terminal)
- marked.js (markdown rendering)
- highlight.js (syntax highlighting)
- Chart.js (analytics charts)
- All loaded from CDN

### Performance Targets
- Dashboard load: < 500ms
- Session conversation load: < 1s for 200 messages
- Search: < 200ms for full-text across all sessions
- SQLite index rebuild: < 30s for 300MB of JSONL
- Memory: < 100MB server process
- Terminal latency: < 50ms (WebSocket round-trip)

### Compatibility
- Chrome, Firefox, Safari (latest)
- iOS Safari, Android Chrome (mobile)
- Tailscale network (no public internet)

## XIV. What We're NOT Building

- **An IDE.** We don't edit code. Claude Code does that. We observe and interact.
- **A chat interface that replaces the terminal.** The terminal is the primary interface for active development. We complement it.
- **An authentication system.** Tailscale IS the auth. If you're on the network, you're authorized.
- **A cloud service.** Everything runs locally. Your data never leaves your network.
- **A monitoring/alerting system.** We show you what's happening. We don't page you at 3 AM.

## XV. Success Criteria

1. **The phone check**: You can glance at your phone and know what all your Claude sessions are doing. In under 3 seconds.

2. **The morning review**: You can review everything Claude did overnight in under 5 minutes. With full understanding of what changed and why.

3. **The "where was that" moment**: You can find any past conversation by searching for what you remember about it. In under 10 seconds.

4. **The cost question**: You can answer "how much am I spending on AI?" with actual data. Instantly.

5. **The handoff**: You can walk away from your desk, pick up your phone, and continue guiding your AI session without missing a beat.

---

*This document describes the complete vision. Implementation is phased to deliver value incrementally. Phase 1 (rich conversation view) alone transforms the product from "remote terminal hack" to "something I actually want to use every day."*
