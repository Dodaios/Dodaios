"""Several orders in one chat: a turn that only waits hands its seat to the next message."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.agent_chat import delegation_wait, parked_work, send_queue
from jarvis.agent_chat import service as service_mod
from jarvis.agent_chat.events import make_event
from jarvis.agent_chat.parked_work import BACKGROUND_ORIGIN, ParkedWorkBoard
from jarvis.agent_chat.send_queue import send_or_queue
from jarvis.agent_chat.service import AgentChatService
from jarvis.agent_chat.store import AgentChatStore
from jarvis.core.delegated_work import DelegatedWork, register_delegated_work

_FIRST = "Brief the agent in terminal two about the login bug."
_SECOND = "And create a new agent for the documentation."
_REPO = Path(__file__).resolve().parents[3]


async def _until(predicate, limit_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


class Chat:
    """The real chat service with a scripted model in place of a provider."""

    def __init__(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(delegation_wait, "POLL_SECONDS", 0.005)
        monkeypatch.setattr(parked_work, "_POLL_S", 0.005)
        monkeypatch.setattr(send_queue, "_POLL_S", 0.005)
        self.store = AgentChatStore(tmp_path / "chat.db")
        self.svc = AgentChatService(self.store)
        self.sid = self.store.create_session(
            provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
        ).session_id
        self.prompts: list[tuple[str, str]] = []
        #: The pane has finished the first order.
        self.pane_done = False
        #: Held turns: an event per prompt index that the scripted model waits for.
        self.holds: dict[int, asyncio.Event] = {}
        monkeypatch.setattr(service_mod, "run_brain_turn", self._model)
        monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **kw: "brain")

    async def _model(self, handle, prompt, *args, **kwargs) -> None:
        index = len(self.prompts)
        self.prompts.append((handle.turn_id, prompt))
        hold = self.holds.get(index)
        if hold is not None:
            await hold.wait()
        if index == 0:

            async def pane():
                if not self.pane_done:
                    return None
                return {"status": "completed", "report": "The login bug is fixed."}

            assert register_delegated_work(DelegatedWork("pane-t2", "Agent T2", pane))
        text = ["Sent to the agent in terminal two.", "The documentation agent exists.",
                "The login bug is fixed."][min(index, 2)]
        await handle.emit(make_event("assistant_text", {"turn_id": handle.turn_id, "text": text}))
        await handle.emit(make_event(
            "turn_finished", {"turn_id": handle.turn_id, "status": "done", "usage": {}},
        ))

    def events(self, kind: str) -> list[dict]:
        return [e for e in self.store.list_events(self.sid) if e["kind"] == kind]

    def waiting_for_agents(self) -> bool:
        return any("Waiting for agents" in e["payload"].get("text", "")
                   for e in self.events("reasoning"))

    async def idle(self) -> None:
        await _until(lambda: not self.svc.is_running(self.sid))


@pytest.fixture
def chat(tmp_path, monkeypatch):
    built = Chat(tmp_path, monkeypatch)
    yield built
    built.svc.parked_work.stop(built.sid)
    built.store.close()


async def test_the_next_message_is_answered_while_the_first_request_still_runs(chat):
    first_turn, _ = await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(chat.waiting_for_agents)
    assert chat.svc.is_running(chat.sid)  # the turn is open, but only waiting

    second_turn, queue_id = await send_or_queue(chat.svc, chat.sid, _SECOND)
    assert second_turn and queue_id == ""  # started at once, not queued
    await chat.idle()

    finished = [e["payload"]["turn_id"] for e in chat.events("turn_finished")]
    assert finished == [first_turn, second_turn]
    closed = chat.events("turn_finished")[0]["payload"]
    assert closed["status"] == "done" and closed["background"] == ["Agent T2"]
    assert [item.request for item in chat.svc.parked_work.running(chat.sid)] == [_FIRST]
    # The second turn receives the person's words untouched. What still runs
    # is briefing for the runner, never part of the message: the brain reads
    # that text to decide which coding pane an order addresses.
    assert chat.prompts[1][1] == _SECOND
    assert chat.events("user_message")[1]["payload"]["text"] == _SECOND
    note = chat.svc.parked_work.context_note(chat.sid)
    assert _FIRST in note and "Agent T2" in note
    assert len(chat.prompts) == 2  # no model call while the agent works

    chat.pane_done = True
    await _until(lambda: len(chat.prompts) == 3)
    await chat.idle()
    result_turn, result_prompt = chat.prompts[2]
    assert result_turn not in (first_turn, second_turn)  # a turn of its own, at the bottom
    assert "The login bug is fixed." in result_prompt and _FIRST in result_prompt
    assert "other messages since" in result_prompt
    marker = chat.events("user_message")[2]["payload"]
    assert marker["origin"] == BACKGROUND_ORIGIN and marker["typed"] == _FIRST
    assert chat.svc.parked_work.running(chat.sid) == []
    assert not chat.events("error")


async def test_an_undisturbed_wait_keeps_its_turn(chat):
    first_turn, _ = await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(chat.waiting_for_agents)
    chat.pane_done = True
    await chat.idle()
    assert [turn for turn, _ in chat.prompts] == [first_turn, first_turn]
    assert len(chat.events("turn_finished")) == 1
    assert chat.svc.parked_work.running(chat.sid) == []
    assert all("origin" not in e["payload"] for e in chat.events("user_message"))


async def test_a_message_queued_during_the_answer_starts_when_the_wait_begins(chat):
    chat.holds[0] = asyncio.Event()  # the model is still answering the first order
    await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(lambda: len(chat.prompts) == 1)
    turn_id, queue_id = await send_or_queue(chat.svc, chat.sid, _SECOND)
    assert turn_id == "" and queue_id  # an answering turn keeps its seat
    chat.holds[0].set()
    await _until(lambda: len(chat.prompts) == 2)  # started without the agent's result
    await chat.idle()
    assert not chat.pane_done
    assert [item.request for item in chat.svc.parked_work.running(chat.sid)] == [_FIRST]


async def test_a_finished_request_waits_for_the_running_turn(chat):
    await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(chat.waiting_for_agents)
    chat.holds[1] = asyncio.Event()  # the second order is still being answered
    await send_or_queue(chat.svc, chat.sid, _SECOND)
    await _until(lambda: len(chat.prompts) == 2)
    chat.pane_done = True
    await asyncio.sleep(0.05)
    assert len(chat.prompts) == 2  # the result does not interrupt the running turn
    chat.holds[1].set()
    await _until(lambda: len(chat.prompts) == 3)
    await chat.idle()
    assert "The login bug is fixed." in chat.prompts[2][1]


async def test_two_messages_sent_into_a_wait_keep_their_order(chat):
    await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(chat.waiting_for_agents)
    second, third = await asyncio.gather(
        send_or_queue(chat.svc, chat.sid, _SECOND),
        send_or_queue(chat.svc, chat.sid, "And then tell me a joke."),
    )
    assert second[0] and third[1]  # the first one starts, the later one waits behind it
    await _until(lambda: len(chat.prompts) == 3)
    await chat.idle()
    assert [prompt for _, prompt in chat.prompts[1:]] == [_SECOND, "And then tell me a joke."]


async def test_a_dropped_background_wait_starts_no_turn(chat):
    await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(chat.waiting_for_agents)
    await send_or_queue(chat.svc, chat.sid, _SECOND)
    await chat.idle()
    task = chat.svc.parked_work.running(chat.sid)[0].task
    assert chat.svc.parked_work.stop(chat.sid) == 1
    await asyncio.gather(task, return_exceptions=True)
    chat.pane_done = True
    await asyncio.sleep(0.05)
    assert len(chat.prompts) == 2


async def test_an_answering_turn_is_never_asked_for_its_seat(chat):
    chat.holds[0] = asyncio.Event()
    await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(lambda: len(chat.prompts) == 1)
    assert await chat.svc.release_waiting_turn(chat.sid) is False
    assert chat.svc.is_running(chat.sid)
    chat.holds[0].set()
    chat.pane_done = True
    await chat.idle()


def test_an_agents_own_chat_keeps_its_turn():
    assert ParkedWorkBoard.parks(SimpleNamespace(surface="jarvis")) is True
    assert ParkedWorkBoard.parks(SimpleNamespace(surface="society")) is False
    assert ParkedWorkBoard.parks(SimpleNamespace(surface="agent")) is False


def test_the_timeline_knows_the_background_origin():
    """The marker crosses to the frontend as a literal: both sides name it the same."""
    reducer = (
        _REPO / "jarvis/ui/web/frontend/src/components/agentchat/reduce.ts"
    ).read_text(encoding="utf-8")
    assert f'p.origin === "{BACKGROUND_ORIGIN}"' in reducer
