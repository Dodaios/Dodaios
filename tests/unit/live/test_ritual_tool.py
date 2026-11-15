"""A live call's way into rituals: a tool that names the phrases to listen for."""

from __future__ import annotations

import pytest

from dodaios.live import native
from dodaios.live.state import LiveLedger
from dodaios.live.tools import LiveTools
from dodaios.rituals import prepare, said, service
from dodaios.rituals.store import RitualStore, set_store
from tests.fakes.fake_subscription_session import SafeMessageGateway
from tests.unit.rituals.conftest import Society

MORNING = {
    "name": "Good morning",
    "phrases": ["Good morning", "Rise and shine"],
    "steps": [{"when": "now", "text": "Play my favourite music."}],
}


@pytest.fixture
async def call(tmp_path, monkeypatch: pytest.MonkeyPatch):
    rituals = RitualStore(":memory:")
    set_store(rituals)
    world = Society()
    monkeypatch.setattr(service, "_runtime", lambda: world)
    monkeypatch.setattr(prepare, "_runtime", lambda: world)
    monkeypatch.setattr(service, "_POLL_S", 0.01)
    ledger = LiveLedger(tmp_path / "receipts.db")
    tools = LiveTools(SafeMessageGateway(), ledger, "call", language="en", backend_model="")
    try:
        yield tools, world
    finally:
        await service.drain()
        await prepare.drain()
        ledger.close()
        set_store(None)
        rituals.close()


def _declared(tools: LiveTools) -> dict[str, dict]:
    return {tool["name"]: tool for tool in tools.declarations()}


async def test_without_a_ritual_the_model_is_told_of_no_such_tool(call) -> None:
    tools, _world = call
    assert "start_ritual" not in _declared(tools)
    await service.create(**{**MORNING, "enabled": False})
    # A ritual that is off is nothing to listen for.
    assert "start_ritual" not in _declared(tools)


async def test_the_tool_names_the_phrases_to_listen_for(call) -> None:
    tools, _world = call
    await service.create(**MORNING)
    tool = _declared(tools)["start_ritual"]
    assert '"Good morning", "Rise and shine"' in tool["description"]
    assert "BEFORE you answer" in tool["description"]
    assert tool["parameters"]["required"] == ["phrase"]
    # It is one of the session's own tools, declared whatever the budget.
    assert "start_ritual" in native._SESSION_TOOLS


async def test_the_phrase_starts_the_ritual_and_hands_back_what_to_say(call) -> None:
    tools, world = call
    ritual = await service.create(**MORNING)
    tools.declarations()
    result = await tools.execute("call-1", "start_ritual", {"phrase": "Good morning"}, 0)
    assert result["success"] is True and result["started"] is True
    assert result["say"] == "On it."
    assert service.today_of(ritual.id).fired_via == "voice"
    assert [card["via"] for card in world.cards()] == ["voice"]


async def test_what_starts_nothing_is_left_to_the_model(call) -> None:
    tools, world = call
    await service.create(**MORNING)
    tools.declarations()
    first = await tools.execute("call-1", "start_ritual", {"phrase": "Good morning"}, 0)
    # The second time on the day, and a sentence that is no phrase.
    again = await tools.execute("call-2", "start_ritual", {"phrase": "Good morning"}, 0)
    other = await tools.execute("call-3", "start_ritual", {"phrase": "Good evening"}, 0)
    assert first["started"] is True
    assert again == {"success": True, "started": False}
    assert other == {"success": True, "started": False}
    assert len(world.cards()) == 1


def test_phrases_that_cannot_be_read_mean_nothing_to_listen_for(monkeypatch) -> None:
    def broken() -> list:
        raise RuntimeError("the store is closed")

    monkeypatch.setattr(service, "list_rituals", broken)
    assert said.live_phrases() == []
