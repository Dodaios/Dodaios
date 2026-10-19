"""The IDE's side chat: a plain conversation, no tools on any seat.

Pinned here: the surface seats only what can answer without tools, an API
seat's request carries no tool and the surface's own system prompt, a
tool-free CLI keeps its conversation for the next message and hears the
instructions whenever it starts one, and the model is told nothing about the
workspace: this is a plain AI chat.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import plain_chat, runner_api, service
from dodaios.agent_chat.catalog import rows_for
from dodaios.agent_chat.native_control import TOOL_FREE_RUNNERS, disable_cli_tools
from dodaios.agent_chat.runner_api import supports_api_runner
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.agent_chat.surface_kits import kit_for
from dodaios.agentic_ide import side_chat
from dodaios.core.protocols import BrainDelta, BrainRequest


class _Brain:
    """Answers from ``script`` and keeps the requests it was sent."""

    script: list[BrainDelta] = []
    seen: list[BrainRequest] = []

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        _Brain.seen.append(req)
        for delta in _Brain.script or [BrainDelta(content="Sure.")]:
            await asyncio.sleep(0)
            yield delta


@pytest.fixture
def brain(monkeypatch: pytest.MonkeyPatch) -> type[_Brain]:
    _Brain.script, _Brain.seen = [], []
    monkeypatch.setitem(
        runner_api.BRAIN_BY_PROVIDER, "fakeprov", ("tests.unit.agent_chat.test_side_chat", "_Brain")
    )
    return _Brain


async def _until_finished(queue: asyncio.Queue) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=5)
        events.append(event)
        if event["kind"] == "turn_finished":
            return events


def test_the_side_chat_seats_only_what_can_answer_without_tools() -> None:
    assert kit_for("side").plain
    assert not kit_for("agent").plain
    rows = rows_for("side")
    assert rows, "a plain chat still needs seats"
    for row in rows:
        assert supports_api_runner(row.id) or row.runner in TOOL_FREE_RUNNERS, row.id


@pytest.mark.parametrize("runner", sorted(TOOL_FREE_RUNNERS))
def test_every_tool_free_cli_can_drop_its_tools_and_keep_the_conversation(runner: str) -> None:
    """A chat's next message resumes this one, so the CLI must persist it."""
    kept = SimpleNamespace(argv=["binary", "exec"])
    disable_cli_tools(kept, runner, keep_session=True)
    assert "--no-session-persistence" not in kept.argv and "--ephemeral" not in kept.argv

    one_shot = SimpleNamespace(argv=["binary", "exec"])
    disable_cli_tools(one_shot, runner)
    assert "--no-session-persistence" in one_shot.argv or "--ephemeral" in one_shot.argv


async def test_an_api_seat_gets_no_tools_and_the_surfaces_own_system_prompt(
    tmp_path: Path, brain: type[_Brain]
) -> None:
    (tmp_path / "frontend").mkdir()
    # A model that asks for a tool anyway is not handed one.
    brain.script = [
        BrainDelta(content="Paris."),
        BrainDelta(tool_call={"id": "c1", "name": "Read", "input": {"file_path": "x"}}),
    ]
    store = AgentChatStore(":memory:")
    try:
        svc = AgentChatService(store, assistant_name=lambda: "Testo")
        session = svc.create_session(provider="fakeprov", cwd=str(tmp_path), surface="side")
        queue = svc.subscribe(session.session_id)

        await svc.send(session.session_id, "what is the capital of France?")
        events = await _until_finished(queue)

        request = brain.seen[0]
        assert request.tools == ()
        assert "You are Testo" in request.system and "no tools in this chat" in request.system
        # A plain chat: nothing about the folder the session happens to sit in.
        assert str(tmp_path) not in request.system and "frontend" not in request.system
        assert request.messages[-1].content == "what is the capital of France?"
        kinds = [event["kind"] for event in events]
        assert "tool_call" not in kinds and "approval_required" not in kinds
        assert events[-1]["payload"]["status"] == "done"
        assert len(brain.seen) == 1, "a plain turn is one request"
    finally:
        store.close()


async def test_a_cli_seat_runs_tool_free_and_carries_the_surfaces_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[tuple[str, bool, str]] = []

    async def _run_cli_turn(handle: Any, prompt: str, runner: str, **_kwargs: object) -> str:
        prompts.append((prompt, handle.tools_disabled, handle.plain_system))
        await handle.emit(
            service.make_event(
                "turn_finished",
                {"turn_id": handle.turn_id, "status": "done", "duration_ms": 1, "usage": {}},
            )
        )
        return "vendor-1"

    monkeypatch.setattr(service, "resolve_runner", lambda provider, **_kwargs: "claude-cli")
    monkeypatch.setattr(service, "run_cli_turn", _run_cli_turn)
    store = AgentChatStore(":memory:")
    try:
        svc = AgentChatService(store, assistant_name=lambda: "Testo")
        session = svc.create_session(provider="claude-api", cwd=str(tmp_path), surface="side")
        queue = svc.subscribe(session.session_id)

        await svc.send(session.session_id, "first question")
        await _until_finished(queue)
        await svc.send(session.session_id, "second question")
        await _until_finished(queue)

        # The runner decides where the instructions go; the service hands it
        # the person's own words and the surface's prompt beside them.
        assert [prompt for prompt, _tool_free, _system in prompts] == [
            "first question",
            "second question",
        ]
        assert all(tool_free for _prompt, tool_free, _system in prompts)
        assert all("You are Testo" in system for _prompt, _tool_free, system in prompts)
    finally:
        store.close()


def _handle(system: str = "Be a plain chat.", history: list[dict[str, Any]] | None = None) -> Any:
    return SimpleNamespace(plain_system=system, history=history or [])


def test_a_cli_conversation_opens_with_the_instructions() -> None:
    prompt = plain_chat.cli_prompt(_handle(), "first question", None)
    assert prompt.startswith("<chat_instructions>\nBe a plain chat.\n</chat_instructions>")
    assert prompt.endswith("first question")
    assert "<earlier_conversation>" not in prompt


def test_a_resumed_cli_conversation_gets_the_persons_words_alone() -> None:
    assert plain_chat.cli_prompt(_handle(), "second question", "vendor-1") == "second question"


def test_a_conversation_restarted_after_a_lost_resume_gets_instructions_and_history() -> None:
    """A fresh CLI session must not leave the chat without its framing."""
    history = [
        {"kind": "user_message", "payload": {"text": "what is the plan?"}},
        {"kind": "reasoning", "payload": {"text": "private thinking"}},
        {"kind": "assistant_text", "payload": {"text": "Ship the chat."}},
    ]
    prompt = plain_chat.cli_prompt(_handle(history=history), "and then?", None)
    assert prompt.startswith("<chat_instructions>")
    assert "User: what is the plan?\n\nAssistant: Ship the chat." in prompt
    assert "private thinking" not in prompt
    assert prompt.endswith("and then?")


def test_a_long_chat_keeps_its_newest_messages_in_the_transcript() -> None:
    history = [
        {"kind": "user_message", "payload": {"text": f"message {index} " + "x" * 400}}
        for index in range(40)
    ]
    kept = plain_chat.transcript(history, max_chars=2000)
    assert "message 39" in kept and "message 0 " not in kept
    assert len(kept) < 2600


def test_a_surface_with_tools_sends_the_cli_the_message_as_it_is() -> None:
    handle = SimpleNamespace(plain_system="", history=[])
    assert plain_chat.cli_prompt(handle, "do the work", None) == "do the work"
    assert plain_chat.permission_mode(handle, "codex-cli", "full-access") == "full-access"


def test_a_plain_chat_on_a_cli_that_could_still_write_runs_read_only() -> None:
    assert plain_chat.permission_mode(_handle(), "codex-cli", "full-access") == "read-only"
    # No tool at all leaves nothing to sandbox.
    assert plain_chat.permission_mode(_handle(), "claude-cli", "bypassPermissions") == (
        "bypassPermissions"
    )


async def test_the_chat_is_told_how_to_answer_and_nothing_about_a_workspace(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()

    prompt = await side_chat.system_prompt(SimpleNamespace(cwd=str(tmp_path)), "hi", "Testo")

    assert prompt.startswith("You are Testo, an AI assistant in a chat.")
    assert "no tools in this chat" in prompt
    assert str(tmp_path) not in prompt and "src" not in prompt
    assert prompt == await side_chat.system_prompt(SimpleNamespace(cwd=""), "other", "Testo")


def test_a_plain_chat_ignores_a_folder_that_no_longer_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that still remembers a deleted folder must not lose the chat."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web.agent_chat_routes import router

    store = AgentChatStore(":memory:")
    try:
        app = FastAPI()
        app.include_router(router)
        app.state.agent_chat = AgentChatService(store, default_cwd=lambda: str(tmp_path))
        client = TestClient(app)
        gone = str(tmp_path / "deleted-worktree")

        created = client.post(
            "/api/agent-chat/sessions",
            json={"provider": "openai", "surface": "side", "cwd": gone},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]
        assert created.json()["cwd"] != gone

        patched = client.patch(f"/api/agent-chat/sessions/{session_id}", json={"cwd": gone})
        assert patched.status_code == 200, patched.text
        assert patched.json()["cwd"] != gone

        catalog = client.get("/api/agent-chat/catalog", params={"surface": "side", "cwd": gone})
        assert catalog.status_code == 200, catalog.text

        # Every other surface still refuses a folder that is not there.
        refused = client.post(
            "/api/agent-chat/sessions",
            json={"provider": "openai", "surface": "agent", "cwd": gone},
        )
        assert refused.status_code == 400
    finally:
        store.close()
