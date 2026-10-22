"""Engine concurrency: the chat re-entrancy guard must be per-thread."""

import threading
import types

import pytest


def _require_pyside():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")


def _fake_engine():
    from kairos.main import KairosEngine  # noqa: F401
    eng = types.SimpleNamespace()
    eng._chat_local = threading.local()
    eng._llm_gate = threading.RLock()
    eng.config = {"agent": {}}
    eng.attach_context = lambda paths: ("", [])
    eng._build_user_content = lambda prompt, context: prompt
    eng.list_providers = lambda: []
    eng._graph_cfg = lambda: {"use_in_chat": False, "use_in_tools": False}
    eng.spawn_graph_extract = lambda *a, **k: None
    eng.record_error = lambda *a, **k: None
    eng.ask_llm = lambda prompt, **k: "DEGRADED"
    eng._tool_loop = lambda conv, progress=None: "FULL"
    return eng


def test_concurrent_chat_is_independent_per_thread():
    _require_pyside()
    from kairos.main import KairosEngine
    eng = _fake_engine()
    results = {}
    barrier = threading.Barrier(2)

    def worker(key):
        barrier.wait()
        results[key] = KairosEngine.chat(eng, "hi")

    ts = [threading.Thread(target=worker, args=(k,)) for k in ("a", "b")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    # Both threads keep full chat behaviour (no degradation to ask_llm).
    assert results == {"a": "FULL", "b": "FULL"}


def test_same_thread_reentry_degrades():
    _require_pyside()
    from kairos.main import KairosEngine
    eng = _fake_engine()
    eng._chat_local.active = True  # simulate being inside chat on this thread
    assert KairosEngine.chat(eng, "hi") == "DEGRADED"
