"""Notion connector (search) via the REST API."""

import logging

import httpx

from kairos import config

logger = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _conf():
    return (config.load_config().get("connectors", {}) or {}).get("notion", {}) or {}


def _token():
    return config._keyring_get("notion_token") or _conf().get("token")


def enabled() -> bool:
    return bool(_conf().get("enabled")) and bool(_token())


def _headers():
    tok = _token()
    if not tok:
        raise PermissionError("Notion token not configured.")
    return {"Authorization": f"Bearer {tok}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json"}


def search(query: str, limit: int = 10) -> str:
    if not enabled():
        raise PermissionError("Notion connector is disabled.")
    r = httpx.post(f"{API}/search", headers=_headers(),
                   json={"query": query, "page_size": max(1, min(limit, 25))}, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Notion {r.status_code}: {r.text[:200]}")
    data = r.json()
    lines = []
    for it in data.get("results", [])[:limit]:
        title = "(untitled)"
        props = it.get("properties") or {}
        for v in props.values():
            if v.get("type") == "title" and v.get("title"):
                title = "".join(t.get("plain_text", "") for t in v["title"]) or title
                break
        lines.append(f"- [{it.get('object')}] {title}  id={it.get('id')}")
    return "\n".join(lines) or "(no results)"