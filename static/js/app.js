/* ============================================================
   Claude Remote v4.0 - Core Application
   State management, API client, router, utilities
   ============================================================ */

window.CR = window.CR || {};

// --------------- State ---------------
CR.state = {
    currentView: 'dashboard',
    currentSessionId: null,
    currentSessionHostname: null,
    currentSessionTab: 'conversation',
    sessions: [],
    dashboardData: null,
    isConnected: false,
    ws: null,
    term: null,
    fitAddon: null,
    refreshInterval: null,
    needsInputSessions: new Set(),
    // Multi-machine
    coordinatorMode: false,
    localHostname: '',
    machines: []
};

// --------------- API Client ---------------
CR.api = {
    async _fetch(url) {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
        return res.json();
    },
    async _post(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: body ? { 'Content-Type': 'application/json' } : {},
            body: body ? JSON.stringify(body) : undefined
        });
        if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
        return res.json();
    },
    async _delete(url) {
        const res = await fetch(url, { method: 'DELETE' });
        if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
        return res.json();
    },

    getDashboard() {
        var prefix = CR.state.coordinatorMode ? '/api/multi' : '/api';
        return this._fetch(prefix + '/dashboard');
    },
    getSessions(params = {}) {
        var prefix = CR.state.coordinatorMode ? '/api/multi' : '/api';
        const q = new URLSearchParams();
        if (params.status) q.set('status', params.status);
        if (params.project) q.set('project', params.project);
        if (params.hostname) q.set('hostname', params.hostname);
        if (params.limit) q.set('limit', params.limit);
        if (params.offset) q.set('offset', params.offset);
        const qs = q.toString();
        return this._fetch(prefix + '/sessions' + (qs ? '?' + qs : ''));
    },
    getSession(id) {
        return this._fetch('/api/sessions/' + encodeURIComponent(id));
    },
    getConversation(id, limit, offset) {
        const q = new URLSearchParams();
        if (limit) q.set('limit', limit);
        if (offset) q.set('offset', offset);
        const qs = q.toString();
        return this._fetch('/api/sessions/' + encodeURIComponent(id) + '/conversation' + (qs ? '?' + qs : ''));
    },
    search(query, filters = {}) {
        var prefix = CR.state.coordinatorMode ? '/api/multi' : '/api';
        const q = new URLSearchParams();
        q.set('q', query);
        if (filters.project) q.set('project', filters.project);
        if (filters.after) q.set('after', filters.after);
        if (filters.before) q.set('before', filters.before);
        if (filters.limit) q.set('limit', filters.limit);
        return this._fetch(prefix + '/search?' + q.toString());
    },
    getTokenAnalytics(period, groupBy) {
        const q = new URLSearchParams();
        if (period) q.set('period', period);
        if (groupBy) q.set('group_by', groupBy);
        return this._fetch('/api/analytics/tokens?' + q.toString());
    },
    getToolAnalytics(period) {
        const q = new URLSearchParams();
        if (period) q.set('period', period);
        return this._fetch('/api/analytics/tools?' + q.toString());
    },
    createSession(opts) {
        const q = new URLSearchParams();
        if (opts.name) q.set('name', opts.name);
        if (opts.working_dir) q.set('working_dir', opts.working_dir);
        if (opts.resume_id) q.set('resume_id', opts.resume_id);
        q.set('rows', '36');
        q.set('cols', '120');
        return this._post('/api/sessions?' + q.toString());
    },
    deleteSession(id) {
        return this._delete('/api/sessions/' + encodeURIComponent(id));
    },
    reindex() {
        return this._post('/api/reindex');
    },
    joinSession(sessionId, hostname) {
        if (CR.state.coordinatorMode && hostname && hostname !== CR.state.localHostname) {
            return this._post('/api/multi/sessions/' + encodeURIComponent(hostname) + '/' + encodeURIComponent(sessionId) + '/join');
        }
        return this._post('/api/sessions/' + encodeURIComponent(sessionId) + '/join');
    },
    injectTerminal(sessionId, text, hostname) {
        if (CR.state.coordinatorMode && hostname && hostname !== CR.state.localHostname) {
            return this._post('/api/multi/terminal/' + encodeURIComponent(hostname) + '/' + encodeURIComponent(sessionId) + '/inject', { text: text });
        }
        return this._post('/api/terminal/' + encodeURIComponent(sessionId) + '/inject', { text: text });
    },
    getMachines() {
        return this._fetch('/api/machines');
    }
};

// --------------- Router ---------------
CR.router = {
    init() {
        window.addEventListener('hashchange', () => this.route());
        this.route();
    },
    route() {
        const hash = window.location.hash || '#/';
        const parts = hash.slice(1).split('?');
        const path = parts[0];
        const query = parts[1] ? Object.fromEntries(new URLSearchParams(parts[1])) : {};

        // Parse route
        if (path === '/' || path === '') {
            this._activate('dashboard');
            CR.dashboard.render();
        } else if (path.startsWith('/session/')) {
            const segments = path.split('/');
            // Support both #/session/{id}/{tab} and #/session/{hostname}/{id}/{tab}
            var sessionId, sessionHostname, tab;
            if (segments.length >= 4 && segments[3] && !['conversation','terminal','files','stats'].includes(segments[3])) {
                // Format: /session/{hostname}/{id}/{tab?}
                sessionHostname = segments[2];
                sessionId = segments[3];
                tab = segments[4] || 'conversation';
            } else {
                // Format: /session/{id}/{tab?}
                sessionId = segments[2];
                sessionHostname = CR.state.localHostname || '';
                tab = segments[3] || 'conversation';
            }
            CR.state.currentSessionId = sessionId;
            CR.state.currentSessionHostname = sessionHostname;
            CR.state.currentSessionTab = tab;
            this._activate('session');
            this._activateSessionTab(tab);
            // Render based on tab
            if (tab === 'conversation') {
                CR.conversation.render(sessionId);
            } else if (tab === 'terminal') {
                CR.terminal.render(sessionId, 'interactive');
            } else if (tab === 'files' || tab === 'stats') {
                CR.conversation.renderSessionDetail(sessionId, tab);
            }
        } else if (path === '/search') {
            this._activate('search');
            CR.search.render(query.q);
        } else if (path === '/analytics') {
            this._activate('analytics');
            CR.analytics.render();
        } else {
            // Fallback to dashboard
            this._activate('dashboard');
            CR.dashboard.render();
        }
    },
    _activate(viewName) {
        CR.state.currentView = viewName;

        // Disconnect terminal if leaving session view
        if (viewName !== 'session' && CR.state.ws) {
            CR.terminal.disconnect();
        }

        // Manage SSE connections
        if (viewName === 'dashboard') {
            CR.sse.connectDashboard();
            CR.sse.disconnectSession();
        } else if (viewName === 'session' && CR.state.currentSessionId) {
            CR.sse.connectSession(CR.state.currentSessionId);
            // Keep dashboard SSE running for badge updates
        } else {
            CR.sse.disconnectSession();
        }

        // Toggle view visibility
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        const el = document.getElementById('view-' + viewName);
        if (el) el.classList.add('active');

        // Update nav links
        document.querySelectorAll('.nav-link').forEach(link => {
            const dv = link.dataset.view;
            link.classList.toggle('active', dv === viewName || (dv === 'dashboard' && viewName === 'session'));
        });
        document.querySelectorAll('.drawer-link').forEach(link => {
            const dv = link.dataset.view;
            link.classList.toggle('active', dv === viewName);
        });

        // Start/stop auto-refresh
        this._manageRefresh(viewName);
    },
    _activateSessionTab(tab) {
        CR.state.currentSessionTab = tab;
        document.querySelectorAll('#session-tabs .tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        document.querySelectorAll('.session-panel').forEach(panel => {
            panel.classList.remove('active');
        });
        const panelId = 'session-' + tab;
        const panel = document.getElementById(panelId);
        if (panel) panel.classList.add('active');
    },
    _manageRefresh(viewName) {
        if (CR.state.refreshInterval) {
            clearInterval(CR.state.refreshInterval);
            CR.state.refreshInterval = null;
        }
        if (viewName === 'dashboard') {
            CR.state.refreshInterval = setInterval(() => {
                CR.dashboard.render(true); // silent refresh
            }, 10000);
        }
    }
};

// --------------- Navigation ---------------
CR.navigate = function(hash) {
    window.location.hash = hash;
};

CR.showView = function(viewName) {
    CR.router._activate(viewName);
};

// --------------- Utilities ---------------
CR.formatTokens = function(n) {
    if (n == null) return '0';
    if (n >= 1000000000) return (n / 1000000000).toFixed(1) + 'B';
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
};

CR.formatCost = function(n) {
    if (n == null) return '$0.00';
    return '$' + Number(n).toFixed(2);
};

CR.formatTime = function(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    let relative;
    if (diffSec < 60) relative = 'just now';
    else if (diffMin < 60) relative = diffMin + 'm ago';
    else if (diffHr < 24) relative = diffHr + 'h ago';
    else if (diffDay < 7) relative = diffDay + 'd ago';
    else relative = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    return '<span title="' + date.toLocaleString() + '">' + relative + '</span>';
};

CR.formatTimeShort = function(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
};

CR.formatDuration = function(minutes) {
    if (minutes == null || minutes <= 0) return '0m';
    if (minutes < 60) return Math.round(minutes) + 'm';
    var h = Math.floor(minutes / 60);
    var m = Math.round(minutes % 60);
    return h + 'h' + (m > 0 ? ' ' + m + 'm' : '');
};

CR.escapeHtml = function(text) {
    if (!text) return '';
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
};

CR.setStatus = function(status, extra) {
    var dot = document.getElementById('statusDot');
    var text = document.getElementById('statusText');
    var meta = document.getElementById('statusMeta');
    if (dot) {
        dot.className = 'status-dot';
        if (status) dot.classList.add(status);
    }
    var labels = {
        connected: 'Connected',
        spectator: 'Spectator Mode',
        connecting: 'Connecting...',
        stopped: 'Disconnected',
        '': 'Ready'
    };
    if (text) text.textContent = labels[status] || status || 'Ready';
    if (meta) meta.textContent = extra || '';
};

CR.getToolIcon = function(toolName) {
    var icons = {
        Read: '\uD83D\uDCD6', Glob: '\uD83D\uDCD6', Grep: '\uD83D\uDCD6',
        Write: '\uD83D\uDCDD',
        Edit: '\u270F\uFE0F',
        Bash: '\uD83D\uDD28',
        Task: '\uD83D\uDCCB', TodoRead: '\uD83D\uDCCB', TodoWrite: '\uD83D\uDCCB'
    };
    return icons[toolName] || '\uD83D\uDD27';
};

CR.projectName = function(dir) {
    if (!dir) return 'unknown';
    var parts = dir.replace(/\/+$/, '').split('/');
    return parts[parts.length - 1] || 'home';
};

// --------------- Modal ---------------
CR.modal = {
    open() {
        document.getElementById('newSessionModal').classList.add('open');
    },
    close() {
        document.getElementById('newSessionModal').classList.remove('open');
    },
    async create() {
        var dir = document.getElementById('modalWorkingDir').value || '~';
        var resumeId = document.getElementById('modalResumeId').value || null;
        try {
            var session = await CR.api.createSession({
                name: CR.projectName(dir),
                working_dir: dir,
                resume_id: resumeId
            });
            CR.modal.close();
            document.getElementById('modalResumeId').value = '';
            CR.navigate('#/session/' + session.id + '/terminal');
        } catch (err) {
            console.error('Failed to create session:', err);
            alert('Failed to create session: ' + err.message);
        }
    }
};

// --------------- SSE (Server-Sent Events) ---------------
CR.sse = {
    _dashboardSource: null,
    _sessionSource: null,
    _reconnectTimeout: null,
    _currentSessionId: null,

    connectDashboard() {
        if (this._dashboardSource) return; // already connected
        try {
            this._dashboardSource = new EventSource('/api/dashboard/stream');
            this._dashboardSource.addEventListener('new_message', function(e) {
                try {
                    var event = JSON.parse(e.data);
                    if (CR.state.currentView === 'dashboard' && CR.dashboard.updateSessionCard) {
                        CR.dashboard.updateSessionCard(event.session_id, event);
                    }
                } catch (err) { console.debug('SSE parse error:', err); }
            });
            this._dashboardSource.addEventListener('needs_input', function(e) {
                try {
                    var event = JSON.parse(e.data);
                    CR.state.needsInputSessions.add(event.session_id);
                    CR.sse._updateBadge();
                    CR.notifications.show('Session needs input', event.session_id.substring(0, 8) + '...', event.session_id);
                } catch (err) { console.debug('SSE parse error:', err); }
            });
            this._dashboardSource.onerror = function() {
                CR.sse._closeDashboard();
                CR.sse._reconnectTimeout = setTimeout(function() {
                    if (CR.state.currentView === 'dashboard' || CR.state.currentView === 'session') {
                        CR.sse.connectDashboard();
                    }
                }, 5000);
            };
        } catch (err) {
            console.warn('SSE dashboard connect failed:', err);
        }
    },

    _closeDashboard() {
        if (this._dashboardSource) {
            this._dashboardSource.close();
            this._dashboardSource = null;
        }
    },

    connectSession(sessionId) {
        if (this._currentSessionId === sessionId && this._sessionSource) return;
        this.disconnectSession();
        this._currentSessionId = sessionId;
        // Clear needs_input for this session since user is viewing it
        CR.state.needsInputSessions.delete(sessionId);
        this._updateBadge();

        try {
            this._sessionSource = new EventSource('/api/sessions/' + encodeURIComponent(sessionId) + '/stream');
            this._sessionSource.addEventListener('new_message', function(e) {
                try {
                    var event = JSON.parse(e.data);
                    if (CR.conversation.appendMessage) {
                        CR.conversation.appendMessage(event);
                    }
                } catch (err) { console.debug('SSE session parse error:', err); }
            });
            this._sessionSource.addEventListener('needs_input', function(e) {
                // User is already viewing this session, no notification needed
            });
            this._sessionSource.onerror = function() {
                CR.sse.disconnectSession();
                setTimeout(function() {
                    if (CR.state.currentView === 'session' && CR.state.currentSessionId === sessionId) {
                        CR.sse.connectSession(sessionId);
                    }
                }, 5000);
            };
        } catch (err) {
            console.warn('SSE session connect failed:', err);
        }
    },

    disconnectSession() {
        if (this._sessionSource) {
            this._sessionSource.close();
            this._sessionSource = null;
        }
        this._currentSessionId = null;
    },

    disconnectAll() {
        this._closeDashboard();
        this.disconnectSession();
        if (this._reconnectTimeout) {
            clearTimeout(this._reconnectTimeout);
            this._reconnectTimeout = null;
        }
    },

    _updateBadge() {
        var badge = document.getElementById('needsInputBadge');
        var count = CR.state.needsInputSessions.size;
        if (badge) {
            badge.textContent = String(count);
            badge.style.display = count > 0 ? 'inline-flex' : 'none';
        }
    }
};

// --------------- Browser Notifications ---------------
CR.notifications = {
    _permitted: false,

    requestPermission() {
        if (!('Notification' in window)) return;
        if (Notification.permission === 'granted') {
            this._permitted = true;
            return;
        }
        if (Notification.permission !== 'denied') {
            Notification.requestPermission().then(function(perm) {
                CR.notifications._permitted = (perm === 'granted');
            });
        }
    },

    show(title, body, sessionId) {
        if (!this._permitted || !('Notification' in window)) return;
        if (document.hasFocus()) return; // Don't notify if window is focused
        try {
            var n = new Notification(title, {
                body: body,
                icon: '/static/icons/icon-192.png',
                tag: 'claude-remote-' + (sessionId || ''),
                renotify: true
            });
            n.onclick = function() {
                window.focus();
                if (sessionId) CR.navigate('#/session/' + sessionId);
                n.close();
            };
        } catch (err) {
            console.debug('Notification error:', err);
        }
    }
};

// --------------- Push Notifications (PWA) ---------------
CR.push = {
    _swRegistration: null,

    registerServiceWorker() {
        if (!('serviceWorker' in navigator)) return;
        navigator.serviceWorker.register('/static/sw.js').then(function(reg) {
            CR.push._swRegistration = reg;
            console.log('Service worker registered');
        }).catch(function(err) {
            console.debug('SW registration failed:', err);
        });
    },

    async subscribe() {
        if (!this._swRegistration) return;
        try {
            // Get VAPID public key from server
            var res = await fetch('/api/push/vapid-key');
            if (!res.ok) return;
            var data = await res.json();
            var vapidKey = data.public_key;
            if (!vapidKey) return;

            // Convert VAPID key
            var key = this._urlBase64ToUint8Array(vapidKey);
            var subscription = await this._swRegistration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: key
            });

            // Send subscription to server
            await fetch('/api/push/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(subscription.toJSON())
            });
            console.log('Push subscription registered');
        } catch (err) {
            console.debug('Push subscribe error:', err);
        }
    },

    _urlBase64ToUint8Array(base64String) {
        var padding = '='.repeat((4 - base64String.length % 4) % 4);
        var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        var raw = window.atob(base64);
        var arr = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) {
            arr[i] = raw.charCodeAt(i);
        }
        return arr;
    }
};

// --------------- Init ---------------
document.addEventListener('DOMContentLoaded', function() {
    // Mobile menu
    var menuBtn = document.getElementById('mobileMenuBtn');
    var overlay = document.getElementById('mobileNavOverlay');
    var drawer = document.getElementById('mobileNavDrawer');

    function toggleMobileMenu() {
        drawer.classList.toggle('open');
        overlay.classList.toggle('open');
    }
    function closeMobileMenu() {
        drawer.classList.remove('open');
        overlay.classList.remove('open');
    }

    if (menuBtn) menuBtn.addEventListener('click', toggleMobileMenu);
    if (overlay) overlay.addEventListener('click', closeMobileMenu);

    // Close mobile menu on nav link click
    document.querySelectorAll('.drawer-link').forEach(function(link) {
        link.addEventListener('click', closeMobileMenu);
    });

    // Session tab clicks
    document.querySelectorAll('#session-tabs .tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var tab = btn.dataset.tab;
            if (CR.state.currentSessionId) {
                CR.navigate('#/session/' + CR.state.currentSessionId + (tab === 'conversation' ? '' : '/' + tab));
            }
        });
    });

    // Modal events
    var modalCancel = document.getElementById('modalCancelBtn');
    var modalCreate = document.getElementById('modalCreateBtn');
    var modalOverlay = document.querySelector('#newSessionModal .modal-overlay');
    if (modalCancel) modalCancel.addEventListener('click', CR.modal.close);
    if (modalCreate) modalCreate.addEventListener('click', CR.modal.create);
    if (modalOverlay) modalOverlay.addEventListener('click', CR.modal.close);

    // Request notification permission
    CR.notifications.requestPermission();

    // Register service worker (web only)
    CR.push.registerServiceWorker();

    // Initialize native push (Capacitor)
    if (CR.nativePush) CR.nativePush.init();

    // Configure native platform (Capacitor)
    if (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()) {
        // Status bar
        try {
            var StatusBar = window.Capacitor.Plugins.StatusBar;
            if (StatusBar) {
                StatusBar.setStyle({ style: 'DARK' });
                StatusBar.setBackgroundColor({ color: '#0a0a0f' });
            }
        } catch (e) {}
        // Keyboard
        try {
            var Keyboard = window.Capacitor.Plugins.Keyboard;
            if (Keyboard) {
                Keyboard.setAccessoryBarVisible({ isVisible: true });
                Keyboard.setScroll({ isDisabled: false });
            }
        } catch (e) {}
    }

    // Detect coordinator mode and initialize machine status
    CR.api.getMachines().then(function(data) {
        CR.state.coordinatorMode = data.coordinator || false;
        CR.state.machines = data.machines || [];
        // Find local hostname
        for (var i = 0; i < CR.state.machines.length; i++) {
            if (!CR.state.machines[i].url) {
                CR.state.localHostname = CR.state.machines[i].hostname;
                break;
            }
        }
        if (CR.state.coordinatorMode) {
            CR.fleet.renderMachineStatus();
        }
    }).catch(function() {
        // Not available or not coordinator — no-op
    });

    // Start router (which will also connect SSE)
    CR.router.init();
});

// --------------- Fleet (Multi-Machine UI) ---------------
CR.fleet = {
    renderMachineStatus() {
        var container = document.getElementById('machineStatus');
        if (!container || !CR.state.coordinatorMode) return;

        var html = '';
        for (var i = 0; i < CR.state.machines.length; i++) {
            var m = CR.state.machines[i];
            var statusClass = m.status === 'ok' ? 'running' : 'stopped';
            var name = m.hostname || m.label || 'unknown';
            html += '<div class="machine-indicator" title="' + CR.escapeHtml(m.label || name) + '">';
            html += '<span class="status-dot ' + statusClass + '"></span>';
            html += '<span class="machine-name">' + CR.escapeHtml(name) + '</span>';
            html += '</div>';
        }
        container.innerHTML = html;
        container.style.display = '';
    },

    refresh() {
        CR.api.getMachines().then(function(data) {
            CR.state.machines = data.machines || [];
            CR.fleet.renderMachineStatus();
        }).catch(function() {});
    }
};

// --------------- Haptic Feedback (Native) ---------------
CR.haptic = function(style) {
    if (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()) {
        try {
            var Haptics = window.Capacitor.Plugins.Haptics;
            if (Haptics) {
                Haptics.impact({ style: style || 'MEDIUM' });
            }
        } catch (e) {}
    }
};

// Helper: build session URL with optional hostname
CR.sessionUrl = function(sessionId, hostname, tab) {
    var path = '#/session/';
    if (CR.state.coordinatorMode && hostname && hostname !== CR.state.localHostname) {
        path += encodeURIComponent(hostname) + '/';
    }
    path += encodeURIComponent(sessionId);
    if (tab && tab !== 'conversation') {
        path += '/' + tab;
    }
    return path;
};
