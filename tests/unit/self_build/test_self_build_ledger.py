"""The build ledger, the lifecycle, the hard limits and one undo for every kind."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core.config import JarvisConfig, SelfBuildConfig
from dodaios.self_build import (
    BuildLedger,
    DuplicateBuild,
    Kind,
    Outcome,
    SelfBuild,
    State,
    TransitionError,
    UndoUnavailable,
    policy,
)
from dodaios.self_build.ledger import now_ms

DAY = 86_400_000


def _config(**overrides: object) -> SimpleNamespace:
    values = {"silent_days": 0, **overrides}
    return SimpleNamespace(self_build=SelfBuildConfig(**values))


@pytest.fixture
def ledger(tmp_path: Path) -> BuildLedger:
    book = BuildLedger(tmp_path / "self_build.db")
    yield book
    book.close()


# ------------------------------------------------------------------ ledger


def test_open_case_records_evidence_and_history(ledger: BuildLedger) -> None:
    record = ledger.open_case(
        Kind.SKILL, "weekly-report", "Builds the Monday report", evidence=["turn:1", "turn:2"]
    )
    assert record.state == State.PROPOSED
    assert record.evidence == ("turn:1", "turn:2")
    assert record.caller == f"self_build:{record.id}"
    assert [h["to"] for h in ledger.history(record.id)] == ["proposed"]


def test_one_open_build_per_signature(ledger: BuildLedger) -> None:
    ledger.open_case(Kind.SKILL, "sig", "first")
    with pytest.raises(DuplicateBuild):
        ledger.open_case(Kind.ROUTINE, "sig", "second")


def test_closed_build_frees_its_signature(ledger: BuildLedger) -> None:
    first = ledger.open_case(Kind.SKILL, "sig", "first")
    ledger.set_state(first.id, State.REJECTED)
    second = ledger.open_case(Kind.SKILL, "sig", "again")
    assert second.id != first.id
    assert ledger.rejections("sig") == 1


def test_lifecycle_refuses_impossible_moves(ledger: BuildLedger) -> None:
    record = ledger.open_case(Kind.MEMORY, "sig", "note")
    with pytest.raises(TransitionError):
        ledger.set_state(record.id, State.KEPT)
    ledger.set_state(record.id, State.BUILDING)
    trial = ledger.set_state(record.id, State.TRIAL)
    assert trial.trial_started_ms > 0
    ledger.set_state(record.id, State.UNDONE)
    with pytest.raises(TransitionError):
        ledger.set_state(record.id, State.TRIAL)


def test_uses_and_outcomes_are_counted(ledger: BuildLedger) -> None:
    record = ledger.open_case(Kind.SKILL, "sig", "skill", state=State.BUILDING)
    ledger.record_use(record.id, Outcome.ACCEPTED)
    ledger.record_use(record.id, Outcome.CORRECTED)
    updated = ledger.record_use(record.id, Outcome.IGNORED)
    assert updated.uses == 2
    assert updated.outcomes == {"accepted": 1, "corrected": 1, "ignored": 1}


def test_change_hook_sees_every_commit(tmp_path: Path) -> None:
    seen: list[str] = []
    book = BuildLedger(tmp_path / "db.sqlite", on_change=lambda r: seen.append(r.state.value))
    record = book.open_case(Kind.SKILL, "sig", "skill")
    book.set_state(record.id, State.BUILDING)
    book.close()
    assert seen == ["proposed", "building"]


def test_hook_failure_never_loses_the_write(tmp_path: Path) -> None:
    def boom(_: object) -> None:
        raise RuntimeError("listener broke")

    book = BuildLedger(tmp_path / "db.sqlite", on_change=boom)
    record = book.open_case(Kind.SKILL, "sig", "skill")
    assert book.get(record.id) is not None
    book.close()


# ------------------------------------------------------------------ policy


def test_off_and_paused_admit_nothing(ledger: BuildLedger) -> None:
    assert policy.admit(ledger, _config(skill="off"), Kind.SKILL, "s", undoable=True).start is None
    disabled = _config(enabled=False)
    assert policy.admit(ledger, disabled, Kind.MEMORY, "s", undoable=True).start is None
    policy.set_paused(ledger, True)
    verdict = policy.admit(ledger, _config(), Kind.MEMORY, "s", undoable=True)
    assert (verdict.start, verdict.reason) == (None, "paused")


def test_suggest_only_proposes(ledger: BuildLedger) -> None:
    verdict = policy.admit(ledger, _config(skill="suggest"), Kind.SKILL, "s", undoable=True)
    assert verdict.start == State.PROPOSED


def test_trial_builds_only_when_undoable(ledger: BuildLedger) -> None:
    cfg = _config(memory="trial")
    assert policy.admit(ledger, cfg, Kind.MEMORY, "s", undoable=True).build
    assert policy.admit(ledger, cfg, Kind.MEMORY, "s", undoable=False).start == State.PROPOSED


def test_silent_days_only_propose(ledger: BuildLedger) -> None:
    cfg = _config(memory="trial", silent_days=7)
    start = now_ms()
    assert policy.admit(ledger, cfg, Kind.MEMORY, "s", undoable=True, now=start).reason == "silent"
    later = start + 8 * DAY
    assert policy.admit(ledger, cfg, Kind.MEMORY, "s", undoable=True, now=later).build


def test_rejected_need_is_not_offered_again(ledger: BuildLedger) -> None:
    cfg = _config(max_rejections=2)
    for _ in range(2):
        record = ledger.open_case(Kind.SKILL, "s", "skill")
        ledger.set_state(record.id, State.REJECTED)
    assert policy.admit(ledger, cfg, Kind.SKILL, "s", undoable=True).reason == "rejected before"


def test_daily_cap_and_weekly_agent_cap(ledger: BuildLedger) -> None:
    cfg = _config(memory="trial", agent="trial", max_builds_per_day=1, max_agents_per_week=1)
    ledger.open_case(Kind.AGENT, "a1", "agent", state=State.BUILDING)
    assert policy.admit(ledger, cfg, Kind.MEMORY, "m", undoable=True).reason == "daily build cap"
    cfg = _config(agent="trial", max_builds_per_day=10, max_agents_per_week=1)
    verdict = policy.admit(ledger, cfg, Kind.AGENT, "a2", undoable=True)
    assert verdict.reason == "weekly agent cap"


def test_trial_settles_by_use(ledger: BuildLedger) -> None:
    cfg = _config(trial_uses=3)
    record = ledger.open_case(Kind.SKILL, "s", "skill", state=State.BUILDING)
    ledger.set_state(record.id, State.TRIAL)
    for _ in range(3):
        record = ledger.record_use(record.id, Outcome.ACCEPTED)
    assert policy.trial_over(record, cfg)
    assert policy.settle(record) == State.KEPT


def test_unused_trial_is_archived(ledger: BuildLedger) -> None:
    cfg = _config(trial_days=14)
    record = ledger.open_case(Kind.SKILL, "s", "skill", state=State.BUILDING)
    record = ledger.set_state(record.id, State.TRIAL)
    assert not policy.trial_over(record, cfg)
    assert policy.trial_over(record, cfg, now=record.trial_started_ms + 15 * DAY)
    assert policy.settle(record) == State.ARCHIVED


def test_config_section_ships_with_safe_defaults() -> None:
    cfg = JarvisConfig().self_build
    assert cfg.enabled and cfg.silent_days == 7
    assert (cfg.memory, cfg.skill, cfg.routine, cfg.agent, cfg.code) == (
        "trial",
        "suggest",
        "suggest",
        "suggest",
        "suggest",
    )


# ------------------------------------------------------------------ service + undo


@pytest.fixture
def service(tmp_path: Path) -> SelfBuild:
    svc = SelfBuild(tmp_path, lambda: _config(memory="trial", skill="full", trial_uses=2))
    yield svc
    svc.ledger.close()


async def test_undo_rejects_a_proposal(service: SelfBuild) -> None:
    record = service.ledger.open_case(Kind.SKILL, "s", "skill")
    undone = await service.undo_build(record.id)
    assert undone.state == State.REJECTED


async def test_undo_calls_the_kind_undoer(service: SelfBuild) -> None:
    removed: list[str] = []

    async def remove(rec: object) -> None:
        removed.append(rec.artefact["id"])  # type: ignore[attr-defined]

    service.undo.register(Kind.SKILL, remove)
    record = service.ledger.open_case(Kind.SKILL, "s", "skill", state=State.BUILDING)
    service.ledger.attach_artefact(record.id, {"type": "skill", "id": "weekly"}, {"slug": "weekly"})
    service.ledger.set_state(record.id, State.TRIAL)
    undone = await service.undo_build(record.id)
    assert undone.state == State.UNDONE
    assert removed == ["weekly"]


async def test_undo_without_undoer_is_refused(service: SelfBuild) -> None:
    record = service.ledger.open_case(Kind.AGENT, "s", "agent", state=State.BUILDING)
    service.ledger.attach_artefact(record.id, {"type": "agent", "id": "a"}, {})
    with pytest.raises(UndoUnavailable):
        await service.undo_build(record.id)
    assert service.ledger.get(record.id).state == State.BUILDING  # type: ignore[union-attr]


async def test_accept_hands_the_build_to_its_builder(service: SelfBuild) -> None:
    built = asyncio.Event()

    async def builder(rec: object) -> None:
        service.ledger.set_state(rec.id, State.TRIAL)  # type: ignore[attr-defined]
        built.set()

    service.register_builder(Kind.SKILL, builder)
    service.undo.register(Kind.SKILL, lambda rec: None)
    record = service.ledger.open_case(Kind.SKILL, "s", "skill")
    accepted = await service.accept(record.id)
    assert accepted.state == State.BUILDING
    await asyncio.wait_for(built.wait(), 2)
    assert service.ledger.get(record.id).state == State.TRIAL  # type: ignore[union-attr]


async def test_sweep_keeps_only_at_full_and_archives_unused(service: SelfBuild) -> None:
    used = service.ledger.open_case(Kind.SKILL, "used", "used", state=State.BUILDING)
    service.ledger.set_state(used.id, State.TRIAL)
    for _ in range(2):
        service.ledger.record_use(used.id, Outcome.ACCEPTED)
    memo = service.ledger.open_case(Kind.MEMORY, "memo", "memo", state=State.BUILDING)
    service.ledger.set_state(memo.id, State.TRIAL)
    for _ in range(2):
        service.ledger.record_use(memo.id, Outcome.ACCEPTED)
    await service.sweep()
    assert service.ledger.get(used.id).state == State.KEPT  # type: ignore[union-attr]
    # memory runs at "trial": a good trial waits for the person's keep
    assert service.ledger.get(memo.id).state == State.TRIAL  # type: ignore[union-attr]


async def test_changes_are_published_on_the_bus(tmp_path: Path) -> None:
    events: list[object] = []

    async def publish(event: object) -> None:
        events.append(event)

    svc = SelfBuild(tmp_path, lambda: _config(), publish=publish)
    svc.bind_loop(asyncio.get_running_loop())
    svc.ledger.open_case(Kind.SKILL, "s", "Weekly report")
    for _ in range(20):
        if events:
            break
        await asyncio.sleep(0.01)
    svc.ledger.close()
    assert type(events[0]).__name__ == "SelfBuildChanged"
    assert events[0].title == "Weekly report"  # type: ignore[attr-defined]


# ------------------------------------------------------------------ routes


def test_routes_list_pause_and_undo(tmp_path: Path) -> None:
    from dodaios.ui.web.self_build_routes import router

    svc = SelfBuild(tmp_path, lambda: _config())
    app = FastAPI()
    app.state.self_build = svc
    app.include_router(router)
    client = TestClient(app)
    record = svc.ledger.open_case(Kind.SKILL, "s", "Weekly report")

    listing = client.get("/api/self-build").json()
    assert [b["id"] for b in listing["builds"]] == [record.id]
    assert listing["status"]["paused"] is False

    assert client.post("/api/self-build/pause", json={"paused": True}).json()["paused"] is True
    detail = client.get(f"/api/self-build/{record.id}").json()
    assert detail["build"]["title"] == "Weekly report"
    assert detail["history"][0]["to"] == "proposed"

    undone = client.post(f"/api/self-build/{record.id}/undo").json()
    assert undone["build"]["state"] == "rejected"
    assert client.post(f"/api/self-build/{record.id}/accept").status_code == 200
    assert client.get("/api/self-build/nope").status_code == 404
    svc.ledger.close()
