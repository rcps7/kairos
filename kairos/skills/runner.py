"""Run a Kairos skill in an isolated subprocess.

The child gets a *proxy* engine that can only call a small, whitelisted subset
of engine methods (RPC back to the parent, which enforces the active
character's capabilities). The child runs in a fresh interpreter, a temporary
working directory, and a stripped environment (no secrets), with a hard
timeout.

Note: this is process isolation, not a hardened OS sandbox; container isolation
is planned. Use it to contain accidental damage and keep secrets out of skills.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from kairos import safety

logger = logging.getLogger(__name__)

ALLOWED_METHODS = {"ask_llm", "search_web", "scrape_page", "learn_from_page",
                   "add_memory", "recall"}


class SandboxUnavailable(RuntimeError):
    """Raised when the sandbox itself cannot run (not a skill error)."""

_CHILD = r'''
import json, sys
repo, skill_path, args_json = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo)

import importlib.util
spec = importlib.util.spec_from_file_location("kairos_sandbox_skill", skill_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

from kairos.skills.base import Skill
cls = None
for v in vars(mod).values():
    if isinstance(v, type) and issubclass(v, Skill) and v is not Skill:
        cls = v
        break
if cls is None:
    print(json.dumps({"done": True, "error": "no Skill subclass found"}))
    sys.exit(0)


def rpc(method, **kwargs):
    sys.stdout.write(json.dumps({"rpc": {"method": method, "args": kwargs}}) + "\n")
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("parent closed the connection")
    msg = json.loads(line)
    if "error" in msg:
        raise RuntimeError(msg["error"])
    return msg.get("result")


class ProxyEngine:
    def ask_llm(self, prompt, **k): return rpc("ask_llm", prompt=prompt)
    def search_web(self, query, max_results=10): return rpc("search_web", query=query, max_results=max_results)
    def scrape_page(self, url): return rpc("scrape_page", url=url)
    def learn_from_page(self, url): return rpc("learn_from_page", url=url)
    def add_memory(self, content): return rpc("add_memory", content=content)
    def recall(self, query, limit=8): return rpc("recall", query=query, limit=limit)


try:
    args = json.loads(args_json)
    out = cls().run(ProxyEngine(), **args)
    print(json.dumps({"done": True, "result": str(out)}))
except Exception as e:
    print(json.dumps({"done": True, "error": str(e)}))
'''


def _install_root() -> str:
    import kairos
    return str(Path(kairos.__file__).resolve().parent.parent)


def _child_env():
    sysroot = os.environ.get("SystemRoot", "")
    return {
        "SystemRoot": sysroot,
        "PATH": os.path.join(sysroot, "System32") if sysroot else "",
        "TEMP": tempfile.gettempdir(),
        "TMP": tempfile.gettempdir(),
    }


def run_skill_sandboxed(skill_path, engine, args=None, timeout: float = 30.0) -> str:
    skill_path = Path(skill_path)
    with tempfile.TemporaryDirectory(prefix="kairos_skill_") as cwd:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", _CHILD, _install_root(), str(skill_path),
                 json.dumps(args or {})],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, cwd=cwd, env=_child_env(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            raise SandboxUnavailable(str(e)) from e
        killer = threading.Timer(timeout, proc.kill)
        killer.start()
        try:
            saw_output = False
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                saw_output = True
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if msg.get("done"):
                    if msg.get("error"):
                        raise RuntimeError(safety.redact_secrets(str(msg["error"])))
                    return msg.get("result", "")
                rpc = msg.get("rpc")
                if rpc:
                    method = rpc.get("method")
                    a = rpc.get("args", {})
                    try:
                        if method not in ALLOWED_METHODS:
                            raise PermissionError(f"method '{method}' is not allowed")
                        result = getattr(engine, method)(**a)
                        if not isinstance(result, (str, int, float, bool, type(None))):
                            result = str(result)
                        proc.stdin.write(json.dumps({"result": result}) + "\n")
                    except Exception as e:
                        proc.stdin.write(json.dumps({"error": safety.redact_secrets(str(e))}) + "\n")
                    proc.stdin.flush()
            if not saw_output:
                raise SandboxUnavailable("skill sandbox produced no output")
            raise RuntimeError("skill sandbox ended without a result")
        finally:
            killer.cancel()
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass