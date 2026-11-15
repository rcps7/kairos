"""Tests for Plan/Execute modes: the advanced tool protocol and capability gates."""

import pytest

from kairos import tools, toolkit, planner


def test_generic_tool_parse():
    text = 'Sure.\n<tool name="git_status">{}</tool>'
    clean, calls = tools.parse_tool_calls(text)
    assert calls and calls[0].name == "git_status"
    assert "tool name" not in clean


def test_generic_tool_args():
    text = '<tool name="git_commit">{"message": "hi"}</tool>'
    _, calls = tools.parse_tool_calls(text)
    assert calls[0].name == "git_commit"
    assert calls[0].args.get("message") == "hi"


def test_web_forms_still_parse():
    _, calls = tools.parse_tool_calls("<web_search><query>cats</query></web_search>")
    assert calls and calls[0].name == "web_search" and calls[0].query == "cats"


def test_capability_map():
    assert toolkit.capability_for("git_commit") == "git_ops"
    assert toolkit.capability_for("draw_diagram") == "artifacts"
    assert toolkit.capability_for("browser_js") == "browser_control"
    assert toolkit.capability_for("web_search") == "web_search"


def test_capability_gate_blocks_tool():
    class _E:
        def can(self, cap):
            return cap != "git_ops"

    with pytest.raises(PermissionError):
        toolkit.execute(_E(), "git_status", {})


def test_planner_prompt():
    p = planner.plan_prompt("build a thing", "some context")
    assert "build a thing" in p and "JSON" in p
    assert "steps" in planner.PLANNER_SYSTEM.lower()


def test_tool_schemas_present():
    names = [t["function"]["name"] for t in toolkit.TOOL_SCHEMAS]
    for n in ("git_status", "git_commit", "write_document", "draw_diagram",
              "browser_open", "browser_js", "browser_mouse"):
        assert n in names
