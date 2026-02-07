/* Claude Remote - Service Worker */

const CACHE_NAME = 'claude-remote-v2';
const APP_SHELL = [
    '/',
    '/static/css/styles.css',
    '/static/js/app.js',
    '/static/js/dashboard.js',
    '/static/js/conversation.js',
    '/static/js/terminal.js',
    '/static/js/search.js',
    '/static/js/analytics.js',
    '/static/manifest.json',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png'
];

// Install: cache app shell
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return cache.addAll(APP_SHELL);
        }).then(function() {
            return self.skipWaiting();
        })
    );
});

// Activate: clean old caches
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(names) {
            return Promise.all(
                names.filter(function(name) { return name !== CACHE_NAME; })
                    .map(function(name) { return caches.delete(name); })
            );
        }).then(function() {
            return self.clients.claim();
        })
    );
});

// Fetch: network-first for API, cache-first for static
self.addEventListener('fetch', function(event) {
    var url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') return;

    // Skip WebSocket and SSE
    if (url.pathname.startsWith('/api/terminal/') ||
        url.pathname.endsWith('/stream')) {
        return;
    }

    // API calls: network-first with no cache fallback
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(event.request).catch(function() {
                return new Response(JSON.stringify({ error: 'offline' }), {
                    status: 503,
                    headers: { 'Content-Type': 'application/json' }
                });
            })
        );
        return;
    }

    // Static assets: cache-first
    event.respondWith(
        caches.match(event.request).then(function(cached) {
            if (cached) {
                // Update cache in background
                fetch(event.request).then(function(response) {
                    if (response && response.status === 200) {
                        caches.open(CACHE_NAME).then(function(cache) {
                            cache.put(event.request, response);
                        });
                    }
                }).catch(function() {});
                return cached;
            }
            return fetch(event.request).then(function(response) {
                if (response && response.status === 200) {
                    var clone = response.clone();
                    caches.open(CACHE_NAME).then(function(cache) {
                        cache.put(event.request, clone);
                    });
                }
                return response;
            });
        })
    );
});

// Push notification handler
self.addEventListener('push', function(event) {
    var data = { title: 'Claude Remote', body: 'A session needs your attention' };
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    event.waitUntil(
        self.registration.showNotification(data.title || 'Claude Remote', {
            body: data.body || '',
            icon: '/static/icons/icon-192.png',
            badge: '/static/icons/icon-96.png',
            tag: data.tag || 'claude-remote',
            renotify: true,
            data: { sessionId: data.session_id, url: data.url }
        })
    );
});

// Notification click handler
self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    var sessionId = event.notification.data && event.notification.data.sessionId;
    var url = event.notification.data && event.notification.data.url;
    var targetUrl = url || (sessionId ? '/#/session/' + sessionId : '/');

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clients) {
            // Focus existing window if available
            for (var i = 0; i < clients.length; i++) {
                if (clients[i].url.includes(self.location.origin)) {
                    clients[i].focus();
                    clients[i].navigate(targetUrl);
                    return;
                }
            }
            // Open new window
            return self.clients.openWindow(targetUrl);
        })
    );
});
