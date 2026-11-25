# KAIROS for Android — Feature Feasibility Matrix

Source audited: `rcps7/kairos` tag **v0.16.5** (commit `63891e4`), 84 Python modules, ~22.7k lines.
Target: native **Kotlin / Jetpack Compose** app, **minSdk 29 (Android 10)**, fully FOSS (F-Droid compatible), GPLv3.

Legend:
- **Ported** — reimplemented in Kotlin with the same behaviour.
- **Substituted** — same user-facing capability, using an Android-native equivalent (named).
- **Excluded** — not possible on stock, non-rooted Android; reason given. *Exclusions are proposals and need the owner's approval before being final.*

## Core agent

| Feature (desktop module) | Status | Android implementation / reason |
|---|---|---|
| Chat engine, tool loop, streaming (`main.py`, `llm/client.py`) | Ported | Kotlin coroutines + OkHttp SSE against OpenAI-style `/chat/completions` with native tool calls |
| Multi-provider LLM: Moonshot/Kimi, DeepSeek, OpenAI, OpenRouter, Groq, Custom (`config.py`, `llm/kimi.py`) | Ported | Same provider presets, editable base URL / model |
| Model selector with live `GET /models` + daily refresh | Ported | WorkManager daily job |
| Token usage accounting (`usage.py`) | Ported | Room table |
| Agent Characters + presets + per-character tool access (`characters*.py`) | Ported | Presets ported as JSON assets |
| Plan / Execute modes, durable plans (`planner.py`, `agents.py`) | Ported | Room-backed plans; execution in a foreground service |
| FIFO job queue (`jobs.py`) | Ported | Single-consumer coroutine `Channel`; long jobs promoted to a foreground service |
| Council (multi-model deliberation) (`council.py`) | Ported | |
| Structured JSON output validation (`structured.py`, pydantic) | Ported | kotlinx.serialization |
| Guardrails / safety / prompt-injection handling (`guardrails.py`, `safety.py`) | Ported | |
| Self-improvement: error records, reflection, lessons (`learning.py`) | Ported | |
| Tracing (`tracing.py`) | Ported | Local log viewer |
| Evaluation suite (`evaluation.py`) | Ported | As instrumented tests |
| Reranking (`rerank.py`) | Ported | |

## Knowledge & memory

| Feature | Status | Android implementation / reason |
|---|---|---|
| Knowledge library, SQLite store (`storage/knowledge.py`) | Ported | Room (SQLite) |
| Semantic search via Chroma vector store | Substituted | Chroma has no Android build. Embeddings from the configured provider's `/embeddings` endpoint (or on-device ONNX Runtime MiniLM, Apache-2.0) stored in SQLite; cosine search in Kotlin |
| Long-term memory — LadybugDB knowledge graph with approval gate (`graph_memory.py`, `ladybug_bootstrap.py`) | Substituted | LadybugDB is a native desktop engine with no Android binary. Nodes/edges tables in SQLite with recursive CTE queries; same approval gate (`pending_store.py`) |
| Graph WAL recovery (`python -m kairos.graph_memory`) | Substituted | SQLite integrity check + repair action |
| Memory extraction (`memory_extract.py`) | Ported | |
| Data retention & deletion (`retention.py`) | Ported | WorkManager periodic purge |
| Predictive engine + MiroFish client (`predictive/*`) | Ported | HTTP client unchanged |
| SQL tool over CSV/XLSX via DuckDB (`sql_tool.py`) | Substituted | DuckDB has no official Android build. Import CSV/XLSX into in-app SQLite and query (Apache POI is too heavy; FastExcel-reader / own XLSX reader) |

## Web & media

| Feature | Status | Android implementation / reason |
|---|---|---|
| Web search, 10 numbered results (`ddgs`) (`web/__init__.py`) | Ported | DuckDuckGo HTML endpoint via OkHttp + Jsoup |
| Google search tool | Ported | Same API as desktop |
| Page scraping + LLM summary into library (`learn_web`, `scrape_page`) | Ported | Jsoup readability extraction |
| Audio MP3 / video MP4 download (`media_downloader.py`, yt-dlp) | Substituted | yt-dlp is Python. Use the FOSS **youtubedl-android** library (embeds yt-dlp + ffmpeg, GPL-3.0, used by Seal on F-Droid). Saved to `Music/` / `Movies/` via MediaStore |
| Attachments: PDF / DOCX / XLSX / images (`attachments.py`) | Ported | PdfRenderer + text extraction (PdfBox-Android, Apache-2.0), DOCX via zip+XML parse |
| Image generation (`imagegen.py`) | Ported | HTTP API |
| Artifacts folder: SVG diagrams & documents (`artifacts.py`) | Ported | App-specific storage + share sheet; SVG rendered in WebView |

## Browser Agent (v0.16.5)

| Feature | Status | Android implementation / reason |
|---|---|---|
| Browse: go/back/forward/reload (`browser_goto` …) | Substituted | Playwright/CDP do not run on Android. In-app **Android WebView** controlled by the agent |
| Read page, list form inputs, fill forms by label/name (`browser_read/form/fill`) | Substituted | WebView `evaluateJavascript` DOM scripts (same selectors as desktop) |
| Click / type / drag / keyboard / JS / mouse (`browser_click/action/js/mouse/design`) | Substituted | WebView JS + `MotionEvent` dispatch for coordinate clicks |
| Screenshot + Vision assist (`browser_screenshot`) | Substituted | WebView bitmap capture → vision model |
| CAPTCHA human-in-the-loop (`browser_captcha`) | Substituted | Agent pauses; user solves in the visible WebView; resume. **No automated solving.** |
| Detect installed browsers / attach to running Chromium (`browser_detect/start`, CDP) | **Excluded (proposed)** | Android apps cannot remote-control other apps' browsers (no CDP on Chrome for Android without USB debugging from a PC). The built-in WebView replaces this. On the PC, it remains available through PC remote control |
| Online design in EasyEDA | Substituted | Works in WebView. Desktop-class editors may be slow on phones |

## Communication

| Feature | Status | Android implementation / reason |
|---|---|---|
| Telegram bot + all commands (`telegram_bot.py`) | Ported | Bot API long-polling in a foreground service (user-toggled; battery-optimisation exemption requested) |
| Discord bot (`discord_bot.py`) | Ported | Gateway WebSocket via OkHttp, same foreground service |
| Email read / write / send (`email_client.py`) | Ported | Jakarta Mail for Android (`com.sun.mail:android-mail`, EPL/GPL+CE) IMAP/SMTP |
| Peer collaboration: encrypted P2P chat via call signs (`collab/*`) | Ported | Same protocol and crypto (X25519/Ed25519/AES-GCM via Tink or BouncyCastle) so phones and PCs interoperate |
| LAN discovery via zeroconf | Substituted | Android `NsdManager` (mDNS) |
| Tailscale transport (`collab/transport.py` calls the `tailscale` CLI) | Substituted | Cannot call the CLI. If the Tailscale app is running, its 100.x address is detected from network interfaces |
| CRDT shared projects (`pycrdt`) (`collab/project.py`) | Substituted | pycrdt (Yjs) is Python/Rust. Use **y-crdt via yrs JNI** if it builds reproducibly, else Automerge-Java. *Needs a dependency approval.* |
| QR code for call sign (`qrcode`) | Ported | ZXing core (Apache-2.0); also scan with CameraX |
| Webhooks inbound (loopback `127.0.0.1:8765`) (`webhook.py`) | Substituted | Embedded NanoHTTPD on loopback while the service runs; outbound webhooks unchanged. Android also accepts share/intents as triggers |
| Connectors: GitHub, Google, Notion (`connectors/*`) | Ported | REST calls |
| MCP client to MCP servers (`mcp_client.py`) | Substituted | stdio subprocess servers can't run on Android. **Streamable-HTTP/SSE MCP servers** supported |
| MCP server over stdio (`mcp_server.py`) | **Excluded (proposed)** | No stdio host can launch an Android app as a process. Equivalent access is given by the PC remote API |

## Devices & system

| Feature | Status | Android implementation / reason |
|---|---|---|
| Serial peripherals ESP32 / Arduino / RPi (`peripherals/serial_manager.py`, pyserial) | Substituted | **USB OTG** via `usb-serial-for-android` (MIT): CP210x, CH34x, FTDI, CDC-ACM. Bluetooth SPP serial added for wireless boards |
| Voice-to-text (Talk) + live voice meter | Substituted | Android `SpeechRecognizer` (falls back to Vosk offline model for F-Droid devices without Google speech) + `AudioRecord` level meter |
| Spoken replies (pyttsx3) | Substituted | Android `TextToSpeech` |
| Animated mood orb | Ported | Compose Canvas animation |
| Skills: create / view / edit / run / delete (`skills/*`) | Substituted | Desktop skills are Python files run in a subprocess or Docker. On Android: skills are **JavaScript** run in a sandboxed QuickJS engine (`quickjs-kt`, MIT) with the same tool API. Existing Python skills can run on the PC via remote control |
| Docker skill sandbox (`skills/docker_runner.py`) | **Excluded (proposed)** | No Docker on Android. QuickJS sandbox replaces it |
| File read/write/list confined to a root (`read_file` …) | Ported | App storage + user-picked folder via Storage Access Framework |
| Shell command tool (`run_command`, off by default) | Substituted | Runs `/system/bin/sh` inside the app sandbox (very limited toolset), still off by default |
| Computer-use task (`computer.py`, desktop mouse/keyboard) | **Excluded (proposed)** | Controlling other apps requires an AccessibilityService, which F-Droid and Play treat as high-risk and which cannot drive arbitrary apps reliably. Available on the PC through remote control |
| Git workflows (system `git`) (`git_tool.py`) | Substituted | **JGit** (EDL/BSD) — status/diff/log/commit/branch/checkout, opt-in push/pull with token |
| Watchdog + kill switch + heartbeat (`watchdog.py`, `kill.bat`) | Substituted | Foreground-service heartbeat with **Kill** in the persistent notification and in-app; Telegram `/kill` kept. `.bat` scripts excluded (Windows-only) |
| Keyring secret storage (Windows Credential Manager) | Substituted | Android Keystore-backed EncryptedSharedPreferences |
| Self-updater + Ed25519 signed bundle (`updater.py`, `release_signing.py`) | Substituted | Checks GitHub Releases, verifies the APK signature, hands the APK to the system installer. Disabled in the F-Droid flavour (F-Droid updates the app) |
| Install scripts, `run.bat`, `watchdog.bat`, `win_runtime.py` | **Excluded** | Windows-specific launchers; not applicable to an APK |

## New on Android

| Feature | Notes |
|---|---|
| PC remote control | Token-paired, TLS (self-signed, pinned at pairing via QR) remote API added to desktop Kairos; the phone can chat and submit jobs to the PC agent's queue over LAN / Tailscale. *Needs approval to change desktop code.* |
| Share-to-Kairos | Share a URL/text/file from any app to learn, summarise or attach |

## Summary

- Most features are ported or substituted; 5 capabilities are proposed for exclusion — browser detect/attach to external browsers, stdio MCP server, Docker skill runner, computer-use of other apps, Windows launcher scripts. Each excluded capability remains reachable on the PC through the remote-control feature.
- Dependencies needing explicit approval before use: youtubedl-android (bundles ffmpeg), yrs/Automerge for CRDT, Vosk offline speech model, ONNX Runtime for on-device embeddings.
