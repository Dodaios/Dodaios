"""The lead's brain turn verifies its answer and takes typed messages mid-turn."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dodaios.agent_chat import runner_brain
from tests.fakes.fake_brain_manager import FakeBrainManager
from tests.unit.agent_chat.test_runner_brain import (  # noqa: F401
    _drain,
    _jarvis_session,
    _service,
    no_cli,
)


async def test_a_lead_turn_verifies_and_takes_typed_messages_mid_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_cli  # noqa: F811
):
    hold = asyncio.Event()
    fake = FakeBrainManager(hold=hold)
    monkeypatch.setattr(runner_brain, "brain_manager", lambda: fake)
    monkeypatch.setattr(runner_brain, "_is_lead", lambda _sid: True)
    svc = _service(None)
    session = _jarvis_session(svc, tmp_path)
    q = svc.subscribe(session.session_id)
    await svc.send(session.session_id, "long job")
    await _drain(q, "reasoning_started")
    assert svc.can_steer(session.session_id)
    assert await svc.steer(session.session_id, "use the blue one instead")
    control = fake.calls[0][1]["turn_override"].loop_control
    assert control is not None and control.verify is not None
    assert list(control.drain_steer()) == ["use the blue one instead"]
    assert list(control.drain_steer()) == [], "a drained message is not delivered twice"
    hold.set()
    events = await _drain(q, "turn_finished")
    assert events[-1]["payload"]["status"] == "done"
    assert not svc.can_steer(session.session_id), "the steerer is gone with the turn"


async def test_a_non_lead_brain_turn_has_no_loop_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_cli  # noqa: F811
):
    fake = FakeBrainManager()
    monkeypatch.setattr(runner_brain, "brain_manager", lambda: fake)
    monkeypatch.setattr(runner_brain, "_is_lead", lambda _sid: False)
    svc = _service(None)
    session = _jarvis_session(svc, tmp_path)
    q = svc.subscribe(session.session_id)
    await svc.send(session.session_id, "hi")
    await _drain(q, "turn_finished")
    assert fake.calls[0][1]["turn_override"].loop_control is None
