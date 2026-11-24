"""Export and import of the personal memory vault (ADR-0044).

Two outputs:

- **Bundle** (lossless, re-importable), an open folder layout:
  ``manifest.json``, ``items/<kind>.jsonl``,
  ``entities.jsonl``, ``audit/log.jsonl``, ``audit/tombstones.jsonl`` and
  ``CHECKSUMS``. As a folder or a zip file.
- **Markdown** (readable): ``MEMORY.md`` plus one file per kind, which opens in
  any Markdown editor, Obsidian included.

Import applies tombstones first, then inserts every memory whose id and
content are unknown, so importing the same bundle twice changes nothing.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dodaios.memory.vault.models import KINDS, Memory
from dodaios.memory.vault.store import MemoryVault

FORMAT = "portable-memory"
FORMAT_VERSION = "1.0"
APP = "dodaios"

# A bundle is text: one list per kind of memory and a few small files. The
# limits below are far above any real vault. They keep a crafted archive from
# filling memory or keeping the import busy for minutes.
MAX_BUNDLE_FILE_BYTES = 200 * 1024 * 1024
MAX_BUNDLE_TOTAL_BYTES = 400 * 1024 * 1024
MAX_BUNDLE_ENTRIES = 2000
#: A zip's own list of its entries (the central directory). ``zipfile`` builds
#: one object per entry while it opens an archive, before any limit here could
#: count them, so the declared size of that list is checked first.
MAX_BUNDLE_DIRECTORY_BYTES = 512 * 1024

#: The files an import reads. Anything else in a bundle (the readable copy and
#: ``memories.json`` of the "everything" download, what an archive tool adds)
#: is never opened.
_BUNDLE_FILES = frozenset(
    {
        "manifest.json",
        "CHECKSUMS",
        "entities.jsonl",
        "audit/log.jsonl",
        "audit/tombstones.jsonl",
    }
)
_ITEMS_FILE = re.compile(r"items/[a-z0-9_-]{1,64}\.jsonl")

_KIND_TITLES = {
    "profile": "About me",
    "preference": "Preferences",
    "relationship": "People",
    "project": "Projects",
    "procedural": "Standing instructions",
    "episode": "Moments",
    "reference": "Where things are",
    "ephemeral": "For now",
}


class BundleError(ValueError):
    """The bundle is not one this app can read, or it was altered."""


@dataclass
class ImportReport:
    added: int = 0
    skipped: int = 0
    forgotten: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "skipped": self.skipped,
            "forgotten": self.forgotten,
            "errors": list(self.errors),
        }


# -- bundle --------------------------------------------------------------


def bundle_files(vault: MemoryVault) -> dict[str, bytes]:
    """Every file of a bundle, keyed by its path inside the bundle."""
    memories = vault.list(include_closed=True)
    files: dict[str, bytes] = {}
    for kind in KINDS:
        rows = [m.to_dict() for m in memories if m.kind == kind]
        if rows:
            files[f"items/{kind}.jsonl"] = _jsonl(rows)
    entities = [
        {"id": e["id"], "name": e["name"], "created_at": e["created_at"]} for e in vault.entities()
    ]
    files["entities.jsonl"] = _jsonl(entities)
    files["audit/log.jsonl"] = _jsonl(vault.audit_log())
    files["audit/tombstones.jsonl"] = _jsonl(vault.tombstones())
    stats = vault.stats()
    manifest = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "app": APP,
        "vault_id": vault.vault_id,
        "created_at": vault.now(),
        "counts": {
            "memories": len(memories),
            "current": stats["current"],
            "entities": stats["entities"],
            "tombstones": stats["forgotten"],
        },
        "kinds": list(KINDS),
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    files["CHECKSUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    return files


def export_bundle(vault: MemoryVault, dest: str | Path) -> Path:
    """Write a bundle. A path ending in ``.zip`` gets a zip file, else a folder."""
    dest = Path(dest)
    files = bundle_files(vault)
    if dest.suffix.lower() == ".zip":
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_zip(files))
        return dest
    for name, data in files.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return dest


def export_zip_bytes(vault: MemoryVault) -> bytes:
    return _zip(bundle_files(vault))


def everything_zip_bytes(vault: MemoryVault) -> bytes:
    """One download with all of it: the lossless bundle (re-importable as is),
    ``memories.json`` (a plain list of the current memories) and
    ``readable/`` (the Markdown pages). The extra files sit outside
    ``CHECKSUMS``, so the zip still imports as a bundle.
    """
    files = bundle_files(vault)
    current = [
        {
            "text": m.text,
            "kind": m.kind,
            "scope": m.scope,
            "origin": m.origin,
            "pinned": m.pinned,
            "entities": list(m.entities),
            "recorded_at": m.recorded_at,
            "valid_from": m.valid_from,
            "valid_to": m.valid_to,
            "due_at": m.due_at,
            "id": m.id,
        }
        for m in vault.list()
    ]
    files["memories.json"] = json.dumps(
        {"memories": current}, ensure_ascii=False, indent=2
    ).encode()
    for name, text in markdown_files(vault).items():
        files[f"readable/{name}"] = text.encode()
    return _zip(files)


def read_bundle(src: str | Path | bytes) -> dict[str, bytes]:
    """Load a bundle from a folder, a zip path or zip bytes and verify it."""
    if isinstance(src, bytes):
        files = _unzip(src)
    else:
        path = Path(src)
        if path.is_dir():
            files = _read_folder(path)
        else:
            files = _unzip(path.read_bytes())
    _verify(files)
    return files


def import_bundle(vault: MemoryVault, src: str | Path | bytes) -> ImportReport:
    files = read_bundle(src)
    report = ImportReport()
    for row in _rows(files.get("audit/tombstones.jsonl", b"")):
        try:
            vault.apply_tombstone(
                str(row["id"]),
                str(row["content_hash"]),
                str(row.get("forgotten_at") or vault.now()),
                str(row.get("reason") or "imported"),
            )
            report.forgotten += 1
        except (KeyError, TypeError) as exc:
            report.errors.append(f"tombstone: {exc}")
    memories: list[Memory] = []
    for name in sorted(files):
        if name.startswith("items/") and name.endswith(".jsonl"):
            for row in _rows(files[name]):
                try:
                    memories.append(Memory.from_dict(row))
                except (TypeError, ValueError) as exc:
                    report.errors.append(f"{name}: {exc}")
    # Older versions first, so a row is inserted after the one it replaces.
    memories.sort(key=lambda m: (m.recorded_at, m.id))
    for memory in memories:
        if vault.has(memory.id) or vault.has_hash_version(memory):
            report.skipped += 1
            continue
        try:
            if vault.insert_imported(memory):
                report.added += 1
            else:
                report.skipped += 1
        except ValueError as exc:
            report.errors.append(f"{memory.id}: {exc}")
    return report


# -- markdown ------------------------------------------------------------


def markdown_files(vault: MemoryVault) -> dict[str, str]:
    """A readable copy: ``MEMORY.md`` and one page per kind."""
    current = vault.list()
    stats = vault.stats()
    files: dict[str, str] = {}
    index = [
        "# My memory",
        "",
        f"Exported {vault.now()} · {stats['current']} current memories.",
        "",
    ]
    for kind in KINDS:
        items = [m for m in current if m.kind == kind]
        if not items:
            continue
        title = _KIND_TITLES[kind]
        index.append(f"- [{title}]({kind}.md) — {len(items)}")
        page = [
            "---",
            f"kind: {kind}",
            f"count: {len(items)}",
            "---",
            "",
            f"# {title}",
            "",
        ]
        for m in sorted(items, key=lambda m: m.recorded_at):
            line = f"- {m.text}"
            details = []
            if m.entities:
                details.append(", ".join(m.entities))
            # An imported memory's start date is the import, not when it became true.
            if m.valid_from and m.origin != "imported":
                details.append(f"since {m.valid_from[:10]}")
            if m.valid_to:
                details.append(f"until {m.valid_to[:10]}")
            if m.pinned:
                details.append("pinned")
            if details:
                line += f" *({'; '.join(details)})*"
            page.append(f"{line} <!-- {m.id} -->")
        files[f"{kind}.md"] = "\n".join(page) + "\n"
    files["MEMORY.md"] = "\n".join(index) + "\n"
    return files


def export_markdown(vault: MemoryVault, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name, text in markdown_files(vault).items():
        (dest / name).write_text(text, encoding="utf-8")
    return dest


# -- helpers -------------------------------------------------------------


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode()


def _rows(data: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    return buffer.getvalue()


def _is_bundle_file(name: str) -> bool:
    return name in _BUNDLE_FILES or _ITEMS_FILE.fullmatch(name) is not None


def _admit(name: str, size: int, total: int) -> int:
    """Count one bundle file of ``size`` bytes against the limits; the new total."""
    if size > MAX_BUNDLE_FILE_BYTES:
        raise BundleError(f"file too large in bundle: {name}")
    total += size
    if total > MAX_BUNDLE_TOTAL_BYTES:
        raise BundleError("bundle too large: its files exceed the size a memory bundle may have")
    return total


def _read_folder(path: Path) -> dict[str, bytes]:
    """The bundle files of an unpacked bundle; nothing else in the folder is read."""
    candidates = [path / name for name in sorted(_BUNDLE_FILES)]
    candidates += sorted((path / "items").glob("*.jsonl"))
    files: dict[str, bytes] = {}
    total = 0
    for candidate in candidates:
        name = candidate.relative_to(path).as_posix()
        if not candidate.is_file() or not _is_bundle_file(name):
            continue
        total = _admit(name, candidate.stat().st_size, total)
        files[name] = candidate.read_bytes()
    return files


def _declared_directory_bytes(data: bytes) -> int | None:
    """How large the zip says its list of entries is; ``None`` when it cannot tell.

    Asked of the standard library's own end-record reader. It is the record
    ``ZipFile`` goes on to use, in its ZIP64 form too, so the two cannot
    disagree about which record counts.
    """
    reader = getattr(zipfile, "_EndRecData", None)
    if reader is None:  # pragma: no cover - an interpreter without the reader
        return None
    try:
        record = reader(io.BytesIO(data))
        return None if not record else int(record[getattr(zipfile, "_ECD_SIZE", 5)])
    except (zipfile.BadZipFile, OSError, IndexError, TypeError, ValueError):
        # Not a zip, or a record it cannot read: ZipFile says so below.
        return None


def _unzip(data: bytes) -> dict[str, bytes]:
    directory = _declared_directory_bytes(data)
    if directory is not None and directory > MAX_BUNDLE_DIRECTORY_BYTES:
        raise BundleError("too many files in bundle")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_BUNDLE_ENTRIES:
                raise BundleError("too many files in bundle")
            members: dict[str, zipfile.ZipInfo] = {}
            for info in infos:
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise BundleError(f"unsafe path in bundle: {name}")
                members[name] = info
            # A zip of the folder may wrap everything in one top folder.
            if "manifest.json" not in members:
                roots = {n.split("/", 1)[0] for n in members if "/" in n}
                if len(roots) == 1:
                    root = roots.pop() + "/"
                    members = {
                        n[len(root) :]: info for n, info in members.items() if n.startswith(root)
                    }
            files: dict[str, bytes] = {}
            total = 0
            for name, info in members.items():
                if not _is_bundle_file(name):
                    continue
                total = _admit(name, info.file_size, total)
                # The size in the header is a claim; one byte more than it
                # would show a file that is larger than it says.
                with zf.open(info) as handle:
                    content = handle.read(info.file_size + 1)
                if len(content) > info.file_size:
                    raise BundleError(f"file larger than declared in bundle: {name}")
                files[name] = content
            return files
    except zipfile.BadZipFile as exc:
        raise BundleError("not a zip file") from exc


def _verify(files: dict[str, bytes]) -> None:
    if "manifest.json" not in files:
        raise BundleError("no manifest.json; not a memory bundle")
    try:
        manifest = json.loads(files["manifest.json"])
    except json.JSONDecodeError as exc:
        raise BundleError("manifest.json is not JSON") from exc
    if manifest.get("format") != FORMAT:
        raise BundleError(f"unknown bundle format {manifest.get('format')!r}")
    if str(manifest.get("version", "")).split(".")[0] != FORMAT_VERSION.split(".")[0]:
        raise BundleError(f"unsupported bundle version {manifest.get('version')!r}")
    checksums = files.get("CHECKSUMS")
    if checksums is None:
        return
    for line in checksums.decode("utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        if not _is_bundle_file(name):
            # A file this version does not read (a later format may list more):
            # there is nothing of it here to check.
            continue
        if name not in files:
            raise BundleError(f"missing file listed in CHECKSUMS: {name}")
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise BundleError(f"checksum mismatch: {name}")
