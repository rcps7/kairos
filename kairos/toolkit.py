"""OpenAI-style tool registry for native function-calling.

Exposes a safe subset of engine capabilities as JSON-schema tools. The engine's
native chat loop (when enabled) passes these to the provider and executes the
returned tool calls. All tool output is treated as untrusted data.
"""

import json
import logging

logger = logging.getLogger(__name__)


def _fn(name, description, params, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": params,
                "required": required,
            },
        },
    }


TOOL_SCHEMAS = [
    _fn("web_search", "Search the web and return ranked results.",
        {"query": {"type": "string"}, "max_results": {"type": "integer"}}, ["query"]),
    _fn("learn_web", "Fetch a web page and store a summary in the knowledge library.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("scrape_page", "Fetch the readable text of a web page.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("remember", "Save a durable note/fact to retained memory.",
        {"content": {"type": "string"}}, ["content"]),
    _fn("recall", "Search retained memory and the knowledge graph.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("predict", "Run the predictive engine on a question.",
        {"question": {"type": "string"}}, ["question"]),
]

_CAP = {
    "web_search": "web_search",
    "learn_web": "learn_web",
    "scrape_page": "learn_web",
    "remember": "memory",
    "recall": None,
    "predict": "predict",
}


def available_tools(engine) -> list:
    out = []
    for t in TOOL_SCHEMAS:
        cap = _CAP.get(t["function"]["name"])
        try:
            if cap is None or engine.can(cap):
                out.append(t)
        except Exception:
            out.append(t)
    return out


def execute(engine, name: str, args: dict) -> str:
    args = args or {}
    if name == "web_search":
        results = engine.search_web(args.get("query", ""),
                                   max_results=int(args.get("max_results", 8)))
        return "\n".join(f"{i}. {r.get('title','')} — {r.get('url','')}\n   "
                         f"{(r.get('description') or '').strip()}"
                         for i, r in enumerate(results[:8], 1)) or "(no results)"
    if name == "learn_web":
        d = engine.learn_from_page(args.get("url", ""))
        return f"Page: {d.get('title','')}\n{d.get('summary','')}"
    if name == "scrape_page":
        d = engine.scrape_page(args.get("url", ""))
        return f"Page: {d.get('title','')}\n{(d.get('text') or '')[:6000]}"
    if name == "remember":
        engine.add_memory(args.get("content", ""))
        return "Saved to retained memory."
    if name == "recall":
        items = engine.recall(args.get("query", ""), limit=8)
        return "\n".join(f"- {it.get('text','')[:300]}" for it in items) or "(nothing found)"
    if name == "predict":
        res = engine.predict(args.get("question", ""))
        return res.get("report", "")
    raise PermissionError(f"Unknown or disallowed tool '{name}'.")