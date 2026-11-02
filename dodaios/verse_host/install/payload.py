"""Verse packages on disk: tree, full install, delta apply, rollback, removal (WP22.4/22.5).

A full package (``Verse-<Platform>-<version>.tar``) holds ``verse-tree.json``
and ``files/<path>``. A delta (``Verse-<Platform>-<old>-to-<new>.delta.tar``)
also holds ``verse-delta.json`` and only the changed or added files. A new
version is assembled beside the running one in a staging folder, every file is
checked against the target tree (100 % hash match), and only then does
``current.json`` move. Any failure discards the staging folder, so the
previous version stays the running one: that is the rollback.

Extraction copies file data only: no links, modes, devices or paths that could
leave the folder are ever taken from an archive.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any

from dodaios.verse_host.install.layout import (
    VERSE_CURRENT_FILE,
    VerseInstallError,
    check_version,
    read_current,
    version_dir,
    write_current,
)

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_ENTRIES",
    "VERSE_DELTA_FILE",
    "VERSE_DELTA_SCHEMA",
    "VERSE_TREE_FILE",
    "VERSE_TREE_SCHEMA",
    "apply_delta",
    "build_tree",
    "check_tree",
    "ensure_healthy",
    "entry_path",
    "folder_bytes",
    "install_full",
    "read_package_tree",
    "rollback",
    "sha256_file",
    "tree_digest",
    "uninstall",
    "verify_tree",
]

VERSE_TREE_SCHEMA = "verse.tree/1"
VERSE_DELTA_SCHEMA = "verse.delta/1"
VERSE_TREE_FILE = "verse-tree.json"
VERSE_DELTA_FILE = "verse-delta.json"
#: A tree or delta header lists a few thousand files at most.
MAX_HEADER_BYTES = 16_000_000
#: The launcher of a staged Unreal build, per platform. A tree may name another.
DEFAULT_ENTRIES = {"Win64": "Verse.exe", "Linux": "Verse.sh"}
_PAYLOAD_PREFIX = "files/"
_SHA256_LENGTH = 64


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def folder_bytes(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


# ------------------------------------------------------------------ the tree
def _safe_relpath(name: Any) -> str:
    """A package path as POSIX text; anything that could leave the folder is refused."""
    text = str(name)
    if not text or "\\" in text or text.startswith("/") or ":" in text or "\0" in text:
        raise VerseInstallError(f"unsafe path in the Verse package: {name!r}")
    if any(part in {"", ".", ".."} for part in text.split("/")):
        raise VerseInstallError(f"unsafe path in the Verse package: {name!r}")
    return text


def build_tree(
    folder: Path, *, version: str, platform: str, entry: str | None = None
) -> dict[str, Any]:
    """Size and SHA-256 of every file below ``folder`` (``verse-tree.json`` excluded).

    ``entry`` is the file the launcher starts; by default the platform's
    Unreal launcher when the build has one.
    """
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        if rel == VERSE_TREE_FILE:
            continue
        files[_safe_relpath(rel)] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    chosen = entry if entry is not None else DEFAULT_ENTRIES.get(platform)
    if chosen is not None and chosen not in files:
        if entry is not None:
            raise VerseInstallError(f"the entry {entry!r} is not part of the build")
        chosen = None
    return {
        "schema": VERSE_TREE_SCHEMA,
        "version": check_version(version),
        "platform": platform,
        "entry": chosen,
        "files": files,
    }


def tree_digest(tree: dict[str, Any]) -> str:
    """SHA-256 of a tree's canonical JSON: what a delta names as its base."""
    canonical = json.dumps(tree, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def check_tree(tree: Any) -> dict[str, Any]:
    if not isinstance(tree, dict) or tree.get("schema") != VERSE_TREE_SCHEMA:
        raise VerseInstallError(f"{VERSE_TREE_FILE} is not a {VERSE_TREE_SCHEMA} document")
    check_version(tree.get("version"))
    if not isinstance(tree.get("platform"), str) or not tree["platform"]:
        raise VerseInstallError(f"{VERSE_TREE_FILE} names no platform")
    files = tree.get("files")
    if not isinstance(files, dict) or not files:
        raise VerseInstallError(f"{VERSE_TREE_FILE} lists no files")
    for rel, entry in files.items():
        _safe_relpath(rel)
        if not isinstance(entry, dict):
            raise VerseInstallError(f"{VERSE_TREE_FILE} has a bad entry for {rel}")
        digest = str(entry.get("sha256", ""))
        if len(digest) != _SHA256_LENGTH or not isinstance(entry.get("size"), int):
            raise VerseInstallError(f"{VERSE_TREE_FILE} has a bad entry for {rel}")
    launcher = tree.get("entry")
    if launcher is not None and launcher not in files:
        raise VerseInstallError(f"{VERSE_TREE_FILE} names an entry that is not in the package")
    return tree


def _read_tree(folder: Path) -> dict[str, Any]:
    try:
        return check_tree(json.loads((folder / VERSE_TREE_FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise VerseInstallError(f"{folder / VERSE_TREE_FILE} cannot be read: {exc}") from exc


def verify_tree(
    folder: Path, tree: dict[str, Any] | None = None, *, hashes: bool = True
) -> list[str]:
    """Every way ``folder`` differs from its tree; empty means a 100 % match.

    ``hashes=False`` compares sizes only, a cheap check for every launch.
    """
    try:
        expected = check_tree(tree) if tree is not None else _read_tree(folder)
    except VerseInstallError as exc:  # the reason becomes the reported problem
        return [str(exc)]
    problems: list[str] = []
    for rel, entry in expected["files"].items():
        path = folder / rel
        if not path.is_file():
            problems.append(f"missing {rel}")
        elif path.stat().st_size != entry["size"]:
            problems.append(f"size mismatch {rel}")
        elif hashes and sha256_file(path) != entry["sha256"]:
            problems.append(f"hash mismatch {rel}")
    listed = set(expected["files"])
    for path in folder.rglob("*"):
        if path.is_file():
            rel = path.relative_to(folder).as_posix()
            if rel != VERSE_TREE_FILE and rel not in listed:
                problems.append(f"unexpected {rel}")
    return problems


def entry_path(root: Path) -> Path | None:
    """The launcher file of the running version, or ``None`` when nothing is installed."""
    current = read_current(root)
    if current is None or not current.get("entry"):
        return None
    return version_dir(root, current["version"]) / str(current["entry"])


# --------------------------------------------------------------- switching
def _prune_versions(root: Path, keep: set[str]) -> None:
    versions = root / "versions"
    if not versions.is_dir():
        return
    for item in versions.iterdir():
        if item.is_dir() and item.name not in keep:
            shutil.rmtree(item, ignore_errors=True)


def _staging_dir(root: Path, version: str) -> Path:
    staging = root / "versions" / f".staging-{version}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    return staging


def _mark_executable(folder: Path, tree: dict[str, Any]) -> None:
    """The launcher and Linux binaries need the execute bit; tar modes are never trusted."""
    if os.name == "nt":
        return
    for rel in tree["files"]:
        if rel == tree.get("entry") or rel.endswith(".sh") or "/Binaries/Linux/" in f"/{rel}":
            path = folder / rel
            path.chmod(path.stat().st_mode | 0o755)


def _replace(source: Path, target: Path, *, attempts: int = 6) -> None:
    """``os.replace`` that rides out a short Windows sharing violation.

    A virus scanner or the search indexer holds a freshly written folder for a
    moment; a rename in that moment fails with access denied and succeeds a
    few hundred milliseconds later.
    """
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def _switch(root: Path, staging: Path, tree: dict[str, Any]) -> dict[str, Any]:
    """Make the verified ``staging`` folder the running version; keep one previous."""
    version = tree["version"]
    current = read_current(root)
    previous = current["version"] if current else None
    if previous == version:
        previous = current.get("previous") if current else None
    target = version_dir(root, version)
    aside: Path | None = None
    if target.exists():
        # Reinstalling the running version (a repair): move the old folder
        # aside first, so current.json never points at a missing folder and a
        # failed swap puts it back.
        aside = target.with_name(f".replaced-{version}-{os.getpid()}")
        shutil.rmtree(aside, ignore_errors=True)
        _replace(target, aside)
    try:
        _replace(staging, target)
    except OSError:
        if aside is not None:
            _replace(aside, target, attempts=20)
        raise
    if aside is not None:
        shutil.rmtree(aside, ignore_errors=True)
    write_current(root, version, previous, tree["platform"], entry=tree.get("entry"))
    _prune_versions(root, {version, *([previous] if previous else [])})
    return {"version": version, "previous": previous}


# ----------------------------------------------------------- tar extraction
def _tar_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        if member.isdir():
            continue
        if not member.isfile():
            raise VerseInstallError(f"the Verse package holds a non-file entry: {member.name!r}")
        members[_safe_relpath(member.name)] = member
    return members


def _tar_json(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> Any:
    member = members.get(name)
    handle = archive.extractfile(member) if member is not None else None
    if member is None or handle is None or member.size > MAX_HEADER_BYTES:
        raise VerseInstallError(f"the Verse package has no usable {name}")
    try:
        return json.loads(handle.read().decode("utf-8"))
    except ValueError as exc:
        raise VerseInstallError(f"{name} in the Verse package is not JSON: {exc}") from exc


def read_package_tree(source: Path) -> dict[str, Any]:
    """The tree of a full package tar or of an installed version folder."""
    if source.is_dir():
        return _read_tree(source)
    try:
        with tarfile.open(source, "r:") as archive:
            return check_tree(_tar_json(archive, _tar_members(archive), VERSE_TREE_FILE))
    except (OSError, tarfile.TarError) as exc:
        raise VerseInstallError(f"{source.name} is not a Verse package: {exc}") from exc


def _extract(
    archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], rel: str, dest: Path
) -> None:
    member = members.get(_PAYLOAD_PREFIX + rel)
    source = archive.extractfile(member) if member is not None else None
    if source is None:
        raise VerseInstallError(f"the Verse package lacks {rel}")
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with source, target.open("wb") as handle:
        shutil.copyfileobj(source, handle, 1024 * 1024)


def _link_or_copy(source: Path, target: Path) -> None:
    """Reuse an unchanged file of the running version: a hard link, else a copy.

    Nothing ever writes into a package file after it is verified, so a file
    shared by two versions through a hard link stays correct for both.
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


def _fail_and_discard(staging: Path, message: str, *, previous: str | None) -> VerseInstallError:
    shutil.rmtree(staging, ignore_errors=True)
    kept = f"; rolled back, version {previous} stays installed" if previous else ""
    log.warning("[verse] %s%s", message, kept)
    return VerseInstallError(f"{message}{kept}")


def _verified_switch(
    root: Path, staging: Path, tree: dict[str, Any], *, what: str, previous: str | None
) -> dict[str, Any]:
    _write_tree(staging, tree)
    problems = verify_tree(staging, tree)
    if problems:
        raise _fail_and_discard(
            staging,
            f"{what} failed verification ({len(problems)} files: {', '.join(problems[:3])})",
            previous=previous,
        )
    _mark_executable(staging, tree)
    try:
        return _switch(root, staging, tree)
    except OSError as exc:
        raise _fail_and_discard(
            staging, f"{what} could not be switched in: {exc}", previous=previous
        ) from exc


def _check_expected(tree: dict[str, Any], expected: dict[str, Any] | None) -> None:
    """The package must be the one the signed manifest describes."""
    if not expected:
        return
    if expected.get("version") and tree["version"] != expected["version"]:
        raise VerseInstallError(
            f"the package is Verse {tree['version']}, the manifest names {expected['version']}"
        )
    if expected.get("platform") and tree["platform"] != expected["platform"]:
        raise VerseInstallError("the package is for another platform than the manifest names")
    if expected.get("tree_sha256") and tree_digest(tree) != expected["tree_sha256"]:
        raise VerseInstallError("the package's file list is not the one the manifest signed")


# ---------------------------------------------------------- install, delta
def install_full(
    root: Path, package: Path, *, expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Install a full package tar as the running version. Verified before it switches."""
    root.mkdir(parents=True, exist_ok=True)
    current = read_current(root)
    previous = current["version"] if current else None
    try:
        archive = tarfile.open(package, "r:")
    except (OSError, tarfile.TarError) as exc:
        raise VerseInstallError(f"{package.name} is not a Verse package: {exc}") from exc
    with archive:
        members = _tar_members(archive)
        tree = check_tree(_tar_json(archive, members, VERSE_TREE_FILE))
        _check_expected(tree, expected)
        staging = _staging_dir(root, tree["version"])
        try:
            for rel in tree["files"]:
                _extract(archive, members, rel, staging)
        except (OSError, tarfile.TarError, VerseInstallError) as exc:
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
        raise VerseInstallError(f"{VERSE_DELTA_FILE} is not a {VERSE_DELTA_SCHEMA} document")
    if header.get("from") != previous:
        raise VerseInstallError(
            f"this delta updates Verse {header.get('from')}, but {previous} is installed"
        )
    platform = header.get("platform")
    if platform != current.get("platform") or platform != tree["platform"]:
        raise VerseInstallError("this delta is for another platform")
    if header.get("to") != tree["version"]:
        raise VerseInstallError(f"{VERSE_DELTA_FILE} and {VERSE_TREE_FILE} name other versions")
    if header.get("from_tree_sha256") != tree_digest(base_tree):
        raise VerseInstallError(
            f"the installed Verse {previous} is not the build this delta was made from"
        )
    changed = [_safe_relpath(p) for p in header.get("files", [])]
    reused = [_safe_relpath(p) for p in header.get("reuse", [])]
    if set(changed) | set(reused) != set(tree["files"]) or set(changed) & set(reused):
        raise VerseInstallError(f"{VERSE_DELTA_FILE} does not cover the target tree exactly")
    missing = [rel for rel in reused if rel not in base_tree["files"]]
    if missing:
        raise VerseInstallError(f"{missing[0]} is not part of the installed Verse {previous}")
    return changed, reused


def apply_delta(
    root: Path, delta: Path, *, expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Apply a delta tar on top of the running version. Fail closed, roll back.

    The new version is assembled from the delta's files plus hard links to the
    running version's unchanged files, then checked against the target tree.
    A corrupted chunk, a wrong base version or a missing file leaves the
    running version untouched and raises :class:`VerseInstallError`.
    """
    current = read_current(root)
    if current is None:
        raise VerseInstallError("no Verse is installed; a delta needs the version it was made from")
    previous = current["version"]
    base_dir = version_dir(root, previous)
    try:
        archive = tarfile.open(delta, "r:")
    except (OSError, tarfile.TarError) as exc:
        raise VerseInstallError(f"{delta.name} is not a Verse delta: {exc}") from exc
    with archive:
        members = _tar_members(archive)
        header = _tar_json(archive, members, VERSE_DELTA_FILE)
        tree = check_tree(_tar_json(archive, members, VERSE_TREE_FILE))
        _check_expected(tree, expected)
        changed, reused = _check_delta_header(header, tree, current, _read_tree(base_dir))
        staging = _staging_dir(root, tree["version"])
        try:
            for rel in changed:
                _extract(archive, members, rel, staging)
            for rel in reused:
                _link_or_copy(base_dir / rel, staging / rel)
        except (OSError, tarfile.TarError, VerseInstallError) as exc:
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


def rollback(root: Path) -> dict[str, Any]:
    """Make the previous version the running one again, after verifying it."""
    current = read_current(root)
    if current is None or not current.get("previous"):
        raise VerseInstallError("there is no previous Verse version to roll back to")
    previous = current["previous"]
    folder = version_dir(root, previous)
    problems = verify_tree(folder)
    if problems:
        raise VerseInstallError(
            f"the previous Verse {previous} is damaged too ({', '.join(problems[:3])})"
        )
    tree = _read_tree(folder)
    write_current(root, previous, None, str(current.get("platform", "")), entry=tree.get("entry"))
    log.warning("[verse] rolled back from %s to %s", current["version"], previous)
    return {"version": previous, "rolled_back_from": current["version"]}


def ensure_healthy(root: Path, *, hashes: bool = False) -> dict[str, Any]:
    """Check the running version; roll back to the previous one when it is damaged."""
    current = read_current(root)
    if current is None:
        return {"status": "not_installed"}
    problems = verify_tree(version_dir(root, current["version"]), hashes=hashes)
    if not problems:
        return {"status": "ok", "version": current["version"]}
    try:
        rolled = rollback(root)
    except VerseInstallError as exc:  # reported to the caller as status broken
        return {
            "status": "broken",
            "version": current["version"],
            "problems": problems[:10],
            "detail": str(exc),
        }
    return {"status": "rolled_back", "problems": problems[:10], **rolled}


def uninstall(root: Path) -> dict[str, Any]:
    """Remove every installed version and download; the Verse is ``not_installed`` again.

    The pointer goes first, so a removal stopped half-way (a file a running
    game still holds on Windows) already reads as not installed, and the next
    removal or install clears what is left.
    """
    before = folder_bytes(root)
    (root / VERSE_CURRENT_FILE).unlink(missing_ok=True)
    leftovers: list[str] = []
    for name in ("versions", "downloads"):
        folder = root / name
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
            if folder.exists():
                leftovers.append(str(folder))
    freed = before - folder_bytes(root)
    if leftovers:
        log.warning("[verse] removal left %s behind (files in use?)", ", ".join(leftovers))
    else:
        try:
            root.rmdir()  # only when nothing else (crash reports, settings) lives there
        except OSError:
            log.debug("[verse] %s keeps other files; left in place", root)
    log.info("[verse] removed the Verse (%d bytes freed)", freed)
    return {"status": "not_installed", "freed_bytes": freed, "leftovers": leftovers}
