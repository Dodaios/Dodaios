"""The "needs you" list: aggregation over every runtime, the gate, the notifier."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.attention import (
    THROTTLE_S,
    AgentAttentionChanged,
    AttentionBoard,
    AttentionGate,
    attention_of,
    install,
    waiting_reasons,
)
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore

_QUESTION = {
    "question": "Which database should the project use?",
    "options": [{"label": "SQLite", "description": ""}, {"label": "Postgres", "description": ""}],
    "recommended": 0,
    "recommendation_reason": "",
}


def _ev(kind: str, **payload: Any) -> dict[str, Any]:
    return make_event(kind, payload)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ------------------------------------------------------------------- board


def test_board_opens_and_closes_every_card_kind() -> None:
    board = AttentionBoard()
    sid = "society:scout"
    board.observe(sid, _ev("approval_required", approval_id="a1", name="shell", summary="Run ls"))
    board.observe(sid, _ev("question_required", question_id="q1", questions=[_QUESTION]))
    board.observe(sid, _ev("credential_required", request_id="c1", label="GitHub token"))
    kinds = sorted(item.kind for item in board.items())
    assert kinds == ["approval", "credential", "question"]
    question = next(item for item in board.items() if item.kind == "question")
    assert question.summary == _QUESTION["question"]
    assert question.detail["options"] == ["SQLite", "Postgres"]
    assert question.detail["single"] is True

    board.observe(sid, _ev("approval_resolved", approval_id="a1", decision="allow"))
    board.observe(sid, _ev("question_resolved", question_id="q1", answers=[]))
    board.observe(sid, _ev("credential_resolved", request_id="c1", status="saved"))
    assert board.items() == []


def test_progress_moves_the_summary_to_the_next_question() -> None:
    board = AttentionBoard()
    second = {**_QUESTION, "question": "Where should it run?"}
    board.observe("s", _ev("question_required", question_id="q", questions=[_QUESTION, second]))
    board.observe(
        "s", _ev("question_progress", question_id="q", answers=[{"answer": "SQLite"}, None])
    )
    (item,) = board.items()
    assert item.summary == "Where should it run?"
    assert item.detail["step"] == 1 and item.detail["count"] == 2


def test_a_multi_pick_question_is_listed_but_not_offered_for_one_tap() -> None:
    board = AttentionBoard()
    multi = {**_QUESTION, "multi_select": True}
    board.observe("s", _ev("question_required", question_id="q", questions=[multi]))
    assert board.items()[0].detail["single"] is False


def test_a_new_turn_settles_end_of_turn_cards_and_a_finished_turn_its_own() -> None:
    board = AttentionBoard()
    board.observe(
        "s", _ev("question_required", question_id="d", questions=[_QUESTION], deferred=True)
    )
    board.observe("s", _ev("credential_required", request_id="c", label="Key"))
    board.observe("s", _ev("turn_started", turn_id="t2"))
    assert [item.kind for item in board.items()] == ["credential"]  # a secret field stays open

    board.observe("s", _ev("approval_required", approval_id="a", name="x", turn_id="t2"))
    board.observe("s", _ev("turn_finished", turn_id="t2", status="error"))
    assert [item.kind for item in board.items()] == ["credential"]


def test_done_only_for_a_turn_the_person_started_with_nothing_left_open() -> None:
    board = AttentionBoard()
    board.observe("s", _ev("turn_started", turn_id="t1"))
    assert [
        c.what for c in board.observe("s", _ev("turn_finished", turn_id="t1", status="done"))
    ] == []

    board.observe("s", _ev("user_message", text="hi", author="lead"))  # an agent wrote it
    board.observe("s", _ev("turn_started", turn_id="t2"))
    assert board.observe("s", _ev("turn_finished", turn_id="t2", status="done")) == []

    board.observe("s", _ev("user_message", text="hi"))
    board.observe("s", _ev("turn_started", turn_id="t3"))
    changes = board.observe("s", _ev("turn_finished", turn_id="t3", status="done"))
    assert [c.what for c in changes] == ["done"]


# -------------------------------------------------------------------- gate


def test_gate_throttles_per_agent_and_kind() -> None:
    clock = _Clock()
    gate = AttentionGate(clock=clock)
    assert gate.verdict(agent_id="a", transition="needs_input", session_id="society:a") is None
    assert (
        gate.verdict(agent_id="a", transition="needs_input", session_id="society:a") == "throttled"
    )
    assert gate.verdict(agent_id="a", transition="done", session_id="society:a") is None
    assert gate.verdict(agent_id="b", transition="needs_input", session_id="society:b") is None
    clock.now += THROTTLE_S + 0.1
    assert gate.verdict(agent_id="a", transition="needs_input", session_id="society:a") is None


def test_gate_is_quiet_while_the_person_looks_at_that_agent() -> None:
    clock = _Clock()
    gate = AttentionGate(clock=clock, focus_ttl_s=60)
    gate.report_focus(agent_id="a", app_focused=True)
    assert gate.verdict(agent_id="a", transition="needs_input", session_id="society:a") == "looking"
    assert gate.verdict(agent_id="b", transition="needs_input", session_id="society:b") is None
    gate.report_focus(agent_id="a", app_focused=False)  # window in the background
    assert gate.verdict(agent_id="a", transition="done", session_id="society:a") is None
    gate.report_focus(agent_id="c", app_focused=True)
    clock.now += 61  # a stale report says nothing any more
    assert gate.verdict(agent_id="c", transition="done", session_id="society:c") is None


def test_gate_holds_muted_agents_and_unattended_runs() -> None:
    gate = AttentionGate(clock=_Clock())
    gate.report_focus(muted=["quiet"])
    assert gate.verdict(agent_id="quiet", transition="done", session_id="society:quiet") == "muted"
    routine = "society:a:routine:task-1:run-1"
    assert gate.verdict(agent_id="a", transition="needs_input", session_id=routine) == "unattended"
    assert gate.verdict(agent_id="", transition="done", session_id="x") == "no_agent"


# ------------------------------------------------------------- service fold


@dataclass
class _Row:
    id: str
    agent_id: str
    capability: str
    summary: str
    created_ms: int
    expires_ms: int
    state: str = "pending"
    action: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.action = self.action or {}


class _Approvals:
    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows

    async def pending(self) -> list[_Row]:
        return list(self.rows)


class _Society:
    def __init__(self, rows: list[_Row] | None = None) -> None:
        self.approvals = _Approvals(rows or [])
        self._agents = {
            aid: SimpleNamespace(agent_id=aid, name=aid.capitalize(), tier="specialist")
            for aid in ("brain", "cli", "hermes", "openclaw", "scout")
        }

    def cached_agent(self, agent_id: str) -> Any:
        return self._agents.get(agent_id)


def _service() -> AgentChatService:
    return AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")


async def _settle(attention: Any) -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    while attention._tasks:  # noqa: SLF001 — wait for the scheduled publishes
        await asyncio.gather(*list(attention._tasks))  # noqa: SLF001
        await asyncio.sleep(0)  # let the done callbacks drop the finished tasks


async def test_aggregates_cards_from_every_runtime() -> None:
    svc = _service()
    seats = {
        "brain": ("openai", ""),
        "cli": ("claude-api", ""),
        "hermes": ("openrouter", "hermes"),
        "openclaw": ("openrouter", "openclaw"),
    }
    for agent_id, (provider, runtime) in seats.items():
        svc.store.create_session(
            provider=provider,
            model="m",
            effort="high",
            cwd=".",
            surface="society",
            session_id=f"society:{agent_id}",
            runtime=runtime,
        )
    lead = svc.store.create_session(
        provider="openai", model="m", effort="", cwd=".", surface="jarvis"
    )
    attention = install(svc, society=_Society)
    await svc._emit(
        "society:brain", _ev("approval_required", approval_id="a", name="shell", summary="Run")
    )
    await svc._emit("society:cli", _ev("question_required", question_id="q", questions=[_QUESTION]))
    await svc._emit("society:hermes", _ev("credential_required", request_id="c", label="Token"))
    await svc._emit(
        "society:openclaw",
        _ev("question_required", question_id="d", questions=[_QUESTION], deferred=True),
    )
    await svc._emit(
        lead.session_id, _ev("approval_required", approval_id="l", name="x", summary="Lead")
    )
    await _settle(attention)

    items = await attention.items()
    assert sorted((i.agent_id, i.kind) for i in items) == [
        ("brain", "approval"),
        ("cli", "question"),
        ("hermes", "credential"),
        ("jarvis", "approval"),
        ("openclaw", "question"),
    ]
    assert install(svc) is attention  # idempotent


async def test_society_queue_items_join_the_list_and_rank_below_live_cards() -> None:
    svc = _service()
    rows = [
        _Row(
            "p1",
            "scout",
            "core:config:rule",
            "Add a standing rule",
            10,
            99,
            action={"session_id": "society:scout"},
        ),
        _Row("u1", "brain", "plugin:gmail:send", "Send the digest", 20, 99, state="blocked"),
    ]
    attention = install(svc, society=lambda: _Society(rows))
    await svc._emit(
        "society:scout", _ev("approval_required", approval_id="a", name="x", summary="Live")
    )
    await _settle(attention)

    items = {i.ref_id: i for i in await attention.items()}
    assert items["p1"].kind == "proposal" and items["p1"].source == "queue"
    assert items["u1"].kind == "approval" and items["u1"].detail["parked"] is True
    reasons = await attention.waiting_reasons()
    assert reasons["scout"]["ref_id"] == "a"  # the live card outranks the proposal
    assert reasons["brain"] == {
        "kind": "approval",
        "summary": "Send the digest",
        "session_id": "society:brain",
        "ref_id": "u1",
    }
    assert await waiting_reasons(SimpleNamespace(agent_chat=svc)) == reasons
    assert await waiting_reasons(SimpleNamespace(agent_chat=None)) == {}


async def test_notifier_publishes_count_and_needs_input_but_never_speaks() -> None:
    svc = _service()
    published: list[Any] = []

    async def publish(event: Any) -> None:
        published.append(event)

    attention = install(svc, publish=publish, society=_Society)
    await svc._emit(
        "society:scout", _ev("approval_required", approval_id="a", name="x", summary="Run it")
    )
    await _settle(attention)
    assert all(isinstance(e, AgentAttentionChanged) for e in published)
    first = published[-1]
    assert (first.count, first.transition, first.agent_id, first.kind) == (
        1,
        "needs_input",
        "scout",
        "approval",
    )
    assert first.agent_name == "Scout" and first.summary == "Run it"

    # A second card within the throttle window updates the count only.
    await svc._emit("society:scout", _ev("credential_required", request_id="c", label="Key"))
    await _settle(attention)
    assert (published[-1].count, published[-1].transition) == (2, "")

    # Answering clears the badge.
    await svc._emit("society:scout", _ev("approval_resolved", approval_id="a", decision="deny"))
    await svc._emit("society:scout", _ev("credential_resolved", request_id="c", status="declined"))
    await _settle(attention)
    assert published[-1].count == 0
    assert attention_of(svc) is attention


async def test_notifier_is_silent_for_the_agent_on_screen_and_for_routines() -> None:
    svc = _service()
    published: list[Any] = []

    async def publish(event: Any) -> None:
        published.append(event)

    attention = install(svc, publish=publish, society=_Society)
    attention.gate.report_focus(agent_id="scout", app_focused=True)
    await svc._emit(
        "society:scout", _ev("approval_required", approval_id="a", name="x", summary="s")
    )
    await svc._emit(
        "society:brain:routine:t:r",
        _ev("approval_required", approval_id="b", name="x", summary="s"),
    )
    await _settle(attention)
    assert [e.transition for e in published] == ["", ""]
    assert published[-1].count == 2  # still counted


async def test_done_is_told_only_for_the_agents_own_chat() -> None:
    svc = _service()
    published: list[Any] = []

    async def publish(event: Any) -> None:
        published.append(event)

    attention = install(svc, publish=publish, society=_Society)
    attention.done_grace_s = 0
    for sid in ("society:scout", "society:scout:with:brain"):
        await svc._emit(sid, _ev("user_message", text="go"))
        await svc._emit(sid, _ev("turn_started", turn_id=f"t-{sid}"))
        await svc._emit(sid, _ev("turn_finished", turn_id=f"t-{sid}", status="done"))
    await _settle(attention)
    told = [(e.transition, e.session_id) for e in published if e.transition]
    assert told == [("done", "society:scout")]


async def test_a_turn_that_ends_by_asking_is_told_as_a_question_not_as_done() -> None:
    svc = _service()
    published: list[Any] = []

    async def publish(event: Any) -> None:
        published.append(event)

    attention = install(svc, publish=publish, society=_Society)
    attention.done_grace_s = 0.05
    sid = "society:scout"
    await svc._emit(sid, _ev("user_message", text="go"))
    await svc._emit(sid, _ev("turn_started", turn_id="t1"))
    await svc._emit(sid, _ev("turn_finished", turn_id="t1", status="done"))
    # A fence-only CLI's end-of-turn card lands right after the turn finished.
    await svc._emit(sid, _ev(
        "question_required", turn_id="t1", question_id="q-end", questions=[_QUESTION], deferred=True,
    ))
    await _settle(attention)
    told = [e.transition for e in published if e.transition]
    assert told == ["needs_input"]


def test_a_series_is_never_offered_for_one_tap() -> None:
    board = AttentionBoard()
    board.observe("s", _ev("question_required", question_id="q", questions=[_QUESTION, _QUESTION]))
    assert board.items()[0].detail["single"] is False
    lone = AttentionBoard()
    lone.observe("s", _ev("question_required", question_id="q", questions=[_QUESTION]))
    assert lone.items()[0].detail["single"] is True


async def test_open_cards_are_rebuilt_from_the_log_after_a_restart() -> None:
    store = AgentChatStore(":memory:")
    store.create_session(
        provider="kimi", model="m", effort="", cwd=".", surface="society", session_id="society:cli"
    )
    for event in (
        _ev("turn_started", turn_id="t1"),
        _ev("question_required", question_id="old", questions=[_QUESTION], deferred=True),
        _ev("turn_finished", turn_id="t1", status="done"),
        _ev("turn_started", turn_id="t2"),
        _ev("question_required", question_id="new", questions=[_QUESTION], deferred=True),
        _ev("turn_finished", turn_id="t2", status="done"),
    ):
        store.append_event("society:cli", event)
    svc = AgentChatService(store, assistant_name=lambda: "Testo")
    attention = install(svc, society=_Society)
    items = await attention.items()
    assert [(i.agent_id, i.ref_id, i.deferred) for i in items] == [("cli", "new", True)]


@pytest.fixture
def client() -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web.attention_routes import router

    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = _service()
    app.state.society = _Society()
    return TestClient(app)


def test_routes_list_items_and_take_the_focus_report(client: Any) -> None:
    svc = client.app.state.agent_chat
    # The card opened before the list existed: the first read replays the log.
    svc.store.create_session(
        provider="codex",
        model="m",
        effort="",
        cwd=".",
        surface="society",
        session_id="society:scout",
    )
    asyncio.run(
        svc._emit("society:scout", _ev("question_required", question_id="q", questions=[_QUESTION]))
    )
    body = client.get("/api/agent-chat/attention").json()
    assert body["count"] == 1
    (item,) = body["items"]
    assert item["agent_id"] == "scout" and item["kind"] == "question"
    assert "questions" not in item["detail"] and item["detail"]["options"] == ["SQLite", "Postgres"]

    ok = client.post(
        "/api/agent-chat/attention/focus",
        json={"agent_id": "scout", "app_focused": True, "muted": ["brain"]},
    )
    assert ok.json() == {"ok": True}
    gate = attention_of(svc).gate
    assert gate.looking_at("scout") and "brain" in gate.focus.muted


class _UnopenedApprovals:
    async def pending(self) -> list[_Row]:
        raise RuntimeError("SocietyStore: call open() before use")


class _BuiltButNotStartedSociety(_Society):
    """The runtime exists (built lazily) but ensure_started() has not run yet."""

    started = False

    def __init__(self) -> None:
        super().__init__()
        self.approvals = _UnopenedApprovals()


async def test_a_society_that_is_not_started_yet_adds_nothing_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    svc = _service()
    attention = install(svc, society=_BuiltButNotStartedSociety)
    await svc._emit(
        "society:scout", _ev("approval_required", approval_id="a", name="x", summary="Live")
    )
    await _settle(attention)

    with caplog.at_level("WARNING", logger="dodaios.agent_chat.attention"):
        items = await attention.items()

    assert [item.ref_id for item in items] == ["a"]
    assert "society items unavailable" not in caplog.text
