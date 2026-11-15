"""Tests for the git & version-control workflows (system git CLI)."""

import shutil
import subprocess

import pytest

from kairos import git_tool

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def _make_repo(tmp):
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.io"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)


def _cfg(tmp, **extra):
    base = {"enabled": True, "repo_root": str(tmp), "allow_push": False,
            "allow_pull": False, "allow_destructive": False,
            "author_name": "", "author_email": "", "token": None}
    base.update(extra)
    return base


def test_name_validation():
    assert git_tool._check_name("feature/x") == "feature/x"
    with pytest.raises(ValueError):
        git_tool._check_name("../bad")


def test_confine(monkeypatch, tmp_path):
    monkeypatch.setattr(git_tool, "_cfg", lambda: _cfg(tmp_path))
    with pytest.raises(PermissionError):
        git_tool._confine(str(tmp_path.parent))


def test_git_workflow(monkeypatch, tmp_path):
    _make_repo(tmp_path)
    monkeypatch.setattr(git_tool, "_cfg", lambda: _cfg(tmp_path))
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    assert git_tool.is_repo()
    assert "a.txt" in git_tool.status()

    git_tool.add()
    git_tool.commit("initial commit")
    assert "initial commit" in git_tool.log(5)

    base_branch = git_tool.current_branch()
    git_tool.create_branch("feature/x")
    assert git_tool.current_branch() == "feature/x"
    assert "feature/x" in git_tool.branches()
    git_tool.checkout(base_branch)
    assert git_tool.current_branch() == base_branch


def test_push_pull_gated(monkeypatch, tmp_path):
    _make_repo(tmp_path)
    monkeypatch.setattr(git_tool, "_cfg", lambda: _cfg(tmp_path))
    with pytest.raises(PermissionError):
        git_tool.push()
    with pytest.raises(PermissionError):
        git_tool.pull()


def test_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(git_tool, "_cfg", lambda: _cfg(tmp_path, enabled=False))
    with pytest.raises(PermissionError):
        git_tool.status()


def test_summary(monkeypatch, tmp_path):
    _make_repo(tmp_path)
    monkeypatch.setattr(git_tool, "_cfg", lambda: _cfg(tmp_path))
    assert "Branch:" in git_tool.summary()
