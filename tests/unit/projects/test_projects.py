"""Projects: durable plans, progress from evidence only, one re-plan, quiet reviews, gated close."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.brain.project_tool import ProjectTool
from dodaios.core.protocols import ExecutionContext
from dodaios.projects import reviewer
from dodaios.projects.engine import EvaluatorUnavailable, ProjectEngine, ProjectError, set_engine
from dodaios.projects.metrics import project_metrics
from dodaios.projects.models import DAY_MS, validate_plan
from dodaios.projects.store import ProjectStore

NOW = 1_800_000_000_000


class Clock:
    def __init__(self, now: int = NOW) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def days(self, n: float) -> None:
        self.now += int(n * DAY_MS)


class Verdict(SimpleNamespace):
    pass


def _evaluator(status: str = "complete", reason: str = "criteria met"):
    calls: list[list[dict[str, Any]]] = []

    async def judge(project, events, background):
        calls.append(events)
        return Verdict(status=status, reason=reason)

    judge.calls = calls  # type: ignore[attr-defined]
    return judge


def _engine(store: ProjectStore, clock: Clock, **kw: Any) -> ProjectEngine:
    return ProjectEngine(store, clock=clock, **kw)


def _job(ledger, job_id: str, state: str = "running", **kw: Any) -> str:
    ledger.create("mission", job_id=job_id, title=job_id, state="running")
    if state != "running":
        ledger.update(job_id, state=state, **kw)
    return job_id


PLAN = [
    {"id": "a", "title": "Research the options"},
    {"id": "b", "title": "Build the prototype", "depends_on": ["a"], "owner": "agent:coder"},
    {"id": "c", "title": "Owner signs off", "depends_on": ["b"], "evidence": "owner"},
]


def _create(engine: ProjectEngine, **kw: Any):
    return engine.create(
        title="Prototype",
        goal="Ship a prototype",
        criteria=["It runs"],
        subgoals=kw.pop("subgoals", PLAN),
        owner_session="lead-1",
        **kw,
    )


# ------------------------------------------------------------------ plan validation


def test_plan_rejects_cycles_unknown_dependencies_and_bad_owners(store) -> None:
    engine = _engine(store, Clock())
    with pytest.raises(ProjectError, match="cycle"):
        _create(
            engine,
            subgoals=[
                {"id": "a", "title": "A", "depends_on": ["b"]},
                {"id": "b", "title": "B", "depends_on": ["a"]},
            ],
        )
    with pytest.raises(ProjectError, match="unknown"):
        _create(engine, subgoals=[{"id": "a", "title": "A", "depends_on": ["zz"]}])
    with pytest.raises(ProjectError, match="owner"):
        _create(engine, subgoals=[{"id": "a", "title": "A", "owner": "somebody"}])
    assert validate_plan([]) == ""


# ------------------------------------------------------------------ persistence


async def test_a_plan_survives_a_restart(tmp_path) -> None:
    path = tmp_path / "projects.db"
    first = ProjectStore(path)
    project = _create(_engine(first, Clock()))
    first.close()  # the app restarts

    second = ProjectStore(path)
    engine = _engine(second, Clock())
    loaded = second.get(project.id)
    assert loaded is not None
    assert [s.id for s in loaded.subgoals] == ["a", "b", "c"]
    assert loaded.criteria == ["It runs"] and loaded.status == "active"
    view = await engine.status(project.id)
    assert [s["id"] for s in view["subgoals"] if s.get("ready")] == ["a"]
    second.close()


# ------------------------------------------------------------------ evidence only


async def test_progress_comes_from_job_evidence_never_from_claims(store, ledger) -> None:
    engine = _engine(store, Clock())
    project = _create(engine)
    with pytest.raises(ProjectError, match="not in the jobs ledger"):
        await engine.link_job(project.id, "a", "job_nope")
    _job(ledger, "job_a")
    await engine.link_job(project.id, "a", "job_a")
    await engine.note(project.id, "a", "I am sure this is finished, mark it done")
    view = await engine.status(project.id)
    assert view["subgoals"][0]["state"] == "running"  # a note is not evidence
    with pytest.raises(ProjectError, match="waits for"):
        await engine.link_job(project.id, "b", "job_a")

    ledger.update("job_a", state="done", summary="options written", result_ref="mission:m1")
    view = await engine.status(project.id)
    first = view["subgoals"][0]
    assert first["state"] == "done" and "options written" in first["proof"]
    assert view["progress"] == "1 of 3 sub-goals done"
    assert [s["id"] for s in view["subgoals"] if s.get("ready")] == ["b"]


async def test_verified_evidence_needs_verify_delegate_to_agree(store, ledger) -> None:
    verdicts = {"value": ("unverified", "the file is missing")}

    async def verifier(job_id: str):
        return verdicts["value"]

    engine = _engine(store, Clock(), verifier=verifier)
    project = _create(engine, subgoals=[{"id": "a", "title": "Make it", "evidence": "verified"}])
    _job(ledger, "job_a", "done", summary="done")
    await engine.link_job(project.id, "a", "job_a")
    view = await engine.status(project.id)
    assert view["subgoals"][0]["state"] == "blocked"
    assert "could not confirm" in view["subgoals"][0]["note"]
    verdicts["value"] = ("verified", "file ok")
    # blocked sub-goals read the evidence again on the next status
    assert (await engine.status(project.id))["subgoals"][0]["state"] == "done"


async def test_an_owner_sub_goal_is_done_only_by_the_owners_confirmation(store, ledger) -> None:
    engine = _engine(store, Clock())
    project = _create(engine)
    with pytest.raises(ProjectError, match="by the owner"):
        await engine.link_job(project.id, "c", "job_x")
    with pytest.raises(ProjectError, match="evidence 'owner'"):
        await engine.confirm(project.id, "a")
    done = await engine.confirm(project.id, "c")
    assert done.subgoal("c").state == "done"


# ------------------------------------------------------------------ re-plan once


async def test_a_failed_sub_goal_is_re_planned_once_then_the_owner_decides(store, ledger) -> None:
    clock = Clock()
    engine = _engine(store, clock)
    project = _create(engine)
    _job(ledger, "job_1")
    await engine.link_job(project.id, "a", "job_1")
    ledger.update("job_1", state="failed", error="agent crashed")

    first = await engine.review(project.id)
    sub = store.get(project.id).subgoal("a")
    assert (sub.state, sub.replans, sub.job_id) == ("pending", 1, "")
    assert "agent crashed" in sub.note and sub.history == ["job_1"]
    assert "re-planned once" in (first.line or "")
    assert store.get(project.id).status == "active"

    _job(ledger, "job_2", "failed", error="agent crashed again")
    await engine.link_job(project.id, "a", "job_2")
    second = await engine.review(project.id)
    after = store.get(project.id)
    assert after.subgoal("a").replans == 1 and after.subgoal("a").state == "failed"
    assert after.status == "blocked" and after.decision_kind == "stuck"
    assert "needs your decision" in (second.line or "")
    assert "Resume it, rescope" in second.line


# ------------------------------------------------------------------ quiet reviews


async def test_a_review_is_quiet_unless_something_changed_or_the_owner_must_decide(
    store, ledger
) -> None:
    clock = Clock()
    engine = _engine(store, clock)
    project = _create(engine)
    sent: list[dict[str, Any]] = []

    async def post(payload):
        sent.append(payload)
        return True

    async def awake():
        return False

    clock.days(1)
    assert await reviewer.review_due(engine, post, awake) == []  # nothing moved: silence
    _job(ledger, "job_a")
    await engine.link_job(project.id, "a", "job_a")
    clock.days(1)
    assert await reviewer.review_due(engine, post, awake) == []  # running is not a change

    ledger.update("job_a", state="done", summary="options written")
    clock.days(1)
    lines = await reviewer.review_due(engine, post, awake)
    assert len(lines) == 1 and "1 of 3 sub-goals done" in lines[0]
    assert sent[0]["kind"] == "project" and sent[0]["text"] == lines[0]
    assert "next: Build the prototype" in lines[0]

    clock.days(1)
    assert await reviewer.review_due(engine, post, awake) == []  # same state, not repeated
    assert len(sent) == 1


async def test_quiet_hours_defer_the_line_instead_of_dropping_it(store, ledger) -> None:
    clock = Clock()
    engine = _engine(store, clock)
    project = _create(engine)
    _job(ledger, "job_a", "done", summary="ok")
    await engine.link_job(project.id, "a", "job_a")
    sent: list[dict[str, Any]] = []
    asleep = {"on": True}

    async def post(payload):
        sent.append(payload)
        return True

    async def quiet():
        return asleep["on"]

    clock.days(1)
    assert await reviewer.review_due(engine, post, quiet) == [] and sent == []
    asleep["on"] = False
    clock.days(1)
    assert len(await reviewer.review_due(engine, post, quiet)) == 1


# ------------------------------------------------------------------ the close gate


async def _finish_all(engine: ProjectEngine, ledger, project_id: str) -> None:
    _job(ledger, "job_a", "done", summary="researched")
    await engine.link_job(project_id, "a", "job_a")
    await engine.status(project_id)
    _job(ledger, "job_b", "done", summary="prototype built")
    await engine.link_job(project_id, "b", "job_b")
    await engine.status(project_id)
    await engine.confirm(project_id, "c")


async def test_close_is_refused_while_sub_goals_are_open(store, ledger) -> None:
    judge = _evaluator()
    engine = _engine(store, Clock(), evaluator=judge)
    project = _create(engine)
    result = await engine.close(project.id)
    assert not result.closed and len(result.missing) == 3
    assert judge.calls == []  # the evaluator is not even asked
    assert store.get(project.id).status == "active"


async def test_close_needs_the_evaluators_verdict_on_the_evidence(store, ledger) -> None:
    clock = Clock()
    judge = _evaluator("continue", "no sign that it runs")
    engine = _engine(store, clock, evaluator=judge)
    project = _create(engine)
    await _finish_all(engine, ledger, project.id)

    refused = await engine.close(project.id)
    assert not refused.closed and "no sign that it runs" in refused.reason
    assert store.get(project.id).status == "active"
    evidence = [json.loads(e["payload"]["output"])["evidence"] for e in judge.calls[0]]
    assert any("researched" in text for text in evidence) and len(judge.calls[0]) == 3

    judge_ok = _evaluator("complete", "it runs, shown by the build job")
    engine._evaluator = judge_ok
    clock.days(2)
    done = await engine.close(project.id)
    assert done.closed and store.get(project.id).status == "complete"
    assert store.get(project.id).closed_ms == clock.now


async def test_close_without_a_judge_never_closes(store, ledger) -> None:
    async def nobody(project, events, background):
        raise EvaluatorUnavailable("No subscription or local seat is free for the check.")

    engine = _engine(store, Clock(), evaluator=nobody)
    project = _create(engine)
    await _finish_all(engine, ledger, project.id)
    result = await engine.close(project.id)
    assert not result.closed and "could not be judged" in result.reason

    async def broken(project, events, background):
        raise RuntimeError("provider down")

    engine._evaluator = broken
    assert not (await engine.close(project.id)).closed


async def test_the_review_checks_criteria_once_and_closes_on_a_complete_verdict(
    store, ledger
) -> None:
    clock = Clock()
    judge = _evaluator("complete", "criteria met")
    engine = _engine(store, clock, evaluator=judge)
    project = _create(engine)
    await _finish_all(engine, ledger, project.id)
    clock.days(1)
    result = await engine.review(project.id)
    assert result.closed and "is complete: criteria met" in result.line
    assert len(judge.calls) == 1


async def test_a_not_met_verdict_is_reported_once_and_not_judged_again(store, ledger) -> None:
    clock = Clock()
    judge = _evaluator("continue", "tests were never run")
    engine = _engine(store, clock, evaluator=judge)
    project = _create(engine)
    await _finish_all(engine, ledger, project.id)
    clock.days(1)
    first = await engine.review(project.id)
    assert "not shown as met" in first.line
    await engine.mark_reported(project.id, first.report_fp)
    clock.days(1)
    second = await engine.review(project.id)
    assert second.line is None and len(judge.calls) == 1


async def test_abandoning_is_an_owner_decision_and_not_a_completion(store) -> None:
    engine = _engine(store, Clock())
    project = _create(engine)
    result = await engine.close(project.id, "abandon", reason="plans changed")
    assert result.closed and result.status == "abandoned"
    assert store.get(project.id).close_note == "plans changed"
    with pytest.raises(ProjectError, match="already"):
        await engine.plan(project.id, subgoals=[{"id": "z", "title": "Z"}])


# ------------------------------------------------------------------ metrics


async def test_metrics_count_multi_session_projects_and_median_duration(store, ledger) -> None:
    clock = Clock()
    judge = _evaluator()
    engine = _engine(store, clock, evaluator=judge)
    single = _create(engine)  # touched on one day, one session: not multi-session
    await engine.close(single.id, "abandon")
    long_ = _create(engine)
    clock.days(2)
    await _finish_all(engine, ledger, long_.id)
    await engine.close(long_.id)
    gone = _create(engine)
    clock.days(1)
    await engine.plan(gone.id, subgoals=[{"id": "d", "title": "D"}], session="other")
    clock.days(10)  # nothing moves for longer than the stall window

    metrics = project_metrics(store, now=clock.now)
    assert metrics["multi_session_projects"] == 2
    assert (metrics["completed"], metrics["stalled"], metrics["abandoned"]) == (1, 1, 0)
    assert metrics["completion_rate"] == 0.5
    assert metrics["median_days_to_complete"] == pytest.approx(2.0)


# ------------------------------------------------------------------ the lead's tool


def _ctx(session: str = "lead-1") -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{session}", "tool_origin": "agent-chat"},
        memory_read=None,
    )


async def test_the_project_tool_creates_links_and_reports(store, ledger) -> None:
    set_engine(_engine(store, Clock(), evaluator=_evaluator()))
    try:
        tool = ProjectTool()
        assert tool.risk_tier_for_args({"action": "status"}) == "safe"
        assert tool.risk_tier_for_args({"action": "close", "outcome": "abandon"}) == "ask"
        assert tool.risk_tier_for_args({"action": "plan"}) == "monitor"
        made = await tool.execute({"action": "create", "goal": "Ship it", "subgoals": PLAN}, _ctx())
        assert made.success and made.output["hint"].startswith("No success criteria")
        pid = made.output["id"]
        assert store.get(pid).owner_session == "lead-1"
        _job(ledger, "job_a")
        linked = await tool.execute(
            {"action": "link", "project_id": pid, "subgoal_id": "a", "job_id": "job_a"}, _ctx()
        )
        assert linked.success and linked.output["subgoals"][0]["state"] == "running"
        listing = await tool.execute({"action": "list"}, _ctx())
        assert listing.output["projects"][0]["id"] == pid
        refused = await tool.execute({"action": "close", "project_id": pid}, _ctx())
        assert refused.success and refused.output["closed"] is False
        missing = await tool.execute({"action": "status", "project_id": "prj_none"}, _ctx())
        assert not missing.success and "No such project" in missing.error
    finally:
        set_engine(None)
