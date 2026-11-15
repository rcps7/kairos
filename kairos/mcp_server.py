"""Expose Kairos tools as a Model Context Protocol (MCP) stdio server.

Run with:  python -m kairos.mcp_server

Speaks newline-delimited JSON-RPC 2.0 over stdio: ``initialize``, ``tools/list``,
``tools/call``, plus ``resources/list``/``resources/read`` and
``prompts/list``/``prompts/get`` (toggleable under ``mcp.server``).

The engine is created lazily and **headless** (see ``KairosEngine(headless=True)``)
so the MCP process never touches the running GUI's pid/heartbeat files nor starts
the scheduler / collaboration / Discord / webhook services.
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
        # Headless engine: never touches the watchdog pid/heartbeat files nor
        # starts the scheduler/collab/discord/webhook services, so an MCP server
        # process cannot clobber a running GUI instance.
        _engine = KairosEngine(headless=True)
    return _engine


def _server_cfg() -> dict:
    try:
        from kairos import config
        return (config.load_config().get("mcp", {}) or {}).get("server", {}) or {}
    except Exception:
        return {}


def _tool_defs():
    out = []
    for t in toolkit.TOOL_SCHEMAS:
        f = t["function"]
        out.append({"name": f["name"], "description": f.get("description", ""),
                    "inputSchema": f.get("parameters") or {"type": "object", "properties": {}}})
    out.append({"name": "kairos_info", "description": "Return the Kairos version.",
                "inputSchema": {"type": "object", "properties": {}}})
    return out


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------
def _resources():
    return [
        {"uri": "kairos://version", "name": "Kairos version", "mimeType": "text/plain"},
        {"uri": "kairos://config", "name": "Kairos config (secrets redacted)",
         "mimeType": "application/json"},
        {"uri": "kairos://knowledge/memories", "name": "Retained memories",
         "mimeType": "text/plain"},
        {"uri": "kairos://graph/stats", "name": "Knowledge graph stats",
         "mimeType": "application/json"},
    ]


def _redacted_config() -> dict:
    from kairos import config
    cfg = config.load_config()
    cfg.pop("telegram_token", None)
    for p in (cfg.get("llm_providers", {}) or {}).values():
        p.pop("api_key", None)
    (cfg.setdefault("webhook", {})).pop("secret", None)
    (cfg.get("webhook", {}).get("outbound", {}) or {}).pop("secret", None)
    (cfg.setdefault("git", {})).pop("token", None)
    (cfg.get("mirofish", {})).pop("zep_api_key", None)
    email = cfg.setdefault("email", {})
    email.pop("password", None)
    return cfg


def _read_resource(uri: str):
    from kairos import __version__
    eng = _get_engine()
    if uri == "kairos://version":
        return "text/plain", f"Kairos {__version__}"
    if uri == "kairos://config":
        return "application/json", json.dumps(_redacted_config(), indent=2)[:20000]
    if uri == "kairos://knowledge/memories":
        try:
            items = eng.list_memories()
        except Exception:
            items = []
        text = "\n".join(f"- {m[1] if isinstance(m, (list, tuple)) else m}"
                         for m in (items or []))[:20000]
        return "text/plain", text or "(no retained memories)"
    if uri == "kairos://graph/stats":
        try:
            stats = eng.graph_stats()
        except Exception:
            stats = {"available": False}
        return "application/json", json.dumps(stats, indent=2)
    raise ValueError(f"Unknown resource: {uri}")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
_PROMPTS = {
    "research_topic": {
        "description": "Research a topic on the web and summarize with sources.",
        "arguments": [{"name": "topic", "description": "The topic to research",
                       "required": True}],
        "template": ("Research the following topic using web search as needed and "
                     "summarize the key points with sources:\n\n{topic}"),
    },
    "make_plan": {
        "description": "Produce an ordered, actionable plan for a goal.",
        "arguments": [{"name": "goal", "description": "The goal", "required": True}],
        "template": ("Produce an ordered, actionable plan (JSON array of steps) "
                     "for this goal:\n\n{goal}"),
    },
    "summarize_page": {
        "description": "Summarize a web page into bullet points.",
        "arguments": [{"name": "url", "description": "Page URL", "required": True}],
        "template": "Fetch and summarize this page into concise bullet points:\n\n{url}",
    },
    "git_commit_message": {
        "description": "Draft a clear git commit message for staged changes.",
        "arguments": [{"name": "context", "description": "What changed",
                       "required": False}],
        "template": ("Write a concise, conventional git commit message for the "
                     "following changes:\n\n{context}"),
    },
}


def _prompt_defs():
    return [{"name": k, "description": v["description"], "arguments": v["arguments"]}
            for k, v in _PROMPTS.items()]


def _get_prompt(name, args):
    spec = _PROMPTS.get(name)
    if not spec:
        raise ValueError(f"Unknown prompt: {name}")
    args = args or {}
    text = spec["template"]
    for a in spec["arguments"]:
        val = str(args.get(a["name"], "") or "")
        text = text.replace("{" + a["name"] + "}", val)
    return {"description": spec["description"],
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def _handle(method, params):
    from kairos import __version__
    cfg = _server_cfg()
    expose_resources = cfg.get("expose_resources", True)
    expose_prompts = cfg.get("expose_prompts", True)

    if method == "initialize":
        caps = {"tools": {}}
        if expose_resources:
            caps["resources"] = {}
        if expose_prompts:
            caps["prompts"] = {}
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": caps,
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
    if method == "resources/list":
        return {"resources": _resources() if expose_resources else []}
    if method == "resources/read":
        uri = params.get("uri", "")
        try:
            mime, text = _read_resource(uri)
        except Exception as e:
            return {"contents": [{"uri": uri, "mimeType": "text/plain",
                                  "text": f"error: {e}"}]}
        return {"contents": [{"uri": uri, "mimeType": mime, "text": text}]}
    if method == "prompts/list":
        return {"prompts": _prompt_defs() if expose_prompts else []}
    if method == "prompts/get":
        try:
            return _get_prompt(params.get("name", ""), params.get("arguments"))
        except Exception as e:
            return {"description": "", "messages": [
                {"role": "user", "content": {"type": "text", "text": f"error: {e}"}}]}
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
