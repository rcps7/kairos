"""Call signs: a compact, human-copyable string that encodes how to reach a
peer and the fingerprint of their identity key.

Grammar (v1):
    K1!<LABEL>!<transport>!<host>!<port>!<FP32>!<CK>

* LABEL      : 1-24 chars [A-Za-z0-9_-] (display name; never used as a path)
* transport  : direct | ts | ngrok
* host       : IPv4 / IPv6 / DNS name (<= 64 chars)
* port       : 1..65535
* FP32       : first 128 bits of SHA-256(identity SPKI), UPPERCASE hex
* CK         : 2-char base36 checksum of everything before it (typo guard)

The call sign is NOT a secret. It only ensures you connect to the peer that
owns the key it names; authenticity is established by TLS pinning plus an
out-of-band SAS comparison.
"""

import base64
import hashlib
import io
import re
from dataclasses import dataclass

from . import security

PREFIX = "K1"
TRANSPORTS = ("direct", "ts", "ngrok")
_LABEL_RE = re.compile(r"^[A-Za-z0-9_\-]{1,24}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
_FP_RE = re.compile(r"^[0-9A-F]{32}$")
_CK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class CallSignError(ValueError):
    pass


def _checksum(body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).digest()
    value = int.from_bytes(digest[:2], "big") % (36 * 36)
    return _CK_ALPHABET[value // 36] + _CK_ALPHABET[value % 36]


def fingerprint128(spki_sha256_hex: str) -> str:
    """Return the 32-char uppercase fingerprint used inside call signs."""
    return (spki_sha256_hex or "").upper()[:32]


@dataclass
class CallSign:
    label: str
    transport: str
    host: str
    port: int
    fp: str
    raw: str

    def __str__(self):
        return self.raw


def build(label: str, transport: str, host: str, port: int, spki_sha256_hex: str) -> str:
    label = security.sanitize_component(label, 24)
    if not _LABEL_RE.match(label):
        label = "KAIROS"
    if transport not in TRANSPORTS:
        raise CallSignError(f"Unknown transport '{transport}'.")
    if not _HOST_RE.match(host or ""):
        raise CallSignError("Invalid host in call sign.")
    port = int(port)
    if not (1 <= port <= 65535):
        raise CallSignError("Port out of range.")
    fp = fingerprint128(spki_sha256_hex)
    if not _FP_RE.match(fp):
        raise CallSignError("Invalid identity fingerprint.")
    body = f"{PREFIX}!{label}!{transport}!{host}!{port}!{fp}"
    sign = body + "!" + _checksum(body)
    if len(sign) > security.MAX_CALLSIGN_LEN:
        raise CallSignError("Call sign too long.")
    return sign


def parse(text: str) -> CallSign:
    text = security.sanitize_text(text, security.MAX_CALLSIGN_LEN).strip()
    if not text or len(text) > security.MAX_CALLSIGN_LEN:
        raise CallSignError("Empty or oversized call sign.")
    parts = text.split("!")
    if len(parts) != 7:
        raise CallSignError("Malformed call sign (expected 7 fields).")
    prefix, label, transport, host, port_s, fp, ck = parts
    if prefix != PREFIX:
        raise CallSignError("Unsupported call sign version.")
    if not _LABEL_RE.match(label):
        raise CallSignError("Invalid label.")
    if transport not in TRANSPORTS:
        raise CallSignError("Unknown transport.")
    if not _HOST_RE.match(host):
        raise CallSignError("Invalid host.")
    if not port_s.isdigit():
        raise CallSignError("Invalid port.")
    port = int(port_s)
    if not (1 <= port <= 65535):
        raise CallSignError("Port out of range.")
    if not _FP_RE.match(fp.upper()):
        raise CallSignError("Invalid fingerprint.")
    body = "!".join(parts[:6])
    if _checksum(body) != ck.upper():
        raise CallSignError("Checksum mismatch (typo?).")
    return CallSign(label=label, transport=transport, host=host, port=port,
                    fp=fp.upper(), raw=text)


def qr_png(call_sign: str, scale: int = 4) -> bytes:
    """Render a call sign as a PNG QR code (best-effort)."""
    try:
        import qrcode
    except Exception:
        return b""
    img = qrcode.make(call_sign)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()