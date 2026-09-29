"""GitHub connector (read-focused) via the REST API."""

import logging

import httpx

from kairos import config

logger = logging.getLogger(__name__)

API = "https://api.github.com"


def _conf():
    return (config.load_config().get("connectors", {}) or {}).get("github", {}) or {}


def _token():
    return config._keyring_get("github_token") or _conf().get("token")


def enabled() -> bool:
    return bool(_conf().get("enabled")) and bool(_token())


def _headers():
    tok = _token()
    if not tok:
        raise PermissionError("GitHub token not configured.")
    return {"Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "kairos-connector"}


def _get(path, params=None):
    if not enabled():
        raise PermissionError("GitHub connector is disabled.")
    r = httpx.get(f"{API}{path}", headers=_headers(), params=params, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub {r.status_code}: {r.text[:200]}")
    return r.json()


def search_repos(query: str, limit: int = 10) -> str:
    data = _get("/search/repositories", {"q": query, "per_page": max(1, min(limit, 20))})
    lines = []
    for it in data.get("items", [])[:limit]:
        lines.append(f"- {it.get('full_name')} ⭐{it.get('stargazers_count')}: "
                     f"{(it.get('description') or '')[:120]}")
    return "\n".join(lines) or "(no results)"


def list_issues(repo: str, state: str = "open", limit: int = 10) -> str:
    data = _get(f"/repos/{repo}/issues", {"state": state, "per_page": max(1, min(limit, 30))})
    lines = []
    for it in data[:limit]:
        if "pull_request" in it:
            continue
        lines.append(f"#{it.get('number')} [{it.get('state')}] {it.get('title')}")
    return "\n".join(lines) or "(no issues)"


def get_issue(repo: str, number: int) -> str:
    it = _get(f"/repos/{repo}/issues/{number}")
    return (f"#{it.get('number')} {it.get('title')} [{it.get('state')}]\n"
            f"by {it.get('user', {}).get('login')}\n\n{(it.get('body') or '')[:3000]}")