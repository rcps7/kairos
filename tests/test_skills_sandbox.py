"""Skill confinement + sandbox tests (A2)."""

import tempfile
from pathlib import Path

from kairos.skills import SkillManager

SKILL = '''from kairos.skills.base import Skill
class Hello(Skill):
    name = "hello"
    description = "test"
    def run(self, engine, **kwargs):
        return "echo:" + engine.ask_llm("hi")
'''


class _FakeEngine:
    def ask_llm(self, prompt, **k):
        return "PONG"


def test_name_traversal_blocked():
    d = Path(tempfile.mkdtemp())
    mgr = SkillManager(str(d))
    assert mgr.read_source("../evil") == ""
    try:
        mgr.save_source("../evil", "x=1")
        assert False, "traversal not blocked"
    except ValueError:
        pass


def test_sandbox_rpc():
    d = Path(tempfile.mkdtemp())
    (d / "hello.py").write_text(SKILL, encoding="utf-8")
    mgr = SkillManager(str(d))
    out = mgr.run_skill("hello", _FakeEngine())
    assert out == "echo:PONG", out
