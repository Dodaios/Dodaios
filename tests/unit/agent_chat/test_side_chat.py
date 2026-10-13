"""The IDE's side chat: a plain conversation, no tools on any seat.

Pinned here: the surface seats only what can answer without tools, an API
seat's request carries no tool and the surface's own system prompt, a
tool-free CLI keeps its conversation for the next message and hears the
instructions once, and the model is told about the workspace folder.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.agent_chat import runner_api, service
from jarvis.agent_chat.catalog import rows_for
from jarvis.agent_chat.native_control import TOOL_FREE_RUNNERS, disable_cli_tools
from jarvis.agent_chat.runner_api import supports_api_runner
from jarvis.agent_chat.service import AgentChatService
from jarvis.agent_chat.store import AgentChatStore
from jarvis.agent_chat.surface_kits import kit_for
from jarvis.agentic_ide import side_chat
from jarvis.agentic_ide.prompt_blueprint import GOAL_NOT_IMPLEMENTATION_RULE
from jarvis.core.protocols import BrainDelta, BrainRequest


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
        BrainDelta(content="The frontend lives in frontend/."),
        BrainDelta(tool_call={"id": "c1", "name": "Read", "input": {"file_path": "x"}}),
    ]
    store = AgentChatStore(":memory:")
    try:
        svc = AgentChatService(store, assistant_name=lambda: "Testo")
        session = svc.create_session(provider="fakeprov", cwd=str(tmp_path), surface="side")
        queue = svc.subscribe(session.session_id)

        await svc.send(session.session_id, "where is the frontend?")
        events = await _until_finished(queue)

        request = brain.seen[0]
        assert request.tools == ()
        assert "You are Testo" in request.system and "no tools here" in request.system
        assert GOAL_NOT_IMPLEMENTATION_RULE in request.system
        assert str(tmp_path) in request.system and "frontend" in request.system
        assert request.messages[-1].content == "where is the frontend?"
        kinds = [event["kind"] for event in events]
        assert "tool_call" not in kinds and "approval_required" not in kinds
        assert events[-1]["payload"]["status"] == "done"
        assert len(brain.seen) == 1, "a plain turn is one request"
    finally:
        store.close()


async def test_a_cli_seat_hears_the_instructions_once_at_the_head_of_the_conversation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[tuple[str, bool, bool]] = []

    async def _run_cli_turn(handle: Any, prompt: str, runner: str, **_kwargs: object) -> str:
        prompts.append((prompt, handle.tools_disabled, bool(handle.plain_system)))
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

        (first, first_tool_free, first_plain), (second, second_tool_free, _plain) = prompts
        assert first.startswith("<side_chat_instructions>") and first.endswith("first question")
        assert "You are Testo" in first
        assert first_tool_free and first_plain and second_tool_free
        # The CLI resumed its own conversation, which already holds them.
        assert second == "second question"
    finally:
        store.close()


async def test_the_workspace_notes_describe_the_sessions_folder(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/feature/chat\n", encoding="utf-8")
    (tmp_path / "src").mkdir()

    prompt = await side_chat.system_prompt(SimpleNamespace(cwd=str(tmp_path)), "hello", "Testo")

    assert "WORKSPACE" in prompt
    assert str(tmp_path) in prompt and "feature/chat" in prompt and "src" in prompt


async def test_a_session_without_a_folder_has_no_workspace_notes(tmp_path: Path) -> None:
    for cwd in ("", str(tmp_path / "gone")):
        prompt = await side_chat.system_prompt(SimpleNamespace(cwd=cwd), "hello", "Testo")
        assert "WORKSPACE" not in prompt
        assert "You are Testo" in prompt


async def test_unreadable_notes_cost_the_notes_never_the_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _unreadable(*_args: object) -> str:
        raise OSError("disk went away")

    monkeypatch.setattr(side_chat, "workspace_notes", _unreadable)

    prompt = await side_chat.system_prompt(SimpleNamespace(cwd=str(tmp_path)), "hello", "Testo")

    assert "WORKSPACE" not in prompt and "You are Testo" in prompt
