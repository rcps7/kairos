"""Encrypted session establishment (TLS 1.2+/1.3) with certificate pinning.

The peer's certificate public-key fingerprint MUST match the value advertised
in the call sign, otherwise the connection is aborted. This is the core
anti-MITM control; the SAS is an additional human-verifiable check.
"""

import asyncio
import base64
import logging
import ssl
from dataclasses import dataclass, field

from . import identity, protocol

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    pass


def server_context(ident: identity.Identity) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.options |= ssl.OP_NO_COMPRESSION
    ctx.load_cert_chain(ident.cert_path, ident.key_path)
    return ctx


def client_context() -> ssl.SSLContext:
    # Verification is done by pinning the public-key fingerprint after the
    # handshake (self-signed certs have no CA chain), so disable CA/hostname
    # checks here -- but ALWAYS pin before proceeding.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.options |= ssl.OP_NO_COMPRESSION
    return ctx


def peer_fp(writer) -> str:
    ssl_obj = writer.get_extra_info("ssl_object")
    if ssl_obj is None:
        raise SecurityError("Connection is not TLS.")
    der = ssl_obj.getpeercert(binary_form=True)
    if not der:
        raise SecurityError("No peer certificate presented.")
    try:
        from datetime import datetime, timezone
        if identity.cert_not_after_utc(der) < datetime.now(timezone.utc):
            raise SecurityError("Peer certificate has expired.")
    except SecurityError:
        raise
    except Exception:
        logger.debug("Could not check peer certificate validity", exc_info=True)
    return identity.spki_fp_from_cert_der(der)


@dataclass
class Session:
    reader: object
    writer: object
    remote_fp: str
    remote_label: str = ""
    remote_callsign: str = ""
    capabilities: list = field(default_factory=list)
    is_server: bool = False

    async def send_control(self, type_name: str, obj):
        await protocol.write_control(self.writer, type_name, obj)

    async def send_binary(self, type_name: str, data: bytes):
        await protocol.write_binary(self.writer, type_name, data)

    async def recv(self):
        return await protocol.read_frame(self.reader)

    async def close(self):
        try:
            await self.send_control("BYE", {})
        except Exception:
            pass
        try:
            self.writer.close()
        except Exception:
            pass


async def connect(host: str, port: int, ident: identity.Identity, my_callsign: str,
                  expected_fp: str, display_name: str = "",
                  capabilities=None, timeout: float = 10.0) -> Session:
    """Connect to a peer and complete the handshake as the initiator."""
    ctx = client_context()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=None),
            timeout=timeout,
        )
    except Exception as e:
        raise ConnectionError(f"Could not connect to {host}:{port}: {e}") from e

    try:
        fp = peer_fp(writer)
    except SecurityError:
        writer.close()
        raise

    if fp.upper()[:32] != (expected_fp or "").upper()[:32]:
        writer.close()
        raise SecurityError(
            "Peer certificate fingerprint does not match the call sign (possible MITM)."
        )

    # Challenge-response: prove possession of our identity key.
    try:
        type_name, payload = await asyncio.wait_for(protocol.read_frame(reader), timeout)
    except Exception as e:
        writer.close()
        raise ConnectionError(f"Handshake failed: {e}") from e
    if type_name != "CHALLENGE":
        writer.close()
        raise SecurityError(f"Expected CHALLENGE, got '{type_name}'.")
    nonce = base64.b64decode(protocol.parse_control("CHALLENGE", payload).nonce)

    await protocol.write_control(writer, "HELLO", {
        "proto": "K1",
        "callsign": my_callsign,
        "display_name": display_name,
        "fp": ident.fp_hex,
        "capabilities": list(capabilities or []),
        "cert": identity.cert_pem(ident),
        "sig": identity.sign_nonce(ident, nonce),
    })

    try:
        type_name, payload = await asyncio.wait_for(protocol.read_frame(reader), timeout)
    except Exception as e:
        writer.close()
        raise ConnectionError(f"Handshake failed: {e}") from e
    if type_name == "REJECT":
        msg = protocol.parse_control("REJECT", payload).reason
        writer.close()
        raise ConnectionError(f"Peer rejected the connection: {msg}")
    if type_name != "ACCEPT":
        writer.close()
        raise SecurityError(f"Unexpected handshake message '{type_name}'.")

    # Consume the peer's HELLO (sent before ACCEPT) if present.
    try:
        type2, payload2 = await asyncio.wait_for(protocol.read_frame(reader), timeout)
        if type2 == "HELLO":
            hello = protocol.parse_control("HELLO", payload2)
            remote_label = hello.display_name
            caps = hello.capabilities
        elif type2 == "CAPS":
            caps = protocol.parse_control("CAPS", payload2).capabilities
            remote_label = ""
        else:
            remote_label, caps = "", []
    except Exception:
        remote_label, caps = "", []

    return Session(reader=reader, writer=writer, remote_fp=fp,
                   remote_label=remote_label, remote_callsign="",
                   capabilities=caps, is_server=False)


async def accept_handshake(reader, writer, ident: identity.Identity, my_callsign: str,
                           display_name: str = "", capabilities=None,
                           sas_value: str = "") -> Session:
    """Complete the handshake on the accepting (server) side and return a Session."""
    fp = peer_fp(writer)
    type_name, payload = await protocol.read_frame(reader)
    if type_name != "HELLO":
        writer.close()
        raise SecurityError(f"Expected HELLO, got '{type_name}'.")
    hello = protocol.parse_control("HELLO", payload)
    if hello.fp and hello.fp.upper()[:32] != fp.upper()[:32]:
        writer.close()
        raise SecurityError("HELLO fingerprint does not match TLS certificate.")

    await protocol.write_control(writer, "ACCEPT", {"sas": sas_value})
    await protocol.write_control(writer, "HELLO", {
        "proto": "K1", "callsign": my_callsign, "display_name": display_name,
        "fp": ident.fp_hex, "capabilities": list(capabilities or []),
    })
    return Session(reader=reader, writer=writer, remote_fp=fp,
                   remote_label=hello.display_name, remote_callsign=hello.callsign,
                   capabilities=hello.capabilities, is_server=True)


async def reject_handshake(writer, reason: str = "declined"):
    try:
        await protocol.write_control(writer, "REJECT", {"reason": reason})
    except Exception:
        pass
    try:
        writer.close()
    except Exception:
        pass