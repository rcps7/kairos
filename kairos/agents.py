"""Named sub-agents (delegation / handoffs).

Each sub-agent has a focused system prompt and a suggested toolset. The engine
can delegate a task to a sub-agent, which answers with its own (character-less)
prompt; when the native tool loop is active, the sub-agent inherits the parent's
tools.
"""

import logging

logger = logging.getLogger(__name__)

SUBAGENTS = {
    "researcher": {
        "description": "Gathers and cites information from the web.",
        "system": (
            "You are a RESEARCH sub-agent. Find accurate, sourced information. "
            "Use web tools when enabled; cite sources. Be concise and factual; "
            "clearly mark uncertainty."
        ),
        "tools": ["web_search", "learn_web", "scrape_page"],
    },
    "coder": {
        "description": "Writes and reviews code and runs commands.",
        "system": (
            "You are a CODING sub-agent. Produce correct, minimal, well-structured "
            "code. Explain briefly. Use file/shell tools only when permitted."
        ),
        "tools": ["read_file", "write_file", "list_dir", "run_command"],
    },
    "analyst": {
        "description": "Analyzes data and produces structured findings.",
        "system": (
            "You are an ANALYSIS sub-agent. Break the problem down, reason from "
            "evidence, quantify where possible, and present findings and caveats."
        ),
        "tools": ["sql_query", "web_search"],
    },
    "writer": {
        "description": "Drafts clear prose, summaries and documentation.",
        "system": (
            "You are a WRITING sub-agent. Produce clear, well-organized prose for "
            "the requested audience. No fabrication of facts."
        ),
        "tools": [],
    },
    "planner": {
        "description": "Decomposes goals into ordered steps.",
        "system": (
            "You are a PLANNING sub-agent. Decompose the goal into a short, ordered "
            "list of concrete steps with clear deliverables. Reply with the steps."
        ),
        "tools": ["plan_create", "plan_add_step"],
    },
}


def list_subagents() -> list:
    return [{"name": k, "description": v["description"], "tools": v["tools"]}
            for k, v in SUBAGENTS.items()]


def run_subagent(engine, name: str, task: str) -> str:
    spec = SUBAGENTS.get((name or "").strip().lower())
    if not spec:
        raise ValueError(f"Unknown sub-agent '{name}'. "
                         f"Available: {', '.join(SUBAGENTS)}")
    return engine.ask_llm(task, system_prompt=spec["system"], use_character=False)