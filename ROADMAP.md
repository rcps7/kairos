# KAIROS Roadmap

Current version: **0.13.0** · License: MIT (PolyForm Noncommercial for the app) ·
Repo: https://github.com/rcps7/kairos

This document tracks completed work and the forward plan. Versions are cut as
GitHub Releases with the `KAIROS-agent-bundle.zip` asset; installed copies
self-update from Releases.

---

## Guiding principles

- **Security first.** Secrets in the OS keyring only; user data under `~/.kairos`
  and the storage root; the updater never touches user data.
- **Explicit consent** for risky actions (connections, files, LLM tasks, shell).
- **Least privilege.** Tools are capability-gated and confined; risky ones are
  off or read-only by default.
- **Durable + observable.** Long-running work persists (plans, scheduler, tasks)
  and is accounted for (usage, traces).
- **Provider-agnostic.** Any OpenAI-compatible endpoint; no forced vendor.

---

## Delivered

### Core (≤ 0.6.1)
- GUI (PySide6), CLI, Telegram; knowledge library (SQLite + Chroma).
- Web search/scrape, media download, email, serial peripherals, skills.
- Multi-provider LLM, council, predictive engine, watchdog kill switch,
  self-update, voice I/O.
- **Agent Characters** (v0.4.x): selectable personas with per-character tool
  access, approval-gated long-term memory.
- **LadybugDB knowledge graph** (v0.5.x): entities/relations/episodes, vector +
  traversal retrieval, approval queue, backfill of retained data.
- **Peer collaboration** (v0.6.x): call signs, TLS pinning + challenge-response,
  chat, file transfer, shared CRDT project, federated LLM, voice/video, Direct/
  Tailscale/ngrok transports, mDNS discovery.

### Plan A — Security hardening (v0.7.0)
- Telegram manual allowlist; skill name confinement + subprocess sandbox.
- Secrets never written to disk (keyring-only); email password migrated.
- Updater sha256 verification + safe archive extraction; config atomic writes +
  deep-merge defaults; bounded background extraction; UI-skill main-thread
  routing; watchdog kill-token + PID check; collab cert-expiry check.
- `.gitignore`, `SECURITY.md`, `tests/`, CI, `requirements.lock`.

### Plan B — Agent capabilities
- **Wave 1 (v0.9.0):** streaming responses; structured JSON output; durable
  plans/todo; platform tools (confined file ops, opt-in shell); tracing + daily
  token budgets.
- **Wave 2 (v0.10.0):** read-only text-to-SQL (DuckDB); stdio **MCP client**;
  GitHub + Notion connectors (keyring tokens).
- **Wave 3 (v0.11.0):** image generation; browser automation (Playwright
  render/screenshot); Discord channel (allowlist).
- **Wave 4 (v0.12.0):** sub-agents + `delegate`; offline evaluation harness;
  optional Docker skill sandbox.
- **Wave 5 (v0.13.0):** MCP **server** mode; browser actions (click/type/extract/
  screenshot); Google Drive connector; Telegram streaming; GUI **Agent Settings +
  Usage & Traces + Plans & Tasks** dialogs.
- **Release integrity (v0.13.1):** Ed25519-signed release bundles; the updater
  verifies the detached signature against a pinned in-repo public key
  (`kairos/release_signing.py`, `kairos/release_pubkey.pem`).

---

## Backlog (next)

### Near-term
| Item | Notes | Priority |
|------|-------|----------|
| **Native tool-calling coverage** | Enable `agent.native_tools` for more providers; surface in GUI settings. | Medium |

### Later
- **Browser agent actions** — click/type/form-fill (not just render).
- **Container sandbox polish** — bundled image, engine RPC hardening.
- **MCP server mode** — publish Kairos tools *as* an MCP server.
- **RAG improvements** — reranking, citations, per-character memory scoping.
- **Evaluation expansion** — golden agent tasks + LLM-judge, wired into CI.
- **Observability dashboard** — span timeline + cost charts in the GUI.
- **Portable packaging** — signed installer, checksum manifest.

### Hardening / hygiene
- **GUI refactor** — split `gui/main_window.py` into modules.
- **Replace remaining silent `except` blocks** in non-critical paths.
- **Rate/cost governance** — per-provider budgets and quotas (partly done).
- **Dependency automation** — Dependabot + scheduled lockfile refresh.

---

## Deferred / on-demand setup

These features work only after the noted setup; they are off by default:

- **Playwright browsers:** `python -m playwright install chromium`.
- **Discord:** create a bot, enable the *Message Content* intent, add
  `discord.allowed_user_ids`, token in keyring.
- **Image generation:** set `agent.image.enabled` + endpoint/model, key in keyring.
- **Docker sandbox:** install Docker, set `agent.skill_sandbox: "docker"`.
- **MCP servers:** configure `mcp.servers` (command + args).
- **Connectors:** enable `connectors.github/notion.enabled`, token in keyring.
- **Tailscale/ngrok:** install the binary; choose the transport in My Call Sign.

---

## Release process

1. Bump `kairos/__init__.py` `__version__`.
2. Update `README.md` / `ROADMAP.md` and regenerate `requirements.lock` if deps changed.
3. Rebuild `KAIROS-agent-bundle.zip` (package + root scripts; exclude venv,
   `__pycache__`, user data, `pen_fi.py`).
4. Commit + push, tag `vX.Y.Z`, create a GitHub Release with the bundle asset.
5. Installed copies pick it up via the in-app updater (verified by sha256).

---

## Tests & CI

- `tests/` covers security, config secrets, skills sandbox, planner, tools,
  guardrails, usage, SQL, MCP, connectors, image, Discord, sub-agents, evaluation.
- Run: `python -m pytest -q tests` and `python -m kairos.evaluation`.
- CI: `.github/workflows/ci.yml` (Ubuntu + Windows; Python 3.10/3.12; compile +
  tests).