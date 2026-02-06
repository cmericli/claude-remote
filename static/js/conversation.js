/* ============================================================
   Claude Remote v2.0 - Conversation Renderer
   The most important file: renders rich conversation views
   ============================================================ */

CR.conversation = {
    _sessionData: null,
    _scrolledUp: false,
    _messageContainer: null,

    async render(sessionId) {
        var panel = document.getElementById('session-conversation');
        if (!panel) return;

        // Render skeleton
        panel.innerHTML = this._skeleton();

        try {
            // Fetch session detail and conversation in parallel
            var results = await Promise.all([
                CR.api.getSession(sessionId),
                CR.api.getConversation(sessionId, 200, 0)
            ]);
            var detail = results[0];
            var convo = results[1];
            this._sessionData = detail;

            // Render session header
            this._renderSessionHeader(detail);

            // Render conversation
            panel.innerHTML = '';
            panel.innerHTML = this._buildConversation(convo, detail);

            this._messageContainer = panel.querySelector('.conversation-messages');
            this._bindEvents(panel);

            // Scroll to bottom
            if (this._messageContainer) {
                this._messageContainer.scrollTop = this._messageContainer.scrollHeight;
            }

            // Update status bar
            var totalTokens = 0;
            if (detail.token_breakdown) {
                var tb = detail.token_breakdown;
                totalTokens = (tb.input || 0) + (tb.output || 0) + (tb.cache_read || 0) + (tb.cache_create || 0);
            }
            CR.setStatus('', CR.formatTokens(totalTokens) + ' tokens');

        } catch (err) {
            console.error('Conversation load error:', err);
            panel.innerHTML = '<div class="search-empty">' +
                '<p>Failed to load conversation</p>' +
                '<p style="font-size:12px;margin-top:8px;color:var(--text-dim)">' + CR.escapeHtml(err.message) + '</p>' +
                '<button class="btn btn-ghost" style="margin-top:12px" onclick="CR.conversation.render(\'' + CR.escapeHtml(sessionId) + '\')">Retry</button>' +
                '</div>';
        }
    },

    async renderSessionDetail(sessionId, tab) {
        // For files and stats tabs
        try {
            var detail = await CR.api.getSession(sessionId);
            this._sessionData = detail;
            this._renderSessionHeader(detail);

            if (tab === 'files') {
                this._renderFiles(detail);
            } else if (tab === 'stats') {
                this._renderStats(detail);
            }
        } catch (err) {
            console.error('Session detail error:', err);
        }
    },

    _renderSessionHeader(detail) {
        var header = document.getElementById('session-header');
        if (!header) return;

        var s = detail.session || detail;
        var project = s.project || CR.projectName(s.working_dir);
        var model = (s.model || '').replace('claude-', '').replace(/-/g, ' ');
        var isRunning = s.is_running;
        var statusClass = isRunning ? 'running' : 'stopped';
        var statusLabel = isRunning ? 'Running' : 'Stopped';

        // Calculate duration
        var duration = '';
        if (s.first_message && s.last_message) {
            var diffMin = (new Date(s.last_message) - new Date(s.first_message)) / 60000;
            duration = CR.formatDuration(diffMin);
        }

        var totalTokens = 0;
        if (detail.token_breakdown) {
            var tb = detail.token_breakdown;
            totalTokens = (tb.input || 0) + (tb.output || 0) + (tb.cache_read || 0) + (tb.cache_create || 0);
        } else if (s.total_tokens) {
            totalTokens = s.total_tokens;
        }

        var html = '<div class="session-header-top">';
        html += '<button class="session-back-btn" onclick="CR.navigate(\'#/\')">&larr; Dashboard</button>';
        html += '<span class="session-title">' + CR.escapeHtml(s.slug || project) + '</span>';
        html += '<span class="session-status-badge">';
        html += '<span class="status-dot ' + statusClass + '"></span>';
        html += '<span>' + statusLabel + '</span>';
        html += '</span>';
        html += '</div>';

        html += '<div class="session-meta-row">';
        html += '<span>' + CR.escapeHtml(project) + '</span>';
        if (s.git_branch) html += '<span class="meta-sep">&middot;</span><span>' + CR.escapeHtml(s.git_branch) + '</span>';
        if (model) html += '<span class="meta-sep">&middot;</span><span>' + CR.escapeHtml(model) + '</span>';
        if (duration) html += '<span class="meta-sep">&middot;</span><span>' + duration + '</span>';
        html += '<span class="meta-sep">&middot;</span><span>' + CR.formatTokens(totalTokens) + ' tokens</span>';
        html += '</div>';

        header.innerHTML = html;
    },

    _skeleton() {
        var html = '<div style="padding:20px">';
        for (var i = 0; i < 4; i++) {
            html += '<div style="margin-bottom:16px;max-width:' + (i % 2 === 0 ? '60%' : '75%') + ';' +
                (i % 2 === 0 ? 'margin-left:auto' : '') + '">';
            html += '<div class="skeleton skeleton-line" style="width:80%"></div>';
            html += '<div class="skeleton skeleton-line short"></div>';
            html += '</div>';
        }
        html += '</div>';
        return html;
    },

    _buildConversation(convo, detail) {
        var s = (detail && detail.session) || detail || {};
        var messages = convo.messages || [];
        var isRunning = s.is_running;

        var html = '<div class="conversation-messages">';

        if (convo.total > messages.length && convo.offset === 0) {
            html += '<div style="text-align:center;padding:12px">';
            html += '<button class="btn btn-ghost btn-sm" data-action="load-more">Load earlier messages (' + (convo.total - messages.length) + ' more)</button>';
            html += '</div>';
        }

        for (var i = 0; i < messages.length; i++) {
            html += this._renderMessage(messages[i]);
        }

        if (messages.length === 0) {
            html += '<div class="search-empty"><p>No messages in this session</p></div>';
        }

        html += '</div>';

        // Jump to latest button
        html += '<button class="jump-latest" id="jumpLatest">&#8595; Jump to latest</button>';

        // Quick actions bar (only for running sessions)
        if (isRunning) {
            html += '<div class="quick-actions">';
            html += '<button class="btn btn-success btn-sm" data-quick="continue">Continue</button>';
            html += '<button class="btn btn-info btn-sm" data-quick="lgtm">Looks good</button>';
            html += '<button class="btn btn-danger btn-sm" data-quick="stop">Stop</button>';
            html += '<input type="text" class="quick-input" placeholder="Send a message..." data-quick-input>';
            html += '<button class="btn btn-primary btn-sm" data-quick="send">Send</button>';
            html += '</div>';
        }

        return html;
    },

    _renderMessage(msg) {
        var role = msg.role || 'assistant';
        if (role === 'system') return ''; // skip system messages

        // For user messages that are just tool_result arrays, skip rendering
        if (role === 'user' && !msg.content_text) return '';

        var html = '<div class="msg ' + role + '" data-uuid="' + CR.escapeHtml(msg.uuid || '') + '">';
        html += '<div class="msg-bubble">';

        if (role === 'assistant') {
            // Thinking block
            if (msg.has_thinking && msg.thinking_text) {
                html += this._renderThinking(msg.thinking_text);
            }

            // Tool uses
            if (msg.tool_uses && msg.tool_uses.length > 0) {
                for (var t = 0; t < msg.tool_uses.length; t++) {
                    html += this._renderToolUse(msg.tool_uses[t]);
                }
            }

            // Main text content
            if (msg.content_text) {
                html += '<div class="msg-text">' + this._renderMarkdown(msg.content_text) + '</div>';
            }
        } else {
            // User message
            if (msg.content_text) {
                html += '<div class="msg-text">' + this._renderMarkdown(msg.content_text) + '</div>';
            }
        }

        html += '</div>'; // msg-bubble

        // Timestamp and model badge
        html += '<div class="msg-timestamp">';
        if (role === 'assistant' && msg.model) {
            var shortModel = (msg.model || '').replace('claude-', '');
            html += '<span class="msg-model-badge">' + CR.escapeHtml(shortModel) + '</span>';
        }
        if (msg.output_tokens && role === 'assistant') {
            html += '<span style="font-size:10px;color:var(--text-dim)">' + CR.formatTokens(msg.output_tokens) + ' out</span>';
        }
        html += '<span>' + CR.formatTimeShort(msg.timestamp) + '</span>';
        html += '</div>';

        html += '</div>'; // msg
        return html;
    },

    _renderThinking(text) {
        var preview = text.length > 120 ? text.substring(0, 120) + '...' : text;
        var html = '<div class="thinking-block">';
        html += '<button class="thinking-toggle" data-action="toggle-thinking">';
        html += '<span class="arrow">&#9654;</span> Thinking...';
        html += '</button>';
        html += '<div class="thinking-content">' + CR.escapeHtml(text) + '</div>';
        html += '</div>';
        return html;
    },

    _renderToolUse(tool) {
        var icon = CR.getToolIcon(tool.name);
        var html = '<div class="tool-block">';
        html += '<div class="tool-header" data-action="toggle-tool">';
        html += '<span class="tool-icon">' + icon + '</span>';
        html += '<span class="tool-name">' + CR.escapeHtml(tool.name) + '</span>';
        html += '<span class="tool-summary">' + CR.escapeHtml(tool.summary || '') + '</span>';
        html += '</div>';
        if (tool.input_detail || tool.summary) {
            html += '<div class="tool-detail">' + CR.escapeHtml(tool.input_detail || tool.summary || '') + '</div>';
        }
        html += '</div>';
        return html;
    },

    _renderMarkdown(text) {
        if (!text) return '';
        try {
            // Configure marked
            if (typeof marked !== 'undefined') {
                marked.setOptions({
                    breaks: true,
                    gfm: true,
                    highlight: function(code, lang) {
                        if (typeof hljs !== 'undefined') {
                            if (lang && hljs.getLanguage(lang)) {
                                try {
                                    return hljs.highlight(code, { language: lang }).value;
                                } catch (e) { /* fall through */ }
                            }
                            try {
                                return hljs.highlightAuto(code).value;
                            } catch (e) { /* fall through */ }
                        }
                        return CR.escapeHtml(code);
                    }
                });
                return marked.parse(text);
            }
        } catch (e) {
            console.warn('Markdown parse error:', e);
        }
        // Fallback: escape and handle basic formatting
        return '<p>' + CR.escapeHtml(text).replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>') + '</p>';
    },

    _renderFiles(detail) {
        var panel = document.getElementById('session-files');
        if (!panel) return;

        var files = detail.files_touched || [];
        if (files.length === 0) {
            panel.innerHTML = '<div class="search-empty"><p>No files tracked for this session</p></div>';
            return;
        }

        var html = '<div class="files-list">';
        var typeIcons = { read: '\uD83D\uDCD6', write: '\uD83D\uDCDD', edit: '\u270F\uFE0F', create: '\uD83D\uDCDD', bash: '\uD83D\uDD28' };
        for (var i = 0; i < files.length; i++) {
            var f = files[i];
            var icon = typeIcons[f.event_type] || '\uD83D\uDCC4';
            var path = f.path || '';
            // Show just filename for brevity
            var parts = path.split('/');
            var filename = parts.length > 2 ? '.../' + parts.slice(-2).join('/') : path;

            html += '<div class="file-item">';
            html += '<span class="file-icon">' + icon + '</span>';
            html += '<span class="file-path" title="' + CR.escapeHtml(path) + '">' + CR.escapeHtml(filename) + '</span>';
            html += '<span class="file-event-type">' + CR.escapeHtml(f.event_type) + '</span>';
            if (f.count && f.count > 1) {
                html += '<span class="file-count">&times;' + f.count + '</span>';
            }
            html += '</div>';
        }
        html += '</div>';
        panel.innerHTML = html;
    },

    _renderStats(detail) {
        var panel = document.getElementById('session-stats');
        if (!panel) return;

        var s = detail.session || detail;
        var tb = detail.token_breakdown || {};
        var toolSummary = detail.tool_summary || {};

        var totalTokens = (tb.input || 0) + (tb.output || 0) + (tb.cache_read || 0) + (tb.cache_create || 0);
        var cacheRate = totalTokens > 0 ? ((tb.cache_read || 0) / totalTokens * 100).toFixed(0) : '0';

        // Duration
        var duration = '';
        if (s.first_message && s.last_message) {
            var diffMin = (new Date(s.last_message) - new Date(s.first_message)) / 60000;
            duration = CR.formatDuration(diffMin);
        }

        var html = '<div class="stats-grid">';

        // Token stats
        html += this._statsCard('Total Tokens', CR.formatTokens(totalTokens));
        html += this._statsCard('Output Tokens', CR.formatTokens(tb.output));
        html += this._statsCard('Cache Read', CR.formatTokens(tb.cache_read));
        html += this._statsCard('Cache Create', CR.formatTokens(tb.cache_create));
        html += this._statsCard('Input Tokens', CR.formatTokens(tb.input));
        html += this._statsCard('Cache Hit Rate', cacheRate + '%');
        html += this._statsCard('Duration', duration || 'N/A');
        html += this._statsCard('Messages', String(s.message_count || 0));
        html += this._statsCard('User Messages', String(s.user_msg_count || 0));
        html += this._statsCard('Assistant Messages', String(s.asst_msg_count || 0));

        html += '</div>';

        // Tool usage breakdown
        var toolNames = Object.keys(toolSummary);
        if (toolNames.length > 0) {
            html += '<div style="padding:0 20px 16px">';
            html += '<h3 style="font-size:13px;color:var(--text-secondary);margin-bottom:12px;font-weight:600;">Tool Usage</h3>';
            html += '<div class="activity-list">';
            // Sort by count descending
            toolNames.sort(function(a, b) { return (toolSummary[b] || 0) - (toolSummary[a] || 0); });
            for (var i = 0; i < toolNames.length; i++) {
                var name = toolNames[i];
                var count = toolSummary[name];
                html += '<div class="activity-item" style="cursor:default">';
                html += '<span class="activity-icon">' + CR.getToolIcon(name) + '</span>';
                html += '<span class="activity-text" style="color:var(--text)">' + CR.escapeHtml(name) + '</span>';
                html += '<span style="font-size:13px;font-weight:600;color:var(--text)">' + count + '</span>';
                html += '</div>';
            }
            html += '</div>';
            html += '</div>';
        }

        panel.innerHTML = html;
    },

    _statsCard(label, value) {
        return '<div class="session-stats-card">' +
            '<div class="label">' + CR.escapeHtml(label) + '</div>' +
            '<div class="value">' + CR.escapeHtml(value || '0') + '</div>' +
            '</div>';
    },

    _bindEvents(panel) {
        // Toggle thinking blocks
        panel.addEventListener('click', function(e) {
            var thinkBtn = e.target.closest('[data-action="toggle-thinking"]');
            if (thinkBtn) {
                thinkBtn.classList.toggle('expanded');
                var content = thinkBtn.nextElementSibling;
                if (content) content.classList.toggle('visible');
                return;
            }

            // Toggle tool details
            var toolHeader = e.target.closest('[data-action="toggle-tool"]');
            if (toolHeader) {
                var detail = toolHeader.nextElementSibling;
                if (detail && detail.classList.contains('tool-detail')) {
                    detail.classList.toggle('visible');
                }
                return;
            }

            // Load more messages
            var loadMore = e.target.closest('[data-action="load-more"]');
            if (loadMore) {
                // TODO: implement pagination
                return;
            }

            // Quick actions
            var quickBtn = e.target.closest('[data-quick]');
            if (quickBtn) {
                var action = quickBtn.dataset.quick;
                if (action === 'send') {
                    var input = panel.querySelector('[data-quick-input]');
                    if (input && input.value.trim()) {
                        CR.conversation._sendQuickAction(input.value.trim());
                        input.value = '';
                    }
                } else if (action === 'continue') {
                    CR.conversation._sendQuickAction('Continue');
                } else if (action === 'lgtm') {
                    CR.conversation._sendQuickAction('Looks good, proceed.');
                } else if (action === 'stop') {
                    // Navigate to terminal and let user Ctrl+C
                    if (CR.state.currentSessionId) {
                        CR.navigate('#/session/' + CR.state.currentSessionId + '/terminal');
                    }
                }
                return;
            }
        });

        // Quick action input enter key
        var quickInput = panel.querySelector('[data-quick-input]');
        if (quickInput) {
            quickInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && quickInput.value.trim()) {
                    CR.conversation._sendQuickAction(quickInput.value.trim());
                    quickInput.value = '';
                }
            });
        }

        // Scroll tracking for "jump to latest"
        var msgContainer = panel.querySelector('.conversation-messages');
        var jumpBtn = document.getElementById('jumpLatest');
        if (msgContainer && jumpBtn) {
            msgContainer.addEventListener('scroll', function() {
                var atBottom = msgContainer.scrollHeight - msgContainer.scrollTop - msgContainer.clientHeight < 100;
                CR.conversation._scrolledUp = !atBottom;
                jumpBtn.classList.toggle('visible', !atBottom);
            });
            jumpBtn.addEventListener('click', function() {
                msgContainer.scrollTop = msgContainer.scrollHeight;
            });
        }
    },

    _sendQuickAction(text) {
        // Attempt to inject text via terminal API or navigate to terminal
        var sessionId = CR.state.currentSessionId;
        if (!sessionId) return;

        // Try the inject endpoint
        fetch('/api/terminal/' + encodeURIComponent(sessionId) + '/inject', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text + '\n' })
        }).catch(function(err) {
            console.warn('Inject failed, switching to terminal:', err);
            CR.navigate('#/session/' + sessionId + '/terminal');
        });
    }
};
