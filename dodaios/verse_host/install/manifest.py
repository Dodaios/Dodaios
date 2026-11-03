"""The signed per-platform Verse release manifest (WP22.5, WP22.8).

Every release that carries the Verse publishes, per platform, next to the
installers but never inside them:

    Verse-<Platform>-<version>.tar                 the full package
    Verse-<Platform>-<old>-to-<new>.delta.tar      changed chunks since <old>
    verse-<Platform>-manifest.json                 this document
    verse-<Platform>-manifest.json.sig             Ed25519 signature over it

The manifest names the version, the platform, the full package's size and
SHA-256, the unpacked size, the digest of the package's file list and every
delta. It is canonical JSON (sorted keys, no whitespace, ASCII), signed by
the same release key and with the same ``openssl pkeyutl -sign -rawin`` step
as the installers' update manifest, and checked against the keys pinned in
:mod:`dodaios.core.update_manifest`. Nothing is downloaded before the
signature verifies, and nothing is installed whose SHA-256 differs from the
signed one.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from dodaios.verse_host.install.layout import VerseInstallError, check_version

__all__ = [
    "MAX_RELEASE_MANIFEST_BYTES",
    "RELEASE_SCHEMA",
    "PackageRef",
    "ReleaseManifest",
    "build_release_manifest",
    "delta_asset_name",
    "full_asset_name",
    "manifest_asset_name",
    "parse_release_manifest",
    "signature_asset_name",
    "verify_release_manifest",
]

RELEASE_SCHEMA = "verse.release/1"
MAX_RELEASE_MANIFEST_BYTES = 64_000
_HEX = frozenset("0123456789abcdef")


def full_asset_name(platform: str, version: str) -> str:
    return f"Verse-{platform}-{check_version(version)}.tar"


def delta_asset_name(platform: str, old: str, new: str) -> str:
    return f"Verse-{platform}-{check_version(old)}-to-{check_version(new)}.delta.tar"


def manifest_asset_name(platform: str) -> str:
    return f"verse-{platform}-manifest.json"


def signature_asset_name(platform: str) -> str:
    return f"{manifest_asset_name(platform)}.sig"


@dataclass(frozen=True)
class PackageRef:
    """One downloadable package the manifest vouches for."""

    name: str
    size: int
    sha256: str
    from_version: str | None = None  # deltas only
    from_tree_sha256: str | None = None  # deltas only

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "size": self.size, "sha256": self.sha256}
        if self.from_version is not None:
            data["from"] = self.from_version
            data["from_tree_sha256"] = self.from_tree_sha256
        return data


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    tag: str
    platform: str
    entry: str | None
    install_bytes: int
    tree_sha256: str
    full: PackageRef
    deltas: tuple[PackageRef, ...] = field(default=())

    def delta_from(self, version: str | None) -> PackageRef | None:
        for delta in self.deltas:
            if version is not None and delta.from_version == version:
                return delta
        return None

    def expected(self) -> dict[str, Any]:
        """What an installed package must match (``payload.install_full(expected=)``)."""
        return {"version": self.version, "platform": self.platform, "tree_sha256": self.tree_sha256}

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tag": self.tag,
            "platform": self.platform,
            "entry": self.entry,
            "install_bytes": self.install_bytes,
            "download_bytes": self.full.size,
            "full": self.full.as_dict(),
            "deltas": [d.as_dict() for d in self.deltas],
        }


def _digest(value: Any, what: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(c not in _HEX for c in text):
        raise VerseInstallError(f"the Verse manifest has no valid SHA-256 for {what}")
    return text


def _size(value: Any, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise VerseInstallError(f"the Verse manifest has no valid size for {what}")
    return value


def build_release_manifest(
    *,
    version: str,
    tag: str,
    platform: str,
    entry: str | None,
    install_bytes: int,
    tree_sha256: str,
    full: dict[str, Any],
    deltas: Sequence[dict[str, Any]] = (),
) -> bytes:
    """The exact bytes the release workflow signs (canonical JSON, ASCII)."""
    bare = check_version(version)
    if check_version(tag) != bare:
        raise VerseInstallError(f"tag {tag!r} does not match version {version!r}")
    document = {
        "schema": RELEASE_SCHEMA,
        "version": bare,
        "tag": tag,
        "platform": platform,
        "entry": entry,
        "install_bytes": install_bytes,
        "tree_sha256": tree_sha256,
        "full": full,
        "deltas": sorted(deltas, key=lambda d: str(d.get("from"))),
    }
    data = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    parse_release_manifest(data.encode("ascii"))  # never sign what the app would refuse
    return data.encode("ascii")


def _ref(raw: Any, what: str, *, delta: bool) -> PackageRef:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"]:
        raise VerseInstallError(f"the Verse manifest has a bad {what} entry")
    name = raw["name"]
    if "/" in name or "\\" in name or name.startswith("."):
        raise VerseInstallError(f"the Verse manifest names an unsafe file {name!r}")
    return PackageRef(
        name=name,
        size=_size(raw.get("size"), name),
        sha256=_digest(raw.get("sha256"), name),
        from_version=check_version(raw.get("from")) if delta else None,
        from_tree_sha256=_digest(raw.get("from_tree_sha256"), name) if delta else None,
    )


def parse_release_manifest(data: bytes) -> ReleaseManifest:
    """Parse manifest bytes; raise :class:`VerseInstallError` on any defect."""
    if len(data) > MAX_RELEASE_MANIFEST_BYTES:
        raise VerseInstallError("the Verse manifest is too large to be genuine")
    try:
        document: Any = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise VerseInstallError(f"the Verse manifest is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema") != RELEASE_SCHEMA:
        raise VerseInstallError("the Verse manifest has an unknown schema")
    version = check_version(document.get("version"))
    tag = document.get("tag")
    if not isinstance(tag, str) or check_version(tag) != version:
        raise VerseInstallError("the Verse manifest's tag does not match its version")
    platform = document.get("platform")
    if not isinstance(platform, str) or not platform:
        raise VerseInstallError("the Verse manifest names no platform")
    entry = document.get("entry")
    if entry is not None and (not isinstance(entry, str) or not entry):
        raise VerseInstallError("the Verse manifest has a bad entry")
    full = _ref(document.get("full"), "full package", delta=False)
    if full.name != full_asset_name(platform, version):
        raise VerseInstallError(f"the Verse manifest's full package is misnamed: {full.name}")
    raw_deltas = document.get("deltas", [])
    if not isinstance(raw_deltas, list):
        raise VerseInstallError("the Verse manifest's delta list is not a list")
    deltas = tuple(_ref(item, "delta", delta=True) for item in raw_deltas)
    for delta in deltas:
        assert delta.from_version is not None
        if delta.name != delta_asset_name(platform, delta.from_version, version):
            raise VerseInstallError(f"the Verse manifest's delta is misnamed: {delta.name}")
    return ReleaseManifest(
        version=version,
        tag=tag,
        platform=platform,
        entry=entry,
        install_bytes=_size(document.get("install_bytes"), "the unpacked Verse"),
        tree_sha256=_digest(document.get("tree_sha256"), "the file list"),
        full=full,
        deltas=deltas,
    )


def verify_release_manifest(
    data: bytes,
    signature_text: str,
    *,
    platform: str,
    tag: str | None = None,
    public_keys: Sequence[str] | None = None,
) -> ReleaseManifest:
    """Signature first, then shape, platform and the release it was found on. Fail closed."""
    from dodaios.core.update_manifest import UpdateManifestError, verify_signature

    try:
        verify_signature(data, signature_text, public_keys=public_keys)
    except UpdateManifestError as exc:
        raise VerseInstallError(
            f"the Verse package is not signed by the Dodaios release key — refusing it ({exc})"
        ) from exc
    manifest = parse_release_manifest(data)
    if manifest.platform != platform:
        raise VerseInstallError(
            f"the signed Verse manifest is for {manifest.platform}, this machine needs {platform}"
        )
    if tag is not None and check_version(tag) != manifest.version:
        raise VerseInstallError(
            f"the signed Verse manifest is for {manifest.tag}, found on {tag} — refusing a replay"
        )
    return manifest
