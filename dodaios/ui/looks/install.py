"""Install and remove looks from the Community Marketplace (``docs/looks.md``).

A marketplace look is a zip archive on a public https host. The registry pins
its SHA-256 and size, so what the app installs is byte for byte what the
registry checked. Install:

1. download over https only, from the allowed hosts, public addresses only,
   never more than the pinned size;
2. compare the SHA-256 with the pinned one;
3. read the zip without trusting it: entry count, total unpacked size, safe
   names, no links;
4. unpack into a hidden staging folder and check it as a pack
   (``loader.read_manifest``): the id must be the entry's name;
5. move it into ``<DATA_DIR>/looks/<id>`` with one rename.

A crash leaves at most a staging folder, which the next install sweeps.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import secrets
import shutil
import stat
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from dodaios.ui.looks import loader
from dodaios.ui.looks.manifest import (
    LOOK_ID_RE,
    MAX_PACK_BYTES,
    MAX_PACK_FILES,
    LookManifest,
    LookManifestError,
    is_safe_rel_path,
)

_log = logging.getLogger(__name__)

#: Hosts a look archive or preview may come from. GitHub release assets
#: redirect to objects.githubusercontent.com.
ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "raw.githubusercontent.com",
        "dodaios.github.io",
    }
)

#: Slack on top of the pack limit for the zip's own headers.
MAX_ARCHIVE_BYTES = MAX_PACK_BYTES + 2 * 1024 * 1024

_STAGING_PREFIX = ".staging-"


class LookInstallError(RuntimeError):
    """An install that was refused; the message is shown to the user."""


def allowed_url(url: object) -> bool:
    """True for an https URL on one of :data:`ALLOWED_HOSTS`."""
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and (parts.hostname or "").lower() in ALLOWED_HOSTS
        and not parts.username
        and not parts.password
        and parts.port in (None, 443)
    )


async def download(url: str, *, max_bytes: int) -> bytes:
    """Fetch ``url`` with every redirect kept on https and public addresses."""
    import httpx

    from dodaios.core.http_guard import public_only_async

    if not allowed_url(url):
        raise LookInstallError("The look's download address is not allowed.")
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)
    buf = io.BytesIO()
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout, **public_only_async()
        ) as client:
            async with client.stream("GET", url) as response:
                if not allowed_url(str(response.url)):
                    raise LookInstallError(
                        "The download was redirected to a host that is not allowed."
                    )
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    buf.write(chunk)
                    if buf.tell() > max_bytes:
                        raise LookInstallError("The look's archive is larger than allowed.")
    except httpx.HTTPError as exc:
        raise LookInstallError(f"The look could not be downloaded: {exc}") from exc
    return buf.getvalue()


def _members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    """``(info, pack path)`` for every file, after every safety check.

    An archive may hold the pack at its root or inside one top folder.
    """
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos:
        raise LookInstallError("The look's archive is empty.")
    if len(infos) > MAX_PACK_FILES:
        raise LookInstallError(f"A look may hold at most {MAX_PACK_FILES} files.")

    names = [info.filename.replace("\\", "/") for info in infos]
    tops = {name.split("/", 1)[0] for name in names}
    strip = ""
    if len(tops) == 1 and all("/" in name for name in names):
        strip = next(iter(tops)) + "/"

    total = 0
    out: list[tuple[zipfile.ZipInfo, str]] = []
    for info, name in zip(infos, names, strict=True):
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            raise LookInstallError(f"The archive contains a link: {name}.")
        if info.flag_bits & 0x1:
            raise LookInstallError("The archive is encrypted.")
        rel = name[len(strip) :] if strip else name
        if not is_safe_rel_path(rel):
            raise LookInstallError(f"The archive contains a file name that is not allowed: {name}.")
        total += info.file_size
        if total > MAX_PACK_BYTES:
            mb = MAX_PACK_BYTES // (1024 * 1024)
            raise LookInstallError(f"A look may be at most {mb} MB unpacked.")
        out.append((info, rel))
    return out


def _extract(data: bytes, target: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise LookInstallError("The look's archive is not a valid zip file.") from exc
    with archive:
        for info, rel in _members(archive):
            dest = target.joinpath(*rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(info) as src, open(dest, "xb") as out:
                while chunk := src.read(64 * 1024):
                    written += len(chunk)
                    # The header's size is a claim; the stream is the truth.
                    if written > info.file_size:
                        raise LookInstallError("The archive's sizes do not match its contents.")
                    out.write(chunk)


def _sweep_staging(root: Path) -> None:
    try:
        stale = [p for p in root.iterdir() if p.name.startswith(_STAGING_PREFIX)]
    except FileNotFoundError:  # No installed-looks folder yet: nothing to sweep.
        return
    for folder in stale:
        shutil.rmtree(folder, ignore_errors=True)


def install_archive(
    data: bytes, *, look_id: str, sha256: str, data_dir: Path | None = None
) -> LookManifest:
    """Check and unpack a downloaded archive as the look ``look_id``.

    Replaces an installed look with the same id. Refuses an id that a
    built-in look owns.
    """
    if not LOOK_ID_RE.match(look_id):
        raise LookInstallError("The look's name is not a valid look id.")
    if (loader.builtin_root() / look_id).is_dir():
        raise LookInstallError(f"'{look_id}' is the name of a built-in look.")
    digest = hashlib.sha256(data).hexdigest()
    if not secrets.compare_digest(digest, sha256.lower()):
        raise LookInstallError("The downloaded look does not match the registry's checksum.")

    root = loader.custom_root(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    _sweep_staging(root)
    staging = root / f"{_STAGING_PREFIX}{secrets.token_hex(6)}"
    pack = staging / look_id
    pack.mkdir(parents=True)
    try:
        _extract(data, pack)
        try:
            manifest = loader.read_manifest(pack, builtin=False)
        except LookManifestError as exc:
            raise LookInstallError(f"The look is not valid: {exc}") from exc

        final = root / look_id
        if final.exists():
            # The old version goes into staging and is deleted with it.
            os.replace(final, staging / "previous")
        os.replace(pack, final)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def uninstall(look_id: str, *, data_dir: Path | None = None) -> bool:
    """Remove an installed look. False when there is none; built-ins stay."""
    if not LOOK_ID_RE.match(look_id):
        return False
    folder = loader.custom_root(data_dir) / look_id
    if not (folder / loader.MANIFEST_NAME).is_file():
        return False
    trash = folder.with_name(f"{_STAGING_PREFIX}{secrets.token_hex(6)}")
    os.replace(folder, trash)
    shutil.rmtree(trash, ignore_errors=True)
    _log.info("look %s removed", look_id)
    return True


def installed_ids(*, data_dir: Path | None = None) -> frozenset[str]:
    """Ids of every look installed from the marketplace (not the built-ins)."""
    root = loader.custom_root(data_dir)
    try:
        return frozenset(
            p.name
            for p in root.iterdir()
            if LOOK_ID_RE.match(p.name) and (p / loader.MANIFEST_NAME).is_file()
        )
    except FileNotFoundError:  # No installed-looks folder yet: nothing installed.
        return frozenset()
