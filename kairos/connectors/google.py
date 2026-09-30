"""Google Drive connector (token-based) via the REST API.

Uses a stored OAuth access token from the OS keyring (or config). This avoids
bundling an OAuth client; obtain a token with the Drive scope and store it as
the keyring entry ``google_token``.
"""

import logging

import httpx

from kairos import config

logger = logging.getLogger(__name__)

API = "https://www.googleapis.com/drive/v3"


def _conf():
    return (config.load_config().get("connectors", {}) or {}).get("google", {}) or {}


def _token():
    return config._keyring_get("google_token") or _conf().get("token")


def enabled() -> bool:
    return bool(_conf().get("enabled")) and bool(_token())


def search_files(query: str, limit: int = 10) -> str:
    if not enabled():
        raise PermissionError("Google connector is disabled or no token is set.")
    q = f"name contains '{query.replace(chr(39), chr(92) + chr(39))}' and trashed = false"
    r = httpx.get(f"{API}/files",
                  headers={"Authorization": f"Bearer {_token()}"},
                  params={"q": q, "pageSize": max(1, min(limit, 25)),
                          "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"},
                  timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Google {r.status_code}: {r.text[:200]}")
    files = r.json().get("files", [])
    lines = [f"- {f.get('name')} ({f.get('mimeType')}) id={f.get('id')} "
             f"{f.get('webViewLink', '')}" for f in files[:limit]]
    return "\n".join(lines) or "(no results)"