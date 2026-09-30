"""OpenAI-style tool registry for native function-calling.

Exposes a safe subset of engine capabilities as JSON-schema tools. The engine's
native chat loop (when enabled) passes these to the provider and executes the
returned tool calls. All tool output is treated as untrusted data.
"""

import json
import logging
import os
import subprocess

from kairos import safety

try:
    from kairos import config as _config
except Exception:
    _config = None

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
    _fn("plan_create", "Create a multi-step plan for a goal.",
        {"goal": {"type": "string"},
         "steps": {"type": "array", "items": {"type": "string"}}}, ["goal"]),
    _fn("plan_add_step", "Add a step to an existing plan.",
        {"plan_id": {"type": "string"}, "title": {"type": "string"}},
        ["plan_id", "title"]),
    _fn("plan_update_step", "Update a plan step's status/result.",
        {"step_id": {"type": "string"}, "status": {"type": "string"},
         "result": {"type": "string"}}, ["step_id", "status"]),
    _fn("plan_status", "Show a plan and its steps.",
        {"plan_id": {"type": "string"}}, ["plan_id"]),
    _fn("read_file", "Read a text file inside the allowed root.",
        {"path": {"type": "string"}}, ["path"]),
    _fn("write_file", "Write a text file inside the allowed root.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"]),
    _fn("list_dir", "List files in a directory inside the allowed root.",
        {"path": {"type": "string"}}, []),
    _fn("run_command", "Run a shell command (disabled unless explicitly enabled).",
        {"command": {"type": "string"}}, ["command"]),
    _fn("sql_query", "Run a read-only SQL query over registered CSV/Parquet files.",
        {"sql": {"type": "string"}}, ["sql"]),
    _fn("github_search_repos", "Search GitHub repositories.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("github_list_issues", "List issues in a GitHub repo (owner/name).",
        {"repo": {"type": "string"}, "state": {"type": "string"}}, ["repo"]),
    _fn("github_get_issue", "Get a GitHub issue.",
        {"repo": {"type": "string"}, "number": {"type": "integer"}}, ["repo", "number"]),
    _fn("notion_search", "Search Notion pages/databases.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("generate_image", "Generate an image from a prompt and save it.",
        {"prompt": {"type": "string"}}, ["prompt"]),
    _fn("browser_fetch", "Render a web page in a headless browser and return its text.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("browser_screenshot", "Screenshot a web page and save it.",
        {"url": {"type": "string"}}, ["url"]),
    _fn("browser_action", "Run browser actions (click/type/wait/text/screenshot) on a page.",
        {"url": {"type": "string"},
         "actions": {"type": "array", "items": {"type": "object"}}}, ["url"]),
    _fn("google_search", "Search Google Drive files by name.",
        {"query": {"type": "string"}}, ["query"]),
    _fn("delegate", "Delegate a task to a named sub-agent (researcher, coder, "
        "analyst, writer, planner).",
        {"agent": {"type": "string"}, "task": {"type": "string"}},
        ["agent", "task"]),
]

_CAP = {
    "web_search": "web_search",
    "learn_web": "learn_web",
    "scrape_page": "learn_web",
    "remember": "memory",
    "recall": None,
    "predict": "predict",
    "plan_create": None,
    "plan_add_step": None,
    "plan_update_step": None,
    "plan_status": None,
    "read_file": None,
    "write_file": None,
    "list_dir": None,
    "run_command": None,
    "sql_query": None,
    "github_search_repos": None,
    "github_list_issues": None,
    "github_get_issue": None,
    "notion_search": None,
    "generate_image": None,
    "browser_fetch": "learn_web",
    "browser_screenshot": "learn_web",
    "browser_action": "learn_web",
    "google_search": None,
    "delegate": None,
}


def _agent_cfg():
    try:
        if _config is None:
            return {}
        return (_config.load_config().get("agent", {}) or {})
    except Exception:
        return {}


def _file_root():
    root = _agent_cfg().get("file_root") or str(os.path.expanduser("~"))
    return os.path.abspath(root)


def _confine(path: str) -> str:
    root = _file_root()
    target = os.path.abspath(os.path.join(root, path or ""))
    if target != root and not target.startswith(root + os.sep):
        raise PermissionError("Path is outside the allowed root.")
    return target


def available_tools(engine) -> list:
    out = []
    for t in TOOL_SCHEMAS:
        cap = _CAP.get(t["function"]["name"])
        try:
            if cap is None or engine.can(cap):
                out.append(t)
        except Exception:
            out.append(t)
    try:
        from kairos import mcp_client
        if mcp_client.enabled():
            out.extend(mcp_client.tool_schemas())
    except Exception:
        pass
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
    if name == "plan_create":
        pid = engine.plan_create(args.get("goal", ""), args.get("steps") or [])
        return f"Plan created: {pid}"
    if name == "plan_add_step":
        sid = engine.plan_add_step(args.get("plan_id", ""), args.get("title", ""))
        return f"Step added: {sid}"
    if name == "plan_update_step":
        engine.plan_update_step(args.get("step_id", ""), args.get("status", ""),
                                args.get("result", ""))
        return "Step updated."
    if name == "plan_status":
        p = engine.plan_get(args.get("plan_id", ""))
        if not p:
            return "Plan not found."
        lines = [f"{p['goal']} [{p['status']}]"]
        for s in p["steps"]:
            lines.append(f"  {s['idx']}. [{s['status']}] {s['title']}")
        return "\n".join(lines)
    if name == "read_file":
        p = _confine(args.get("path", ""))
        with open(p, "rb") as f:
            return f.read(200000).decode("utf-8", "ignore")
    if name == "write_file":
        if not _agent_cfg().get("allow_file_write", True):
            raise PermissionError("File writes are disabled (agent.allow_file_write).")
        p = _confine(args.get("path", ""))
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        safety.atomic_write_text(p, args.get("content", ""))
        return f"Wrote {p}"
    if name == "list_dir":
        p = _confine(args.get("path", "") or ".")
        return "\n".join(sorted(os.listdir(p))[:500])
    if name == "run_command":
        if not _agent_cfg().get("allow_shell", False):
            raise PermissionError("Shell execution is disabled (agent.allow_shell).")
        import tempfile
        out = subprocess.run(args.get("command", ""), shell=True, capture_output=True,
                             text=True, timeout=30, cwd=tempfile.gettempdir(),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (out.stdout + out.stderr)[:8000]
    if name == "sql_query":
        from kairos import sql_tool
        return sql_tool.run_sql(args.get("sql", ""), files=args.get("files"),
                                root=_file_root())
    if name.startswith("github_"):
        from kairos.connectors import github as gh
        if name == "github_search_repos":
            return gh.search_repos(args.get("query", ""))
        if name == "github_list_issues":
            return gh.list_issues(args.get("repo", ""), args.get("state", "open"))
        if name == "github_get_issue":
            return gh.get_issue(args.get("repo", ""), int(args.get("number", 0)))
    if name == "notion_search":
        from kairos.connectors import notion as nt
        return nt.search(args.get("query", ""))
    if name == "google_search":
        from kairos.connectors import google as g
        return g.search_files(args.get("query", ""))
    if name == "browser_action":
        from kairos import browser
        return browser.run_actions(args.get("url", ""), args.get("actions") or [])
    if name == "generate_image":
        from kairos import imagegen
        return "Image saved: " + imagegen.generate(args.get("prompt", ""))
    if name == "browser_fetch":
        from kairos import browser
        return browser.fetch_text(args.get("url", ""))
    if name == "browser_screenshot":
        from kairos import browser
        return "Screenshot saved: " + browser.screenshot(args.get("url", ""))
    if name == "delegate":
        from kairos import agents
        return agents.run_subagent(engine, args.get("agent", ""), args.get("task", ""))
    if name.startswith("mcp__"):
        from kairos import mcp_client
        return mcp_client.call(name, args)
    raise PermissionError(f"Unknown or disallowed tool '{name}'.")