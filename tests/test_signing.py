"""Signed-release tests (Ed25519 detached signatures)."""

import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from kairos import release_signing as rs


def test_ephemeral_keypair_sign_verify():
    d = Path(tempfile.mkdtemp())
    pem = rs.generate_keypair(str(d / "key.pem"))
    f = d / "payload.bin"
    f.write_bytes(b"hello kairos")
    sig_path = rs.sign_file(f, str(d / "key.pem"))
    assert rs.verify_bytes(f.read_bytes(), sig_path.read_bytes(), pem) is True
    assert rs.verify_bytes(b"tampered", sig_path.read_bytes(), pem) is False


def test_pinned_public_key_present_and_valid():
    pem = rs.load_public_key_pem()
    assert "BEGIN PUBLIC KEY" in pem
    serialization.load_pem_public_key(pem.encode("utf-8"))  # must parse
