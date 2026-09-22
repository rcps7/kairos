"""Extract entities and relationships from text for the knowledge graph.

The heavy lifting is delegated to the active LLM (with the character persona
disabled, since this is an internal structured task). A cheap heuristic skips
trivial turns so most messages cost no extra LLM call.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

_GREETINGS = {
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "yes", "no",
    "cool", "nice", "great", "sure", "got it", "good morning", "good night",
}

EXTRACTION_PROMPT = (
    "Extract durable, reusable knowledge from the text below and return it as "
    "STRICT JSON only (no prose, no code fences).\n\n"
    "JSON schema:\n"
    '{"entities":[{"name":"...","kind":"Person|Project|Device|Concept|Organization|'
    'Location|Event|Preference|Task|Tool|other","summary":"one sentence","aliases":["..."]}],\n'
    ' "relations":[{"subject":"<entity name>","predicate":"<lowercase_snake_case verb phrase>",'
    '"object":"<entity name>","evidence":"short quote or reason"}]}\n\n'
    "Rules:\n"
    "- Capture only durable facts, preferences, projects, tools, and decisions "
    "(ignore small talk, questions, and transient phrasing).\n"
    "- Reuse the exact entity names when they appear in relations.\n"
    "- Use generic `kind` values; invent a new one only if none fit.\n"
    "- At most 12 entities and 20 relations.\n"
    "- If there is nothing worth storing, return {\"entities\":[],\"relations\":[]}.\n\n"
    "TEXT:\n<<<TEXT>>>"
)


def should_extract(text: str) -> bool:
    """Cheap heuristic: skip greetings and very short/empty messages."""
    t = (text or "").strip()
    if len(t) < 40:
        return False
    low = t.lower().strip(" !.?,;:")
    if low in _GREETINGS:
        return False
    # Require at least a few real words.
    words = [w for w in re.split(r"\s+", low) if len(w) > 2]
    return len(words) >= 6


def _parse_json(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except Exception:
        return None


def normalize(data: dict) -> dict:
    entities, relations = [], []
    for e in (data or {}).get("entities", []) or []:
        name = str(e.get("name", "")).strip()
        if not name:
            continue
        entities.append({
            "name": name,
            "kind": str(e.get("kind", "Concept") or "Concept").strip(),
            "summary": str(e.get("summary", "") or "").strip(),
            "aliases": [str(a) for a in (e.get("aliases") or []) if str(a).strip()],
        })
    for r in (data or {}).get("relations", []) or []:
        s = str(r.get("subject", "")).strip()
        o = str(r.get("object", "")).strip()
        p = str(r.get("predicate", "") or "related_to").strip()
        if s and o:
            relations.append({"subject": s, "predicate": p, "object": o,
                              "evidence": str(r.get("evidence", "") or "").strip()})
    return {"entities": entities, "relations": relations}


def extract(engine, text: str, source: str = "chat", kind: str = "chat") -> dict:
    """Ask the LLM to extract knowledge. Returns a proposal dict."""
    prompt = EXTRACTION_PROMPT.replace("<<<TEXT>>>", text[:6000])
    raw = engine.ask_llm(prompt, use_character=False)
    data = normalize(_parse_json(raw) or {})
    data["memory"] = {"text": text[:4000], "kind": kind, "source": source,
                      "character": engine.active_character}
    return data