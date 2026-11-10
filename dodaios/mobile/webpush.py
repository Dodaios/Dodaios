"""Web push to a paired phone: VAPID (RFC 8292) and ``aes128gcm`` payloads (RFC 8291).

Built on ``cryptography`` only (a base dependency), so no extra package has to
install on any platform. The VAPID key pair is generated once on this machine
and kept in the app's data directory (``mobile/vapid.json``); it never leaves
it and is never part of the repository. The public key goes to the phone,
which subscribes with its browser's push service; every notification is
encrypted for that one subscription and posted to the push service's endpoint.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from dodaios.core.paths import user_data_dir

from .devices import PushSubscription

log = logging.getLogger(__name__)

#: Who the push service may contact about this sender; no real mailbox is needed.
VAPID_SUBJECT = "mailto:owner@localhost"
#: Web push limits a payload to 4096 bytes including the encryption overhead.
MAX_PAYLOAD_BYTES = 3800
_RECORD_SIZE = 4096


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class VapidKeys:
    """The sender key pair, generated on first use and kept in the data dir."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_dir() / "mobile" / "vapid.json"
        self._lock = threading.Lock()
        self._private: ec.EllipticCurvePrivateKey | None = None

    def _load(self) -> ec.EllipticCurvePrivateKey | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # no key yet: generated below
            return None
        except (ValueError, OSError):
            log.warning("mobile push: the VAPID key file is unreadable; a new key is generated")
            return None
        pem = str(raw.get("private_key_pem") or "")
        if not pem:
            return None
        try:
            key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
        except (ValueError, TypeError):
            log.warning("mobile push: the VAPID key is damaged; a new key is generated")
            return None
        return key if isinstance(key, ec.EllipticCurvePrivateKey) else None

    def _store(self, key: ec.EllipticCurvePrivateKey) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        body = json.dumps(
            {
                "private_key_pem": pem,
                "public_key": b64url(_raw_public(key.public_key())),
                "created_at": time.time(),
            },
            indent=2,
        )
        fd, name = tempfile.mkstemp(prefix=".vapid-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
            os.replace(name, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:  # Windows ACLs do not take POSIX modes; the user profile protects it
                pass
        except OSError:
            try:
                os.unlink(name)
            except OSError:  # the temp file is already gone
                pass
            raise

    def private_key(self) -> ec.EllipticCurvePrivateKey:
        with self._lock:
            if self._private is None:
                key = self._load()
                if key is None:
                    key = ec.generate_private_key(ec.SECP256R1())
                    self._store(key)
                    log.info("mobile push: generated a VAPID key pair in %s", self.path.parent)
                self._private = key
            return self._private

    def public_key_b64url(self) -> str:
        return b64url(_raw_public(self.private_key().public_key()))

    def authorization(self, endpoint: str, *, ttl_s: int = 12 * 3600) -> str:
        """The ``Authorization: vapid`` header value for one push endpoint."""
        parts = urlsplit(endpoint)
        audience = f"{parts.scheme}://{parts.netloc}"
        header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        claims = b64url(
            json.dumps(
                {"aud": audience, "exp": int(time.time()) + ttl_s, "sub": VAPID_SUBJECT},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{claims}".encode("ascii")
        der = self.private_key().sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        return f"vapid t={header}.{claims}.{signature}, k={self.public_key_b64url()}"


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt_payload(plaintext: bytes, subscription: PushSubscription) -> bytes:
    """One ``aes128gcm`` record for ``subscription`` (RFC 8291 §3, RFC 8188)."""
    if len(plaintext) > MAX_PAYLOAD_BYTES:
        raise ValueError("push payload too large")
    ua_public = b64url_decode(subscription.p256dh)
    auth_secret = b64url_decode(subscription.auth)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    as_private = ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_private.public_key())
    shared = as_private.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    record = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + struct.pack("!I", _RECORD_SIZE) + bytes([len(as_public)]) + as_public
    return header + record


_VAPID: VapidKeys | None = None
_VAPID_LOCK = threading.Lock()


def get_vapid() -> VapidKeys:
    """The process-wide sender keys (the file is read or created on first use)."""
    global _VAPID
    with _VAPID_LOCK:
        if _VAPID is None:
            _VAPID = VapidKeys()
        return _VAPID


def set_vapid(keys: VapidKeys | None) -> None:
    """Test hook: swap the process-wide keys."""
    global _VAPID
    with _VAPID_LOCK:
        _VAPID = keys


class WebPushSender:
    """Posts encrypted notifications; tells the caller when a subscription is dead."""

    def __init__(self, keys: VapidKeys | None = None, *, pool: Any | None = None) -> None:
        self.keys = keys or get_vapid()
        self._pool = pool

    def _client(self) -> Any:
        if self._pool is None:
            from dodaios.core.http_pool import HttpClientPool

            self._pool = HttpClientPool(
                timeout_s=15, client_kwargs={"follow_redirects": False, "trust_env": False}
            )
        return self._pool.client()

    async def send(
        self,
        subscription: PushSubscription,
        payload: dict[str, Any],
        *,
        ttl_s: int = 24 * 3600,
        urgency: str = "normal",
    ) -> str:
        """``"sent"``, ``"gone"`` (the phone unsubscribed) or ``"failed"``."""
        plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        body = encrypt_payload(plaintext, subscription)
        headers = {
            "Authorization": self.keys.authorization(subscription.endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(int(ttl_s)),
            "Urgency": urgency,
        }
        try:
            response = await self._client().post(
                subscription.endpoint, content=body, headers=headers
            )
        except Exception as exc:  # noqa: BLE001 — a push service outage is logged, never raised
            log.warning("mobile push: delivery failed: %s", type(exc).__name__)
            return "failed"
        if response.status_code in (404, 410):
            return "gone"
        if response.status_code >= 300:
            log.warning("mobile push: the push service answered %s", response.status_code)
            return "failed"
        return "sent"


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "VAPID_SUBJECT",
    "VapidKeys",
    "WebPushSender",
    "b64url",
    "b64url_decode",
    "encrypt_payload",
    "get_vapid",
    "set_vapid",
]
