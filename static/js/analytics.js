/* ============================================================
   Claude Remote v2.0 - Analytics Charts
   Token usage, tool usage, cost visualization
   ============================================================ */

CR.analytics = {
    _tokenChart: null,
    _toolChart: null,
    _projectChart: null,
    _currentPeriod: '7d',

    async render() {
        var container = document.getElementById('view-analytics');
        if (!container) return;

        container.innerHTML = this._buildLayout();
        this._bindEvents(container);

        await this._loadData();
    },

    _buildLayout() {
        var html = '';

        // Stats summary cards
        html += '<div class="stats-row" id="analyticsStats" style="margin-bottom:16px"></div>';

        // Charts grid
        html += '<div class="analytics-grid">';

        // Token usage chart
        html += '<div class="analytics-card full-width">';
        html += '<h3>Token Usage' +
            '<div class="period-selector">' +
            '<button class="period-btn active" data-period="7d">7 days</button>' +
            '<button class="period-btn" data-period="30d">30 days</button>' +
            '</div></h3>';
        html += '<div class="chart-container"><canvas id="tokenChart"></canvas></div>';
        html += '</div>';

        // Tool usage chart
        html += '<div class="analytics-card">';
        html += '<h3>Tool Usage</h3>';
        html += '<div class="chart-container"><canvas id="toolChart"></canvas></div>';
        html += '</div>';

        // Token by project
        html += '<div class="analytics-card">';
        html += '<h3>Tokens by Project</h3>';
        html += '<div class="chart-container"><canvas id="projectChart"></canvas></div>';
        html += '</div>';

        html += '</div>'; // analytics-grid
        return html;
    },

    _bindEvents(container) {
        var self = this;
        container.addEventListener('click', function(e) {
            var periodBtn = e.target.closest('.period-btn');
            if (periodBtn) {
                container.querySelectorAll('.period-btn').forEach(function(b) { b.classList.remove('active'); });
                periodBtn.classList.add('active');
                self._currentPeriod = periodBtn.dataset.period;
                self._loadData();
            }
        });
    },

    async _loadData() {
        try {
            var results = await Promise.all([
                CR.api.getTokenAnalytics(this._currentPeriod, 'day'),
                CR.api.getToolAnalytics(this._currentPeriod),
                CR.api.getTokenAnalytics(this._currentPeriod, 'project')
            ]);

            var tokenData = results[0];
            var toolData = results[1];
            var projectData = results[2];

            this._renderStats(tokenData);
            this._renderTokenChart(tokenData);
            this._renderToolChart(toolData);
            this._renderProjectChart(projectData);
        } catch (err) {
            console.error('Analytics load error:', err);
            var stats = document.getElementById('analyticsStats');
            if (stats) {
                stats.innerHTML = '<div class="stat-card" style="grid-column:1/-1">' +
                    '<h3>Error</h3><div class="stat-sub">' + CR.escapeHtml(err.message) + '</div>' +
                    '<button class="btn btn-ghost btn-sm" style="margin-top:8px" onclick="CR.analytics._loadData()">Retry</button>' +
                    '</div>';
            }
        }
    },

    _renderStats(tokenData) {
        var container = document.getElementById('analyticsStats');
        if (!container) return;

        var totals = tokenData.totals || {};
        var totalTokens = (totals.input || 0) + (totals.output || 0) + (totals.cache_read || 0) + (totals.cache_create || 0);
        var totalAll = totalTokens + (totals.cache_read || 0);
        var cacheRate = totalAll > 0 ? ((totals.cache_read || 0) / totalAll * 100).toFixed(0) : '0';

        var days = tokenData.data ? tokenData.data.length : 0;
        var avgCost = days > 0 ? (totals.cost_estimate || 0) / days : 0;

        var html = '';
        html += '<div class="stat-card"><h3>Total Cost (' + this._currentPeriod + ')</h3>' +
            '<div class="stat-value">' + CR.formatCost(totals.cost_estimate) + '</div></div>';
        html += '<div class="stat-card"><h3>Avg Cost / Day</h3>' +
            '<div class="stat-value">' + CR.formatCost(avgCost) + '</div></div>';
        html += '<div class="stat-card"><h3>Total Tokens</h3>' +
            '<div class="stat-value">' + CR.formatTokens(totalTokens) + '</div></div>';
        html += '<div class="stat-card"><h3>Cache Hit Rate</h3>' +
            '<div class="stat-value">' + cacheRate + '%</div></div>';

        container.innerHTML = html;
    },

    _renderTokenChart(tokenData) {
        var canvas = document.getElementById('tokenChart');
        if (!canvas) return;

        if (this._tokenChart) {
            this._tokenChart.destroy();
            this._tokenChart = null;
        }

        var data = tokenData.data || [];
        var labels = data.map(function(d) {
            // Format date label
            var parts = (d.label || '').split('-');
            if (parts.length === 3) return parts[1] + '/' + parts[2];
            return d.label;
        });

        var ctx = canvas.getContext('2d');
        this._tokenChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Output',
                        data: data.map(function(d) { return d.output || 0; }),
                        backgroundColor: '#f97316',
                        borderRadius: 2
                    },
                    {
                        label: 'Cache Read',
                        data: data.map(function(d) { return d.cache_read || 0; }),
                        backgroundColor: '#3b82f6',
                        borderRadius: 2
                    },
                    {
                        label: 'Cache Create',
                        data: data.map(function(d) { return d.cache_create || 0; }),
                        backgroundColor: '#6366f1',
                        borderRadius: 2
                    },
                    {
                        label: 'Input',
                        data: data.map(function(d) { return d.input || 0; }),
                        backgroundColor: '#555570',
                        borderRadius: 2
                    }
                ]
            },
            options: this._chartOptions({
                stacked: true,
                yTitle: 'Tokens',
                yCallback: function(value) { return CR.formatTokens(value); }
            })
        });
    },

    _renderToolChart(toolData) {
        var canvas = document.getElementById('toolChart');
        if (!canvas) return;

        if (this._toolChart) {
            this._toolChart.destroy();
            this._toolChart = null;
        }

        var tools = toolData.tools || [];
        var labels = tools.map(function(t) { return t.name; });
        var counts = tools.map(function(t) { return t.count; });
        var colors = tools.map(function(t, i) {
            var palette = ['#f97316', '#3b82f6', '#6366f1', '#22c55e', '#eab308', '#ef4444', '#8888a0'];
            return palette[i % palette.length];
        });

        var ctx = canvas.getContext('2d');
        this._toolChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Uses',
                    data: counts,
                    backgroundColor: colors,
                    borderRadius: 4
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#1e1e30',
                        titleColor: '#f0f0f5',
                        bodyColor: '#8888a0',
                        borderColor: '#2a2a3a',
                        borderWidth: 1,
                        callbacks: {
                            label: function(ctx) {
                                var pct = tools[ctx.dataIndex] ? tools[ctx.dataIndex].percentage : 0;
                                return ctx.parsed.x + ' uses (' + pct.toFixed(1) + '%)';
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(42, 42, 58, 0.5)' },
                        ticks: { color: '#8888a0', font: { size: 11 } }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { color: '#f0f0f5', font: { size: 12 } }
                    }
                }
            }
        });
    },

    _renderProjectChart(projectData) {
        var canvas = document.getElementById('projectChart');
        if (!canvas) return;

        if (this._projectChart) {
            this._projectChart.destroy();
            this._projectChart = null;
        }

        var data = projectData.data || [];
        if (data.length === 0) {
            // No data available for doughnut
            return;
        }

        var labels = data.map(function(d) { return d.label; });
        var values = data.map(function(d) {
            return (d.output || 0) + (d.cache_read || 0) + (d.cache_create || 0) + (d.input || 0);
        });
        var palette = ['#f97316', '#6366f1', '#3b82f6', '#22c55e', '#eab308', '#ef4444', '#8888a0'];
        var colors = data.map(function(d, i) { return palette[i % palette.length]; });

        var ctx = canvas.getContext('2d');
        this._projectChart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderWidth: 0,
                    hoverBorderWidth: 2,
                    hoverBorderColor: '#f0f0f5'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            color: '#f0f0f5',
                            font: { size: 12 },
                            padding: 12,
                            usePointStyle: true,
                            pointStyleWidth: 10
                        }
                    },
                    tooltip: {
                        backgroundColor: '#1e1e30',
                        titleColor: '#f0f0f5',
                        bodyColor: '#8888a0',
                        borderColor: '#2a2a3a',
                        borderWidth: 1,
                        callbacks: {
                            label: function(ctx) {
                                return ctx.label + ': ' + CR.formatTokens(ctx.parsed) + ' tokens';
                            }
                        }
                    }
                }
            }
        });
    },

    _chartOptions(opts) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#8888a0',
                        font: { size: 11 },
                        usePointStyle: true,
                        pointStyleWidth: 8,
                        padding: 12
                    }
                },
                tooltip: {
                    backgroundColor: '#1e1e30',
                    titleColor: '#f0f0f5',
                    bodyColor: '#8888a0',
                    borderColor: '#2a2a3a',
                    borderWidth: 1,
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + CR.formatTokens(context.parsed.y);
                        }
                    }
                }
            },
            scales: {
                x: {
                    stacked: opts.stacked || false,
                    grid: { color: 'rgba(42, 42, 58, 0.5)' },
                    ticks: { color: '#8888a0', font: { size: 11 } }
                },
                y: {
                    stacked: opts.stacked || false,
                    grid: { color: 'rgba(42, 42, 58, 0.5)' },
                    ticks: {
                        color: '#8888a0',
                        font: { size: 11 },
                        callback: opts.yCallback || function(v) { return v; }
                    },
                    title: opts.yTitle ? {
                        display: true,
                        text: opts.yTitle,
                        color: '#555570',
                        font: { size: 11 }
                    } : undefined
                }
            }
        };
    }
};
