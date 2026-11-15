"""GUI regression tests: mode dropdown is selectable; provider/model selector works."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kairos.gui.main_window import KairosGUI  # noqa: E402


class _Chars:
    active_id = "general"

    def active(self):
        return {"id": "general", "name": "General", "system_prompt": "x",
                "capabilities": None}

    def capabilities(self):
        return ["web_search", "learn_web", "memory"]

    def can(self, cap):
        return True

    def allows_skill(self, name):
        return True


class _LLM:
    active_provider = "moonshot"
    providers = {"moonshot": {"model": "kimi-k3", "api_key": "x"}}


class _Engine:
    def __init__(self):
        self.llm = _LLM()
        self.characters = _Chars()
        self.collab = None
        self._mode = "chat"
        self.config = {"agent": {"mode": "chat"}, "council": {"members": []}}

    def list_skills(self):
        return []

    def list_providers(self):
        return ["moonshot"]

    def can(self, cap):
        return True

    def character_capabilities(self):
        return None

    def graph_pending_count(self):
        return 0

    def get_mode(self):
        return self._mode

    def set_mode(self, mode):
        self._mode = mode
        return mode

    def cached_models(self, pid):
        return ["kimi-k3", "kimi-k2-0905-preview"]


def _app():
    return QApplication.instance() or QApplication([])


def test_mode_dropdown_is_selectable():
    _app()
    gui = KairosGUI(_Engine())

    # Regression: the dropdown must remain enabled so Plan/Execute can be chosen.
    assert gui.mode_combo.isEnabled()
    assert gui.chat_mode_btn.isChecked()

    plan_idx = gui.mode_combo.findData("plan")
    assert plan_idx >= 0
    gui._on_mode_activated(plan_idx)
    assert gui._current_mode() == "plan"
    assert not gui.chat_mode_btn.isChecked()

    exec_idx = gui.mode_combo.findData("execute")
    gui._on_mode_activated(exec_idx)
    assert gui._current_mode() == "execute"

    gui._select_chat_mode()
    assert gui._current_mode() == "chat"
    # still selectable after returning to chat
    assert gui.mode_combo.isEnabled()

    gui.deleteLater()


def test_provider_model_selector_populated():
    _app()
    eng = _Engine()
    gui = KairosGUI(eng)

    assert gui.provider_combo.count() == 1
    assert gui.provider_combo.currentData() == "moonshot"
    models = [gui.model_combo.itemData(i) for i in range(gui.model_combo.count())]
    assert "kimi-k3" in models
    assert gui.model_combo.currentData() or gui.model_combo.currentText()

    gui.deleteLater()
