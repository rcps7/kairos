# KAIROS — Self-Evolving AI Agent

KAIROS is a lightweight, self-improving AI agent for your workstation. It searches the
web, scrapes and summarizes articles into a persistent knowledge library, downloads
audio/video, reads and sends email, controls serial peripherals (ESP32 / Arduino /
Raspberry Pi), talks to you over Telegram, and learns from its own errors — all guarded
by a watchdog with a kill switch.

Licensed under the **PolyForm Noncommercial License 1.0.0** (free for personal/non-commercial use).

---

## Table of Contents

1. [Features](#features)
2. [System Requirements](#system-requirements)
3. [Installation](#installation)
4. [First Run — Setup Wizard](#first-run--setup-wizard)
5. [Running the Agent](#running-the-agent)
6. [The GUI](#the-gui)
7. [Telegram Commands](#telegram-commands)
8. [LLM Providers (multi-provider)](#llm-providers-multi-provider)
9. [Skills — Creating & Managing](#skills--creating--managing)
10. [Agent Characters](#agent-characters)
11. [Knowledge Library & Media Storage](#knowledge-library--media-storage)
12. [Data Retention & Deletion](#data-retention--deletion)
13. [Email](#email)
14. [Peripheral Control (Serial USB)](#peripheral-control-serial-usb)
15. [Watchdog & Kill Switch](#watchdog--kill-switch)
16. [Self-Improvement & Learning](#self-improvement--learning)
17. [Configuration File](#configuration-file)
18. [Project Structure](#project-structure)
19. [Creating a Distributable ZIP](#creating-a-distributable-zip)
20. [Uploading to GitHub (what NOT to commit)](#uploading-to-github-what-not-to-commit)
21. [Troubleshooting](#troubleshooting)
22. [License](#license)
23. [Contributing](#contributing)

---

## Features

| Capability | Interface |
|------------|-----------|
| Web search (10 numbered results with title + link + description) | GUI / Telegram |
| Page scraping + LLM summarization into the knowledge library | GUI / Telegram |
| Knowledge library (SQLite + Chroma vector store for semantic search) | automatic |
| Audio (MP3) / video (MP4) download | GUI / Telegram |
| Email read / write / send (on request only) | GUI / Telegram |
| Serial peripheral control (ESP32 / Arduino / RPi) | GUI / Telegram |
| Multi-provider LLM (Moonshot/Kimi, DeepSeek, OpenAI, any OpenAI-style API) | GUI / Telegram |
| Agent Characters — selectable personas with per-character tool access | GUI / Telegram |
| Long-term memory — LadybugDB knowledge graph with approval gate | GUI / Telegram |
| Peer collaboration — P2P encrypted chat via call signs | GUI / Telegram |
| Skill system — create, view, edit, run, delete skills | GUI / Telegram |
| Self-improvement — records errors, reflects, stores lessons | GUI / Telegram |
| Watchdog with kill switch + heartbeat monitoring | `kill.bat`, GUI, Telegram `/kill` |
| Voice-to-text (Talk button) + spoken replies + live voice meter | GUI |
| Animated mood orb (thinking/speaking/success/error) | GUI |
| Plan & Execute modes — **Chat** button + **Plan/Execute** dropdown beside the chat box | GUI / Telegram |
| Git & version-control workflows (system `git`, confined, opt-in push/pull) | GUI / Telegram |
| Webhooks — inbound triggers + outbound notifications (loopback `127.0.0.1:8765`) | HTTP / GUI / Telegram |
| Draw diagrams (SVG) & write documents to the Artifacts folder | GUI / Telegram |
| Web-page design via a persistent, headed browser (e.g. EasyEDA) | GUI / Telegram |
| MCP server — resources, prompts & tools over stdio | `python -m kairos.mcp_server` |
| CLI + GUI front-ends | `run.bat` / `python -m kairos.main` |

---

## System Requirements

- **Windows 10/11** (primary target) — Linux/macOS also work via the Python entry point
- **Python 3.9+** (3.11+ recommended)
- Internet connection (for LLM API and web access)
- Optional: a serial device (ESP32/Arduino/RPi) for peripheral control

---

## Installation

1. Install Python from <https://www.python.org/downloads/> — **check "Add Python to PATH"**
   during installation.
2. Extract the project folder (e.g. `KAIROS-agent-bundle.zip`) anywhere.
3. Double-click **`install.bat`**, or run in a terminal inside the folder:

   ```bat
   install.bat
   ```

   This creates a virtual environment (`venv`) and installs all dependencies from
   `requirements.txt`. It may take a few minutes.

---

## First Run — Setup Wizard

Launch the agent:

```bat
run.bat
```

On first launch, a setup dialog asks for:

1. **Telegram Bot Token** (optional) — create a bot with [@BotFather](https://t.me/BotFather)
   and paste the token, or click **Skip** to proceed without Telegram.
2. **LLM provider** (optional) — pick a provider from the dropdown (Moonshot/Kimi,
   DeepSeek, OpenAI, OpenRouter, Groq, or Custom). The API URL and model name are
   filled in automatically and are editable. You only need to enter the **API key**.
   You can also click **Skip LLM** to continue without one.

Skipping either step does not stop the installation — you can add or change them
later via `Edit → LLM Providers` in the GUI.

These are stored securely:
- API keys go to the OS keyring (Windows Credential Manager).
- Non-secret settings go to `%USERPROFILE%\.kairos\config.json`.

> **Tip:** you can add more providers or switch the active one later via
> `Edit → LLM Providers` in the GUI.

---

## Running the Agent

| Action | Command |
|--------|---------|
| Launch Kairos + watchdog | `run.bat` |
| Watchdog only | `watchdog.bat` |
| Kill switch (emergency shutdown) | `kill.bat` |
| Linux/macOS | `./run.sh` (or `python -m kairos.main`) |

`run.bat` opens two windows:
1. **KAIROS** — the main GUI.
2. **Kairos Watchdog** — the background monitor enforcing the kill switch.

---

## The GUI

The main window has a **dark theme with fluorescent-green text and grey-white
buttons**, and is divided into three panes:

```
+--------------------------------------------------------------+
| File  Edit  View  Window  Help         (menu bar)           |
+--------------------------------------------------------------+
|  SKILL TOOLS   |              CONSOLE          |   SYSTEM     |
|  (left)        |           (chat box)          |  (right)     |
+--------------------------------------------------------------+
|                         status bar                           |
+--------------------------------------------------------------+
```

- **Left pane** — quick skill tools: Web Search, Learn From Page, Email, Downloads,
  Peripheral Control, Self-Reflect, Create/View Skills.
- **Center pane** — the chat console. Type instructions directly; responses appear
  here. Search results are numbered with clickable links. A **Clear** button empties
  only the visible chat (storage and memory are untouched).
- **Mode selector** (beside the input) — a **Chat** button (the default, independent
  mode) and a **Plan / Execute** dropdown. *Plan* produces a durable, step-by-step
  plan without running it; *Execute* creates the plan and then autonomously runs
  each step using the full toolkit (web, git, artifacts, browser, memory). The
  choice is remembered. The **Council (multi-LLM)** checkbox, when ticked, takes
  precedence over the mode selector.
- **Provider & model selector** (below the chat box) — pick the active **LLM
  provider** and its **model** from dropdowns. The model list is cached and
  refreshed from the provider's `GET /models` endpoint; click **Refresh models**
  to fetch the latest list, and newer models appear automatically (the active
  provider is refreshed once a day in the background). The model box is editable,
  so you can also type a model id.
- **Right pane** — system status (active character, active LLM, skill count, storage
  path), quick-action buttons, and the red **KILL SWITCH** button.
- **Toolbar** — Search, Learn URL, Download, Skills, Providers, Peripherals,
  Character, Self-Reflect. Tools the active character may not use are greyed out.

### Voice & mood

- **Talk button** (next to Send) — hold/click to talk; your speech is converted to
  text and sent as a message. A live **voice meter** shows your input level.
- **Spoken replies** — KAIROS reads its answers aloud (Windows SAPI voice) while also
  showing the text; the meter animates while it speaks.
- **Mood orb** (top-right of the console) — an animated indicator that reflects the
  agent's state:
  - grey = idle
  - cyan = listening
  - orange = thinking
  - red = deep/prolonged thinking (complex tasks)
  - green = speaking / task success
  - red flash = error

### Menus

| Menu | Actions |
|------|---------|
| **File** | New Session (`Ctrl+N`), Exit, Kill Switch (Emergency) |
| **Edit** | LLM Providers, Storage Settings, Email Settings, Telegram Settings…, Peripheral Control, Retention (Delete Expired), Skills, Agent Character…, Knowledge Graph…, Pending Knowledge…, Git & Version Control…, Webhook… |
| **Tools** | Predictive Engine, Web Designer (browser)…, Drawings & Design… |
| **Agent** | Settings…, Usage & Traces…, Plans & Tasks… |
| **View** | Self-Reflect, Show Lessons, Refresh Status |
| **Window** | Minimize, Maximize |
| **Help** | About Kairos |

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/chat <text>` | Talk to the LLM |
| `/search <query>` | Web search (numbered results with description) |
| `/learn <url>` | Scrape + summarize a page into the knowledge library |
| `/download <url>` | Download media — inline MP3/MP4 buttons |
| `/skills` | List installed skills |
| `/runs <skill>` | Run a skill |
| `/newskill <name> <desc>` | Generate a skill (Approve/Reject buttons) |
| `/mail` | Read latest email |
| `/sendmail <to> <subject> \| <body>` | Send email |
| `/expired` | List items due for retention deletion |
| `/remember <text>` | Save a note/fact to retained data |
| `/memory` | List retained data |
| `/providers` | List LLM providers |
| `/setllm <id>` | Switch active LLM provider |
| `/character` | Show the active character and list all characters |
| `/setcharacter <id>` | Switch the active agent character |
| `/graph <query>` | Search the long-term knowledge graph |
| `/pending` | Review/approve/reject proposed knowledge |
| `/graphstats` | Knowledge graph counts |
| `/graphdel <id>` | Delete a graph entity |
| `/reflect` | Analyze recent errors and store a lesson |
| `/lessons` | Show lessons learned |
| `/ports` | List serial ports |
| `/open <port> [baud]` | Open a serial port |
| `/send <port> <text>` | Write data to a port |
| `/read <port>` | Read data from a port |
| `/close <port>` | Close a serial port |
| `/kill` | Kill switch (with confirmation) |
| `/mode <chat\|plan\|execute>` | Set the agent mode |
| `/planagent <goal>` | Produce a durable plan (no execution) |
| `/execute <goal>` | Plan then autonomously execute every step |
| `/git <status\|diff\|log\|branches\|commit <msg>\|branch <n>\|checkout <n>\|pull\|push>` | Git workflows |
| `/write <file> \| <content>` | Save a document to the Artifacts folder |
| `/draw <name> \| <svg or description>` | Draw an SVG diagram |
| `/artifacts` | List drawings & design files |
| `/webhooks` | Show webhook configuration |
| `/design <url> \| <goal>` | Drive a headed browser to design a web page |

---

## LLM Providers (multi-provider)

KAIROS supports **any OpenAI-compatible chat API**. Each provider entry has:

- `provider_id` — a short name (e.g. `moonshot`, `deepseek`, `openai`)
- `api_url` — the chat completions endpoint
- `api_key` — stored in the OS keyring
- `model` — the model name

### Examples

| Provider | API URL | Model |
|----------|---------|-------|
| Moonshot (Kimi) | `https://api.moonshot.ai/v1/chat/completions` | `kimi-k3` |
| DeepSeek | `https://api.deepseek.com/chat/completions` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` |

### Managing providers

- **GUI:** `Edit → LLM Providers` → Add / Set Active / Remove.
- **GUI (chat box):** the **Provider** / **Model** dropdowns below the chat input
  switch the active provider and model directly, and **Refresh models** pulls the
  provider's live model list (`GET <api_url minus /chat/completions>/models`).
  The list is cached in `llm_models_cache` and refreshed in the background once a
  day; known models are shown as a fallback when the endpoint is unreachable.
- **Telegram:** `/providers` (list) and `/setllm <id>` (switch).

---

## Skills — Creating & Managing

Skills are Python files stored in `<storage_root>/Kairos/Skills/`. They are
auto-loaded at startup and can be created, viewed, edited, run, and deleted from
the GUI (`Edit → Skills`).

### Create a skill (GUI)

1. `Edit → Skills` → **+ New Skill**.
2. Enter a name (lowercase, underscores) and a description.
3. KAIROS asks the LLM to generate a working implementation and shows it in the code
   editor.
4. Review it → **Save & Reload** → **Run Skill** to test.

### Skill anatomy

```python
from kairos.skills.base import Skill
from datetime import datetime

class Greet(Skill):
    name = "greet"
    description = "Say hello with the current time"

    def run(self, engine, **kwargs):
        return f"Hello! The time is {datetime.now().strftime('%H:%M:%S')}"
```

### Rules

- Subclass `Skill` from `kairos.skills.base`.
- Set `name` (invocation id) and `description`.
- Implement `run(self, engine, **kwargs)` returning a string.

### The `engine` object

Inside `run()`, the `engine` object exposes:

- `ask_llm(prompt)`, `search_web(query)`, `scrape_page(url)`, `learn_from_page(url)`
- `download_media(url, fmt)`
- `read_email(limit)`, `send_email(to, subject, body)`
- `list_ports()`, `open_port(device, baud)`, `write_port(device, text)`,
  `read_port(device)`
- `knowledge` (knowledge store), `media` (media store)

### Description guidelines

- **One clear, verb-first sentence** — `"Summarize a web page into bullet points"`.
- For **multi-step skills**, list steps in order:
  `"Search the web, open the top result, and return a summary"`.
- Keep it ~5–20 words, no code.

### Delete a skill

`Edit → Skills` → select the skill → **Delete** (with confirmation). The file is
removed and the skill is unloaded from memory.

---

## Agent Characters

An **Agent Character** is a selectable persona that controls *how* KAIROS behaves.
Exactly one character is active at a time, and every user-facing LLM call (chat,
web summaries, learned pages, predictions, and the council's final answer) is
made **under that character's system prompt**. Selecting **General** gives the
original all-purpose behavior.

### Built-in characters

Shipped with KAIROS and seeded on first run:

| Character | Purpose |
|-----------|---------|
| General | All-purpose agent with full tool access |
| Medical Assistant | Evidence-based medical answers with inline citations |
| Law Assist | Jurisdiction-aware legal research with source links |
| Electronic Specialist | Circuit/PCB design and embedded firmware |
| Astrophysics Expert | Astrophysics & cosmology, LaTeX math, telescope citations |
| Quantum Physics Expert | Quantum mechanics/computing & particle physics |
| Genetics Expert | Genomics/bioinformatics with bioethical safeguards |
| AI Expert | ML research, architectures, and cited SOTA benchmarks |

Built-in characters are **read-only** (they cannot be edited or deleted). You can
**Duplicate** one to create an editable copy, or **Restore Defaults** to reset a
damaged built-in to its packaged version.

### Custom characters

Add, edit, and delete your own characters freely:

- **GUI:** `Edit → Agent Character…` (or the toolbar **Character** button) →
  **New** / **Duplicate** / **Save** / **Delete** / **Set Active**.
- **Telegram:** `/character` (list + active) and `/setcharacter <id>` (switch).

Each profile defines a name, icon, description, system prompt, an optional
disclaimer (shown when you switch), and **which tools it may use** (web search,
learn page, downloads, email, peripherals, predict, council, skills, memory).
Tools the active character is not allowed to use are disabled in the GUI and
refused over Telegram.

### Storage layout

Profiles are plain JSON, one folder per character:

```
<storage_root>/Kairos/AGENT_CHARACTER/<character_id>/character.json
```

The active character id is saved in `%USERPROFILE%\.kairos\config.json` as
`active_character`.

### Example profile

```json
{
  "id": "medical_assistant",
  "name": "Medical Assistant",
  "icon": "\ud83e\ude7a",
  "description": "Evidence-based medical AI with inline citations.",
  "system_prompt": "You are KAIROS operating as a specialized Medical Assistant...",
  "disclaimer": "General medical information only — not a diagnosis or prescription.",
  "capabilities": ["web_search", "learn_web", "memory", "predict", "council", "skills_run"],
  "skills": null,
  "builtin": true,
  "version": 1
}
```

`"capabilities": null` means *all tools allowed*. `"skills": null` means *all
skills allowed*; otherwise it is a whitelist of skill names.

---

## Long-Term Memory (Knowledge Graph)

Kairos keeps a persistent, relationship-aware memory in **LadybugDB** (the
embedded graph database formerly known as Kuzu). It stores entities,
relationships and episodic notes, and feeds a compact, relevant context into
LLM calls, skill generation, the council and predictions — so Kairos has the
"full picture" of your context before it acts.

### How it works

1. After a substantive chat turn (and on `/remember`, learned pages,
   predictions and reflections) Kairos asks the LLM to extract durable
   **entities** and **relationships**.
2. The proposal is **not stored automatically** — it is queued and you are
   notified. Nothing enters the graph until **you explicitly approve it**.
3. On approval the entities are de-duplicated (semantic vector match) and
   merged into the graph; relationships are linked by predicate.

Semantic retrieval uses Ladybug's native HNSW **vector index** (embeddings from
the same all-MiniLM-L6-v2 model Kairos already uses) plus graph traversal, so
results are both semantically *and* relationally relevant.

### Managing memory

- **GUI:** the toolbar **Graph** button (or `Edit → Knowledge Graph…`) lets you
  **search**, **edit** entities, **delete** entities/relations/notes and
  **clear** the graph. `Edit → Pending Knowledge…` is the approval queue, where
  each proposal can be edited (JSON) before you **approve** or **reject** it.
- **Telegram:** `/graph <query>`, `/pending`, `/graphstats`, `/graphdel <id>`,
  plus inline **Approve / Reject** buttons on notifications.

### Generic, low-cost model

Entity *kind* and relationship *predicate* are open strings held as data (not
schema), so new types never require migrations and de-duplication keeps the
graph small — minimising LLM cost.

### Storage & configuration

- Graph: `~/.kairos/graph.lbdb` · pending queue: `~/.kairos/graph_pending.db`
  (user data — preserved across app updates).
- Native runtime (the Ladybug shared library + OpenSSL/MSVC deps) is assembled
  once into `~/.kairos/lbug/`.
- Config (`graph_memory`): `enabled`, `require_approval` (default true),
  `auto_approve` (default false), `extract_on_chat`, `auto_repair` (default true),
  and per-area reuse toggles `use_in_chat`, `use_in_tools`, `use_in_skills`,
  `use_in_council`, `use_in_predict`, plus `max_nodes`, `max_memories`,
  `dedup_distance`.

> Note: the Ladybug **full-text (FTS)** extension aborts the process on the
> current Windows/Python 3.14 build, so keyword search falls back to a
> Python-side scan; vector search and traversal are unaffected.

### Repair / recovery

The graph is a **derived** store — your durable data (retained memories and
document summaries) lives in `knowledge.db`, and proposed knowledge lives in
`graph_pending.db`. Neither is ever touched by graph repair, so **no saved data
is lost**.

If the graph fails to open (for example a corrupt write-ahead log), Kairos logs
a **warning** and keeps running with the graph disabled — a broken graph never
blocks startup. To fix it:

- **GUI:** `Edit → Knowledge Graph… → Repair / Rebuild`.
- **Telegram:** `/graphrepair`.
- **CLI:**
  ```bat
  python -m kairos.graph_memory diagnose   REM read-only check
  python -m kairos.graph_memory recover    REM quarantine a corrupt WAL (backup kept)
  python -m kairos.graph_memory rebuild    REM recover + re-ingest knowledge.db
  ```

Repair is **non-destructive**: the database file is copied to a timestamped
`graph.lbdb.bak-<ts>` and a corrupt WAL is renamed to
`graph.lbdb.wal.corrupt-<ts>` — nothing is deleted, and all data committed up to
the last checkpoint is preserved. `rebuild` additionally re-ingests retained
memories and document summaries. On startup, `graph_memory.auto_repair` (default
`true`) auto-quarantines a corrupt WAL (backup kept) and retries once.

---

## Peer Collaboration

Two Kairos instances can connect **peer-to-peer** and chat over an encrypted
link — no central server required. Each install has an identity key; you share a
**call sign** that encodes how to reach you plus the fingerprint of your key.

- **Call sign:** `K1!<LABEL>!<transport>!<host>!<port>!<FP>!<CK>` (copy/paste or
  QR). *Collaborate → My Call Sign…*.
- **Connect:** *Collaborate → Connect to Peer…*, paste the peer's call sign.
- **Approval:** the peer sees an incoming request with a fingerprint and a
  6-digit **SAS** (verify it out-of-band, e.g. by voice) and must **Accept**
  (GUI popup or Telegram inline buttons).
- **Security:** TLS with certificate **fingerprint pinning** (mitM protection),
  challenge–response client authentication, SSRF host policy (loopback/
  link-local/metadata blocked; private/LAN blocked unless enabled), strict
  message validation and frame-size caps.
- **Transports:** Direct/LAN (binds your LAN or Tailscale IP, not 0.0.0.0),
  Tailscale, and **ngrok** (TCP relay for hard NATs). Optional **LAN discovery**
  (`Collaborate → Discover Peers…`) finds peers via mDNS.

### What you can do together
- **Encrypted chat** (Chat tab).
- **File transfer** — consent-gated, SHA-256-verified, saved to a quarantine
  folder (`Collaborate → Send File to Peer…`).
- **Shared project** — CRDT-synced notes and tasks (Project tab), conflict-free.
- **Federated LLM** — each side answers with its own model
  (`Collaborate → Ask Peer's LLM…`), off by default with per-task approval.
- **Voice & video** — 16 kHz PCM voice and JPEG video over the encrypted link
  (Call tab; local opt-in, mute/camera toggles).

---

## Agent Capabilities

Kairos includes standard agentic building blocks:

- **Native tool-calling** — an OpenAI-style tool registry (`kairos/toolkit.py`)
  for web search, page learning, scraping, memory and prediction. Enable with
  `agent.native_tools` in the config (falls back to the built-in text tool
  protocol when off).
- **Guardrails** — prompt-injection detection, secret/PII redaction, and
  untrusted-content wrapping for everything fetched from the web, tools,
  attachments or peers (`kairos/guardrails.py`).
- **Usage & cost accounting** — per-call token usage stored locally; view with
  `/usage` on Telegram (`kairos/usage.py`).
- **Scheduler** — durable interval tasks (ask the LLM or run a skill) with
  Telegram control: `/task <name> <minutes> | <prompt>`, `/tasks`,
  `/deltask <name>` (`kairos/scheduler.py`).
- **Streaming** — responses stream token-by-token into the console
  (`agent.streaming`).
- **Structured output** — validated JSON with automatic retries
  (`kairos/structured.py`).
- **Plans / todo** — durable multi-step plans (`kairos/planner.py`), with
  Telegram `/newplan`, `/plans`, `/plan`.
- **Platform tools** — confined `read_file`/`write_file`/`list_dir` and an
  opt-in, sandboxed `run_command` (`agent.file_root`, `agent.allow_file_write`,
  `agent.allow_shell`).
- **Tracing & budgets** — per-call spans (`kairos/tracing.py`) and an optional
  daily token budget (`agent.budgets.daily_tokens`).

Planned additions: MCP resource/prompt **subscriptions**, an HTTP/SSE MCP
transport, and a portable signed installer.

### Wave 2 (connectors & data)
- **Text-to-SQL** — read-only DuckDB queries over registered CSV/Parquet files
  (`kairos/sql_tool.py`, tool `sql_query`).
- **MCP client** — connect stdio MCP servers and expose their tools
  (`kairos/mcp_client.py`; config `mcp.servers`).
- **Data connectors** — GitHub and Notion over httpx with keyring-stored tokens
  (`kairos/connectors/`; tools `github_*`, `notion_search`; config
  `connectors.*.enabled`).

### Wave 3 (media & channels)
- **Image generation** — OpenAI-compatible images endpoint via httpx
  (`kairos/imagegen.py`; tool `generate_image`; Telegram `/image`; config
  `agent.image`). Disabled until enabled + an API key is set.
- **Browser automation** — headless Chromium render/screenshot
  (`kairos/browser.py`; tools `browser_fetch`, `browser_screenshot`). Requires
  `python -m playwright install chromium` once.
- **Discord channel** — optional bot with a manual user allowlist mirroring
  `!chat`, `!search`, `!remember` (`kairos/discord_bot.py`; config `discord`).

### Wave 4 (orchestration & quality)
- **Sub-agents** — named specialists (researcher, coder, analyst, writer,
  planner) reachable via the `delegate` tool (`kairos/agents.py`).
- **Evaluation harness** — offline smoke checks of the security/agent
  primitives (`kairos/evaluation.py`; run `python -m kairos.evaluation`).
- **Docker skill sandbox** — optional stronger isolation for skills
  (`agent.skill_sandbox: "docker"`; falls back to the subprocess sandbox).

### Wave 5 (access & orchestration)
- **MCP server mode** — expose Kairos tools over stdio: `python -m kairos.mcp_server`.
- **Browser actions** — click/type/wait/extract/screenshot (`kairos/browser.py`;
  tool `browser_action`).
- **Google Drive connector** — token-based file search (`kairos/connectors/google.py`;
  tool `google_search`).
- **Telegram streaming** — `/chat` streams the reply in place.
- **Agent Settings GUI** — configure agent flags, MCP, connectors, image gen and
  Discord; plus **Usage & Traces** and **Plans & Tasks** dialogs (menu **Agent**).

### Wave 6 (structure & retrieval)
- **GUI refactor** — `main_window.py` split into `gui/common.py`, `gui/widgets.py`,
  `gui/workers.py`, `gui/dialogs.py` (names re-exported for compatibility).
- **Browser computer-use loop** — goal-driven plan/act/observe loop
  (`kairos/computer.py`; tool `computer_task`).
- **RAG reranking** — embedding (cosine) rerank with lexical fallback
  (`kairos/rerank.py`; config `rag.rerank`, `rag.top_k`).
- **Signed releases** — Ed25519-signed bundles verified by the updater against a
  pinned public key (`kairos/release_signing.py`).
- **Streaming executes tools** — streamed replies run web tool requests (search /
  learn / scrape) and show the answer, never the raw tool markup.

### Wave 7 (concurrency)
- **FIFO job queue** — chat turns, skills and background actions are queued and
  run one at a time, so the window stays responsive and you can keep submitting
  work while a job is running (`kairos/jobs.py`).
- **Independent jobs** — the chat re-entrancy guard is per-thread, so Telegram and
  scheduled/background jobs keep full tool + recall access; skills run off the UI
  thread; token usage is tracked per call.

---

## Knowledge Library & Media Storage

### Storage location

By default, data is stored under `%USERPROFILE%\KairosData\`. You can change the
drive/folder via **`Edit → Storage Settings`** in the GUI. All writes go to:

```
<storage_root>/Kairos/Knowledge/        (SQLite + vector index metadata)
<storage_root>/Kairos/Media/            (downloaded audio/video)
<storage_root>/Kairos/Skills/           (skill source files)
<storage_root>/Kairos/AGENT_CHARACTER/  (agent character profiles)
```

### Knowledge library

- Scraped pages are summarized by the LLM and stored in SQLite.
- Full-text is indexed and optionally embedded into a **Chroma** vector store for
  semantic search (the ONNX `all-MiniLM-L6-v2` model is downloaded once on first use
  and cached).

### Media download

- **MP3** → audio (bestaudio + FFmpeg extraction at 192 kbps).
- **MP4** → video (bestvideo+bestaudio merged).
- Files are saved to `<storage_root>/Kairos/Media/`.

---

## Data Retention & Deletion

- Items older than `retention_days` (default **30 days**) are considered expired.
- A background sweep runs **weekly**.
- Expired items are presented as a **checkbox list** — nothing is deleted without
  your approval.
- Review manually via `Edit → Retention (Delete Expired)` or Telegram `/expired`.

---

## Email

Email works **only on your explicit request** (`/mail`, `/sendmail`, or GUI Email
actions). Configure via `Edit → Email Settings`:

- Email address + password
- IMAP host/port (default `imap.gmail.com:993`)
- SMTP host/port (default `smtp.gmail.com:465`)

Credentials are stored in the OS keyring. For Gmail, use an
[App Password](https://support.google.com/accounts/answer/185833).

---

## Peripheral Control (Serial USB)

Connect ESP32, Arduino, or Raspberry Pi over serial USB.

- **GUI:** `Edit → Peripheral Control` — refresh ports, set baud rate (default
  **115200**, changeable), open/close, send data, read data.
- **Telegram:** `/ports`, `/open <port> [baud]`, `/send <port> <text>`,
  `/read <port>`, `/close <port>`.

The default baud rate is configurable in `config.json` under `peripherals.default_baud`.

---

## Watchdog & Kill Switch

KAIROS writes a heartbeat every 5 seconds. A separate **watchdog** process monitors
it and force-kills KAIROS if the heartbeat stops (the agent hung or went rogue).

### Kill KAIROS at any time

- **`kill.bat`** — one-click shutdown
- **GUI** — `File → Kill Switch (Emergency)` or the red **KILL SWITCH** button
- **Telegram** — `/kill` (with confirmation)

### How the kill switch works

1. `kill.bat` runs `python -m kairos.watchdog --kill`.
2. The watchdog reads KAIROS's PID from `~/.kairos/kairos.pid` and runs
   `taskkill /F /PID <pid>` (Windows) or `SIGKILL` (Unix).
3. KAIROS itself also writes a `~/.kairos/KILLSWITCH` marker and hard-exits, so the
   shutdown succeeds even if the watchdog isn't running.

### Watchdog triggers

- **Kill-switch file** — creating `~/.kairos/KILLSWITCH`
- **Kill socket** — send `KILL` to `127.0.0.1:50055`
- **Stale heartbeat** — no heartbeat for 60 s → auto-kill
- **`--kill` flag** — one-shot shutdown

---

## Self-Improvement & Learning

KAIROS maintains a persistent error log and learns from its mistakes.

1. Every caught error (LLM, web, media, peripherals, skills) is recorded with context
   to a SQLite error memory.
2. **`Self-Reflect`** (GUI `View → Self-Reflect`, or Telegram `/reflect`) sends recent
   errors to the LLM, which produces root causes, corrective actions, and a
   "lesson learned".
3. Lessons are stored and shown via **Show Lessons** (`View → Show Lessons`, or
   `/lessons`).

---

## Predictive Engine

KAIROS includes a prediction feature that turns seed material (news links, social
media links, Excel/CSV data, or free text) into a forecast report.

### Quick prediction (built-in)

Runs a small multi-agent debate (3 analyst personas, 2 rounds) using your active
LLM, then synthesizes a report. No external service needed.

- **GUI:** `Tools → Predictive Engine` (or the **Predict** toolbar button)
- **Telegram:** `/predict <question>`

### MiroFish swarm simulation (optional)

For full multi-agent swarm simulation, KAIROS can talk to a separately-run
**MiroFish** service (`https://github.com/666ghj/MiroFish`) over HTTP.

1. Install/run MiroFish independently (Docker or its own Python 3.12 venv —
   MiroFish needs Python ≤3.12, while KAIROS uses 3.14, so they must be separate).
2. In `config.json`, set:
   ```json
   "mirofish": {
     "enabled": true,
     "base_url": "http://localhost:5001",
     "zep_api_key": null
   }
   ```
3. Enter your **Zep** API key via the GUI or config (stored in the keyring).

When `enabled` is true and MiroFish is reachable, `mode=auto` uses it; otherwise
KAIROS falls back to the built-in quick predictor. Prediction reports are saved
to the predictions store and retention, and are included in **Self-Reflect** for
forecasting self-assessment.

---

## Multi-LLM Council & Attachments

### Multi-LLM Council (complex tasks)

For complex work (software projects, large-data analysis), Kairos can run a
**council of three different LLMs**:

1. **Aptitude discussion** — each member assesses the task, states the role it
   is best suited for, and votes for a lead.
2. **Primary election** — the votes (then confidence) elect the Primary.
3. **Work division** — the Primary breaks the task into subtasks and assigns
   them to the two workers.
4. **Execution** — the workers complete their parts.
5. **Verification** — the Primary reviews, corrects and optimizes the result.

- Enable with the **"Council (multi-LLM)"** checkbox next to the input and pick
  the three members from the dropdowns (chosen **per run**, remembered for next
  time).
- A standard run costs ~7 LLM calls. Large inputs are chunked and summarized
  first so the context stays comprehensive without exploding the token budget.
- The final, verified result is shown in the chat **and opened in a new
  copyable window** (with **Copy All** and **Save…**), and is saved to the
  knowledge library for later recall.

### Attachments

The **📎 Attach** button adds context to a normal chat or a council run:

- **Files**: PDF, DOCX, TXT/MD, CSV, XLSX/XLS, source code, JSON, logs.
- **Folders**: added recursively (text-like files).
- **Images**: PNG/JPG/etc. — routed to a **vision-capable** model.

Use *Attach Files…*, *Attach Folder…*, or *Clear Attachments* from the menu.
Large extracted text is chunked and summarized automatically.

#### Free vision-capable models

To use images, mark a provider as **vision-capable** (checkbox in the provider
dialog) and give it a multimodal model. **OpenRouter** hosts free
vision-capable models (for example models tagged `:free` with visual
perception, such as InclusionAI Ling VL). Add an OpenRouter provider:

| Field | Value |
|-------|-------|
| Provider ID | `openrouter` |
| API URL | `https://openrouter.ai/api/v1/chat/completions` |
| Model | a `:free` vision model (e.g. `inclusionai/ling-3.0-flash-vl:free`) |
| Vision | ✅ enabled |

If no vision-capable member is present, images are noted but not analyzed.

---

## Chat Modes (Plan & Execute)

Next to the chat input there is a **Chat** button and a **Plan / Execute** dropdown.

- **Chat** — the normal conversational mode (tools available). This is the default.
- **Plan** — Kairos decomposes your request into an ordered, concrete step list and
  stores it as a durable plan (`planner.db`); nothing is executed. You can view
  plans under **Agent → Plans & Tasks…** or `/plans`.
- **Execute** — Kairos produces the plan and then **autonomously executes each
  step**, using the full toolkit (web search/learn/scrape, git commits, drawing &
  document artifacts, browser actions, memory). Each step's status and result are
  persisted; progress is streamed into the console.

The selected mode is saved as `agent.mode` in the config and restored on startup.
The **Council (multi-LLM)** checkbox takes precedence when ticked. Set the mode
from Telegram with `/mode chat|plan|execute`, produce a plan with
`/planagent <goal>`, or run it with `/execute <goal>`.

> Execute mode runs with the *active character's* capabilities; tools it is not
> permitted to use are refused. It never runs shell commands, force-pushes, or
> evaluates JavaScript unless those are explicitly enabled.

---

## Git & Version Control

Kairos can run git workflows for you using the **system `git` CLI** (no extra
dependency). Configure it under **Edit → Git & Version Control…**:

- **Repository root** — all git commands are confined to this folder
  (`git.repo_root`, defaulting to `agent.file_root` / your home).
- **Allow push / Allow pull** — off by default; must be explicitly enabled.
- **Allow destructive operations** — off by default (force/hard-reset/clean/branch
  delete are blocked unless enabled).
- **Author name / email** — optional, applied to commits.

Supported operations: `status`, `diff`, `log`, `branches`, `create branch`,
`checkout`, `add`, `commit`, `init`, `stash`, `pull`, `push`. Commands run with
`shell=False`, arguments are validated (no leading dashes, no `..` traversal), and
output is redacted. The same actions are exposed to the LLM as tools
(`git_status`, `git_diff`, `git_log`, `git_commit`, `git_create_branch`,
`git_checkout`) and via Telegram `/git …`, gated by the `git_ops` capability.

---

## Webhooks

Kairos can both **receive** and **send** webhooks. The endpoint is **off by
default** and, when enabled, binds to **`127.0.0.1:8765`** (loopback only).

### Inbound (external → Kairos)

Configure hooks under **Edit → Webhook…** (or `webhook.hooks` in the config). Each
hook maps a name to an action:

| Action | Effect |
|--------|--------|
| `ask` | Send the payload to the LLM (optionally via a `payload` template with `{body}`) |
| `skill` | Run a named skill |
| `remember` | Store the payload in retained memory |
| `notify` | Forward the payload to your Telegram chat(s) |

POST JSON to `POST http://127.0.0.1:8765/hook/<name>`. A shared **secret**
(stored in the OS keyring) is required and sent as the `X-Kairos-Token` header; set
**Require HMAC signature** to also accept `X-Kairos-Signature: sha256=<hex>` (HMAC
of the raw body). Add `?wait=1` to run synchronously and receive the result;
otherwise the endpoint returns `202 Accepted` immediately. `GET /health` returns
the service status. Body size is capped and payloads are treated as untrusted data.

### Outbound (Kairos → URL)

Enable outbound notifications and list one or more URLs. Kairos POSTs a signed
JSON body (`{"event": …,"data": …}`) to each URL when notable events happen:
agent/job completion, scheduled-task runs, predictions, pending-knowledge and
git-commit events. Optional HMAC signing via the outbound secret.

> Non-loopback binding is refused unless you explicitly set
> `webhook.allow_public_bind` — only do this behind your own firewall/proxy.

---

## Drawings & Design (draw & write)

Kairos can produce files and store them under
`<storage_root>/Kairos/Artifacts/`:

- **Drawings (SVG)** — bar charts, line charts, flowcharts, or raw LLM-generated
  SVG. LLM SVG is **sanitized** (scripts, event handlers, `javascript:` URIs and
  external `href`s are stripped) before it is written, so an opened file cannot
  execute code or phone home.
- **Documents** — Markdown, text, code, JSON, CSV and similar, written atomically.

Access it via **Tools → Drawings & Design…**:

- **Design from description (SVG)** — type a description (e.g. *"a block diagram of
  an ESP32-S3 with a 3.3V regulator"*) and click **Generate SVG**; the LLM writes
  the SVG code, it is sanitized and saved. The drawing is offered for opening.
- **Write document** — save Markdown/text/code/JSON/CSV atomically.
- **Manage** — **Open**, **Reveal Folder**, and **Delete Selected** (with
  confirmation) remove files from the Artifacts folder.

Also available as the tools `draw_diagram` and `write_document`, or Telegram
`/draw <name> | <description>` (generates SVG) and `/write <file> | <content>`.
Gated by the `artifacts` capability (`artifacts.enabled`, `artifacts.allow_svg`).

---

## Web-Page Design (headed browser)

For design work on canvas/SVG editors such as **EasyEDA**, Kairos can drive a
**persistent, headed Chromium** session and interact with the page:

- Open a real browser window and keep it open across actions.
- Click/type by CSS selector, or click/drag at coordinates on a canvas.
- Press keyboard keys.
- Evaluate JavaScript (`browser.allow_js_eval`) to call the site's own editor API.

Open **Tools → Web Designer (browser)…**. The dialog has **Enable browser
session** and **Enable JavaScript evaluation** toggles (saved to the config), an
**Install Chromium (Playwright)** button, a start URL and a design goal. Click
**Open Session**, then **Run Design Task**. The task planner navigates, acts and
observes the page (screenshots go to the Media folder). The same capability is
exposed as tools `browser_open`, `browser_js`, `browser_mouse` and via Telegram
`/design <url> | <goal>`, gated by the `browser_control` capability.

The session is **off by default**. Tick **Enable browser session** in the dialog
(or set `browser.enabled`), install Chromium once via the dialog's button (or
`python -m playwright install chromium`), and optionally enable JavaScript
evaluation (`browser.allow_js_eval`) to let the agent call the site's own editor
API. If you try to open a session while it is disabled, Kairos offers to enable it.

> Results depend on the target site's DOM/JS API; EasyEDA tasks are best-effort and
> should be reviewed before you rely on them.

---

## Model Context Protocol (MCP) server

Kairos can expose its tools to any MCP client over stdio:

```bat
python -m kairos.mcp_server
```

The server speaks newline-delimited JSON-RPC 2.0 and supports `initialize`,
`tools/list`, `tools/call`, plus **`resources/list`/`resources/read`** and
**`prompts/list`/`prompts/get`** (toggle under `mcp.server.expose_resources` /
`expose_prompts`). Built-in resources include the Kairos version, a
secret-redacted config view, retained memories and knowledge-graph stats; built-in
prompts include `research_topic`, `make_plan`, `summarize_page` and
`git_commit_message`.

The MCP process builds a **headless engine** — it does **not** touch the watchdog
PID/heartbeat files and does not start the scheduler, collaboration, Discord or
webhook services, so it can run safely alongside the GUI. Configure the client
side (connect Kairos to *other* MCP servers) and the server toggles under
**Agent → Settings… → MCP**.

---

## Updates

KAIROS can update itself from GitHub Releases.

- On startup it checks for a new release **once per day**.
- A button in the **top-right corner** shows the state:
  - **Check for updates** — click to check manually
  - **⬆ Update available** — a newer release exists
  - **✓ Up to date** — no newer release
- Clicking **Update available** asks for confirmation, then downloads the new
  release, replaces the program files, installs any new dependencies from
  `requirements.txt`, and restarts KAIROS.

Your data is never touched: config, API keys (keyring), custom skills, the
knowledge library, and media are all preserved.

---

## Configuration File

Location: `%USERPROFILE%\.kairos\config.json`

```json
{
  "storage_root": "C:\\Users\\<you>\\KairosData",
  "telegram_token": null,
  "active_llm": "moonshot",
  "llm_providers": {
    "moonshot": {
      "api_url": "https://api.moonshot.ai/v1/chat/completions",
      "api_key": null,
      "model": "kimi-k3"
    }
  },
  "peripherals": {
    "default_baud": 115200
  },
  "retention_days": 30,
  "active_character": "general",
  "character": {
    "dir_name": "AGENT_CHARACTER"
  },
  "agent": {
    "mode": "chat",
    "native_tools": false,
    "streaming": true,
    "allow_file_write": true,
    "allow_shell": false
  },
  "git": {
    "enabled": false,
    "repo_root": null,
    "allow_push": false,
    "allow_pull": false,
    "allow_destructive": false,
    "author_name": "",
    "author_email": "",
    "token": null
  },
  "webhook": {
    "enabled": false,
    "host": "127.0.0.1",
    "port": 8765,
    "allow_public_bind": false,
    "secret": null,
    "require_signature": false,
    "hooks": {},
    "outbound": {"enabled": false, "urls": [], "secret": null}
  },
  "browser": {
    "enabled": false,
    "headless": false,
    "allow_js_eval": false
  },
  "artifacts": {
    "enabled": true,
    "allow_svg": true
  },
  "mcp": {
    "enabled": false,
    "servers": {},
    "server": {"enabled": false, "expose_resources": true, "expose_prompts": true}
  }
}
```

- `api_key` values are `null` in the file because they live in the OS keyring.
- `storage_root` — drive/folder for knowledge, media, and skills.
- `retention_days` — data older than this is flagged for deletion.
- `active_llm` — currently selected provider.
- `active_character` — id of the active Agent Character (see [Agent Characters](#agent-characters)).
- `character.dir_name` — folder under `<storage_root>/Kairos/` holding character profiles.
- `agent.mode` — default chat mode: `chat`, `plan`, or `execute`.
- `git.*` — git integration (disabled by default); `git.token` is stored in the keyring (`git_token`).
- `webhook.*` — webhook endpoint (disabled by default; loopback **`127.0.0.1:8765`**); `webhook.secret` and `webhook.outbound.secret` live in the keyring (`webhook_secret`, `webhook_outbound_secret`).
- `browser.*` — persistent headed browser session (disabled by default); JS evaluation requires `browser.allow_js_eval`.
- `artifacts.*` — drawing/document output (enabled by default).
- `mcp.server.*` — expose Kairos as an MCP server (`enabled`, `expose_resources`, `expose_prompts`).

All secrets are `null` in the file and live in the OS keyring (service `kairos`):
`telegram_token`, `llm_api_key_<provider>`, `mirofish_zep_api_key`,
`email_password_<addr>`, `github_token`, `notion_token`, `google_token`,
`image_api_key`, `discord_token`, `webhook_secret`, `webhook_outbound_secret`,
`git_token`.

---

## Project Structure

```
kairos/
├── kairos/                     # main package
│   ├── main.py                 # KairosEngine + entry point
│   ├── config.py               # config + keyring secrets
│   ├── characters.py           # Agent Character manager
│   ├── characters_presets.py   # built-in character presets
│   ├── watchdog.py             # watchdog / kill switch
│   ├── telegram_bot.py         # Telegram interface
│   ├── media_downloader.py     # yt-dlp MP3/MP4
│   ├── retention.py            # weekly retention sweep
│   ├── email_client.py         # IMAP/SMTP
│   ├── learning.py             # error memory + reflection
│   ├── git_tool.py             # git & version-control workflows
│   ├── webhook.py              # inbound/outbound webhooks
│   ├── artifacts.py            # draw (SVG) & write documents
│   ├── planner.py              # durable plans (Plan/Execute modes)
│   ├── browser.py              # Playwright one-shot + persistent session
│   ├── computer.py             # browser computer-use loop
│   ├── mcp_server.py           # MCP stdio server (tools/resources/prompts)
│   ├── mcp_client.py           # MCP stdio client
│   ├── llm/                    # multi-provider LLM client
│   │   ├── client.py
│   │   └── kimi.py             # backwards-compatible wrapper
│   ├── web/                    # search + scrape + summarize
│   │   └── __init__.py
│   ├── storage/                # knowledge + media stores
│   │   ├── knowledge.py
│   │   └── media.py
│   ├── peripherals/            # serial manager
│   │   └── serial_manager.py
│   ├── skills/                 # skill system
│   │   ├── base.py
│   │   └── __init__.py
│   └── gui/                    # PySide6 GUI
│       └── main_window.py
├── install.bat                 # one-time setup
├── install.py                  # setup script
├── run.bat                     # launch Kairos + watchdog
├── watchdog.bat                # watchdog only
├── kill.bat                    # kill switch
├── run.sh                      # Unix launcher
├── requirements.txt
├── setup.cfg
├── LICENSE
└── README.md
```

---

## Creating a Distributable ZIP

To package KAIROS for installation on any computer, zip the following (excluding
`venv/`, `__pycache__/`, and any user data):

```
install.bat  install.py  run.bat  watchdog.bat  kill.bat  run.sh
requirements.txt  setup.cfg  LICENSE  README.md
kairos/          (the whole package)
```

On the target machine: extract → `install.bat` → `run.bat`.

---

## Uploading to GitHub (what NOT to commit)

Yes — this project is safe to upload to GitHub **if** you exclude the following.
The included [.gitignore](.gitignore) already does this:

| Excluded | Why |
|----------|-----|
| `venv/` | Virtual environment — machine-specific |
| `__pycache__/`, `*.pyc` | Python bytecode |
| `~/.kairos/config.json`, `*.db`, `chroma/` | Local config + databases |
| `Kairos/`, `KairosData/` | **Your custom-created skills**, knowledge library, and media |
| `*.zip` | Build artifacts (e.g. `KAIROS-agent-bundle.zip`) |
| `*.jpg`, `*.png` | Personal screenshots |

**Secrets are safe** because they are never stored in the project folder:
- Telegram token and LLM API keys live in the **OS keyring**.
- Email credentials live in the **OS keyring**.
- The only config file (`%USERPROFILE%\.kairos\config.json`) is outside the repo
  and gitignored anyway.

Before pushing, run `git status` and make sure none of the above appear as
untracked files.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `Python was not found` | Python is not on PATH. Install from python.org and check "Add Python to PATH". |
| `InvalidToken` on startup | The Telegram bot token is wrong or expired. Get a new one from @BotFather. |
| `LLM error 401` | Invalid API key or wrong provider URL. Check `Edit → LLM Providers`. |
| `Site returned 403 Forbidden (blocked)` | The site blocks non-browser traffic. Try another URL, or a site that allows scraping. |
| `SQLite objects created in a thread...` | Fixed — stores are thread-safe; update to the latest bundle. |
| Chroma downloads a 79 MB model on first run | Normal — the ONNX embedding model is downloaded once and cached. |
| GUI won't start | Run `python -m kairos.main` in a terminal to see the error. |

---

## License

**PolyForm Noncommercial License 1.0.0** — see [LICENSE](LICENSE).

- Free for **personal, educational, research, and non-commercial** use.
- **Commercial use requires a separate commercial license** from the author
  (acknowledgment and, where applicable, a royalty). Contact the author to obtain one.
- The software is provided "as is", without warranty.

See <https://polyformproject.org/licenses/noncommercial/1.0.0> for the full terms.

### Commercial license

To use KAIROS (or a modified version of it) in any commercial product, service,
or organization, contact the author to obtain a written commercial license:

- **Email:** `roopchandps@gmail.com`
- **GitHub:** `https://github.com/rcps7/kairos`

The commercial license includes attribution and royalty terms agreed in writing.

---

## Contributing

Contributions are welcome for non-commercial improvements — see
[CONTRIBUTING.md](CONTRIBUTING.md).
