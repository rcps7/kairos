"""Self-update via GitHub Releases.

Kairos checks the latest release of ``rcps7/kairos``. When a newer version is
available, the release asset (a ZIP of the program files) is downloaded and a
small batch script replaces the program files and restarts Kairos. User data
(config, keys, skills, media) is never touched.
"""

import logging
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_REPO = "rcps7/kairos"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
HEADERS = {"User-Agent": "kairos-updater", "Accept": "application/vnd.github+json"}

# Program files copied during an update (never user data).
PROGRAM_FILES = [
    "requirements.txt",
    "run.bat",
    "watchdog.bat",
    "kill.bat",
    "install.bat",
    "install.py",
    "run.sh",
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "setup.cfg",
]


def install_root() -> Path:
    """The folder that contains the ``kairos`` package and the launch scripts."""
    import kairos
    return Path(kairos.__file__).resolve().parent.parent


def local_version() -> str:
    from kairos import __version__
    return __version__


def _parse_version(v: str):
    v = (v or "").strip().lstrip("vV")
    parts = re.split(r"[.\-+]", v)
    out = []
    for p in parts:
        if p.isdigit():
            out.append(int(p))
        else:
            break
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def check_for_update(timeout: float = 10.0) -> dict:
    """Return info about the latest release and whether an update is available."""
    try:
        r = httpx.get(API_LATEST, headers=HEADERS, timeout=timeout, follow_redirects=True)
        if r.status_code == 404:
            return {"update_available": False, "error": "No releases published yet."}
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"update_available": False, "error": str(e)}

    latest = data.get("tag_name", "")
    local = local_version()

    asset_url = None
    for a in data.get("assets", []):
        if str(a.get("name", "")).lower().endswith(".zip"):
            asset_url = a.get("browser_download_url")
            break
    if not asset_url:
        asset_url = data.get("zipball_url")

    return {
        "update_available": _parse_version(latest) > _parse_version(local),
        "local_version": local,
        "latest_version": latest,
        "notes": (data.get("body") or "")[:1500],
        "published_at": data.get("published_at", ""),
        "html_url": data.get("html_url", ""),
        "download_url": asset_url,
        "error": None,
    }


def download_and_extract(url: str, dest: str) -> Path:
    """Download a ZIP and extract it. Returns the extraction folder."""
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    zip_path = dest_path / "update.zip"
    with httpx.stream("GET", url, headers={"User-Agent": "kairos-updater"},
                      timeout=120.0, follow_redirects=True) as r:
        r.raise_for_status()
        with zip_path.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_path)
    return dest_path


def find_update_root(dest: str) -> Path:
    """Locate the folder inside the extracted archive that holds the program."""
    dest_path = Path(dest)
    if (dest_path / "run.bat").exists() or (dest_path / "kairos").is_dir():
        return dest_path
    subdirs = [p for p in dest_path.iterdir() if p.is_dir()]
    # GitHub source archives wrap everything in a single top-level folder.
    for sub in subdirs:
        if (sub / "run.bat").exists() or (sub / "kairos").is_dir():
            return sub
    if len(subdirs) == 1:
        return subdirs[0]
    return dest_path


def create_updater_batch(update_root: str, root: Optional[Path] = None) -> Path:
    """Write a batch script that replaces program files and restarts Kairos."""
    root = Path(root or install_root()).resolve()
    update_root = Path(update_root).resolve()
    bat = root / "apply_update.bat"

    lines = [
        "@echo off",
        "timeout /t 2 /nobreak >nul",
        'taskkill /FI "WINDOWTITLE eq Kairos Watchdog" /F >nul 2>nul',
        f'robocopy "{update_root}\\kairos" "{root}\\kairos" /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul',
    ]
    for fname in PROGRAM_FILES:
        lines.append(f'if exist "{update_root}\\{fname}" copy /Y "{update_root}\\{fname}" "{root}\\{fname}" >nul')
    # Install any new dependencies, then relaunch.
    lines.append(f'"{root}\\venv\\Scripts\\python.exe" -m pip install -r "{root}\\requirements.txt"')
    lines.append(f'start "" "{root}\\run.bat"')
    lines.append('del "%~f0"')

    bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return bat


def launch_updater(bat_path: Path):
    """Launch the updater batch detached, then the caller should exit Kairos."""
    subprocess.Popen(["cmd", "/c", str(bat_path)], cwd=str(bat_path.parent),
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
