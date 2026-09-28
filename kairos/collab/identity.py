"""Local identity for peer collaboration.

Generates and stores an EC P-256 key + self-signed certificate once, derives a
stable SHA-256 fingerprint of the public key (used in call signs, TLS pinning
and the SAS), and manages a trust store of accepted peers.

Private material is written under ``~/.kairos/identity`` with a restricted ACL.
"""

import base64
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import security

logger = logging.getLogger(__name__)

DEFAULT_IDENTITY_DIR = Path.home() / ".kairos" / "identity"
PEERS_FILE = Path.home() / ".kairos" / "peers.json"

_lock = threading.Lock()
_cache = {}


def identity_dir(directory=None) -> Path:
    if directory:
        return Path(directory)
    env = os.environ.get("KAIROS_IDENTITY_DIR")
    if env:
        return Path(env)
    return DEFAULT_IDENTITY_DIR


def _paths(directory=None):
    d = identity_dir(directory)
    return d, d / "cert.pem", d / "key.pem", d / "identity.json"


@dataclass
class Identity:
    label: str
    fp_hex: str          # full 64-char SHA-256 of SPKI
    cert_path: str
    key_path: str

    @property
    def fp(self) -> str:
        return self.fp_hex


def _spki_sha256(public_key) -> str:
    from cryptography.hazmat.primitives import serialization
    der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def spki_fp_from_cert_der(der: bytes) -> str:
    from cryptography import x509
    cert = x509.load_der_x509_certificate(der)
    return _spki_sha256(cert.public_key())


def cert_not_after_utc(der: bytes):
    from cryptography import x509
    return x509.load_der_x509_certificate(der).not_valid_after_utc


def _generate(label: str, directory=None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    d, cert_file, key_file, _ = _paths(directory)
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Kairos Peer")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    d.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    security.restrict_acl(str(d))
    security.restrict_acl(str(key_file))
    return key.public_key()


def load_identity(label: str = "", force_new: bool = False, directory=None) -> Identity:
    """Load (or create) the local identity for the given directory."""
    d, cert_file, key_file, meta_file = _paths(directory)
    key = str(d)
    with _lock:
        if _cache.get(key) is not None and not force_new:
            return _cache[key]

        need = force_new or not (cert_file.exists() and key_file.exists())
        if need:
            pub = _generate(label, directory)
        else:
            from cryptography import x509
            cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
            pub = cert.public_key()

        fp = _spki_sha256(pub)
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        if label:
            meta["label"] = security.sanitize_component(label, 24)
        meta.setdefault("label", "KAIROS")
        meta["fp"] = fp
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        security.restrict_acl(str(meta_file))

        _cache[key] = Identity(label=meta["label"], fp_hex=fp,
                               cert_path=str(cert_file), key_path=str(key_file))
        return _cache[key]


def rotate(label: str = "", directory=None) -> Identity:
    """Generate a brand-new identity (invalidates existing call signs)."""
    return load_identity(label, force_new=True, directory=directory)


def sas(fp_a: str, fp_b: str) -> str:
    lo, hi = sorted([(fp_a or "").upper(), (fp_b or "").upper()])
    digest = hashlib.sha256((lo + "|" + hi).encode("ascii")).digest()
    value = int.from_bytes(digest[:4], "big") % 1_000_000
    return f"{value:06d}"


# ---------------------------------------------------------------------------
# Certificate helpers + challenge-response (client auth without mutual TLS)
# ---------------------------------------------------------------------------
def cert_pem(ident: "Identity") -> str:
    from pathlib import Path
    return Path(ident.cert_path).read_text(encoding="utf-8")


def fp_from_cert_pem(cert_pem_str: str) -> str:
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(cert_pem_str.encode("utf-8"))
    return _spki_sha256(cert.public_key())


def sign_nonce(ident: "Identity", nonce: bytes) -> str:
    from pathlib import Path
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = serialization.load_pem_private_key(Path(ident.key_path).read_bytes(), password=None)
    sig = key.sign(nonce, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode("ascii")


def verify_sig(cert_pem_str: str, nonce: bytes, sig_b64: str) -> bool:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        cert = x509.load_pem_x509_certificate(cert_pem_str.encode("utf-8"))
        pub = cert.public_key()
        pub.verify(base64.b64decode(sig_b64), nonce, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Trust store
# ---------------------------------------------------------------------------
def load_peers() -> dict:
    if PEERS_FILE.exists():
        try:
            return json.loads(PEERS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_peers(peers: dict):
    PEERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PEERS_FILE.write_text(json.dumps(peers, indent=2), encoding="utf-8")


def remember_peer(fp: str, label: str):
    peers = load_peers()
    peers[fp.upper()] = {"label": security.sanitize_component(label, 24),
                         "added": datetime.now(timezone.utc).isoformat()}
    save_peers(peers)


def is_known_peer(fp: str) -> bool:
    return fp.upper() in load_peers()


def forget_peer(fp: str):
    peers = load_peers()
    peers.pop(fp.upper(), None)
    save_peers(peers)