"""A step that is one tool call: checked when it is written, made at once at the start."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.core import runtime_refs
from dodaios.core.protocols import ToolResult
from dodaios.rituals import instant, service
from dodaios.rituals.models import RitualError
from dodaios.rituals.store import get_store
from tests.unit.rituals.conftest import MONDAY_0830, settle

PLAY = {"tool": "music", "args": {"action": "play", "what": "liked"}, "says": "Music: liked songs"}
MUSIC_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["play", "pause"]},
        "what": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def _tool(name: str, schema: dict[str, Any] | None = None, *, instructions: bool = False) -> Any:
    return SimpleNamespace(
        name=name, input_schema=schema or {"type": "object"}, yields_instructions_only=instructions
    )


class Gateway:
    """Stands in for the app's tool gateway: a catalog and what each call answers."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answers: dict[str, Any] = {}
        self.tools = [
            _tool("music", MUSIC_SCHEMA),
            _tool("open_app"),
            _tool("run-skill", instructions=True),
        ]

    def catalog(self) -> tuple[Any, ...]:
        return tuple(self.tools)

    async def execute(self, name: str, arguments: dict[str, Any], request: Any) -> ToolResult:
        self.calls.append({"name": name, "args": arguments, "request": request})
        answer = self.answers.get(name, ToolResult(success=True, output="ok"))
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return await answer()
        return answer


@pytest.fixture
def gateway():
    fake = Gateway()
    before = runtime_refs.get_supervisor_tool_gateway()
    runtime_refs.set_supervisor_tool_gateway(fake)
    try:
        yield fake
    finally:
        runtime_refs.set_supervisor_tool_gateway(before)


def _ritual(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"name": "Good morning", "phrases": ["Good morning"], "steps": list(steps)}


async def _code(awaitable) -> tuple[str, str]:
    with pytest.raises(RitualError) as caught:
        await awaitable
    return caught.value.code, caught.value.message


# ── the call itself ─────────────────────────────────────────────────────────────


def test_a_call_names_a_tool_its_arguments_and_itself_in_plain_words() -> None:
    assert instant.clean(None) is None and instant.clean({}) is None
    assert instant.clean({"tool": " music ", "says": "  Music:   liked songs "}) == {
        "tool": "music", "args": {}, "says": "Music: liked songs",
    }
    assert len(instant.clean({"tool": "music", "says": "x" * 500})["says"]) == 160
    for bad in ("music", {"args": {}}, {"tool": "music", "args": ["play"]}):
        with pytest.raises(ValueError):
            instant.clean(bad)
    assert instant.line(PLAY) == "Music: liked songs"
    assert instant.line({"tool": "music", "args": {}, "says": ""}) == "music"


def test_a_call_is_checked_against_the_tools_the_app_has(gateway: Gateway) -> None:
    assert instant.problem(PLAY) == ""
    assert "no tool named 'jukebox'" in instant.problem({**PLAY, "tool": "jukebox"})
    wrong = instant.problem({**PLAY, "args": {"action": "shuffle"}})
    assert wrong.startswith("The arguments do not fit the tool 'music'")
    assert "only hands out instructions" in instant.problem({"tool": "run-skill", "args": {}})


def test_without_a_running_app_nothing_is_refused() -> None:
    before = runtime_refs.get_supervisor_tool_gateway()
    runtime_refs.set_supervisor_tool_gateway(None)
    try:
        assert instant.problem({"tool": "anything", "args": {}}) == ""
    finally:
        runtime_refs.set_supervisor_tool_gateway(before)


async def test_the_call_is_made_where_nobody_can_be_asked(gateway: Gateway) -> None:
    outcome = await instant.run(PLAY, sentence="Play my favourite music.")
    assert outcome == (True, "Music: liked songs", False)
    (call,) = gateway.calls
    assert (call["name"], call["args"]) == ("music", {"action": "play", "what": "liked"})
    request = call["request"]
    assert request.origin == "ritual" and request.user_utterance == "Play my favourite music."
    # A call that would need a question fails at once instead of waiting for nobody.
    assert request.config_snapshot == {"approval_surface": "unattended"}


async def test_a_call_that_does_not_work_says_why_and_never_raises(
    gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway.answers["music"] = ToolResult(success=False, output=None, error="No active device.")
    assert await instant.run(PLAY, sentence="x") == (
        False, "Music: liked songs: No active device.", True,
    )
    gateway.answers["music"] = RuntimeError("boom")
    assert await instant.run(PLAY, sentence="x") == (
        False, "Music: liked songs: RuntimeError", True,
    )

    async def never() -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult(success=True, output="late")

    gateway.answers["music"] = never
    monkeypatch.setattr(instant, "CALL_TIMEOUT_S", 0.05)
    # No answer in time: it may have happened, so no turn does it a second time.
    assert await instant.run(PLAY, sentence="x") == (
        False, "Music: liked songs: no answer in time, not tried again", False,
    )
    runtime_refs.set_supervisor_tool_gateway(None)
    assert await instant.run(PLAY, sentence="x") == (
        False, "Music: liked songs: the tools are not ready", True,
    )


# ── writing a ritual with one ───────────────────────────────────────────────────


async def test_a_step_for_the_moment_keeps_its_call(society, gateway: Gateway) -> None:
    ritual = await service.create(
        **_ritual(
            {"when": "now", "text": "Play my favourite music.", "call": PLAY},
            {"when": "now", "text": "Ask my agents where they stand."},
        )
    )
    first, second = ritual.steps
    assert first.call == PLAY and second.call is None
    assert first.to_dict()["call"] == PLAY and "call" not in second.to_dict()
    # It survives the store and a change that sends it back.
    assert service.get(ritual.id).steps[0].call == PLAY
    kept = await service.update(ritual.id, steps=[step.to_dict() for step in ritual.steps])
    assert kept.steps[0].call == PLAY
    # A reworded step that comes without it is done by a turn again.
    reworded = await service.update(
        ritual.id, steps=[{"id": first.id, "when": "now", "text": "Play something calm."}]
    )
    assert reworded.steps[0].call is None


async def test_a_call_that_cannot_be_made_is_refused_with_the_way_out(
    society, gateway: Gateway
) -> None:
    code, message = await _code(
        service.create(
            **_ritual({"when": "now", "text": "Play.", "call": {**PLAY, "tool": "jukebox"}})
        )
    )
    assert code == "invalid" and "no tool named 'jukebox'" in message
    assert "Leave 'call' out" in message
    code, message = await _code(
        service.create(**_ritual({"when": "ahead", "text": "The news.", "call": PLAY}))
    )
    assert code == "invalid" and "'now'" in message
    code, _ = await _code(
        service.create(**_ritual({"when": "now", "text": "Play.", "call": "music"}))
    )
    assert code == "invalid"
    assert service.list_rituals() == []


# ── the start ───────────────────────────────────────────────────────────────────


async def test_a_step_with_a_call_is_done_at_once_and_no_turn_is_started(
    society, gateway: Gateway
) -> None:
    ritual = await service.create(
        **_ritual({"when": "now", "text": "Play my favourite music.", "call": PLAY})
    )
    await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    await settle()
    assert [call["name"] for call in gateway.calls] == ["music"]
    assert society.chat.sent == []
    assert get_store().day(ritual.id, "2026-03-02").results == ("Music: liked songs",)


async def test_only_what_is_no_single_call_goes_to_a_turn(society, gateway: Gateway) -> None:
    ritual = await service.create(
        **_ritual(
            {"when": "now", "text": "Play my favourite music.", "call": PLAY},
            {"when": "now", "text": "Ask my agents where they stand."},
        )
    )
    await service.fire(ritual.id, via="chat", now=MONDAY_0830)
    await settle()
    assert len(gateway.calls) == 1
    (turn,) = society.chat.sent
    assert "1. Ask my agents where they stand." in turn["text"]
    assert "favourite music" not in turn["text"]


async def test_a_call_that_fails_leaves_its_step_to_the_turn(society, gateway: Gateway) -> None:
    gateway.answers["music"] = ToolResult(success=False, output=None, error="No active device.")
    ritual = await service.create(
        **_ritual({"when": "now", "text": "Play my favourite music.", "call": PLAY})
    )
    await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    await settle()
    (turn,) = society.chat.sent
    assert "1. Play my favourite music." in turn["text"]
    # The day remembers what was tried.
    assert get_store().day(ritual.id, "2026-03-02").results == (
        "Music: liked songs: No active device.",
    )


async def test_a_call_that_answers_too_late_is_not_done_a_second_time(
    society, gateway: Gateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow() -> ToolResult:
        # The music starts, but the answer comes after the start stopped waiting.
        await asyncio.sleep(0.2)
        return ToolResult(success=True, output="ok")

    gateway.answers["music"] = slow
    monkeypatch.setattr(instant, "CALL_TIMEOUT_S", 0.05)
    ritual = await service.create(
        **_ritual({"when": "now", "text": "Play my favourite music.", "call": PLAY})
    )
    await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    await settle()
    assert [call["name"] for call in gateway.calls] == ["music"]
    # No turn plays it again.
    assert society.chat.sent == []
    assert get_store().day(ritual.id, "2026-03-02").results == (
        "Music: liked songs: no answer in time, not tried again",
    )


async def test_a_switch_or_a_rename_saves_when_a_steps_tool_went_away(
    society, gateway: Gateway
) -> None:
    ritual = await service.create(
        **_ritual({"when": "now", "text": "Play my favourite music.", "call": PLAY})
    )
    # The plugin behind the tool was disconnected.
    gateway.tools = [tool for tool in gateway.tools if tool.name != "music"]
    switched = await service.update(ritual.id, enabled=False)
    assert switched.enabled is False and switched.steps[0].call == PLAY
    renamed = await service.update(ritual.id, name="Morning")
    assert renamed.name == "Morning" and renamed.steps[0].call == PLAY
    # A new call is still checked against the tools the app has.
    code, message = await _code(
        service.update(
            ritual.id,
            steps=[{"when": "now", "text": "Play.", "call": {**PLAY, "args": {"action": "stop"}}}],
        )
    )
    assert code == "invalid" and "no tool named 'music'" in message
