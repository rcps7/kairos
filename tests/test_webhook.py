"""Tests for the webhook module (inbound server + auth + outbound signing)."""

import json
import urllib.error
import urllib.request

from kairos import webhook


class _Engine:
    telegram = None
    _loop = None

    def ask_llm(self, prompt, **kw):
        return "ok:" + (prompt or "")[:30]

    def run_skill(self, name):
        return f"ran:{name}"

    def add_memory(self, content):
        return "id"


def test_helpers():
    assert webhook._is_loopback("127.0.0.1")
    assert webhook._is_loopback("localhost")
    assert not webhook._is_loopback("8.8.8.8")
    assert webhook._sign("secret", b"body").startswith("sha256=")
    assert webhook._sign("", b"body") == ""


def test_handle_hook():
    mgr = webhook.WebhookManager(_Engine(), {
        "hooks": {"h1": {"action": "ask", "payload": "Q: {body}", "enabled": True}}})
    assert mgr.handle_hook("h1", {"x": 1}).startswith("ok:")
    assert mgr.handle_hook("missing", {}) == "unknown hook"


def test_server_roundtrip():
    cfg = {"enabled": True, "host": "127.0.0.1", "port": 0, "secret": "tok",
           "hooks": {"ping": {"action": "notify", "enabled": True}}}
    mgr = webhook.WebhookManager(_Engine(), cfg)
    mgr.start()
    try:
        port = mgr._server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            assert json.loads(r.read())["ok"] is True

        # Unauthorized (no token) -> 401
        req = urllib.request.Request(f"http://127.0.0.1:{port}/hook/ping",
                                     data=b"{}", method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401

        # Authorized -> 202
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/hook/ping", data=b"{}", method="POST",
            headers={"X-Kairos-Token": "tok"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 202
    finally:
        mgr.stop()


def test_public_bind_refused():
    import pytest
    cfg = {"enabled": True, "host": "0.0.0.0", "port": 0, "allow_public_bind": False}
    with pytest.raises(PermissionError):
        webhook.WebhookManager(_Engine(), cfg).start()
