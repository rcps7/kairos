"""Paired, encrypted LAN remote API so the Kairos Android app can control this PC.

Security model
    * Off by default (``remote.enabled``). When on it listens on the LAN
      (``remote.host``, default ``0.0.0.0``) and only answers clients whose
      source address is loopback, private (RFC 1918 / ULA) or link-local.
    * Pairing: a random 32-byte secret, kept in the OS keyring
      (``remote_secret``) and shared once with the phone as a
      ``kairos://pair?...`` link or QR code. Re-pairing replaces the secret, which
      revokes the old phone.
    * Every request and response is sealed with AES-256-GCM using a key derived
      from the secret with HKDF-SHA256. Tampered, replayed (nonce seen) or stale
      (clock skew > 120 s) messages are rejected; repeated failures from one IP
      are rate limited. Without the secret nothing is readable or forgeable, even
      on an untrusted Wi-Fi.

Wire format (``POST /v1/rpc``, JSON)::

    request  {"v": 1, "kid": "<8 hex>", "ts": <unix s>, "n": "<b64url 12B>", "c": "<b64url>"}
             AAD = "kairos-remote-v1|req|<ts>"
    response {"v": 1, "n": "<b64url 12B>", "c": "<b64url>"}
             AAD = "kairos-remote-v1|resp|<request n>"
    plaintext request  {"op": "...", "args": {...}}
    plaintext response {"ok": true, "result": ...} | {"ok": false, "error": "..."}

Operations: ``ping``, ``chat`` (prompt), ``submit`` (prompt, mode -> job id),
``job`` (id), ``jobs``, ``kill`` (confirm=true).

Config (``remote``)::

    {"enabled": false, "host": "0.0.0.0", "port": 8766, "secret": null}

CLI: ``python -m kairos.remote_api pair`` prints the pairing link and a QR code.
"""

import base64
import collections
import hashlib
import ipaddress
import json
import logging
import os
import secrets as _secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

from kairos.jobs import Job, JobQueue

logger = logging.getLogger(__name__)

PROTOCOL = 1
MAX_BODY = 1_000_000
MAX_SKEW = 120          # seconds
NONCE_TTL = 300         # seconds a nonce is remembered
MAX_FAILURES = 10       # per IP per minute before 429
MAX_RESULT = 200_000    # characters returned per job result
MAX_JOBS_KEPT = 50
_INFO = b"kairos-remote-v1 aes-256-gcm"
_SALT = b"kairos-remote"


# ---------------------------------------------------------------------------
# Crypto helpers (shared test vectors with android/.../remote/Remote.kt)
# ---------------------------------------------------------------------------
def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def b64d(s: str) -> bytes:
    s = (s or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_secret() -> str:
    return b64e(_secrets.token_bytes(32))


def derive_key(secret: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    raw = b64d(secret)
    if len(raw) < 32:
        raise ValueError("pairing secret is too short")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=_SALT, info=_INFO).derive(raw)


def key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def seal(key: bytes, plaintext: bytes, aad: bytes, nonce: bytes = None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = nonce or os.urandom(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def open_sealed(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


def req_aad(ts: int) -> bytes:
    return f"kairos-remote-v1|req|{int(ts)}".encode("ascii")


def resp_aad(req_nonce_b64: str) -> bytes:
    return f"kairos-remote-v1|resp|{req_nonce_b64}".encode("ascii")


def client_allowed(addr: str) -> bool:
    """Only same-LAN callers: loopback, private (RFC 1918/ULA) or link-local."""
    try:
        ip = ipaddress.ip_address((addr or "").split("%", 1)[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local


def lan_address() -> str:
    """Best guess at this PC's LAN IP (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def pairing_link(host: str, port: int, secret: str, name: str = None) -> str:
    name = name or socket.gethostname()
    return f"kairos://pair?host={quote(host)}&port={int(port)}&key={secret}&name={quote(name)}"


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
class RemoteServer:
    def __init__(self, engine, cfg: dict = None, clock=time.time):
        self.engine = engine
        self.cfg = cfg or {}
        self.clock = clock
        secret = self.cfg.get("secret")
        if not secret:
            raise ValueError("remote.secret is not set; pair a phone first")
        self.key = derive_key(secret)
        self.kid = key_id(self.key)
        self.queue = JobQueue()
        self.jobs = collections.OrderedDict()
        self._jobs_lock = threading.Lock()
        self._nonces = {}
        self._nonce_lock = threading.Lock()
        self._failures = collections.defaultdict(collections.deque)
        self._server = None
        self._thread = None

    # -- lifecycle ------------------------------------------------------
    def start(self):
        host = self.cfg.get("host", "0.0.0.0")
        port = int(self.cfg.get("port", 8766))
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "KairosRemote/1"

            def log_message(self, *a):
                return

            def _send(self, code, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

            def do_GET(self):
                if not client_allowed(self.client_address[0]):
                    return self._send(403, {"error": "forbidden"})
                if self.path == "/v1/hello":
                    # Unauthenticated discovery: only the protocol and key id.
                    return self._send(200, {"service": "kairos-remote", "v": PROTOCOL, "kid": server.kid})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                ip = self.client_address[0]
                if not client_allowed(ip):
                    return self._send(403, {"error": "forbidden"})
                if self.path != "/v1/rpc":
                    return self._send(404, {"error": "not found"})
                if server._rate_limited(ip):
                    return self._send(429, {"error": "too many failures"})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                if length <= 0 or length > MAX_BODY:
                    return self._send(413, {"error": "bad size"})
                raw = self.rfile.read(length)
                code, obj = server.handle_raw(raw, ip)
                self._send(code, obj)

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True,
                                        name="kairos-remote")
        self._thread.start()
        return self

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else 0

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # -- request handling ------------------------------------------------
    def _rate_limited(self, ip) -> bool:
        q = self._failures[ip]
        now = self.clock()
        while q and now - q[0] > 60:
            q.popleft()
        return len(q) >= MAX_FAILURES

    def _fail(self, ip, code=401, msg="unauthorized"):
        self._failures[ip].append(self.clock())
        return code, {"error": msg}

    def _fresh_nonce(self, n: str) -> bool:
        now = self.clock()
        with self._nonce_lock:
            for k in [k for k, t in self._nonces.items() if now - t > NONCE_TTL]:
                del self._nonces[k]
            if n in self._nonces:
                return False
            self._nonces[n] = now
            return True

    def handle_raw(self, raw: bytes, ip: str = "127.0.0.1"):
        try:
            env = json.loads(raw.decode("utf-8"))
            ts = int(env["ts"])
            n = str(env["n"])
            nonce, ct = b64d(n), b64d(env["c"])
        except Exception:
            return self._fail(ip, 400, "bad request")
        if env.get("v") != PROTOCOL or env.get("kid") != self.kid or len(nonce) != 12:
            return self._fail(ip)
        if abs(self.clock() - ts) > MAX_SKEW:
            return self._fail(ip, 401, "stale request (check the clocks)")
        try:
            req = json.loads(open_sealed(self.key, nonce, ct, req_aad(ts)).decode("utf-8"))
        except Exception:
            return self._fail(ip)
        if not self._fresh_nonce(n):
            return self._fail(ip, 401, "replayed request")
        try:
            result = {"ok": True, "result": self.dispatch(req.get("op"), req.get("args") or {})}
        except Exception as e:  # noqa: BLE001 - reported to the paired client only
            result = {"ok": False, "error": str(e)[:500]}
        rn, rc = seal(self.key, json.dumps(result).encode("utf-8"), resp_aad(n))
        return 200, {"v": PROTOCOL, "n": b64e(rn), "c": b64e(rc)}

    # -- operations ------------------------------------------------------
    def dispatch(self, op, args: dict):
        if op == "ping":
            from kairos import __version__
            character = None
            try:
                character = (self.engine.active_character_profile() or {}).get("name")
            except Exception:
                pass
            return {"name": socket.gethostname(), "version": __version__,
                    "character": character, "busy": self.queue.pending()}
        if op == "chat":
            prompt = str(args.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("prompt is required")
            return str(self.engine.chat(prompt))[:MAX_RESULT]
        if op == "submit":
            return {"id": self.submit(str(args.get("prompt") or ""), args.get("mode"))}
        if op == "job":
            return self.job(str(args.get("id") or ""))
        if op == "jobs":
            with self._jobs_lock:
                return [self._public(j) for j in reversed(self.jobs.values())]
        if op == "kill":
            if args.get("confirm") is not True:
                raise ValueError("kill needs confirm=true")
            threading.Thread(target=self.engine.emergency_kill, daemon=True).start()
            return "Kill switch engaged on the PC."
        raise ValueError(f"unknown op '{op}'")

    def submit(self, prompt: str, mode: str = None) -> str:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt is required")
        mode = mode if mode in ("chat", "plan", "execute") else None
        rec = {"id": None, "prompt": prompt[:500], "mode": mode or "default", "status": "queued",
               "progress": "", "output": "", "result": None, "error": None,
               "created": self.clock(), "finished": None}

        def run(emit_chunk, emit_progress):
            if mode == "chat":
                return self.engine.chat(prompt, progress=emit_progress)
            return self.engine.run_agent(prompt, mode=mode, progress=emit_progress)

        def on_start(_id):
            rec["status"] = "running"

        def on_progress(_id, text):
            rec["progress"] = str(text)[-500:]

        def on_chunk(_id, text):
            rec["output"] = (rec["output"] + str(text))[-MAX_RESULT:]

        def on_done(_id, result):
            if isinstance(result, dict):
                result = result.get("text") or json.dumps(result, default=str, indent=1)
            rec.update(status="done", result=str(result)[:MAX_RESULT], finished=self.clock())

        def on_error(_id, exc):
            rec.update(status="error", error=str(exc)[:500], finished=self.clock())

        job = Job(run, label="remote", on_start=on_start, on_progress=on_progress,
                  on_chunk=on_chunk, on_done=on_done, on_error=on_error)
        rec["id"] = job.id
        with self._jobs_lock:
            self.jobs[job.id] = rec
            while len(self.jobs) > MAX_JOBS_KEPT:
                self.jobs.popitem(last=False)
        self.queue.submit(job)
        return job.id

    def job(self, job_id: str) -> dict:
        with self._jobs_lock:
            rec = self.jobs.get(job_id)
            if rec is None:
                raise KeyError(f"no job '{job_id}'")
            return dict(rec)

    @staticmethod
    def _public(rec):
        return {k: rec[k] for k in ("id", "prompt", "mode", "status", "created", "finished")}


# ---------------------------------------------------------------------------
# Client (used by tests and for PC-to-PC scripting)
# ---------------------------------------------------------------------------
def call(host: str, port: int, secret: str, op: str, args: dict = None, timeout: float = 30):
    import urllib.request
    key = derive_key(secret)
    ts = int(time.time())
    nonce, ct = seal(key, json.dumps({"op": op, "args": args or {}}).encode("utf-8"), req_aad(ts))
    n = b64e(nonce)
    body = json.dumps({"v": PROTOCOL, "kid": key_id(key), "ts": ts, "n": n, "c": b64e(ct)}).encode()
    req = urllib.request.Request(f"http://{host}:{port}/v1/rpc", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        env = json.loads(r.read().decode("utf-8"))
    out = json.loads(open_sealed(key, b64d(env["n"]), b64d(env["c"]), resp_aad(n)))
    if not out.get("ok"):
        raise RuntimeError(out.get("error"))
    return out.get("result")


def pair(cfg: dict, save) -> str:
    """Create a new secret (revoking any paired phone) and return the pairing link."""
    remote = cfg.setdefault("remote", {})
    secret = new_secret()
    remote["secret"] = secret
    save(cfg)
    host = remote.get("host") or "0.0.0.0"
    if host in ("0.0.0.0", "::", ""):
        host = lan_address()
    return pairing_link(host, int(remote.get("port", 8766)), secret)


class EchoEngine:
    """Deterministic stand-in engine for protocol tests (no LLM needed)."""

    def active_character_profile(self):
        return {"name": "Echo"}

    def chat(self, prompt, progress=None):
        return f"echo: {prompt}"

    def run_agent(self, prompt, mode=None, progress=None):
        if progress:
            progress("step 1/1")
        time.sleep(0.2)
        return {"mode": mode or "chat", "text": f"done [{mode or 'default'}]: {prompt}"}

    def emergency_kill(self):
        return True


def _main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="python -m kairos.remote_api")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pair", help="create a new pairing link/QR (revokes the old phone)")
    t = sub.add_parser("serve-test", help="serve with an echo engine (for app tests)")
    t.add_argument("--port", type=int, default=8766)
    t.add_argument("--host", default="0.0.0.0")
    t.add_argument("--secret", required=True)
    a = p.parse_args(argv)
    if a.cmd == "pair":
        from kairos.config import load_config, save_config
        cfg = load_config()
        link = pair(cfg, save_config)
        print("Pairing link (keep it private):\n" + link)
        try:
            import qrcode
            qr = qrcode.QRCode(border=1)
            qr.add_data(link)
            qr.print_ascii(invert=True)
        except Exception:
            pass
        print("Set remote.enabled to true in the config and restart Kairos to start the server.")
        return 0
    srv = RemoteServer(EchoEngine(), {"host": a.host, "port": a.port, "secret": a.secret}).start()
    print(f"kairos-remote test server on {a.host}:{srv.port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
