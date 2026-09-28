"""Shared safety helpers: id/path validation, safe archive extraction, atomic
writes, and secret redaction. Used by skills, the updater, bootstraps and config.
"""

import hashlib
import logging
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{12,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_\-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9\-]{10,}|[0-9]{8,10}:[A-Za-z0-9_\-]{30,})"
)


def safe_id(name: str) -> bool:
    return bool(_ID_RE.match((name or "").strip()))


def confine_path(base, name: str, ext: str = ".py") -> Path:
    """Return base/<name><ext>, guaranteed to stay inside base."""
    if not safe_id(name):
        raise ValueError(f"Invalid name '{name}': use lowercase letters, digits and _ only.")
    base = Path(base).resolve()
    target = (base / f"{name}{ext}").resolve()
    if target.parent != base:
        raise ValueError("Path escapes the allowed directory.")
    return target


def _within(base: str, target: str) -> bool:
    base = os.path.abspath(base)
    target = os.path.abspath(target)
    return target == base or target.startswith(base + os.sep)


def safe_extract(archive, dest):
    """Extract a .zip/.tar(.gz) archive, rejecting path traversal and links."""
    archive = Path(archive)
    dest = Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                target = (dest / name).resolve()
                if not _within(str(dest), str(target)):
                    raise ValueError(f"Unsafe path in archive: {name}")
            z.extractall(dest)
        return dest
    with tarfile.open(archive) as t:
        for member in t.getmembers():
            target = (dest / member.name).resolve()
            if not _within(str(dest), str(target)):
                raise ValueError(f"Unsafe path in archive: {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"Archive contains a link: {member.name}")
        t.extractall(dest)
    return dest


def sha256_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def atomic_write_text(path, data: str, encoding: str = "utf-8"):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding=encoding)
    os.replace(tmp, path)
    return path


def redact_secrets(text: str) -> str:
    try:
        return _SECRET_RE.sub("[REDACTED]", text or "")
    except Exception:
        return text or ""


def log_exception(msg: str):
    logger.exception(redact_secrets(msg))


def restrict_file(path):
    """Best-effort: restrict a file to the current user only."""
    try:
        if sys.platform == "win32":
            me = ""
            try:
                r = subprocess.run(["whoami"], capture_output=True, text=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                me = (r.stdout or "").strip()
            except Exception:
                me = ""
            if me:
                subprocess.run(["icacls", str(path), "/grant:r", f"{me}:(F)"],
                               capture_output=True, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.chmod(path, 0o600)
    except Exception:
        logger.debug("Could not restrict %s", path)