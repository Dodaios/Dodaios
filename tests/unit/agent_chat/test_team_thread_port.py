"""How a coordinator turn maps onto a thread session of the agent chat."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from dodaios.agent_chat.service import SessionBusy
from dodaios.agent_chat.team import port as team_port
from dodaios.agent_chat.team.port import ChatTurns


class ScriptedStore:
    def __init__(self) -> None:
        self.terminal: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []

    def turn_terminal(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        return self.terminal

    def list_events(self, session_id: str, *, tail: int = 0) -> list[dict[str, Any]]:
        return self.events


class ScriptedChat:
    """The few calls ``ChatTurns`` makes, answered from a script."""

    def __init__(self) -> None:
        self.store = ScriptedStore()
        self.sent: list[dict[str, Any]] = []
        self.cancelled: list[tuple[str, str | None]] = []
        self.running = False
        self.previous_turn = asyncio.Event()
        self.turn_done = asyncio.Event()
        self.turn_done.set()
        self.send_error: Exception | None = None
        self.turn_stopped = False

    def is_running(self, session_id: str) -> bool:
        return self.running

    async def send(self, session_id: str, text: str, **options: Any) -> str:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append({"session_id": session_id, "text": text, **options})
        return "t1"

    async def wait_turn(self, session_id: str) -> None:
        if self.turn_stopped:
            # What awaiting the turn's own cancelled task does.
            raise asyncio.CancelledError
        if self.running:
            await self.previous_turn.wait()
            self.running = False
            return
        await self.turn_done.wait()

    async def cancel(self, session_id: str, *, expected_turn_id: str | None = None) -> bool:
        self.cancelled.append((session_id, expected_turn_id))
        return True

    def finish(self, status: str, *, text: str = "", error: str = "", cost: Any = None) -> None:
        self.store.terminal = {
            "payload": {"turn_id": "t1", "status": status, "error": error, "cost_usd": cost,
                        "duration_ms": 40},
        }
        self.store.events = [
            {"kind": "assistant_text", "payload": {"turn_id": "t1", "text": "Looking around"}},
            {"kind": "assistant_text", "payload": {"turn_id": "t1", "text": text}},
            {"kind": "assistant_text", "payload": {"turn_id": "other", "text": "not this turn"}},
        ]


async def _ask(chat: ScriptedChat, timeout_s: float = 5):
    return await ChatTurns(chat).ask(
        "s1", "the prompt", display="Team thread: your own plan", language="en",
        timeout_s=timeout_s,
    )


async def test_a_turn_returns_its_final_message_and_what_it_cost() -> None:
    chat = ScriptedChat()
    chat.finish("done", text="The plan", cost=0.5)

    result = await _ask(chat)

    assert (result.status, result.text, result.cost_usd, result.duration_ms) == (
        "ok", "The plan", 0.5, 40,
    )
    (sent,) = chat.sent
    # The coordinator wrote it, not the person, and the member's thread says so.
    assert sent["direct_user"] is False
    assert sent["display_text"] == "Team thread: your own plan"
    assert sent["author"]["name"] == "Team thread"
    assert sent["output_language"] == "en"


async def test_a_seat_without_a_price_reports_none() -> None:
    chat = ScriptedChat()
    chat.finish("done", text="The plan")

    assert (await _ask(chat)).cost_usd is None


async def test_a_provider_error_is_a_failed_turn_in_plain_words() -> None:
    chat = ScriptedChat()
    chat.finish(
        "error",
        error='{"type":"error","status":400,"error":{"type":"invalid_request_error",'
        '"message":"The model is not supported."}}',
    )

    result = await _ask(chat)

    assert (result.status, result.error) == ("failed", "The model is not supported.")


async def test_a_turn_stopped_from_outside_is_not_a_failed_seat() -> None:
    chat = ScriptedChat()
    chat.finish("cancelled")
    assert (await _ask(chat)).status == "timeout"

    chat.store.terminal = None  # the app went down under the turn
    assert (await _ask(chat)).status == "timeout"


async def test_a_turn_stopped_in_the_members_thread_does_not_cancel_the_coordinator() -> None:
    chat = ScriptedChat()
    chat.finish("cancelled")
    chat.turn_stopped = True

    result = await _ask(chat)

    assert result.status == "timeout"
    assert chat.cancelled == []  # nothing left to stop, and nobody was cancelled


async def test_a_turn_without_words_is_handed_on_as_it_is() -> None:
    chat = ScriptedChat()
    chat.finish("done", text="  ")

    result = await _ask(chat)

    # An earlier line of the same turn is still its answer.
    assert (result.status, result.text) == ("ok", "Looking around")
    # No word at all is still a finished turn (a build that only edited files);
    # whether that counts is the coordinator's call.
    chat.store.events = []
    silent = await _ask(chat)
    assert (silent.status, silent.text) == ("ok", "")


async def test_a_turn_over_its_time_is_cancelled_and_reported() -> None:
    chat = ScriptedChat()
    chat.turn_done.clear()

    result = await _ask(chat, timeout_s=0.01)

    assert result.status == "timeout"
    assert chat.cancelled == [("s1", "t1")]


async def test_a_member_still_stopping_its_last_turn_is_waited_for() -> None:
    chat = ScriptedChat()
    chat.finish("done", text="The plan")
    chat.running = True
    asking = asyncio.create_task(_ask(chat))
    await asyncio.sleep(0)
    assert chat.sent == []  # nothing is sent into a thread that still runs

    chat.previous_turn.set()
    result = await asking

    assert result.status == "ok"
    assert len(chat.sent) == 1


async def test_a_member_that_stays_busy_is_asked_again_later_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(team_port, "_BUSY_WAIT_S", 0.01)
    chat = ScriptedChat()
    chat.running = True
    assert (await _ask(chat)).status == "timeout"

    chat.running = False
    chat.send_error = SessionBusy("s1")
    assert (await _ask(chat)).status == "timeout"

    chat.send_error = ValueError("Unknown agent-chat provider")
    failed = await _ask(chat)
    assert (failed.status, failed.error) == ("failed", "Unknown agent-chat provider")


async def test_stopping_the_coordinator_stops_the_members_turn() -> None:
    chat = ScriptedChat()
    chat.turn_done.clear()
    asking = asyncio.create_task(_ask(chat))
    while not chat.sent:  # noqa: ASYNC110 - one scheduling step of a scripted fake
        await asyncio.sleep(0)

    asking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asking

    assert chat.cancelled == [("s1", "t1")]
