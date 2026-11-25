# KAIROS for Android

Native Android (Kotlin + Jetpack Compose) port of [KAIROS](../README.md), the self-evolving AI agent.
**Developed by RC.** Licensed under the **GNU General Public License v3.0** — see [`../LICENSE`](../LICENSE) and [`../NOTICE`](../NOTICE).

- Minimum Android version: **Android 10 (API 29)**
- Fully FOSS dependencies, no Google Play Services (F-Droid compatible)
- Feature mapping from desktop v0.16.5: [`FEASIBILITY.md`](FEASIBILITY.md)
- Desktop code audit: [`AUDIT_v0.16.5.md`](AUDIT_v0.16.5.md)

## Status

| Area | State |
|---|---|
| Chat with streaming, multi-provider LLM (Moonshot/Kimi, DeepSeek, OpenAI, OpenRouter, Groq, Custom) | ✅ |
| Model selector with live `GET /models` + curated fallbacks | ✅ |
| Agent Characters (all 8 desktop presets, per-character capabilities) | ✅ |
| Retained memory (`/remember`, `/recall`, Memory tab) | ✅ |
| API keys encrypted with the Android Keystore | ✅ |
| Remaining features | see FEASIBILITY.md |

## Build

```sh
cd android
gradle testDebugUnitTest assembleDebug      # Gradle 8.10+, JDK 17
gradle connectedDebugAndroidTest            # needs an emulator/device, Android 10+
```

CI (`.github/workflows/android.yml`) runs unit tests, builds the debug APK and runs instrumented tests on an
Android 10 emulator. Release signing reads `KAIROS_KEYSTORE`, `KAIROS_KEYSTORE_PASSWORD`, `KAIROS_KEY_ALIAS`
and `KAIROS_KEY_PASSWORD` from the environment; no keys are ever committed.
