"""The "live" world: a copy of the person's memory that benchmark runs read.

A run must not touch the live memory, and both runs of a pair must see the same
memory. So each night starts by copying the vault file into the kernel's own
folder (SQLite's online backup: safe while the app writes) and opening that
copy with a clock that stands at the moment of the copy.
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi.bench.recall import RecallWorld

__all__ = ["LIVE_WORLD", "SNAPSHOT_NAME", "LiveWorld", "take_snapshot"]

#: Name of the world own tasks run in (``Task.payload["world"]``).
LIVE_WORLD: Final = "live"
SNAPSHOT_NAME: Final = "vault-snapshot.db"


def take_snapshot(vault_path: Path, folder: Path) -> Path | None:
    """Copy the vault into ``folder``. ``None`` when there is no vault to copy."""
    source_path = Path(vault_path)
    if not source_path.is_file():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target_path = folder / SNAPSHOT_NAME
    fresh = folder / (SNAPSHOT_NAME + ".new")
    for leftover in (fresh, Path(str(fresh) + "-wal"), Path(str(fresh) + "-shm")):
        with contextlib.suppress(FileNotFoundError):
            leftover.unlink()
    source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        target = sqlite3.connect(fresh)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    # The copy carries no journal of its own; the old copy's journal must not meet it.
    for stale in (Path(str(target_path) + "-wal"), Path(str(target_path) + "-shm")):
        with contextlib.suppress(FileNotFoundError):
            stale.unlink()
    fresh.replace(target_path)
    return target_path


class LiveWorld:
    """The night's copy of the memory, opened on demand and closed with the night."""

    def __init__(self, vault_path: Path, folder: Path) -> None:
        self._vault_path = Path(vault_path)
        self._folder = Path(folder)
        self._vault: MemoryVault | None = None
        self._taken_at = ""

    def refresh(self) -> bool:
        """Take a new copy. False when there is no vault (nothing to run against)."""
        self.close()
        path = take_snapshot(self._vault_path, self._folder)
        if path is None:
            return False
        self._taken_at = datetime.now(UTC).isoformat(timespec="seconds")
        taken_at = self._taken_at
        self._vault = MemoryVault(path, clock=lambda: taken_at)
        return True

    @property
    def vault(self) -> MemoryVault | None:
        return self._vault

    def worlds(self) -> dict[str, RecallWorld]:
        """What the benchmark runner needs: the live world, when a copy is open."""
        if self._vault is None:
            return {}
        return {LIVE_WORLD: RecallWorld(self._vault, {})}

    def close(self) -> None:
        if self._vault is not None:
            self._vault.close()
            self._vault = None
