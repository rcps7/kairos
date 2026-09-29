"""Minimal Model Context Protocol (MCP) client over stdio.

Speaks newline-delimited JSON-RPC 2.0 to a server process: initialize,
tools/list and tools/call. No third-party dependency; each call starts the
configured server, performs the request, and stops it.

Config:
    "mcp": {"enabled": false, "servers": {
        "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]}
    }}
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


def _child_env(extra=None):
    env = {"SystemRoot": os.environ.get("SystemRoot", ""),
           "PATH": os.environ.get("PATH", ""),
           "TEMP": os.environ.get("TEMP", ""), "TMP": os.environ.get("TMP", "")}
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


class MCPClient:
    def __init__(self, command, args=None, env=None, timeout=25.0):
        self.command = command
        self.args = list(args or [])
        self.env = env or {}
        self.timeout = timeout
        self.proc = None
        self._id = 0
        self._reader = None
        self._lines = []
        self._lock = threading.Lock()

    # ---- process / transport ----
    def start(self):
        self.proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, env=_child_env(self.env),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "kairos", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def stop(self):
        try:
            if self.proc:
                self.proc.kill()
        except Exception:
            pass
        self.proc = None

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if line:
                    with self._lock:
                        self._lines.append(line)
        except Exception:
            pass

    def _write(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method, params):
        self._id += 1
        rid = self._id
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            with self._lock:
                line = self._lines.pop(0) if self._lines else None
            if line is None:
                time.sleep(0.05)
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise MCPError(str(msg["error"]))
                return msg.get("result", {})
        raise MCPError(f"MCP request '{method}' timed out")

    # ---- high level ----
    def list_tools(self):
        result = self._request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name, arguments=None):
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        parts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "\n".join(parts) or json.dumps(result)[:4000]


# ---------------------------------------------------------------------------
# Config-driven manager
# ---------------------------------------------------------------------------
def _cfg():
    try:
        from kairos import config
        return config.load_config().get("mcp", {}) or {}
    except Exception:
        return {}


def servers():
    return _cfg().get("servers", {}) or {}


def enabled() -> bool:
    c = _cfg()
    return bool(c.get("enabled")) and bool(c.get("servers"))


def tool_schemas():
    """Return OpenAI-style tool schemas for every MCP tool (best effort)."""
    out = []
    if not enabled():
        return out
    for sname, scfg in servers().items():
        client = MCPClient(scfg.get("command", ""), scfg.get("args"), scfg.get("env"))
        try:
            client.start()
            for t in client.list_tools():
                tname = t.get("name", "")
                out.append({
                    "type": "function",
                    "function": {
                        "name": f"mcp__{sname}__{tname}",
                        "description": (t.get("description") or "")[:300],
                        "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                    },
                })
        except Exception:
            logger.exception("MCP server '%s' failed", sname)
        finally:
            client.stop()
    return out


def call(full_name: str, arguments=None) -> str:
    # full_name = mcp__<server>__<tool>
    if not full_name.startswith("mcp__"):
        raise ValueError("Not an MCP tool name")
    rest = full_name[len("mcp__"):]
    sname, _, tool = rest.partition("__")
    scfg = servers().get(sname)
    if not scfg:
        raise PermissionError(f"MCP server '{sname}' not configured")
    client = MCPClient(scfg.get("command", ""), scfg.get("args"), scfg.get("env"))
    try:
        client.start()
        return client.call_tool(tool, arguments or {})
    finally:
        client.stop()