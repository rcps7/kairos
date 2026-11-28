#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# KAIROS for Android — Developed by RC.
#
# Create a PKCS#12 release keystore for signing the APKs, without needing a JDK
# (uses `cryptography`). Prints the values to store as GitHub Actions secrets:
#
#   KAIROS_KEYSTORE_BASE64   (the base64 of the .p12 file)
#   KAIROS_KEYSTORE_PASSWORD
#   KAIROS_KEY_ALIAS
#   KAIROS_KEY_PASSWORD
#
# Usage:  python android/scripts/make_keystore.py [output.p12]
# The keystore and password are written next to the output file as CREDENTIALS.txt.
# KEEP THEM SECRET and never commit them.

import base64
import datetime
import os
import secrets
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    sys.exit("Install 'cryptography' first:  pip install cryptography")

ALIAS = "kairos"


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "kairos-release.p12").resolve()
    password = secrets.token_urlsafe(28)

    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "RC"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Kairos"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Android Release"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=27 * 365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))

    blob = pkcs12.serialize_key_and_certificates(
        ALIAS.encode(), key, cert, None,
        serialization.BestAvailableEncryption(password.encode()))
    out.write_bytes(blob)

    out.with_name(out.name + ".b64").write_text(base64.b64encode(blob).decode())
    out.with_name("CREDENTIALS.txt").write_text(
        "Kairos Android release keystore\n"
        f"file:          {out}\n"
        f"keyAlias:      {ALIAS}\n"
        f"storePassword: {password}\n"
        f"keyPassword:   {password}\n"
        f"cert SHA-256:  {cert.fingerprint(hashes.SHA256()).hex()}\n"
        "KEEP SECRET. Never commit. If leaked, rotate the key and re-publish.\n")

    print(f"keystore:      {out}")
    print(f"keyAlias:      {ALIAS}")
    print(f"storePassword: {password}")
    print(f"keyPassword:   {password}")
    print(f"cert SHA-256:  {cert.fingerprint(hashes.SHA256()).hex()}")
    print("\nAdd these as GitHub Actions secrets (Settings -> Secrets and variables -> Actions):")
    print("  KAIROS_KEYSTORE_BASE64 = contents of " + str(out.with_name(out.name + ".b64")))
    print(f"  KAIROS_KEYSTORE_PASSWORD = {password}")
    print(f"  KAIROS_KEY_ALIAS = {ALIAS}")
    print(f"  KAIROS_KEY_PASSWORD = {password}")
    print("\nOr, with the GitHub CLI:")
    print(f"  gh secret set KAIROS_KEYSTORE_BASE64 < \"{out.with_name(out.name + '.b64')}\"")
    print(f"  gh secret set KAIROS_KEYSTORE_PASSWORD -b \"{password}\"")
    print(f"  gh secret set KAIROS_KEY_ALIAS -b \"{ALIAS}\"")
    print(f"  gh secret set KAIROS_KEY_PASSWORD -b \"{password}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
