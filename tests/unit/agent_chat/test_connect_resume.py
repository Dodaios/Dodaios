"""A connected service continues the request that needed it, in a turn of its own."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import connect_resume
from dodaios.agent_chat.connect_resume import _request_of, resume_prompt
from dodaios.agent_chat.credential_requests import CLI, PLUGIN, CredentialSpec
from dodaios.agent_chat.delegation_wait import is_continuation_prompt
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService, SessionBusy, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.society import connect_tool
from dodaios.society.connect_tool import Target, connect_save
from dodaios.society.credentials import CredentialError

LEAD_CHAT = "chat-1"
REQUEST = "Kannst du meine Gmails checken"  # i18n-allow
_GMAIL = CredentialSpec.build("gmail", "Gmail", kind=PLUGIN)


@pytest.fixture
async def chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The lead's chat: the person asked for their mail, the turn showed the card."""
    monkeypatch.setattr(connect_resume, "_POLL_S", 0.01)
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")
    svc.store.create_session(
        provider="fakeprov", model="m", effort="high", cwd=str(tmp_path),
        session_id=LEAD_CHAT, surface="jarvis",
    )
    await svc._emit(LEAD_CHAT, make_event("user_message", {"text": REQUEST}))  # noqa: SLF001
    await svc._emit(LEAD_CHAT, make_event("turn_started", {"turn_id": "turn-1"}))  # noqa: SLF001
    run = _Running("turn-1", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(3600))
    svc._running[LEAD_CHAT] = run  # noqa: SLF001 — a running turn without a runner
    sent: list[dict[str, Any]] = []

    async def send(session_id: str, text: str, **kwargs: Any) -> str:
        if svc.is_running(session_id):
            raise SessionBusy(session_id)
        sent.append({"session_id": session_id, "text": text, **kwargs})
        return "turn-2"

    svc.send = send  # type: ignore[method-assign]
    connected = {"gmail": True}
    monkeypatch.setattr(
        connect_tool, "resolve_target",
        lambda kind, raw: Target(kind, raw, raw.title(), connected.get(raw, False)),
    )

    async def settle() -> None:
        resume = getattr(svc, "_connect_resume", None)
        tasks = list(resume._tasks) if resume is not None else []  # noqa: SLF001
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), 5)

    async def end_turn() -> None:
        run.task.cancel()
        await asyncio.gather(run.task, return_exceptions=True)

    try:
        yield svc, sent, settle, end_turn, connected
    finally:
        run.task.cancel()


async def _open(svc: AgentChatService, spec: CredentialSpec = _GMAIL) -> str:
    return await svc.open_credential_request(
        LEAD_CHAT, spec, connect_save(spec.kind, spec.env), asker="Nova"
    )


async def test_a_connected_card_continues_the_request_once_its_turn_has_ended(chat) -> None:
    svc, sent, settle, end_turn, _connected = chat
    request_id = await _open(svc)
    assert await svc.submit_credential(LEAD_CHAT, request_id, "connected")
    await asyncio.sleep(0.05)
    assert sent == []  # the turn that showed the card is still running
    await end_turn()
    await settle()
    assert len(sent) == 1
    turn = sent[0]
    assert turn["session_id"] == LEAD_CHAT
    # No bubble of the person's: the line names the request this result belongs to.
    assert turn["background_result"] is True and turn["display_text"] == REQUEST
    assert turn["text"] == resume_prompt("Gmail", REQUEST)
    assert "connected Gmail on the Connect card" in turn["text"]
    assert turn["text"].endswith(f"Original user request:\n{REQUEST}")
    # Composed by the app: no runner reads it as the person's words.
    assert is_continuation_prompt(turn["text"])


async def test_a_repeated_report_does_not_continue_twice(chat) -> None:
    svc, sent, settle, end_turn, _connected = chat
    request_id = await _open(svc)
    await end_turn()
    assert await svc.submit_credential(LEAD_CHAT, request_id, "connected")
    # A second window showing the same card reports the same connection.
    assert await svc.submit_credential(LEAD_CHAT, request_id, "connected")
    await settle()
    assert len(sent) == 1


async def test_a_card_that_is_not_connected_yet_continues_nothing(chat) -> None:
    svc, sent, settle, end_turn, connected = chat
    connected["gmail"] = False
    request_id = await _open(svc)
    await end_turn()
    with pytest.raises(CredentialError):
        await svc.submit_credential(LEAD_CHAT, request_id, "connected")
    assert await svc.decline_credential(LEAD_CHAT, request_id)
    await settle()
    assert sent == []


async def test_a_command_line_tool_continues_the_same_way(chat) -> None:
    svc, sent, settle, end_turn, connected = chat
    connected["gh"] = True
    request_id = await _open(svc, CredentialSpec.build("gh", "GitHub CLI", kind=CLI))
    await end_turn()
    assert await svc.submit_credential(LEAD_CHAT, request_id, "connected")
    await settle()
    assert [turn["text"] for turn in sent] == [resume_prompt("GitHub CLI", REQUEST)]


async def test_a_secret_field_starts_no_turn(chat) -> None:
    svc, sent, settle, end_turn, _connected = chat
    saved: list[str] = []
    token = CredentialSpec.build("GITHUB_TOKEN", "GitHub token")
    request_id = await svc.open_credential_request(LEAD_CHAT, token, saved.append)
    await end_turn()
    assert await svc.submit_credential(LEAD_CHAT, request_id, "ghp_example")
    await settle()
    assert saved == ["ghp_example"] and sent == []


async def test_a_routine_and_a_talk_between_agents_are_not_continued(chat) -> None:
    svc, sent, settle, _end_turn, _connected = chat
    resume = connect_resume.ConnectResume(svc)
    resume.connected("society:ada:routine:t1:r1", "turn-1", "Gmail")
    resume.connected("society:ada:with:bob", "turn-1", "Gmail")
    assert resume._tasks == set()  # noqa: SLF001
    await settle()
    assert sent == []


def test_the_leads_card_survives_a_restart() -> None:
    """Rebuilt from the chat's history, the card still has somewhere to report to."""
    for session_id in (LEAD_CHAT, "society:ada"):
        assert AgentChatService._restore_credential_save(session_id, _GMAIL) is not None  # noqa: SLF001
    token = CredentialSpec.build("GITHUB_TOKEN", "GitHub token")
    # A secret still needs an agent's vault to go to.
    assert AgentChatService._restore_credential_save(LEAD_CHAT, token) is None  # noqa: SLF001


def test_the_request_is_what_the_person_typed_in_the_cards_turn() -> None:
    events = [
        make_event("user_message", {"text": "What is the weather like?"}),
        make_event("turn_started", {"turn_id": "turn-0"}),
        make_event("user_message", {"text": "composed prompt with a file", "typed": REQUEST}),
        make_event("turn_started", {"turn_id": "turn-1"}),
        make_event("user_message", {"text": "And what is in my calendar?"}),
        make_event("turn_started", {"turn_id": "turn-2"}),
    ]
    assert _request_of(events, "turn-1") == REQUEST
    assert _request_of(events, "turn-0") == "What is the weather like?"
    assert len(_request_of([make_event("user_message", {"text": "x" * 900})], "t")) == 200
