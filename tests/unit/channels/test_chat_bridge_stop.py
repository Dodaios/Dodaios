"""The owner's "stop" from a phone channel halts everything, with one confirmation."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from dodaios.channels.base import ChannelMessage
from dodaios.channels.chat_bridge import ChannelChatBridge
from dodaios.core.bus import EventBus
from dodaios.core.events import KillRequested
from dodaios.orchestrator import jobs
from dodaios.safety.stop_hold import stop_holds
from tests.unit.channels.test_chat_bridge import _Manager, _ReplyChannel

OWNER = {"telegram_chat_id": 12345, "friend_id": None}


class _Svc:
    def __init__(self) -> None:
        self.running = ["lead", "agent-1"]
        self.cancelled: list[str] = []

    def running_session_ids(self) -> list[str]:
        return list(self.running)

    async def cancel(self, sid: str) -> bool:
        self.cancelled.append(sid)
        self.running.remove(sid)
        return True


@pytest.fixture(autouse=True)
def _ledger():
    ledger = jobs.JobLedger(":memory:")
    jobs.set_ledger(ledger)
    yield ledger
    jobs.set_ledger(None)
    ledger.close()


async def _say(channel: _ReplyChannel, text: str, metadata: dict) -> None:
    channel.got.clear()
    await channel.queue.put(
        ChannelMessage(session_id=uuid4(), kind="text", content=text, metadata=metadata)
    )
    await asyncio.wait_for(channel.got.wait(), timeout=3.0)


async def test_stop_from_the_owners_phone_halts_work_and_confirms_once(monkeypatch) -> None:
    svc = _Svc()
    bus = EventBus()
    kills: list[KillRequested] = []

    async def on_kill(event: KillRequested) -> None:
        kills.append(event)

    bus.subscribe(KillRequested, on_kill)
    channel = _ReplyChannel()
    bridge = ChannelChatBridge(
        bus=bus, manager=_Manager(channel), get_chat_service=lambda: svc  # type: ignore[arg-type]
    )
    bridge.start()
    jobs.get_ledger().create("mission", job_id="j1", title="m", state="running")

    await _say(channel, "Stop", OWNER)
    await bridge.stop()

    assert svc.running == [] and sorted(svc.cancelled) == ["agent-1", "lead"]
    assert jobs.get_ledger().get("j1").state == "cancelled"
    assert [k.source for k in kills] == ["telegram"]
    hold = stop_holds().get("everything")
    assert hold is not None and hold.source == "telegram"
    assert len(channel.sent) == 1, "one written confirmation"
    assert channel.sent[0].content.startswith("Stopped.")
    assert channel.sent[0].metadata["telegram_chat_id"] == 12345


async def test_resume_lifts_the_stop_only_when_one_is_in_force(monkeypatch) -> None:
    from dodaios.agent_chat import lead

    asked: list[str] = []

    async def fake_answer(svc, text, *, source, **_kw):
        asked.append(text)
        return "ok, continuing the chat"

    monkeypatch.setattr(lead, "answer_in_lead", fake_answer)
    channel = _ReplyChannel()
    bridge = ChannelChatBridge(
        bus=EventBus(), manager=_Manager(channel), get_chat_service=lambda: _Svc()  # type: ignore[arg-type]
    )
    bridge.start()

    # No stop in force: "resume" is an ordinary message for the lead.
    await _say(channel, "resume", OWNER)
    assert asked == ["resume"]

    await _say(channel, "stop", OWNER)
    assert stop_holds().get("everything") is not None
    await _say(channel, "resume", OWNER)
    await bridge.stop()
    assert stop_holds().get("everything") is None
    assert asked == ["resume"], "the resume word did not reach the lead as a chat turn"
    assert "Resumed" in channel.sent[-1].content


async def test_a_friend_or_group_cannot_stop_the_owners_work() -> None:
    svc = _Svc()
    channel = _ReplyChannel()
    bridge = ChannelChatBridge(
        bus=EventBus(), manager=_Manager(channel), get_chat_service=lambda: svc  # type: ignore[arg-type]
    )
    bridge.start()
    await channel.queue.put(
        ChannelMessage(
            session_id=uuid4(), kind="text", content="stop",
            metadata={"telegram_chat_id": 777, "friend_id": "f-1"},
        )
    )
    await asyncio.sleep(0.2)
    await bridge.stop()
    assert svc.cancelled == [] and stop_holds().get("everything") is None
