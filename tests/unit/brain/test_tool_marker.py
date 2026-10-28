"""Imitated "[used tool …]" markers: never replayed, never shown as an answer.

Live 2026-10-28 (BC-250, chat session on local Qwen3 1.7B): after one real
search_web call, every later answer opened with "[used tool search_web]" typed
as text, no tool ran, and the rest was invented. Each such answer was replayed
as history and taught the next turn the same habit.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.runner_brain import brain_history_from_events
from dodaios.brain.manager import BrainManager
from dodaios.brain.public_fact_gate import public_fact_unfulfilled_answer
from dodaios.brain.streaming import StreamingAggregate
from dodaios.brain.tool_marker import WITHDRAWN_ANSWER_NOTE, strip_tool_markers
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.core.protocols import BrainDelta, BrainRequest

_FAKE_ANSWER = (
    "[used tool search_web]  \nAujourd'hui, le train en Espagne a été remplacé par "  # i18n-allow
    "des wagons de luxe."  # i18n-allow: live invented answer, 2026-10-28
)


def test_strip_removes_line_markers_and_names_the_tools() -> None:
    assert strip_tool_markers(_FAKE_ANSWER) == (
        "Aujourd'hui, le train en Espagne a été remplacé par des wagons de luxe.",  # i18n-allow
        ("search_web",),
    )
    assert strip_tool_markers("[used tool search_web: q] Texte")[0] == "Texte"  # i18n-allow
    assert strip_tool_markers("no marker here") == ("no marker here", ())
    # Only a marker that opens a line is the history format.
    assert strip_tool_markers("see [used tool x] inline")[1] == ()


def _session_events() -> list[dict]:
    """The live session's shape: one real search turn, then one imitation."""
    return [
        make_event("user_message", {"text": "date de sortie de Python 3.13 ?"}),  # i18n-allow
        make_event("turn_started", {"turn_id": "t1"}),
        make_event(
            "tool_call",
            {"turn_id": "t1", "call_id": "c1", "name": "search_web",
             "input": {"query": "Python 3.13.0 release date"}},
        ),
        make_event(
            "tool_result",
            {"turn_id": "t1", "call_id": "c1", "output": "Oct 7, 2024", "is_error": False},
        ),
        make_event("assistant_text", {"turn_id": "t1", "text": "Le 7 octobre 2024."}),  # i18n-allow
        make_event("turn_finished", {"turn_id": "t1", "status": "done"}),
        make_event("user_message", {"text": "et en espagne"}),  # i18n-allow: live
        make_event("turn_started", {"turn_id": "t2"}),
        make_event("assistant_text", {"turn_id": "t2", "text": _FAKE_ANSWER}),
        make_event("turn_finished", {"turn_id": "t2", "status": "done"}),
    ]


def test_replay_keeps_a_real_call_and_withdraws_an_imitated_answer() -> None:
    history = brain_history_from_events(_session_events())
    assert [m.role for m in history] == ["user", "assistant", "user", "assistant"]
    # The real call is replayed as the labelled tool record (#980).
    assert history[1].content.startswith("Tool record of this turn")
    assert "search_web" in history[1].content
    # The imitation's made-up content is withdrawn, not replayed for copying.
    assert history[3].content == WITHDRAWN_ANSWER_NOTE
    assert "wagons" not in history[3].content


# --- model output -----------------------------------------------------------


class _FakeBrain:
    name = "claude-api"
    context_window = 8192
    supports_tools = True
    supports_vision = False

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(content="ok")
        yield BrainDelta(finish_reason="stop")


class _ScriptedDispatcher:
    def __init__(self, text: str, executed: set[str]) -> None:
        self._text = text
        self._executed = executed

    async def dispatch(self, user_text, *, images=(), history=None, **_kwargs):
        agg = StreamingAggregate()
        agg.text = self._text
        agg.finish_reason = "stop"
        agg.executed_tool_names = set(self._executed)
        return agg


def _manager(reply: str, executed: set[str]) -> BrainManager:
    cfg = JarvisConfig()
    cfg.brain.primary = "claude-api"
    cfg.brain.reply_language = "fr"
    m = BrainManager(config=cfg, bus=EventBus(), tools={"search_web": object()})
    m._build_fallback_chain = lambda _l: [("claude-api", "model")]  # type: ignore[method-assign]
    m._get_brain = lambda _n, _mo: _FakeBrain()  # type: ignore[method-assign]
    m._build_dispatcher = (  # type: ignore[method-assign]
        lambda _b, *, tools_override=None: _ScriptedDispatcher(reply, executed)
    )
    return m


@pytest.mark.asyncio
async def test_a_claimed_search_that_never_ran_is_not_spoken() -> None:
    m = _manager(_FAKE_ANSWER, executed=set())
    out = await m.generate("raconte-moi ta journée", trace_id=uuid4(), use_history=False)  # i18n-allow
    assert "wagons" not in out
    assert out == public_fact_unfulfilled_answer("fr")


@pytest.mark.asyncio
async def test_a_real_search_keeps_its_answer_without_the_marker() -> None:
    m = _manager(_FAKE_ANSWER, executed={"search_web"})
    out = await m.generate("raconte-moi ta journée", trace_id=uuid4(), use_history=False)  # i18n-allow
    assert out.startswith("Aujourd'hui")
    assert "[used tool" not in out
