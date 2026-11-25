# KAIROS v0.16.5 — Code Audit (errors, conflicts, Android porting issues)

Audited: tag `v0.16.5`, commit `63891e4`. Checks run: `python -m compileall kairos` (clean), `pyflakes kairos tests`, `pytest` (Python 3.13, Linux; GUI tests excluded because PySide6 needs a display; heavy optional deps chromadb/playwright/ladybug not installed).

Test result: **90 passed, 7 skipped, 1 failed** (GUI test module excluded) (`tests/test_browsers.py::test_running_ids_parsing`).

## A. Real defects in the desktop code

| # | Severity | Location | Problem | Suggested fix |
|---|---|---|---|---|
| A1 | **High** (runtime crash) | `kairos/gui/dialogs.py:753` (`SkillDialog.refresh_status_bar`) | Uses `KairosGUI`, which is defined in `gui/main_window.py` and is not imported into `dialogs.py` (star-imports only pull in `common`, `widgets`, `workers`). Called after creating/deleting a skill (lines 704, 742) → `NameError: name 'KairosGUI' is not defined`. | Replace with `if hasattr(parent, "refresh_status_bar"):` (avoids a circular import). |
| A2 | **Medium** (dependency) | `requirements.txt` vs `kairos/collab/protocol.py:11`, `kairos/structured.py`, `tests/test_wave1.py:7` | `pydantic` is imported unconditionally by the collaboration protocol but is not listed in `requirements.txt` (it only arrives transitively via chromadb). A clean install without chromadb fails to import collaboration and `test_wave1.py` fails to collect. | Add `pydantic>=2` to `requirements.txt`. |
| A3 | Low (test portability) | `tests/test_browsers.py:43-51` | The test mocks Windows `tasklist` CSV output, but `running_browser_ids()` (`kairos/browsers.py:174`) only parses that format when `sys.platform == "win32"`; on Linux/macOS it uses `ps`, so the test fails off Windows. | `@pytest.mark.skipif(sys.platform != "win32", ...)` or patch `sys.platform`. |
| A4 | Low (silent data loss) | `kairos/config.py:185-200, 267-275` | When no OS keyring backend exists (headless Linux, Android-like environments), `_keyring_set` returns False and secrets (API keys, Telegram token) are discarded with only a log warning, so the user re-enters them every run. | Surface a GUI warning, or offer an encrypted-file fallback. |
| A5 | Low (code quality) | `kairos/gui/workers.py:397`, `kairos/gui/dialogs.py:3267` | `sys` re-imported inside functions, shadowing the module import. | Remove the inner imports. |
| A6 | Low (code quality) | `kairos/gui/main_window.py:1681` | Local `before` assigned, never used. | Remove or use. |
| A7 | Info | whole package | 242 unused imports reported by pyflakes; GUI modules use `from .x import *`, which hides undefined-name errors like A1 from static analysis. | Replace star imports with explicit imports. |

## B. Conflicts / issues when implementing on Android

| # | Desktop dependency | Why it conflicts on Android | Resolution in the Android app |
|---|---|---|---|
| B1 | PySide6 / Qt GUI | No Android Qt-for-Python path that F-Droid accepts | Kotlin + Jetpack Compose UI (agreed rewrite) |
| B2 | `subprocess` usage in `browsers.py`, `git_tool.py`, `mcp_client.py`, `skills/runner.py`, `skills/docker_runner.py`, `watchdog.py`, `updater.py`, `collab/transport.py`, `toolkit.py` (`run_command`, `shell=True`) | Android apps cannot launch desktop binaries (git, tailscale, docker, browsers, python) | JGit, NsdManager/interface scan, QuickJS skills, HTTP MCP, foreground-service watchdog |
| B3 | `playwright` + CDP (`browser.py`) | No Playwright driver on Android; Chrome for Android exposes CDP only over USB to a PC | Agent-controlled WebView |
| B4 | `chromadb`, `ladybug`, `duckdb` | Native desktop engines with no Android builds | SQLite (Room) for vectors, graph and SQL tool |
| B5 | `keyring` | No Credential Manager | Android Keystore |
| B6 | `soundcard`, `SpeechRecognition`, `pyttsx3` | Desktop audio APIs | AudioRecord, SpeechRecognizer/Vosk, TextToSpeech |
| B7 | `pyserial` | No `/dev/tty*` access for apps | usb-serial-for-android over USB OTG |
| B8 | `yt-dlp` (needs ffmpeg) | Python + native ffmpeg | youtubedl-android (needs dependency approval) |
| B9 | Long-running threads (Telegram/Discord polling, scheduler, webhook server) | Android kills background work; Android 12+ restricts starting foreground services from background; Android 14 requires typed foreground services | `dataSync`/`specialUse` foreground service with a persistent notification; WorkManager for periodic jobs |
| B10 | Loopback webhook server `127.0.0.1:8765` | Only reachable on-device; port may be taken | Configurable port, only active while the service runs |
| B11 | Self-updater (`updater.py`, `.bat` swap) | Apps can't replace their own code; F-Droid forbids self-update | APK-installer flow in GitHub flavour only |
| B12 | `mcp_server.py` over stdio, `computer.py` | No stdio host; can't drive other apps without accessibility | Proposed exclusion; available via PC remote control |
| B13 | Thread-local guards and provider-call lock (`main.py`, `llm/client.py`) | Python threading model | Coroutine dispatchers + `Mutex` |
| B14 | Paths `%USERPROFILE%\.kairos` | Scoped storage | `Context.filesDir` + SAF for user folders |
