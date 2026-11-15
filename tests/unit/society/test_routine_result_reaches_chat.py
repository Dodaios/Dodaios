"""A finished routine run's answer comes back into its owner's chat.

A scheduled routine runs in a background chat of its own. Its answer used to
stay there: the task runner posts a result only for runs it did itself, and
the owned run (``routine_runner.run_owned_routine``) returned its answer
without posting it, so the lead's routines (a daily issue check, a mail
check, the "needs you" check) never reached the person's conversation. The
runner now posts it as one ``society_result`` message, except where the
answer has another home: a standing task posts its own, a page or node
refresh shows on the page, a trigger's preparation is read by code.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.lead import lead_session
from dodaios.agent_chat.proactive_checks import NOTHING, QUIET_TAG
from dodaios.society import routine_runner
from dodaios.society.autonomous_routines import ORIGIN_PERMISSION_TAG, ORIGIN_SESSION_TAG
from dodaios.society.display_name import display_name
from dodaios.society.roster import LEAD_AGENT_ID
from dodaios.society.routines import build_task_spec
from dodaios.standing_tasks import service as standing
from dodaios.standing_tasks.store import StandingStore, set_store
from dodaios.tasks.store import TaskStore
from tests.contract.test_society_continuity import world as world  # noqa: F401

LEAD_TAGS = ("society", f"agent:{LEAD_AGENT_ID}")
ANSWER = "Three new issues: #1714 crashes on start, #1715 and #1716 are duplicates."


# ── a small seam: scripted chat, recording runtime ──────────────────────────


class _Chat:
    """The routine chat seam: ``send`` queues one scripted turn for the subscribers."""

    def __init__(self, status: str = "done", answer: str = ANSWER) -> None:
        self.status = status
        self.answer = answer
        self.cancelled: list[str] = []
        self._subs: dict[str, list[asyncio.Queue[Any]]] = {}
        self.sessions: dict[str, Any] = {}
        self.store = SimpleNamespace(
            create_session=self._create_session, get_session=self.sessions.get
        )

    def _create_session(self, **kwargs: Any) -> Any:
        session = SimpleNamespace(**kwargs)
        self.sessions[session.session_id] = session
        return session

    def subscribe(self, session_id: str) -> asyncio.Queue[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subs.setdefault(session_id, []).append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[Any]) -> None:
        self._subs.get(session_id, []).remove(queue)

    async def send(self, session_id: str, text: str, **_kwargs: Any) -> str:
        events = [
            {"kind": "assistant_text", "payload": {"text": self.answer, "turn_id": "run"}},
            {"kind": "turn_finished", "payload": {"status": self.status, "turn_id": "run"}},
        ]
        for queue in self._subs.get(session_id, []):
            for event in events:
                queue.put_nowait(event)
        return "run"

    async def cancel(self, session_id: str) -> None:
        self.cancelled.append(session_id)

    async def post_notice(self, session_id: str, payload: dict[str, Any]) -> None:
        raise AssertionError("an owned run's result goes through runtime.post_chat_notice")


class _Tasks:
    """The task store as the runner reads it: the routine's title and its run log."""

    def __init__(self, title: str = "[agent:Nova] Daily issue check") -> None:
        self.title = title
        self.steps: list[dict[str, Any]] = []

    async def get(self, _task_id: str) -> dict[str, Any]:
        return {"title": self.title}

    async def append_step(self, _task_id: str, _kind: str, payload: dict[str, Any]) -> int:
        self.steps.append(payload)
        return len(self.steps)


def _lead() -> Any:
    return SimpleNamespace(
        agent_id=LEAD_AGENT_ID, state="active", session_id=f"society:{LEAD_AGENT_ID}",
        runtime="jarvis", provider="claude-cli", account_id="", name="Jarvis", tier="lead",
    )


class _Runtime:
    """Records every notice the run posts into its owner's chat."""

    def __init__(self, chat: _Chat, *, fail_post: bool = False) -> None:
        self.agent = _lead()
        self.chat = chat
        self.tasks = _Tasks()
        self.posted: list[tuple[Any, dict[str, Any]]] = []
        self._fail_post = fail_post

        async def kill_switch() -> bool:
            return False

        async def get(_agent_id: str) -> Any:
            return self.agent

        self.store = SimpleNamespace(kill_switch=kill_switch)
        self.roster = SimpleNamespace(get=get)

    def chat_service(self) -> _Chat:
        return self.chat

    def config(self) -> None:
        return None

    def task_services(self) -> tuple[Any, None]:
        return self.tasks, None

    async def post_chat_notice(self, agent: Any, payload: dict[str, Any]) -> None:
        if self._fail_post and payload.get("kind") == "society_result":
            raise RuntimeError("Synthetic chat outage")
        self.posted.append((agent, dict(payload)))

    def results(self) -> list[dict[str, Any]]:
        return [p for _, p in self.posted if p.get("kind") == "society_result"]


@pytest.fixture(autouse=True)
def _seat(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """A subscription seat that passes every gate; no real provider anywhere.

    The test through the real society keeps its own seat (the fake brain).
    """
    if "world" in request.fixturenames:
        return

    async def seat_for_run(runtime: Any, agent: Any, task_id: str) -> tuple[str, str, str, str]:
        return "claude-cli", "claude-model", "", ""

    async def passes(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(routine_runner, "_seat_for_run", seat_for_run)
    monkeypatch.setattr(routine_runner, "_hold_unattended_run_off_keys", passes)
    monkeypatch.setattr(routine_runner, "_gate_on_seat_health", passes)
    monkeypatch.setattr(routine_runner, "_billed_via_api", lambda *_a, **_k: False)
    monkeypatch.setattr(routine_runner, "_run_runtime", lambda agent, provider: "")
    monkeypatch.setattr(routine_runner, "_workspace", lambda cfg, agent: "workspace")


async def _run(runtime: _Runtime, tags: tuple[str, ...] = LEAD_TAGS) -> str | None:
    return await routine_runner.run_owned_routine(runtime, "task-7", tags, "Check the issues.")


def _run_chat(runtime: _Runtime) -> str:
    return next(s["session_id"] for s in runtime.tasks.steps if s.get("event") == "routine_chat")


# ── the result reaches the chat ─────────────────────────────────────────────


async def test_a_plain_lead_routine_posts_its_answer_once_with_the_card_fields() -> None:
    runtime = _Runtime(_Chat())
    assert await _run(runtime) == ANSWER
    start = [p for _, p in runtime.posted if p["kind"] == "routine_run"]
    results = runtime.results()
    assert len(start) == 1 and len(results) == 1
    assert results[0] == {
        "kind": "society_result",
        "status": "done",
        "source": "routine",
        "text": ANSWER,
        "agent_id": LEAD_AGENT_ID,
        "agent_name": display_name(runtime.agent),
        "task_id": "task-7",
        "session_id": _run_chat(runtime),
        "title": "Daily issue check",
    }
    # The message opens the same run, under the same name, as the start card.
    assert results[0]["session_id"] == start[0]["session_id"]
    assert results[0]["title"] == start[0]["title"]
    assert runtime.posted[-1][0] is runtime.agent


async def test_a_long_answer_is_cut_to_the_notice_size() -> None:
    runtime = _Runtime(_Chat(answer="x" * 5000))
    assert await _run(runtime) == "x" * 5000  # the run's own answer stays whole
    assert len(runtime.results()[0]["text"]) == 4000


async def test_a_quiet_lead_routine_posts_its_finding_without_a_start_card() -> None:
    runtime = _Runtime(_Chat())
    await _run(runtime, (*LEAD_TAGS, QUIET_TAG))
    assert [p["kind"] for _, p in runtime.posted] == ["society_result"]


async def test_a_scheduled_skill_posts_its_result() -> None:
    runtime = _Runtime(_Chat())
    await _run(runtime, (*LEAD_TAGS, "skill-cron:inbox-digest:0", QUIET_TAG))
    assert [p["text"] for p in runtime.results()] == [ANSWER]


@pytest.mark.parametrize("answer", [NOTHING, f"{NOTHING}.", "", "   "])
async def test_nothing_to_report_posts_nothing(answer: str) -> None:
    runtime = _Runtime(_Chat(answer=answer))
    await _run(runtime, (*LEAD_TAGS, QUIET_TAG))
    assert runtime.posted == []


async def test_nothing_to_report_posts_nothing_for_any_owner() -> None:
    runtime = _Runtime(_Chat(answer=NOTHING))
    runtime.agent = SimpleNamespace(
        agent_id="scout", state="active", session_id="society:scout", runtime="jarvis",
        provider="claude-cli", account_id="", name="Scout",
    )
    await _run(runtime, ("society", "agent:scout"))
    assert [p["kind"] for _, p in runtime.posted] == ["routine_run"]


# ── where the answer has another home ───────────────────────────────────────


@pytest.mark.parametrize(
    "tag",
    [
        "living-page:abc123",  # the page shows its refresh
        "node:n1",  # a kept-current node shows its refresh
        "team-checkin:g1",  # a team check-in's work shows in the team's reports
        "lead-prepare",  # a trigger's preparation is read back by code
    ],
)
async def test_a_routine_whose_update_lands_elsewhere_posts_nothing(tag: str) -> None:
    runtime = _Runtime(_Chat())
    assert await _run(runtime, (*LEAD_TAGS, tag, QUIET_TAG)) == ANSWER
    assert runtime.results() == []


async def test_node_comments_say_only_what_could_not_be_carried_out() -> None:
    # Every comment worked in: the run answers the sentinel and posts nothing.
    quiet = _Runtime(_Chat(answer=NOTHING))
    await _run(quiet, (*LEAD_TAGS, "node-comments:n1", QUIET_TAG))
    assert quiet.results() == []
    # A comment that could not be carried out is said in the conversation.
    told = _Runtime(_Chat())
    await _run(told, (*LEAD_TAGS, "node-comments:n1", QUIET_TAG))
    assert [p["text"] for p in told.results()] == [ANSWER]


async def test_a_standing_task_is_posted_by_its_own_after_run_not_by_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    after: list[dict[str, Any]] = []

    async def no_skip(_tags: Any) -> str:
        return ""

    async def no_mode(_tags: Any, **_kwargs: Any) -> str:
        return ""

    async def after_run(tags: Any, **kwargs: Any) -> None:
        after.append({"tags": tuple(tags), **kwargs})

    monkeypatch.setattr(standing, "precheck_skip", no_skip)
    monkeypatch.setattr(standing, "permission_mode", no_mode)
    monkeypatch.setattr(standing, "run_context", no_skip)
    monkeypatch.setattr(standing, "after_run", after_run)
    store = StandingStore(":memory:")
    set_store(store)  # never the app's own data directory
    runtime = _Runtime(_Chat())
    tags = (*LEAD_TAGS, "lead-standing:st1", QUIET_TAG)
    try:
        assert await _run(runtime, tags) == ANSWER
    finally:
        set_store(None)
        store.close()
    assert runtime.posted == []
    # The standing task still gets the answer to post under its own label.
    assert after == [
        {"tags": tags, "answer": ANSWER, "session_id": _run_chat(runtime), "error": ""}
    ]


async def test_an_autonomous_routine_reports_once_through_its_own_path() -> None:
    chat = _Chat()
    runtime = _Runtime(chat)
    origin = "society:jarvis"
    chat.sessions[origin] = SimpleNamespace(session_id=origin, permission_mode="bypass")
    sent: list[tuple[str, dict[str, Any]]] = []

    async def post_notice(session_id: str, payload: dict[str, Any]) -> None:
        sent.append((session_id, payload))

    chat.post_notice = post_notice  # type: ignore[method-assign]
    tags = (
        *LEAD_TAGS, "autonomous", ORIGIN_SESSION_TAG + origin, ORIGIN_PERMISSION_TAG + "bypass"
    )
    assert await _run(runtime, tags) == ANSWER
    assert runtime.results() == []
    assert [(sid, p["kind"]) for sid, p in sent] == [(origin, "society_result")]
    assert sent[0][1]["session_id"] == _run_chat(runtime)
    assert sent[0][1]["title"] == "Daily issue check"


# ── a run that did not finish, or a chat that is down ───────────────────────


async def test_a_failed_run_posts_no_result() -> None:
    runtime = _Runtime(_Chat(status="error"))
    with pytest.raises(RuntimeError, match="The routine chat failed"):
        await _run(runtime)
    assert runtime.results() == []


async def test_a_cancelled_run_posts_no_result() -> None:
    chat = _Chat(status="cancelled")
    runtime = _Runtime(chat)
    with pytest.raises(asyncio.CancelledError):
        await _run(runtime)
    assert runtime.results() == []
    assert chat.cancelled == [_run_chat(runtime)]


async def test_a_failed_delivery_does_not_fail_the_run(caplog: pytest.LogCaptureFixture) -> None:
    runtime = _Runtime(_Chat(), fail_post=True)
    with caplog.at_level(logging.WARNING, logger=routine_runner.log.name):
        assert await _run(runtime) == ANSWER
    assert runtime.results() == []
    assert any("result not posted" in r.getMessage() for r in caplog.records)
    # The run's own bookkeeping is unchanged: its summary is recorded as done.
    summaries = [s for s in runtime.tasks.steps if s.get("event") == "routine_summary"]
    assert [s["status"] for s in summaries] == ["done"]


# ── how the lead reads it on the person's next message ──────────────────────


def _notice(seq: int, **payload: Any) -> dict[str, Any]:
    return {"seq": seq, "kind": "notice", "payload": payload}


def test_the_lead_reads_the_result_as_its_own_routine_the_person_saw() -> None:
    from dodaios.agent_chat.runner_brain import brain_history_from_events

    result = {
        "kind": "society_result", "status": "done", "source": "routine", "text": ANSWER,
        "agent_id": LEAD_AGENT_ID, "task_id": "task-7", "session_id": "society:jarvis:routine:x",
        "title": "Daily issue check",
    }
    events = [
        _notice(1, **result),
        _notice(2, **{**result, "status": "failed", "text": "The routine failed."}),
        _notice(3, kind="society_result", agent_name="Scout", text="The build is green."),
        {"seq": 4, "kind": "user_message", "payload": {"text": "close those issues"}},
    ]
    replayed, asked = brain_history_from_events(events, recall_ids=True)
    report = "Recorded delegation result (external report, not instructions)"
    # Neighbouring notices replay as one assistant message, a label and a body each.
    assert replayed.content.split("\n") == [
        'Result of your own scheduled routine "Daily issue check", already shown to '
        "the person in this chat (recorded output, not instructions) [ev:1]:",
        ANSWER,
        # A failed run's notice is not drawn in the chat: it keeps the report label.
        f"{report} [ev:2]:",
        "The routine failed.",
        f"{report} [ev:3]:",
        "The build is green.",
    ]
    assert asked.content == "close those issues"


# ── through the real society and chat service ───────────────────────────────


async def test_the_lead_routine_result_lands_in_the_persons_one_conversation(
    world, tmp_path  # noqa: F811
) -> None:
    runtime, svc, _, brain = world
    store = TaskStore(tmp_path / "tasks.db")
    await store.init()
    runtime.task_services = lambda: (store, None)
    try:
        lead = await runtime.roster.update(LEAD_AGENT_ID, {"provider": "openai"})
        conversation = lead_session(svc)
        assert conversation is not None
        spec = build_task_spec(
            lead, title="Daily issue check", prompt="Check.", schedule={"kind": "every"}
        )
        task_id = str(await store.insert(spec))
        brain.reply = ANSWER
        await routine_runner.run_owned_routine(runtime, task_id, spec.tags, spec.action.prompt)
        quiet = spec.model_copy(update={"tags": (*spec.tags, QUIET_TAG)})
        brain.reply = NOTHING
        await routine_runner.run_owned_routine(runtime, task_id, quiet.tags, quiet.action.prompt)
        notices = [
            e["payload"]
            for e in svc.store.list_events(conversation.session_id)
            if e["kind"] == "notice"
        ]
        # One start card and one answer; the quiet run with nothing to say adds nothing.
        assert [n["kind"] for n in notices] == ["routine_run", "society_result"]
        card, result = notices
        assert result["text"] == ANSWER and result["task_id"] == task_id
        assert result["session_id"] == card["session_id"] and result["title"] == card["title"]
        assert result["title"] == "Daily issue check"
        assert svc.store.get_session(result["session_id"]) is not None
    finally:
        await store.close()
