"""The commit of a release, as the release key states it.

A managed install (the one-line installer's git checkout) updates by fetching
the tag of the newest release and installing the commit it points to. A tag
proves nothing about who set it: whoever can move a tag or publish a release
could point it at a commit of their own. So the updater also asks the release
key. Every release carries

* ``payload-commit.txt`` — one line, the commit the release was built from,
* ``payload-commit.txt.cosign.sig`` — the base64 of a raw Ed25519 signature
  over the exact bytes of that file,

both written by ``sign-installer.yml`` with the offline-ceremony key, whose
public half is pinned in :mod:`dodaios.core.update_manifest`. It is the key
that signs the update manifest of the native installers, and the file the
verifying installer (``install/install-verify.sh``) pins its clone to. A
managed update is installed only when the commit its tag resolved to is the one
this file names.

The file holds one git revision and nothing else. Nothing else the key signs
has that shape (the install scripts, the dependency lock, the update manifest),
so no other signature of the key can pass as a statement about a commit.

The statement of an OLDER release still verifies. That replay is the caller's
to stop: ``update_routes`` installs a commit only when the version written in
it is the version of the release being installed, and that release is newer
than the running one.

``cryptography`` and ``httpx`` are imported lazily by the modules this one
calls, so importing it costs the boot nothing (AP-26).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from dodaios.core.installer_update import (
    READ_TIMEOUT_S,
    AssetFetcher,
    HttpxAssetFetcher,
    InstallerAsset,
    InstallerUpdateError,
    select_asset,
)
from dodaios.core.update_manifest import (
    MAX_SIGNATURE_BYTES,
    UpdateManifestError,
    verify_signature,
)

__all__ = [
    "MAX_PAYLOAD_COMMIT_BYTES",
    "PAYLOAD_COMMIT_ASSET_NAME",
    "PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME",
    "ReleaseCommitError",
    "SignedCommitAssets",
    "fetch_signed_commit",
    "select_signed_commit_assets",
    "signed_commit",
]

PAYLOAD_COMMIT_ASSET_NAME = "payload-commit.txt"
PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME = "payload-commit.txt.cosign.sig"

# One revision and a line break: 41 bytes for SHA-1, 65 for SHA-256. Anything
# much larger is not what the release workflow wrote.
MAX_PAYLOAD_COMMIT_BYTES = 256

# A full git revision, as ``git rev-parse`` prints it: 40 hex digits, or 64 in
# a SHA-256 repository.
_REVISION_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

_SUBJECT = f"{PAYLOAD_COMMIT_ASSET_NAME} of this release"


class ReleaseCommitError(RuntimeError):
    """The signed commit of a release is missing, unreadable or not signed.

    The message is user-facing: the updater shows it when it refuses an update.
    """


@dataclass(frozen=True)
class SignedCommitAssets:
    """The two release assets that state the commit of one release."""

    statement: InstallerAsset
    signature: InstallerAsset


def select_signed_commit_assets(assets: Iterable[Any]) -> SignedCommitAssets | None:
    """The statement and its signature out of a release's ``assets``, or ``None``.

    ``None`` when either is absent or has no https download address: half a
    pair proves nothing.
    """
    listed = list(assets)
    statement = select_asset(listed, PAYLOAD_COMMIT_ASSET_NAME)
    signature = select_asset(listed, PAYLOAD_COMMIT_SIGNATURE_ASSET_NAME)
    if statement is None or signature is None:
        return None
    return SignedCommitAssets(statement=statement, signature=signature)


def signed_commit(
    data: bytes, signature_text: str, *, public_keys: Sequence[str] | None = None
) -> str:
    """The commit ``data`` names, once the release key's signature over it holds.

    The signature is checked first, over the exact bytes; only a statement the
    key signed is parsed at all. ``public_keys`` is ``None`` for the pinned
    release key (:data:`dodaios.core.update_manifest.PINNED_PUBLIC_KEYS`).
    """
    if len(data) > MAX_PAYLOAD_COMMIT_BYTES:
        raise ReleaseCommitError(f"{_SUBJECT} is too large to be genuine")
    try:
        verify_signature(data, signature_text, public_keys=public_keys, subject=_SUBJECT)
    except UpdateManifestError as exc:
        raise ReleaseCommitError(str(exc)) from exc
    try:
        revision = data.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseCommitError(f"{_SUBJECT} does not name a commit") from exc
    if not _REVISION_RE.fullmatch(revision):
        raise ReleaseCommitError(f"{_SUBJECT} does not name a commit")
    return revision


async def _document(active: AssetFetcher, asset: InstallerAsset, max_bytes: int) -> str:
    """Fetch one of the two small documents; every failure is the same refusal."""
    try:
        return await asyncio.wait_for(
            active.get_text(asset.url, max_bytes=max_bytes), timeout=READ_TIMEOUT_S
        )
    except InstallerUpdateError as exc:
        # An oversized body or a hop that left https: the fetcher refused it.
        raise ReleaseCommitError(f"{asset.name}: {exc}") from exc
    except TimeoutError as exc:
        raise ReleaseCommitError(
            f"{asset.name} did not arrive within {READ_TIMEOUT_S:.0f}s"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — every transport error is the same refusal
        raise ReleaseCommitError(f"could not download {asset.name}: {exc}") from exc


async def fetch_signed_commit(
    assets: SignedCommitAssets,
    *,
    fetcher: AssetFetcher | None = None,
    public_keys: Sequence[str] | None = None,
) -> str:
    """Download the statement and its signature and return the signed commit.

    Both travel over the updater's own fetcher: https on every hop, and a size
    cap applied while the body streams in. Raises :class:`ReleaseCommitError`
    on every failure; nothing is returned that the release key did not sign.
    """
    active = HttpxAssetFetcher() if fetcher is None else fetcher
    statement = await _document(active, assets.statement, MAX_PAYLOAD_COMMIT_BYTES)
    signature = await _document(active, assets.signature, MAX_SIGNATURE_BYTES)
    # Both documents are ASCII as published, so the text round trip returns
    # their exact bytes; anything else fails the signature check.
    return signed_commit(statement.encode("utf-8"), signature, public_keys=public_keys)
