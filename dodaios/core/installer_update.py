"""Self-update for a FROZEN install — the one that arrived as a native installer.

A frozen install (Windows ``Setup.exe``, macOS ``.dmg``, Linux ``.AppImage``)
has no git checkout, so ``dodaios/ui/web/update_routes.py``'s managed path cannot
update it. What it does have is a GitHub Release carrying one installer asset
per platform plus a ``installers-SHA256SUMS.txt`` manifest:

* ``Dodaios-Setup-x64.exe``          Windows 10/11 x64
* ``Dodaios-macOS-arm64.dmg``        Apple Silicon
* ``Dodaios-macOS-x64.dmg``          Intel Mac
* ``Dodaios-Linux-x86_64.AppImage``  Linux x86_64

Releases publish each file a second time, with identical bytes, under the
earlier ``PersonalJarvis-`` prefix, which is the only one older installs know;
releases from before the rename carry only that prefix.
:data:`INSTALLER_ASSET_NAMES` lists every accepted name per platform.

This module resolves which of those belongs to the running machine, downloads
it, proves it byte-for-byte against the checksum manifest of the SAME release,
and then hands control to the platform's own upgrade mechanism.

Two rules run through everything here:

* **Fail closed.** A missing asset, a missing or unparsable checksum manifest, a
  digest that does not match, an oversized body, an unexpected redirect target —
  every one of them raises :class:`InstallerUpdateError` and installs nothing.
  Executing an unverified binary is the single worst thing an updater can do.
* **Injectable edges.** Network and process spawning arrive as small protocols
  (:class:`AssetFetcher`, :class:`CommandRunner`), so the whole flow — including
  the macOS and Linux handovers — is exercised on any OS with fakes and without
  a network.

Every subprocess goes out with ``NO_WINDOW_CREATIONFLAGS`` (AP-1) so a windowed
build never flashes a console.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import platform as platform_module
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from dodaios.core.branding import (
    LEGACY_MACOS_APP_DIR_NAMES,
    MACOS_APP_DIR_NAME,
    MACOS_APP_DIR_NAMES,
    MACOS_BUNDLE_ID,
    MACOS_DMG_BUNDLE_ID,
    UPDATER_USER_AGENT,
)
from dodaios.core.frozen import bundle_root, is_frozen
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS
from dodaios.core.update_manifest import (
    MAX_MANIFEST_BYTES,
    MAX_SIGNATURE_BYTES,
    UPDATE_MANIFEST_ASSET_NAME,
    UpdateManifestError,
    verify_update_manifest,
)

log = logging.getLogger(__name__)

__all__ = [
    "CHECKSUMS_ASSET_NAME",
    "INSTALLER_ASSET_NAMES",
    "AssetFetcher",
    "CommandRunner",
    "DownloadProgress",
    "HttpxAssetFetcher",
    "InstallerAsset",
    "InstallerUpdateError",
    "SignedManifestAssets",
    "UpdateBlocker",
    "SubprocessCommandRunner",
    "apply_installer",
    "download_and_verify",
    "handover_env",
    "installer_asset_name",
    "installer_asset_names",
    "machine_for_update",
    "parse_sha256sums",
    "select_asset",
    "select_installer_asset",
    "select_installer_assets",
    "sweep_stale_downloads",
    "update_blocker",
    "VerseUpdateError",
    "VerseUpdatePlan",
    "apply_verse_delta",
    "build_verse_tree",
    "download_verse_payload",
    "ensure_verse_healthy",
    "install_verse_full",
    "rollback_verse",
    "seed_verse_from_bundle",
    "select_verse_update",
    "update_verse",
    "verse_current",
    "verse_root",
    "verify_verse_tree",
]

# The checksum manifest published alongside the installers. Its lines are plain
# ``sha256sum`` output, so `sha256sum -c` verifies the same file by hand.
CHECKSUMS_ASSET_NAME = "installers-SHA256SUMS.txt"

# A whole onedir bundle compresses to a few hundred MB, and the installer also
# carries the Unreal Verse payload (at most 2 GB compressed at parity,
# docs/verse/unreal/architecture.md 7). The cap exists to stop a hostile or
# broken endpoint from filling the disk, not to be a tight budget.
MAX_INSTALLER_BYTES = 4_000_000_000
# The manifest is a handful of lines; anything larger is not the manifest.
MAX_CHECKSUMS_BYTES = 256_000

# Whole-download budget. Generous on purpose: a 2.5 GB installer over a slow
# connection is normal, a download that never ends is not.
DOWNLOAD_TIMEOUT_S = 3 * 3600.0
CONNECT_TIMEOUT_S = 15.0
READ_TIMEOUT_S = 120.0

_SHA256_LENGTH = 64


class InstallerUpdateError(RuntimeError):
    """A frozen update could not be completed. The message is user-facing."""


#: Called with ``(bytes_written, total_bytes_or_None)`` as the download streams.
#: ``total`` is the release asset's published size when the caller knows it and
#: the server confirms it, and ``None`` when it does not — a progress bar built
#: on this must therefore survive an unknown total rather than assume one.
#: Never raises into the download: :func:`_report` swallows a bad callback.
DownloadProgress = Callable[[int, int | None], None]


def _report(on_progress: DownloadProgress | None, written: int, total: int | None) -> None:
    """Deliver one progress tick without ever endangering the download.

    A progress consumer is cosmetic; the download is not. A callback that raises
    (a UI store torn down mid-flight, a bad lambda) must not abort an otherwise
    healthy 400 MB transfer, so its exception is logged and dropped here.
    """
    if on_progress is None:
        return
    try:
        on_progress(written, total)
    except Exception:  # noqa: BLE001 - a cosmetic callback never fails the update
        log.debug("[update] progress callback raised; continuing the download")


@dataclass(frozen=True)
class InstallerAsset:
    """One downloadable file on a GitHub Release."""

    name: str
    url: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        """The shape the update status route publishes to the UI."""
        return {"name": self.name, "url": self.url, "size": self.size}


@dataclass(frozen=True)
class SignedManifestAssets:
    """The signed update manifest of one release, and the version it must name.

    See :mod:`dodaios.core.update_manifest`. ``version`` is the version of the
    release the caller is installing; the signed manifest must name exactly it.
    """

    manifest: InstallerAsset
    signature: InstallerAsset
    version: str


# --------------------------------------------------------------------------- #
# Asset selection
# --------------------------------------------------------------------------- #
#: Every installer file name the updater accepts, per ``(os, cpu)``, best
#: first. This is the one place the names live.
#:
#: The updater takes the first name of its row that the release actually
#: carries, so an install keeps updating whichever prefix a release uses.
#: Current releases carry BOTH names of every row with identical bytes; the
#: LAST name is the one every release ever published carries
#: (``scripts/ci/release_assets.py`` pins the set for the release pipeline).
INSTALLER_ASSET_NAMES: dict[tuple[str, str], tuple[str, ...]] = {
    ("windows", "x64"): ("Dodaios-Setup-x64.exe", "PersonalJarvis-Setup-x64.exe"),
    ("macos", "arm64"): ("Dodaios-macOS-arm64.dmg", "PersonalJarvis-macOS-arm64.dmg"),
    ("macos", "x64"): ("Dodaios-macOS-x64.dmg", "PersonalJarvis-macOS-x64.dmg"),
    ("linux", "x64"): (
        "Dodaios-Linux-x86_64.AppImage",
        "PersonalJarvis-Linux-x86_64.AppImage",
    ),
}


def installer_asset_names(platform_name: str, machine: str) -> tuple[str, ...]:
    """Accepted release asset names for this OS/CPU pair, best first.

    ``machine`` is compared case-insensitively because the same CPU reports
    different spellings per OS: Windows says ``AMD64``, Linux says ``x86_64``,
    macOS says ``arm64`` while ``platform.machine()`` under Rosetta says
    ``x86_64``. An unrecognised pair returns an empty tuple — the caller then
    reports "no installer for this platform" instead of guessing.
    """
    arch = machine.strip().lower()
    if arch in {"x86_64", "amd64", "x64"}:
        cpu = "x64"
    elif arch in {"arm64", "aarch64"}:
        cpu = "arm64"
    else:
        return ()

    if platform_name == "win32":
        system = "windows"
    elif platform_name == "darwin":
        system = "macos"
    elif platform_name.startswith("linux"):
        system = "linux"
    else:
        return ()
    return INSTALLER_ASSET_NAMES.get((system, cpu), ())


def installer_asset_name(platform_name: str, machine: str) -> str | None:
    """The asset name every published release carries for this OS/CPU pair.

    ``None`` when no installer exists for the pair. Use
    :func:`installer_asset_names` to pick a file out of a release: a release
    may carry the installer under another accepted name.
    """
    names = installer_asset_names(platform_name, machine)
    return names[-1] if names else None


def _running_under_rosetta() -> bool:
    """True when this process is an x86_64 build translated by Rosetta 2.

    ``sysctl.proc_translated`` is 1 for a translated process, 0 for a native
    one, and absent on an Intel Mac (the call then fails, which reads as
    "not translated"). Read through ``sysctlbyname`` so the status poll spawns
    no process.
    """
    if sys.platform != "darwin":
        return False
    try:
        import ctypes

        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        value = ctypes.c_int(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        rc = libc.sysctlbyname(
            b"sysctl.proc_translated", ctypes.byref(value), ctypes.byref(size), None, 0
        )
    except (OSError, AttributeError) as exc:
        log.debug("[update] could not ask whether Rosetta translates this process: %s", exc)
        return False
    return rc == 0 and value.value == 1


def machine_for_update(
    platform_name: str | None = None,
    machine: str | None = None,
    *,
    translated: Callable[[], bool] = _running_under_rosetta,
) -> str:
    """The CPU whose installer this machine should receive.

    Normally ``platform.machine()``. The exception is an Intel build running on
    Apple Silicon: Rosetta makes it report ``x86_64``, so it would keep
    updating to the Intel DMG forever and never leave emulation. Asking the
    kernel whether this process is translated moves it to the native arm64
    build on its next update instead.
    """
    active_platform = sys.platform if platform_name is None else platform_name
    active_machine = platform_module.machine() if machine is None else machine
    if (
        active_platform == "darwin"
        and active_machine.strip().lower() in {"x86_64", "amd64"}
        and translated()
    ):
        return "arm64"
    return active_machine


def select_asset(assets: Iterable[Any], name: str) -> InstallerAsset | None:
    """Find one asset by exact name in a GitHub Release ``assets`` array.

    Accepts the raw JSON list so callers do not have to pre-shape it. Entries
    that are not objects, or that lack a usable download URL, are skipped rather
    than crashing the status poll on a malformed release.
    """
    for entry in assets:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("name") or "") != name:
            continue
        url = str(entry.get("browser_download_url") or "")
        if not url.startswith("https://"):
            # A non-HTTPS or missing URL is not something to "fix" by guessing.
            log.warning("[update] release asset %s has no usable https URL", name)
            return None
        try:
            size = int(entry.get("size") or 0)
        except (TypeError, ValueError):
            # Size is display-only. A release asset whose size GitHub reports
            # oddly still downloads, so an unreadable one reads as unknown
            # rather than failing the update.
            size = 0
        return InstallerAsset(name=name, url=url, size=size)
    return None


def select_installer_assets(
    assets: Iterable[Any], names: Sequence[str]
) -> tuple[InstallerAsset, ...]:
    """The assets of one release that match ``names``, in the order of ``names``.

    Usually one entry. More than one means the release carries the installer
    under several accepted names; :func:`download_and_verify` then takes the
    first that the checksum manifest vouches for.
    """
    listed = list(assets)
    found = (select_asset(listed, name) for name in names)
    return tuple(asset for asset in found if asset is not None)


def select_installer_asset(
    assets: Iterable[Any],
    *,
    platform_name: str | None = None,
    machine: str | None = None,
) -> InstallerAsset | None:
    """The installer asset for the running machine, or ``None``."""
    active_platform = sys.platform if platform_name is None else platform_name
    names = installer_asset_names(
        active_platform,
        machine_for_update(active_platform) if machine is None else machine,
    )
    candidates = select_installer_assets(assets, names)
    return candidates[0] if candidates else None


# --------------------------------------------------------------------------- #
# Checksum manifest
# --------------------------------------------------------------------------- #
def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse ``sha256sum`` output into ``{file name: lowercase digest}``.

    Handles both the binary (``digest *name``) and text (``digest  name``)
    markers and ignores blank or malformed lines, because one bad line must not
    hide the digest of the file we actually need.
    """
    digests: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip().lower(), parts[1].strip()
        if len(digest) != _SHA256_LENGTH:
            continue
        try:
            int(digest, 16)
        except ValueError:
            # Not a hex digest, so not a checksum line. SHA256SUMS files carry
            # headers and blank lines too; skipping a non-entry is parsing,
            # not swallowing a failure.
            continue
        if name.startswith("*"):
            name = name[1:]
        # Release manifests are flat, but a path-prefixed entry must still match
        # by file name rather than being dropped.
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        if name:
            digests[name] = digest
    return digests


# --------------------------------------------------------------------------- #
# Network edge
# --------------------------------------------------------------------------- #
def _content_length(raw: str | None) -> int | None:
    """The response's byte total, or ``None`` when the server did not state one."""
    try:
        total = int(str(raw))
    except (TypeError, ValueError):
        # Absent or malformed: the caller falls back to the release metadata,
        # and failing that shows an indeterminate bar. Not an error.
        return None
    return total if total > 0 else None


class AssetFetcher(Protocol):
    """The only network this module performs. Faked wholesale in tests."""

    async def get_text(self, url: str, *, max_bytes: int) -> str:
        """Fetch a small text body (the checksum manifest)."""

    async def download(
        self,
        url: str,
        dest: Path,
        *,
        max_bytes: int,
        on_progress: DownloadProgress | None = None,
    ) -> int:
        """Stream ``url`` into ``dest``; return the byte count written.

        ``on_progress`` is called as the bytes arrive so a caller can show a
        real percentage. It is optional in the protocol so an implementation
        that cannot report progress stays valid.
        """


class HttpxAssetFetcher:
    """Default :class:`AssetFetcher` on top of httpx.

    ``httpx`` is imported lazily: the base install must boot on a host where the
    updater never runs, and this module sits on an import path the desktop app
    touches at startup (AP-26).

    GitHub answers an asset URL with a redirect to its download CDN, so
    redirects are followed — but every hop, the first request included, must
    stay on ``https``. A hop to plain ``http`` is refused before it is sent.

    ``transport`` exists for tests (an ``httpx.MockTransport``); production
    leaves it ``None`` and gets httpx's default network transport.
    """

    def __init__(self, *, transport: Any | None = None) -> None:
        self._transport = transport

    def _client(self) -> Any:
        import httpx

        return httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            follow_redirects=True,
            transport=self._transport,
            event_hooks={"request": [_require_https]},
        )

    async def get_text(self, url: str, *, max_bytes: int) -> str:
        body = bytearray()
        async with self._client() as client:
            async with client.stream("GET", url, headers=self._headers()) as response:
                response.raise_for_status()
                # Streamed with the cap applied per chunk: reading the whole
                # body first would let a hostile endpoint fill memory before
                # the size check ever ran.
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise InstallerUpdateError(
                            f"release manifest is larger than {max_bytes} bytes — refusing it"
                        )
        return bytes(body).decode("utf-8", errors="replace")

    async def download(
        self,
        url: str,
        dest: Path,
        *,
        max_bytes: int,
        on_progress: DownloadProgress | None = None,
    ) -> int:
        written = 0
        async with self._client() as client:
            async with client.stream("GET", url, headers=self._headers()) as response:
                response.raise_for_status()
                # A GitHub asset redirect always answers with a Content-Length,
                # but a proxy or a chunked transfer need not: an unparsable or
                # absent header means "total unknown", never a guessed size.
                total = _content_length(response.headers.get("content-length"))
                _report(on_progress, 0, total)
                with dest.open("wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        written += len(chunk)
                        if written > max_bytes:
                            raise InstallerUpdateError(
                                f"installer download exceeded {max_bytes} bytes — refusing it"
                            )
                        handle.write(chunk)
                        _report(on_progress, written, total)
        return written

    async def download_resume(
        self,
        url: str,
        dest: Path,
        *,
        offset: int,
        max_bytes: int,
        on_progress: DownloadProgress | None = None,
    ) -> int:
        """Continue a download at byte ``offset`` of ``dest``; return the file's size.

        Asks for ``Range: bytes=<offset>-``. A ``206`` answer appends, a plain
        ``200`` (a server or CDN without ranges) starts the file over, and a
        ``416`` for a non-empty file means it is already complete; the caller's
        hash check decides either way.
        """
        headers = self._headers()
        if offset:
            headers["Range"] = f"bytes={offset}-"
        async with self._client() as client:
            async with client.stream("GET", url, headers=headers) as response:
                if offset and response.status_code == 416:
                    return offset
                response.raise_for_status()
                resumed = bool(offset) and response.status_code == 206
                written = offset if resumed else 0
                length = _content_length(response.headers.get("content-length"))
                total = written + length if length else None
                _report(on_progress, written, total)
                with dest.open("ab" if resumed else "wb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        written += len(chunk)
                        if written > max_bytes:
                            raise InstallerUpdateError(
                                f"download exceeded {max_bytes} bytes — refusing it"
                            )
                        handle.write(chunk)
                        _report(on_progress, written, total)
        return written

    @staticmethod
    def _headers() -> dict[str, str]:
        return {"User-Agent": UPDATER_USER_AGENT, "Accept": "application/octet-stream"}


async def _require_https(request: Any) -> None:
    """httpx request hook: refuse any hop that is not ``https``.

    Runs for the first request and for every redirect httpx follows, so a
    redirect chain that ends on plain ``http`` never sends that request.
    """
    if request.url.scheme != "https":
        raise InstallerUpdateError(
            f"refusing a non-https download hop to {request.url.host or 'an unknown host'}"
        )


async def download_and_verify(
    asset: InstallerAsset,
    checksums: InstallerAsset,
    *,
    dest_dir: Path,
    fetcher: AssetFetcher | None = None,
    max_bytes: int = MAX_INSTALLER_BYTES,
    on_progress: DownloadProgress | None = None,
    download_timeout_s: float = DOWNLOAD_TIMEOUT_S,
    alternatives: Sequence[InstallerAsset] = (),
    signed: SignedManifestAssets | None = None,
) -> Path:
    """Download ``asset`` and prove it against ``checksums``. Fail closed.

    ``signed`` is the release's signed update manifest. When given, the
    checksum manifest is trusted only after the Ed25519 signature over the
    update manifest verifies against the pinned release key, the signed
    version equals ``signed.version`` and the signed digest equals the
    checksum manifest's own SHA-256 — all before a byte of the installer is
    fetched. The in-app updater always passes it; ``None`` keeps the bare
    checksum check for callers that have no release to bind to.

    ``alternatives`` are further assets of the SAME release holding the same
    installer under another accepted name, in order of preference after
    ``asset``. The first of them all that has a line in the checksum manifest
    is the one downloaded: a file the manifest does not vouch for is never
    fetched, whatever it is called.

    ``checksums`` must come from the SAME release as ``asset`` — verifying
    against another release's manifest would authorise the wrong bytes. The
    caller (``update_routes``) reads both out of one release payload.

    ``on_progress`` receives ``(written, total)`` while the installer streams in.
    ``total`` falls back to the release metadata's ``asset.size`` when the server
    states no Content-Length, and stays ``None`` when neither source knows it.

    ``download_timeout_s`` bounds the WHOLE transfer, not one read: httpx's
    read timeout restarts with every chunk, so a server trickling one byte a
    minute would otherwise hold the update — and the apply lock with it —
    forever, leaving the button stuck at the same percentage until a restart.

    Returns the path of the verified file inside ``dest_dir``. Raises
    :class:`InstallerUpdateError` on every failure, leaving nothing executable
    behind.
    """
    active = HttpxAssetFetcher() if fetcher is None else fetcher

    def tick(written: int, total: int | None) -> None:
        _report(on_progress, written, total or (asset.size or None))

    if asset.size and asset.size > max_bytes:
        raise InstallerUpdateError(
            f"{asset.name} is {asset.size} bytes, over the {max_bytes} byte cap"
        )

    try:
        manifest_text = await asyncio.wait_for(
            active.get_text(checksums.url, max_bytes=MAX_CHECKSUMS_BYTES),
            timeout=READ_TIMEOUT_S,
        )
    except InstallerUpdateError:
        raise
    except TimeoutError as exc:
        raise InstallerUpdateError(
            f"{CHECKSUMS_ASSET_NAME} did not arrive within {READ_TIMEOUT_S:.0f}s"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — every transport error is the same refusal
        raise InstallerUpdateError(f"could not download {CHECKSUMS_ASSET_NAME}: {exc}") from exc

    if signed is not None:
        await _verify_signed_manifest(active, signed, manifest_text)

    digests = parse_sha256sums(manifest_text)
    candidates = (asset, *alternatives)
    vouched = [candidate for candidate in candidates if digests.get(candidate.name)]
    if not vouched:
        named = " or ".join(candidate.name for candidate in candidates)
        raise InstallerUpdateError(
            f"{CHECKSUMS_ASSET_NAME} of this release has no entry for {named} — "
            "refusing to install an unverified file"
        )
    if vouched[0] is not asset:
        asset = vouched[0]
        if asset.size and asset.size > max_bytes:
            raise InstallerUpdateError(
                f"{asset.name} is {asset.size} bytes, over the {max_bytes} byte cap"
            )
    expected = digests[asset.name]

    target = _prepare_target(dest_dir, asset.name)
    try:
        written = await asyncio.wait_for(
            active.download(asset.url, target, max_bytes=max_bytes, on_progress=tick),
            timeout=download_timeout_s,
        )
    except InstallerUpdateError:
        _discard(target)
        raise
    except TimeoutError as exc:
        _discard(target)
        raise InstallerUpdateError(
            f"{asset.name} did not finish downloading within "
            f"{download_timeout_s / 60:.0f} minutes — the connection is too slow or stalled"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — same refusal for any transport error
        _discard(target)
        raise InstallerUpdateError(f"could not download {asset.name}: {exc}") from exc

    # Hashing several hundred MB takes seconds of pure CPU. On the event loop
    # that freezes every other request — including the progress poll this very
    # download is feeding — so it goes to a thread.
    actual = await asyncio.to_thread(_sha256_file, target)
    if actual != expected:
        _discard(target)
        raise InstallerUpdateError(
            f"{asset.name} failed its SHA-256 check (expected {expected}, got "
            f"{actual}) — the download was NOT installed"
        )

    log.info("[update] verified %s (%d bytes, sha256 %s)", asset.name, written, actual)
    return target


async def _fetch_small_text(active: AssetFetcher, asset: InstallerAsset, max_bytes: int) -> str:
    """Fetch one small release document; every failure is the same refusal."""
    try:
        return await asyncio.wait_for(
            active.get_text(asset.url, max_bytes=max_bytes), timeout=READ_TIMEOUT_S
        )
    except InstallerUpdateError:
        raise
    except TimeoutError as exc:
        raise InstallerUpdateError(
            f"{asset.name} did not arrive within {READ_TIMEOUT_S:.0f}s"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — every transport error is the same refusal
        raise InstallerUpdateError(f"could not download {asset.name}: {exc}") from exc


async def _verify_signed_manifest(
    active: AssetFetcher, signed: SignedManifestAssets, checksums_text: str
) -> None:
    """Prove the checksum manifest is the one the release key signed for this version."""
    manifest_text = await _fetch_small_text(active, signed.manifest, MAX_MANIFEST_BYTES)
    signature_text = await _fetch_small_text(active, signed.signature, MAX_SIGNATURE_BYTES)
    try:
        # Both documents are ASCII as published, so the text round trip
        # returns their exact bytes; anything else fails the signature check.
        verified = verify_update_manifest(
            manifest_text.encode("utf-8"),
            signature_text,
            checksums=checksums_text.encode("utf-8"),
            expected_version=signed.version,
        )
    except UpdateManifestError as exc:
        raise InstallerUpdateError(f"{UPDATE_MANIFEST_ASSET_NAME}: {exc}") from exc
    log.info("[update] signed update manifest verified for %s", verified.tag)


def _prepare_target(dest_dir: Path, name: str) -> Path:
    """Create the download directory and return the file path inside it.

    Split out of the async caller so the blocking filesystem call does not sit
    on the event loop (ruff ASYNC240); it is a single mkdir, so a thread would
    cost more than it saves.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / name


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _discard(path: Path) -> None:
    """Remove a partial or rejected download so nothing unverified survives."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        # Worth a line: a leftover rejected installer in the temp directory is
        # harmless on its own but confusing in a support log.
        log.warning("[update] could not remove %s: %s", path, exc)


# --------------------------------------------------------------------------- #
# Process edge
# --------------------------------------------------------------------------- #
class CommandRunner(Protocol):
    """Spawning, isolated so the handovers are testable without side effects."""

    def run(self, command: Sequence[str], *, timeout_s: float) -> tuple[int, str, str]:
        """Run to completion; return ``(returncode, stdout, stderr)``."""

    def spawn_detached(self, command: Sequence[str]) -> None:
        """Start ``command`` and return immediately, outliving this process."""


def handover_env(
    base: dict[str, str] | None = None, *, frozen: bool | None = None
) -> dict[str, str]:
    """Environment for every process the handover starts.

    The installer, ``hdiutil`` and the relaunch waiter are spawned by a
    PyInstaller build, and they — or the new version they start — inherit its
    environment. Two parts of that environment belong to the OLD process only:

    * PyInstaller's own bookkeeping (``_PYI_*``). The new version's bootloader
      would read it as "I am a child of that build" — on Windows the install
      path is identical, so the match is exact. ``PYINSTALLER_RESET_ENVIRONMENT``
      (PyInstaller >= 6.10) tells it to start as a fresh top-level process.
    * ``LD_LIBRARY_PATH`` on Linux, which the bootloader pointed into the old
      AppImage's private mount. PyInstaller keeps the user's value in
      ``LD_LIBRARY_PATH_ORIG``; that is what a system program must see, and
      the old mount is gone by the time the new AppImage starts anyway.

    Outside a frozen build nothing was rewritten, so only the reset flag is
    added and the library path is left exactly as the user set it.
    """
    env = dict(os.environ if base is None else base)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if not (is_frozen() if frozen is None else frozen):
        return env
    for var in ("LD_LIBRARY_PATH", "LIBPATH"):
        original = env.pop(f"{var}_ORIG", None)
        if original is not None:
            env[var] = original
        else:
            env.pop(var, None)
    return env


class SubprocessCommandRunner:
    """Default :class:`CommandRunner`. Every spawn is console-free (AP-1)."""

    def run(self, command: Sequence[str], *, timeout_s: float) -> tuple[int, str, str]:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                list(command),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
                stdin=subprocess.DEVNULL,
                env=handover_env(),
                creationflags=NO_WINDOW_CREATIONFLAGS,
            )
        except FileNotFoundError as exc:  # returned to the caller, not swallowed
            return -1, "", f"{command[0]} is not available: {exc}"
        except subprocess.TimeoutExpired:  # returned to the caller, not swallowed
            return -1, "", f"{command[0]} timed out after {timeout_s:.0f}s"
        return completed.returncode, completed.stdout or "", completed.stderr or ""

    def spawn_detached(self, command: Sequence[str]) -> None:
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
            "env": handover_env(),
        }
        if sys.platform == "win32":
            detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            kwargs["creationflags"] = NO_WINDOW_CREATIONFLAGS | detached | new_group
        else:
            # Leave the process group so the handover survives this app exiting.
            kwargs["start_new_session"] = True
        subprocess.Popen(list(command), **kwargs)  # noqa: S603 - fixed argv, no shell


# --------------------------------------------------------------------------- #
# Platform handovers
# --------------------------------------------------------------------------- #
def apply_installer(
    installer: Path,
    *,
    platform_name: str | None = None,
    runner: CommandRunner | None = None,
    app_path: Path | None = None,
    appimage_path: Path | None = None,
    relaunch: bool = True,
    wait_for_pid: int | None = None,
    installer_log: Path | None = None,
) -> str:
    """Install the verified ``installer`` and hand control to the new version.

    Returns a one-line, user-facing description of what was handed over. Raises
    :class:`InstallerUpdateError` when the platform is unsupported or the
    handover could not be completed — the running app then keeps working on the
    old version, which is always better than a half-replaced install.

    The caller must QUIT the running app once this returns. The new version is
    started only after ``wait_for_pid`` (default: this process) has exited:
    started any earlier, it would find the single-instance lock still held,
    focus the old window and exit — leaving the user on the old version.
    """
    active_platform = sys.platform if platform_name is None else platform_name
    active_runner = SubprocessCommandRunner() if runner is None else runner
    old_pid = os.getpid() if wait_for_pid is None else wait_for_pid

    if not installer.is_file():
        raise InstallerUpdateError(f"{installer} does not exist")

    if active_platform == "win32":
        return _handover_windows(
            installer, runner=active_runner, wait_for_pid=old_pid, log_path=installer_log
        )
    if active_platform == "darwin":
        return _handover_macos(
            installer,
            runner=active_runner,
            app_path=app_path if app_path is not None else _running_macos_app(),
            relaunch=relaunch,
            wait_for_pid=old_pid,
        )
    if active_platform.startswith("linux"):
        return _handover_linux(
            installer,
            runner=active_runner,
            appimage_path=(appimage_path if appimage_path is not None else _running_appimage()),
            relaunch=relaunch,
            wait_for_pid=old_pid,
        )
    raise InstallerUpdateError(f"no installer handover exists for platform {active_platform!r}")


# The Inno Setup parameter that tells the installer to start the app again
# once the files are in place (see the RelaunchRequested check in
# packaging/windows/Dodaios.iss).
WINDOWS_RELAUNCH_PARAM = "/RELAUNCH=1"
# The Inno Setup parameter naming the process the installer must outlive (see
# InitializeSetup in packaging/windows/Dodaios.iss).
WINDOWS_WAIT_PID_PARAM = "/WAITPID"
# Where the silent installer writes its log. A silent upgrade that fails shows
# nothing at all, so this file is the only trace of what went wrong.
WINDOWS_INSTALLER_LOG_NAME = "update-installer.log"


def _windows_installer_log() -> Path | None:
    """The installer log path in the user's log directory, or ``None``."""
    try:
        from dodaios.core.paths import user_logs_dir

        logs = user_logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # The update still works without a log; it is only harder to debug.
        log.warning("[update] no log directory for the installer: %s", exc)
        return None
    return logs / WINDOWS_INSTALLER_LOG_NAME


def _handover_windows(
    installer: Path,
    *,
    runner: CommandRunner,
    wait_for_pid: int,
    log_path: Path | None = None,
) -> str:
    """Start the Inno Setup wizard silently and let it replace the running app.

    The app quits right after this returns. ``/WAITPID`` makes the installer
    wait until this process has actually exited before it touches a file: a
    shutdown that takes longer than Setup's start-up would otherwise meet
    files still in use, and a silent install answers that with Abort — the
    app gone, nothing installed, nothing relaunched. ``/CLOSEAPPLICATIONS``
    stays as the fallback for anything else holding a file.
    ``/SUPPRESSMSGBOXES`` keeps a silent upgrade from stopping on a dialog
    nobody asked for, and ``/NORESTART`` guarantees the machine is never
    rebooted behind the user's back.

    The app comes back through ``/RELAUNCH=1``, which the installer's own
    ``[Run]`` entry honours. ``/RESTARTAPPLICATIONS`` is deliberately absent: it
    only restarts apps registered with ``RegisterApplicationRestart``, which
    this one is not, so it promised a relaunch that never happened.
    """
    command = [
        str(installer),
        "/SILENT",
        "/SUPPRESSMSGBOXES",
        "/CLOSEAPPLICATIONS",
        "/NORESTART",
        WINDOWS_RELAUNCH_PARAM,
        f"{WINDOWS_WAIT_PID_PARAM}={wait_for_pid}",
    ]
    log_file = _windows_installer_log() if log_path is None else log_path
    if log_file is not None:
        command.append(f"/LOG={log_file}")
    try:
        runner.spawn_detached(command)
    except OSError as exc:
        raise InstallerUpdateError(f"could not start {installer.name}: {exc}") from exc
    log.info("[update] handed over to %s (log: %s)", installer.name, log_file)
    return "the Windows installer is running; Dodaios restarts by itself"


# Absolute, so the relaunch never depends on the PATH a Finder-started app
# inherits — the same binary the restart helper uses.
MACOS_OPEN = "/usr/bin/open"


#: Pauses before re-trying an ``hdiutil attach`` that failed only because the
#: disk-image machinery was busy (EAGAIN, "Resource temporarily unavailable").
_ATTACH_BUSY_RETRY_DELAYS_S = (2.0, 5.0)
_ATTACH_BUSY_MARKER = "resource temporarily unavailable"


def _attach_dmg(dmg: Path, mountpoint: Path, runner: CommandRunner) -> tuple[int, str]:
    """``hdiutil attach`` the image read-only; a busy refusal is tried again.

    macOS answers an attach with EAGAIN while diskarbitrationd is still busy
    with another image (seen on CI runners right after one was detached). It
    is transient, so it gets a short bounded retry instead of failing the
    update. Every other error is final at once. Returns ``(rc, stderr)``.
    """
    command = [
        "hdiutil",
        "attach",
        str(dmg),
        "-nobrowse",
        "-readonly",
        "-mountpoint",
        str(mountpoint),
    ]
    rc, _out, err = runner.run(command, timeout_s=180.0)
    for delay in _ATTACH_BUSY_RETRY_DELAYS_S:
        if rc == 0 or _ATTACH_BUSY_MARKER not in err.lower() or _is_mounted(mountpoint):
            break
        log.info("[update] hdiutil is busy, attaching %s again in %.0fs", dmg.name, delay)
        time.sleep(delay)
        rc, _out, err = runner.run(command, timeout_s=180.0)
    return rc, err


def _is_mounted(path: Path) -> bool:
    """Whether a volume is mounted at ``path`` (a seam for the tests)."""
    return os.path.ismount(path)


def _can_write(folder: Path) -> bool:
    """Whether this process may create and rename entries in ``folder``."""
    return os.access(folder, os.W_OK)


def _remove_empty_mountpoint(mountpoint: Path) -> None:
    """Delete the temporary mountpoint directory — only if it is empty.

    ``rmdir`` instead of ``rmtree``: when a detach failed the volume is still
    mounted there, and walking into it to "clean up" is never what we want.
    """
    try:
        mountpoint.rmdir()
    except OSError as exc:
        log.warning("[update] left %s in place: %s", mountpoint, exc)


def _handover_macos(
    dmg: Path,
    *,
    runner: CommandRunner,
    app_path: Path | None,
    relaunch: bool,
    wait_for_pid: int,
) -> str:
    """Mount the DMG, swap the running ``.app`` for the one inside, relaunch.

    The running bundle is replaced in place whenever the disk image carries
    the app under the running bundle's name or under a name this version
    knows (the current one or an earlier one). That covers a bundle the USER
    renamed or duplicated ("Keep Both" in Finder): the image still holds the
    usual name, and the update belongs into the bundle they launched.

    Two cases install the image's bundle beside the running one under its own
    name, relaunch it from there and set the old bundle aside afterwards (see
    :func:`_install_renamed_bundle`): a running bundle that still carries an
    earlier name of ours while the image carries the current one, and an image
    whose single bundle has a name this version has never used (a release that
    renamed the app again).
    """
    if app_path is None:
        raise InstallerUpdateError(
            f"could not locate the running {MACOS_APP_DIR_NAME} — refusing to update"
        )

    mountpoint = Path(tempfile.mkdtemp(prefix="jarvis-dmg-"))
    attached = False
    try:
        rc, err = _attach_dmg(dmg, mountpoint, runner)
        if rc != 0:
            raise InstallerUpdateError(
                f"could not mount {dmg.name}: {err.strip()[:200] or 'hdiutil failed'}"
            )
        attached = True

        source = mountpoint / app_path.name
        if not source.is_dir():
            candidates = [p for p in mountpoint.glob("*.app") if p.is_dir()]
            if len(candidates) != 1:
                raise InstallerUpdateError(
                    f"{dmg.name} does not contain exactly one application bundle"
                )
            source = candidates[0]

        known_names = {app_path.name.casefold(), *map(str.casefold, MACOS_APP_DIR_NAMES)}
        earlier_names = set(map(str.casefold, LEGACY_MACOS_APP_DIR_NAMES))
        # The bundle still has the name an earlier release gave it: the update
        # brings the current name with it instead of filling the old folder.
        takes_the_current_name = (
            app_path.name.casefold() in earlier_names
            and source.name.casefold() == MACOS_APP_DIR_NAME.casefold()
        )
        if source.name.casefold() in known_names and not takes_the_current_name:
            installed = app_path
            _replace_directory(source, app_path)
        else:
            installed = app_path.with_name(source.name)
            _install_renamed_bundle(source, installed, replaced=app_path)
    finally:
        # ``attached`` misses one case: hdiutil mounted the image and then
        # reported failure (or timed out after mounting). The mountpoint is the
        # proof either way, so a mounted one is always released.
        if attached or _is_mounted(mountpoint):
            rc, _out, err = runner.run(
                ["hdiutil", "detach", str(mountpoint), "-force"], timeout_s=120.0
            )
            if rc != 0:
                # Not fatal — the swap already happened. Say it so a stuck mount
                # in a support log has an explanation.
                log.warning("[update] could not detach %s: %s", mountpoint, err.strip())
        _remove_empty_mountpoint(mountpoint)

    if relaunch:
        try:
            runner.spawn_detached(
                relaunch_after_exit_command(wait_for_pid, [MACOS_OPEN, "-n", str(installed)])
            )
        except OSError as exc:
            raise InstallerUpdateError(
                f"the update was installed but could not be relaunched: {exc}"
            ) from exc
    if installed != app_path:
        log.info("[update] installed %s from %s, replacing %s", installed, dmg.name, app_path)
        return (
            f"{installed.name} was installed in place of {app_path.name}; "
            "it starts as soon as this window closes"
        )
    log.info("[update] replaced %s from %s", app_path, dmg.name)
    return f"{app_path.name} was replaced; it restarts as soon as this window closes"


def _handover_linux(
    downloaded: Path,
    *,
    runner: CommandRunner,
    appimage_path: Path | None,
    relaunch: bool,
    wait_for_pid: int,
) -> str:
    """Atomically swap the running AppImage for the downloaded one, relaunch."""
    if appimage_path is None:
        raise InstallerUpdateError(
            "this process is not running from an AppImage ($APPIMAGE is unset) — refusing to update"
        )

    staged = appimage_path.with_name(f".{appimage_path.name}.new")
    try:
        # Same directory, so os.replace below is a real atomic rename rather
        # than a cross-device copy that can leave a half-written binary.
        shutil.copyfile(downloaded, staged)
        # An AppImage that is not executable cannot be launched at all, and it
        # is the user's own file in their own directory. 0o755 is the mode the
        # AppImage project itself documents.
        os.chmod(staged, 0o755)  # noqa: S103
        os.replace(staged, appimage_path)
    except OSError as exc:
        try:
            staged.unlink(missing_ok=True)
        except OSError as cleanup_exc:
            log.warning("[update] could not remove %s: %s", staged, cleanup_exc)
        raise InstallerUpdateError(f"could not replace {appimage_path}: {exc}") from exc

    if relaunch:
        try:
            runner.spawn_detached(relaunch_after_exit_command(wait_for_pid, [str(appimage_path)]))
        except OSError as exc:
            raise InstallerUpdateError(
                f"the update was installed but could not be relaunched: {exc}"
            ) from exc
    log.info("[update] replaced %s", appimage_path)
    return f"{appimage_path.name} was replaced; it restarts as soon as this window closes"


# How long the relaunch waiter gives the old app to exit (240 x 0.5 s). Past
# that it launches anyway: the new instance then finds the old one still
# holding the lock and simply focuses it, which is harmless.
RELAUNCH_WAIT_TICKS = 240

# POSIX sh, so it exists on every macOS and Linux box — including a frozen
# build that ships no Python of its own outside the bundle. ``$1`` is the PID
# to outlive, the rest is the command to exec.
_WAIT_THEN_EXEC = (
    'pid="$1"; shift; n=0; '
    f'while kill -0 "$pid" 2>/dev/null && [ "$n" -lt {RELAUNCH_WAIT_TICKS} ]; '
    "do sleep 0.5; n=$((n+1)); done; "
    'exec "$@"'
)


def relaunch_after_exit_command(pid: int, command: Sequence[str]) -> list[str]:
    """Argv that waits for ``pid`` to exit, then execs ``command`` (POSIX only).

    Spawned detached right before the app quits. The single-instance lock only
    frees once the old process is gone, so the new version must not start a
    moment earlier — otherwise it focuses the dying window and exits.
    """
    return ["/bin/sh", "-c", _WAIT_THEN_EXEC, "jarvis-relaunch", str(pid), *command]


def _replace_directory(source: Path, target: Path) -> None:
    """Put ``source`` where ``target`` is, keeping a rollback until it succeeds.

    ``os.replace`` refuses a non-empty destination directory, so the swap is two
    renames on the same filesystem: move the live bundle aside, move the new one
    in, then delete the old one. If the second rename fails the original is put
    straight back, so the app is never left missing.
    """
    staging = target.with_name(f".{target.name}.new")
    previous = target.with_name(f".{target.name}.old")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(previous, ignore_errors=True)

    try:
        shutil.copytree(source, staging, symlinks=True)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallerUpdateError(f"could not stage {target.name}: {exc}") from exc

    moved_aside = False
    try:
        if target.exists():
            os.replace(target, previous)
            moved_aside = True
        os.replace(staging, target)
    except OSError as exc:
        if moved_aside:
            try:
                os.replace(previous, target)
            except OSError as rollback_exc:
                raise InstallerUpdateError(
                    f"{target.name} could not be restored after a failed update: {rollback_exc}"
                ) from rollback_exc
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallerUpdateError(f"could not replace {target.name}: {exc}") from exc

    shutil.rmtree(previous, ignore_errors=True)


# Bundle identifiers this product has shipped under: the installer-built app
# and the downloadable disk image. Only a bundle that names one of them is
# ever removed by an update.
_OWN_MACOS_BUNDLE_IDS = frozenset({MACOS_BUNDLE_ID, MACOS_DMG_BUNDLE_ID})


def _macos_bundle_identifier(bundle: Path) -> str | None:
    """``CFBundleIdentifier`` of ``bundle``; ``None`` when it cannot be read."""
    import plistlib

    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as stream:
            bundle_id = plistlib.load(stream).get("CFBundleIdentifier")
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        # Missing or unreadable metadata proves nothing about ownership.
        log.debug("[update] no readable Info.plist in %s: %s", bundle, exc)
        return None
    return bundle_id if isinstance(bundle_id, str) and bundle_id else None


def _install_renamed_bundle(source: Path, installed: Path, *, replaced: Path) -> None:
    """Install a bundle whose name changed next to the one it supersedes.

    Copying it ONTO the running bundle would leave the new app inside a folder
    that still carries the old name. It goes beside it instead, and only once
    that copy is complete is the superseded bundle taken away — so a failure at
    any point leaves the app the user started exactly where it was.

    Two things are never touched: an unrelated app that already owns the new
    name, and a superseded bundle that does not identify itself as ours.
    """
    if installed.exists():
        present = _macos_bundle_identifier(installed)
        if present is None or present != _macos_bundle_identifier(source):
            raise InstallerUpdateError(
                f"{installed} already exists and is a different application — "
                "refusing to overwrite it"
            )

    _replace_directory(source, installed)

    if _macos_bundle_identifier(replaced) not in _OWN_MACOS_BUNDLE_IDS:
        log.warning("[update] %s does not identify itself as ours; leaving it in place", replaced)
        return
    # Renamed aside first, so a removal that fails halfway leaves a hidden
    # leftover instead of a visible app that no longer starts.
    retired = replaced.with_name(f".{replaced.name}.old")
    shutil.rmtree(retired, ignore_errors=True)
    try:
        os.replace(replaced, retired)
    except OSError as exc:
        # The new app is installed and is what gets relaunched; a superseded
        # bundle that stays behind costs disk space, not the update.
        log.warning("[update] could not remove the superseded %s: %s", replaced, exc)
        return
    shutil.rmtree(retired, ignore_errors=True)


def _running_macos_app() -> Path | None:
    """The ``.app`` bundle of the RUNNING process (``/Applications/<name>.app``), if any.

    ``bundle_root()`` is ``<app>/Contents/MacOS``; the bundle is two levels up.
    """
    root = bundle_root()
    if root is None:
        return None
    for parent in (root, *root.parents):
        if parent.suffix == ".app":
            return parent
    return None


def _running_appimage() -> Path | None:
    """The AppImage file this process was launched from (``$APPIMAGE``)."""
    raw = os.environ.get("APPIMAGE", "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    return candidate if candidate.is_file() else None


def supported_here() -> bool:
    """True when this process is frozen AND an installer exists for its platform."""
    if not is_frozen():
        return False
    return bool(installer_asset_names(sys.platform, machine_for_update()))


@dataclass(frozen=True)
class UpdateBlocker:
    """Why this install cannot replace itself.

    ``code`` is stable and what the UI translates (``topbar.update_blocked_*``);
    ``message`` is the English sentence for logs, the API and any client that
    does not know the code yet.
    """

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


#: Every code :func:`update_blocker` can answer. The frontend has one locale
#: string per code; a parity test keeps the two lists equal.
UPDATE_BLOCKER_CODES = (
    "no_app_bundle",
    "app_translocated",
    "app_read_only",
    "no_appimage",
    "appimage_read_only",
)


def update_blocker(
    platform_name: str | None = None,
    *,
    app_path: Path | None = None,
    appimage_path: Path | None = None,
) -> UpdateBlocker | None:
    """Why the handover would fail on THIS install, or ``None`` when it can run.

    Asked before a single byte is downloaded: every case below otherwise
    surfaces only after a several-hundred-MB download, as a refusal the user
    cannot act on. Each answer says what to do.

    Windows has no such case — the per-user installer replaces its own
    directory — so it always answers ``None``.
    """
    active_platform = sys.platform if platform_name is None else platform_name
    if active_platform == "darwin":
        app = app_path if app_path is not None else _running_macos_app()
        if app is None:
            return UpdateBlocker(
                "no_app_bundle",
                "Dodaios could not find its own app bundle, so it cannot replace it.",
            )
        if "/AppTranslocation/" in app.as_posix():
            # Gatekeeper runs a quarantined app that was never moved from a
            # read-only, randomised copy; nothing there can be replaced.
            return UpdateBlocker(
                "app_translocated",
                "macOS is running Dodaios from a temporary copy. Move it to "
                "the Applications folder, open it from there, then update.",
            )
        if not _can_write(app.parent):
            return UpdateBlocker(
                "app_read_only",
                f"Dodaios cannot write to {app.parent} (a disk image or a "
                "protected folder). Move it to the Applications folder, then update.",
            )
        return None
    if active_platform.startswith("linux"):
        appimage = appimage_path if appimage_path is not None else _running_appimage()
        if appimage is None:
            return UpdateBlocker(
                "no_appimage",
                "This copy of Dodaios was not started from its AppImage file, "
                "so there is no file to update. Download the new AppImage instead.",
            )
        if not _can_write(appimage.parent):
            return UpdateBlocker(
                "appimage_read_only",
                f"Dodaios cannot write to {appimage.parent}. Move the AppImage "
                "to a folder you own (for example ~/Applications), then update.",
            )
        return None
    return None


# A download directory younger than this may belong to an update still in
# flight in another instance (the whole download may take DOWNLOAD_TIMEOUT_S).
STALE_DOWNLOAD_AGE_S = 6 * 3600.0
_DOWNLOAD_DIR_PREFIX = "jarvis-update-"


def download_workdir() -> Path:
    """A fresh private directory for one update's download."""
    return Path(tempfile.mkdtemp(prefix=_DOWNLOAD_DIR_PREFIX))


def sweep_stale_downloads(
    temp_root: Path | None = None,
    *,
    max_age_s: float = STALE_DOWNLOAD_AGE_S,
    now: float | None = None,
) -> int:
    """Delete download directories earlier updates left behind; return how many.

    On Windows the installer runs FROM its download, so that directory cannot
    be removed while the update happens — and nothing removes it later, which
    left one installer of several hundred MB in the temp folder per update.
    The next run of the app reclaims them. Never raises: this is housekeeping.
    """
    root = Path(tempfile.gettempdir()) if temp_root is None else temp_root
    current = time.time() if now is None else now
    removed = 0
    try:
        candidates = [p for p in root.glob(f"{_DOWNLOAD_DIR_PREFIX}*") if p.is_dir()]
    except OSError as exc:
        log.debug("[update] could not list %s for old downloads: %s", root, exc)
        return 0
    for folder in candidates:
        try:
            newest = max(
                [folder.stat().st_mtime, *(entry.stat().st_mtime for entry in folder.iterdir())]
            )
        except OSError as exc:
            log.debug("[update] skipping %s: %s", folder, exc)
            continue
        if current - newest < max_age_s:
            continue
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            log.debug("[update] %s is still in use; leaving it", folder)
            continue
        removed += 1
    if removed:
        log.info("[update] removed %d old update download(s) from %s", removed, root)
    return removed


# =========================================================================== #
# The Unreal Verse payload: channel, resumable download, delta apply, rollback
# =========================================================================== #
# docs/verse/unreal/work-packages.md WP22. The Verse is a packaged Unreal build
# (IoStore chunks per deck) that lives OUTSIDE the app bundle, in
# :func:`verse_root`, so an app update never re-downloads it and a Verse update
# never touches the app:
#
#   <root>/current.json                   which version runs, and the one before
#   <root>/versions/<version>/            one complete, verified payload each
#   <root>/versions/<v>/verse-tree.json   size + SHA-256 of every file of it
#   <root>/downloads/                     resumable ``.part`` downloads
#
# A release carries, per platform (``Win64``, ``Linux``):
#
#   Verse-<Platform>-<version>.tar               the full payload
#   Verse-<Platform>-<old>-to-<new>.delta.tar    changed chunks since <old>
#   verse-SHA256SUMS.txt                         digests of every Verse asset
#   verse-update-manifest.json(.sig)             the release key's signature
#                                                binding that digest file to
#                                                the release version
#
# A payload tar holds ``verse-tree.json`` and ``files/<path>``; a delta tar
# also holds ``verse-delta.json`` and only the changed or added files. A new
# version is built beside the running one in a staging folder, every file is
# checked against the target tree (100 % hash match), and only then does
# ``current.json`` move. Any failure discards the staging folder, so the
# previous version stays the running one: that is the rollback.
#
# Machines the Verse cannot run on (no GPU: ``probe.py`` answers
# ``unsupported``) never download it.

VERSE_TREE_SCHEMA = "verse.tree/1"
VERSE_DELTA_SCHEMA = "verse.delta/1"
VERSE_CURRENT_SCHEMA = "verse.current/1"
VERSE_CHECKSUMS_ASSET_NAME = "verse-SHA256SUMS.txt"
VERSE_MANIFEST_ASSET_NAME = "verse-update-manifest.json"
VERSE_MANIFEST_SIGNATURE_ASSET_NAME = "verse-update-manifest.json.sig"
VERSE_TREE_FILE = "verse-tree.json"
VERSE_DELTA_FILE = "verse-delta.json"
VERSE_CURRENT_FILE = "current.json"
VERSE_ROOT_ENV = "DODAIOS_VERSE_ROOT"

#: Full payload: at most 2 GB compressed at parity (architecture.md 7) plus
#: margin. A delta is typically at most 300 MB; the caps only stop a hostile
#: endpoint from filling the disk.
MAX_VERSE_BYTES = 3_000_000_000
MAX_VERSE_DELTA_BYTES = 1_500_000_000
#: A tree or delta header lists a few thousand files at most.
MAX_VERSE_HEADER_BYTES = 16_000_000
VERSE_DOWNLOAD_TIMEOUT_S = 6 * 3600.0
#: Transport failures one download survives by resuming where it stopped.
VERSE_RESUME_ATTEMPTS = 8
VERSE_RESUME_BACKOFF_S = 3.0

#: ``(os, cpu)`` -> the Unreal platform name of the payload.
VERSE_PLATFORMS: dict[tuple[str, str], str] = {
    ("windows", "x64"): "Win64",
    ("linux", "x64"): "Linux",
}
_VERSE_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_PAYLOAD_PREFIX = "files/"


class VerseUpdateError(InstallerUpdateError):
    """A Verse download, install, delta or rollback failed. The message is user-facing."""


def verse_platform(platform_name: str | None = None, machine: str | None = None) -> str | None:
    """``Win64`` / ``Linux`` for this machine, ``None`` where no Verse ships (macOS)."""
    active = (sys.platform if platform_name is None else platform_name).lower()
    cpu = (platform_module.machine() if machine is None else machine).strip().lower()
    if active.startswith("win"):
        os_name = "windows"
    elif active.startswith("linux"):
        os_name = "linux"
    else:
        os_name = ""
    arch = "x64" if cpu in {"amd64", "x86_64", "x64"} else ""
    return VERSE_PLATFORMS.get((os_name, arch))


def _verse_version(value: str | None) -> str:
    version = str(value or "").strip().removeprefix("v")
    if not _VERSE_VERSION.match(version):
        raise VerseUpdateError(f"{value!r} is not a Verse version (want MAJOR.MINOR.PATCH)")
    return version


def verse_full_asset_name(platform: str, version: str) -> str:
    return f"Verse-{platform}-{_verse_version(version)}.tar"


def verse_delta_asset_name(platform: str, old: str, new: str) -> str:
    return f"Verse-{platform}-{_verse_version(old)}-to-{_verse_version(new)}.delta.tar"


def verse_root(env: dict[str, str] | None = None, platform_name: str | None = None) -> Path:
    """Where the Verse versions live: ``DODAIOS_VERSE_ROOT``, else the per-user data folder."""
    environ = os.environ if env is None else env
    override = environ.get(VERSE_ROOT_ENV, "").strip()
    if override:
        return Path(override)
    active = sys.platform if platform_name is None else platform_name
    if active.startswith("win"):
        base = environ.get("LOCALAPPDATA", "").strip() or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Dodaios" / "verse"
    base = environ.get("XDG_DATA_HOME", "").strip() or str(Path.home() / ".local" / "share")
    return Path(base) / "dodaios" / "verse"


# ------------------------------------------------------------------ the tree
def _safe_relpath(name: str) -> str:
    """A payload path as POSIX text; anything that could leave the folder is refused."""
    text = str(name)
    if not text or "\\" in text or text.startswith("/") or ":" in text or "\0" in text:
        raise VerseUpdateError(f"unsafe path in the Verse payload: {name!r}")
    if any(part in {"", ".", ".."} for part in text.split("/")):
        raise VerseUpdateError(f"unsafe path in the Verse payload: {name!r}")
    return text


def build_verse_tree(folder: Path, *, version: str, platform: str) -> dict[str, Any]:
    """Size and SHA-256 of every file below ``folder`` (``verse-tree.json`` excluded)."""
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        if rel == VERSE_TREE_FILE:
            continue
        files[_safe_relpath(rel)] = {"size": path.stat().st_size, "sha256": _sha256_file(path)}
    return {
        "schema": VERSE_TREE_SCHEMA,
        "version": _verse_version(version),
        "platform": platform,
        "files": files,
    }


def verse_tree_digest(tree: dict[str, Any]) -> str:
    """SHA-256 of a tree's canonical JSON: what a delta names as its base."""
    canonical = json.dumps(tree, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _check_tree(tree: Any) -> dict[str, Any]:
    if not isinstance(tree, dict) or tree.get("schema") != VERSE_TREE_SCHEMA:
        raise VerseUpdateError(f"{VERSE_TREE_FILE} is not a {VERSE_TREE_SCHEMA} document")
    _verse_version(tree.get("version"))
    if not isinstance(tree.get("platform"), str) or not tree["platform"]:
        raise VerseUpdateError(f"{VERSE_TREE_FILE} names no platform")
    files = tree.get("files")
    if not isinstance(files, dict) or not files:
        raise VerseUpdateError(f"{VERSE_TREE_FILE} lists no files")
    for rel, entry in files.items():
        _safe_relpath(rel)
        if not isinstance(entry, dict):
            raise VerseUpdateError(f"{VERSE_TREE_FILE} has a bad entry for {rel}")
        digest = str(entry.get("sha256", ""))
        if len(digest) != _SHA256_LENGTH or not isinstance(entry.get("size"), int):
            raise VerseUpdateError(f"{VERSE_TREE_FILE} has a bad entry for {rel}")
    return tree


def _read_tree(folder: Path) -> dict[str, Any]:
    try:
        return _check_tree(json.loads((folder / VERSE_TREE_FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise VerseUpdateError(f"{folder / VERSE_TREE_FILE} cannot be read: {exc}") from exc


def verify_verse_tree(
    folder: Path, tree: dict[str, Any] | None = None, *, hashes: bool = True
) -> list[str]:
    """Every way ``folder`` differs from its tree; empty means a 100 % match.

    ``hashes=False`` compares sizes only, a cheap check for every launch.
    """
    try:
        expected = _check_tree(tree) if tree is not None else _read_tree(folder)
    except VerseUpdateError as exc:  # the reason becomes the reported problem
        return [str(exc)]
    problems: list[str] = []
    for rel, entry in expected["files"].items():
        path = folder / rel
        if not path.is_file():
            problems.append(f"missing {rel}")
        elif path.stat().st_size != entry["size"]:
            problems.append(f"size mismatch {rel}")
        elif hashes and _sha256_file(path) != entry["sha256"]:
            problems.append(f"hash mismatch {rel}")
    listed = set(expected["files"])
    for path in folder.rglob("*"):
        if path.is_file():
            rel = path.relative_to(folder).as_posix()
            if rel != VERSE_TREE_FILE and rel not in listed:
                problems.append(f"unexpected {rel}")
    return problems


# --------------------------------------------------------------- the pointer
def verse_current(root: Path) -> dict[str, Any] | None:
    """``current.json`` of ``root``: the running version and the previous one."""
    try:
        data = json.loads((root / VERSE_CURRENT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no or unreadable pointer means nothing installed
        return None
    if not isinstance(data, dict) or data.get("schema") != VERSE_CURRENT_SCHEMA:
        return None
    try:
        _verse_version(data.get("version"))
    except VerseUpdateError:  # a pointer naming no version means nothing installed
        return None
    return data


def verse_version_dir(root: Path, version: str) -> Path:
    return root / "versions" / _verse_version(version)


def _write_current(root: Path, version: str, previous: str | None, platform: str) -> None:
    data = {
        "schema": VERSE_CURRENT_SCHEMA,
        "version": version,
        "previous": previous,
        "platform": platform,
    }
    tmp = root / f".{VERSE_CURRENT_FILE}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, root / VERSE_CURRENT_FILE)


def _prune_versions(root: Path, keep: set[str]) -> None:
    versions = root / "versions"
    if not versions.is_dir():
        return
    for entry in versions.iterdir():
        if entry.is_dir() and entry.name not in keep:
            shutil.rmtree(entry, ignore_errors=True)


def _staging_dir(root: Path, version: str) -> Path:
    staging = root / "versions" / f".staging-{version}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    return staging


def _switch(root: Path, staging: Path, tree: dict[str, Any]) -> dict[str, Any]:
    """Make the verified ``staging`` folder the running version; keep one previous."""
    version = tree["version"]
    current = verse_current(root)
    previous = current["version"] if current else None
    if previous == version:
        previous = current.get("previous") if current else None
    target = verse_version_dir(root, version)
    aside: Path | None = None
    if target.exists():
        # Reinstalling the running version (a repair): move the old folder
        # aside first, so current.json never points at a missing folder and a
        # failed swap puts it back.
        aside = target.with_name(f".replaced-{version}-{os.getpid()}")
        shutil.rmtree(aside, ignore_errors=True)
        os.replace(target, aside)
    try:
        os.replace(staging, target)
    except OSError:
        if aside is not None:
            os.replace(aside, target)
        raise
    if aside is not None:
        # Files a running game still holds stay until the next prune.
        shutil.rmtree(aside, ignore_errors=True)
    _write_current(root, version, previous, tree["platform"])
    _prune_versions(root, {version, *([previous] if previous else [])})
    return {"version": version, "previous": previous}


# ----------------------------------------------------------- tar extraction
def _tar_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        if member.isdir():
            continue
        if not member.isfile():
            raise VerseUpdateError(f"the Verse payload holds a non-file entry: {member.name!r}")
        members[_safe_relpath(member.name)] = member
    return members


def _tar_json(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> Any:
    member = members.get(name)
    handle = archive.extractfile(member) if member is not None else None
    if member is None or handle is None or member.size > MAX_VERSE_HEADER_BYTES:
        raise VerseUpdateError(f"the Verse payload has no usable {name}")
    try:
        return json.loads(handle.read().decode("utf-8"))
    except ValueError as exc:
        raise VerseUpdateError(f"{name} in the Verse payload is not JSON: {exc}") from exc


def _extract_payload(
    archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], rel: str, dest: Path
) -> None:
    """Copy one payload file out of the tar: data only, never links or modes."""
    member = members.get(_PAYLOAD_PREFIX + rel)
    source = archive.extractfile(member) if member is not None else None
    if source is None:
        raise VerseUpdateError(f"the Verse payload lacks {rel}")
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with source, target.open("wb") as handle:
        shutil.copyfileobj(source, handle, 1024 * 1024)


def _link_or_copy(source: Path, target: Path) -> None:
    """Reuse an unchanged file of the running version: a hard link, else a copy.

    Nothing ever writes into a payload file after it is verified, so a file
    shared by two versions through a hard link stays correct for both. Damage
    from outside to a shared file damages both versions; the health check then
    answers ``broken`` and :func:`update_verse` (or the installer seed)
    reinstalls the full payload of the same version.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:  # no hard links here (FAT, other volume): copy instead
        shutil.copy2(source, target)


def _write_tree(folder: Path, tree: dict[str, Any]) -> None:
    (folder / VERSE_TREE_FILE).write_text(
        json.dumps(tree, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _fail_and_discard(staging: Path, message: str, *, previous: str | None) -> VerseUpdateError:
    shutil.rmtree(staging, ignore_errors=True)
    kept = f"; rolled back, version {previous} stays installed" if previous else ""
    log.warning("[verse] %s%s", message, kept)
    return VerseUpdateError(f"{message}{kept}")


def _verified_switch(
    root: Path, staging: Path, tree: dict[str, Any], *, what: str, previous: str | None
) -> dict[str, Any]:
    _write_tree(staging, tree)
    problems = verify_verse_tree(staging, tree)
    if problems:
        raise _fail_and_discard(
            staging,
            f"{what} failed verification ({len(problems)} files: {', '.join(problems[:3])})",
            previous=previous,
        )
    try:
        return _switch(root, staging, tree)
    except OSError as exc:
        raise _fail_and_discard(
            staging, f"{what} could not be switched in: {exc}", previous=previous
        ) from exc


# ---------------------------------------------------------- install, delta
def install_verse_full(root: Path, payload: Path) -> dict[str, Any]:
    """Install a full payload tar as the running version. Verified before it switches."""
    root.mkdir(parents=True, exist_ok=True)
    current = verse_current(root)
    previous = current["version"] if current else None
    try:
        archive = tarfile.open(payload, "r:")
    except (OSError, tarfile.TarError) as exc:
        raise VerseUpdateError(f"{payload.name} is not a Verse payload: {exc}") from exc
    with archive:
        members = _tar_members(archive)
        tree = _check_tree(_tar_json(archive, members, VERSE_TREE_FILE))
        staging = _staging_dir(root, tree["version"])
        try:
            for rel in tree["files"]:
                _extract_payload(archive, members, rel, staging)
        except (OSError, tarfile.TarError, VerseUpdateError) as exc:
            raise _fail_and_discard(
                staging, f"Verse install failed: {exc}", previous=previous
            ) from exc
    switched = _verified_switch(
        root, staging, tree, what=f"Verse {tree['version']}", previous=previous
    )
    log.info("[verse] installed %s (full, %d files)", tree["version"], len(tree["files"]))
    return {"kind": "full", "files": len(tree["files"]), **switched}


def _check_delta_header(
    header: Any, tree: dict[str, Any], current: dict[str, Any], base_tree: dict[str, Any]
) -> tuple[list[str], list[str]]:
    previous = current["version"]
    if not isinstance(header, dict) or header.get("schema") != VERSE_DELTA_SCHEMA:
        raise VerseUpdateError(f"{VERSE_DELTA_FILE} is not a {VERSE_DELTA_SCHEMA} document")
    if header.get("from") != previous:
        raise VerseUpdateError(
            f"this delta updates Verse {header.get('from')}, but {previous} is installed"
        )
    platform = header.get("platform")
    if platform != current.get("platform") or platform != tree["platform"]:
        raise VerseUpdateError("this delta is for another platform")
    if header.get("to") != tree["version"]:
        raise VerseUpdateError(f"{VERSE_DELTA_FILE} and {VERSE_TREE_FILE} name other versions")
    if header.get("from_tree_sha256") != verse_tree_digest(base_tree):
        raise VerseUpdateError(
            f"the installed Verse {previous} is not the build this delta was made from"
        )
    changed = [_safe_relpath(p) for p in header.get("files", [])]
    reused = [_safe_relpath(p) for p in header.get("reuse", [])]
    if set(changed) | set(reused) != set(tree["files"]) or set(changed) & set(reused):
        raise VerseUpdateError(f"{VERSE_DELTA_FILE} does not cover the target tree exactly")
    missing = [rel for rel in reused if rel not in base_tree["files"]]
    if missing:
        raise VerseUpdateError(f"{missing[0]} is not part of the installed Verse {previous}")
    return changed, reused


def apply_verse_delta(root: Path, delta: Path) -> dict[str, Any]:
    """Apply a delta tar on top of the running version. Fail closed, roll back.

    The new version is assembled from the delta's files plus hard links to
    the running version's unchanged files, then checked against the target
    tree. A corrupted chunk, a wrong base version or a missing file leaves
    the running version untouched and raises :class:`VerseUpdateError`.
    """
    current = verse_current(root)
    if current is None:
        raise VerseUpdateError("no Verse is installed; a delta needs the version it was made from")
    previous = current["version"]
    base_dir = verse_version_dir(root, previous)
    try:
        archive = tarfile.open(delta, "r:")
    except (OSError, tarfile.TarError) as exc:
        raise VerseUpdateError(f"{delta.name} is not a Verse delta: {exc}") from exc
    with archive:
        members = _tar_members(archive)
        header = _tar_json(archive, members, VERSE_DELTA_FILE)
        tree = _check_tree(_tar_json(archive, members, VERSE_TREE_FILE))
        changed, reused = _check_delta_header(header, tree, current, _read_tree(base_dir))
        staging = _staging_dir(root, tree["version"])
        try:
            for rel in changed:
                _extract_payload(archive, members, rel, staging)
            for rel in reused:
                _link_or_copy(base_dir / rel, staging / rel)
        except (OSError, tarfile.TarError, VerseUpdateError) as exc:
            raise _fail_and_discard(
                staging, f"Verse delta to {tree['version']} failed: {exc}", previous=previous
            ) from exc
    switched = _verified_switch(
        root, staging, tree, what=f"Verse delta to {tree['version']}", previous=previous
    )
    log.info(
        "[verse] applied delta %s -> %s (%d changed, %d reused, 100%% hash match)",
        previous,
        tree["version"],
        len(changed),
        len(reused),
    )
    return {"kind": "delta", "changed": len(changed), "reused": len(reused), **switched}


def rollback_verse(root: Path) -> dict[str, Any]:
    """Make the previous version the running one again, after verifying it."""
    current = verse_current(root)
    if current is None or not current.get("previous"):
        raise VerseUpdateError("there is no previous Verse version to roll back to")
    previous = current["previous"]
    problems = verify_verse_tree(verse_version_dir(root, previous))
    if problems:
        raise VerseUpdateError(
            f"the previous Verse {previous} is damaged too ({', '.join(problems[:3])})"
        )
    _write_current(root, previous, None, str(current.get("platform", "")))
    log.warning("[verse] rolled back from %s to %s", current["version"], previous)
    return {"version": previous, "rolled_back_from": current["version"]}


def ensure_verse_healthy(root: Path, *, hashes: bool = False) -> dict[str, Any]:
    """Check the running version; roll back to the previous one when it is damaged."""
    current = verse_current(root)
    if current is None:
        return {"status": "not_installed"}
    problems = verify_verse_tree(verse_version_dir(root, current["version"]), hashes=hashes)
    if not problems:
        return {"status": "ok", "version": current["version"]}
    try:
        rolled = rollback_verse(root)
    except VerseUpdateError as exc:  # reported to the caller as status broken
        return {
            "status": "broken",
            "version": current["version"],
            "problems": problems[:10],
            "detail": str(exc),
        }
    return {"status": "rolled_back", "problems": problems[:10], **rolled}


# ------------------------------------------------------- channel, download
@dataclass(frozen=True)
class VerseUpdatePlan:
    """What one Verse update downloads: a delta when one fits, else the full payload."""

    kind: str  # "delta" | "full"
    platform: str
    from_version: str | None
    to_version: str
    payload: InstallerAsset
    checksums: InstallerAsset
    signed: SignedManifestAssets
    fallback: InstallerAsset | None = None  # the full payload behind a delta

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "platform": self.platform,
            "from": self.from_version,
            "to": self.to_version,
            "payload": self.payload.as_dict(),
        }


def select_verse_update(
    assets: Iterable[Any],
    *,
    version: str,
    installed: str | None,
    gpu_supported: bool,
    platform_name: str | None = None,
    machine: str | None = None,
    repair: bool = False,
) -> VerseUpdatePlan | None:
    """The Verse download this machine needs from one release, or ``None``.

    ``None`` when the machine cannot run the Verse (no GPU: nothing is
    downloaded), when no Verse ships for this OS, when the installed version
    is already the release's (unless ``repair``: a broken install gets the
    full payload again), or when the release carries no Verse payload.
    A release that carries a payload without its signed digest files raises:
    an unverifiable payload is never offered.
    """
    if not gpu_supported:
        return None
    platform = verse_platform(platform_name, machine)
    if platform is None:
        return None
    target = _verse_version(version)
    base = _verse_version(installed) if installed and not repair else None
    if base == target:
        return None
    listed = list(assets)
    full = select_asset(listed, verse_full_asset_name(platform, target))
    delta = select_asset(listed, verse_delta_asset_name(platform, base, target)) if base else None
    payload = delta or full
    if payload is None:
        return None
    checksums = select_asset(listed, VERSE_CHECKSUMS_ASSET_NAME)
    manifest = select_asset(listed, VERSE_MANIFEST_ASSET_NAME)
    signature = select_asset(listed, VERSE_MANIFEST_SIGNATURE_ASSET_NAME)
    if checksums is None or manifest is None or signature is None:
        raise VerseUpdateError(
            "this release carries a Verse payload without its signed checksum manifest — "
            "refusing it"
        )
    return VerseUpdatePlan(
        kind="delta" if delta else "full",
        platform=platform,
        from_version=base,
        to_version=target,
        payload=payload,
        checksums=checksums,
        signed=SignedManifestAssets(manifest=manifest, signature=signature, version=target),
        fallback=full if delta else None,
    )


async def _download_resume(
    active: Any,
    url: str,
    part: Path,
    *,
    offset: int,
    max_bytes: int,
    on_progress: DownloadProgress | None,
) -> int:
    resume = getattr(active, "download_resume", None)
    if resume is not None:
        return int(
            await resume(url, part, offset=offset, max_bytes=max_bytes, on_progress=on_progress)
        )
    # A fetcher without HTTP ranges restarts from the first byte.
    return int(await active.download(url, part, max_bytes=max_bytes, on_progress=on_progress))


def _resume_error(asset: InstallerAsset, reason: str) -> VerseUpdateError:
    return VerseUpdateError(
        f"{asset.name}: {reason}; the next attempt resumes where this one stopped"
    )


async def download_verse_payload(
    plan: VerseUpdatePlan,
    *,
    dest_dir: Path,
    fetcher: AssetFetcher | None = None,
    payload: InstallerAsset | None = None,
    on_progress: DownloadProgress | None = None,
    timeout_s: float = VERSE_DOWNLOAD_TIMEOUT_S,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> Path:
    """Download one Verse asset of ``plan``, resuming after drops. Fail closed.

    The signed manifest is verified first (signature, version, digest of
    ``verse-SHA256SUMS.txt``), then the payload streams into ``<name>.part``,
    continuing from the bytes already there after every transport failure,
    and is renamed only after its SHA-256 matches the signed digest.
    """
    active = HttpxAssetFetcher() if fetcher is None else fetcher
    asset = payload or plan.payload
    sums_text = await _fetch_small_text(active, plan.checksums, MAX_CHECKSUMS_BYTES)
    await _verify_signed_manifest(active, plan.signed, sums_text)
    expected = parse_sha256sums(sums_text).get(asset.name)
    if not expected:
        raise VerseUpdateError(
            f"{VERSE_CHECKSUMS_ASSET_NAME} has no entry for {asset.name} — refusing it"
        )
    cap = MAX_VERSE_DELTA_BYTES if asset.name.endswith(".delta.tar") else MAX_VERSE_BYTES
    if asset.size and asset.size > cap:
        raise VerseUpdateError(f"{asset.name} is {asset.size} bytes, over the {cap} byte cap")
    final = _prepare_target(dest_dir, asset.name)
    part = dest_dir / f"{asset.name}.part"
    if final.is_file() and await asyncio.to_thread(_sha256_file, final) == expected:
        return final
    _discard(final)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    attempt = 0
    while True:
        offset = part.stat().st_size if part.is_file() else 0
        if offset > cap:
            _discard(part)
            offset = 0
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise _resume_error(asset, f"not finished within {timeout_s / 3600:.1f} h")
        try:
            await asyncio.wait_for(
                _download_resume(
                    active, asset.url, part, offset=offset, max_bytes=cap, on_progress=on_progress
                ),
                timeout=remaining,
            )
            break
        except InstallerUpdateError:
            _discard(part)
            raise
        except TimeoutError as exc:
            raise _resume_error(asset, f"not finished within {timeout_s / 3600:.1f} h") from exc
        except Exception as exc:  # noqa: BLE001 - every transport error resumes
            attempt += 1
            if attempt >= VERSE_RESUME_ATTEMPTS:
                raise _resume_error(asset, f"{attempt} attempts failed ({exc})") from exc
            log.info("[verse] %s dropped at %d bytes (%s); resuming", asset.name, offset, exc)
            await sleep(VERSE_RESUME_BACKOFF_S)
    actual = await asyncio.to_thread(_sha256_file, part)
    if actual != expected:
        _discard(part)
        raise VerseUpdateError(
            f"{asset.name} failed its SHA-256 check (expected {expected}, got {actual}) — "
            "the download was NOT installed"
        )
    os.replace(part, final)
    log.info("[verse] verified %s (sha256 %s)", asset.name, actual)
    return final


async def update_verse(
    assets: Iterable[Any],
    *,
    version: str,
    gpu_supported: bool,
    root: Path | None = None,
    fetcher: AssetFetcher | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
    on_progress: DownloadProgress | None = None,
    verify_hashes: bool = False,
) -> dict[str, Any]:
    """Bring the installed Verse to ``version`` from one release's assets.

    The running version is health-checked first: a damaged one rolls back to
    the previous version, and one with no healthy version to fall back to
    (a hard-linked file both share was damaged) gets the full payload again,
    even when its version number is already the release's. A delta that
    fails (download, cap or apply) leaves the running version in place and
    falls back to the full payload when the release carries one.
    """
    active_root = verse_root() if root is None else root
    if not gpu_supported:
        current = verse_current(active_root)
        return {"status": "unsupported", "version": current["version"] if current else None}
    health = await asyncio.to_thread(ensure_verse_healthy, active_root, hashes=verify_hashes)
    broken = health["status"] == "broken"
    if broken:
        log.warning("[verse] the installed Verse is broken (%s); reinstalling", health)
    current = verse_current(active_root)
    installed = current["version"] if current else None
    plan = select_verse_update(
        assets,
        version=version,
        installed=installed,
        gpu_supported=gpu_supported,
        platform_name=platform_name,
        machine=machine,
        repair=broken,
    )
    if plan is None:
        return {"status": "broken" if broken else "current", "version": installed}
    downloads = active_root / "downloads"
    if plan.kind == "delta":
        try:
            path = await download_verse_payload(
                plan, dest_dir=downloads, fetcher=fetcher, on_progress=on_progress
            )
            result = await asyncio.to_thread(apply_verse_delta, active_root, path)
            _discard(path)
            return {"status": "updated", **plan.as_dict(), **result}
        except (InstallerUpdateError, OSError) as exc:
            # A refused signature fails the full payload the same way (same
            # manifest), before any of it is downloaded.
            if plan.fallback is None:
                raise
            log.warning("[verse] delta update failed (%s); using the full payload", exc)
    payload = plan.fallback or plan.payload
    path = await download_verse_payload(
        plan, dest_dir=downloads, fetcher=fetcher, payload=payload, on_progress=on_progress
    )
    result = await asyncio.to_thread(install_verse_full, active_root, path)
    _discard(path)
    return {
        "status": "repaired" if broken else "updated",
        **plan.as_dict(),
        "kind": "full",
        "payload": payload.as_dict(),
        **result,
    }


#: Folder of the frozen bundle the installers put the Verse seed payload in
#: (``packaging/windows/verse/stage_verse.ps1``, ``packaging/linux/verse/stage_verse.sh``).
VERSE_SEED_DIR = "verse"
_SEED_NAME = re.compile(r"^Verse-(?P<platform>Win64|Linux)-(?P<version>\d+\.\d+\.\d+)\.tar$")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in _verse_version(version).split("."))


def seed_verse_from_bundle(
    *,
    gpu_supported: bool,
    root: Path | None = None,
    bundle: Path | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> dict[str, Any]:
    """Install the Verse payload the installer shipped, when it is newer than the installed one.

    The installer carries a full payload as ``<bundle>/verse/Verse-<Platform>-<v>.tar``.
    It is installed (verified file by file) into :func:`verse_root` and then
    removed from the bundle where the bundle is writable, so the machine does
    not keep two copies. Machines that cannot run the Verse leave it alone.
    """
    if not gpu_supported:
        return {"status": "unsupported"}
    platform = verse_platform(platform_name, machine)
    folder = (bundle if bundle is not None else bundle_root() or Path()) / VERSE_SEED_DIR
    if platform is None or not folder.is_dir():
        return {"status": "no_seed"}
    seeds = []
    for path in folder.iterdir():
        match = _SEED_NAME.match(path.name)
        if match and match.group("platform") == platform and path.is_file():
            seeds.append((_version_key(match.group("version")), path))
    if not seeds:
        return {"status": "no_seed"}
    key, seed = max(seeds)
    active_root = verse_root() if root is None else root
    # A damaged install rolls back first; one with nothing healthy left gets
    # the seed even when the seed is not newer.
    broken = ensure_verse_healthy(active_root)["status"] == "broken"
    current = verse_current(active_root)
    if not broken and current is not None and _version_key(current["version"]) >= key:
        return {"status": "current", "version": current["version"]}
    result = install_verse_full(active_root, seed)
    try:
        seed.unlink()
    except OSError:
        # A read-only bundle (a mounted AppImage) keeps its seed; nothing breaks.
        log.debug("[verse] the seed %s stays in the read-only bundle", seed)
    return {"status": "repaired" if broken else "installed", **result}
