/* ============================================================
   Claude Remote v2.0 - Search UI
   Full-text search across all sessions
   ============================================================ */

CR.search = {
    _debounceTimer: null,
    _lastQuery: '',

    render(query) {
        var container = document.getElementById('view-search');
        if (!container) return;

        var html = '';

        // Search bar
        html += '<div class="search-bar">';
        html += '<input type="text" class="search-input" id="searchInput" placeholder="Search conversations..." ' +
            'value="' + CR.escapeHtml(query || '') + '">';
        html += '<select class="search-filter" id="searchProject"><option value="">All projects</option></select>';
        html += '<input type="date" class="search-filter" id="searchAfter" placeholder="After">';
        html += '<input type="date" class="search-filter" id="searchBefore" placeholder="Before">';
        html += '</div>';

        // Results container
        html += '<div id="searchResults" class="search-results"></div>';

        container.innerHTML = html;

        // Populate project filter
        this._loadProjects();

        // Bind events
        this._bindEvents();

        // If query provided, execute search
        if (query) {
            this._executeSearch(query);
        } else {
            this._showEmpty();
        }
    },

    _bindEvents() {
        var self = this;
        var input = document.getElementById('searchInput');
        var project = document.getElementById('searchProject');
        var after = document.getElementById('searchAfter');
        var before = document.getElementById('searchBefore');

        if (input) {
            input.addEventListener('input', function() {
                self._debounceSearch();
            });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    clearTimeout(self._debounceTimer);
                    self._doSearch();
                }
            });
            // Focus input
            input.focus();
        }
        if (project) project.addEventListener('change', function() { self._doSearch(); });
        if (after) after.addEventListener('change', function() { self._doSearch(); });
        if (before) before.addEventListener('change', function() { self._doSearch(); });
    },

    _debounceSearch() {
        var self = this;
        clearTimeout(this._debounceTimer);
        this._debounceTimer = setTimeout(function() {
            self._doSearch();
        }, 300);
    },

    _doSearch() {
        var input = document.getElementById('searchInput');
        var query = input ? input.value.trim() : '';
        if (!query) {
            this._showEmpty();
            return;
        }
        this._executeSearch(query);
    },

    async _executeSearch(query) {
        var resultsEl = document.getElementById('searchResults');
        if (!resultsEl) return;

        // Show loading
        resultsEl.innerHTML = '<div class="search-loading">Searching...</div>';

        var project = document.getElementById('searchProject');
        var after = document.getElementById('searchAfter');
        var before = document.getElementById('searchBefore');

        var filters = {};
        if (project && project.value) filters.project = project.value;
        if (after && after.value) filters.after = after.value;
        if (before && before.value) filters.before = before.value;
        filters.limit = 20;

        try {
            var data = await CR.api.search(query, filters);
            this._renderResults(data, query);
        } catch (err) {
            console.error('Search error:', err);
            resultsEl.innerHTML = '<div class="search-empty">' +
                '<p>Search failed</p>' +
                '<p style="font-size:12px;margin-top:4px;color:var(--text-dim)">' + CR.escapeHtml(err.message) + '</p>' +
                '</div>';
        }
    },

    _renderResults(data, query) {
        var resultsEl = document.getElementById('searchResults');
        if (!resultsEl) return;

        var results = data.results || [];
        if (results.length === 0) {
            resultsEl.innerHTML = '<div class="search-empty">' +
                '<p>No results for "' + CR.escapeHtml(query) + '"</p>' +
                '<p style="font-size:12px;margin-top:4px;color:var(--text-dim)">Try different keywords or broaden your filters</p>' +
                '</div>';
            return;
        }

        var html = '<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">' +
            data.total + ' result' + (data.total !== 1 ? 's' : '') + ' found</div>';

        for (var i = 0; i < results.length; i++) {
            var r = results[i];
            html += this._renderResultItem(r, query);
        }

        resultsEl.innerHTML = html;
        this._bindResultEvents(resultsEl);
    },

    _renderResultItem(result, query) {
        var snippet = result.snippet || '';
        // Highlight matching terms in snippet
        snippet = CR.escapeHtml(snippet);
        if (query) {
            var terms = query.split(/\s+/);
            for (var t = 0; t < terms.length; t++) {
                if (terms[t].length < 2) continue;
                var escaped = terms[t].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                var re = new RegExp('(' + escaped + ')', 'gi');
                snippet = snippet.replace(re, '<mark>$1</mark>');
            }
        }

        var hostname = result.hostname || '';
        var html = '<div class="search-result" data-session-id="' + CR.escapeHtml(result.session_id) + '" ' +
            'data-hostname="' + CR.escapeHtml(hostname) + '" ' +
            'data-msg-uuid="' + CR.escapeHtml(result.message_uuid || '') + '">';
        html += '<div class="search-result-header">';
        html += '<span class="search-result-slug">' + CR.escapeHtml(result.slug || '') + '</span>';
        if (CR.state.coordinatorMode && hostname) {
            html += '<span class="badge badge-machine">' + CR.escapeHtml(hostname) + '</span>';
        }
        if (result.project) {
            html += '<span class="search-result-project">' + CR.escapeHtml(result.project) + '</span>';
        }
        html += '<span class="badge badge-dim">' + CR.escapeHtml(result.role || '') + '</span>';
        html += '<span class="search-result-time">' + CR.formatTime(result.timestamp) + '</span>';
        html += '</div>';
        html += '<div class="search-result-snippet">' + snippet + '</div>';
        html += '</div>';
        return html;
    },

    _showEmpty() {
        var resultsEl = document.getElementById('searchResults');
        if (resultsEl) {
            resultsEl.innerHTML = '<div class="search-empty">' +
                '<p>Search across all your Claude conversations</p>' +
                '<p style="font-size:12px;margin-top:4px;color:var(--text-dim)">Enter a search term above to find messages, thinking, and tool uses</p>' +
                '</div>';
        }
    },

    async _loadProjects() {
        try {
            var data = await CR.api.getSessions({ limit: 100 });
            var projects = {};
            var sessions = data.sessions || [];
            for (var i = 0; i < sessions.length; i++) {
                var p = sessions[i].project || CR.projectName(sessions[i].working_dir);
                if (p) projects[p] = true;
            }
            var select = document.getElementById('searchProject');
            if (select) {
                var names = Object.keys(projects).sort();
                for (var j = 0; j < names.length; j++) {
                    var opt = document.createElement('option');
                    opt.value = names[j];
                    opt.textContent = names[j];
                    select.appendChild(opt);
                }
            }
        } catch (err) {
            // Ignore - project filter just won't populate
        }
    },

    _bindResultEvents(container) {
        container.addEventListener('click', function(e) {
            var result = e.target.closest('.search-result');
            if (result) {
                var sid = result.dataset.sessionId;
                var hostname = result.dataset.hostname || '';
                var msgUuid = result.dataset.msgUuid;
                if (sid) {
                    var hash = CR.sessionUrl(sid, hostname);
                    if (msgUuid) hash += '?msg=' + msgUuid;
                    CR.navigate(hash);
                }
            }
        });
    }
};
