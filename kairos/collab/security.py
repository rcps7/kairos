"""Security primitives for Kairos peer collaboration.

Centralises the SSRF host policy, rate limiting, text/filename sanitisation
(anti-injection, anti-bidi-spoofing), frame-size guards and file ACL locking so
every collaboration module applies the same rules.
"""

import ipaddress
import logging
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque

logger = logging.getLogger(__name__)

MAX_CALLSIGN_LEN = 256
MAX_FRAME_BYTES = 8 * 1024 * 1024  # 8 MB hard cap per frame

_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x200E, 0x200F, 0x061C}
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}


# ---------------------------------------------------------------------------
# Text / name sanitisation (V4, V8, V19)
# ---------------------------------------------------------------------------
def sanitize_text(text: str, max_len: int = 4096) -> str:
    """NFC-normalise, drop control/bidi characters, and bound the length."""
    text = unicodedata.normalize("NFC", text or "")
    out = []
    for ch in text:
        o = ord(ch)
        if ch in "\r\n\t":
            out.append(ch)
            continue
        if o < 0x20 or o == 0x7F or (0x80 <= o <= 0x9F) or o in _BIDI:
            continue
        out.append(ch)
    return "".join(out)[:max_len]


def sanitize_filename(name: str, max_len: int = 180) -> str:
    """Reduce a peer-supplied name to a safe basename (no dirs/.. /reserved)."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = sanitize_text(name, max_len)
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    if name in ("", ".", ".."):
        name = "file"
    if name.split(".")[0].upper() in _WIN_RESERVED:
        name = "_" + name
    return name[:max_len]


def sanitize_component(name: str, max_len: int = 64) -> str:
    """Safe single path component for project/session folders."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", sanitize_text(name, max_len)) or "x"


# ---------------------------------------------------------------------------
# Rate limiting (V5, V6, V11, V18)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.time()
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            while dq and now - dq[0] > window_seconds:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True


# ---------------------------------------------------------------------------
# SSRF host policy (V3)
# ---------------------------------------------------------------------------
def classify_host(host: str):
    """Return (kind, ip_or_None). kind in public/private/loopback/linklocal/
    metadata/invalid/hostname."""
    host = (host or "").strip().strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ("hostname", None)
    if ip.is_loopback:
        return ("loopback", ip)
    if str(ip) == "169.254.169.254":
        return ("metadata", ip)
    if ip.is_link_local:
        return ("linklocal", ip)
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return ("invalid", ip)
    if ip.is_private:
        return ("private", ip)
    return ("public", ip)


def validate_target(host: str, allow_private: bool = False, allow_loopback: bool = False):
    """Raise ValueError if the host is not an allowed connection target."""
    kind, _ = classify_host(host)
    if kind == "invalid":
        raise ValueError("Invalid target host.")
    if kind == "loopback":
        if not allow_loopback:
            raise ValueError("Blocked target (loopback).")
    elif kind == "linklocal":
        raise ValueError("Blocked target (link-local).")
    elif kind == "metadata":
        raise ValueError("Blocked target (cloud metadata).")
    elif kind == "private" and not allow_private:
        raise ValueError("Private/LAN target blocked; enable 'allow_private_targets'.")
    return True


# ---------------------------------------------------------------------------
# Frame guard (V6)
# ---------------------------------------------------------------------------
def check_frame_size(n: int):
    if n < 0 or n > MAX_FRAME_BYTES:
        raise ValueError(f"Frame size {n} exceeds limit ({MAX_FRAME_BYTES}).")


# ---------------------------------------------------------------------------
# File ACL locking (V13)
# ---------------------------------------------------------------------------
def restrict_acl(path: str):
    """Best-effort: ensure only the current user has access.

    Non-destructive on Windows: we GRANT the current user full control but do
    not strip inherited ACEs (stripping could lock out the very process that
    owns the file if the account name fails to resolve).
    """
    try:
        if sys.platform == "win32":
            me = ""
            try:
                r = subprocess.run(["whoami"], capture_output=True, text=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                me = (r.stdout or "").strip()
            except Exception:
                me = ""
            if not me:
                return
            subprocess.run(
                ["icacls", path, "/grant:r", f"{me}:(F)", "/T", "/C"],
                check=False, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.chmod(path, 0o600 if os.path.isfile(path) else 0o700)
    except Exception:
        logger.debug("Could not restrict ACL for %s", path)