"""An owed result reaches a live call on an install without a speech pipeline."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from dodaios.core import runtime_refs
from dodaios.core.events import AnnouncementRequested
from dodaios.live import announcements, runtime


class _Call:
    """A live call that takes a report after refusing the first ``busy`` offers."""

    def __init__(self, *, busy: int = 0) -> None:
        self.session_id = "call-1"
        self.is_active = True
        self.busy = busy
        self.offers: list[dict] = []

    async def deliver_announcement(self, **kwargs) -> bool:
        self.offers.append(kwargs)
        if self.busy:
            self.busy -= 1
            return False
        return True


def _result(**overrides) -> AnnouncementRequested:
    fields = {
        "trace_id": uuid4(), "source_layer": "agentic_ide.readback", "kind": "completion",
        "language": "en", "text": "T1 has finished: **done**", "report": "done",
    }
    return AnnouncementRequested(**{**fields, **overrides})


@pytest.fixture
def no_pipeline(monkeypatch):
    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(runtime, "_owners", {})
    monkeypatch.setattr(runtime_refs, "_SPEECH_PIPELINE", [])
    monkeypatch.setattr(announcements, "RETRY_S", 0.01)


async def _settle() -> None:
    for _ in range(50):
        if not announcements._pending:
            return
        await asyncio.sleep(0.01)


async def test_a_finished_agent_is_reported_to_the_call(no_pipeline):
    call = _Call()
    runtime.register(call)
    await announcements.deliver_to_live_call(_result())
    await _settle()
    assert len(call.offers) == 1
    offer = call.offers[0]
    assert offer["report"] == "done" and offer["spoken_kind"] == "completion"
    assert "**" not in offer["text"] and offer["language"] == "en"


async def test_a_busy_call_is_offered_the_report_again(no_pipeline):
    call = _Call(busy=2)
    runtime.register(call)
    await announcements.deliver_to_live_call(_result())
    await _settle()
    assert len(call.offers) == 3  # refused twice while a turn ran, then taken


async def test_the_speech_pipeline_keeps_the_delivery_where_it_runs(no_pipeline, monkeypatch):
    call = _Call()
    runtime.register(call)
    monkeypatch.setattr(runtime_refs, "_SPEECH_PIPELINE", [object()])
    await announcements.deliver_to_live_call(_result())
    await _settle()
    assert call.offers == []


async def test_a_line_spoken_inside_a_turn_is_not_handed_over(no_pipeline):
    call = _Call()
    runtime.register(call)
    await announcements.deliver_to_live_call(_result(kind="preamble", report=None))
    await announcements.deliver_to_live_call(_result(kind="progress", report=None))
    await _settle()
    assert call.offers == []
    # An info line carrying an agent's report is still owed.
    await announcements.deliver_to_live_call(_result(kind="info", report="three mails"))
    await _settle()
    assert len(call.offers) == 1


async def test_nothing_is_kept_waiting_without_a_call(no_pipeline):
    await announcements.deliver_to_live_call(_result())
    assert not announcements._pending


async def test_a_call_that_ends_stops_the_offers(no_pipeline, monkeypatch):
    monkeypatch.setattr(announcements, "ATTEMPTS", 500)
    call = _Call(busy=10_000)
    runtime.register(call)
    await announcements.deliver_to_live_call(_result())
    await asyncio.sleep(0.05)
    runtime.unregister(call.session_id)
    await _settle()
    assert not announcements._pending
    assert 0 < len(call.offers) < 500
