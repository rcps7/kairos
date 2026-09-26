"""Ensure the Microsoft Visual C++ runtime DLLs are discoverable on Windows.

Some wheels (e.g. ``onnxruntime`` used by ChromaDB, and ``ladybug``) link
against ``MSVCP140.dll`` / ``MSVCP140_1.dll``, which are provided by the VC++
Redistributable. They are frequently absent from ``System32``. This module
locates 64-bit copies already present on the machine, caches them in
``~/.kairos/vcruntime`` and registers that directory for DLL loading.

Safe to call repeatedly; it is a no-op off Windows.
"""

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_RT_DIR = Path.home() / ".kairos" / "vcruntime"
_NEED = ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")
_prepared = None


def _is_x64(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            f.seek(0x3C)
            offset = int.from_bytes(f.read(4), "little")
            f.seek(offset + 4)
            machine = int.from_bytes(f.read(2), "little")
        return machine == 0x8664
    except Exception:
        return False


def _candidate_dirs():
    env = os.environ
    dirs = [
        env.get("ProgramFiles"),
        env.get("ProgramW6432"),
        env.get("ProgramFiles(x86)"),
        env.get("LOCALAPPDATA"),
        r"C:\Windows\System32",
        r"C:\Windows\WinSxS",
    ]
    # Common apps that ship the VC runtime.
    for sub in ("Mozilla Firefox", r"Dell\DTP\DiagnosticsSubAgent",
                r"Dell\DTP\InstrumentationSubAgent", r"Weasis\runtime\bin",
                "Microsoft-Edge-WebView"):
        base = env.get("ProgramFiles") or env.get("ProgramW6432")
        if base:
            dirs.append(os.path.join(base, sub))
    return [d for d in dirs if d and os.path.isdir(d)]


def _find_x64(names):
    found = {}
    # 1. direct hits in known directories
    for d in _candidate_dirs():
        for n in list(names):
            if n in found:
                continue
            p = os.path.join(d, n)
            if os.path.exists(p) and _is_x64(p):
                found[n] = p
    if len(found) == len(names):
        return found
    # 2. bounded recursive search
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
             os.environ.get("ProgramFiles(x86)")]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth > 4:
                dirs[:] = []
                continue
            for n in list(names):
                if n in found:
                    continue
                if n in files:
                    p = os.path.join(dirpath, n)
                    if _is_x64(p):
                        found[n] = p
            if len(found) == len(names):
                return found
    return found


def ensure_vc_runtime() -> bool:
    """Make the VC++ runtime discoverable. Returns True if msvcp140 is available."""
    global _prepared
    if sys.platform != "win32":
        _prepared = True
        return True
    if _prepared is not None:
        return _prepared

    _RT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [n for n in _NEED if not (_RT_DIR / n).exists()]

    # vcruntime140* ships with CPython itself.
    for n in ("vcruntime140.dll", "vcruntime140_1.dll"):
        if n in missing:
            src = Path(sys.base_prefix) / n
            if src.exists():
                try:
                    shutil.copy2(src, _RT_DIR / n)
                except Exception:
                    pass

    missing = [n for n in _NEED if not (_RT_DIR / n).exists()]
    for n in ("msvcp140.dll", "msvcp140_1.dll"):
        if n in missing:
            # The ladybug wheel bundles a (renamed) msvcp140 we can reuse.
            if n == "msvcp140.dll":
                libs = Path(sys.prefix) / "Lib" / "site-packages" / "ladybug.libs"
                if libs.is_dir():
                    for cand in libs.glob("msvcp140*.dll"):
                        try:
                            shutil.copy2(cand, _RT_DIR / n)
                            break
                        except Exception:
                            pass

    missing = [n for n in _NEED if not (_RT_DIR / n).exists()]
    if missing:
        found = _find_x64(missing)
        for n, p in found.items():
            try:
                shutil.copy2(p, _RT_DIR / n)
            except Exception:
                logger.warning("Could not copy %s from %s", n, p)

    try:
        os.add_dll_directory(str(_RT_DIR))
    except Exception:
        pass
    os.environ["PATH"] = str(_RT_DIR) + os.pathsep + os.environ.get("PATH", "")

    ok = (_RT_DIR / "msvcp140.dll").exists()
    if not ok:
        logger.warning("VC++ runtime (msvcp140.dll) not found; embeddings may fail.")
    _prepared = ok
    return ok