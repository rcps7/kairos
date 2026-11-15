"""Inbound + outbound webhooks for Kairos (stdlib HTTP server, no new deps).

Inbound
    A small ``http.server`` bound to ``webhook.host`` (loopback by default).
    External systems ``POST /hook/<name>``; each configured hook maps to an
    action (``ask`` | ``skill`` | ``remember`` | ``notify``). Optional shared
    secret (``X-Kairos-Token``) and HMAC-SHA256 signature
    (``X-Kairos-Signature: sha256=<hex>``) verification. Body size is capped and
    payloads are treated strictly as untrusted data.

Outbound
    :meth:`WebhookManager.notify` POSTs a signed JSON body to every configured
    URL. Wired to job completion/errors, scheduler runs, predictions, approvals
    and git commits.

Config (``webhook``)::

    {
      "enabled": false,
      "host": "127.0.0.1",
      "port": 8765,
      "allow_public_bind": false,
      "secret": null,                 # secret -> keyring ("webhook_secret")
      "require_signature": false,
      "hooks": {
        "build": {"action": "ask", "payload": "Summarize this build event: {body}", "enabled": true}
      },
      "outbound": {"enabled": false, "urls": [], "secret": null}
    }
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

MAX_BODY = 1_000_000            # 1 MB
HOOK_PREFIX = "/hook/"


def _is_loopback(host: str) -> bool:
    host = (host or "").strip()
    if host in ("", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _sign(secret: str, body: bytes) -> str:
    if not secret:
        return ""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class WebhookManager:
    def __init__(self, engine, cfg: dict = None):
        self.engine = engine
        self.cfg = cfg or {}
        self._server = None
        self._thread = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        host = self.cfg.get("host", "127.0.0.1")
        port = int(self.cfg.get("port", 8765))
        if not _is_loopback(host) and not self.cfg.get("allow_public_bind"):
            raise PermissionError(
                "Refusing to bind the webhook endpoint to a non-loopback host "
                "without webhook.allow_public_bind."
            )
        manager = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "KairosWebhook/1.0"

            def log_message(self, *a):  # silence default stderr logging
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
                if self.path == "/health":
                    from kairos import __version__
                    self._send(200, {"ok": True, "service": "kairos", "version": __version__})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                if not self.path.startswith(HOOK_PREFIX):
                    self._send(404, {"error": "not found"})
                    return
                name = self.path[len(HOOK_PREFIX):].split("?", 1)[0].strip("/")
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = 0
                if length > MAX_BODY:
                    self._send(413, {"error": "payload too large"})
                    return
                raw = self.rfile.read(length) if length else b""
                if not manager._authorized(self.headers, raw):
                    self._send(401, {"error": "unauthorized"})
                    return
                try:
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                except Exception:
                    payload = {"raw": raw.decode("utf-8", "ignore")}
                wait = "wait=1" in (self.path.split("?", 1)[1] if "?" in self.path else "")
                try:
                    if wait:
                        result = manager.handle_hook(name, payload)
                        self._send(200, {"ok": True, "result": str(result)[:8000]})
                    else:
                        threading.Thread(target=manager.handle_hook, args=(name, payload),
                                         daemon=True).start()
                        self._send(202, {"ok": True, "accepted": name})
                except Exception as e:
                    self._send(400, {"ok": False, "error": str(e)[:300]})

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True, name="kairos-webhook")
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self._server:
                self._server.shutdown()
                self._server.server_close()
        except Exception:
            pass
        self._server = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def _secret(self) -> str:
        return (self.cfg.get("secret") or "").strip()

    def _authorized(self, headers, body: bytes) -> bool:
        secret = self._secret()
        if not secret:
            # No secret configured: rely on the loopback-only bind restriction.
            return True
        token = headers.get("X-Kairos-Token", "")
        if token and hmac.compare_digest(token, secret):
            return True
        if self.cfg.get("require_signature"):
            sig = headers.get("X-Kairos-Signature", "")
            if sig and hmac.compare_digest(sig, _sign(secret, body)):
                return True
            return False
        return False

    # ------------------------------------------------------------------
    # Inbound dispatch
    # ------------------------------------------------------------------
    def handle_hook(self, name: str, payload: dict):
        hooks = self.cfg.get("hooks", {}) or {}
        hook = hooks.get(name)
        if not hook or not hook.get("enabled", True):
            logger.warning("Webhook '%s' is not configured/enabled.", name)
            return "unknown hook"
        action = (hook.get("action") or "ask").lower()
        body_text = json.dumps(payload, ensure_ascii=False)
        template = hook.get("payload") or "{body}"
        prompt = template.replace("{body}", body_text)
        try:
            if action == "ask":
                result = self.engine.ask_llm(prompt)
            elif action == "skill":
                result = self.engine.run_skill(hook.get("skill") or prompt)
            elif action == "remember":
                self.engine.add_memory(prompt)
                result = "remembered"
            elif action == "notify":
                self._to_telegram(f"Webhook '{name}':\n{body_text[:1000]}")
                result = "notified"
            else:
                result = f"unknown action '{action}'"
        except Exception as e:
            logger.exception("Webhook action failed.")
            result = f"error: {e}"
        logger.info("Webhook '%s' (%s) -> %s", name, action, str(result)[:120])
        return result

    def _to_telegram(self, text: str):
        try:
            tg = getattr(self.engine, "telegram", None)
            if tg and tg.running and getattr(self.engine, "_loop", None):
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    tg.notify_task("webhook", text), self.engine._loop)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    def notify(self, event: str, data: dict = None):
        out = self.cfg.get("outbound", {}) or {}
        if not out.get("enabled"):
            return
        urls = out.get("urls") or []
        if not urls:
            return
        secret = (out.get("secret") or "").strip()
        body = json.dumps({"event": event, "data": data or {}}).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Kairos-Event": event}
        if secret:
            headers["X-Kairos-Signature"] = _sign(secret, body)
        try:
            import httpx
        except Exception:
            return
        for url in urls:
            try:
                httpx.post(url, content=body, headers=headers, timeout=10)
            except Exception:
                logger.debug("Outbound webhook to %s failed.", url, exc_info=True)
