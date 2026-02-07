/* ============================================================
   Claude Remote v4.0 - Notifications
   Unified push notification handling for Web Push and native APNs.
   Detects Capacitor native platform and uses correct push path.
   ============================================================ */

CR.nativePush = {
    _isNative: false,
    _deviceToken: null,

    init() {
        // Detect Capacitor native platform
        this._isNative = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());

        if (this._isNative) {
            this._initNativePush();
        }
        // Web Push is handled by CR.push in app.js (existing)
    },

    async _initNativePush() {
        try {
            var PushNotifications = window.Capacitor.Plugins.PushNotifications;
            if (!PushNotifications) return;

            // Request permission
            var permResult = await PushNotifications.requestPermissions();
            if (permResult.receive !== 'granted') {
                console.log('Native push permission denied');
                return;
            }

            // Register for push
            await PushNotifications.register();

            // Listen for registration success
            PushNotifications.addListener('registration', function(token) {
                CR.nativePush._deviceToken = token.value;
                console.log('APNs device token:', token.value);
                // Register token with server
                CR.nativePush._registerWithServer(token.value);
            });

            // Listen for registration error
            PushNotifications.addListener('registrationError', function(err) {
                console.error('APNs registration error:', err);
            });

            // Listen for push received (foreground)
            PushNotifications.addListener('pushNotificationReceived', function(notification) {
                console.log('Push received (foreground):', notification);
                // Show in-app notification
                var data = notification.data || {};
                if (data.session_id) {
                    CR.state.needsInputSessions.add(data.session_id);
                    CR.sse._updateBadge();
                }
            });

            // Listen for push action (user tapped notification)
            PushNotifications.addListener('pushNotificationActionPerformed', function(action) {
                console.log('Push action:', action);
                var data = action.notification.data || {};
                if (data.session_id) {
                    CR.navigate(CR.sessionUrl(data.session_id, data.hostname || ''));
                }
            });

        } catch (err) {
            console.error('Native push init error:', err);
        }
    },

    async _registerWithServer(deviceToken) {
        try {
            await fetch('/api/push/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    device_token: deviceToken,
                    platform: 'ios'
                })
            });
            console.log('Device token registered with server');
        } catch (err) {
            console.error('Failed to register device token:', err);
        }
    },

    async unregister() {
        if (!this._deviceToken) return;
        try {
            await fetch('/api/push/register', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    device_token: this._deviceToken
                })
            });
            this._deviceToken = null;
        } catch (err) {
            console.error('Failed to unregister device:', err);
        }
    },

    isNative() {
        return this._isNative;
    }
};
