"""Canonical SQLite path resolution for every wiki consumer."""
from __future__ import annotations

from pathlib import Path

from dodaios.core.paths import repo_root, runtime_data_dir


def resolve_wiki_db_path(data_dir: str | Path | None = None) -> Path:
    """Return one absolute ``jarvis.db`` path independent of process CWD.

    A relative ``data_dir`` is anchored at the checkout. Without one, the
    runtime data dir (``JARVIS_DATA_DIR`` or ``<checkout>/data``, #458).
    """
    raw = Path(data_dir) if data_dir is not None else runtime_data_dir()
    directory = raw if raw.is_absolute() else repo_root() / raw
    return (directory / "jarvis.db").resolve(strict=False)


__all__ = ["resolve_wiki_db_path"]
