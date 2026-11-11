"""The ask-gate: memory first, then reversibility and confidence, then one question."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import ask_gate
from dodaios.agent_chat.ask_gate import AskContext, decide, pending_reversibility
from dodaios.agent_chat.questions import MEMORY, UNATTENDED, answer_from, parse_questions
from dodaios.society.ask_tool import AskUserTool
from dodaios.trust.ask_log import AskLog, set_ask_log

_AIRLINE: dict[str, Any] = {
    "question": "Which airline should I book for your flights?",
    "options": [{"label": "Lufthansa"}, {"label": "Ryanair"}],
    "recommendation_reason": "Cheapest.",
}
_ROOM: dict[str, Any] = {
    "question": "Which room should the meeting use?",
    "options": [{"label": "Small room"}, {"label": "Big room"}],
    "recommendation_reason": "Four people.",
}


def _specs(*raw: dict[str, Any]) -> Any:
    return parse_questions({"questions": list(raw)})


def _memory(*texts: str) -> Any:
    return lambda _query: [(t, ()) for t in texts]


def test_a_memory_hit_answers_without_a_card() -> None:
    search = _memory("Always books Lufthansa for flights, never budget airlines.")
    result = decide(_specs(_AIRLINE), AskContext(reversibility="irreversible"), search)
    assert not result.needs_card
    (d,) = result.decisions
    assert d.decision == ask_gate.FROM_MEMORY
    assert d.answer is not None and d.answer.answer == "Lufthansa" and d.answer.source == MEMORY


def test_a_memory_that_names_both_options_or_none_is_not_an_answer() -> None:
    both = _memory("Flights: Lufthansa for long trips, Ryanair for short flights.")
    unrelated = _memory("Lufthansa is a German company.")
    for search in (both, unrelated, _memory()):
        result = decide(_specs(_AIRLINE), AskContext(reversibility="irreversible"), search)
        assert result.needs_card


def test_reversible_and_confident_acts_with_the_assumption() -> None:
    ctx = AskContext(reversibility="reversible", confidence=0.85, clarify_enabled=True)
    result = decide(_specs(_ROOM), ctx)
    (d,) = result.decisions
    assert not result.needs_card and d.decision == ask_gate.ASSUME
    assert d.answer is not None and d.answer.answer == "Small room"
    assert d.answer.source == UNATTENDED


def test_reversible_but_unsure_asks_only_when_clarify_is_on() -> None:
    on = AskContext(reversibility="reversible", confidence=0.4, clarify_enabled=True)
    off = AskContext(reversibility="reversible", confidence=0.4)
    assert decide(_specs(_ROOM), on).needs_card
    assert not decide(_specs(_ROOM), off).needs_card


def test_irreversible_asks_even_when_confident() -> None:
    ctx = AskContext(reversibility="irreversible", confidence=0.95)
    assert decide(_specs(_ROOM), ctx).needs_card


def test_clarify_off_still_asks_for_a_missing_required_parameter() -> None:
    off = AskContext(reversibility="reversible", confidence=0.3, clarify_enabled=False)
    assert not decide(_specs(_ROOM), off).needs_card
    missing = AskContext(reversibility="reversible", confidence=0.3, missing_required=True)
    assert decide(_specs(_ROOM), missing).needs_card


def test_an_unclassified_action_counts_as_costly() -> None:
    assert decide(_specs(_ROOM), AskContext()).needs_card


def test_one_question_at_a_time() -> None:
    result = decide(_specs(_AIRLINE, _ROOM), AskContext(reversibility="irreversible"))
    assert result.ask_indices == (0,)
    assert [d.decision for d in result.decisions] == [ask_gate.ASK, ask_gate.TRIMMED]


def test_reversibility_comes_from_the_tool_table_unless_declared() -> None:
    assert pending_reversibility("gmail", "send_message") == "irreversible"
    assert pending_reversibility("gmail", "create_draft") == "reversible"
    assert pending_reversibility("gmail", "create_draft", "irreversible") == "irreversible"
    assert pending_reversibility("", "") == ""


class _Service:
    def __init__(self) -> None:
        self.opened: list[Any] = []

    async def open_questions(self, session_id: str, specs: Any, *, asker: str = "") -> str:
        self.opened.append(specs)
        return "q1"

    def question_specs(self, session_id: str, question_id: str) -> Any:
        return self.opened[-1]

    async def wait_questions(self, session_id: str, question_id: str, timeout_s: Any) -> Any:
        return [answer_from(s, option_index=1, text=None) for s in self.opened[-1]]


@pytest.fixture
def log(tmp_path: Path):
    ask_log = AskLog(tmp_path / "ask.db")
    set_ask_log(ask_log)
    yield ask_log
    set_ask_log(None)
    ask_log.close()


def _tool(service: _Service, *, clarify: bool = False) -> AskUserTool:
    config = SimpleNamespace(voice=SimpleNamespace(clarify_incomplete_enabled=clarify))
    runtime = SimpleNamespace(
        chat_service=lambda: service,
        cached_agent=lambda _id: SimpleNamespace(name="Ada"),
        config=config,
    )
    return AskUserTool(runtime, "ada", session_id="society:ada")


def test_the_tool_answers_from_memory_and_logs_it(monkeypatch, log: AskLog) -> None:
    monkeypatch.setattr(
        ask_gate, "vault_search", lambda: _memory("Always books Lufthansa for flights.")
    )
    service = _Service()
    args = {**_AIRLINE, "pending_action": {"tool": "gmail", "action": "send_message"}}
    result = asyncio.run(_tool(service).execute(args, None))
    assert result.success and service.opened == []
    assert result.output["status"] == "not_asked"
    (row,) = result.output["answers"]
    assert row["answer"] == "Lufthansa" and row["source"] == MEMORY
    (logged,) = log.rows()
    assert logged["decision"] == ask_gate.FROM_MEMORY


def test_the_tool_acts_with_an_assumption_when_reversible_and_confident(
    monkeypatch, log: AskLog
) -> None:
    monkeypatch.setattr(ask_gate, "vault_search", lambda: None)
    service = _Service()
    args = {
        **_ROOM,
        "pending_action": {"tool": "google_calendar", "action": "create_event"},
        "confidence": 0.9,
    }
    result = asyncio.run(_tool(service, clarify=True).execute(args, None))
    assert service.opened == [] and result.output["status"] == "not_asked"
    assert result.output["answers"][0]["answer"] == "Small room"
    assert "state each assumption" in result.output["note"]


def test_the_tool_asks_for_an_irreversible_action(monkeypatch, log: AskLog) -> None:
    monkeypatch.setattr(ask_gate, "vault_search", lambda: None)
    service = _Service()
    args = {**_ROOM, "pending_action": {"tool": "gmail", "action": "send_message"}}
    result = asyncio.run(_tool(service).execute(args, None))
    assert len(service.opened) == 1 and result.output["answers"][0]["answer"] == "Big room"
    (logged,) = log.rows()
    assert logged["decision"] == ask_gate.ASK and logged["answer"] == "Big room"
    assert logged["needless"] == ""


def test_a_card_is_needless_when_memory_holds_the_answer_afterwards(
    monkeypatch, log: AskLog
) -> None:
    searches = iter([None, _memory("Meetings always use the Big room.")])
    monkeypatch.setattr(ask_gate, "vault_search", lambda: next(searches))
    service = _Service()
    args = {**_ROOM, "pending_action": {"tool": "gmail", "action": "send_message"}}
    asyncio.run(_tool(service).execute(args, None))
    (logged,) = log.rows()
    assert logged["needless"] == "in_memory"


def test_clarify_default_is_off() -> None:
    from dodaios.core.config import VoiceConfig

    assert VoiceConfig().clarify_incomplete_enabled is False
