"""Read-only knowledge sources searched next to the active vault.

``[wiki_integration].external_sources`` lists folders Jarvis may read, search
and index for recall, but never write. One writer, many readers: every write
goes to ``vault_root``; an external source only ever feeds search hits.

Each entry is either a path string or ``{ name = "...", path = "..." }``. The
name is what a hit reports as its ``source``; without one it is derived from
the folder name.

The write ban is enforced, not a convention: the wiki writer, the backup
manager and the agents' vault resolution call :func:`guard_write`, which
raises :class:`ExternalSourceWriteDenied` for any path inside a registered
source. The FTS index of a source lives under ``data/``, never in the source.
"""
from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WRITE_DENIED_EXTERNAL_SOURCE = "WRITE_DENIED_EXTERNAL_SOURCE"

SOURCE_TYPE_CANONICAL = "canonical"
SOURCE_TYPE_EXTERNAL = "external"
CANONICAL_SOURCE = "dodaios"


class ExternalSourceWriteDenied(PermissionError):
    """A write was aimed at a read-only external source."""

    code = WRITE_DENIED_EXTERNAL_SOURCE

    def __init__(self, path: Path, source: ExternalSource) -> None:
        super().__init__(
            f"{WRITE_DENIED_EXTERNAL_SOURCE}: {path} is inside the read-only "
            f"external source {source.name!r} ({source.path})"
        )
        self.path = path
        self.source = source


@dataclass(frozen=True, slots=True)
class ExternalSource:
    name: str
    path: Path


_lock = threading.Lock()
_registered: tuple[ExternalSource, ...] = ()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "external"


def _resolve(raw: Any) -> Path:
    # Not resolve_vault_root: that one records its result as the app's last
    # resolution, and a source must never be mistaken for the active vault.
    from jarvis.core.paths import repo_root

    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = repo_root() / path
    return path.resolve(strict=False)


def parse_sources(entries: Any) -> tuple[ExternalSource, ...]:
    """Turn the configured entries into sources; blank entries are skipped."""
    sources: list[ExternalSource] = []
    for entry in entries or ():
        if isinstance(entry, dict):
            raw_path, name = entry.get("path"), entry.get("name")
        else:
            raw_path, name = getattr(entry, "path", entry), getattr(entry, "name", None)
        if raw_path is None or not str(raw_path).strip():
            continue
        path = _resolve(raw_path)
        sources.append(ExternalSource(name=_slug(str(name or path.name)), path=path))
    return tuple(sources)


def register_from_config(cfg: Any) -> tuple[ExternalSource, ...]:
    """Read ``[wiki_integration].external_sources`` and arm the write guard.

    Called wherever the app resolves its vault, so the guard is armed before
    any writer for that vault exists.
    """
    wiki_cfg = getattr(cfg, "wiki_integration", None)
    if wiki_cfg is None:
        # A config without the section says nothing; keep what is armed.
        return registered()
    sources = parse_sources(getattr(wiki_cfg, "external_sources", None))
    register(sources)
    return sources


def register(sources: tuple[ExternalSource, ...] | list[ExternalSource]) -> None:
    global _registered
    with _lock:
        _registered = tuple(sources)


def registered() -> tuple[ExternalSource, ...]:
    return _registered


def source_containing(path: Path | str) -> ExternalSource | None:
    target = Path(path).resolve(strict=False)
    for source in _registered:
        if target == source.path or target.is_relative_to(source.path):
            return source
    return None


def guard_write(path: Path | str) -> None:
    """Raise :class:`ExternalSourceWriteDenied` when *path* is inside a source."""
    source = source_containing(path)
    if source is not None:
        raise ExternalSourceWriteDenied(Path(path), source)


def index_db_path(source: ExternalSource) -> Path:
    """The source's own FTS database, kept under ``data/`` — never in the source."""
    from jarvis.memory.wiki.db_path import resolve_wiki_db_path

    digest = hashlib.sha1(
        str(source.path).lower().encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:10]
    return resolve_wiki_db_path().parent / "external_sources" / f"{source.name}-{digest}.db"


__all__ = [
    "CANONICAL_SOURCE",
    "SOURCE_TYPE_CANONICAL",
    "SOURCE_TYPE_EXTERNAL",
    "WRITE_DENIED_EXTERNAL_SOURCE",
    "ExternalSource",
    "ExternalSourceWriteDenied",
    "guard_write",
    "index_db_path",
    "parse_sources",
    "register",
    "register_from_config",
    "registered",
    "source_containing",
]
