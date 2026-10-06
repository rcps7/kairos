# KAIROS Roadmap

Current version: **0.14.0** · License: MIT (PolyForm Noncommercial for the app) ·
Repo: https://github.com/rcps7/kairos

This document tracks shipped functionality and the forward plan. Each release is
published on GitHub Releases with a **signed** `KAIROS-agent-bundle.zip` (plus
`.sig`); installed copies self-update from Releases after verifying the sha256
digest and the Ed25519 signature against the pinned public key.

Verification gates for every release: `python -m compileall kairos`,
`python -m kairos.evaluation` (12/12) and `python -m pytest -q tests` (38 passing).

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
| MCP resource/prompt support | Beyond tools: list/read resources and prompts from MCP servers. | M | M | — |

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
  usage, SQL, MCP (client + server), connectors, image, Discord, sub-agents,
  signing, GUI split, computer-use, RAG rerank.
- `python -m kairos.evaluation` — 12 offline smoke checks.
- CI: `.github/workflows/ci.yml` (Ubuntu + Windows; Python 3.10/3.12; compile + tests).

---

## Non-goals

- Hosting LLMs or providing compute; Kairos orchestrates external providers.
- A central server/account system; collaboration is peer-to-peer.
- Distributing API keys or credentials of any kind.
