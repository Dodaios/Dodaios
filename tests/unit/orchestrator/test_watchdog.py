"""The watchdog: code checks, dedupe, repair-once, the judge gate, downtime report."""

from __future__ import annotations

import json
from typing import Any

import pytest

from dodaios.orchestrator.watchdog import checks, judge, supervisor
from dodaios.orchestrator.watchdog.checks import (
    ClaimView,
    Finding,
    JobView,
    Limits,
    RoutineView,
    SeatView,
    Snapshot,
    TurnView,
)
from dodaios.orchestrator.watchdog.store import WatchdogStore

NOW = 1_800_000_000_000
MIN = 60_000


def _turn(**kw: Any) -> TurnView:
    base: dict[str, Any] = {
        "session_id": "lead-1", "turn_id": "t1", "surface": "jarvis",
        "started_ms": NOW - 40 * MIN, "last_event_ms": NOW - 20 * MIN, "running": True,
    }
    base.update(kw)
    return TurnView(**base)


def _job(**kw: Any) -> JobView:
    base: dict[str, Any] = {
        "id": "job_a", "kind": "ide_submission", "title": "pane: fix the build", "state": "running",
        "owner_session": "lead-1", "progress_ms": NOW - 2 * 3600_000,
        "created_ms": NOW - 3 * 3600_000,
    }
    base.update(kw)
    return JobView(**base)


def _kinds(snap: Snapshot) -> list[str]:
    return [f.kind for f in checks.run_checks(snap)]


# ------------------------------------------------------------------ checks


def test_stuck_turn_is_found_and_offers_a_nudge_when_steerable() -> None:
    found = checks.run_checks(Snapshot(NOW, turns=[_turn(steerable=True)]))
    assert [f.kind for f in found] == [checks.KIND_STUCK_TURN]
    assert found[0].repair == checks.ACT_NUDGE
    assert found[0].evidence["idle_min"] == 20


def test_fresh_waiting_or_delegating_turns_are_not_stuck() -> None:
    assert _kinds(Snapshot(NOW, turns=[_turn(last_event_ms=NOW - 5 * MIN)])) == []
    assert _kinds(Snapshot(NOW, turns=[_turn(waiting_on_person=True)])) == []
    # The turn waits on a job it started: the job check owns that wait.
    job = _job(progress_ms=NOW - 5 * MIN)
    assert _kinds(Snapshot(NOW, turns=[_turn()], jobs=[job])) == []


def test_open_turn_nothing_runs_is_lost_not_stuck() -> None:
    found = checks.run_checks(Snapshot(NOW, turns=[_turn(running=False)]))
    assert [f.kind for f in found] == [checks.KIND_LOST_TURN]
    assert found[0].repair == ""  # closing it is the person's call


def test_stuck_job_by_kind_limit() -> None:
    found = checks.run_checks(Snapshot(NOW, jobs=[_job()]))
    assert [f.kind for f in found] == [checks.KIND_STUCK_JOB]
    assert found[0].judge is not None
    # A mission may run much longer than a pane prompt before it is suspicious.
    mission = _job(kind="mission", progress_ms=NOW - 2 * 3600_000)
    assert _kinds(Snapshot(NOW, jobs=[mission])) == []
    assert _kinds(Snapshot(NOW, jobs=[_job(progress_ms=NOW - 10 * MIN)])) == []


def test_interrupted_job_offers_a_single_requeue() -> None:
    found = checks.run_checks(Snapshot(NOW, jobs=[_job(state="interrupted")]))
    assert [f.kind for f in found] == [checks.KIND_INTERRUPTED_JOB]
    assert found[0].repair == checks.ACT_REQUEUE


def test_loop_signature_needs_identical_repeats() -> None:
    same = tuple(["Read:abc"] * 6)
    found = checks.run_checks(Snapshot(NOW, turns=[_turn(last_event_ms=NOW, tool_signatures=same)]))
    assert [f.kind for f in found] == [checks.KIND_LOOP]
    assert found[0].evidence["tool"] == "Read"
    varied = tuple(f"Read:{i}" for i in range(12))
    assert _kinds(Snapshot(NOW, turns=[_turn(last_event_ms=NOW, tool_signatures=varied)])) == []
    few = tuple(["Read:abc"] * 5)
    assert _kinds(Snapshot(NOW, turns=[_turn(last_event_ms=NOW, tool_signatures=few)])) == []


def test_claims_routines_seats_and_loop() -> None:
    snap = Snapshot(
        NOW,
        claims=[ClaimView("tr1", "Ada", NOW - 5 * 3600_000), ClaimView("tr2", "Bo", NOW - MIN)],
        routines=[RoutineView("r1", "Morning brief", NOW - 30 * MIN),
                  RoutineView("r2", "Soon", NOW - MIN)],
        seats=[SeatView("openai", "brain", "no_credits", NOW - MIN),
               SeatView("anthropic", "brain", "rate_limited", NOW - MIN),
               SeatView("old", "brain", "bad_key", NOW - 3 * 24 * 3600_000)],
        loop_ok=False, loop_stalled_s=90,
    )
    assert sorted(_kinds(snap)) == sorted([
        checks.KIND_LOOP_WEDGED, checks.KIND_CLAIM, checks.KIND_ROUTINE, checks.KIND_SEAT,
    ])


def test_limits_are_overridable() -> None:
    tight = Limits(lead_turn_idle_s=60)
    found = checks.run_checks(Snapshot(NOW, turns=[_turn(last_event_ms=NOW - 2 * MIN)]), tight)
    assert [f.kind for f in found] == [checks.KIND_STUCK_TURN]


# --------------------------------------------------------- the supervisor


class FakeSources:
    def __init__(self, snap: Snapshot) -> None:
        self.snap = snap
        self.lines: list[str] = []

    def snapshot(self, store: WatchdogStore, now: int) -> Snapshot:
        return self.snap

    def drain_log(self) -> list[str]:
        lines, self.lines = self.lines, []
        return lines


class FakeActions:
    def __init__(self) -> None:
        self.nudged: list[str] = []
        self.notices: list[dict[str, Any]] = []
        self.quiet = False
        self.reachable = True
        self.requeued: list[str] = []
        self.verdict: tuple[str, str] | None = None
        self.judged: list[tuple[str, str]] = []

    def can_repair(self, finding: Finding) -> bool:
        return True

    def repair(self, finding: Finding) -> str | None:
        if finding.repair == checks.ACT_NUDGE:
            self.nudged.append(finding.open_ref)
            return "asked the turn for a status"
        self.requeued.append(finding.key)
        return "re-queued"

    def post_notice(self, payload: dict[str, Any]) -> bool:
        if not self.reachable:
            return False
        self.notices.append(payload)
        return True

    def quiet_hours(self) -> bool:
        return self.quiet

    def judge(self, goal: str, evidence: str) -> tuple[str, str] | None:
        self.judged.append((goal, evidence))
        return self.verdict


def _watchdog(tmp_path: Any, snap: Snapshot, actions: FakeActions | None = None):
    sources = FakeSources(snap)
    actions = actions or FakeActions()
    clock = {"now": NOW}
    dog = supervisor.Watchdog(
        tmp_path, sources, actions, store=WatchdogStore(":memory:"), boot_id="boot-2",
        clock=lambda: clock["now"],
    )
    return dog, sources, actions, clock


def test_one_deduplicated_notice_for_a_persisting_finding(tmp_path: Any) -> None:
    dog, _src, actions, clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]))
    assert dog.scan()["notified"] == 1
    clock["now"] += 5 * MIN
    dog.scan()
    clock["now"] += 5 * MIN
    dog.scan()
    assert len(actions.notices) == 1
    notice = actions.notices[0]
    assert notice["kind"] == "watchdog"
    assert "No progress on" in notice["text"]
    assert notice["findings"][0]["actions"] == [checks.ACT_MARK_INTERRUPTED, checks.ACT_DISMISS]


def test_several_findings_share_one_notice(tmp_path: Any) -> None:
    snap = Snapshot(NOW, jobs=[_job(), _job(id="job_b", title="second")],
                    routines=[RoutineView("r1", "Brief", NOW - 30 * MIN)])
    dog, _src, actions, _clock = _watchdog(tmp_path, snap)
    dog.scan()
    assert len(actions.notices) == 1
    assert len(actions.notices[0]["findings"]) == 3


def test_resolved_finding_closes_and_a_new_one_notifies_again(tmp_path: Any) -> None:
    dog, src, actions, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]))
    dog.scan()
    src.snap = Snapshot(NOW)
    dog.scan()
    assert dog.store.open_findings() == []
    src.snap = Snapshot(NOW, jobs=[_job(id="job_other")])
    dog.scan()
    assert len(actions.notices) == 2


def test_quiet_hours_defer_the_notice_without_losing_it(tmp_path: Any) -> None:
    actions = FakeActions()
    actions.quiet = True
    dog, _src, _actions, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]), actions)
    dog.scan()
    assert actions.notices == []
    actions.quiet = False
    dog.scan()
    assert len(actions.notices) == 1


def test_unreachable_conversation_keeps_the_notice_pending(tmp_path: Any) -> None:
    actions = FakeActions()
    actions.reachable = False
    dog, _src, _a, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]), actions)
    dog.scan()
    actions.reachable = True
    dog.scan()
    assert len(actions.notices) == 1


def test_repair_is_tried_once_then_the_person_hears(tmp_path: Any) -> None:
    snap = Snapshot(NOW, turns=[_turn(steerable=True)])
    dog, _src, actions, _clock = _watchdog(tmp_path, snap)
    first = dog.scan()
    assert actions.nudged == ["lead-1"]
    assert first["notified"] == 0  # the nudge gets a scan to work before anything is said
    dog.scan()
    dog.scan()
    assert actions.nudged == ["lead-1"]  # never a second time
    assert len(actions.notices) == 1
    assert "Tried once" in actions.notices[0]["text"]


def test_requeue_runs_once_and_needs_no_notice(tmp_path: Any) -> None:
    dog, _src, actions, _clock = _watchdog(
        tmp_path, Snapshot(NOW, jobs=[_job(state="interrupted")])
    )
    dog.scan()
    dog.scan()
    assert actions.requeued == [f"{checks.KIND_INTERRUPTED_JOB}:job_a"]
    assert actions.notices == []


def test_a_failed_repair_becomes_a_notice(tmp_path: Any) -> None:
    class Failing(FakeActions):
        def repair(self, finding: Finding) -> str | None:
            return None

    dog, _src, actions, _clock = _watchdog(
        tmp_path, Snapshot(NOW, turns=[_turn(steerable=True)]), Failing()
    )
    dog.scan()
    assert len(actions.notices) == 1
    assert "did not apply" in actions.notices[0]["text"]


def test_checks_switch_off_stops_everything(tmp_path: Any) -> None:
    dog, _src, actions, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]))
    dog.store.save_settings(checks=False)
    assert dog.scan()["findings"] == 0
    assert actions.notices == []


def test_repair_log_lines_from_sources_are_recorded(tmp_path: Any) -> None:
    dog, src, _actions, _clock = _watchdog(tmp_path, Snapshot(NOW))
    src.lines = ["marked lost work interrupted: build"]
    report = dog.scan()
    assert report["repaired"] == ["marked lost work interrupted: build"]
    assert any(e["event"] == "repaired" for e in dog.store.events_since(0))


# ------------------------------------------------------------------ judge


def test_judge_is_off_by_default(tmp_path: Any) -> None:
    actions = FakeActions()
    dog, _src, _a, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]), actions)
    dog.scan()
    assert actions.judged == []


def test_judge_skipped_without_a_seat_leaves_the_code_checks_standing(tmp_path: Any) -> None:
    actions = FakeActions()  # verdict None: no subscription or local seat
    dog, _src, _a, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]), actions)
    dog.store.save_settings(judge=True)
    dog.scan()
    dog.scan()
    assert len(actions.judged) == 1  # asked once, not every scan
    assert len(actions.notices) == 1
    assert any(e["event"] == "judge_skipped" for e in dog.store.events_since(0))


def test_judge_saying_progress_silences_the_notice(tmp_path: Any) -> None:
    actions = FakeActions()
    actions.verdict = ("progress", "the build is compiling")
    dog, _src, _a, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]), actions)
    dog.store.save_settings(judge=True)
    dog.scan()
    assert actions.notices == []


def test_judge_saying_stuck_adds_its_reason(tmp_path: Any) -> None:
    actions = FakeActions()
    actions.verdict = ("stuck", "the same error repeats")
    dog, _src, _a, _clock = _watchdog(tmp_path, Snapshot(NOW, jobs=[_job()]), actions)
    dog.store.save_settings(judge=True)
    dog.scan()
    assert "the same error repeats" in actions.notices[0]["text"]


def test_judge_seats_never_include_a_key_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.brain import background_policy as policy

    monkeypatch.setattr(policy, "login_state", lambda provider: False)
    monkeypatch.setattr(policy, "keyless_local", lambda provider: False)
    assert judge.judge_seats() == []
    assert judge.resolve_judge_brain(object()) is None


@pytest.mark.asyncio
async def test_judge_returns_none_without_a_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_judge_brain", lambda config: None)
    assert await judge.judge("goal", "evidence", config=object()) is None


def test_judge_seats_allow_only_signed_in_subscriptions_and_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.brain import background_policy as policy

    monkeypatch.setattr(policy, "login_state", lambda provider: provider == "sub")
    monkeypatch.setattr(
        policy, "subscription_capable", lambda provider: provider in ("sub", "keyed")
    )
    monkeypatch.setattr(policy, "keyless_local", lambda provider: provider == "local")

    class Spec:
        def __init__(self, name: str) -> None:
            self.id, self.tier = name, "brain"

    import dodaios.ui.web.provider_spec as spec

    monkeypatch.setattr(spec, "PROVIDERS", [Spec("sub"), Spec("keyed"), Spec("local"), Spec("api")])
    assert judge.judge_seats() == ["sub", "local"]


def test_verdict_parsing_is_strict() -> None:
    assert judge.parse_verdict('x {"verdict": "stuck", "reason": "loops"} y') == judge.Verdict(
        "stuck", "loops"
    )
    assert judge.parse_verdict('{"verdict": "dance"}') is None
    assert judge.parse_verdict("no json") is None


# -------------------------------------------------- heartbeat and downtime


def test_unclean_stop_is_reported_with_downtime_and_in_flight_work(tmp_path: Any) -> None:
    (tmp_path / supervisor.HEARTBEAT_FILE).write_text(json.dumps({
        "ts_ms": NOW - 25 * MIN, "boot_id": "boot-1", "clean": False,
        "inflight": ["pane: fix the build"],
    }))
    dog, _src, actions, _clock = _watchdog(tmp_path, Snapshot(NOW))
    finding = dog.check_previous_run()
    assert finding is not None and finding.evidence["down_min"] == 25
    dog.scan()
    assert "about 25 minutes" in actions.notices[0]["text"]
    assert "pane: fix the build" in actions.notices[0]["text"]
    dog.scan()
    assert len(actions.notices) == 1


def test_clean_stop_and_short_gap_are_not_downtime(tmp_path: Any) -> None:
    path = tmp_path / supervisor.HEARTBEAT_FILE
    dog, _src, _actions, _clock = _watchdog(tmp_path, Snapshot(NOW))
    path.write_text(json.dumps({"ts_ms": NOW - 25 * MIN, "boot_id": "b", "clean": True}))
    assert dog.check_previous_run() is None
    path.write_text(json.dumps({"ts_ms": NOW - 30_000, "boot_id": "b", "clean": False}))
    assert dog.check_previous_run() is None


def test_heartbeat_file_carries_boot_id_and_clean_flag(tmp_path: Any) -> None:
    dog, _src, _actions, _clock = _watchdog(tmp_path, Snapshot(NOW))
    dog._write_heartbeat(clean=False)  # noqa: SLF001
    body = json.loads(dog.heartbeat_path.read_text())
    assert body["boot_id"] == "boot-2" and body["clean"] is False
    dog.stop()
    assert json.loads(dog.heartbeat_path.read_text())["clean"] is True


# ------------------------------------------------------------------- store


def test_progress_is_measured_from_the_last_change() -> None:
    store = WatchdogStore(":memory:")
    assert store.track_progress("j", "a", now=1000) == 1000
    assert store.track_progress("j", "a", now=9000) == 1000
    assert store.track_progress("j", "b", now=9500) == 9500


def test_claim_repair_is_atomic_once() -> None:
    store = WatchdogStore(":memory:")
    store.upsert(Finding("k", "stuck_turn", "t", {}), now=1)
    assert store.claim_repair("k") is True
    assert store.claim_repair("k") is False


def test_settings_defaults_and_validation() -> None:
    store = WatchdogStore(":memory:")
    assert store.settings() == {"checks": True, "judge": False, "interval_min": 5}
    store.save_settings(judge=True, interval_min=999, bogus=1)
    assert store.settings() == {"checks": True, "judge": True, "interval_min": 60}


# ----------------------------------------------- live evidence (own SQLite)


def test_open_turns_and_loop_signature_read_through_a_read_only_connection(tmp_path: Any) -> None:
    from dodaios.agent_chat.events import make_event
    from dodaios.agent_chat.store import AgentChatStore
    from dodaios.orchestrator.watchdog.live import LiveSources

    db = tmp_path / "agent_chat.db"
    chat = AgentChatStore(db)
    session = chat.create_session(
        title="", provider="p", model="m", effort="", cwd=str(tmp_path)
    )
    sid = session.session_id
    chat.append_event(sid, make_event("turn_started", {"turn_id": "t9"}))
    for i in range(7):
        chat.append_event(sid, make_event(
            "tool_call", {"turn_id": "t9", "call_id": f"c{i}", "name": "Read", "input": {"f": 1}}))
        chat.append_event(sid, make_event(
            "tool_result", {"turn_id": "t9", "call_id": f"c{i}", "output": "same"}))
    chat.append_event(sid, make_event("notice", {"kind": "x", "text": "ignored"}))

    class Service:
        store = chat

    class Runtime:
        def chat_service(self) -> Any:
            return Service()

    views = LiveSources(Runtime(), hop=None)._turns(loop_ok=False)  # noqa: SLF001
    assert len(views) == 1 and views[0].turn_id == "t9"
    assert len(views[0].tool_signatures) == 7 and len(set(views[0].tool_signatures)) == 1
    found = checks.run_checks(Snapshot(views[0].last_event_ms, turns=views))
    assert [f.kind for f in found] == [checks.KIND_LOOP]
    chat.close()


# ------------------------------------------------------------------- tools


@pytest.mark.asyncio
async def test_watchdog_status_tool_is_bounded_and_summary_first(tmp_path: Any) -> None:
    from dodaios.plugins.tool.watchdog_tools import WatchdogActTool, WatchdogStatusTool

    snap = Snapshot(NOW, jobs=[_job(id=f"job_{i}", title=f"w{i}") for i in range(14)])
    dog, _src, _actions, _clock = _watchdog(tmp_path, snap)
    dog.scan()
    supervisor.set_current(dog)
    try:
        result = await WatchdogStatusTool().execute({}, None)  # type: ignore[arg-type]
        assert result.success
        out = result.output
        assert len(out["open"]) == 10 and out["open_more"] is True
        assert out["settings"]["judge"] is False
        key = out["open"][0]["id"]
        # An action the finding does not offer is refused; dismiss always works.
        bad = await WatchdogActTool().execute({"action": "nudge", "id": key}, None)  # type: ignore[arg-type]
        assert not bad.success
        ok = await WatchdogActTool().execute({"action": "dismiss", "id": key}, None)  # type: ignore[arg-type]
        assert ok.success and dog.store.get(key)["state"] == "dismissed"
        sw = await WatchdogActTool().execute({"action": "set_judge", "enabled": True}, None)  # type: ignore[arg-type]
        assert sw.output["settings"]["judge"] is True
    finally:
        supervisor.set_current(None)


@pytest.mark.asyncio
async def test_lost_work_is_marked_interrupted_and_tracked(tmp_path: Any) -> None:
    from dodaios.orchestrator import jobs
    from dodaios.orchestrator.watchdog.live import LiveSources

    ledger = jobs.JobLedger(":memory:")
    jobs.set_ledger(ledger)
    try:
        ledger.create("ide_submission", job_id="job_old", title="pane work", owner_session="s")
        ledger.create("ide_submission", job_id="job_live", title="live work", owner_session="s")
        with ledger._lock:  # noqa: SLF001 - a row left by an earlier boot
            ledger._conn.execute("UPDATE jobs SET boot_id='older' WHERE id='job_old'")  # noqa: SLF001
            ledger._conn.commit()  # noqa: SLF001
        sources = LiveSources(runtime=None, hop=None)
        store = WatchdogStore(":memory:")
        views = await sources._read_jobs(store, NOW)  # noqa: SLF001
        by_id = {v.id: v for v in views}
        assert by_id["job_old"].state == "interrupted"
        assert by_id["job_live"].state == "running"
        assert sources.drain_log() == ["marked lost work interrupted: pane work"]
    finally:
        jobs.set_ledger(None)
        ledger.close()


def test_loop_hop_times_out_instead_of_waiting_on_a_wedged_loop() -> None:
    import asyncio
    import threading

    from dodaios.orchestrator.watchdog.live import LoopHop, LoopUnresponsive

    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(2)
    hop = LoopHop(loop)

    async def answer() -> int:
        return 7

    async def never() -> None:
        await asyncio.sleep(60)

    try:
        assert hop(answer, 2) == 7
        with pytest.raises(LoopUnresponsive):
            hop(never, 0.2)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(2)
        loop.close()
