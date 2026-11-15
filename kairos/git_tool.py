"""Git & version-control workflows via the system ``git`` CLI (no dependency).

Every command runs with :mod:`subprocess` (``shell=False``) inside a configured
repository root. The root confines which repositories may be operated on;
``push``/``pull`` are opt-in, and destructive operations (force/hard reset/clean)
are blocked unless explicitly enabled in config (``git.*``).

Config (``git``)::

    {
      "enabled": false,
      "repo_root": "C:/path/to/repos",
      "allow_push": false,
      "allow_pull": false,
      "allow_destructive": false,
      "author_name": "",
      "author_email": "",
      "token": null            # secret -> keyring ("git_token")
    }
"""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_NAME_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,120}$")
_REF_RE = re.compile(r"^[A-Za-z0-9._/~^@{}\-]{1,200}$")


class GitError(RuntimeError):
    pass


def _cfg() -> dict:
    try:
        from kairos import config
        return (config.load_config().get("git", {}) or {})
    except Exception:
        return {}


def available() -> bool:
    """Return True if a usable ``git`` executable is on PATH."""
    return shutil.which("git") is not None


def _root() -> Path:
    cfg = _cfg()
    try:
        from kairos import config
        agent = config.load_config().get("agent", {}) or {}
    except Exception:
        agent = {}
    root = cfg.get("repo_root") or agent.get("file_root") or os.path.expanduser("~")
    return Path(root).expanduser().resolve()


def _confine(repo=None) -> Path:
    base = _root()
    target = Path(repo).expanduser().resolve() if repo else base
    if target != base and base not in target.parents:
        raise PermissionError("Repository is outside the allowed git root (git.repo_root).")
    return target


def _env() -> dict:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")   # never block on credential prompts
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("GIT_OPTIONAL_LOCKS", "0")
    cfg = _cfg()
    if cfg.get("author_name"):
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = cfg["author_name"]
    if cfg.get("author_email"):
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = cfg["author_email"]
    return env


def _run(repo, args, timeout: int = 30, check: bool = True) -> str:
    exe = shutil.which("git")
    if not exe:
        raise GitError("git executable not found on PATH.")
    d = _confine(repo)
    try:
        proc = subprocess.run([exe, *[str(a) for a in args]], cwd=str(d),
                              capture_output=True, text=True, timeout=timeout,
                              env=_env(), creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise GitError(f"git {' '.join(map(str, args))} timed out")
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if check and proc.returncode != 0:
        raise GitError((err or out or f"git {' '.join(map(str, args))} failed")[:800])
    return out or err


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if (not _NAME_RE.match(name) or ".." in name
            or name.startswith(("/", "\\", "-"))):
        raise ValueError("Invalid branch/remote name.")
    return name


def _check_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not _REF_RE.match(ref) or ref.startswith("-"):
        raise ValueError("Invalid git ref.")
    return ref


def _require_enabled():
    if not _cfg().get("enabled"):
        raise PermissionError("Git integration is disabled (git.enabled).")


def _require(flag: str, label: str):
    if not _cfg().get(flag):
        raise PermissionError(f"{label} is disabled (git.{flag}).")


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------
def is_repo(repo=None) -> bool:
    try:
        _confine(repo)
        return _run(repo, ["rev-parse", "--is-inside-work-tree"], check=False).strip() == "true"
    except Exception:
        return False


def current_branch(repo=None) -> str:
    return _run(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def status(*, repo=None) -> str:
    _require_enabled()
    out = _run(repo, ["status", "--porcelain=v1", "-b", "--untracked-files=all"])
    return out or "(clean working tree)"


def diff(staged: bool = False, ref: str = None, *, repo=None) -> str:
    _require_enabled()
    args = ["diff"]
    if staged:
        args.append("--staged")
    if ref:
        args.append(_check_ref(ref))
    out = _run(repo, args, timeout=60)
    return out[:20000] or "(no differences)"


def log(n: int = 20, *, repo=None) -> str:
    _require_enabled()
    n = max(1, min(int(n or 20), 200))
    return _run(repo, ["log", f"-n{n}", "--date=short",
                       "--pretty=format:%h  %ad  %an  %s"], check=False) or "(no commits)"


def branches(*, repo=None) -> str:
    _require_enabled()
    return _run(repo, ["branch", "-a", "--no-color"], check=False) or "(no branches)"


def remotes(*, repo=None) -> str:
    _require_enabled()
    return _run(repo, ["remote", "-v"], check=False) or "(no remotes)"


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
def init(*, repo=None) -> str:
    _require_enabled()
    return _run(repo, ["init"]) or "initialized"


def create_branch(name: str = "", checkout: bool = True, *, repo=None) -> str:
    _require_enabled()
    name = _check_name(name)
    if checkout:
        return _run(repo, ["checkout", "-b", name]) or f"switched to new branch {name}"
    return _run(repo, ["branch", name]) or f"created branch {name}"


def checkout(name: str = "", *, repo=None) -> str:
    _require_enabled()
    name = _check_name(name)
    return _run(repo, ["checkout", name]) or f"checked out {name}"


def add(paths=None, *, repo=None) -> str:
    _require_enabled()
    if paths:
        return _run(repo, ["add", "--", *[str(p) for p in paths]], timeout=60) or "staged"
    return _run(repo, ["add", "-A"], timeout=60) or "staged"


def commit(message: str = "", add_all: bool = False, *, repo=None) -> str:
    _require_enabled()
    message = (message or "").strip()
    if not message:
        raise ValueError("Commit message is required.")
    if add_all:
        _run(repo, ["add", "-A"], timeout=60)
    return _run(repo, ["commit", "-m", message], timeout=60)


def stash(*, repo=None) -> str:
    _require_enabled()
    return _run(repo, ["stash"]) or "stashed"


def pull(*, repo=None) -> str:
    _require_enabled()
    _require("allow_pull", "Git pull")
    return _run(repo, ["pull", "--ff-only"], timeout=120)


def push(remote: str = "origin", branch: str = None, *, repo=None) -> str:
    _require_enabled()
    _require("allow_push", "Git push")
    remote = _check_name(remote or "origin")
    args = ["push", remote]
    if branch:
        args.append(_check_name(branch))
    # Never force: guarded by omission and the destructive block below.
    if any(a in ("--force", "-f", "--force-with-lease") for a in args):
        raise PermissionError("Force push is not permitted.")
    return _run(repo, args, timeout=120)


def summary(repo=None) -> str:
    """Compact human-readable repository summary for the GUI/Telegram."""
    if not available():
        return "git is not installed on this system."
    try:
        _confine(repo)
    except PermissionError as e:
        return str(e)
    if not is_repo(repo):
        return "Not a git repository (run `git init` or set git.repo_root)."
    parts = []
    try:
        parts.append(f"Branch: {current_branch(repo)}")
    except Exception as e:
        parts.append(f"Branch: (error: {e})")
    try:
        parts.append("Status:\n" + status(repo))
    except Exception as e:
        parts.append(f"Status: (error: {e})")
    return "\n".join(parts)
