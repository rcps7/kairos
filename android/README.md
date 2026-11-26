# KAIROS for Android

Native Android (Kotlin + Jetpack Compose) port of [KAIROS](../README.md), the self-evolving AI agent.
**Developed by RC.** Licensed under the **GNU General Public License v3.0** — see [`../LICENSE`](../LICENSE) and [`../NOTICE`](../NOTICE).

- Minimum Android version: **Android 10 (API 29)**
- Fully FOSS dependencies, **no Google Play Services**, no ads, no trackers
- Feature mapping from desktop v0.16.5: [`FEASIBILITY.md`](FEASIBILITY.md)
- Desktop code audit: [`AUDIT_v0.16.5.md`](AUDIT_v0.16.5.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)

## Distributions (product flavours)

| Flavour | Media download (yt-dlp) | Where to get it |
|---|---|---|
| `fdroid` (default) | ✗ | Mainline F-Droid, or build it yourself |
| `full` | ✓ (yt-dlp + ffmpeg) | IzzyOnDroid, GitHub Releases |

Everything else is identical. The split exists because the mainline F-Droid repository does
not accept the prebuilt native binaries bundled by `youtubedl-android` (yt-dlp, Python and
ffmpeg). The `fdroid` flavour simply omits on-device media download; you can still download
media on a paired PC through the remote-control feature.

## Build

```sh
cd android
# Unit tests for both flavours
gradle testFdroidDebugUnitTest testFullDebugUnitTest      # Gradle 8.10+, JDK 17
# Debug APKs
gradle assembleFdroidDebug assembleFullDebug
# Instrumented tests (emulator/device, Android 10+); 'full' so the media test runs
gradle connectedFullDebugAndroidTest
```

Release signing reads `KAIROS_KEYSTORE`, `KAIROS_KEYSTORE_PASSWORD`, `KAIROS_KEY_ALIAS` and
`KAIROS_KEY_PASSWORD` from the environment; no keys are ever committed. Without them the
release build is unsigned (F-Droid signs the APK itself).

## F-Droid

- Metadata template: [`fdroid-metadata.yml`](fdroid-metadata.yml) (copy into `fdroiddata`).
- Listing text and changelogs: `fastlane/metadata/android/en-US/`.
- Reproducible-build settings (no dependency metadata blob, no self-update) are already applied
  in `app/build.gradle.kts`.

## Status

| Area | State |
|---|---|
| Chat with streaming, multi-provider LLM | ✅ |
| Model selector with live `GET /models` + curated fallbacks | ✅ |
| Agent Characters (all desktop presets, per-character capabilities) | ✅ |
| Retained memory, knowledge library, durable plans | ✅ |
| Git (JGit), Email (IMAP/SMTP), Telegram bot + allowlist, kill switch | ✅ |
| Skills (sandboxed JavaScript, Rhino) | ✅ |
| PC remote control (paired, AES-256-GCM over LAN) | ✅ |
| Browser Agent (in-app WebView, human-in-the-loop CAPTCHA) | ✅ |
| USB OTG serial (CDC-ACM, CP210x, CH34x, FTDI) | ✅ |
| Voice (system STT / offline Vosk, TTS) | ✅ |
| Media download (MP3/MP4) | `full` flavour only |

## Security notes

- Secrets (API keys, tokens, passwords) are encrypted with the Android Keystore and never
  written in plain text to app storage.
- The PC remote protocol rejects tampered, replayed and stale requests, and only answers
  devices on the local network.
- Agent serial transmits are **off by default**; enable *Allow agent serial writes* in the
  Serial screen to let the agent send data to a connected board.
- The in-app WebView allows cleartext HTTP because users configure their own LAN endpoints
  (local LLM servers, the paired PC). Public providers use HTTPS.
