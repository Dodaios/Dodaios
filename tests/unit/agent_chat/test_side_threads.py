"""A message sent while the lead still works is answered beside it, in a side thread."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import send_queue, side_threads
from dodaios.agent_chat import service as service_mod
from dodaios.agent_chat.dodaios_harness import since_last_turn_block
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.runner_brain import brain_history_from_events
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router

_FIRST = "Research the three best standing desks and compare them."
_SECOND = "What is the capital of Australia?"


async def _until(predicate, limit_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


class Chat:
    """The real chat service on the lead's conversation, with a scripted model."""

    def __init__(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(send_queue, "_POLL_S", 0.005)
        self.store = AgentChatStore(tmp_path / "chat.db")
        self.svc = AgentChatService(self.store)
        self.sid = self.store.create_session(
            provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
        ).session_id
        self.store.set_lead_session_id(self.sid)
        #: ``(session id, prompt)`` of every turn the model ran.
        self.prompts: list[tuple[str, str]] = []
        #: A turn whose prompt is a key here waits for its event (or for Stop).
        self.holds: dict[str, asyncio.Event] = {}
        monkeypatch.setattr(service_mod, "run_brain_turn", self._model)
        monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **kw: "brain")

    async def _model(self, handle, prompt, *args, **kwargs) -> None:
        self.prompts.append((handle.session.session_id, prompt))
        hold = self.holds.get(prompt)
        if hold is not None:
            waits = {asyncio.create_task(hold.wait()), asyncio.create_task(handle.cancel.wait())}
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            for task in waits:
                task.cancel()
        status = "cancelled" if handle.cancel.is_set() else "done"
        if status == "done":
            await handle.emit(make_event(
                "assistant_text", {"turn_id": handle.turn_id, "text": f"Answer to: {prompt}"},
            ))
        await handle.emit(make_event(
            "turn_finished", {"turn_id": handle.turn_id, "status": status, "usage": {}},
        ))

    def hold(self, prompt: str) -> asyncio.Event:
        self.holds[prompt] = asyncio.Event()
        return self.holds[prompt]

    def notices(self, kind: str) -> list[dict]:
        return [
            e["payload"] for e in self.store.list_events(self.sid)
            if e["kind"] == "notice" and e["payload"].get("kind") == kind
        ]

    async def working(self) -> asyncio.Event:
        """The lead is in the middle of its first request."""
        release = self.hold(_FIRST)
        await self.svc.send(self.sid, _FIRST)
        await _until(lambda: bool(self.prompts))
        return release

    async def idle(self, session_id: str | None = None) -> None:
        await _until(lambda: not self.svc.is_running(session_id or self.sid))


@pytest.fixture
def chat(tmp_path, monkeypatch):
    built = Chat(tmp_path, monkeypatch)
    yield built
    built.store.close()


async def test_a_message_sent_while_the_lead_works_is_answered_beside_it(chat):
    release = await chat.working()
    assert side_threads.takes(chat.svc, chat.sid)

    side_id = await side_threads.start(chat.svc, chat.sid, _SECOND)
    await _until(lambda: bool(chat.notices(side_threads.FINISHED)))

    # Answered while the first request is still being worked on.
    assert chat.svc.is_running(chat.sid)
    assert chat.prompts == [(chat.sid, _FIRST), (side_id, _SECOND)]
    assert chat.notices(side_threads.STARTED) == [
        {"kind": side_threads.STARTED, "side_id": side_id, "text": _SECOND}
    ]
    finished = chat.notices(side_threads.FINISHED)[0]
    assert finished["status"] == "done" and finished["side_id"] == side_id
    assert finished["text"] == _SECOND and finished["answer"] == f"Answer to: {_SECOND}"
    # The person's words reach the side thread untouched; the brief is briefing.
    assert chat.store.list_events(side_id)[0]["payload"]["text"] == _SECOND
    # It is part of the conversation, never a chat of its own.
    assert [s.session_id for s in chat.store.list_sessions(surface="jarvis")] == [chat.sid]
    assert chat.store.side_thread(side_id)["status"] == "done"
    assert side_threads.speaks_as_lead(chat.svc, side_id)

    release.set()
    await chat.idle()
    # The lead's next turn reads what was asked and answered beside it.
    history = brain_history_from_events(chat.store.list_events(chat.sid))
    told = "\n".join(str(message.content) for message in history)
    assert _SECOND in told and f"Answer to: {_SECOND}" in told
    assert "Side thread of this chat" in told


async def test_only_a_working_lead_conversation_branches(chat, tmp_path):
    assert not side_threads.takes(chat.svc, chat.sid)  # nothing runs: a normal turn
    other = chat.store.create_session(
        provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
    ).session_id
    release = await chat.working()
    assert not side_threads.takes(chat.svc, other)  # not the lead's conversation

    for index in range(side_threads.MAX_RUNNING):
        prompt = f"Question {index}"
        chat.hold(prompt)
        assert side_threads.takes(chat.svc, chat.sid)
        await side_threads.start(chat.svc, chat.sid, prompt)
    # The cap is reached: the next message waits in the queue as before.
    assert not side_threads.takes(chat.svc, chat.sid)
    note = side_threads.running_note(chat.svc, chat.sid)
    assert all(f'"Question {index}"' in note for index in range(side_threads.MAX_RUNNING))

    for hold in chat.holds.values():
        hold.set()
    release.set()
    await _until(
        lambda: len(chat.notices(side_threads.FINISHED)) == side_threads.MAX_RUNNING
    )
    await chat.idle()
    assert side_threads.running_note(chat.svc, chat.sid) == ""


async def test_a_side_thread_starts_on_a_brief_of_the_conversation(chat):
    chat.store.append_event(chat.sid, make_event("user_message", {"text": "My dog is called Bo."}))
    chat.store.append_event(
        chat.sid, make_event("assistant_text", {"turn_id": "t0", "text": "Bo, noted."})
    )
    chat.store.append_event(
        chat.sid, make_event("turn_finished", {"turn_id": "t0", "status": "done"})
    )
    release = await chat.working()
    chat.hold(_SECOND)
    side_id = await side_threads.start(chat.svc, chat.sid, _SECOND)

    note = side_threads.context_note(chat.svc, side_id)
    assert "Side thread of your one conversation" in note
    assert "My dog is called Bo." in note and "Bo, noted." in note
    assert _FIRST in note  # the request still being worked on
    assert side_threads.context_note(chat.svc, chat.sid) == ""  # the main thread has none

    chat.holds[_SECOND].set()
    release.set()
    await _until(lambda: bool(chat.notices(side_threads.FINISHED)))
    await chat.idle()
    assert side_threads.context_note(chat.svc, side_id) == ""


async def test_stop_ends_one_side_thread_and_leaves_the_main_thread(chat):
    release = await chat.working()
    chat.hold(_SECOND)
    side_id = await side_threads.start(chat.svc, chat.sid, _SECOND)
    await _until(lambda: len(chat.prompts) == 2)

    assert await side_threads.stop(chat.svc, chat.sid, side_id)

    finished = chat.notices(side_threads.FINISHED)
    assert [row["status"] for row in finished] == ["stopped"]
    assert "answer" not in finished[0]
    assert chat.svc.is_running(chat.sid)  # the first request goes on
    assert not await side_threads.stop(chat.svc, "another-chat", side_id)
    release.set()
    await chat.idle()
    assert len(chat.notices(side_threads.FINISHED)) == 1  # closed exactly once


async def test_a_message_that_belongs_to_the_running_request_moves_to_the_main_thread(chat):
    release = await chat.working()
    chat.hold(_SECOND)
    side_id = await side_threads.start(chat.svc, chat.sid, _SECOND)
    await _until(lambda: len(chat.prompts) == 2)
    steered: list[str] = []

    async def steer(session_id: str, text: str, *_files) -> bool:
        steered.append(text)
        return True

    # Even a seat that takes a message mid-turn is not written into: it would
    # read it only after its answer, as a turn the chat does not show.
    chat.svc.steer = steer
    assert await side_threads.move_to_main(chat.svc, chat.sid, side_id) == "queued"
    assert steered == []
    await _until(lambda: not chat.svc.is_running(side_id))

    finished = chat.notices(side_threads.FINISHED)
    assert [row["status"] for row in finished] == ["moved"]
    assert side_threads.replay(finished[0]) == ""  # nothing was answered beside
    assert await side_threads.move_to_main(chat.svc, chat.sid, side_id) == ""

    chat.holds.pop(_SECOND)
    release.set()
    await _until(lambda: len(chat.prompts) == 3)
    await chat.idle()
    assert chat.prompts[2] == (chat.sid, _SECOND)  # answered in the main thread
    assert len(chat.notices(side_threads.FINISHED)) == 1


async def test_a_message_that_cannot_be_sent_leaves_no_side_thread(chat):
    release = await chat.working()
    with pytest.raises(ValueError, match="empty message"):
        await side_threads.start(chat.svc, chat.sid, "   ")
    assert chat.store.side_threads(chat.sid) == []
    assert chat.notices(side_threads.STARTED) == []
    assert [s.session_id for s in chat.store.list_sessions()] == [chat.sid]
    release.set()
    await chat.idle()


async def test_a_restart_closes_the_side_threads_it_interrupted(chat, tmp_path):
    side = chat.store.create_session(
        provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
    ).session_id
    chat.store.save_side_thread(side, chat.sid, _SECOND)
    chat.store.append_event(side, make_event("user_message", {"text": _SECOND}))

    assert await side_threads.recover(chat.svc) == 1
    assert await side_threads.recover(chat.svc) == 0

    finished = chat.notices(side_threads.FINISHED)
    assert [(row["side_id"], row["status"]) for row in finished] == [(side, "interrupted")]
    assert "restarted" in side_threads.replay(finished[0])


def test_a_cli_seat_is_told_of_side_threads_that_ended_during_its_turn():
    """The closing notice lies inside the CLI's own turn, which its session never saw."""
    finished = {
        "kind": side_threads.FINISHED, "side_id": "s1", "status": "done",
        "text": _SECOND, "answer": "Canberra.",
    }
    history = [
        make_event("user_message", {"text": _FIRST}),
        make_event("turn_started", {"turn_id": "t1", "runner": "claude-cli"}),
        make_event("notice", {"kind": side_threads.STARTED, "side_id": "s1", "text": _SECOND}),
        make_event("notice", finished),
        make_event("assistant_text", {"turn_id": "t1", "text": "Here are the desks."}),
        make_event("turn_finished", {"turn_id": "t1", "status": "done"}),
    ]
    block = since_last_turn_block(history)
    assert _SECOND in block and "Canberra." in block
    assert "Here are the desks." not in block  # its own turn is in its own session


def test_claude_code_reads_the_catch_up_in_front_of_a_resumed_turn(monkeypatch, tmp_path):
    """Claude Code takes its identity as a file, so the block rides on the message."""
    from dodaios.agent_chat import runner_cli
    from dodaios.agent_chat.dodaios_harness import Identity

    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli.dodaios_harness, "control_key", lambda: None)

    def planned(identity, resume):
        plan = runner_cli.plan_claude(
            prompt="And now?", cwd=tmp_path, model="", effort="", permission_mode="ask",
            resume=resume, identity=identity,
        )
        return plan.stdin_text or ""

    vendor = "11111111-1111-4111-8111-111111111111"
    block = "<since_your_last_turn>\nThe person also asked: Canberra?\n</since_your_last_turn>\n\n"
    lead = Identity(session_id="lead-1", text="id", compact="id", catchup=block)
    assert "The person also asked: Canberra?" in planned(lead, vendor)
    # A fresh conversation carries the transcript in its identity, never the block.
    assert "also asked" not in planned(lead, None)
    # A created agent's seat has its own refresh; a coding thread has no identity.
    agent = Identity(session_id="society:scout", text="id", compact="id", catchup=block)
    assert "also asked" not in planned(agent, vendor)
    assert "also asked" not in planned(None, vendor)


@pytest.mark.parametrize(
    ("surface", "briefing", "expected"),
    [
        # The lead has no briefing of its own: its identity stays Dodaios' own
        # prompt layers, and a resumed turn gets its catch-up block.
        ("jarvis", None, None),
        # A created agent's briefing is its identity and carries the line.
        ("society", "You are Scout.", "You are Scout.\nRespond in this language: de"),
    ],
)
async def test_a_reply_language_never_stands_in_for_the_leads_identity(
    monkeypatch, surface, briefing, expected
):
    from types import SimpleNamespace

    from dodaios.agent_chat import dodaios_harness, runner_cli
    from dodaios.agent_chat.runner_api import TurnHandle

    seen: dict[str, object] = {}

    async def surface_identity(_session):
        return briefing

    async def build_identity(**kwargs):
        seen.update(kwargs)
        return dodaios_harness.Identity(kwargs["session_id"], "id", "id")

    async def once(handle, prompt, runner, resume, **kwargs):
        seen["prompt"] = prompt
        return runner_cli._Outcome("done", None, {}, None, resume)  # noqa: SLF001

    async def language(*_args):
        return "de"

    async def emit(_event):
        return None

    async def deny(*_args):
        return "deny"

    monkeypatch.setattr(runner_cli, "_surface_identity", surface_identity)
    monkeypatch.setattr(dodaios_harness, "build_identity", build_identity)
    monkeypatch.setattr(runner_cli, "_run_cli_once", once)
    monkeypatch.setattr("dodaios.society.reply_preference.resolve_agent_reply_language", language)
    session_id = "society:scout" if surface == "society" else "lead-1"
    handle = TurnHandle(
        session=SimpleNamespace(
            surface=surface, session_id=session_id, vendor_session="vendor-1", account_id="",
        ),
        turn_id="t1", emit=emit, request_approval=deny, cancel=asyncio.Event(),
        surface=surface, stance="ask", output_language="de",
    )
    await runner_cli.run_cli_turn(handle, "Was steht heute an?", "claude-cli", identity=True)

    assert seen["prompt_override"] == expected
    assert seen["resume"] == "vendor-1"
    # The line itself reaches every seat on the message.
    assert str(seen["prompt"]).endswith("Respond in this language: de")


def test_the_composer_route_answers_beside_a_working_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **kw: "brain")

    async def model(handle, prompt, *args, **kwargs) -> None:
        if prompt == _FIRST:
            await handle.cancel.wait()  # works until the person stops it
        status = "cancelled" if handle.cancel.is_set() else "done"
        await handle.emit(make_event(
            "assistant_text", {"turn_id": handle.turn_id, "text": f"Answer to: {prompt}"},
        ))
        await handle.emit(make_event(
            "turn_finished", {"turn_id": handle.turn_id, "status": status, "usage": {}},
        ))

    monkeypatch.setattr(service_mod, "run_brain_turn", model)
    store = AgentChatStore(tmp_path / "chat.db")
    sid = store.create_session(
        provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
    ).session_id
    store.set_lead_session_id(sid)
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = AgentChatService(store)
    url = f"/api/agent-chat/sessions/{sid}"
    try:
        with TestClient(app) as client:
            first = client.post(f"{url}/messages", json={"text": _FIRST})
            assert first.status_code == 202 and first.json()["turn_id"]

            second = client.post(f"{url}/messages", json={"text": _SECOND})
            assert second.status_code == 202
            side_id = second.json()["side_thread"]
            assert side_id and second.json()["turn_id"] == ""

            # The person asked for the other way: wait for the running request.
            third = client.post(f"{url}/messages", json={"text": "Later.", "delivery": "after"})
            assert third.json().get("queued") is True

            # A side thread of another chat is not found here.
            assert client.post(f"{url}/side-threads/nope/stop").status_code == 404
            stopped = client.post(f"{url}/side-threads/{side_id}/stop")
            assert stopped.status_code == 200 and stopped.json() == {"stopped": True}
            gone = client.post(f"{url}/side-threads/{side_id}/to-main")
            assert gone.status_code == 409

            listed = client.get("/api/agent-chat/sessions?surface=jarvis").json()["sessions"]
            assert [row["session_id"] for row in listed] == [sid]
            assert client.delete(f"{url}/queue/{third.json()['queue_id']}").json()["removed"]
            assert client.post(f"{url}/cancel").status_code == 200
    finally:
        store.close()
