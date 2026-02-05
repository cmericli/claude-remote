# Claude Remote

Web-based terminal access for Claude Code sessions. Access your Claude Code sessions from any browser on your Tailscale network.

## Quick Start

```bash
# Install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run server
python server.py
```

Then open `http://feynman:7860` in your browser.

## Features

- **Web Terminal**: Full xterm.js-based terminal in your browser
- **Session Management**: Create, list, and attach to Claude Code sessions
- **Mobile Friendly**: Responsive UI works on phones
- **Multi-Device**: Access from any device on your Tailscale network

## API

- `GET /` - Web UI
- `GET /api/sessions` - List active sessions
- `POST /api/sessions?name=...&working_dir=...` - Create session
- `DELETE /api/sessions/{id}` - Terminate session
- `WS /api/terminal/{id}` - WebSocket terminal connection

## Architecture

```
Browser (xterm.js) <--WebSocket--> FastAPI <--PTY--> Claude Code
```

## Configuration

Default port: 7860

To change, edit `DEFAULT_PORT` in `server.py` or run:
```bash
uvicorn server:app --host 0.0.0.0 --port 8080
```

## Security

This service trusts your network (designed for Tailscale). No authentication is implemented - anyone on your network can access sessions.
