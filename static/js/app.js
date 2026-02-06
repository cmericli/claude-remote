/* ============================================================
   Claude Remote v2.0 - Core Application
   State management, API client, router, utilities
   ============================================================ */

window.CR = window.CR || {};

// --------------- State ---------------
CR.state = {
    currentView: 'dashboard',
    currentSessionId: null,
    currentSessionTab: 'conversation',
    sessions: [],
    dashboardData: null,
    isConnected: false,
    ws: null,
    term: null,
    fitAddon: null,
    refreshInterval: null
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
        return this._fetch('/api/dashboard');
    },
    getSessions(params = {}) {
        const q = new URLSearchParams();
        if (params.status) q.set('status', params.status);
        if (params.project) q.set('project', params.project);
        if (params.limit) q.set('limit', params.limit);
        if (params.offset) q.set('offset', params.offset);
        const qs = q.toString();
        return this._fetch('/api/sessions' + (qs ? '?' + qs : ''));
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
        const q = new URLSearchParams();
        q.set('q', query);
        if (filters.project) q.set('project', filters.project);
        if (filters.after) q.set('after', filters.after);
        if (filters.before) q.set('before', filters.before);
        if (filters.limit) q.set('limit', filters.limit);
        return this._fetch('/api/search?' + q.toString());
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
            const sessionId = segments[2];
            const tab = segments[3] || 'conversation';
            CR.state.currentSessionId = sessionId;
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

    // Start router
    CR.router.init();
});
