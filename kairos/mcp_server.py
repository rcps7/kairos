"""Expose Kairos tools as a Model Context Protocol (MCP) stdio server.

Run with:  python -m kairos.mcp_server

Speaks newline-delimited JSON-RPC 2.0 over stdio (initialize, tools/list,
tools/call). The engine is created lazily on the first tool call that needs it.
"""

import json
import logging
import sys

from kairos import toolkit

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from kairos.main import KairosEngine
        _engine = KairosEngine()
    return _engine


def _tool_defs():
    out = []
    for t in toolkit.TOOL_SCHEMAS:
        f = t["function"]
        out.append({"name": f["name"], "description": f.get("description", ""),
                    "inputSchema": f.get("parameters") or {"type": "object", "properties": {}}})
    out.append({"name": "kairos_info", "description": "Return the Kairos version.",
                "inputSchema": {"type": "object", "properties": {}}})
    return out


def _handle(method, params):
    from kairos import __version__
    if method == "initialize":
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                "serverInfo": {"name": "kairos", "version": __version__}}
    if method == "tools/list":
        return {"tools": _tool_defs()}
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        if name == "kairos_info":
            return {"content": [{"type": "text", "text": f"Kairos {__version__}"}]}
        try:
            out = toolkit.execute(_get_engine(), name, args)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
        return {"content": [{"type": "text", "text": str(out)[:8000]}]}
    return {}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        method = msg.get("method")
        if method and method.startswith("notifications/"):
            continue
        rid = msg.get("id")
        try:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "result": _handle(method, msg.get("params") or {})}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": str(e)}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()