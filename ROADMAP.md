# KAIROS Roadmap

Current version: **0.16.3** · License: MIT (PolyForm Noncommercial for the app) ·
Repo: https://github.com/rcps7/kairos

This document tracks shipped functionality and the forward plan. Each release is
published on GitHub Releases with a **signed** `KAIROS-agent-bundle.zip` (plus
`.sig`); installed copies self-update from Releases after verifying the sha256
digest and the Ed25519 signature against the pinned public key.

Verification gates for every release: `python -m compileall kairos`,
`python -m kairos.evaluation` (18/18) and `python -m pytest -q tests` (82 passing).

---

## Guiding principles

- **Security first.** Secrets live only in the OS keyring; user data stays under
  `~/.kairos` and the storage root; the updater never touches user data and
  verifies both hash and signature.
- **Explicit consent** for risky actions (peer connections, incoming files, LLM
  tasks, shell, updates).
- **Least privilege.** Tools are capability-gated, path-confined, and off or
  read-only by default (shell off, writes confined, Docker optional).
- **Durable + observable.** Long-running work persists (plans, scheduler, tasks,
  pending memory) and is accounted for (usage + traces).
- **Provider-agnostic.** Any OpenAI-compatible endpoint; no forced vendor.
- **Untrusted by default.** Web, tool, file and peer content is wrapped/redacted
  and never treated as instructions.

---

## Shipped

| Version | Theme | Highlights |
|---------|-------|------------|
| 0.4.x | Agent Characters | Selectable personas, per-character tool access, approval-gated memory. |
| 0.5.x | Knowledge graph | LadybugDB entities/relations/episodes, vector + traversal, approval queue, backfill. |
| 0.6.x | Peer collaboration | Call signs, TLS pinning + challenge-response, chat, files, CRDT project, federated LLM, voice/video, Direct/Tailscale/ngrok, mDNS. |
| 0.7.0 | **Plan A — security hardening** | Telegram allowlist; skill confinement + subprocess sandbox; keyring-only secrets; atomic config; safe extraction; watchdog token; cert expiry; tests + CI + lockfile. |
| 0.8.0 | Agent foundations | Native tools + registry; scheduler; guardrails; usage accounting. |
| 0.9.0 | Plan B — Wave 1 | Streaming; structured JSON; plans/todo; file/shell tools; tracing + budgets. |
| 0.10.0 | Plan B — Wave 2 | Read-only text-to-SQL (DuckDB); MCP client; GitHub + Notion connectors. |
| 0.11.0 | Plan B — Wave 3 | Image generation; browser automation; Discord channel. |
| 0.12.0 | Plan B — Wave 4 | Sub-agents + `delegate`; evaluation harness; Docker skill sandbox. |
| 0.12.1 | Docs | `ROADMAP.md`. |
| 0.13.0 | Plan B — Wave 5 | MCP **server**; browser actions; Google Drive connector; Telegram streaming; Agent Settings / Usage / Plans GUI. |
| 0.13.1 | Release integrity | Ed25519-signed bundles verified by the updater against `kairos/release_pubkey.pem`. |
| 0.14.0 | Plan B — Wave 6 | GUI split (`common`/`widgets`/`workers`/`dialogs`); browser computer-use loop; RAG reranking. |
| 0.14.1 | CI fix | Pytest `pythonpath` + CI test deps; dropped stray BOM in `kairos/__init__.py`; numpy-free rerank cosine; GUI check/test skip when PySide6 absent. |
| 0.14.2 | Streaming tools | Streamed replies now execute tool requests (search/learn/scrape) instead of printing raw tool markup; parser also accepts `web_search("...")` form. |
| 0.15.0 | Concurrency | FIFO job queue (`kairos/jobs.py`): chat, skills and background actions run one-at-a-time without freezing the UI; per-thread chat guard; skills run off the UI thread; thread-local token usage; provider-call gate. |
| 0.16.0 | Workflows & web | **Plan/Execute modes** (Chat button + Plan/Execute dropdown; durable plans + autonomous step execution over the full toolkit). **Git workflows** (`git_tool.py`, system git, confined, opt-in push/pull). **Webhooks** (`webhook.py`: inbound triggers + outbound notifications, loopback `127.0.0.1:8765`, token/HMAC). **Draw & write** (`artifacts.py`: sanitized SVG diagrams + documents). **Web-page design** — persistent headed Playwright session with JS/mouse control (`browser.py`, `computer.py`) for editors like EasyEDA. **MCP server** now exposes resources & prompts and runs a headless engine (no PID/heartbeat/scheduler clash). |
| 0.16.1 | Graph recovery | Non-destructive knowledge-graph repair: `graph_memory.quarantine_wal` (backup + quarantine a corrupt WAL), auto-repair on startup (`graph_memory.auto_repair`), GUI **Repair / Rebuild**, Telegram `/graphrepair`, CLI `python -m kairos.graph_memory diagnose\|recover\|rebuild`. Source data (`knowledge.db`, `graph_pending.db`) is never touched. |
| 0.16.2 | Chat UX fixes | Fixed the Plan/Execute dropdown being disabled (mode state tracked explicitly; `activated` signal so re-picking works). Added a **provider & model selector** below the chat box with a live `GET /models` refresh, caching (`llm_models_cache`) and a daily background refresh. |
| 0.16.3 | Design tools | Web Designer dialog now has **Enable browser session** / **Enable JS** toggles and an **Install Chromium (Playwright)** button (fixes "Browser session is disabled"). Renamed **Drawings & Documents** → **Drawings & Design**; the dialog now **generates SVG from a description** via the LLM (`draw_from_description`) and adds a confirmed **Delete Selected**. |

Plan A is **fully complete**; Plan B's wave backlog is **fully complete**.

---

## Backlog

Legend: **P** = priority (H/M/L) · **E** = effort (S/M/L) · **Dep** = new dependency.

### Near-term
| Item | Notes | P | E | Dep |
|------|-------|---|---|-----|
| Native tool-calling coverage | Enable `agent.native_tools` per provider, add a GUI toggle, test on OpenAI/DeepSeek/Groq. | H | S | — |
| Per-provider cost governance | Daily/total token budgets per provider (extend `usage.py` + `ask_llm` guard). | M | S | — |
| RAG citations | Return source URL/title with reranked items and render them in answers. | M | S | — |
| Evaluation: golden agent tasks | Add end-to-end task checks + optional LLM-judge; wire into CI. | M | M | — |

### Later
| Item | Notes | P | E | Dep |
|------|-------|---|---|-----|
| Google Calendar connector | Extend `connectors/google.py` beyond Drive (same token). | L | S | — |
| Multi-channel bridges | Slack / WhatsApp, reusing the Discord allowlist pattern. | L | M | `slack-sdk` |
| Observability dashboard | Cost charts + span timeline in the GUI (Usage dialog → charts). | L | M | `PySide6.QtCharts` |
| Portable packaging | Signed installer + `SHA256SUMS` manifest. | L | M | — |
| Docker sandbox polish | Bundled image, hardened engine RPC over stdio. | L | M | Docker |
| Container/OS job-object isolation | Stronger-than-subprocess skill isolation on Windows. | L | L | — |

### Hygiene
- Replace remaining silent `except` blocks in non-critical paths with logging.
- Dependabot + scheduled `requirements.lock` refresh.
- Periodic HNSW index rebuild tuning for large graphs.

---

## Deferred / on-demand setup

Features that are shipped but need local setup; all are **off by default**:

- **Playwright browsers** — `python -m playwright install chromium` (browser
  automation, computer-use).
- **Discord** — create a bot, enable the *Message Content* intent, set
  `discord.allowed_user_ids`, store token in keyring.
- **Image generation** — set `agent.image.enabled` + endpoint/model; key in keyring.
- **Docker sandbox** — install Docker; set `agent.skill_sandbox: "docker"`.
- **MCP servers** — configure `mcp.servers` (command + args).
- **Connectors** — enable `connectors.<name>.enabled`; tokens in keyring
  (`github_token`, `notion_token`, `google_token`).
- **Peer transports** — install Tailscale/ngrok; choose the transport in
  *Collaborate → My Call Sign*.
- **Release signing** — private key at `~/.kairos/release_signing_key.pem`
  (never committed); public key pinned in `kairos/release_pubkey.pem`.

---

## Release process

1. Bump `kairos/__init__.py` `__version__`.
2. Update `README.md` / `ROADMAP.md`; regenerate `requirements.lock` if deps changed.
3. Run the gates: `compileall`, `python -m kairos.evaluation`, `pytest`.
4. Rebuild `KAIROS-agent-bundle.zip` (package + root scripts + `release_pubkey.pem`;
   exclude `venv`, `__pycache__`, user data, `pen_fi.py`).
5. **Sign** the bundle with Ed25519 (`kairos.release_signing.sign_file`).
6. Commit + push, tag `vX.Y.Z`, create a GitHub Release with the bundle **and**
   `KAIROS-agent-bundle.zip.sig` assets.
7. Installed copies update via the in-app updater (sha256 + signature verified).

> Rotating the signing key requires publishing the new `release_pubkey.pem` in the
> same release, before clients rely on it.

---

## Tests & CI

- `tests/` — security & config secrets, skills sandbox, planner, tools, guardrails,
  usage, SQL, MCP (client + server + resources/prompts), connectors, image, Discord,
  sub-agents, signing, GUI split, computer-use, RAG rerank, streaming tool loop,
  FIFO job queue, per-thread chat concurrency, **git tool, webhook, artifacts,
  chat modes, graph WAL recovery**. 
- `python -m kairos.evaluation` — 18 offline smoke checks.
- CI: `.github/workflows/ci.yml` (Ubuntu + Windows; Python 3.10/3.12; compile + tests).

---

## Non-goals

- Hosting LLMs or providing compute; Kairos orchestrates external providers.
- A central server/account system; collaboration is peer-to-peer.
- Distributing API keys or credentials of any kind.
