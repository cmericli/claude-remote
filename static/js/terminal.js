/* ============================================================
   Claude Remote v2.0 - Terminal Management
   xterm.js terminal with WebSocket connection
   ============================================================ */

CR.terminal = {
    _currentMode: null,
    _resizeObserver: null,

    render(sessionId, mode) {
        mode = mode || 'interactive';
        this._currentMode = mode;

        // Make sure the session header is rendered
        if (CR.conversation._sessionData) {
            CR.conversation._renderSessionHeader(CR.conversation._sessionData);
        } else {
            // Fetch session detail for header
            CR.api.getSession(sessionId).then(function(detail) {
                CR.conversation._sessionData = detail;
                CR.conversation._renderSessionHeader(detail);
            }).catch(function() {});
        }

        this.connect(sessionId, mode);
    },

    connect(sessionId, mode) {
        // Disconnect any existing connection
        this.disconnect();

        this._currentMode = mode;
        CR.setStatus('connecting');

        // Show spectator banner if applicable
        var statusBar = document.getElementById('terminal-status-bar');
        if (statusBar) {
            if (mode === 'spectator') {
                statusBar.textContent = 'Spectator Mode - Read Only';
                statusBar.classList.add('visible');
            } else {
                statusBar.classList.remove('visible');
            }
        }

        // Create terminal instance
        var termContainer = document.getElementById('terminal-container');
        if (!termContainer) return;
        termContainer.innerHTML = '';

        var term = new Terminal({
            cursorBlink: mode !== 'spectator',
            fontSize: 14,
            fontFamily: "'JetBrains Mono', Menlo, Monaco, 'Courier New', monospace",
            theme: {
                background: '#000000',
                foreground: '#ffffff',
                cursor: '#f97316',
                selectionBackground: 'rgba(249, 115, 22, 0.3)'
            },
            scrollback: 10000,
            disableStdin: mode === 'spectator',
            allowProposedApi: true
        });

        var fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.loadAddon(new WebLinksAddon.WebLinksAddon());

        term.open(termContainer);

        // Delay fit to ensure container is sized
        setTimeout(function() {
            try { fitAddon.fit(); } catch (e) {}
        }, 50);

        CR.state.term = term;
        CR.state.fitAddon = fitAddon;

        // WebSocket connection — use multi proxy for remote sessions
        var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        var hostname = CR.state.currentSessionHostname;
        var wsPath;
        if (CR.state.coordinatorMode && hostname && hostname !== CR.state.localHostname) {
            wsPath = '/api/multi/terminal/' + encodeURIComponent(hostname) + '/' + encodeURIComponent(sessionId);
        } else {
            wsPath = '/api/terminal/' + encodeURIComponent(sessionId);
        }
        var wsUrl = protocol + '//' + location.host + wsPath + '?mode=' + mode;
        var ws = new WebSocket(wsUrl);
        ws.binaryType = 'arraybuffer';

        ws.onopen = function() {
            CR.state.isConnected = true;
            CR.setStatus(mode === 'spectator' ? 'spectator' : 'connected');

            if (mode !== 'spectator') {
                term.focus();
                // Send initial resize
                setTimeout(function() {
                    CR.terminal._sendResize();
                }, 100);
            }
        };

        ws.onmessage = function(e) {
            if (term) {
                term.write(new Uint8Array(e.data));
            }
        };

        ws.onclose = function() {
            CR.state.isConnected = false;
            CR.setStatus('stopped');
        };

        ws.onerror = function() {
            CR.state.isConnected = false;
            CR.setStatus('stopped');
        };

        CR.state.ws = ws;

        // Send user input to WebSocket
        if (mode !== 'spectator') {
            term.onData(function(data) {
                if (CR.state.ws && CR.state.ws.readyState === WebSocket.OPEN) {
                    CR.state.ws.send(new TextEncoder().encode(data));
                }
            });
        }

        // Handle resize
        var resizeHandler = function() {
            try {
                if (CR.state.fitAddon) {
                    CR.state.fitAddon.fit();
                }
                if (mode !== 'spectator') {
                    CR.terminal._sendResize();
                }
            } catch (e) {}
        };

        window.addEventListener('resize', resizeHandler);
        this._windowResizeHandler = resizeHandler;

        // Use ResizeObserver for container resize
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
        }
        this._resizeObserver = new ResizeObserver(resizeHandler);
        this._resizeObserver.observe(termContainer);

        // Add tab buttons for mode switching
        this._renderModeButtons(sessionId, mode);
    },

    disconnect() {
        if (CR.state.ws) {
            CR.state.ws.close();
            CR.state.ws = null;
        }
        if (CR.state.term) {
            CR.state.term.dispose();
            CR.state.term = null;
        }
        if (CR.state.fitAddon) {
            CR.state.fitAddon = null;
        }
        if (this._windowResizeHandler) {
            window.removeEventListener('resize', this._windowResizeHandler);
            this._windowResizeHandler = null;
        }
        if (this._resizeObserver) {
            this._resizeObserver.disconnect();
            this._resizeObserver = null;
        }
        CR.state.isConnected = false;
    },

    _sendResize() {
        if (CR.state.ws && CR.state.ws.readyState === WebSocket.OPEN && CR.state.term) {
            try {
                CR.state.ws.send(JSON.stringify({
                    type: 'resize',
                    rows: CR.state.term.rows,
                    cols: CR.state.term.cols
                }));
            } catch (e) {}
        }
    },

    _renderModeButtons(sessionId, currentMode) {
        var statusBar = document.getElementById('terminal-status-bar');
        if (!statusBar) return;

        if (currentMode === 'spectator') {
            statusBar.innerHTML = '<span>Spectator Mode - Read Only</span> ' +
                '<button class="btn btn-success btn-sm" style="margin-left:8px" ' +
                'onclick="CR.terminal.connect(\'' + CR.escapeHtml(sessionId) + '\', \'interactive\')">' +
                'Switch to Interactive</button>';
            statusBar.classList.add('visible');
        } else {
            statusBar.innerHTML = '';
            statusBar.classList.remove('visible');
        }
    }
};
