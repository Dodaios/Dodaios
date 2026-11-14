"""The pictures on a whiteboard: where their bytes live, and which bytes count.

A scene names an image by a file id and keeps only its metadata
(:mod:`.scene`); the bytes would make every save of the board megabytes larger.
They live beside the node, in its run directory::

    <run dir>/board-files/<sha256 of the file id, 40 hex>

The folder sits outside ``tasks/*/artifacts/files`` on purpose: the Outputs
allowlist never lists it, so a picture is reached only through the node's own
route, which knows the type it serves. The file on disk is named by a hash of
the id and never by the id itself, so no value from a request ever becomes a
path.

Why the type is read from the bytes: the claimed type of a data URL is the
sender's word. A file is kept only when its first bytes are a PNG, a JPEG, a
GIF or a WebP, and it is served with the type its bytes have. SVG is never
accepted: an SVG is a document that can carry script.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from dodaios.nodes.board.scene import file_id as clean_file_id
from dodaios.nodes.types import NodeError

#: The folder of a whiteboard node's pictures, inside its run directory.
FILES_DIR: Final[str] = "board-files"
MAX_FILE_BYTES: Final[int] = 5 * 1024 * 1024
MAX_BOARD_BYTES: Final[int] = 50 * 1024 * 1024
#: How long a stored picture is safe from pruning although no scene names it yet.
PRUNE_GRACE_SECONDS: Final[int] = 10 * 60
#: The base64 text of the largest picture, with room for line breaks.
MAX_DATA_URL_CHARS: Final[int] = (MAX_FILE_BYTES + 2) // 3 * 4 + 64 * 1024

_DATA_URL_RE: Final = re.compile(
    r"^data:([a-z0-9.+/-]{0,80})((?:;[a-z0-9=._-]{1,40}){0,4});base64,", re.I
)
_DISK_NAME_RE: Final = re.compile(r"^[0-9a-f]{40}$")


class FileConflict(NodeError):
    """A different picture already has this file id."""


def sniff(data: bytes) -> str | None:
    """The picture type the bytes start with, or ``None`` for anything else."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """The bytes of a ``data:`` URL and the picture type they really have.

    Raises :class:`NodeError` for anything but a base64 data URL of a PNG,
    JPEG, GIF or WebP of at most :data:`MAX_FILE_BYTES`.
    """
    if not isinstance(data_url, str) or len(data_url) > MAX_DATA_URL_CHARS:
        raise NodeError(
            f"'dataURL' must be a picture of at most {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )
    match = _DATA_URL_RE.match(data_url)
    if match is None:
        raise NodeError("'dataURL' must be a base64 data URL: data:image/png;base64,....")
    payload = "".join(data_url[match.end() :].split())
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise NodeError("'dataURL' holds no valid base64.") from exc
    if not data:
        raise NodeError("'dataURL' holds an empty file.")
    if len(data) > MAX_FILE_BYTES:
        raise NodeError(
            f"The picture is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB; send a smaller one."
        )
    mime = sniff(data)
    if mime is None:
        raise NodeError("A whiteboard keeps PNG, JPEG, GIF and WebP pictures only.")
    return data, mime


def disk_name(file_id: str) -> str:
    """The name of a picture's file on disk: a hash of its id, never the id."""
    return hashlib.sha256(file_id.encode("utf-8")).hexdigest()[:40]


def _folder(run_dir: Path) -> Path:
    return run_dir / FILES_DIR


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(prefix=".file-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(staged, target)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def used_bytes(run_dir: Path) -> int:
    """How many bytes the board's pictures take on disk."""
    total = 0
    try:
        for entry in _folder(run_dir).iterdir():
            if _DISK_NAME_RE.match(entry.name) and entry.is_file():
                total += entry.stat().st_size
    except OSError:  # no folder yet: the board has no pictures
        return 0
    return total


def prune(run_dir: Path, keep: Iterable[str], *, now: float | None = None) -> int:
    """Remove the pictures whose ids are not in ``keep``. Returns the bytes freed.

    The caller passes every file id the current scene and its kept versions
    name, so a picture that "undo" could bring back stays. A picture stored
    in the last :data:`PRUNE_GRACE_SECONDS` stays too: the editor uploads a
    picture just before the save that names it.
    """
    wanted = {disk_name(ident) for ident in keep}
    cutoff = (time.time() if now is None else now) - PRUNE_GRACE_SECONDS
    freed = 0
    try:
        entries = list(_folder(run_dir).iterdir())
    except OSError:  # no folder: nothing to remove
        return 0
    for entry in entries:
        if not _DISK_NAME_RE.match(entry.name) or entry.name in wanted:
            continue
        try:
            info = entry.stat()
            if info.st_mtime > cutoff:
                continue
            size = info.st_size
            entry.unlink()
            freed += size
        except OSError:  # a file that cannot go now goes on a later prune
            continue
    return freed


def store_bytes(
    run_dir: Path,
    data: bytes,
    mime: str,
    *,
    file_id: str | None = None,
    keep: Iterable[str] | None = None,
) -> str:
    """Keep one picture's bytes for the board in ``run_dir``. Returns its file id.

    Without ``file_id`` the id is the SHA-1 of the bytes, as the editor makes
    it, so the same picture sent twice is kept once. A different picture
    under an id that is taken is a :class:`FileConflict`. When the board's
    pictures would pass :data:`MAX_BOARD_BYTES`, pictures no id in ``keep``
    names are removed first; if that is not enough it is a :class:`NodeError`.
    """
    if file_id is None:
        ident = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    else:
        checked = clean_file_id(file_id)
        if checked is None:
            raise NodeError("'id' must be 1 to 100 letters, digits, '_' or '-'.")
        ident = checked
    if sniff(data) != mime:
        raise NodeError("A whiteboard keeps PNG, JPEG, GIF and WebP pictures only.")
    target = _folder(run_dir) / disk_name(ident)
    try:
        existing = target.read_bytes()
    except OSError:  # not stored yet
        existing = None
    if existing is not None:
        if existing == data:
            return ident
        raise FileConflict(f"A different picture already has the id {ident!r}; send another id.")
    if used_bytes(run_dir) + len(data) > MAX_BOARD_BYTES and keep is not None:
        prune(run_dir, keep)
    if used_bytes(run_dir) + len(data) > MAX_BOARD_BYTES:
        raise NodeError(
            f"This board's pictures would pass {MAX_BOARD_BYTES // (1024 * 1024)} MB; remove "
            "some pictures or make a second board."
        )
    _atomic_write(target, data)
    return ident


def store_data_url(
    run_dir: Path,
    data_url: str,
    *,
    file_id: str | None = None,
    keep: Iterable[str] | None = None,
) -> tuple[str, str]:
    """Keep the picture of a data URL. Returns ``(file id, picture type)``."""
    data, mime = decode_data_url(data_url)
    return store_bytes(run_dir, data, mime, file_id=file_id, keep=keep), mime


def read(run_dir: Path, file_id: str) -> tuple[bytes, str] | None:
    """A picture's bytes and the type they have, or ``None`` when there is none."""
    ident = clean_file_id(file_id)
    if ident is None:
        return None
    try:
        data = (_folder(run_dir) / disk_name(ident)).read_bytes()
    except OSError:  # no such picture
        return None
    mime = sniff(data)
    return (data, mime) if mime is not None else None


def copy_all(source_run: Path, target_run: Path) -> None:
    """Copy a board's pictures to another node's run directory (a duplicate)."""
    source = _folder(source_run)
    if not source.is_dir():
        return
    target = _folder(target_run)
    target.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if _DISK_NAME_RE.match(entry.name) and entry.is_file():
            shutil.copyfile(entry, target / entry.name)


__all__ = [
    "FILES_DIR",
    "MAX_BOARD_BYTES",
    "MAX_FILE_BYTES",
    "FileConflict",
    "copy_all",
    "decode_data_url",
    "disk_name",
    "prune",
    "read",
    "sniff",
    "store_bytes",
    "store_data_url",
    "used_bytes",
]
