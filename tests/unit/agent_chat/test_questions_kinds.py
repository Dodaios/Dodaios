"""Question kinds and the forgiving answer paths of the question card.

Multi-select and text-only questions, a reviewed series sent at once, skipping
one question, a chat message as the answer, and the guarantee that silence or
an unattended run never stalls, whatever the kind.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import turn_prompts
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.questions import (
    DECLINED,
    MESSAGE,
    MOVED_ON,
    MULTI,
    SINGLE,
    TEXT,
    answer_from,
    answer_json,
    parse_questions,
    recommended_answer,
)
from dodaios.agent_chat.service import AgentChatService, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.society.ask_tool import AskUserTool

_DB: dict[str, Any] = {
    "question": "Which database should the project use?",
    "options": [{"label": "SQLite"}, {"label": "Postgres"}],
    "recommendation_reason": "No server to run.",
}
_FEATURES: dict[str, Any] = {
    "question": "Which features should ship first?",
    "kind": "multi",
    "options": [{"label": "Search"}, {"label": "Export"}, {"label": "Sharing"}],
    "recommended": [2, 0],
    "recommendation_reason": "Most asked for.",
}
_NAME: dict[str, Any] = {"question": "What should the project be called?", "kind": "text"}


# ------------------------------------------------------------------ parsing


def test_multi_keeps_its_recommendations_first_in_the_agents_order() -> None:
    (spec,) = parse_questions(_FEATURES)
    assert spec.kind == MULTI
    assert [o.label for o in spec.options] == ["Sharing", "Search", "Export"]
    assert spec.recommended_indices == (0, 1)
    payload = spec.to_payload()
    assert payload["kind"] == "multi" and payload["recommended_count"] == 2


def test_every_runtime_spelling_of_multi_select_is_understood() -> None:
    for flag in ({"multiSelect": True}, {"multi": True}, {"multi_select": "true"}):
        (spec,) = parse_questions({**_DB, **flag})
        assert spec.kind == MULTI
    (plain,) = parse_questions({**_DB, "multiSelect": False})
    assert plain.kind == SINGLE


def test_a_single_question_payload_is_unchanged() -> None:
    (spec,) = parse_questions(_DB)
    assert set(spec.to_payload()) == {"question", "options", "recommended", "recommendation_reason"}


def test_a_text_question_needs_no_options_and_defaults_to_empty() -> None:
    (spec,) = parse_questions(_NAME)
    assert spec.kind == TEXT and spec.options == () and spec.allow_custom
    default = recommended_answer(spec, "timeout")
    assert (default.answer, default.option_index, default.source) == ("", None, "timeout")
    with pytest.raises(ValueError):
        answer_from(spec, option_index=None, text="")
    assert answer_from(spec, option_index=None, text=" Atlas ").answer == "Atlas"


def test_multi_answers_reach_the_agent_one_label_per_line() -> None:
    (spec,) = parse_questions(_FEATURES)
    picked = answer_from(spec, option_index=None, text="Dark mode", option_indices=[2, 0])
    assert picked.answer == "Sharing\nExport\nDark mode"
    assert picked.option_indices == (0, 2) and picked.option_index is None
    assert picked.to_payload()["option_indices"] == [0, 2]
    default = recommended_answer(spec, "timeout")
    assert default.answer == "Sharing\nSearch" and default.option_indices == (0, 1)
    with pytest.raises(ValueError):
        answer_from(spec, option_index=None, text=None, option_indices=[])
    with pytest.raises(ValueError):
        answer_from(spec, option_index=None, text=None, option_indices=[7])
    with pytest.raises(ValueError):
        parse_questions({**_FEATURES, "recommended": [0, 1, 2]})


def test_a_question_can_refuse_own_words() -> None:
    (spec,) = parse_questions({**_DB, "allow_custom": False})
    with pytest.raises(ValueError):
        answer_from(spec, option_index=None, text="MySQL")
    assert answer_json(spec, {"option_indices": [1]}).answer == "Postgres"
    assert answer_json(spec, {"skip": True}).source == DECLINED
    for bad in ({"option_index": "1"}, {"option_indices": "1"}, "nope", {}):
        with pytest.raises(ValueError):
            answer_json(spec, bad)


# ------------------------------------------------------------------ live cards


async def _service_with_turn(tmp_path: Path) -> tuple[AgentChatService, str, asyncio.Task[None]]:
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")
    session = svc.store.create_session(
        provider="fakeprov", model="m", effort="high", cwd=str(tmp_path)
    )
    run = _Running("turn-1", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(3600))
    svc._running[session.session_id] = run
    return svc, session.session_id, run.task


async def _next(q: asyncio.Queue, kind: str) -> dict[str, Any]:
    while True:
        ev = await asyncio.wait_for(q.get(), timeout=5)
        if ev["kind"] == kind:
            return ev["payload"]


def test_a_reviewed_series_resolves_with_one_submit(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, task = await _service_with_turn(tmp_path)
        q = svc.subscribe(sid)
        specs = parse_questions({"questions": [_DB, _FEATURES, _NAME]})
        asking = asyncio.create_task(svc.ask_questions(sid, specs))
        qid = (await _next(q, "question_required"))["question_id"]
        # A bad entry changes nothing: every answer is checked first.
        with pytest.raises(ValueError):
            svc.submit_questions(sid, qid, [{"option_index": 1}, {"option_indices": [9]}, {}])
        with pytest.raises(ValueError):
            svc.submit_questions(sid, qid, [{"option_index": 1}])
        assert svc.pending_questions(sid) == [qid]
        assert svc.submit_questions(
            sid,
            qid,
            [{"option_index": 1}, {"option_indices": [1, 2], "text": "Dark mode"}, {"skip": True}],
        )
        answers = await asking
        assert [(a.answer, a.source) for a in answers] == [
            ("Postgres", "person"),
            ("Search\nExport\nDark mode", "person"),
            ("", DECLINED),
        ]
        resolved = await _next(q, "question_resolved")
        assert resolved["answers"][1]["option_indices"] == [1, 2]
        assert not svc.submit_questions(sid, qid, [{}, {}, {}])  # closed
        task.cancel()

    asyncio.run(scenario())


def test_skipping_one_question_keeps_the_rest_open(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, task = await _service_with_turn(tmp_path)
        asking = asyncio.create_task(
            svc.ask_questions(sid, parse_questions({"questions": [_DB, _FEATURES]}))
        )
        await asyncio.sleep(0)
        (qid,) = svc.pending_questions(sid)
        assert svc.skip_question(sid, qid, 0)
        assert not svc.skip_question(sid, qid, 0)  # already settled
        assert svc.pending_questions(sid) == [qid]
        assert svc.resolve_question(sid, qid, index=1, option_indices=[2])
        answers = await asking
        assert [(a.answer, a.source) for a in answers] == [
            ("", DECLINED),
            ("Export", "person"),
        ]
        task.cancel()

    asyncio.run(scenario())


def test_silence_applies_multi_recommendations(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, task = await _service_with_turn(tmp_path)
        specs = parse_questions({"questions": [_FEATURES, _NAME]})
        answers = await svc.ask_questions(sid, specs, timeout_s=0.05)
        assert [(a.answer, a.source) for a in answers] == [
            ("Sharing\nSearch", "timeout"),
            ("", "timeout"),
        ]
        task.cancel()

    asyncio.run(scenario())


def test_a_touch_restarts_the_quiet_window(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, task = await _service_with_turn(tmp_path)
        q = svc.subscribe(sid)
        qid = await svc.open_questions(sid, parse_questions(_DB), timeout_s=0.4)
        first = await _next(q, "question_required")
        await asyncio.sleep(0.25)
        assert svc.touch_question(sid, qid)
        progress = await _next(q, "question_progress")
        assert progress["expires_ms"] > first["expires_ms"]
        await asyncio.sleep(0.25)  # past the first deadline, inside the new one
        assert svc.pending_questions(sid) == [qid]
        answers = await svc.wait_questions(sid, qid, 5)
        assert answers is not None and answers[0].source == "timeout"
        assert not svc.touch_question(sid, qid)
        task.cancel()

    asyncio.run(scenario())


def test_a_chat_message_answers_the_newest_card(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, task = await _service_with_turn(tmp_path)
        svc._running[sid].asks = -1  # room for three cards in this turn
        older = await svc.open_questions(sid, parse_questions(_DB))
        sticky = await svc.open_questions(
            sid, parse_questions({**_NAME, "dismiss_on_move_on": False})
        )
        newest = await svc.open_questions(
            sid, parse_questions({"questions": [_FEATURES, {**_DB, "question": "And hosting?"}]})
        )
        outcome = await svc.answer_by_message(sid, "Only search, please")
        assert outcome == {"consumed": True, "question_id": newest}
        answers = await svc.wait_questions(sid, newest, 5)
        assert answers is not None
        assert [(a.answer, a.source) for a in answers] == [
            ("Only search, please", MESSAGE),
            ("SQLite", MOVED_ON),
        ]
        (old,) = await svc.wait_questions(sid, older, 5) or []
        assert (old.answer, old.source) == ("SQLite", MOVED_ON)
        assert svc.pending_questions(sid) == [sticky]  # asked to stay open
        task.cancel()

    asyncio.run(scenario())


def test_a_message_naming_an_option_picks_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, task = await _service_with_turn(tmp_path)
        qid = await svc.open_questions(sid, parse_questions(_DB))
        assert (await svc.answer_by_message(sid, "b"))["consumed"]
        (answer,) = await svc.wait_questions(sid, qid, 5) or []
        assert (answer.answer, answer.option_index, answer.source) == ("Postgres", 1, MESSAGE)
        # Nothing open: the message is an ordinary message.
        assert await svc.answer_by_message(sid, "thanks") == {
            "consumed": False,
            "question_id": None,
        }
        task.cancel()

    asyncio.run(scenario())


# ------------------------------------------------------------------ the ask tool


class _Service:
    def __init__(self, answers: Any) -> None:
        self.answers = answers

    async def open_questions(self, session_id: str, specs: Any, *, asker: str = "") -> str:
        self.specs = specs
        return "q1"

    async def wait_questions(self, session_id: str, question_id: str, timeout_s: Any) -> Any:
        return self.answers(self.specs)


def _tool(session_id: str, service: Any) -> AskUserTool:
    runtime = SimpleNamespace(
        chat_service=lambda: service, cached_agent=lambda _id: SimpleNamespace(name="Ada")
    )
    return AskUserTool(runtime, "ada", session_id=session_id)


def test_the_tool_offers_the_kinds_without_requiring_options() -> None:
    item = AskUserTool.schema["properties"]["questions"]["items"]
    assert item["properties"]["kind"]["enum"] == ["single", "multi", "text"]
    assert "options" not in item["required"]


def test_the_tool_reports_multi_picks_and_a_skipped_question() -> None:
    def answers(specs: Any) -> Any:
        return [
            answer_from(specs[0], option_index=None, text=None, option_indices=[1, 2]),
            answer_json(specs[1], {"skip": True}),
        ]

    args = {"questions": [_FEATURES, _NAME]}
    result = asyncio.run(_tool("society:ada", _Service(answers)).execute(args, None))
    assert result.success
    first, second = result.output["answers"]
    assert first["picked"] == ["Search", "Export"] and first["answer"] == "Search\nExport"
    assert second["source"] == DECLINED
    assert "decide it yourself" in result.output["note"]


def test_the_tool_reads_a_chat_reply_as_the_answer() -> None:
    def answers(specs: Any) -> Any:
        return [answer_from(specs[0], option_index=None, text="Neither", source=MESSAGE)]

    result = asyncio.run(_tool("society:ada", _Service(answers)).execute(dict(_DB), None))
    (row,) = result.output["answers"]
    assert row["typed"] is True and row["source"] == MESSAGE
    assert "replied in the chat" in result.output["note"]


def test_a_routine_never_waits_on_any_kind() -> None:
    def never(_specs: Any) -> Any:
        raise AssertionError("a routine must not open a card")

    args = {"questions": [_FEATURES, _NAME]}
    result = asyncio.run(_tool("society:ada:routine:t1:run1", _Service(never)).execute(args, None))
    assert [r["answer"] for r in result.output["answers"]] == ["Sharing\nSearch", ""]
    assert {r["source"] for r in result.output["answers"]} == {"unattended"}


# ------------------------------------------------------------------ end-of-turn cards


async def _deferred(tmp_path: Path, payload: Any) -> tuple[AgentChatService, str, list[Any]]:
    svc = AgentChatService(AgentChatStore(":memory:"))
    session = svc.store.create_session(
        provider="openai-codex", model="", effort="", cwd=str(tmp_path),
        permission_mode="auto", surface="agent",
    )
    sent: list[tuple[str, str | None]] = []

    async def send(session_id: str, text: str, *_: Any, **kwargs: Any) -> str:
        sent.append((text, kwargs.get("display_text")))
        return "next"

    svc.send = send  # type: ignore[method-assign]
    sid = session.session_id
    block = f"Two choices.\n\n```{turn_prompts.ASK_FENCE}\n{json.dumps(payload)}\n```\n"
    await svc._emit(sid, make_event("turn_started", {"turn_id": "t1"}))
    await svc._emit(sid, make_event("assistant_text", {"turn_id": "t1", "text": block}))
    await svc._emit(sid, make_event("turn_finished", {"turn_id": "t1", "status": "done"}))
    await svc._open_turn_prompts(sid, "t1", "codex-cli")
    return svc, sid, sent


def _payloads(svc: AgentChatService, sid: str, kind: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in svc.store.list_events(sid) if e["kind"] == kind]


def test_a_fence_can_ask_a_multi_select_question(tmp_path: Path) -> None:
    async def scenario() -> None:
        fence = {"questions": [{**_DB, "multi": True}, _NAME]}
        svc, sid, sent = await _deferred(tmp_path, fence)
        (card,) = _payloads(svc, sid, "question_required")
        assert card["questions"][0]["kind"] == "multi" and card["questions"][1]["kind"] == "text"
        qid = card["question_id"]
        assert await svc.submit_turn_question(
            sid, qid, [{"option_indices": [0, 1]}, {"text": "Atlas"}]
        )
        ((prompt, shown),) = sent
        assert "Which database should the project use? -> SQLite, Postgres" in prompt
        assert "What should the project be called? -> Atlas" in prompt
        assert shown.splitlines()[0].endswith("SQLite, Postgres")
        assert not await svc.submit_turn_question(sid, qid, [{}, {}])

    asyncio.run(scenario())


def test_skipping_one_deferred_question_sends_once_settled(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _deferred(tmp_path, {"questions": [_DB, _NAME]})
        qid = _payloads(svc, sid, "question_required")[0]["question_id"]
        assert await svc.skip_turn_question(sid, qid, index=1)
        assert sent == [] and len(_payloads(svc, sid, "question_progress")) == 1
        assert await svc.answer_turn_question(sid, qid, index=0, option_index=1)
        ((prompt, _),) = sent
        assert "-> skipped; decide it yourself." in prompt

    asyncio.run(scenario())


def test_a_chat_message_settles_a_deferred_card_without_consuming(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _deferred(tmp_path, {"questions": [_DB, _NAME]})
        qid = _payloads(svc, sid, "question_required")[0]["question_id"]
        assert turn_prompts.newest_open_ask(svc.store.list_events(sid)) is not None
        outcome = await svc.answer_by_message(sid, "Postgres, and call it Atlas")
        assert outcome == {"consumed": False, "question_id": qid}
        (resolved,) = _payloads(svc, sid, "question_resolved")
        assert [(a["answer"], a["source"]) for a in resolved["answers"]] == [
            ("Postgres, and call it Atlas", MESSAGE),
            ("", MOVED_ON),
        ]
        assert sent == []  # the caller sends the message itself
        assert turn_prompts.newest_open_ask(svc.store.list_events(sid)) is None

    asyncio.run(scenario())


def test_a_stored_multi_card_keeps_every_recommendation(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _deferred(tmp_path, {"questions": [_FEATURES]})
        (card,) = _payloads(svc, sid, "question_required")
        assert card["questions"][0]["recommended_count"] == 2
        # The card is read back from its event; closing it applies both picks.
        assert await svc.skip_turn_question(sid, card["question_id"])
        ((prompt, _),) = sent
        assert "go with your recommendation (Sharing, Search)" in prompt

    asyncio.run(scenario())


def test_a_stored_multi_payload_parses_back_to_the_same_question() -> None:
    (spec,) = parse_questions(_FEATURES)
    (again,) = parse_questions({"questions": [spec.to_payload()]})
    assert again == spec
