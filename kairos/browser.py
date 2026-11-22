"""Browser automation for Kairos (Playwright).

Two modes are available:

* one-shot helpers (:func:`fetch_text`, :func:`screenshot`, :func:`run_actions`)
  that launch a throwaway headless Chromium per call (unchanged behaviour); and
* a **persistent browser session** (:class:`BrowserSession` and the ``session_*``
  helpers) that drives a real browser window across calls. It can either launch
  a selected **installed** browser in a dedicated Kairos profile (Chrome, Edge,
  Brave, Vivaldi, Opera, Firefox) or **attach** to a Chromium instance started
  with ``--remote-debugging-port`` (CDP).

The session supports navigation, filling/typing, clicking, form fill, uploads,
captchas, screenshots and (gated) JavaScript evaluation. It is used by the
Browser Agent dialog and the design/computer-use loop.

Config (``browser``): ``enabled``, ``mode`` (launch/attach/ask), ``selected``,
``executable``, ``channel``, ``attach_url``, ``headless``, ``profile_dir``,
``allow_js_eval``, ``allow_uploads``, ``viewport``, ``slow_mo``.
"""

import atexit
import importlib.util
import json
import logging
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


# ---------------------------------------------------------------------------
# One-shot helpers (unchanged)
# ---------------------------------------------------------------------------
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


def _media_dir() -> Path:
    d = Path(config.load_config().get("storage_root", str(Path.home()))) / "Kairos" / "Media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def screenshot(url: str, timeout: float = 30.0, save_dir: str = None) -> str:
    if not available():
        raise RuntimeError("Playwright is not installed (pip install playwright).")
    out_dir = Path(save_dir) if save_dir else _media_dir()
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
    """Navigate and perform a list of actions (click/type/wait/text/screenshot)."""
    if not available():
        raise RuntimeError("Playwright is not installed (pip install playwright).")
    out_dir = Path(save_dir) if save_dir else _media_dir()
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
                    shot = out_dir / f"page_{uuid.uuid4().hex}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    logs.append(f"screenshot: {shot}")
            logs.append("TEXT:\n" + (page.inner_text("body") or "")[:8000])
        finally:
            browser.close()
    return "\n".join(logs)


# ---------------------------------------------------------------------------
# Persistent browser session
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
                           "(pip install playwright).")
    if not session_enabled():
        raise PermissionError("Browser session is disabled (browser.enabled).")


def _save_dir() -> Path:
    return _media_dir()


def _persist_selection(choice: dict):
    try:
        from kairos.config import load_config, save_config
        cfg = load_config()
        b = cfg.setdefault("browser", {})
        if choice and choice.get("id"):
            b["selected"] = choice["id"]
        save_config(cfg)
    except Exception:
        logger.debug("Could not persist browser selection", exc_info=True)


def _start_options(choice_id=None, mode=None, headless=None) -> dict:
    from kairos import browsers
    cfg = _bcfg()
    req_mode = (mode or cfg.get("mode") or "ask").lower()

    # Prefer attaching to a browser already exposing a CDP endpoint.
    if req_mode in ("attach", "ask", "launch"):
        cdp = browsers.detect_debug_endpoint()
        if cdp and req_mode in ("attach", "ask"):
            return {"mode": "attach", "attach_url": cdp["url"],
                    "family": "chromium", "label": f"Attached: {cdp['label']}",
                    "choice": {"id": "attach", "name": f"Attached browser ({cdp['label']})",
                               "family": "chromium"}}

    cid = choice_id or cfg.get("selected")
    choice = browsers.resolve_choice(cid) if cid else None
    if not choice:
        installed = browsers.find_installed_browsers()
        choice = (next((c for c in installed if c.get("family") == "chromium"), None)
                  or (installed[0] if installed else None))
    if not choice:
        choice = {"id": "playwright-chromium", "name": "Playwright Chromium (bundled)",
                  "path": None, "family": "chromium", "channel": None}
    bid = choice.get("id") or "browser"
    profile = cfg.get("profile_dir") or str(Path.home() / ".kairos" / f"browser_profile_{bid}")
    return {
        "mode": "launch",
        "family": choice.get("family", "chromium"),
        "channel": choice.get("channel") or cfg.get("channel"),
        "executable": cfg.get("executable") or choice.get("path"),
        "profile_dir": profile,
        "headless": bool(cfg.get("headless", False)) if headless is None else bool(headless),
        "slow_mo": int(cfg.get("slow_mo", 0) or 0),
        "viewport": cfg.get("viewport") or {"width": 1280, "height": 800},
        "choice": choice,
    }


class BrowserSession:
    """A single long-lived Playwright session on a dedicated worker thread."""

    def __init__(self):
        self._q = queue.Queue()
        self._thread = None
        self._ready = threading.Event()
        self._start_error = None
        self._start_lock = threading.Lock()
        self._options = {}
        self._info = {}
        self._attached = False

    # -- lifecycle -------------------------------------------------------
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._ready.is_set()
                    and not self._start_error)

    def begin(self, choice_id=None, url=None, mode=None, headless=None) -> dict:
        opts = _start_options(choice_id=choice_id, mode=mode, headless=headless)
        if url:
            opts["url"] = url
        self.stop(wait=True)
        with self._start_lock:
            # Fresh queue so a leftover stop sentinel cannot kill the new thread.
            self._q = queue.Queue()
            self._options = opts
            self._start_error = None
            self._info = {}
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="kairos-browser-session")
            self._thread.start()
        if not self._ready.wait(60):
            raise RuntimeError("Browser session did not start in time.")
        if self._start_error:
            err = self._start_error
            self._start_error = None
            self._thread = None
            raise RuntimeError(f"Browser session failed to start: {err}")
        if opts.get("mode") == "launch":
            _persist_selection(opts.get("choice") or {})
        return dict(self._info)

    def _run(self):
        opts = dict(self._options)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                mode = opts.get("mode", "launch")
                family = opts.get("family", "chromium")
                if mode == "attach":
                    browser = p.chromium.connect_over_cdp(opts["attach_url"])
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    self._attached = True
                    browser_obj = browser
                elif family == "firefox":
                    profile = opts.get("profile_dir") or str(Path.home() / ".kairos" / "browser_profile_firefox")
                    Path(profile).mkdir(parents=True, exist_ok=True)
                    context = p.firefox.launch_persistent_context(
                        user_data_dir=profile, headless=opts.get("headless", False),
                        slow_mo=opts.get("slow_mo", 0))
                    self._attached = False
                    browser_obj = None
                else:
                    profile = opts.get("profile_dir") or str(Path.home() / ".kairos" / "browser_profile")
                    Path(profile).mkdir(parents=True, exist_ok=True)
                    kwargs = {"user_data_dir": profile,
                              "headless": opts.get("headless", False),
                              "slow_mo": opts.get("slow_mo", 0),
                              "viewport": opts.get("viewport") or {"width": 1280, "height": 800},
                              "args": ["--start-maximized"]}
                    # Playwright treats channel and executable as alternatives.
                    if opts.get("executable"):
                        kwargs["executable_path"] = opts["executable"]
                    elif opts.get("channel"):
                        kwargs["channel"] = opts["channel"]
                    context = p.chromium.launch_persistent_context(**kwargs)
                    self._attached = False
                    browser_obj = None

                page = context.pages[0] if getattr(context, "pages", None) else context.new_page()
                if opts.get("url"):
                    try:
                        page.goto(opts["url"], timeout=45000,
                                  wait_until="domcontentloaded")
                    except Exception:
                        pass
                self._context = context
                self._page = page
                self._browser = browser_obj
                choice = opts.get("choice") or {}
                self._info = {
                    "mode": opts.get("mode", "launch"),
                    "browser": choice.get("name") or choice.get("id") or "Chromium",
                    "family": opts.get("family", "chromium"),
                    "url": _safe(page.url),
                    "title": _safe_title(page),
                }
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
                self._info["url"] = _safe(page.url)
                self._info["title"] = _safe_title(page)
                if not self._attached:
                    try:
                        context.close()
                    except Exception:
                        pass
        except Exception as e:  # noqa: BLE001
            self._start_error = e
            self._ready.set()

    def call(self, fn, timeout: float = 90.0):
        if not self.is_running():
            self.begin()
        box = {"event": threading.Event()}
        self._q.put((fn, box))
        if not box["event"].wait(timeout):
            raise TimeoutError("Browser session action timed out.")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def info(self) -> dict:
        return dict(self._info)

    def stop(self, wait: bool = False):
        t = self._thread
        try:
            self._q.put(None)
        except Exception:
            pass
        if wait and t is not None:
            try:
                t.join(timeout=10)
            except Exception:
                pass
        self._thread = None
        self._ready.clear()
        self._info = {}
        self._attached = False


_session = BrowserSession()
atexit.register(_session.stop)


def _safe(v):
    try:
        return str(v)
    except Exception:
        return ""


def _safe_title(page):
    try:
        return page.title()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# JavaScript helpers
# ---------------------------------------------------------------------------
_JS_LIST_INPUTS = """
() => Array.from(document.querySelectorAll('input,textarea,select,[contenteditable="true"]'))
  .filter(e => !e.disabled && e.type !== 'hidden')
  .map(e => {
    const r = e.getBoundingClientRect();
    const lab = (e.labels && e.labels[0]) ? e.labels[0].innerText : '';
    return {tag: e.tagName.toLowerCase(), type: e.type || '',
      name: e.name || '', id: e.id || '', placeholder: e.placeholder || '',
      label: (lab || '').trim(), aria: e.getAttribute('aria-label') || '',
      value: (e.type === 'password' ? '' : (e.value || '')).slice(0, 200),
      rect: {x: Math.round(r.x), y: Math.round(r.y),
             w: Math.round(r.width), h: Math.round(r.height)}};
  });
"""

_JS_FILL_FORM = """
(fields) => {
  const norm = s => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
  const els = [...document.querySelectorAll('input,textarea,select,[contenteditable="true"]')];
  const filled = [], missed = [];
  for (const [key, val] of Object.entries(fields)) {
    const k = norm(key);
    const el = els.find(e => {
      const lab = (e.labels && e.labels[0]) ? e.labels[0].innerText : '';
      return [e.name, e.id, e.placeholder, e.getAttribute('aria-label'), lab]
        .some(s => { const n = norm(s); return n && (n === k || n.includes(k) || k.includes(n)); });
    });
    if (!el) { missed.push(key); continue; }
    try {
      if (el.isContentEditable) el.innerText = String(val);
      else el.value = String(val);
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      filled.push(key);
    } catch (err) { missed.push(key); }
  }
  return {filled, missed};
}
"""

_JS_DETECT_CAPTCHA = """
() => {
  const sets = {
    recaptcha: ['iframe[src*="recaptcha"]', '.g-recaptcha', '#g-recaptcha'],
    hcaptcha: ['iframe[src*="hcaptcha"]', '.h-captcha'],
    turnstile: ['iframe[src*="challenges.cloudflare.com"]', '.cf-turnstile'],
    arkose: ['iframe[src*="arkoselabs"]', 'iframe[src*="funcaptcha"]']
  };
  const found = [];
  for (const [k, list] of Object.entries(sets)) {
    if (list.some(s => document.querySelector(s))) found.push(k);
  }
  return found;
}
"""

_JS_CAPTCHA_SOLVED = """
() => {
  const names = ['g-recaptcha-response', 'h-captcha-response', 'cf-turnstile-response'];
  return names.some(n => {
    const e = document.querySelector('textarea[name="' + n + '"],input[name="' + n + '"]');
    return !!(e && e.value && e.value.length > 10);
  });
}
"""

_JS_OUTLINE = """
() => {
  const pick = (els) => [...els].slice(0, 90).map(e => {
    const r = e.getBoundingClientRect();
    return {tag: e.tagName.toLowerCase(),
      text: (e.innerText || e.value || '').trim().slice(0, 80),
      id: e.id || '', name: e.name || '', type: e.type || '',
      rect: {x: Math.round(r.x), y: Math.round(r.y),
             w: Math.round(r.width), h: Math.round(r.height)}};
  }).filter(x => x.text || x.id || x.name);
  return {
    buttons: pick(document.querySelectorAll('button,[role=button],input[type=submit],input[type=button],a')),
    headings: [...document.querySelectorAll('h1,h2,h3')].slice(0, 20)
                .map(h => (h.innerText || '').trim().slice(0, 120)),
    forms: document.querySelectorAll('form').length
  };
}
"""


def _click_text(page, text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("click_text needs text")
    try:
        if page.get_by_text(text, exact=False).count():
            page.get_by_text(text, exact=False).first.click(timeout=15000)
            return f"clicked text '{text}'"
    except Exception:
        pass
    # JS fallback
    js = """(t) => {
      const norm = s => (s||'').toLowerCase().trim();
      const els = [...document.querySelectorAll('button,a,[role=button],input[type=submit],input[type=button]')];
      const el = els.find(e => norm(e.innerText || e.value).includes(norm(t)));
      if (el) { el.click(); return true; } return false;
    }"""
    if page.evaluate(js, text):
        return f"clicked text '{text}'"
    raise RuntimeError(f"No clickable element with text '{text}'")


def _dispatch(page, action: str, **p) -> str:
    a = (action or "").lower()
    url = p.get("url")
    if url and a not in ("goto", "open", "navigate", "back", "forward", "reload",
                         "url", "current_url", "title", "tabs"):
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
        except Exception:
            pass

    if a in ("goto", "open", "navigate"):
        page.goto(url or p.get("target") or "about:blank", timeout=45000,
                  wait_until="domcontentloaded")
        return f"navigated to {_safe(page.url)}"
    if a == "back":
        page.go_back()
        return f"back -> {_safe(page.url)}"
    if a == "forward":
        page.go_forward()
        return f"forward -> {_safe(page.url)}"
    if a == "reload":
        page.reload()
        return f"reloaded {_safe(page.url)}"
    if a in ("url", "current_url"):
        return _safe(page.url)
    if a == "title":
        return _safe_title(page)
    if a == "text":
        return (page.inner_text(p.get("selector") or "body") or "")[:12000]
    if a in ("click", "selector_click"):
        page.click(p.get("selector", ""), timeout=15000)
        return f"clicked {p.get('selector','')}"
    if a == "click_text":
        return _click_text(page, p.get("text") or p.get("selector") or "")
    if a in ("fill", "set"):
        sel = p.get("selector") or p.get("label")
        page.fill(sel, p.get("text") or p.get("value") or "", timeout=15000)
        return f"filled {sel}"
    if a == "type":
        sel = p.get("selector") or p.get("label")
        loc = page.locator(sel)
        loc.click()
        loc.fill("")
        loc.press_sequentially(p.get("text") or p.get("value") or "",
                               delay=int(p.get("delay", 30) or 30))
        return f"typed into {sel}"
    if a in ("press", "key"):
        page.keyboard.press(p.get("text") or p.get("key") or "Enter")
        return f"pressed {p.get('text') or p.get('key') or 'Enter'}"
    if a == "select":
        page.select_option(p.get("selector", ""), p.get("text") or p.get("value"))
        return f"selected option in {p.get('selector','')}"
    if a in ("check", "uncheck"):
        if a == "check":
            page.check(p.get("selector", ""))
        else:
            page.uncheck(p.get("selector", ""))
        return f"{a}ed {p.get('selector','')}"
    if a == "upload":
        if not _bcfg().get("allow_uploads", False):
            raise PermissionError("Uploads are disabled (browser.allow_uploads).")
        page.set_input_files(p.get("selector", ""), p.get("text") or p.get("path"))
        return f"uploaded to {p.get('selector','')}"
    if a == "hover":
        page.hover(p.get("selector", ""))
        return f"hovered {p.get('selector','')}"
    if a == "scroll":
        page.mouse.wheel(int(p.get("x", 0) or 0), int(p.get("y", 600) or 600))
        return "scrolled"
    if a in ("mouse_click", "coord_click"):
        page.mouse.click(float(p.get("x", 0) or 0), float(p.get("y", 0) or 0))
        return f"clicked at ({p.get('x')},{p.get('y')})"
    if a in ("mouse_move", "move"):
        page.mouse.move(float(p.get("x", 0) or 0), float(p.get("y", 0) or 0))
        return f"moved to ({p.get('x')},{p.get('y')})"
    if a == "drag":
        x1 = float(p.get("x", 0) or 0); y1 = float(p.get("y", 0) or 0)
        x2 = float(p.get("x2", x1 + 100) or (x1 + 100)); y2 = float(p.get("y2", y1 + 100) or (y1 + 100))
        page.mouse.move(x1, y1)
        page.mouse.down()
        page.mouse.move(x2, y2, steps=int(p.get("steps", 12) or 12))
        page.mouse.up()
        return f"dragged ({x1},{y1}) -> ({x2},{y2})"
    if a in ("wait", "sleep"):
        page.wait_for_timeout(int(p.get("ms", 1000) or 1000))
        return "waited"
    if a == "wait_for":
        page.wait_for_selector(p.get("selector", ""), timeout=int(p.get("ms", 30000) or 30000))
        return f"found {p.get('selector','')}"
    if a == "exists":
        return str(bool(page.query_selector(p.get("selector", ""))))
    if a == "screenshot":
        shot = _save_dir() / f"page_{uuid.uuid4().hex}.png"
        page.screenshot(path=str(shot), full_page=bool(p.get("full", False)))
        return f"screenshot: {shot}"
    if a in ("js", "eval_js", "evaluate"):
        if not _bcfg().get("allow_js_eval", False):
            raise PermissionError("JavaScript evaluation is disabled (browser.allow_js_eval).")
        res = page.evaluate(p.get("script") or "null")
        return _safe(res)[:12000]
    if a == "list_inputs":
        return json.dumps(page.evaluate(_JS_LIST_INPUTS), ensure_ascii=False)
    if a == "fill_form":
        fields = p.get("fields") or {}
        return json.dumps(page.evaluate(_JS_FILL_FORM, fields), ensure_ascii=False)
    if a == "detect_captcha":
        return json.dumps(page.evaluate(_JS_DETECT_CAPTCHA), ensure_ascii=False)
    if a == "outline":
        return json.dumps(page.evaluate(_JS_OUTLINE), ensure_ascii=False)
    if a == "captcha_solved":
        return str(bool(page.evaluate(_JS_CAPTCHA_SOLVED)))
    if a == "wait_captcha":
        import time as _t
        deadline = _t.time() + float(p.get("ms", 300000) or 300000) / 1000.0
        while _t.time() < deadline:
            if page.evaluate(_JS_CAPTCHA_SOLVED):
                return "captcha solved"
            page.wait_for_timeout(1500)
        return "captcha not solved (timeout)"
    if a == "tabs":
        try:
            return "\n".join(_safe(pg.url) for pg in page.context.pages)
        except Exception:
            return _safe(page.url)
    return f"unknown action '{action}'"


# ---------------------------------------------------------------------------
# Module-level session API
# ---------------------------------------------------------------------------
def session_running() -> bool:
    return _session.is_running()


def session_start(choice_id: str = None, url: str = None, mode: str = None,
                  headless: bool = None) -> dict:
    _require_session()
    return _session.begin(choice_id=choice_id, url=url, mode=mode, headless=headless)


def session_info() -> dict:
    if not _session.is_running():
        return {"running": False}
    info = _session.info()
    info["running"] = True
    try:
        info["url"] = _session.call(lambda page: _safe(page.url), timeout=15)
        info["title"] = _session.call(lambda page: _safe_title(page), timeout=15)
    except Exception:
        pass
    return info


def session_do(action: str, **params) -> str:
    _require_session()
    if (action or "").lower() in ("js", "eval_js", "evaluate") \
            and not _bcfg().get("allow_js_eval", False):
        raise PermissionError("JavaScript evaluation is disabled (browser.allow_js_eval).")
    return _session.call(lambda page: _dispatch(page, action, **params))


def session_open(url: str = "") -> str:
    _require_session()
    if not _session.is_running():
        _session.begin(url=url)
    return _session.call(lambda page: _dispatch(page, "goto", url=url))


def session_eval_js(script: str, url: str = None) -> str:
    _require_session()
    if not _bcfg().get("allow_js_eval", False):
        raise PermissionError("JavaScript evaluation is disabled (browser.allow_js_eval).")
    return session_do("eval_js", script=script, url=url)


def session_mouse(action: str, selector: str = "", x=None, y=None,
                  text: str = "", url: str = None) -> str:
    a = (action or "").lower()
    if a in ("click", "selector_click"):
        return session_do("click", selector=selector, url=url)
    if a in ("coord_click", "mouse_click"):
        return session_do("mouse_click", x=x, y=y, url=url)
    if a in ("move", "mouse_move"):
        return session_do("mouse_move", x=x, y=y, url=url)
    if a in ("drag", "mouse_drag"):
        return session_do("drag", x=x, y=y, x2=(float(x or 0) + 100),
                          y2=(float(y or 0) + 100), url=url)
    if a in ("type", "fill"):
        return session_do("fill", selector=selector, text=text, url=url)
    if a in ("key", "press"):
        return session_do("press", text=text or "Enter", url=url)
    if a == "screenshot":
        return session_do("screenshot", url=url)
    return session_do(action, selector=selector, x=x, y=y, text=text, url=url)


def session_fill(selector: str = "", value: str = "", url: str = None) -> str:
    return session_do("fill", selector=selector, text=value, url=url)


def session_fill_form(fields: dict, url: str = None) -> str:
    return session_do("fill_form", fields=fields, url=url)


def session_click(selector: str = "", url: str = None) -> str:
    return session_do("click", selector=selector, url=url)


def session_click_text(text: str, url: str = None) -> str:
    return session_do("click_text", text=text, url=url)


def session_screenshot(url: str = None, full: bool = False) -> str:
    return session_do("screenshot", url=url, full=full)


def session_list_inputs() -> list:
    raw = session_do("list_inputs")
    try:
        return json.loads(raw)
    except Exception:
        return []


def session_outline() -> dict:
    raw = session_do("outline")
    try:
        return json.loads(raw)
    except Exception:
        return {}


def session_detect_captcha() -> list:
    raw = session_do("detect_captcha")
    try:
        return json.loads(raw)
    except Exception:
        return []


def session_wait_captcha(timeout_ms: int = 300000) -> str:
    return session_do("wait_captcha", ms=timeout_ms)


def session_close() -> str:
    _session.stop(wait=True)
    return "browser session closed"