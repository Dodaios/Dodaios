"""The signed, version-bound update manifest the in-app updater trusts.

A release's ``installers-SHA256SUMS.txt`` proves which bytes each installer
must have, but on its own it proves nothing about WHO wrote it: anyone able to
replace release assets could replace the installer and its checksum line
together. So every release built by ``desktop-installers.yml`` also carries

* ``installers-update-manifest.json`` — a small JSON document that names the
  release version and tag and the SHA-256 of that release's checksum manifest,
* ``installers-update-manifest.json.sig`` — the base64 of a raw Ed25519
  signature over the exact manifest bytes.

The signature is made in the release workflow with the offline-ceremony
Ed25519 key, whose private half lives only in the ``WAVE2_OFFLINE_KEY_B64``
secret of the ``release-signing`` environment (AP-29; only ``v*`` tag runs can
read it). Its public half is pinned below and is the same key published as
``install/keys/offline-ceremony.pub`` (a test keeps the two identical). The
``schema`` field separates these signatures from the ones that key makes over
the install scripts: a signature over a manifest can never be passed off as one
over a script, and the reverse fails to parse as a manifest.

The version binding is what stops a replay: a validly signed manifest of an
OLDER release (with its older, perhaps vulnerable installers) cannot be served
as a newer one, because the updater compares the signed version with the
release it is installing.

Pure functions, no network. ``cryptography`` is imported lazily: it is a base
dependency, but this module sits on the updater's import path and must not cost
the boot anything (AP-26).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "MANIFEST_SCHEMA",
    "MAX_MANIFEST_BYTES",
    "MAX_SIGNATURE_BYTES",
    "PINNED_PUBLIC_KEYS",
    "UPDATE_MANIFEST_ASSET_NAME",
    "UPDATE_MANIFEST_SIGNATURE_ASSET_NAME",
    "UpdateManifest",
    "UpdateManifestError",
    "build_manifest",
    "normalize_version",
    "parse_manifest",
    "verify_signature",
    "verify_update_manifest",
]

UPDATE_MANIFEST_ASSET_NAME = "installers-update-manifest.json"
UPDATE_MANIFEST_SIGNATURE_ASSET_NAME = "installers-update-manifest.json.sig"

#: Identifies what the signature is about. Changing the document's shape means
#: a new schema string, never a silent reinterpretation of the old one.
MANIFEST_SCHEMA = "dodaios-update-manifest/1"

# The manifest is a few hundred bytes and the signature 88 characters; anything
# much larger is not what the release workflow wrote.
MAX_MANIFEST_BYTES = 16_000
MAX_SIGNATURE_BYTES = 1_000

#: Ed25519 public keys allowed to sign an update manifest, as base64 of the DER
#: SubjectPublicKeyInfo (the body of the ``PUBLIC KEY`` PEM). Rotating the key
#: means shipping the NEW key here in one release while the old one still signs,
#: and switching the release workflow only after that release is out — an
#: install that does not know the signing key refuses every update.
PINNED_PUBLIC_KEYS: tuple[str, ...] = (
    # install/keys/offline-ceremony.pub
    "MCowBQYDK2VwAyEArlfig3ALFBrED+VrNZ8hlrVnRJxDnI8PCkxGB26N4U4=",
)

_SHA256_HEX_LENGTH = 64
_ED25519_SIGNATURE_LENGTH = 64


class UpdateManifestError(ValueError):
    """The update manifest is missing, malformed, unsigned or for another release.

    The message is user-facing: the updater shows it when it refuses an update.
    """


@dataclass(frozen=True)
class UpdateManifest:
    """The fields of a parsed, structurally valid update manifest."""

    version: str
    tag: str
    checksums_sha256: str


def normalize_version(value: str) -> str:
    """A version or tag reduced to the bare version (``v4.2.0`` -> ``4.2.0``)."""
    text = str(value).strip()
    return text[1:] if text[:1] in {"v", "V"} else text


def build_manifest(*, version: str, tag: str, checksums: bytes) -> bytes:
    """The exact manifest bytes the release workflow signs.

    Canonical JSON (sorted keys, no whitespace, ASCII only) so the same inputs
    always give the same bytes, and a text transport cannot alter them.
    """
    bare = normalize_version(version)
    if not bare or normalize_version(tag) != bare:
        raise UpdateManifestError(f"tag {tag!r} does not match version {version!r}")
    document = {
        "schema": MANIFEST_SCHEMA,
        "version": bare,
        "tag": tag,
        "checksums_sha256": hashlib.sha256(checksums).hexdigest(),
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def parse_manifest(data: bytes) -> UpdateManifest:
    """Parse manifest bytes; raise :class:`UpdateManifestError` on any defect."""
    if len(data) > MAX_MANIFEST_BYTES:
        raise UpdateManifestError("the update manifest is too large to be genuine")
    try:
        document: Any = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateManifestError(f"the update manifest is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise UpdateManifestError("the update manifest is not a JSON object")
    if document.get("schema") != MANIFEST_SCHEMA:
        raise UpdateManifestError(
            f"the update manifest has an unknown schema {document.get('schema')!r}"
        )
    version = document.get("version")
    tag = document.get("tag")
    digest = document.get("checksums_sha256")
    if not isinstance(version, str) or not version:
        raise UpdateManifestError("the update manifest names no version")
    if not isinstance(tag, str) or normalize_version(tag) != version:
        raise UpdateManifestError("the update manifest's tag does not match its version")
    if (
        not isinstance(digest, str)
        or len(digest) != _SHA256_HEX_LENGTH
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise UpdateManifestError("the update manifest carries no valid checksum digest")
    return UpdateManifest(version=version, tag=tag, checksums_sha256=digest)


def _decode_signature(signature_text: str) -> bytes:
    text = signature_text.strip()
    if len(text) > MAX_SIGNATURE_BYTES:
        raise UpdateManifestError("the update manifest signature is too large to be genuine")
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UpdateManifestError("the update manifest signature is not base64") from exc
    if len(raw) != _ED25519_SIGNATURE_LENGTH:
        raise UpdateManifestError("the update manifest signature is not an Ed25519 signature")
    return raw


def verify_signature(
    data: bytes, signature_text: str, *, public_keys: Sequence[str] | None = None
) -> None:
    """Prove ``data`` was signed by one of ``public_keys``. Fail closed.

    ``None`` means :data:`PINNED_PUBLIC_KEYS`, read at call time.
    """
    if public_keys is None:
        public_keys = PINNED_PUBLIC_KEYS
    raw_signature = _decode_signature(signature_text)
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_der_public_key
    except ImportError as exc:  # pragma: no cover - cryptography is a base dependency
        raise UpdateManifestError(
            "this install cannot check update signatures (cryptography is missing) — "
            "reinstall Dodaios from the download page"
        ) from exc

    for encoded in public_keys:
        key = load_der_public_key(base64.b64decode(encoded))
        if not isinstance(key, Ed25519PublicKey):
            raise UpdateManifestError("a pinned update key is not an Ed25519 key")
        try:
            key.verify(raw_signature, data)
        except InvalidSignature:
            # Not this key; during a rotation another pinned key may have
            # signed. No key matching is reported below.
            continue
        return
    raise UpdateManifestError(
        "the update manifest is not signed by the Dodaios release key — "
        "refusing to install this update"
    )


def verify_update_manifest(
    data: bytes,
    signature_text: str,
    *,
    checksums: bytes,
    expected_version: str,
    public_keys: Sequence[str] | None = None,
) -> UpdateManifest:
    """Verify signature, version binding and checksum binding, in that order.

    ``checksums`` are the exact bytes of the release's checksum manifest that
    the installer will be verified against; ``expected_version`` is the version
    of the release being installed. Returns the manifest when all three hold.
    """
    verify_signature(data, signature_text, public_keys=public_keys)
    manifest = parse_manifest(data)
    expected = normalize_version(expected_version)
    if manifest.version != expected:
        raise UpdateManifestError(
            f"the signed update manifest is for version {manifest.version}, "
            f"not {expected} — refusing a replayed release"
        )
    if hashlib.sha256(checksums).hexdigest() != manifest.checksums_sha256:
        raise UpdateManifestError(
            "the checksum manifest of this release is not the one the release key signed"
        )
    return manifest
