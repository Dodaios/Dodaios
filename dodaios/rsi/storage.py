"""The kernel's SQLite files: a schema version that only ever moves forward.

Everything the assistant learned lives in these files, in the data directory,
and the app is updated often. So a file must survive two things:

* **a newer app.** A schema is a list of steps; step ``i`` brings a file from
  version ``i`` to ``i + 1`` (``PRAGMA user_version``). Opening a file runs the
  steps it has not seen yet, each in one transaction, after a copy of the file
  was put aside (``<name>.before-v<n>``, one copy, the newest migration's).
* **an older app.** A file written by a newer app has a version this code does
  not know. It is opened read-only and says so (:attr:`Db.readonly`), so the
  caller pauses its writing instead of damaging what the newer app stored.

A step is never edited after it shipped: a change to a table is a new step.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Db", "Schema", "open_db"]

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Schema:
    """The steps that build one file. ``steps[i]`` is SQL that takes version ``i`` to ``i + 1``."""

    name: str
    steps: tuple[str, ...]

    @property
    def version(self) -> int:
        return len(self.steps)


@dataclass(slots=True)
class Db:
    """One open kernel file."""

    conn: sqlite3.Connection
    #: True when a newer app wrote this file: read it, never write it.
    readonly: bool = False
    #: The schema version the file has.
    version: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)

    def close(self) -> None:
        with self.lock, contextlib.suppress(sqlite3.Error):
            self.conn.close()


def _connect(path: str, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _put_aside(conn: sqlite3.Connection, path: Path, version: int) -> None:
    """Keep a copy of the file as it was before a migration (the newest migration's only)."""
    copy = path.with_name(f"{path.name}.before-v{version}")
    for old in path.parent.glob(f"{path.name}.before-v*"):
        with contextlib.suppress(OSError):
            old.unlink()
    target = sqlite3.connect(copy)
    try:
        conn.backup(target)
    finally:
        target.close()


def open_db(path: Path | str, schema: Schema) -> Db:
    """Open ``path`` at the schema's version, migrating forward when the file is older."""
    memory = str(path) == ":memory:"
    if not memory:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(str(path))
    have = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if have > schema.version:
        conn.close()
        log.warning(
            "%s was written by a newer version (schema %d, this app knows %d): read-only",
            schema.name,
            have,
            schema.version,
        )
        return Db(_connect(str(path), readonly=True), readonly=True, version=have)
    if not memory:
        conn.execute("PRAGMA journal_mode=WAL")
    if have < schema.version:
        holds_data = bool(
            conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
        )
        if holds_data and not memory:
            _put_aside(conn, Path(path), have)
        for index in range(have, schema.version):
            # One step, one transaction: a step that fails leaves the file at its old version.
            conn.execute("BEGIN")
            try:
                for statement in _statements(schema.steps[index]):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {index + 1}")
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                conn.close()
                raise
    return Db(conn, version=schema.version)


def _statements(script: str) -> list[str]:
    """The statements of a step. ``executescript`` would commit, so they run one by one."""
    out: list[str] = []
    buffer = ""
    for line in script.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                out.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        out.append(buffer.strip())
    return out
