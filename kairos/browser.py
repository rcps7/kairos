"""Optional browser automation via Playwright (headless Chromium).

Requires the ``playwright`` package and browser binaries. If the browser is not
installed, callers should run:  python -m playwright install chromium
"""

import importlib.util
import logging
import uuid
from pathlib import Path

from kairos import config

logger = logging.getLogger(__name__)


def available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _browser_context():
    from playwright.sync_api import sync_playwright
    return sync_playwright()


def fetch_text(url: str, timeout: float = 30.0, max_chars: int = 20000) -> str:
    if not available():
        raise RuntimeError("Playwright is not installed (pip install playwright).")
    with _browser_context() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            text = page.inner_text("body")
            return (text or "")[:max_chars]
        finally:
            browser.close()


def screenshot(url: str, timeout: float = 30.0, save_dir: str = None) -> str:
    if not available():
        raise RuntimeError("Playwright is not installed (pip install playwright).")
    out_dir = Path(save_dir) if save_dir else (
        Path(config.load_config().get("storage_root", str(Path.home()))) / "Kairos" / "Media")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"page_{uuid.uuid4().hex}.png"
    with _browser_context() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            page.screenshot(path=str(path), full_page=True)
        finally:
            browser.close()
    return str(path)


def run_actions(url: str, actions, timeout: float = 30.0, save_dir: str = None) -> str:
    """Navigate and perform a list of actions (click/type/wait/extract/screenshot)."""
    if not available():
        raise RuntimeError("Playwright is not installed (pip install playwright).")
    out_dir = Path(save_dir) if save_dir else (
        Path(config.load_config().get("storage_root", str(Path.home()))) / "Kairos" / "Media")
    logs = []
    with _browser_context() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            for a in (actions or []):
                kind = (a.get("type") or "").lower()
                if kind == "click":
                    page.click(a.get("selector", ""))
                    logs.append(f"clicked {a.get('selector','')}")
                elif kind == "type":
                    page.fill(a.get("selector", ""), a.get("text", ""))
                    logs.append(f"typed into {a.get('selector','')}")
                elif kind == "wait":
                    page.wait_for_timeout(int(a.get("ms", 500)))
                elif kind == "text":
                    logs.append(page.inner_text(a.get("selector") or "body")[:4000])
                elif kind == "screenshot":
                    out_dir.mkdir(parents=True, exist_ok=True)
                    shot = out_dir / f"page_{uuid.uuid4().hex}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    logs.append(f"screenshot: {shot}")
            logs.append("TEXT:\n" + (page.inner_text("body") or "")[:8000])
        finally:
            browser.close()
    return "\n".join(logs)