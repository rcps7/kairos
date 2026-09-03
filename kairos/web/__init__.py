import logging

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Rotating, realistic browser headers to pass basic bot filters.
BROWSER_HEADER_VARIANTS = [
    {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.8",
        "Referer": "https://www.bing.com/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://duckduckgo.com/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    },
]


class WebSearcher:
    """Search the web using DuckDuckGo via the ddgs library (no API key)."""

    def __init__(self):
        self._ddgs = None

    def _get_ddgs(self):
        if self._ddgs is None:
            from ddgs import DDGS
            self._ddgs = DDGS()
        return self._ddgs

    def search(self, query: str, max_results: int = 10) -> list:
        ddgs = self._get_ddgs()
        raw = ddgs.text(query, max_results=max_results)
        results = []
        for item in raw:
            title = item.get("title") or ""
            href = item.get("href") or item.get("url") or ""
            desc = item.get("body") or item.get("description") or ""
            if not title and not href:
                continue
            results.append({"title": title, "url": href, "description": desc})
            if len(results) >= max_results:
                break
        return results

    def close(self):
        self._ddgs = None


class WebScraper:
    """Fetch a page and extract clean text, with bot-filter mitigation."""

    def __init__(self):
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch(self, url: str) -> dict:
        """GET a page, retrying with different browser headers on 403."""
        last_status = None
        for headers in BROWSER_HEADER_VARIANTS:
            resp = self.client.get(url, headers=headers)
            last_status = resp.status_code
            if resp.status_code == 403:
                # Bot filter: try the next header variant before giving up.
                continue
            resp.raise_for_status()
            resp.encoding = resp.encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript", "iframe", "header", "footer", "nav"]):
                tag.decompose()
            title = soup.title.get_text(strip=True) if soup.title else url
            text = soup.get_text(separator="\n", strip=True)
            return {"title": title, "text": text, "html": resp.text}

        raise RuntimeError(
            f"Site returned {last_status} Forbidden (blocked). "
            "Try another URL or enable Playwright rendering."
        )

    def close(self):
        self.client.close()


def summarize_with_llm(llm, text: str, max_chars: int = 6000) -> str:
    """Summarize text into clean, easy-to-learn bullet points using the LLM."""
    excerpt = text[:max_chars]
    prompt = (
        "Summarize the following content into clean, easy-to-learn bullet points. "
        "Use short, clear bullets (one key idea per bullet).\n\n"
        f"CONTENT:\n{excerpt}"
    )
    return llm.generate(prompt)
