import { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.atlasrobotics.clauderemote',
  appName: 'Claude Remote',
  webDir: 'static',
  server: {
    // Live mode: load from server over Tailscale
    // Comment out url to use local static files instead
    url: 'https://zapphood.tailda72f.ts.net:7860',
    cleartext: false
  },
  plugins: {
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert']
    },
    SplashScreen: {
      launchAutoHide: true,
      androidScaleType: 'CENTER_CROP',
      backgroundColor: '#0a0a0f'
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#0a0a0f'
    },
    Keyboard: {
      resize: 'body',
      resizeOnFullScreen: true
    },
    BackgroundRunner: {
      label: 'com.atlasrobotics.clauderemote.check',
      src: 'background-runner.js',
      event: 'checkSessions',
      repeat: true,
      interval: 15,
      autoStart: true
    }
  }
};

export default config;
