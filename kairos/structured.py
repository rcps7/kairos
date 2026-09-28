"""Structured output helper: get validated JSON from the model with retries."""

import json
import logging
import re

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"[\{\[].*[\}\]]", re.S)


def extract_json(text: str):
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    m = _JSON_BLOCK.search(t)
    if m:
        t = m.group(0)
    for candidate in (t,):
        try:
            return json.loads(candidate)
        except Exception:
            continue
    try:
        return json.loads(t, strict=False)
    except Exception:
        return None


def generate_json(engine, prompt: str, model, retries: int = 2, system: str = None):
    """Ask the model for JSON and validate it against a pydantic model (or dict callable).

    Raises ValueError if no valid JSON is produced after retries.
    """
    system = system or ("You are a precise assistant. Reply with ONLY valid JSON "
                        "matching the requested schema; no prose or code fences.")
    last_err = "no JSON found"
    instruction = prompt
    for _ in range(retries + 1):
        raw = engine.ask_llm(instruction, system_prompt=system, use_character=False)
        data = extract_json(raw)
        if data is not None:
            try:
                if hasattr(model, "model_validate"):
                    return model.model_validate(data)
                return model(**data) if isinstance(data, dict) else model(data)
            except Exception as e:
                last_err = str(e)[:300]
        else:
            last_err = "response was not valid JSON"
        instruction = (prompt + f"\n\nYour previous reply was invalid ({last_err}). "
                       "Return ONLY corrected JSON.")
    raise ValueError(f"Could not obtain valid JSON after retries: {last_err}")