"""Tests for the paired, encrypted LAN remote API (kairos/remote_api.py).

The VECTOR is shared with android/app/src/test/.../RemoteTest.kt so the phone
and the PC are checked against the same bytes.
"""

import json
import time

import pytest

pytest.importorskip("cryptography")

from kairos import remote_api as ra  # noqa: E402

SECRET = ra.b64e(bytes(range(32)))
VECTOR = {"kid": "aa609800", "c": "ofjvu6mWWm60OkaarF_gsoc2glyksuVUeRLhyWI",
          "key": "aa40b0756d7874a5acadca61b8b409985915c707bc7b06f7cbb6c5b4f90d228f"}


def test_known_vector_matches_android():
    key = ra.derive_key(SECRET)
    assert key.hex() == VECTOR["key"]
    assert ra.key_id(key) == VECTOR["kid"]
    _, c = ra.seal(key, b'{"op":"ping"}', ra.req_aad(1700000000), nonce=bytes(12))
    assert ra.b64e(c) == VECTOR["c"]


def _envelope(key, payload, ts=None, nonce=None):
    ts = int(time.time()) if ts is None else ts
    n, c = ra.seal(key, json.dumps(payload).encode(), ra.req_aad(ts), nonce=nonce)
    return {"v": 1, "kid": ra.key_id(key), "ts": ts, "n": ra.b64e(n), "c": ra.b64e(c)}


def _open(key, env, resp):
    return json.loads(ra.open_sealed(key, ra.b64d(resp["n"]), ra.b64d(resp["c"]), ra.resp_aad(env["n"])))


def test_rejects_tamper_replay_stale_and_wrong_key():
    srv = ra.RemoteServer(ra.EchoEngine(), {"secret": SECRET})
    key = srv.key
    env = _envelope(key, {"op": "chat", "args": {"prompt": "hi"}})
    code, resp = srv.handle_raw(json.dumps(env).encode())
    assert code == 200 and _open(key, env, resp) == {"ok": True, "result": "echo: hi"}
    # replay of the same nonce
    assert srv.handle_raw(json.dumps(env).encode())[0] == 401
    # tampered ciphertext
    bad = _envelope(key, {"op": "ping"})
    bad["c"] = ra.b64e(bytes([ra.b64d(bad["c"])[0] ^ 1]) + ra.b64d(bad["c"])[1:])
    assert srv.handle_raw(json.dumps(bad).encode())[0] == 401
    # timestamp moved (AAD mismatch) and stale
    moved = _envelope(key, {"op": "ping"})
    moved["ts"] += 1
    assert srv.handle_raw(json.dumps(moved).encode())[0] == 401
    assert srv.handle_raw(json.dumps(_envelope(key, {"op": "ping"}, ts=int(time.time()) - 600)).encode())[0] == 401
    # other pairing secret
    other = ra.derive_key(ra.new_secret())
    assert srv.handle_raw(json.dumps(_envelope(other, {"op": "ping"})).encode())[0] == 401
    assert srv.handle_raw(b"not json")[0] == 400


def test_rate_limit_after_failures():
    srv = ra.RemoteServer(ra.EchoEngine(), {"secret": SECRET})
    for _ in range(ra.MAX_FAILURES):
        srv.handle_raw(b"x", "10.0.0.9")
    assert srv._rate_limited("10.0.0.9")
    assert not srv._rate_limited("10.0.0.10")


def test_lan_only():
    for ok in ("127.0.0.1", "192.168.1.4", "10.1.2.3", "172.16.0.1", "fe80::1", "::1", "fd00::5", "::ffff:192.168.0.2"):
        assert ra.client_allowed(ok), ok
    for bad in ("8.8.8.8", "1.1.1.1", "2001:4860::8888", "", "nonsense"):
        assert not ra.client_allowed(bad), bad


def test_pairing_link_and_pair(tmp_path):
    link = ra.pairing_link("192.168.1.5", 8766, SECRET, "My PC")
    assert link == f"kairos://pair?host=192.168.1.5&port=8766&key={SECRET}&name=My%20PC"
    saved = {}
    cfg = {"remote": {"host": "127.0.0.1", "port": 9000}}
    link = ra.pair(cfg, lambda c: saved.update(c))
    assert saved["remote"]["secret"] == cfg["remote"]["secret"]
    assert len(ra.b64d(cfg["remote"]["secret"])) == 32
    assert link.startswith("kairos://pair?host=127.0.0.1&port=9000&key=")


def test_end_to_end_over_http_runs_job():
    srv = ra.RemoteServer(ra.EchoEngine(), {"host": "127.0.0.1", "port": 0, "secret": SECRET}).start()
    try:
        port = srv.port
        info = ra.call("127.0.0.1", port, SECRET, "ping")
        assert info["version"] == "0.16.5" and info["character"] == "Echo"
        assert ra.call("127.0.0.1", port, SECRET, "chat", {"prompt": "yo"}) == "echo: yo"
        jid = ra.call("127.0.0.1", port, SECRET, "submit", {"prompt": "build it", "mode": "execute"})["id"]
        for _ in range(50):
            job = ra.call("127.0.0.1", port, SECRET, "job", {"id": jid})
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert job["status"] == "done" and job["result"] == "done [execute]: build it"
        assert job["progress"] == "step 1/1"
        assert [j["id"] for j in ra.call("127.0.0.1", port, SECRET, "jobs")] == [jid]
        with pytest.raises(RuntimeError, match="confirm"):
            ra.call("127.0.0.1", port, SECRET, "kill")
        assert "Kill switch" in ra.call("127.0.0.1", port, SECRET, "kill", {"confirm": True})
        with pytest.raises(RuntimeError, match="unknown op"):
            ra.call("127.0.0.1", port, SECRET, "rm -rf")
    finally:
        srv.stop()


def test_config_keeps_secret_out_of_json(monkeypatch):
    from kairos import config
    assert config.DEFAULT_CONFIG["remote"] == {"enabled": False, "host": "0.0.0.0", "port": 8766, "secret": None}
