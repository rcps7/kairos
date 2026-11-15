"""Optional browser automation via Playwright (headless Chromium).

Requires the ``playwright`` package and browser binaries. If the browser is not
installed, callers should run:  python -m playwright install chromium

Two modes are available:

* one-shot helpers (:func:`fetch_text`, :func:`screenshot`, :func:`run_actions`)
  that launch a throwaway headless Chromium per call (behaviour unchanged); and
* a **persistent, headed session** (:class:`BrowserSession` and the
  ``session_*`` helpers) that keeps a real browser window open across calls and
  supports JavaScript evaluation and mouse/keyboard control — used to drive
  canvas/SVG editors such as EasyEDA. The session must be enabled in config
  (``browser.enabled``) and JS evaluation additionally requires
  ``browser.allow_js_eval``.
"""

import atexit
import importlib.util
import logging
import os
import queue
import threading
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


# ---------------------------------------------------------------------------
# Persistent, headed session (opt-in) — for canvas/SVG editors like EasyEDA
# ---------------------------------------------------------------------------
def _bcfg() -> dict:
    try:
        return config.load_config().get("browser", {}) or {}
    except Exception:
        return {}


def session_enabled() -> bool:
    return bool(_bcfg().get("enabled"))


def _require_session():
    if not available():
        raise RuntimeError("Browser session requires Playwright "
                           "(pip install playwright; python -m playwright install chromium).")
    if not session_enabled():
        raise PermissionError("Browser session is disabled (browser.enabled).")


def _save_dir() -> Path:
    d = Path(config.load_config().get("storage_root", str(Path.home()))) / "Kairos" / "Media"
    d.mkdir(parents=True, exist_ok=True)
    return d


class BrowserSession:
    """A single long-lived (optionally headed) Playwright Chromium session.

    Sync Playwright objects are bound to the thread that created them, so all
    interaction is marshalled onto one dedicated worker thread via a queue.
    """

    def __init__(self):
        self._q = queue.Queue()
        self._thread = None
        self._ready = threading.Event()
        self._start_error = None
        self._start_lock = threading.Lock()

    # -- worker thread --
    def _run(self):
        try:
            from playwright.sync_api import sync_playwright
            cfg = _bcfg()
            headless = bool(cfg.get("headless", False))
            slow_mo = int(cfg.get("slow_mo", 0) or 0)
            viewport = cfg.get("viewport") or {"width": 1280, "height": 800}
            profile = cfg.get("profile_dir") or str(Path.home() / ".kairos" / "browser_profile")
            with sync_playwright() as p:
                Path(profile).mkdir(parents=True, exist_ok=True)
                context = p.chromium.launch_persistent_context(
                    user_data_dir=profile, headless=headless, slow_mo=slow_mo,
                    viewport=viewport, args=["--start-maximized"])
                page = context.pages[0] if context.pages else context.new_page()
                self._context = context
                self._page = page
                self._ready.set()
                while True:
                    item = self._q.get()
                    if item is None:
                        break
                    fn, box = item
                    try:
                        box["result"] = fn(page)
                    except Exception as e:  # noqa: BLE001
                        box["error"] = e
                    finally:
                        box["event"].set()
                try:
                    context.close()
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            self._start_error = e
            self._ready.set()

    def _ensure(self):
        with self._start_lock:
            if self._thread is None:
                self._ready.clear()
                self._thread = threading.Thread(target=self._run, daemon=True,
                                                name="kairos-browser-session")
                self._thread.start()
        if not self._ready.wait(45):
            raise RuntimeError("Browser session did not start in time.")
        if self._start_error:
            err = self._start_error
            self._thread = None
            self._start_error = None
            raise RuntimeError(f"Browser session failed to start: {err}")

    def call(self, fn, timeout: float = 60.0):
        self._ensure()
        box = {"event": threading.Event()}
        self._q.put((fn, box))
        if not box["event"].wait(timeout):
            raise TimeoutError("Browser session action timed out.")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def stop(self):
        try:
            self._q.put(None)
        except Exception:
            pass


_session = BrowserSession()
atexit.register(_session.stop)


def _goto(page, url, timeout=45.0):
    if url:
        page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")


def session_open(url: str = "") -> str:
    _require_session()

    def act(page):
        _goto(page, url)
        return (page.inner_text("body") or "")[:8000]

    return _session.call(act)


def session_eval_js(script: str, url: str = None) -> str:
    _require_session()
    if not _bcfg().get("allow_js_eval"):
        raise PermissionError("JavaScript evaluation is disabled (browser.allow_js_eval).")

    def act(page):
        _goto(page, url)
        res = page.evaluate(script or "null")
        return str(res)[:8000]

    return _session.call(act)


def session_mouse(action: str, selector: str = "", x=None, y=None,
                  text: str = "", url: str = None) -> str:
    _require_session()

    def act(page):
        _goto(page, url)
        a = (action or "").lower()
        if a in ("click", "selector_click"):
            page.click(selector)
            return f"clicked {selector}"
        if a in ("coord_click", "mouse_click"):
            page.mouse.click(float(x or 0), float(y or 0))
            return f"clicked at ({x},{y})"
        if a in ("move", "mouse_move"):
            page.mouse.move(float(x or 0), float(y or 0))
            return f"moved to ({x},{y})"
        if a in ("drag", "mouse_drag"):
            page.mouse.move(float(x or 0), float(y or 0))
            page.mouse.down()
            page.mouse.move(float(x or 0) + 100, float(y or 0) + 100, steps=10)
            page.mouse.up()
            return f"dragged from ({x},{y})"
        if a in ("type", "fill"):
            page.fill(selector, text or "")
            return f"typed into {selector}"
        if a in ("key", "press"):
            page.keyboard.press(text or "Enter")
            return f"pressed {text or 'Enter'}"
        if a == "screenshot":
            shot = _save_dir() / f"page_{uuid.uuid4().hex}.png"
            page.screenshot(path=str(shot), full_page=True)
            return f"screenshot: {shot}"
        return f"unknown action '{action}'"

    return _session.call(act)


def session_screenshot(url: str = None) -> str:
    return session_mouse("screenshot", url=url)


def session_close() -> str:
    _session.stop()
    return "browser session closed"