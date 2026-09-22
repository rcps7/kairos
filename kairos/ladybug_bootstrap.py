"""Assemble a working native runtime for the LadybugDB Python package.

The published ``ladybug`` wheel ships the Python bindings but, on Windows at
least, not the native shared library (``lbug_shared.dll``) nor the OpenSSL 3
runtime it links against. This module prepares everything the C-API backend
needs, caches it under ``~/.kairos/lbug/<version>/``, and sets the environment
variables *before* the first database is opened.

Nothing here is imported unless graph memory is enabled.
"""

import logging
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_ROOT = Path.home() / ".kairos" / "lbug"
DEFAULT_VERSION = "0.20.4"
DOWNLOAD_BASE = "https://github.com/LadybugDB/ladybug/releases/download/v{ver}/{asset}"

# platform.machine() -> release asset name and shared-library file names
_ASSETS = {
    ("win32", "amd64"): ("liblbug-windows-x86_64.zip", ["lbug_shared.dll", "lbug.dll"]),
    ("win32", "arm64"): ("liblbug-windows-arm64.zip", ["lbug_shared.dll", "lbug.dll"]),
    ("linux", "x86_64"): ("liblbug-linux-x86_64.tar.gz", ["liblbug.so", "liblbug.so.0"]),
    ("linux", "aarch64"): ("liblbug-linux-aarch64.tar.gz", ["liblbug.so", "liblbug.so.0"]),
    ("linux", "arm64"): ("liblbug-linux-aarch64.tar.gz", ["liblbug.so", "liblbug.so.0"]),
    ("darwin", "x86_64"): ("liblbug-osx-x86_64.tar.gz", ["liblbug.dylib"]),
    ("darwin", "arm64"): ("liblbug-osx-arm64.tar.gz", ["liblbug.dylib"]),
}

_prepared = None


def _machine() -> str:
    import platform
    m = (platform.machine() or "").lower()
    return {"amd64": "amd64", "x86_64": "x86_64", "aarch64": "aarch64",
            "arm64": "arm64"}.get(m, m)


def _asset_info():
    key = (sys.platform if sys.platform in ("win32", "linux", "darwin") else sys.platform, _machine())
    if key not in _ASSETS:
        # Fall back to x86_64 asset on unknown machine names.
        for k, v in _ASSETS.items():
            if k[0] == key[0]:
                return v
        return None
    return _ASSETS[key]


def _ladybug_version() -> str:
    try:
        from importlib.metadata import version
        return version("ladybug")
    except Exception:
        return DEFAULT_VERSION


def _download(url: str, dest: Path):
    import httpx
    logger.info("Downloading Ladybug runtime: %s", url)
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0,
                      headers={"User-Agent": "kairos-ladybug"}) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def _extract(archive: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest)


def _find(root: Path, names):
    for p in root.rglob("*"):
        if p.name in names and p.is_file():
            return p
    return None


def _copy_first(dest_dir: Path, dst_name: str, candidates):
    """Copy the first existing candidate path to dest_dir/dst_name."""
    for c in candidates:
        try:
            if c and Path(c).is_file():
                shutil.copy2(c, dest_dir / dst_name)
                return dest_dir / dst_name
        except Exception:
            continue
    return None


def _win_runtime(runtime_dir: Path):
    """Provide OpenSSL 3 + MSVC runtime next to lbug_shared.dll on Windows."""
    py_dlls = Path(sys.base_prefix) / "DLLs"
    site = Path(sys.prefix) / "Lib" / "site-packages"
    libs_dir = site / "ladybug.libs"

    # OpenSSL 3 (Python ships libssl-3.dll / libcrypto-3.dll).
    for base in ("libssl-3", "libcrypto-3"):
        target = runtime_dir / f"{base}-x64.dll"
        if not target.exists():
            _copy_first(runtime_dir, target.name, [
                py_dlls / f"{base}.dll",
                Path(r"C:\Windows\System32") / f"{base}.dll",
            ])
        # libssl-3.dll imports libcrypto-3.dll by its unsuffixed name.
        unsuffixed = runtime_dir / f"{base}.dll"
        if not unsuffixed.exists():
            _copy_first(runtime_dir, unsuffixed.name, [
                py_dlls / f"{base}.dll",
                runtime_dir / f"{base}-x64.dll",
            ])

    if not (runtime_dir / "msvcp140.dll").exists():
        mangled = list(libs_dir.glob("msvcp140*.dll")) if libs_dir.is_dir() else []
        _copy_first(runtime_dir, "msvcp140.dll", mangled + [
            Path(r"C:\Windows\System32") / "msvcp140.dll",
        ])

    for name in ("vcruntime140.dll", "vcruntime140_1.dll"):
        if not (runtime_dir / name).exists():
            _copy_first(runtime_dir, name, [
                Path(sys.base_prefix) / name,
                Path(r"C:\Windows\System32") / name,
            ])


def _set_env(runtime_dir: Path, lib_path: Path):
    os.environ["LBUG_C_API_LIB_PATH"] = str(lib_path)
    # The C-API backend is the reliable one; the pybind build needs the same
    # OpenSSL DLLs and has proven less stable.
    os.environ.setdefault("LBUG_PYTHON_BACKEND", "capi")
    if sys.platform == "win32":
        try:
            os.add_dll_directory(str(runtime_dir))
        except Exception:
            pass
    os.environ["PATH"] = str(runtime_dir) + os.pathsep + os.environ.get("PATH", "")


def ensure_runtime(force: bool = False) -> dict:
    """Ensure the native runtime is available. Returns a status dict."""
    global _prepared
    if _prepared is not None and not force:
        return _prepared

    info = _asset_info()
    if info is None:
        _prepared = {"available": False, "error": f"Unsupported platform {sys.platform}/{_machine()}"}
        return _prepared

    asset, lib_names = info
    ver = _ladybug_version()
    runtime_dir = CACHE_ROOT / ver
    runtime_dir.mkdir(parents=True, exist_ok=True)

    # 1. native shared library
    lib_path = _find(runtime_dir, lib_names)
    if lib_path is None:
        archive = runtime_dir / asset
        try:
            if not archive.exists():
                _download(DOWNLOAD_BASE.format(ver=ver, asset=asset), archive)
            extract_dir = runtime_dir / "_extract"
            _extract(archive, extract_dir)
            found = _find(extract_dir, lib_names)
            if not found:
                raise RuntimeError(f"shared library not found in {asset}")
            lib_path = runtime_dir / found.name
            shutil.copy2(found, lib_path)
        except Exception as e:
            logger.error("Failed to obtain Ladybug runtime: %s", e)
            _prepared = {"available": False, "error": str(e), "runtime_dir": str(runtime_dir)}
            return _prepared

    # 2. Windows transitive dependencies
    if sys.platform == "win32":
        try:
            _win_runtime(runtime_dir)
        except Exception:
            logger.exception("Failed to assemble Windows runtime dependencies.")

    # 3. environment
    _set_env(runtime_dir, lib_path)
    _prepared = {
        "available": True,
        "version": ver,
        "runtime_dir": str(runtime_dir),
        "lib_path": str(lib_path),
        "error": None,
    }
    logger.info("Ladybug runtime ready: %s", lib_path)
    return _prepared


def import_ladybug():
    """Prepare the runtime and import the ladybug module. Returns (module, info)."""
    info = ensure_runtime()
    import ladybug  # noqa: E402  (must be after env is set)
    return ladybug, info