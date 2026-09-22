"""Provider-agnostic tool-call protocol for Kairos chat.

The chat pipeline asks the LLM to request tools as small, well-defined text
blocks. Kairos parses them, runs the matching engine tool, feeds the results
back, and asks the model for the final answer. No native function-calling API
is required, so it works with any OpenAI-compatible provider.
"""

import json
import re
from dataclasses import dataclass, field

MAX_TOOL_CALLS_PER_TURN = 4

_PROTOCOL_HEAD = (
    "TOOL PROTOCOL\n"
    "You are running inside the Kairos application. Tools are executed by the "
    "host, NOT by you. When (and only when) you need current or externally "
    "verifiable information, or the contents of a specific web page, end your "
    "turn with one or more of the available tool blocks below and nothing else. "
    "Do not add any commentary in the same message as a tool request. The host "
    "will run the tools and send you the results; only then produce the final "
    "answer. Never invent or fabricate tool output. If no external information "
    "is needed, answer the user directly in natural language."
)

_PROTOCOL_OVERRIDE = (
    "If the character instructions above tell you to 'use' a tool, interpret "
    "that as requesting it via this protocol."
)

_PROTOCOL_NONE = (
    "TOOL PROTOCOL\n"
    "No external tools are available to the current character. Do not emit tool "
    "tags; answer from your own knowledge and say when information may be "
    "unverified."
)


def build_tool_protocol(allowed_caps=None) -> str:
    """Return the tool protocol, restricted to the character's capabilities."""
    tools = []
    if allowed_caps is None or "web_search" in allowed_caps:
        tools.append("<web_search><query>your search query</query></web_search>")
    if allowed_caps is None or "learn_web" in allowed_caps:
        tools.append("<learn_web><url>https://example.com/page</url></learn_web>")
        tools.append("<scrape><url>https://example.com/page</url></scrape>")
    if not tools:
        return _PROTOCOL_NONE
    return (
        f"{_PROTOCOL_HEAD}\n\n{_PROTOCOL_OVERRIDE}\n\nAvailable now:\n  "
        + "\n  ".join(tools)
    )


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)

    @property
    def query(self) -> str:
        return (self.args.get("query") or "").strip()

    @property
    def url(self) -> str:
        return (self.args.get("url") or "").strip()


_NAME_ALIASES = {
    "search": "web_search",
    "websearch": "web_search",
    "web_search": "web_search",
    "learn": "learn_web",
    "learn_from_page": "learn_web",
    "learn_web": "learn_web",
    "scrape": "scrape",
    "scrape_page": "scrape",
    "fetch": "scrape",
}

_RE_SEARCH = re.compile(
    r"<web_search>\s*(?:<query>\s*(.*?)\s*</query>|(.*?))\s*</web_search>",
    re.I | re.S,
)
_RE_LEARN = re.compile(
    r"<learn_web>\s*(?:<url>\s*(.*?)\s*</url>|(.*?))\s*</learn_web>",
    re.I | re.S,
)
_RE_SCRAPE = re.compile(
    r"<scrape>\s*(?:<url>\s*(.*?)\s*</url>|(.*?))\s*</scrape>",
    re.I | re.S,
)
_RE_GENERIC = re.compile(r"<tool\s+name=[\"']([A-Za-z_]+)[\"'][^>]*>(.*?)</tool>", re.I | re.S)
_RE_JSON = re.compile(r"\{[^{}]*\}", re.S)
_RE_JSON_KEY = re.compile(r"[\"'](?:tool|action|name)[\"']\s*:", re.I)
_RE_INNER = re.compile(r"<(query|url)>\s*(.*?)\s*</\1>", re.I | re.S)


def _call_from_name(name: str, arg: str):
    key = _NAME_ALIASES.get((name or "").strip().lower())
    if not key:
        return None
    arg = (arg or "").strip()
    if key == "web_search":
        return ToolCall(key, {"query": arg})
    return ToolCall(key, {"url": arg})


def parse_tool_calls(text: str):
    """Split a model reply into (clean_text, [ToolCall]).

    Recognises several formats so that different models are handled without
    native function-calling.
    """
    if not text:
        return "", []

    calls = []
    spans = []

    def _collect(regex, name):
        for m in regex.finditer(text):
            arg = m.group(1) if m.lastindex and m.group(1) is not None else (
                m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            )
            arg = (arg or "").strip()
            calls.append(ToolCall(name, {"query": arg} if name == "web_search" else {"url": arg}))
            spans.append(m.span())

    _collect(_RE_SEARCH, "web_search")
    _collect(_RE_LEARN, "learn_web")
    _collect(_RE_SCRAPE, "scrape")

    for m in _RE_GENERIC.finditer(text):
        call = _call_from_name(m.group(1), _inner_arg(m.group(2)))
        if call:
            calls.append(call)
            spans.append(m.span())

    for m in _RE_JSON.finditer(text):
        blob = m.group(0)
        if not _RE_JSON_KEY.search(blob):
            continue
        try:
            obj = json.loads(blob)
        except Exception:
            continue
        name = str(obj.get("tool") or obj.get("action") or obj.get("name") or "")
        call = _call_from_name(name, obj.get("query") or obj.get("url") or obj.get("input") or "")
        if call:
            calls.append(call)
            spans.append(m.span())

    clean = _remove_spans(text, spans)
    clean = strip_tool_markup(clean)
    return clean, calls[:MAX_TOOL_CALLS_PER_TURN]


def _inner_arg(inner: str) -> str:
    m = _RE_INNER.search(inner or "")
    if m:
        return m.group(2)
    return (inner or "").strip()


def _remove_spans(text: str, spans):
    if not spans:
        return text
    spans = sorted(spans)
    out = []
    last = 0
    for start, end in spans:
        if start < last:
            continue
        out.append(text[last:start])
        last = end
    out.append(text[last:])
    return "".join(out)


def strip_tool_markup(text: str) -> str:
    """Remove any leftover/partial tool tags from user-visible text."""
    if not text:
        return ""
    text = re.sub(
        r"</?(?:web_search|learn_web|scrape|query|url|tool)\b[^>]*>",
        "",
        text,
        flags=re.I,
    )
    return text.strip()


def format_tool_results(results) -> str:
    """Format [(ToolCall, output_text)] into a message for the next LLM turn."""
    blocks = ["TOOL RESULTS (from the host; use these to answer, do not invent more)"]
    for call, output in results:
        if call.name == "web_search":
            blocks.append(f"<web_search query=\"{call.query}\">\n{output}\n</web_search>")
        else:
            blocks.append(f"<{call.name} url=\"{call.url}\">\n{output}\n</{call.name}>")
    return "\n".join(blocks)