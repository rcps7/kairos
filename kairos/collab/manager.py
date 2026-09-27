"""Collaboration manager: listener, outbound connects, handshake approval and
session dispatch. Runs an asyncio loop on a dedicated thread (same pattern as
the Telegram bot) and exposes thread-safe methods for the GUI/Telegram.
"""

import asyncio
import base64
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field

from . import callsign, identity, protocol, security, session
from .transport import choose_endpoint

logger = logging.getLogger(__name__)

CAPABILITIES = ["chat", "file", "voice", "video", "project", "llm"]


@dataclass
class IncomingRequest:
    id: str
    remote_fp: str
    label: str
    callsign: str
    sas: str
    reader: object
    writer: object
    capabilities: list = field(default_factory=list)


class CollaborationManager:
    def __init__(self, engine=None, config=None, display_name: str = "",
                 allow_private: bool = False, allow_loopback: bool = False):
        self.engine = engine
        cfg = config or {}
        self.allow_private = cfg.get("allow_private_targets", allow_private)
        self.allow_loopback = allow_loopback or cfg.get("allow_loopback", False)
        self.max_sessions = int(cfg.get("max_sessions", 4))
        self.accept_timeout = float(cfg.get("accept_timeout", 60))
        self.idle_timeout = float(cfg.get("idle_timeout", 300))

        self.identity = identity.load_identity(
            display_name or cfg.get("display_name", ""),
            directory=cfg.get("identity_dir"),
        )
        self.display_name = self.identity.label
        self._loop = None
        self._thread = None
        self._server = None
        self._sessions = {}
        self._pending = {}
        self._limiter = security.RateLimiter()
        self._bind_host = None
        self._advertised_host = None
        self._transport = "direct"
        self._port = None

        # callbacks (set by GUI/Telegram)
        self.on_incoming = None       # fn(IncomingRequest)
        self.on_connected = None      # fn(Session)
        self.on_chat = None           # fn(Session, text)
        self.on_disconnected = None   # fn(Session)
        self.on_event = None          # fn(str) status text

        self._start_loop()
        self.start_listener(cfg.get("transport", "direct"),
                            int(cfg.get("listen_port", 7777)),
                            cfg.get("allow_public_bind", False),
                            bind_host=cfg.get("listen_host"))

    # ------------------------------------------------------------------
    def _start_loop(self):
        self._loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, daemon=True, name="kairos-collab")
        self._thread.start()

    def _run(self, coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def _notify(self, text):
        if self.on_event:
            try:
                self.on_event(text)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def start_listener(self, mode="direct", port=7777, allow_public_bind=False, bind_host=None):
        if bind_host:
            self._transport = "direct"
            self._bind_host = bind_host
            self._advertised_host = bind_host
        else:
            self._transport, self._bind_host, self._advertised_host = choose_endpoint(
                mode, allow_public_bind)
        self._port = int(port)
        self._run(self._astart(self._bind_host, self._port))
        self._notify(f"Listening on {self._bind_host}:{self._port} ({self._transport})")

    async def _astart(self, host, port):
        ctx = session.server_context(self.identity)
        self._server = await asyncio.start_server(
            self._handle_incoming, host=host, port=port, ssl=ctx, limit=security.MAX_FRAME_BYTES
        )
        try:
            self._port = self._server.sockets[0].getsockname()[1]
        except Exception:
            pass

    def my_callsign(self, label: str = None, host: str = None, port: int = None) -> str:
        return callsign.build(
            label or self.display_name, self._transport,
            host or self._advertised_host, port or self._port, self.identity.fp_hex,
        )

    # ------------------------------------------------------------------
    async def _handle_incoming(self, reader, writer):
        peer = writer.get_extra_info("peername") or ("?", 0)
        ip = peer[0] if isinstance(peer, tuple) else "?"
        if not self._limiter.allow(f"conn:{ip}", limit=8, window_seconds=60):
            logger.warning("Rate limit: dropping connection from %s", ip)
            writer.close()
            return
        if len(self._sessions) + len(self._pending) >= self.max_sessions:
            writer.close()
            return
        try:
            nonce = os.urandom(32)
            await protocol.write_control(
                writer, "CHALLENGE",
                {"nonce": base64.b64encode(nonce).decode("ascii")})
            type_name, payload = await asyncio.wait_for(
                protocol.read_frame(reader), timeout=10)
            if type_name != "HELLO":
                writer.close()
                return
            hello = protocol.parse_control("HELLO", payload)
            if not hello.cert or not hello.sig:
                writer.close()
                return
            cfp = identity.fp_from_cert_pem(hello.cert)
            if (cfp.upper()[:32] != (hello.fp or "").upper()[:32]
                    or not identity.verify_sig(hello.cert, nonce, hello.sig)):
                logger.warning("Client authentication failed for %s", ip)
                writer.close()
                return
            fp = cfp
            sas = identity.sas(self.identity.fp_hex, fp)
            req = IncomingRequest(id=uuid.uuid4().hex, remote_fp=fp,
                                  label=security.sanitize_text(hello.display_name, 64),
                                  callsign=hello.callsign, sas=sas,
                                  reader=reader, writer=writer,
                                  capabilities=hello.capabilities)
            fut = self._loop.create_future()
            self._pending[req.id] = fut
            if self.on_incoming:
                try:
                    self.on_incoming(req)
                except Exception:
                    logger.exception("on_incoming callback failed")
            try:
                accept = await asyncio.wait_for(fut, timeout=self.accept_timeout)
            except asyncio.TimeoutError:
                accept = False
            self._pending.pop(req.id, None)

            if not accept:
                await session.reject_handshake(writer, "declined")
                self._notify(f"Rejected connection from {req.label or fp[:12]}")
                return

            # Re-dispatch the already-read HELLO into accept_handshake is not
            # possible, so build the session directly here.
            await protocol.write_control(writer, "ACCEPT", {"sas": sas})
            await protocol.write_control(writer, "HELLO", {
                "proto": "K1", "callsign": self.my_callsign(),
                "display_name": self.display_name, "fp": self.identity.fp_hex,
                "capabilities": CAPABILITIES,
            })
            sess = session.Session(reader=reader, writer=writer, remote_fp=fp,
                                   remote_label=req.label, remote_callsign=req.callsign,
                                   capabilities=req.capabilities, is_server=True)
            identity.remember_peer(fp, req.label)
            self._sessions[fp] = sess
            self._notify(f"Connected: {req.label or fp[:12]} (SAS {sas})")
            if self.on_connected:
                try:
                    self.on_connected(sess)
                except Exception:
                    logger.exception("on_connected callback failed")
            asyncio.ensure_future(self._recv_loop(sess))
        except Exception:
            logger.exception("Incoming handshake failed")
            try:
                writer.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def connect(self, call_sign_text: str, timeout: float = 15.0):
        cs = callsign.parse(call_sign_text)
        security.validate_target(cs.host, allow_private=self.allow_private,
                                 allow_loopback=self.allow_loopback)
        return self._run(self._aconnect(cs, timeout), timeout=timeout + 5)

    async def _aconnect(self, cs, timeout):
        sess = await session.connect(
            cs.host, cs.port, self.identity, self.my_callsign(),
            expected_fp=cs.fp, display_name=self.display_name,
            capabilities=CAPABILITIES, timeout=timeout,
        )
        self._sessions[sess.remote_fp] = sess
        sas = identity.sas(self.identity.fp_hex, sess.remote_fp)
        identity.remember_peer(sess.remote_fp, sess.remote_label)
        self._notify(f"Connected to {sess.remote_label or cs.label} (SAS {sas})")
        if self.on_connected:
            try:
                self.on_connected(sess)
            except Exception:
                logger.exception("on_connected callback failed")
        asyncio.ensure_future(self._recv_loop(sess))
        return sess

    async def _recv_loop(self, sess):
        try:
            while True:
                type_name, payload = await asyncio.wait_for(sess.recv(), timeout=self.idle_timeout)
                if type_name == "CHAT_MSG":
                    text = protocol.parse_control("CHAT_MSG", payload).text
                    if self.on_chat:
                        self.on_chat(sess, text)
                elif type_name == "PING":
                    await sess.send_control("PONG", {})
                elif type_name == "PONG":
                    pass
                elif type_name == "BYE":
                    break
                else:
                    logger.debug("Ignoring frame type %s (phase not enabled)", type_name)
        except asyncio.TimeoutError:
            logger.info("Session idle timeout; closing.")
        except Exception:
            logger.debug("Receive loop ended", exc_info=True)
        finally:
            self._sessions.pop(sess.remote_fp, None)
            try:
                sess.writer.close()
            except Exception:
                pass
            if self.on_disconnected:
                try:
                    self.on_disconnected(sess)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    def resolve_incoming(self, req_id: str, accept: bool):
        def _set():
            fut = self._pending.get(req_id)
            if fut and not fut.done():
                fut.set_result(bool(accept))
        self._loop.call_soon_threadsafe(_set)

    def send_chat(self, peer_fp: str, text: str):
        sess = self._sessions.get(peer_fp)
        if not sess:
            raise RuntimeError("Not connected to that peer.")
        text = security.sanitize_text(text, 8000)
        return self._run(sess.send_control("CHAT_MSG", {"text": text}))

    def sessions(self):
        return list(self._sessions.values())

    def close(self):
        try:
            for sess in list(self._sessions.values()):
                asyncio.run_coroutine_threadsafe(sess.close(), self._loop)
        except Exception:
            pass
        try:
            if self._server:
                self._loop.call_soon_threadsafe(self._server.close)
        except Exception:
            pass
        try:
            if self._loop:
                self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass