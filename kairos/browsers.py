"""Detect installed and running web browsers, and choose one for the agent.

No third-party dependency is required: Windows uses the ``StartMenuInternet``
registry plus known install paths; macOS scans ``/Applications``; Linux uses
``shutil.which``. Running browsers are detected with ``tasklist`` (Windows) or
``ps`` (Unix). A Chromium instance started with ``--remote-debugging-port`` can
be detected and attached to over CDP.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Descriptors for the browsers Kairos knows how to drive.
KNOWN_BROWSERS = [
    {
        "id": "msedge", "name": "Microsoft Edge", "family": "chromium",
        "channel": "msedge", "exe": "msedge.exe",
        "win": [r"Microsoft\Edge\Application\msedge.exe"],
        "mac": "Microsoft Edge.app",
        "linux": ["microsoft-edge", "microsoft-edge-stable"],
    },
    {
        "id": "chrome", "name": "Google Chrome", "family": "chromium",
        "channel": "chrome", "exe": "chrome.exe",
        "win": [r"Google\Chrome\Application\chrome.exe"],
        "mac": "Google Chrome.app",
        "linux": ["google-chrome", "google-chrome-stable", "chrome", "chromium",
                  "chromium-browser"],
    },
    {
        "id": "brave", "name": "Brave", "family": "chromium", "channel": None,
        "exe": "brave.exe",
        "win": [r"BraveSoftware\Brave-Browser\Application\brave.exe"],
        "mac": "Brave Browser.app",
        "linux": ["brave-browser", "brave"],
    },
    {
        "id": "vivaldi", "name": "Vivaldi", "family": "chromium", "channel": None,
        "exe": "vivaldi.exe",
        "win": [r"Vivaldi\Application\vivaldi.exe"],
        "mac": "Vivaldi.app",
        "linux": ["vivaldi", "vivaldi-stable"],
    },
    {
        "id": "opera", "name": "Opera", "family": "chromium", "channel": None,
        "exe": "opera.exe",
        "win": [r"Programs\Opera\opera.exe", r"Opera\Application\opera.exe"],
        "mac": "Opera.app",
        "linux": ["opera"],
    },
    {
        "id": "firefox", "name": "Mozilla Firefox", "family": "firefox",
        "channel": None, "exe": "firefox.exe",
        "win": [r"Mozilla Firefox\firefox.exe"],
        "mac": "Firefox.app",
        "linux": ["firefox"],
    },
]

_BY_EXE = {b["exe"].lower(): b for b in KNOWN_BROWSERS}


def _desc_by_id(bid: str):
    return next((b for b in KNOWN_BROWSERS if b["id"] == bid), None)


def _desc_for_path(path: str):
    name = Path(path).name.lower()
    return _BY_EXE.get(name)


def _strip_command(value: str) -> str:
    value = (value or "").strip()
    m = re.match(r'\s*"([^"]+)"', value)
    if m:
        return m.group(1)
    m = re.match(r"\s*(\S+)", value)
    return m.group(1) if m else ""


def _registry_paths() -> list:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except Exception:
        return []
    out = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet"),
    ]
    for hive, sub in roots:
        try:
            with winreg.OpenKey(hive, sub) as key:
                n = winreg.QueryInfoKey(key)[0]
                for i in range(n):
                    try:
                        child = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, f"{child}\\shell\\open\\command") as ck:
                            val, _ = winreg.QueryValueEx(ck, "")
                        p = _strip_command(val)
                        if p:
                            out.append(p)
                    except Exception:
                        continue
        except Exception:
            continue
    return out


def _known_paths() -> list:
    out = []
    if sys.platform == "win32":
        bases = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")]
        for b in KNOWN_BROWSERS:
            for rel in b.get("win", []):
                for base in bases:
                    if base:
                        out.append(os.path.join(base, rel))
    elif sys.platform == "darwin":
        for b in KNOWN_BROWSERS:
            app = b.get("mac")
            if app:
                out.append(f"/Applications/{app}")
                out.append(os.path.expanduser(f"~/Applications/{app}"))
    return [p for p in out if p and os.path.exists(p)]


def _linux_paths() -> list:
    out = []
    for b in KNOWN_BROWSERS:
        for name in b.get("linux", []):
            p = shutil.which(name)
            if p:
                out.append(p)
    return out


def find_installed_browsers() -> list:
    """Return installed browsers as ``{id,name,path,family,channel}`` dicts."""
    candidates = _registry_paths() + _known_paths() + _linux_paths()
    seen = set()
    out = []
    for path in candidates:
        try:
            real = str(Path(path).resolve())
        except Exception:
            real = path
        if real.lower() in seen or not os.path.exists(real):
            continue
        desc = _desc_for_path(real)
        if not desc:
            continue
        seen.add(real.lower())
        out.append({"id": desc["id"], "name": desc["name"], "path": real,
                    "family": desc["family"], "channel": desc.get("channel")})
    out.sort(key=lambda c: c["name"].lower())
    return out


def running_browser_ids() -> set:
    """Return the set of browser ids that currently have a process running."""
    ids = set()
    try:
        if sys.platform == "win32":
            p = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                               capture_output=True, text=True, timeout=15,
                               creationflags=CREATE_NO_WINDOW)
            for line in (p.stdout or "").splitlines():
                first = line.split(",", 1)[0].strip().strip('"').lower()
                desc = _BY_EXE.get(first)
                if desc:
                    ids.add(desc["id"])
        else:
            p = subprocess.run(["ps", "-A", "-o", "comm="],
                               capture_output=True, text=True, timeout=15)
            for line in (p.stdout or "").splitlines():
                name = os.path.basename(line.strip()).lower()
                desc = _BY_EXE.get(name)
                if desc:
                    ids.add(desc["id"])
    except Exception:
        logger.debug("Could not enumerate running browsers", exc_info=True)
    return ids


def detect_debug_endpoint(ports=(9222, 9223, 9224), timeout: float = 1.5):
    """Return ``{port,url,label}`` if a CDP endpoint is reachable, else None."""
    try:
        import httpx
    except Exception:
        return None
    for port in ports:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
            if r.status_code == 200:
                data = r.json() if r.content else {}
                label = data.get("Browser") or data.get("browser") or "Chromium"
                return {"port": port, "url": f"http://127.0.0.1:{port}",
                        "label": label}
        except Exception:
            continue
    return None


def list_choices() -> list:
    """Installed + running browsers (with a ``running`` flag), for the GUI/agent.

    Always includes a bundled Playwright Chromium entry as a last resort.
    """
    running = running_browser_ids()
    installed = find_installed_browsers()
    choices = []
    seen_ids = set()
    for c in installed:
        c = dict(c)
        c["running"] = c["id"] in running
        choices.append(c)
        seen_ids.add(c["id"])
    # Running but not "installed" per detection: add a best-effort entry.
    for bid in running:
        if bid in seen_ids:
            continue
        desc = _desc_by_id(bid)
        if desc:
            choices.append({"id": bid, "name": desc["name"], "path": None,
                            "family": desc["family"], "channel": desc.get("channel"),
                            "running": True})
    # Bundled fallback.
    try:
        from kairos import browser
        if browser.available():
            choices.append({"id": "playwright-chromium",
                            "name": "Playwright Chromium (bundled)",
                            "path": None, "family": "chromium", "channel": None,
                            "running": False})
            choices.append({"id": "playwright-firefox",
                            "name": "Playwright Firefox (bundled)",
                            "path": None, "family": "firefox", "channel": None,
                            "running": False})
    except Exception:
        pass
    # Running first, then alphabetical.
    choices.sort(key=lambda c: (not c.get("running"), c["name"].lower()))
    return choices


def resolve_choice(choice_id: str):
    """Resolve a choice id (or path) to a descriptor dict, or None."""
    if not choice_id:
        return None
    if choice_id == "playwright-chromium":
        return {"id": choice_id, "name": "Playwright Chromium (bundled)",
                "path": None, "family": "chromium", "channel": None}
    if choice_id == "playwright-firefox":
        return {"id": choice_id, "name": "Playwright Firefox (bundled)",
                "path": None, "family": "firefox", "channel": None}
    for c in find_installed_browsers():
        if c["id"] == choice_id or c["path"] == choice_id:
            return c
    desc = _desc_by_id(choice_id)
    if desc:
        return {"id": desc["id"], "name": desc["name"], "path": None,
                "family": desc["family"], "channel": desc.get("channel")}
    if os.path.exists(choice_id):
        d = _desc_for_path(choice_id) or {"id": "custom", "name": Path(choice_id).name,
                                         "family": "chromium", "channel": None}
        return {"id": d["id"], "name": d["name"], "path": choice_id,
                "family": d.get("family", "chromium"), "channel": d.get("channel")}
    return None


def summary(choice: dict) -> str:
    if not choice:
        return "No browser selected"
    flag = " (running)" if choice.get("running") else ""
    return f"{choice.get('name') or choice.get('id')}{flag}"