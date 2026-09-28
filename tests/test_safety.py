"""Hardening tests (Plan A). These avoid GUI/heavy deps where possible."""

import json
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from kairos import safety


def test_safe_id_and_confine_path():
    assert safety.safe_id("good_name")
    assert not safety.safe_id("../evil")
    assert not safety.safe_id("bad name")
    d = Path(tempfile.mkdtemp())
    assert safety.confine_path(d, "ok").parent == d.resolve()
    try:
        safety.confine_path(d, "../evil")
        assert False, "traversal not blocked"
    except ValueError:
        pass


def test_safe_extract_zip_slip():
    d = Path(tempfile.mkdtemp())
    z = d / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "x")
    try:
        safety.safe_extract(z, d / "out")
        assert False, "zip slip not blocked"
    except ValueError:
        pass


def test_atomic_write_and_redact():
    d = Path(tempfile.mkdtemp())
    p = d / "f.json"
    safety.atomic_write_text(p, '{"a": 1}')
    assert json.loads(p.read_text())["a"] == 1
    assert "sk-1234567890123456" not in safety.redact_secrets("key sk-1234567890123456 here")
