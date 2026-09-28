"""Wave 1 tests: structured output, planner, platform tools, tracing."""

import tempfile
from pathlib import Path
from unittest import mock

from pydantic import BaseModel

from kairos import structured, toolkit
from kairos.planner import PlannerStore
from kairos.tracing import SpanStore


class Person(BaseModel):
    name: str
    age: int


class _Eng:
    def __init__(self, replies):
        self.replies = list(replies)

    def ask_llm(self, prompt, system_prompt=None, use_character=True):
        return self.replies.pop(0) if self.replies else "{}"


def test_structured_retry():
    e = _Eng(["not json", '{"name": "Ada", "age": 36}'])
    p = structured.generate_json(e, "who?", Person, retries=2)
    assert p.name == "Ada" and p.age == 36
    assert structured.extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}


def test_planner_store():
    db = Path(tempfile.mkdtemp()) / "p.db"
    st = PlannerStore(db)
    pid = st.create("Build a robot", ["design", "assemble"])
    assert len(st.list_plans()) == 1
    plan = st.get_plan(pid)
    assert [s["title"] for s in plan["steps"]] == ["design", "assemble"]
    st.update_step(plan["steps"][0]["id"], "done", "ok")
    assert st.get_plan(pid)["steps"][0]["status"] == "done"
    st.delete(pid)
    assert st.get_plan(pid) is None
    st.close()


class _ToolEng:
    def __init__(self):
        self.plans = {}

    def can(self, cap):
        return True

    def plan_create(self, goal, steps=None):
        self.plans["p1"] = {"goal": goal, "steps": steps or []}
        return "p1"

    def plan_add_step(self, plan_id, title):
        return "s1"

    def plan_update_step(self, *a):
        return None

    def plan_get(self, plan_id):
        return {"goal": "g", "status": "open",
                "steps": [{"idx": 0, "status": "todo", "title": "t"}]}


def test_toolkit_files_and_gates():
    root = Path(tempfile.mkdtemp())
    fake_cfg = mock.Mock()
    fake_cfg.load_config.return_value = {
        "agent": {"file_root": str(root), "allow_file_write": True, "allow_shell": False}}
    with mock.patch.object(toolkit, "_config", fake_cfg):
        e = _ToolEng()
        assert toolkit.execute(e, "write_file", {"path": "a/b.txt", "content": "hi"}) .startswith("Wrote")
        assert toolkit.execute(e, "read_file", {"path": "a/b.txt"}) == "hi"
        assert "b.txt" in toolkit.execute(e, "list_dir", {"path": "a"})
        try:
            toolkit.execute(e, "read_file", {"path": "../../etc/passwd"})
            assert False, "escape not blocked"
        except PermissionError:
            pass
        try:
            toolkit.execute(e, "run_command", {"command": "echo hi"})
            assert False, "shell not blocked"
        except PermissionError:
            pass
        assert toolkit.execute(e, "plan_status", {"plan_id": "p1"}).startswith("g")


def test_tracing():
    db = Path(tempfile.mkdtemp()) / "t.db"
    st = SpanStore(db)
    st.add("chat", "p", "m", 10, 5, ms=42, ok=1)
    rows = st.recent(5)
    assert rows and rows[0][1] == "chat"
    st.close()
