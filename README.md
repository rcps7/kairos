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
10. [Knowledge Library & Media Storage](#knowledge-library--media-storage)
11. [Data Retention & Deletion](#data-retention--deletion)
12. [Email](#email)
13. [Peripheral Control (Serial USB)](#peripheral-control-serial-usb)
14. [Watchdog & Kill Switch](#watchdog--kill-switch)
15. [Self-Improvement & Learning](#self-improvement--learning)
16. [Configuration File](#configuration-file)
17. [Project Structure](#project-structure)
18. [Creating a Distributable ZIP](#creating-a-distributable-zip)
19. [Uploading to GitHub (what NOT to commit)](#uploading-to-github-what-not-to-commit)
20. [Troubleshooting](#troubleshooting)
21. [License](#license)
22. [Contributing](#contributing)

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
| Skill system — create, view, edit, run, delete skills | GUI / Telegram |
| Self-improvement — records errors, reflects, stores lessons | GUI / Telegram |
| Watchdog with kill switch + heartbeat monitoring | `kill.bat`, GUI, Telegram `/kill` |
| Voice-to-text (Talk button) + spoken replies + live voice meter | GUI |
| Animated mood orb (thinking/speaking/success/error) | GUI |
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
- **Right pane** — system status (active LLM, skill count, storage path), quick-action
  buttons, and the red **KILL SWITCH** button.
- **Toolbar** — Search, Learn URL, Download, Skills, Providers, Peripherals,
  Self-Reflect.

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
| **Edit** | LLM Providers, Storage Settings, Email Settings, Peripheral Control, Retention (Delete Expired), Skills |
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
| `/reflect` | Analyze recent errors and store a lesson |
| `/lessons` | Show lessons learned |
| `/ports` | List serial ports |
| `/open <port> [baud]` | Open a serial port |
| `/send <port> <text>` | Write data to a port |
| `/read <port>` | Read data from a port |
| `/close <port>` | Close a serial port |
| `/kill` | Kill switch (with confirmation) |

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

## Knowledge Library & Media Storage

### Storage location

By default, data is stored under `%USERPROFILE%\KairosData\`. You can change the
drive/folder via **`Edit → Storage Settings`** in the GUI. All writes go to:

```
<storage_root>/Kairos/Knowledge/   (SQLite + vector index metadata)
<storage_root>/Kairos/Media/       (downloaded audio/video)
<storage_root>/Kairos/Skills/      (skill source files)
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
  "retention_days": 30
}
```

- `api_key` values are `null` in the file because they live in the OS keyring.
- `storage_root` — drive/folder for knowledge, media, and skills.
- `retention_days` — data older than this is flagged for deletion.
- `active_llm` — currently selected provider.

---

## Project Structure

```
kairos/
├── kairos/                     # main package
│   ├── main.py                 # KairosEngine + entry point
│   ├── config.py               # config + keyring secrets
│   ├── watchdog.py             # watchdog / kill switch
│   ├── telegram_bot.py         # Telegram interface
│   ├── media_downloader.py     # yt-dlp MP3/MP4
│   ├── retention.py            # weekly retention sweep
│   ├── email_client.py         # IMAP/SMTP
│   ├── learning.py             # error memory + reflection
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
