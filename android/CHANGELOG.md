# KAIROS for Android — Changelog

## 0.16.5-android.1 (versionCode 1)

First Android release.

- Chat with streaming and multi-provider LLM support (Moonshot/Kimi, DeepSeek, OpenAI,
  OpenRouter, Groq, Custom) with a live model list.
- Agent Characters (all desktop presets) with per-character tool permissions.
- Retained memory, knowledge library and durable plans (Plan / Execute modes).
- Git workflows with JGit (init, clone, commit, log, branches, remotes, pull, push).
- Email (IMAP/SMTP) and a Telegram bot with an allowlist and a kill switch.
- Sandboxed JavaScript skills (Mozilla Rhino).
- PC remote control: pair by QR, encrypted (AES-256-GCM) chat and jobs on a desktop Kairos.
- Browser Agent (in-app WebView): browse, read, fill forms, click, JavaScript and a
  human-in-the-loop CAPTCHA hand-off. No automated CAPTCHA solving.
- USB OTG serial (CDC-ACM, CP210x, CH34x, FTDI) for ESP32, Arduino and Pico boards.
- Voice: system speech recognition with an offline Vosk option, and spoken replies.
- Media download (audio/video) is available in the separate **full** build (yt-dlp);
  the **fdroid** build omits it.

### Security
- Secrets are stored with the Android Keystore (AES-256-GCM); nothing is kept in plain text.
- The PC remote protocol rejects tampered, replayed and stale requests.
- Agent serial transmits are off by default; enable "Allow agent serial writes" to permit them.
