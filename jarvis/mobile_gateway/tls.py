"""The gateway's self-signed certificate, which the phone pins by fingerprint.

No certificate authority vouches for it: the phone learns the SHA-256 of the
certificate from the pairing QR code and accepts that certificate only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

CERT_NAME = "gateway-cert.pem"
KEY_NAME = "gateway-key.pem"
_VALID_DAYS = 3650


def ensure_certificate(data_dir: Path) -> tuple[Path, Path]:
    """Return ``(cert, key)``, creating a fresh pair the first time."""
    data_dir.mkdir(parents=True, exist_ok=True)
    cert_path = data_dir / CERT_NAME
    key_path = data_dir / KEY_NAME
    if cert_path.is_file() and key_path.is_file():
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Dodaios Mobile Gateway")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key_bytes)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def fingerprint(cert_path: Path) -> str:
    """Lower-case hex SHA-256 of the certificate's DER encoding."""
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
