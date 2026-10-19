"""A self-doc refresh that would only move the clock writes nothing.

Each write adds a ``log.md`` entry; refreshing on every boot and every
consolidator run once made 1,833 of 2,100 log entries say nothing.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

from dodaios.memory.wiki import self_doc


class _RecordingCurator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def apply_external_updates(self, updates, *, source_label: str, verb: str):  # noqa: ANN001
        self.calls.append(source_label)
        return SimpleNamespace(applied=[update.target_path for update in updates])


def test_refresh_skips_a_page_whose_only_change_is_the_timestamp(tmp_path: Path) -> None:
    (tmp_path / "entities").mkdir()
    curator = _RecordingCurator()
    current = self_doc.render_memory_page(
        vault_root=tmp_path,
        backlog_count=0,
        telemetry_snapshot={},
        now=dt.datetime(2026, 1, 1, 9, 0),
    )
    (tmp_path / self_doc.PAGE_NAME).write_text(current, encoding="utf-8")

    wrote = asyncio.run(
        self_doc.refresh_memory_page(curator=curator, vault_root=tmp_path, journal=None)
    )

    assert wrote is False
    assert curator.calls == []


def test_refresh_writes_when_the_status_really_changed(tmp_path: Path) -> None:
    (tmp_path / "entities").mkdir()
    curator = _RecordingCurator()
    (tmp_path / self_doc.PAGE_NAME).write_text("---\ntype: meta\n---\n# Old\n", encoding="utf-8")

    wrote = asyncio.run(
        self_doc.refresh_memory_page(curator=curator, vault_root=tmp_path, journal=None)
    )

    assert wrote is True
    assert curator.calls == ["self-doc:memory.md"]
