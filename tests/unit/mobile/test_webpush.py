"""VAPID keys stay in the data dir; payloads decrypt with the subscription's keys."""

from __future__ import annotations

import base64
import json
import struct

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from dodaios.core.http_pool import HttpClientPool
from dodaios.mobile.devices import PushSubscription
from dodaios.mobile.webpush import (
    VapidKeys,
    WebPushSender,
    b64url,
    b64url_decode,
    encrypt_payload,
)


def _phone_subscription() -> tuple[PushSubscription, ec.EllipticCurvePrivateKey, bytes]:
    """What a browser would hand the page: its P-256 key and a 16-byte auth secret."""
    ua_private = ec.generate_private_key(ec.SECP256R1())
    ua_public = ua_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = b"\x01" * 16
    return (
        PushSubscription(
            endpoint="https://push.example.test/send/abc",
            p256dh=b64url(ua_public),
            auth=b64url(auth),
        ),
        ua_private,
        auth,
    )


def _decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
    salt, rs, idlen = body[:16], struct.unpack("!I", body[16:20])[0], body[20]
    as_public = body[21 : 21 + idlen]
    ciphertext = body[21 + idlen :]
    assert rs == 4096
    as_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    shared = ua_private.exchange(ec.ECDH(), as_key)
    ua_public = ua_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )

    def hkdf(s: bytes, ikm: bytes, info: bytes, n: int) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=n, salt=s, info=info).derive(ikm)

    ikm = hkdf(auth, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_payload_round_trips_with_the_phone_keys() -> None:
    subscription, ua_private, auth = _phone_subscription()
    body = encrypt_payload(b'{"title":"hi"}', subscription)
    assert _decrypt(body, ua_private, auth) == b'{"title":"hi"}'
    # Two encryptions of the same text never look alike (fresh salt and sender key).
    assert body != encrypt_payload(b'{"title":"hi"}', subscription)


def test_payload_size_is_bounded() -> None:
    subscription, _ua, _auth = _phone_subscription()
    with pytest.raises(ValueError):
        encrypt_payload(b"x" * 5000, subscription)


def test_vapid_keys_persist_in_the_data_dir_and_sign_valid_jwts(tmp_path) -> None:
    keys = VapidKeys(tmp_path / "mobile" / "vapid.json")
    public = keys.public_key_b64url()
    assert len(b64url_decode(public)) == 65
    saved = json.loads(keys.path.read_text(encoding="utf-8"))
    assert saved["public_key"] == public and "PRIVATE KEY" in saved["private_key_pem"]
    # A new instance reads the same key instead of generating another.
    assert VapidKeys(keys.path).public_key_b64url() == public

    header = keys.authorization("https://push.example.test/send/abc")
    assert header.startswith("vapid t=") and f", k={public}" in header
    token = header[len("vapid t=") :].split(",")[0]
    h, c, s = token.split(".")
    claims = json.loads(b64url_decode(c))
    assert claims["aud"] == "https://push.example.test" and claims["sub"].startswith("mailto:")
    assert json.loads(b64url_decode(h)) == {"typ": "JWT", "alg": "ES256"}
    raw = b64url_decode(s)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(public))
    verifier.verify(der, f"{h}.{c}".encode("ascii"), ec.ECDSA(hashes.SHA256()))


def test_damaged_key_file_is_replaced(tmp_path) -> None:
    path = tmp_path / "vapid.json"
    path.write_text("{not json", encoding="utf-8")
    keys = VapidKeys(path)
    assert keys.public_key_b64url()
    assert json.loads(path.read_text(encoding="utf-8"))["public_key"]


@pytest.mark.asyncio
async def test_sender_reports_sent_gone_and_failed(tmp_path) -> None:
    subscription, ua_private, auth = _phone_subscription()
    seen: list[httpx.Request] = []
    status = {"code": 201}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status["code"])

    pool = HttpClientPool(transport=httpx.MockTransport(handler))
    sender = WebPushSender(VapidKeys(tmp_path / "vapid.json"), pool=pool)
    assert await sender.send(subscription, {"title": "t", "body": "b"}, urgency="high") == "sent"
    request = seen[0]
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["authorization"].startswith("vapid t=")
    assert request.headers["urgency"] == "high" and request.headers["ttl"] == "86400"
    assert json.loads(_decrypt(request.content, ua_private, auth)) == {"title": "t", "body": "b"}
    status["code"] = 410
    assert await sender.send(subscription, {"title": "t"}) == "gone"
    status["code"] = 500
    assert await sender.send(subscription, {"title": "t"}) == "failed"
    await pool.aclose()


def test_b64url_helpers_round_trip() -> None:
    raw = base64.b64decode("AAEC/w==")
    assert b64url_decode(b64url(raw)) == raw
