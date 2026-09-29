"""Wave 4 tests: sub-agents, evaluation harness, docker availability."""

from kairos import agents, evaluation, toolkit
from kairos.skills import docker_runner


class _Eng:
    def ask_llm(self, prompt, system_prompt=None, use_character=True):
        return f"sub:{prompt}"

    def can(self, cap):
        return True


def test_subagents():
    names = [s["name"] for s in agents.list_subagents()]
    for n in ("researcher", "coder", "analyst", "writer", "planner"):
        assert n in names
    out = agents.run_subagent(_Eng(), "writer", "write a haiku")
    assert "write a haiku" in out
    try:
        agents.run_subagent(_Eng(), "nope", "x")
        assert False
    except ValueError:
        pass


def test_delegate_tool():
    out = toolkit.execute(_Eng(), "delegate", {"agent": "coder", "task": "fix bug"})
    assert "fix bug" in out


def test_evaluation_suite():
    r = evaluation.run_suite()
    assert r["failed"] == 0, r["results"]
    assert r["total"] >= 5


def test_docker_available_flag():
    assert isinstance(docker_runner.available(), bool)
