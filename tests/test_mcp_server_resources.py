"""Tests for the MCP server resources/prompts and browser session gating."""

import pytest

from kairos import mcp_server, browser


def test_mcp_resources_and_prompts(monkeypatch):
    monkeypatch.setattr(mcp_server, "_server_cfg",
                        lambda: {"expose_resources": True, "expose_prompts": True})
    init = mcp_server._handle("initialize", {})
    assert "tools" in init["capabilities"]
    assert "resources" in init["capabilities"]
    assert "prompts" in init["capabilities"]

    res = mcp_server._handle("resources/list", {})["resources"]
    assert any(r["uri"].startswith("kairos://") for r in res)

    prompts = mcp_server._handle("prompts/list", {})["prompts"]
    names = [p["name"] for p in prompts]
    assert "make_plan" in names and "research_topic" in names

    got = mcp_server._handle("prompts/get",
                             {"name": "make_plan", "arguments": {"goal": "goalX"}})
    assert "goalX" in got["messages"][0]["content"]["text"]


def test_mcp_can_disable_resources(monkeypatch):
    monkeypatch.setattr(mcp_server, "_server_cfg",
                        lambda: {"expose_resources": False, "expose_prompts": False})
    assert mcp_server._handle("resources/list", {})["resources"] == []
    assert mcp_server._handle("prompts/list", {})["prompts"] == []


def test_browser_session_disabled(monkeypatch):
    monkeypatch.setattr(browser, "available", lambda: True)
    monkeypatch.setattr(browser, "_bcfg", lambda: {"enabled": False})
    assert browser.session_enabled() is False
    with pytest.raises(PermissionError):
        browser.session_open("http://example.com")


def test_browser_js_disabled(monkeypatch):
    monkeypatch.setattr(browser, "available", lambda: True)
    monkeypatch.setattr(browser, "_bcfg",
                        lambda: {"enabled": True, "allow_js_eval": False})
    assert browser.session_enabled() is True
    with pytest.raises(PermissionError):
        browser.session_eval_js("1+1")
