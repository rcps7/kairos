# KAIROS Android — Round 2 review (Browser Agent / WebView / USB serial + PC remote)

Reviewed commits: `5550b89` (job service), `d5c9ab9` (Browser Agent on WebView + USB OTG serial),
and the desktop remote API from `2ae6741`.

Status legend: **fixed** = changed in this round; **noted** = accepted trade-off, documented.

## Critical / high

| # | Area | Problem | Fix |
|---|---|---|---|
| H1 | `kairos/remote_api.py` | **Replay bypass (critical).** The nonce cache was keyed on the base64 *string* while decryption used the *bytes*; `urlsafe_b64decode` ignores non-alphabet characters and accepts `+ /` as well as `- _`, so an attacker could change `n` and replay a captured request. | Nonces are keyed on the raw bytes (`nonce.hex()`); requests are decoded with a strict canonical base64url decoder. A repeat now returns the cached sealed reply (idempotent, not re-executed) or `401` if the reply has expired. Regression tests added, including junk-character and alphabet-aliasing attempts. |
| H2 | `kairos/main.py` | The remote server was never stopped in `Engine.shutdown()`, leaking the port/thread. | `self.remote.stop()` added to `shutdown()`. |
| H3 | `serial/Serial.kt`, `serial/UsbSerial.kt` | `write`/`readOnce`/`configure` were unsynchronised and `close()` could release the interface mid-transfer → data loss or a native crash. | Per-connection `@Synchronized` access plus a `closed` flag (`markClosed()`) checked before every transfer; `close()` marks the port closed before releasing it. |
| H4 | `serial/UsbSerial.kt` | `claimInterface` results were ignored, so `open` reported success without claiming the data interface. | The data (and CDC control) interface must claim; on failure the connection is released, closed and a clear error is thrown. |

## Medium

| # | Area | Problem | Fix |
|---|---|---|---|
| M1 | `agent/DeviceTools.kt` | Prompt injection could drive a connected board (`serial_write`/`serial_send` were ungated). | New **"Allow agent serial writes"** setting (default **off**), enforced in `SerialTools`, plus a 64 KB write cap. User-initiated UI writes are unaffected. |
| M2 | `agent/Engine.kt` | `ADVANCED_PROTOCOL` advertised every tool to every character. | Replaced with `advancedProtocol(caps)`, filtered by the active character's capabilities. |
| M3 | `browser/WebViewPage.kt` | Weak WebView hardening and a `data:` navigation gap. | `MIXED_CONTENT_NEVER_ALLOW`, no file/universal file access, no JS-opened windows, no saved passwords, debugging disabled; navigation restricted to http/https/about; `load()` re-validates the scheme. |
| M4 | `browser/WebViewPage.kt` | A renderer crash or load error left callers waiting until timeout. | `onReceivedError` and `onRenderProcessGone` now complete the wait and drop the dead WebView. |
| M5 | `browser/Browser.kt` | `browser_inputs` returned typed values to the LLM; `browser_mouse` used device pixels where CSS pixels are required. | Input values are masked (checkbox/radio/select state is still shown); coordinates are divided by `devicePixelRatio`; inputs now include `rect`. |
| M6 | `browser/Browser.kt` | `browser_action` had no step cap and aborted the whole list on one bad step. | Steps are capped at 50 and each step is isolated in try/catch. |
| M7 | `serial/UsbSerial.kt` | USB permission result was never consumed and detach was unhandled. | A receiver is registered for the permission broadcast and `ACTION_USB_DEVICE_DETACHED` (which closes the port). Locale-safe `%04x:%04x` formatting. |
| M8 | `ui/*` | Serial screen leaked the previous port when the selection changed and could steal the agent's bytes. | The open port is tracked by id; the live read pauses while an agent job is running; a **\n** toggle and **Clear log** were added. |

## Verified correct

HKDF-SHA256/AES-256-GCM matches the Kotlin client; AAD binds the timestamp and nonce; strict
`v`/`kid`/length checks; 120 s skew; per-IP rate limit; loopback/private source filter; keyring-only
secret; off by default; `kill` requires `confirm=true`. Browser tool names mirror the desktop;
CAPTCHA hand-off never auto-solves; script arguments are JSON-escaped; URL schemes restricted;
serial chip encodings and driver sequences are unit-tested.

## Notes / accepted trade-offs

- **Cleartext HTTP** is permitted in `network_security_config.xml` because users configure their own
  LAN endpoints (local LLM servers, the paired PC) at arbitrary private addresses. Public providers
  use HTTPS.
- The UI live read and an agent `serial_read` can still interleave on the same port; the per-port
  lock keeps each transfer atomic and the UI pauses during agent jobs.
- Android 12+ background-start restrictions may prevent the job service from starting while the app
  is backgrounded; jobs still run in-process while the app is visible.

## Desktop audit (AUDIT_v0.16.5.md) items fixed in this round

- A1 `gui/dialogs.py` — `SkillDialog.refresh_status_bar` referenced `KairosGUI` (NameError) → now
  duck-typed with `hasattr`.
- A2 `requirements.txt` — added `pydantic>=2`.
- A3 `tests/test_browsers.py` — Windows-only `tasklist` test is now skipped elsewhere.
- A8 `main.py` `fallback_models` — an empty API URL no longer matches every preset.
