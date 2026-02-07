/* ============================================================
   Claude Remote v2.0 - Dashboard View
   ============================================================ */

CR.dashboard = {
    _lastRender: 0,

    async render(silent) {
        var container = document.getElementById('view-dashboard');
        if (!container) return;

        // Show skeleton on first load
        if (!silent) {
            container.innerHTML = this._skeleton();
        }

        try {
            var data = await CR.api.getDashboard();
            CR.state.dashboardData = data;
            container.innerHTML = this._build(data);
            this._bindEvents(container);
        } catch (err) {
            console.error('Dashboard fetch error:', err);
            if (!silent) {
                container.innerHTML = this._errorState(err);
            }
        }
    },

    _skeleton() {
        return '<div class="dashboard-section">' +
            '<h2>Active Sessions</h2>' +
            '<div class="sessions-grid">' +
            '<div class="skeleton skeleton-card"></div>' +
            '<div class="skeleton skeleton-card"></div>' +
            '</div></div>';
    },

    _errorState(err) {
        return '<div class="search-empty">' +
            '<p>Failed to load dashboard</p>' +
            '<p style="font-size:12px;margin-top:8px;color:var(--text-dim)">' + CR.escapeHtml(err.message) + '</p>' +
            '<button class="btn btn-ghost" style="margin-top:12px" onclick="CR.dashboard.render()">Retry</button>' +
            '</div>';
    },

    _build(data) {
        var html = '';

        // Active Sessions
        html += '<div class="dashboard-section">';
        html += '<h2 style="display:flex;align-items:center;justify-content:space-between;">' +
            'Active Sessions' +
            '<button class="btn btn-primary btn-sm" onclick="CR.modal.open()">+ New Session</button>' +
            '</h2>';

        if (data.active_sessions && data.active_sessions.length > 0) {
            html += '<div class="sessions-grid">';
            for (var i = 0; i < data.active_sessions.length; i++) {
                html += this._sessionCard(data.active_sessions[i]);
            }
            html += '</div>';
        } else {
            html += '<div class="search-empty" style="padding:32px">' +
                '<p>No active sessions</p>' +
                '<p style="font-size:12px;margin-top:4px;color:var(--text-dim)">Start a new session to begin</p>' +
                '</div>';
        }
        html += '</div>';

        // Stats Row
        if (data.stats) {
            html += '<div class="dashboard-section">';
            html += '<div class="stats-row">';
            html += this._statCard('Today',
                (data.stats.today_sessions || 0) + ' sessions',
                CR.formatTokens(data.stats.today_tokens) + ' tokens',
                '~' + CR.formatCost(data.stats.today_cost_estimate)
            );
            html += this._statCard('This Week',
                (data.stats.week_sessions || 0) + ' sessions',
                CR.formatTokens(data.stats.week_tokens) + ' tokens',
                '~' + CR.formatCost(data.stats.week_cost_estimate)
            );
            html += this._statCard('Overview',
                (data.stats.total_sessions || 0) + ' total sessions',
                'Cache hit: ' + Math.round((data.stats.cache_hit_rate || 0) * 100) + '%',
                ''
            );
            html += '</div>';
            html += '</div>';
        }

        // Recent Activity
        if (data.recent_activity && data.recent_activity.length > 0) {
            html += '<div class="dashboard-section">';
            html += '<h2>Recent Activity</h2>';
            html += '<div class="activity-list">';
            var actLimit = Math.min(data.recent_activity.length, 10);
            for (var j = 0; j < actLimit; j++) {
                html += this._activityItem(data.recent_activity[j]);
            }
            html += '</div>';
            html += '</div>';
        }

        // Session History
        html += this._historySection(data);

        return html;
    },

    _sessionCard(s) {
        var statusClass = s.is_running ? 'running' : 'stopped';
        var project = s.project || CR.projectName(s.working_dir);
        var model = (s.model || '').replace('claude-', '').replace(/-/g, ' ');
        var preview = s.last_message_preview || '';
        if (preview.length > 80) preview = preview.substring(0, 80) + '...';
        var duration = CR.formatDuration(s.duration_minutes);
        var tokens = CR.formatTokens(s.total_tokens);
        var sessionId = s.session_id;

        var html = '<div class="session-card" data-session-id="' + CR.escapeHtml(sessionId) + '" data-action="open">';
        html += '<div class="session-card-header">';
        html += '<span class="status-dot ' + statusClass + '"></span>';
        html += '<span class="session-card-project">' + CR.escapeHtml(project) + '</span>';
        if (s.is_in_tmux) {
            html += '<span class="badge badge-success">tmux</span>';
        }
        html += '</div>';

        html += '<div class="session-card-meta">';
        if (s.slug) html += '<span>' + CR.escapeHtml(s.slug) + '</span><span class="meta-sep">&middot;</span>';
        if (model) html += '<span>' + CR.escapeHtml(model) + '</span>';
        if (s.git_branch) html += '<span class="meta-sep">&middot;</span><span>' + CR.escapeHtml(s.git_branch) + '</span>';
        html += '</div>';

        if (preview) {
            html += '<div class="session-card-preview">' + CR.escapeHtml(preview) + '</div>';
        }

        html += '<div class="session-card-footer">';
        html += '<div class="session-card-stats">';
        html += '<span>' + duration + '</span>';
        html += '<span>' + tokens + ' tokens</span>';
        html += '</div>';
        html += '<div class="session-card-actions">';
        html += '<button class="btn btn-info btn-sm" data-action="view" data-sid="' + CR.escapeHtml(sessionId) + '">View</button>';
        if (s.is_running && s.is_in_tmux) {
            html += '<button class="btn btn-success btn-sm" data-action="attach" data-sid="' + CR.escapeHtml(sessionId) + '">Attach</button>';
        } else if (s.is_running) {
            html += '<button class="btn btn-ghost btn-sm" data-action="browse" data-sid="' + CR.escapeHtml(sessionId) + '">Browse</button>';
        }
        html += '</div>';
        html += '</div>';
        html += '</div>';
        return html;
    },

    _statCard(title, line1, line2, line3) {
        var html = '<div class="stat-card">';
        html += '<h3>' + CR.escapeHtml(title) + '</h3>';
        html += '<div class="stat-value">' + CR.escapeHtml(line1) + '</div>';
        if (line2) html += '<div class="stat-sub">' + CR.escapeHtml(line2) + '</div>';
        if (line3) html += '<div class="stat-sub">' + CR.escapeHtml(line3) + '</div>';
        html += '</div>';
        return html;
    },

    _activityItem(item) {
        var icon = CR.getToolIcon(item.tool_name);
        var project = item.project || CR.projectName(item.slug);
        var time = CR.formatTimeShort(item.timestamp);
        var summary = item.summary || item.tool_name || '';

        var html = '<div class="activity-item" data-session-id="' + CR.escapeHtml(item.session_id) + '" data-action="open">';
        html += '<span class="activity-time">' + CR.escapeHtml(time) + '</span>';
        html += '<span class="activity-icon">' + icon + '</span>';
        html += '<span class="activity-text">';
        html += '<span class="activity-project">' + CR.escapeHtml(project) + '</span> ';
        html += CR.escapeHtml(summary);
        html += '</span>';
        html += '</div>';
        return html;
    },

    _historySection(data) {
        // Build from active sessions that are stopped, or fetch separately
        // For now, show a link to browse all sessions
        var html = '<div class="dashboard-section">';
        html += '<h2>Session History</h2>';

        // We show stopped sessions from the active_sessions list if any are stopped
        // and also provide a way to see all
        html += '<div class="history-list" id="dashboardHistory">';
        html += '<div class="history-item" style="justify-content:center;color:var(--text-dim);cursor:default;">';
        html += '<span>Loading history...</span>';
        html += '</div>';
        html += '</div>';
        html += '</div>';

        // Fetch history asynchronously
        this._loadHistory();

        return html;
    },

    async _loadHistory() {
        try {
            var data = await CR.api.getSessions({ status: 'all', limit: 10 });
            var container = document.getElementById('dashboardHistory');
            if (!container) return;

            if (!data.sessions || data.sessions.length === 0) {
                container.innerHTML = '<div class="history-item" style="justify-content:center;color:var(--text-dim);cursor:default;">' +
                    '<span>No session history</span></div>';
                return;
            }

            var html = '';
            for (var i = 0; i < data.sessions.length; i++) {
                var s = data.sessions[i];
                var project = s.project || CR.projectName(s.working_dir);
                html += '<div class="history-item" data-session-id="' + CR.escapeHtml(s.session_id) + '" data-action="open">';
                html += '<span class="status-dot ' + (s.is_running ? 'running' : 'stopped') + '"></span>';
                html += '<span class="history-slug">' + CR.escapeHtml(s.slug || s.session_id.substring(0, 8)) + '</span>';
                html += '<span class="history-project badge badge-dim">' + CR.escapeHtml(project) + '</span>';
                html += '<span class="history-time">' + CR.formatTime(s.last_message) + '</span>';
                if (s.file_size_mb) {
                    html += '<span style="font-size:12px;color:var(--text-dim);min-width:50px;text-align:right">' +
                        Number(s.file_size_mb).toFixed(1) + 'MB</span>';
                }
                html += '<button class="btn btn-ghost btn-sm" data-action="browse" data-sid="' + CR.escapeHtml(s.session_id) + '">Browse</button>';
                html += '</div>';
            }

            if (data.total > 10) {
                html += '<div class="history-item" style="justify-content:center;">';
                html += '<a href="#/search" style="font-size:12px;color:var(--text-secondary)">View all ' + data.total + ' sessions</a>';
                html += '</div>';
            }

            container.innerHTML = html;
            this._bindHistoryEvents(container);
        } catch (err) {
            console.error('Failed to load history:', err);
        }
    },

    updateSessionCard(sessionId, event) {
        // Update a specific session card in-place from an SSE event
        var card = document.querySelector('.session-card[data-session-id="' + sessionId + '"]');
        if (card) {
            // Update preview text
            var preview = card.querySelector('.session-card-preview');
            if (preview && event.preview) {
                var text = event.preview;
                if (text.length > 80) text = text.substring(0, 80) + '...';
                preview.textContent = text;
            }
            // Flash the card border to indicate activity
            card.style.borderColor = 'var(--primary)';
            setTimeout(function() { card.style.borderColor = ''; }, 2000);
        } else {
            // Card doesn't exist (new session or not visible) — trigger silent refresh
            this.render(true);
        }
    },

    _bindEvents(container) {
        // Delegate clicks on session cards and action buttons
        container.addEventListener('click', function(e) {
            // Check for action buttons first
            var actionBtn = e.target.closest('[data-action][data-sid]');
            if (actionBtn) {
                e.stopPropagation();
                var action = actionBtn.dataset.action;
                var sid = actionBtn.dataset.sid;
                if (action === 'view' || action === 'browse' || action === 'open') {
                    CR.navigate('#/session/' + sid);
                } else if (action === 'attach') {
                    CR.navigate('#/session/' + sid + '/terminal');
                }
                return;
            }

            // Check for card click
            var card = e.target.closest('[data-session-id][data-action="open"]');
            if (card) {
                CR.navigate('#/session/' + card.dataset.sessionId);
            }
        });
    },

    _bindHistoryEvents(container) {
        container.addEventListener('click', function(e) {
            var actionBtn = e.target.closest('[data-action][data-sid]');
            if (actionBtn) {
                e.stopPropagation();
                CR.navigate('#/session/' + actionBtn.dataset.sid);
                return;
            }
            var row = e.target.closest('[data-session-id][data-action="open"]');
            if (row) {
                CR.navigate('#/session/' + row.dataset.sessionId);
            }
        });
    }
};
