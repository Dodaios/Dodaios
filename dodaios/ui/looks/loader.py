"""Find, read and check look packs on disk (``docs/looks.md``).

Built-in looks ship in ``dodaios/ui/looks/builtin/<id>/``; installed looks
live in ``<DATA_DIR>/looks/<id>/``. Ids are matched against a strict pattern
before they become paths, and :func:`resolve_file` is the one place a
requested file name turns into a path, so no request can leave a pack.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dodaios.ui.looks.manifest import (
    ALLOWED_TYPES,
    LOOK_ID_RE,
    MAX_MANIFEST_BYTES,
    MAX_PACK_BYTES,
    MAX_PACK_FILES,
    LookManifest,
    LookManifestError,
    is_safe_rel_path,
    parse_manifest,
    suffix_of,
)

_log = logging.getLogger(__name__)

MANIFEST_NAME = "look.json"


def builtin_root() -> Path:
    """Folder holding the built-in looks (``dodaios/ui/looks/builtin``)."""
    return Path(__file__).resolve().parent / "builtin"


def custom_root(data_dir: Path | None = None) -> Path:
    """Folder holding installed looks: ``<DATA_DIR>/looks``. Not created here."""
    if data_dir is None:
        from dodaios.core import config

        data_dir = config.DATA_DIR
    return Path(data_dir) / "looks"


def _child_folder(root: Path, name: str) -> Path | None:
    base = os.path.normpath(os.path.abspath(root))
    full = os.path.normpath(os.path.join(base, name))
    if os.path.dirname(full) != base:
        return None
    return Path(full)


def find_look_dir(look_id: str, *, data_dir: Path | None = None) -> tuple[Path, bool] | None:
    """Return ``(folder, builtin)`` for ``look_id``, or ``None``.

    Built-in looks win over installed ones with the same id.
    """
    if not isinstance(look_id, str) or not LOOK_ID_RE.match(look_id):
        return None
    for root, builtin in ((builtin_root(), True), (custom_root(data_dir), False)):
        folder = _child_folder(root, look_id)
        if folder is not None and (folder / MANIFEST_NAME).is_file():
            return folder, builtin
    return None


def check_pack_files(look_dir: Path) -> None:
    """Check every file of a pack: kind, path shape, count and total size.

    Raises :class:`LookManifestError`. Symbolic links are refused, so a pack
    can never point outside its own folder.
    """
    look_dir = Path(look_dir)
    total = 0
    count = 0
    for current, dirs, files in os.walk(look_dir, followlinks=False):
        for name in list(dirs):
            if os.path.islink(os.path.join(current, name)):
                raise LookManifestError(f"The pack contains a link: {name}.")
        for name in files:
            full = os.path.join(current, name)
            rel = os.path.relpath(full, look_dir).replace(os.sep, "/")
            if os.path.islink(full):
                raise LookManifestError(f"The pack contains a link: {rel}.")
            if not is_safe_rel_path(rel):
                raise LookManifestError(f"The file name '{rel}' is not allowed.")
            if suffix_of(rel) not in ALLOWED_TYPES:
                raise LookManifestError(f"The file kind of '{rel}' is not allowed in a look.")
            count += 1
            if count > MAX_PACK_FILES:
                raise LookManifestError(f"A look may hold at most {MAX_PACK_FILES} files.")
            total += os.path.getsize(full)
            if total > MAX_PACK_BYTES:
                mb = MAX_PACK_BYTES // (1024 * 1024)
                raise LookManifestError(f"A look may be at most {mb} MB.")


def read_manifest(look_dir: Path, *, builtin: bool, check_files: bool = True) -> LookManifest:
    """Parse and check ``look.json`` in ``look_dir``; raise :class:`LookManifestError`."""
    look_dir = Path(look_dir)
    path = look_dir / MANIFEST_NAME
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise LookManifestError("look.json is too large.")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise LookManifestError("The look folder has no look.json.") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LookManifestError("look.json could not be read as JSON.") from exc
    manifest = parse_manifest(data, builtin=builtin)
    if manifest.id != look_dir.name:
        raise LookManifestError(
            f"look.json names the id '{manifest.id}' but its folder is '{look_dir.name}'."
        )
    for rel in (manifest.entry, manifest.preview):
        if not (look_dir / rel).is_file():
            raise LookManifestError(f"The pack has no file '{rel}'.")
    if check_files:
        check_pack_files(look_dir)
    return manifest


def _list_root(root: Path, *, builtin: bool) -> list[LookManifest]:
    try:
        folders = [p for p in root.iterdir() if p.is_dir() and LOOK_ID_RE.match(p.name)]
    except FileNotFoundError:
        return []
    except OSError as exc:
        _log.warning("looks folder %s is unreadable: %s", root, exc)
        return []
    manifests: list[LookManifest] = []
    for folder in folders:
        try:
            manifests.append(read_manifest(folder, builtin=builtin))
        except LookManifestError as exc:
            _log.warning("look %r skipped: %s", folder.name, exc)
    manifests.sort(key=lambda m: (m.name.casefold(), m.id))
    return manifests


def list_looks(*, data_dir: Path | None = None) -> list[LookManifest]:
    """Built-in looks, then installed ones (minus id clashes). Never raises."""
    builtin = _list_root(builtin_root(), builtin=True)
    taken = {m.id for m in builtin}
    installed = [m for m in _list_root(custom_root(data_dir), builtin=False) if m.id not in taken]
    return builtin + installed


def resolve_file(look_dir: Path, rel_path: str) -> tuple[Path, str] | None:
    """Return ``(path, media_type)`` for a file inside a pack, or ``None``.

    ``None`` for a malformed path, a kind outside :data:`ALLOWED_TYPES`, a
    link, or a file that does not exist.
    """
    if not is_safe_rel_path(rel_path):
        return None
    media_type = ALLOWED_TYPES.get(suffix_of(rel_path))
    if media_type is None:
        return None
    base = os.path.normpath(os.path.abspath(look_dir))
    full = os.path.normpath(os.path.join(base, *rel_path.split("/")))
    if not full.startswith(base + os.sep):
        return None
    if os.path.islink(full) or not os.path.isfile(full):
        return None
    return Path(full), media_type
