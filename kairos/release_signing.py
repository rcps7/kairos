"""Release signing and verification (Ed25519 detached signatures).

The release bundle is signed with an Ed25519 private key kept OUTSIDE the repo
(default: ``~/.kairos/release_signing_key.pem``). The matching public key is
pinned in the repository as ``kairos/release_pubkey.pem`` and shipped in every
install, so the updater can verify downloads independently of GitHub.

CLI:
    python -m kairos.release_signing sign <file> [key_path]
    python -m kairos.release_signing verify <file> <file.sig>
"""

import logging
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

logger = logging.getLogger(__name__)

PUBKEY_FILE = Path(__file__).resolve().parent / "release_pubkey.pem"
DEFAULT_KEY_FILE = Path.home() / ".kairos" / "release_signing_key.pem"


def load_public_key_pem() -> str:
    env = None
    try:
        import os
        env = os.environ.get("KAIROS_RELEASE_PUBKEY")
    except Exception:
        env = None
    if env:
        return env
    try:
        return PUBKEY_FILE.read_text(encoding="utf-8")
    except Exception:
        return ""


def sign_bytes(data: bytes, key_path=None) -> bytes:
    kp = Path(key_path) if key_path else DEFAULT_KEY_FILE
    key = serialization.load_pem_private_key(kp.read_bytes(), password=None)
    return key.sign(data)


def sign_file(path, key_path=None) -> Path:
    path = Path(path)
    sig = sign_bytes(path.read_bytes(), key_path)
    sig_path = path.with_name(path.name + ".sig")
    sig_path.write_bytes(sig)
    return sig_path


def verify_bytes(data: bytes, signature: bytes, pubkey_pem: str = None) -> bool:
    pem = pubkey_pem if pubkey_pem is not None else load_public_key_pem()
    if not (pem or "").strip():
        logger.warning("No release public key available; cannot verify signature.")
        return False
    try:
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))
        pub.verify(signature, data)
        return True
    except Exception:
        return False


def verify_file(path, sig_path, pubkey_pem: str = None) -> bool:
    try:
        return verify_bytes(Path(path).read_bytes(), Path(sig_path).read_bytes(), pubkey_pem)
    except Exception:
        return False


def generate_keypair(key_path=None) -> str:
    """Create a new keypair and return the public key PEM (private written to key_path)."""
    kp = Path(key_path) if key_path else DEFAULT_KEY_FILE
    key = Ed25519PrivateKey.generate()
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    try:
        from kairos import safety
        safety.restrict_file(str(kp))
    except Exception:
        pass
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "sign":
        key = argv[2] if len(argv) > 2 else None
        out = sign_file(argv[1], key)
        print(f"signed -> {out}")
        return 0
    if len(argv) >= 3 and argv[0] == "verify":
        ok = verify_file(argv[1], argv[2])
        print("signature OK" if ok else "signature INVALID")
        return 0 if ok else 1
    print("usage: python -m kairos.release_signing sign <file> [key_path] | verify <file> <sig>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())