"""A question is never put to the person twice, and a default is never their choice.

Replays the Hermes run where the person answered "green", a stale receipt of an
earlier malformed call restarted the agent, the agent asked again and the
second card's timeout default ("red") was reported as the person's choice.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import dodaios_harness, runner_cli
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.questions import (
    PERSON,
    RECALL_WINDOW_S,
    RECALLED,
    TIMEOUT,
    parse_questions,
)
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.service import AgentChatService, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.agent_chat.task_recovery import ToolRecovery
from dodaios.agent_chat.turn_completion import TurnCompletion
from dodaios.core.protocols import ChatTurn, current_chat_turn
from dodaios.society.ask_tool import AskUserTool

_COLOUR: dict[str, Any] = {
    "question": "What is your favorite color?",
    "options": [{"label": "red"}, {"label": "green"}],
    "recommendation_reason": "No preference known.",
}
_SIZE: dict[str, Any] = {
    "question": "Which size?",
    "options": [{"label": "S"}, {"label": "M"}, {"label": "L"}],
    "recommendation_reason": "Most common.",
}

# The live receipts: a meta call whose arguments did not parse, then the
# corrected call, which the runtime reports under the inner tool's name.
_MALFORMED = (
    '[{"arguments": {"question": "What is your favorite color?", "options": ["red", '
    '"green"], "required": True}, "name": "mcp__dodaios__society_ask_user"}]'
)
_LIVE_RECEIPTS: list[tuple[str, str, Any, str, bool]] = [
    ("c1", "tool_search", {"queries": ["ask user"]}, "matches", False),
    (
        "c2", "tool_call", {"calls": _MALFORMED},
        "tool_call failed: tool_call 'calls' is not valid JSON: Expecting value", True,
    ),
    (
        "c3", "mcp__dodaios__society_ask_user", {"question": "What is your favorite color?"},
        '{"answers": [{"answer": "green", "source": "person"}]}', False,
    ),
]


def _feed(tracker: Any, receipts: list[tuple[str, str, Any, str, bool]]) -> None:
    for call_id, name, args, output, error in receipts:
        tracker.observe(make_event("tool_call", {"call_id": call_id, "name": name, "input": args}))
        tracker.observe(
            make_event("tool_result", {"call_id": call_id, "output": output, "is_error": error})
        )


# ------------------------------------------------------------ (a) stale receipts


def test_a_corrected_retry_settles_the_malformed_meta_call() -> None:
    tracker = ToolRecovery()
    _feed(tracker, _LIVE_RECEIPTS[:2])
    assert "tool_call" in (tracker.hint() or "")
    _feed(tracker, _LIVE_RECEIPTS[2:])
    assert tracker.hint() is None


def test_a_corrected_retry_of_the_same_tool_settles_its_refused_call() -> None:
    tracker = ToolRecovery()
    _feed(tracker, [
        ("c1", "society_ask_user", {"question": "?"}, "invalid questions: no options", True),
        ("c2", "society_ask_user", _COLOUR, "answered", False),
    ])
    assert tracker.hint() is None


def test_a_meta_call_of_another_tool_does_not_settle_a_refused_meta_call() -> None:
    tracker = ToolRecovery()
    _feed(tracker, [
        _LIVE_RECEIPTS[1],
        ("c3", "tool_call", {"calls": '[{"name": "mcp__dodaios__read_file"}]'}, "ok", False),
    ])
    assert "tool_call" in (tracker.hint() or "")
    _feed(tracker, [
        ("c4", "tool_call", {"calls": '[{"name": "mcp__dodaios__society_ask_user"}]'}, "ok", False),
    ])
    assert tracker.hint() is None


def test_a_real_failure_is_not_settled_by_another_target() -> None:
    tracker = ToolRecovery()
    _feed(tracker, [
        ("c1", "Write", {"path": "a.txt"}, "disk full", True),
        ("c2", "Write", {"path": "b.txt"}, "saved", False),
        ("c3", "tool_call", {"calls": '{"name": "Write"'}, "not valid JSON", True),
        ("c4", "Read", {"path": "b.txt"}, "contents", False),
    ])
    hint = tracker.hint() or ""
    assert "for Write" in hint and "for tool_call" in hint


def test_a_receipt_hint_alone_does_not_claim_the_last_call_failed() -> None:
    prompt = runner_cli._keep_going_prompt("Task", None, receipt_hint="hint")
    assert "The last tool call was cancelled or failed" not in prompt
    assert "An earlier tool call failed" in prompt
    assert "boom" in runner_cli._keep_going_prompt("Task", "boom")


@pytest.fixture
def turn(monkeypatch: pytest.MonkeyPatch):
    events: list[dict[str, Any]] = []
    session = SimpleNamespace(
        surface="society", session_id="society:qa", vendor_session="v", account_id=""
    )

    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    async def allow(*_args: Any) -> str:
        return "allow"

    async def briefing(*_args: Any) -> str:
        return "Agent instructions"

    async def identity(**_kwargs: Any) -> dodaios_harness.Identity:
        return dodaios_harness.Identity(session.session_id, "Agent", "Agent")

    async def language(*_args: Any) -> str:
        return "en"

    monkeypatch.setattr(runner_cli, "_surface_identity", briefing)
    monkeypatch.setattr(dodaios_harness, "build_identity", identity)
    monkeypatch.setattr("dodaios.society.reply_preference.resolve_agent_reply_language", language)
    handle = TurnHandle(
        session=session, turn_id="t1", emit=emit, request_approval=allow,
        cancel=asyncio.Event(), surface="society", stance="ask",
    )
    origin = ChatTurn(session.session_id, "t1", "Ask me which colour I prefer.", True, "trace")
    token = current_chat_turn.set(origin)
    try:
        yield handle, events, origin
    finally:
        current_chat_turn.reset(token)


@pytest.mark.parametrize("runner", ["hermes-cli", "openclaw-cli", "claude-cli", "codex-cli"])
async def test_an_answered_question_never_restarts_the_turn(turn, monkeypatch, runner) -> None:
    handle, events, origin = turn
    attempts: list[str] = []

    async def once(handle: Any, prompt: str, *_args: Any, **_kwargs: Any) -> Any:
        attempts.append(prompt)
        for call_id, name, args, output, error in _LIVE_RECEIPTS:
            await handle.emit(
                make_event("tool_call", {"call_id": call_id, "name": name, "input": args})
            )
            await handle.emit(
                make_event(
                    "tool_result", {"call_id": call_id, "output": output, "is_error": error}
                )
            )
        return runner_cli._Outcome("done", None, {}, None, "v")

    monkeypatch.setattr(runner_cli, "_run_cli_once", once)
    await runner_cli.run_cli_turn(handle, origin.user_text, runner, identity=True)
    assert len(attempts) == 1
    assert [e["payload"]["status"] for e in events if e["kind"] == "turn_finished"] == ["done"]


# ------------------------------------------------- (b) and (c) the card itself


async def _service(tmp_path: Path, turn_id: str = "turn-1") -> tuple[AgentChatService, str]:
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")
    session = svc.store.create_session(
        provider="fakeprov", model="m", effort="high", cwd=str(tmp_path)
    )
    _start_turn(svc, session.session_id, turn_id)
    return svc, session.session_id


def _start_turn(svc: AgentChatService, sid: str, turn_id: str) -> None:
    old = svc._running.get(sid)
    if old is not None and old.task is not None:
        old.task.cancel()
    run = _Running(turn_id, asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(3600))
    svc._running[sid] = run


async def _next(q: asyncio.Queue, kind: str) -> dict[str, Any]:
    while True:
        event = await asyncio.wait_for(q.get(), timeout=5)
        if event["kind"] == kind:
            return event["payload"]


async def _answer_green(svc: AgentChatService, sid: str, q: asyncio.Queue) -> None:
    asking = asyncio.create_task(svc.ask_questions(sid, parse_questions(_COLOUR)))
    card = await _next(q, "question_required")
    assert svc.resolve_question(sid, card["question_id"], index=0, option_index=1)
    (answer,) = await asking
    assert (answer.answer, answer.source) == ("green", PERSON)
    await _next(q, "question_resolved")


def _tool(svc: AgentChatService, sid: str) -> AskUserTool:
    runtime = SimpleNamespace(
        chat_service=lambda: svc, cached_agent=lambda _id: SimpleNamespace(name="QA")
    )
    return AskUserTool(runtime, "qa", session_id=sid)


async def test_the_same_question_again_returns_the_answer_without_a_card(tmp_path) -> None:
    svc, sid = await _service(tmp_path)
    q = svc.subscribe(sid)
    await _answer_green(svc, sid, q)
    asks = svc._running[sid].asks
    # Asked again (the recommendation now leads): no card, the person's answer.
    result = await _tool(svc, sid).execute({**_COLOUR, "recommended": 1}, None)
    (row,) = result.output["answers"]
    assert (row["answer"], row["source"], row["person_answered"]) == ("green", RECALLED, True)
    assert row["recommended"] is True  # green leads the re-asked card
    assert "do not ask again" in result.output["note"]
    assert svc._running[sid].asks == asks
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait()["kind"])
    assert "question_required" not in kinds and svc.pending_questions(sid) == []
    svc._running[sid].task.cancel()


async def test_only_the_unanswered_questions_stay_open(tmp_path) -> None:
    svc, sid = await _service(tmp_path)
    q = svc.subscribe(sid)
    await _answer_green(svc, sid, q)
    series = parse_questions({"questions": [_COLOUR, _SIZE]})
    asking = asyncio.create_task(svc.ask_questions(sid, series))
    card = await _next(q, "question_required")
    progress = await _next(q, "question_progress")
    assert progress["answers"][0]["source"] == RECALLED and progress["answers"][1] is None
    assert svc.resolve_question(sid, card["question_id"], index=1, option_index=2)
    first, second = await asking
    assert (first.answer, second.answer) == ("green", "L")
    svc._running[sid].task.cancel()


async def test_an_earlier_turn_counts_only_within_the_window(tmp_path, monkeypatch) -> None:
    svc, sid = await _service(tmp_path)
    q = svc.subscribe(sid)
    await _answer_green(svc, sid, q)
    _start_turn(svc, sid, "turn-2")
    svc._questions.clear()  # the first turn's cards closed with it
    (again,) = await svc.ask_questions(sid, parse_questions(_COLOUR))
    assert (again.answer, again.source) == ("green", RECALLED)
    _start_turn(svc, sid, "turn-3")
    svc._questions.clear()
    later = time.time() + RECALL_WINDOW_S + 60
    monkeypatch.setattr("dodaios.agent_chat.service.time.time", lambda: later)
    (fresh,) = await svc.ask_questions(sid, parse_questions(_COLOUR), timeout_s=0.05)
    assert fresh.source == TIMEOUT
    svc._running[sid].task.cancel()


async def test_a_timeout_never_overrides_what_the_person_answered(tmp_path) -> None:
    svc, sid = await _service(tmp_path)
    q = svc.subscribe(sid)
    specs = parse_questions(_COLOUR)
    first = asyncio.create_task(svc.ask_questions(sid, specs))
    card = await _next(q, "question_required")
    second = asyncio.create_task(svc.ask_questions(sid, specs, timeout_s=0.3))
    await _next(q, "question_required")
    assert svc.resolve_question(sid, card["question_id"], index=0, option_index=1)
    await first
    (late,) = await second
    assert (late.answer, late.source) == ("green", RECALLED)
    svc._running[sid].task.cancel()


async def test_a_timeout_default_tells_the_agent_nobody_chose_it(tmp_path) -> None:
    svc, sid = await _service(tmp_path)
    tool = _tool(svc, sid)
    original = svc.open_questions

    async def quick(*args: Any, **kwargs: Any) -> str:
        return await original(*args, **{**kwargs, "timeout_s": 0.05})

    svc.open_questions = quick  # type: ignore[method-assign]
    result = await tool.execute(dict(_COLOUR), None)
    (row,) = result.output["answers"]
    assert (row["answer"], row["source"], row["person_answered"]) == ("red", TIMEOUT, False)
    assert "Never say they chose it" in row["note"]
    assert "did not choose them" in result.output["note"]
    svc._running[sid].task.cancel()


async def test_the_continuation_marks_a_default_as_not_the_persons(tmp_path) -> None:
    svc, sid = await _service(tmp_path)
    qid = await svc.open_questions(sid, parse_questions(_COLOUR), timeout_s=0.05)
    await svc.wait_questions(sid, qid, 5)
    svc._questions[qid].delivered = False  # the runner never read it
    handle = SimpleNamespace(
        session=SimpleNamespace(session_id=sid), turn_id="turn-1", cancel=asyncio.Event()
    )
    completion = TurnCompletion(svc, handle, "Ask me", allow_correction=False)
    completion.finish_event = make_event("turn_finished", {"status": "done"})
    prompt = await completion.next_prompt()
    assert prompt is not None and '"person_answered": false' in prompt
    assert "Never say they chose it" in prompt
    svc._running[sid].task.cancel()
