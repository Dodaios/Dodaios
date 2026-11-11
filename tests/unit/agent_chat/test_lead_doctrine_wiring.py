"""Both runners mark the lead conversation for the doctrine; nothing else is marked."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.agent_chat import dodaios_harness, runner_brain
from tests.fakes.fake_brain_manager import FakeBrainManager
from tests.unit.agent_chat.test_runner_brain import (  # noqa: F401
    _drain,
    _jarvis_session,
    _service,
    no_cli,
)


@pytest.mark.parametrize("is_lead", [True, False])
async def test_the_brain_runner_marks_only_the_lead_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_cli, is_lead: bool  # noqa: F811
):
    fake = FakeBrainManager()
    monkeypatch.setattr(runner_brain, "brain_manager", lambda: fake)
    monkeypatch.setattr(runner_brain, "_is_lead", lambda _sid: is_lead)
    svc = _service(None)
    session = _jarvis_session(svc, tmp_path)
    q = svc.subscribe(session.session_id)
    await svc.send(session.session_id, "hi")
    await _drain(q, "turn_finished")
    assert fake.calls[0][1]["turn_override"].lead is is_lead


class _Brain:
    def __init__(self) -> None:
        self.lead_flags: list[bool] = []

    async def render_surface_prompt(self, *, user_text: str, lead: bool = False):
        self.lead_flags.append(lead)
        return "BASE", ""


@pytest.mark.parametrize("is_lead", [True, False])
async def test_the_cli_identity_marks_only_the_lead_conversation(
    monkeypatch: pytest.MonkeyPatch, is_lead: bool
):
    brain = _Brain()
    monkeypatch.setattr(dodaios_harness, "_brain", lambda: brain)
    monkeypatch.setattr(runner_brain, "_is_lead", lambda _sid: is_lead)
    await dodaios_harness.identity_prompt(
        user_text="hi", history=[], resume=None, session_id="s1"
    )
    assert brain.lead_flags == [is_lead]


async def test_a_society_seat_identity_never_asks_for_the_lead_layers(
    monkeypatch: pytest.MonkeyPatch,
):
    brain = _Brain()
    monkeypatch.setattr(dodaios_harness, "_brain", lambda: brain)
    await dodaios_harness.identity_prompt(
        user_text="hi", history=[], resume=None, prompt_override="You are Scout.",
        session_id="society:a1",
    )
    assert brain.lead_flags == []
