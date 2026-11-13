"""The lead's own chat asks on the question card, on every seat."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.questions import answer_from
from dodaios.brain.lead_doctrine import LEAD_DOCTRINE
from dodaios.brain.lead_manifest import LEAD_ONLY_TOOLS
from dodaios.society import ask_tool
from dodaios.society.ask_tool import ASK_USER_TOOL_NAME, AskUserTool, lead_ask_tools

_DB: dict[str, Any] = {
    "question": "Which database should the project use?",
    "options": [{"label": "SQLite"}, {"label": "Postgres"}],
    "recommendation_reason": "No server to run.",
}
_HOST: dict[str, Any] = {
    "question": "Where should it run?",
    "options": [{"label": "Laptop"}, {"label": "VPS"}],
    "recommendation_reason": "Nothing to pay for.",
}


class _Service:
    """A chat service whose card is answered with option B after ``polls`` open slices."""

    def __init__(self, polls: int = 0) -> None:
        self.polls = polls
        self.asked: list[tuple[str, str]] = []
        self.specs: dict[str, Any] = {}

    async def open_questions(self, session_id: str, specs: Any, *, asker: str = "") -> str:
        self.asked.append((session_id, asker))
        self.specs["q1"] = specs
        return "q1"

    def question_specs(self, session_id: str, question_id: str) -> Any:
        return self.specs[question_id]

    async def wait_questions(self, session_id: str, question_id: str, timeout_s: Any) -> Any:
        if self.polls:
            self.polls -= 1
            return None
        return [answer_from(spec, option_index=1, text=None) for spec in self.specs[question_id]]


def _runtime(service: _Service, config: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        lead_id="lead",
        chat_service=lambda: service,
        cached_agent=lambda _id: SimpleNamespace(name="Jarvis"),
        config=lambda: config,
    )


@pytest.fixture(autouse=True)
def _no_gates_left_over():
    ask_tool._OPEN_GATES.clear()
    yield
    ask_tool._OPEN_GATES.clear()


def test_the_leads_chat_gets_the_ask_tool_under_the_leads_shown_name(monkeypatch) -> None:
    service = _Service()
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: _runtime(service))
    monkeypatch.setattr("dodaios.society.display_name.lead_display_name", lambda: "Dodaios")

    tools = lead_ask_tools(SimpleNamespace(session_id="chat-1"))

    assert list(tools) == [ASK_USER_TOOL_NAME]
    result = asyncio.run(tools[ASK_USER_TOOL_NAME].execute(dict(_DB), None))
    assert result.success and result.output["answers"][0]["answer"] == "Postgres"
    # The card names the lead as the person knows it, not the roster row.
    assert service.asked == [("chat-1", "Dodaios")]


def test_no_ask_tool_without_a_runtime_a_session_or_in_a_routine(monkeypatch) -> None:
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: None)
    assert lead_ask_tools(SimpleNamespace(session_id="chat-1")) == {}
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: _runtime(_Service()))
    assert lead_ask_tools(SimpleNamespace(session_id="")) == {}
    assert lead_ask_tools(SimpleNamespace(session_id="society:lead:routine:t1:run1")) == {}


def test_a_new_tool_for_the_waiting_call_still_returns_the_gated_questions() -> None:
    """A CLI seat builds a new tool for every call: the one that keeps waiting
    is not the one that opened the card."""
    service = _Service(polls=1)
    runtime = _runtime(service)
    args = {"questions": [_DB, _HOST]}

    first = asyncio.run(AskUserTool(runtime, "lead", session_id="chat-1").execute(args, None))
    assert first.output["status"] == "waiting"

    second = asyncio.run(
        AskUserTool(runtime, "lead", session_id="chat-1").execute({"wait_for": "q1"}, None)
    )
    # The asked question with the person's answer, and the one the gate did
    # not ask with its recommendation, named as an assumption.
    assert [r["answer"] for r in second.output["answers"]] == ["Postgres", "Laptop"]
    assert second.output["answers"][1]["person_answered"] is False
    assert any(note.startswith("trimmed") for note in second.output["gate"])
    assert ask_tool._OPEN_GATES == {}


def test_another_chat_cannot_take_a_cards_gate() -> None:
    service = _Service(polls=1)
    runtime = _runtime(service)
    asyncio.run(
        AskUserTool(runtime, "lead", session_id="chat-1").execute({"questions": [_DB, _HOST]}, None)
    )
    assert ask_tool._take_gate("chat-2", "q1") is None
    assert ask_tool._take_gate("chat-1", "q1") is not None


def test_the_owners_clarify_setting_is_read_from_the_runtimes_config_method() -> None:
    on = SimpleNamespace(voice=SimpleNamespace(clarify_incomplete_enabled=True))
    off = SimpleNamespace(voice=SimpleNamespace(clarify_incomplete_enabled=False))
    service = _Service()
    assert AskUserTool(_runtime(service, on), "lead", session_id="c")._clarify_enabled() is True
    assert AskUserTool(_runtime(service, off), "lead", session_id="c")._clarify_enabled() is False
    assert AskUserTool(_runtime(service), "lead", session_id="c")._clarify_enabled() is False

    def broken() -> Any:
        raise RuntimeError("no config yet")

    runtime = SimpleNamespace(config=broken)
    assert AskUserTool(runtime, "lead", session_id="c")._clarify_enabled() is False


def test_the_doctrine_sends_a_question_to_the_card_and_the_manifest_names_the_tool() -> None:
    assert f"question card ({ASK_USER_TOOL_NAME})" in LEAD_DOCTRINE
    assert ASK_USER_TOOL_NAME in LEAD_ONLY_TOOLS
