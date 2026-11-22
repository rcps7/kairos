"""Tests for browser session action dispatch (with a fake Playwright page)."""

import json

import pytest

from kairos import browser


class _Locator:
    def __init__(self):
        self.clicked = False
        self.filled = None
        self.typed = None

    def click(self, **_k):
        self.clicked = True

    def fill(self, v, **_k):
        self.filled = v

    def press_sequentially(self, t, delay=0):
        self.typed = t

    def count(self):
        return 0


class _Mouse:
    def __init__(self):
        self.clicks = []
        self.moves = []
        self.wheel_calls = []

    def click(self, x, y):
        self.clicks.append((x, y))

    def move(self, *a, **k):
        self.moves.append(a)

    def down(self):
        pass

    def up(self):
        pass

    def wheel(self, dx, dy):
        self.wheel_calls.append((dx, dy))


class _Keyboard:
    def __init__(self):
        self.presses = []

    def press(self, k):
        self.presses.append(k)


class _Context:
    pages = []


class _Page:
    def __init__(self):
        self.url = "http://example.test"
        self._title = "Test"
        self.calls = []
        self.mouse = _Mouse()
        self.keyboard = _Keyboard()
        self.context = _Context()
        self._loc = _Locator()

    def goto(self, url, **_k):
        self.url = url

    def click(self, selector, **_k):
        self.calls.append(("click", selector))

    def fill(self, selector, value, **_k):
        self.calls.append(("fill", selector, value))

    def inner_text(self, selector):
        return "hello body"

    def title(self):
        return self._title

    def evaluate(self, script, arg=None):
        s = script or ""
        if "Object.entries(fields)" in s:
            return {"filled": list((arg or {}).keys()), "missed": []}
        if "contenteditable" in s and "getBoundingClientRect" in s:
            return [{"name": "email", "type": "email"}]
        if "turnstile" in s and "recaptcha" in s:
            return ["recaptcha"]
        if "g-recaptcha-response" in s:
            return True
        if "buttons:" in s:
            return {"buttons": [], "headings": [], "forms": 1}
        return None

    def get_by_text(self, text, exact=False):
        return self._loc

    def locator(self, sel):
        return self._loc

    def query_selector(self, sel):
        return None

    def wait_for_selector(self, *a, **k):
        return None

    def wait_for_timeout(self, ms):
        return None

    def screenshot(self, path=None, full_page=False):
        if path:
            with open(path, "wb") as f:
                f.write(b"png")

    def select_option(self, sel, val):
        self.calls.append(("select", sel, val))

    def check(self, sel):
        self.calls.append(("check", sel))

    def uncheck(self, sel):
        self.calls.append(("uncheck", sel))

    def hover(self, sel):
        self.calls.append(("hover", sel))

    def set_input_files(self, sel, path):
        self.calls.append(("upload", sel, path))

    def go_back(self):
        pass

    def go_forward(self):
        pass

    def reload(self):
        pass


def test_fill_and_click(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {"allow_js_eval": False})
    p = _Page()
    browser._dispatch(p, "fill", selector="#email", text="a@b.com")
    assert ("fill", "#email", "a@b.com") in p.calls
    browser._dispatch(p, "click", selector="#go")
    assert ("click", "#go") in p.calls


def test_mouse_and_drag(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {})
    p = _Page()
    browser._dispatch(p, "mouse_click", x=10, y=20)
    assert (10, 20) in p.mouse.clicks
    browser._dispatch(p, "drag", x=1, y=2, x2=30, y2=40)
    assert p.mouse.moves


def test_press(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {})
    p = _Page()
    browser._dispatch(p, "press", text="Enter")
    assert p.keyboard.presses == ["Enter"]


def test_eval_js_gated(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {"allow_js_eval": False})
    with pytest.raises(PermissionError):
        browser._dispatch(_Page(), "eval_js", script="1+1")


def test_upload_gated(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {"allow_uploads": False})
    with pytest.raises(PermissionError):
        browser._dispatch(_Page(), "upload", selector="input", text="f")


def test_list_inputs(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {})
    out = json.loads(browser._dispatch(_Page(), "list_inputs"))
    assert isinstance(out, list) and out[0]["name"] == "email"


def test_fill_form(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {})
    out = json.loads(browser._dispatch(_Page(), "fill_form",
                                       fields={"Email": "a@b.com"}))
    assert "Email" in out["filled"]


def test_detect_captcha(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {})
    out = json.loads(browser._dispatch(_Page(), "detect_captcha"))
    assert "recaptcha" in out


def test_outline(monkeypatch):
    monkeypatch.setattr(browser, "_bcfg", lambda: {})
    out = json.loads(browser._dispatch(_Page(), "outline"))
    assert "buttons" in out