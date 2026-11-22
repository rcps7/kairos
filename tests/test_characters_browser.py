"""Tests for built-in character capability migration (browser_control)."""

import json

from kairos.characters import CharacterManager


def test_builtins_have_browser_control(tmp_path):
    mgr = CharacterManager(str(tmp_path))
    for cid in ("general", "electronic_specialist", "medical_assistant",
                "ai_expert", "astrophysics_expert"):
        assert mgr.can("browser_control", cid), cid


def test_stale_builtin_profile_is_synced(tmp_path):
    mgr = CharacterManager(str(tmp_path))
    p = mgr._profile_path("medical_assistant")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["capabilities"] = ["web_search"]
    p.write_text(json.dumps(data), encoding="utf-8")

    mgr.reload()
    assert mgr.can("browser_control", "medical_assistant")