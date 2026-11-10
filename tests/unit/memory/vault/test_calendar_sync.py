"""Calendar appointments become short-lived memories (ADR-0044)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dodaios.memory.vault import calendar_sync
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault


class Clock:
    def __init__(self) -> None:
        self.value = "2026-11-09T09:00:00+00:00"

    def __call__(self) -> str:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(tmp_path: Path, clock: Clock):
    v = MemoryVault(tmp_path / "vault.db", clock=clock)
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


def _event(eid: str, summary: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    return {"id": eid, "summary": summary, "start": start, "end": end, **extra}


def test_events_become_due_ephemeral_memories(vault):
    events = [
        _event(
            "e1",
            "Dentist",
            "2026-11-12T09:00:00+00:00",
            "2026-11-12T10:00:00+00:00",
            location="Main St 1",
        ),
        _event("e2", "Holiday", "2026-11-20", "2026-11-21"),
    ]
    assert calendar_sync.apply_events(vault, events) == {"added": 2, "updated": 0, "ended": 0}
    texts = {m.text: m for m in vault.list(kind="ephemeral")}
    dentist = texts["Appointment: Dentist on 2026-11-12 09:00 (Main St 1)."]
    assert dentist.due_at == "2026-11-12T09:00:00+00:00"
    assert dentist.valid_to == "2026-11-12T10:00:00+00:00"
    assert "Appointment: Holiday on 2026-11-20." in texts
    assert "Dentist" in vault_runtime.turn_block("when is my dentist appointment")
    assert "Dentist" not in vault.profile_block()
    # A second identical sync changes nothing.
    assert calendar_sync.apply_events(vault, events) == {"added": 0, "updated": 0, "ended": 0}


def test_moved_and_cancelled_events(vault, clock):
    calendar_sync.apply_events(
        vault, [_event("e1", "Dentist", "2026-11-12T09:00:00+00:00", "2026-11-12T10:00:00+00:00")]
    )
    moved = [_event("e1", "Dentist", "2026-11-13T09:00:00+00:00", "2026-11-13T10:00:00+00:00")]
    assert calendar_sync.apply_events(vault, moved)["updated"] == 1
    assert [m.text for m in vault.list(kind="ephemeral")] == [
        "Appointment: Dentist on 2026-11-13 09:00."
    ]
    assert calendar_sync.apply_events(vault, [])["ended"] == 1
    assert vault.list(kind="ephemeral") == []


def test_past_appointments_drop_out_on_their_own(vault, clock):
    calendar_sync.apply_events(
        vault, [_event("e1", "Call", "2026-11-09T10:00:00+00:00", "2026-11-09T11:00:00+00:00")]
    )
    clock.value = "2026-11-09T12:00:00+00:00"
    assert vault.list(kind="ephemeral") == []


def test_sync_handles_a_disconnected_calendar(vault):
    async def disconnected(**_: Any) -> dict[str, Any]:
        return {"ok": False, "status": 401, "error": "not connected"}

    async def connected(**_: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "data": {
                "events": [
                    _event(
                        "e1", "Dentist", "2026-11-12T09:00:00+00:00", "2026-11-12T10:00+00:00"
                    )
                ]
            },
        }

    assert asyncio.run(calendar_sync.sync(vault, disconnected)) is None
    assert asyncio.run(calendar_sync.sync(vault, connected)) == {
        "added": 1,
        "updated": 0,
        "ended": 0,
    }
