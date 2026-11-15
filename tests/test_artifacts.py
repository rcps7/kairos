"""Tests for draw & write artifacts (SVG sanitization + storage)."""

from pathlib import Path

from kairos import artifacts


def _enable(monkeypatch, tmp_path):
    monkeypatch.setattr(artifacts, "_dir", lambda: tmp_path)
    monkeypatch.setattr(artifacts, "_cfg",
                        lambda: {"enabled": True, "allow_svg": True,
                                 "max_bytes": 100000})


def test_sanitize_removes_scripts():
    bad = ('<svg xmlns="http://www.w3.org/2000/svg">'
           '<script>alert(1)</script>'
           '<rect onclick="x()" width="10" height="10"/>'
           '<a href="http://evil.example">x</a>'
           '<use href="#ok"/></svg>')
    out = artifacts.sanitize_svg(bad)
    low = out.lower()
    assert "<script" not in low
    assert "onclick" not in low
    assert "evil.example" not in out
    assert "http://www.w3.org/2000/svg" in out  # xmlns preserved


def test_sanitize_rejects_non_svg():
    import pytest
    with pytest.raises(ValueError):
        artifacts.sanitize_svg("<html></html>")


def test_charts_and_storage(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    svg = artifacts.bar_chart("T", ["a", "b"], [1, 2])
    assert svg.startswith("<svg")
    p = artifacts.draw_svg("chart", svg)
    assert Path(p).exists()

    flow = artifacts.flowchart("F", ["A", "B"], [[0, 1]])
    assert "<svg" in flow

    d = artifacts.write_document("notes.md", "# hi")
    assert Path(d).read_text(encoding="utf-8") == "# hi"

    items = artifacts.list_artifacts()
    assert any(i["name"].startswith("chart") for i in items)


def test_disabled(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(artifacts, "_dir", lambda: tmp_path)
    monkeypatch.setattr(artifacts, "_cfg", lambda: {"enabled": False})
    with pytest.raises(PermissionError):
        artifacts.write_document("x.md", "y")
