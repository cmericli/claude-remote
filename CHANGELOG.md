# Claude Remote Changelog

---

## v3.0 — "The Living Dashboard"

*February 7, 2026*

### The Inner Voice

Here's what I kept thinking about while building v2.0: you built this beautiful dashboard — rich conversations, syntax-highlighted code, collapsible thinking blocks, analytics charts — and it's **dead**. It's a museum. You walk in, you look at the exhibits, you walk out. The exhibits don't change while you're standing there. They don't tap you on the shoulder when something interesting happens.

That's absurd. You have an AI that's *actively working*, generating tokens, calling tools, writing code, sometimes getting stuck and waiting for you — and your window into that work refreshes on a **ten-second poll**. That's not awareness. That's checking your mailbox every ten minutes and hoping something arrived.

v3.0 fixes the fundamental architectural lie of v2.0: that a dashboard can be passive and still be useful. It can't. A dashboard that doesn't push is just a webpage you have to remember to visit. Three changes, each one unlocking the next:

**Join Session** — because the gap between "I'm reading this conversation" and "I want to jump in" should be exactly one click, not a context switch to a terminal where you manually type a resume command. You're reading a session, you see it's stuck, you click "Resume" and you're in the terminal driving it. Or it's already running in tmux and you click "Attach" and you're watching it live. The distance between observation and action collapses to zero.

**Live Streaming** — because Server-Sent Events exist and we should have been using them from day one. The dashboard cards update in real-time. The conversation view appends messages as they arrive. A red badge pulses on the nav when a session needs your input. Browser notifications pop up on your desktop. You don't check on your AI. Your AI tells you when it needs you. That's the correct power dynamic.

**Native Mobile** — because a Progressive Web App on your iPhone home screen, with push notifications, is the difference between "I should check on that session" and *your phone buzzing and you glancing at it and knowing in two seconds whether to act or ignore*. That's the killer feature. Not the pretty conversation renderer. Not the analytics charts. The vibration in your pocket that says "your AI needs you."

### What Changed

#### Phase A: Join Session

The shortest path from looking to doing.

- **`POST /api/sessions/{id}/join`** — One endpoint that does the right thing. Session stopped? Creates a tmux session with `--resume`. Already in tmux? Returns the existing session for attachment. Not in tmux but running? Returns info so you can take over. The backend figures it out so the frontend doesn't have to.

- **`POST /api/terminal/{id}/inject`** — The endpoint that `conversation.js` line 468 was already calling but that *didn't exist*. A ghost API. Now it's real: sends keystrokes to the tmux session via `tmux send-keys`. This is what makes the quick action buttons (Continue, Looks good, Stop) actually work.

- **Join button in session header** — Context-aware. Green "Attach" when you can connect to a running tmux session. Amber "Take Over" when it's running outside tmux. Blue "Resume" when it's stopped. One button, three behaviors, zero ambiguity.

- **`find_tmux_for_session()` helper** — Iterates tmux sessions, checks each one's process tree for `--resume {session_id}` in the command line. If your session is already in tmux, we find it. If it's not, we know that too.

#### Phase B: Live Session Streaming

The dashboard wakes up.

- **EventBus** — Async pub/sub built on `asyncio.Queue`. Topics are session IDs (for per-session streams) and `__global__` (for the dashboard). `subscribe()`, `unsubscribe()`, `publish()`. Clean, simple, no external dependencies.

- **JSONL File Watcher** — Stat-polls every 2 seconds (because we're on Google Drive FUSE and `inotify`/`kqueue` don't work reliably on FUSE mounts — learned that the hard way). Tracks file sizes, reads only new bytes when a file grows, parses the new JSONL lines, and emits events through the EventBus. Batches events with a 500ms window to avoid flooding during rapid tool use.

- **`GET /api/sessions/{id}/stream`** — Server-Sent Events endpoint for per-session streaming. Subscribe, receive `new_message` / `status_change` / `tool_use` events, 30-second keepalive heartbeats. Connection cleanup on client disconnect. Max 5 concurrent SSE connections to prevent accumulation.

- **`GET /api/dashboard/stream`** — SSE for the dashboard. `new_message`, `session_started`, `session_completed`, `needs_input` events across all sessions.

- **Needs-Input Detector** — Background task, runs every 15 seconds. For each active session: if the last message is `role=assistant` and nothing new has been written for 30+ seconds, emit a `needs_input` event. 5-minute cooldown per session to avoid nagging. Clears when new user message detected.

- **`CR.sse` namespace** — Frontend SSE management. `connectDashboard()` / `connectSession(id)` / `disconnectSession()`. EventSource with 5-second auto-reconnect on error. Routes events to `dashboard.updateSessionCard()` or `conversation.appendMessage()`.

- **`CR.notifications` namespace** — Browser Notification API. Opt-in permission request. Shows notifications with session slug and preview text. Click notification to focus the window and navigate to the session. Doesn't fire if the window is already focused.

- **`conversation.appendMessage(event)`** — Appends new messages to the conversation without full re-render. Respects scroll position: if you've scrolled up to read something, it doesn't yank you to the bottom.

- **`dashboard.updateSessionCard()`** — Updates a specific card's preview text, status dot, and timestamp in-place. 2-second orange flash animation so you see what changed. Falls back to full dashboard refresh if the card doesn't exist yet.

- **Notification badge** — Red circle on the "Dashboard" nav link showing count of sessions needing input. Pulses with CSS animation. Because the most important number in the entire UI is "how many things need me right now."

#### Phase C: Native Mobile (PWA + Push)

Your AI in your pocket.

- **`static/manifest.json`** — PWA manifest. `display: standalone`, orange theme color, all icon sizes from 72px to 512px. Add to Home Screen on iOS and it looks like a native app.

- **`static/sw.js`** — Service worker. Cache-first for static assets (HTML, CSS, JS, icons). Network-first for API calls (always fresh data, fall back to cache when offline). Push event handler that shows notifications with session info. Notification click handler that focuses/opens the window and navigates to the right session.

- **App icons** — 8 PNG sizes, programmatically generated. Orange circle with "CR" text. Not beautiful, but functional. Ships now, gets designed later.

- **VAPID key management** — Generated on first run, stored at `~/.claude-remote/vapid_keys.json`. ECDH key pair for Web Push authentication. No external service, no Firebase, no subscription fees. Your server talks directly to the push service.

- **`POST /api/push/subscribe`** — Stores push subscription (endpoint, p256dh key, auth key) in SQLite. `GET /api/push/vapid-key` returns the public key for the frontend subscription flow.

- **Push notification pipeline** — Hooked into the needs-input detector. When a session needs input and there are push subscriptions, sends a Web Push notification. Rate limited: 5-minute cooldown per session, 10 per hour globally. Auto-cleans stale subscriptions on 410 Gone.

- **`CR.push` namespace** — Frontend push subscription flow. Registers service worker, requests notification permission, subscribes to push via PushManager, sends subscription to server. `urlBase64ToUint8Array()` helper for VAPID key conversion.

### Files Changed

| File | Lines | What |
|------|-------|------|
| `server.py` | 457 → ~1036 | +EventBus, +JSONL watcher, +needs-input detector, +SSE endpoints, +join/inject endpoints, +VAPID/push |
| `indexer.py` | 1295 → ~1348 | +push_subscriptions table, +save/get/delete subscription, +get_session_working_dir |
| `static/js/app.js` | 370 → ~594 | +CR.sse, +CR.notifications, +CR.push, +joinSession/injectTerminal API, +SW registration |
| `static/js/conversation.js` | 477 → ~548 | +Join button, +appendMessage(), +_joinSession(), +quick action fix |
| `static/js/dashboard.js` | 289 → ~309 | +updateSessionCard() with flash animation |
| `static/index.html` | 127 → ~135 | +PWA meta tags, +notification badge |
| `static/css/styles.css` | 1125 → ~1152 | +join button styles, +badge styles with pulse |
| `requirements.txt` | 4 → 5 | +pywebpush>=2.0.0 |
| `static/manifest.json` | **NEW** | PWA manifest |
| `static/sw.js` | **NEW** | Service worker (cache + push) |
| `static/icons/*.png` | **NEW** | 8 app icon sizes |

### Bug Fixes

- **Ghost inject endpoint**: `conversation.js` was calling `POST /api/terminal/{id}/inject` which didn't exist. Now it does. Quick action buttons (Continue, Looks good, Stop) actually work.

### Architecture Notes

**Why stat-polling instead of inotify/kqueue for the JSONL watcher?**

Because the JSONL files live on Google Drive, which mounts as a FUSE filesystem. FUSE doesn't reliably propagate filesystem events to inotify or kqueue. We detect FUSE mounts at startup (checking for `/Google` or `/CloudStorage` in the path) and always use stat-polling. 2-second interval is a good balance: fast enough to feel live, slow enough to not burn CPU.

**Why 500ms event batching?**

During rapid tool use, Claude might generate 10-20 JSONL entries per second. Without batching, the SSE stream floods the browser with events faster than the DOM can update. 500ms accumulation window groups rapid-fire events into single batches.

**Why max 5 SSE connections?**

Each SSE connection holds a server-side asyncio.Queue. Without a cap, opening many tabs accumulates memory. 5 is generous for single-user use. Oldest connection gets dropped when the limit is hit.

**Why VAPID instead of Firebase/APNs?**

Web Push with VAPID keys is a W3C standard that works without any third-party service. No Firebase project, no Apple Developer account, no subscription fees, no data leaving your network. Your FastAPI server generates a key pair, the browser subscribes via PushManager, and push goes directly from your server to the browser's push service. It's the "zero configuration" principle from the product vision applied to notifications.

### What's Next

This is the inflection point. v2.0 was a beautiful museum. v3.0 is a living system that reaches out and taps you on the shoulder. The remaining gaps:

- **Multi-machine aggregation** (Layer 5 from the product vision) — each machine running Claude Remote as an agent, a coordinator querying them all over Tailscale
- **Split view** — terminal + conversation side-by-side on desktop
- **HTTPS for iOS PWA** — iOS requires HTTPS for service workers and push; document Tailscale HTTPS cert setup
- **Richer push payloads** — include conversation context in push notifications, not just "needs input"
- **Offline conversation cache** — service worker caches recently viewed conversations for offline reading

---

## v2.0 — "Mission Control"

*February 7, 2026*

### The Inner Voice

v0.5 was a remote terminal. That's it. You could see your Claude session from a browser. Useful? Yes. Sufficient? Not even close.

The JSONL files sitting in `~/.claude/projects/` are one of the richest datasets any developer has ever generated about their own work. Every thought Claude had. Every tool it used. Every token it spent. Every file it touched. Months of AI-augmented development, meticulously logged, completely ignored.

v2.0 builds the infrastructure to actually *use* that data. A JSONL-to-SQLite indexer that parses every session into structured, searchable, queryable records. A rich conversation viewer that renders markdown, highlights code, collapses thinking blocks, and shows tool use timelines. Full-text search across every conversation you've ever had with Claude. Analytics that answer "how much am I spending?" and "what does my AI actually do?"

The terminal is a keyhole. v2.0 opened the door.

### What Shipped

- **JSONL-to-SQLite indexer** (`indexer.py`, 1295 lines) — Parses all session data into structured SQLite with FTS5 full-text search
- **Rich conversation viewer** — Markdown rendering, syntax highlighting, collapsible thinking blocks, tool use visualization
- **Dashboard** — Session cards with status, previews, token counts, activity feed
- **Cross-session search** — Full-text search with project/date filtering
- **Analytics** — Token usage charts, tool breakdown, cost estimation, session patterns
- **Platform-adaptive process detection** — Works on both Linux (`/proc`) and macOS (`ps`/`lsof`)
- **Spectator mode** — Watch sessions read-only without interfering
- **Quick actions** — Continue, Looks good, Stop buttons in conversation view

---

## v0.5 — "The Keyhole"

*February 6, 2026*

The beginning. A FastAPI server that wraps tmux sessions and exposes them via WebSocket to xterm.js in a browser. You can create sessions, attach to them, and watch them. That's it. That's the whole product.

But it proved the concept: you can be on your phone, on the couch, and see what your AI is doing on your workstation. That's worth building on.

- tmux session management (create, list, attach, terminate)
- WebSocket terminal with xterm.js
- Bidirectional PTY bridge
- Session detection (running Claude processes)
- Basic session listing from disk

---

## v0.1 — "First Light"

*February 6, 2026*

Initial implementation. Server starts, terminal works, sessions persist.
