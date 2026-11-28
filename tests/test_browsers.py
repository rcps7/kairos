"""Tests for browser discovery/selection."""

from pathlib import Path

from kairos import browsers


def test_resolve_bundled():
    c = browsers.resolve_choice("playwright-chromium")
    assert c and c["family"] == "chromium"
    c = browsers.resolve_choice("playwright-firefox")
    assert c and c["family"] == "firefox"


def test_resolve_known_id():
    c = browsers.resolve_choice("msedge")
    assert c and c["id"] == "msedge"
    c = browsers.resolve_choice("chrome")
    assert c and c["id"] == "chrome"


def test_resolve_path(tmp_path):
    p = tmp_path / "chrome.exe"
    p.write_text("x", encoding="utf-8")
    c = browsers.resolve_choice(str(p))
    assert c and c["path"] == str(p.resolve())


def test_resolve_unknown():
    assert browsers.resolve_choice("does-not-exist") is None
    assert browsers.resolve_choice("") is None


def test_list_choices_includes_bundled(monkeypatch):
    monkeypatch.setattr(browsers, "find_installed_browsers", lambda: [])
    monkeypatch.setattr(browsers, "running_browser_ids", lambda: set())
    import kairos.browser as browser_mod
    monkeypatch.setattr(browser_mod, "available", lambda: True)
    ids = [c["id"] for c in browsers.list_choices()]
    assert "playwright-chromium" in ids


def test_running_ids_parsing(monkeypatch):
    import sys
    import pytest
    if sys.platform != "win32":
        pytest.skip("tasklist CSV parsing is Windows-only")
    class _R:
        stdout = ('"msedge.exe","1","Console","1","1 K"\n'
                  '"chrome.exe","2","Console","1","1 K"\n'
                  '"notepad.exe","3","Console","1","1 K"\n')

    monkeypatch.setattr(browsers.subprocess, "run", lambda *a, **k: _R())
    ids = browsers.running_browser_ids()
    assert "msedge" in ids and "chrome" in ids
    assert "notepad" not in ids


def test_choices_flags_running(monkeypatch):
    monkeypatch.setattr(browsers, "find_installed_browsers",
                        lambda: [{"id": "chrome", "name": "Google Chrome",
                                  "path": "/x/chrome.exe", "family": "chromium",
                                  "channel": "chrome"}])
    monkeypatch.setattr(browsers, "running_browser_ids", lambda: {"chrome"})
    import kairos.browser as browser_mod
    monkeypatch.setattr(browser_mod, "available", lambda: False)
    choices = browsers.list_choices()
    chrome = next(c for c in choices if c["id"] == "chrome")
    assert chrome["running"] is True