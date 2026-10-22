"""Streaming tool-loop tests: raw tool markup must never reach the user."""

import types

import pytest

from kairos import tools


def test_marker_helpers():
    assert tools.first_tool_marker("see <web_search>") == 4
    assert tools.first_tool_marker('call web_search("x")') == 5
    assert tools.first_tool_marker("plain answer") is None
    assert tools.tool_marker_holdback("answer <") == 1
    assert tools.tool_marker_holdback("answer") == 0


def test_parse_function_call_form():
    clean, calls = tools.parse_tool_calls('Let me check. web_search("mars weather")')
    assert calls and calls[0].name == "web_search"
    assert calls[0].query == "mars weather"
    assert "web_search(" not in clean


def _require_pyside():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")


def _fake_engine(pieces, final="FINAL ANSWER"):
    eng = types.SimpleNamespace()

    class _LLM:
        def stream_text(self, uc, system_prompt=None, provider_id=None):
            for p in pieces:
                yield p

    eng.llm = _LLM()
    eng.list_providers = lambda: []
    eng.attach_context = lambda paths: ("", [])
    eng._build_user_content = lambda prompt, context: prompt
    eng.current_system_prompt = lambda extra=None, with_tools=False: "SYS"
    eng._record_usage = lambda *a, **k: None
    eng.spawn_graph_extract = lambda *a, **k: None
    eng.record_error = lambda *a, **k: None
    eng._run_tool = lambda call: "RAW RESULTS"
    eng.ask_llm = lambda conversation, **k: final
    eng.chat = lambda *a, **k: "FALLBACK"
    return eng


def _run_stream(eng, prompt="q"):
    from kairos.main import KairosEngine
    eng._tool_loop = types.MethodType(KairosEngine._tool_loop, eng)
    return "".join(KairosEngine.stream_chat(eng, prompt))


def test_stream_executes_tool_request():
    _require_pyside()
    eng = _fake_engine(["Let me look that up.",
                        "<web_search><query>x</query></web_search>"])
    out = _run_stream(eng)
    assert "<web_search" not in out
    assert "FINAL ANSWER" in out


def test_stream_plain_reply_passthrough():
    _require_pyside()
    eng = _fake_engine(["Hello", " world"])
    assert _run_stream(eng) == "Hello world"


def test_stream_function_form_tool():
    _require_pyside()
    eng = _fake_engine(["", 'web_search("cats")'])
    out = _run_stream(eng)
    assert "web_search(" not in out
    assert "FINAL ANSWER" in out
