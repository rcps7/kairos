"""Optional Docker-backed skill sandbox.

Runs a skill inside a throwaway container with no network and read-only mounts
of the Kairos install and the skill file. Requires Docker to be installed and
running; otherwise callers fall back to the subprocess sandbox.
"""

import json
import logging
import shutil
import subprocess

from .runner import _CHILD, SandboxUnavailable, _install_root, pump_rpc

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "python:3.12-slim"


def available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def run_skill_docker(skill_path, engine, args=None, timeout: float = 60.0,
                     image: str = DEFAULT_IMAGE) -> str:
    if not available():
        raise SandboxUnavailable("Docker is not available")
    repo = _install_root()
    cmd = [
        "docker", "run", "-i", "--rm", "--network", "none",
        "--cpus", "1", "-m", "512m",
        "-v", f"{repo}:/app:ro",
        "-v", f"{skill_path}:/skill.py:ro",
        "-w", "/app",
        image, "python", "-c", _CHILD, "/app", "/skill.py", json.dumps(args or {}),
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
    except OSError as e:
        raise SandboxUnavailable(str(e)) from e
    return pump_rpc(proc, engine, timeout)