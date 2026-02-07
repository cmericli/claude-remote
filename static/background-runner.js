/* ============================================================
   Claude Remote v4.0 - Background Runner
   Capacitor Background Runner task: periodically checks for
   sessions needing input and triggers local notifications.
   This is a safety net — APNs push is the primary channel.
   ============================================================ */

addEventListener('checkSessions', async function(resolve, reject) {
    try {
        var serverUrl = CapacitorData.get('serverUrl') || '';
        if (!serverUrl) {
            resolve();
            return;
        }

        var response = await fetch(serverUrl + '/api/needs-input');
        if (!response.ok) {
            resolve();
            return;
        }

        var data = await response.json();
        var sessions = data.sessions || [];

        if (sessions.length > 0) {
            CapacitorNotifications.schedule({
                title: 'Sessions need input',
                body: sessions.length + ' session' + (sessions.length > 1 ? 's' : '') + ' waiting for your response',
                id: 1,
                extra: { session_id: sessions[0] }
            });
        }

        resolve();
    } catch (err) {
        resolve();
    }
});
