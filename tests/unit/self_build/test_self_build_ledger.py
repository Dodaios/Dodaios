"""The build ledger, the lifecycle, the hard limits and one undo for every kind.

Nothing in the loop asks the person: a build opens in ``building`` or not at
all, a finished trial is kept or archived by its use, and proposals an older
version left behind are archived once when the service starts."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
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
from dodaios.self_build import service as service_mod
from dodaios.self_build.ledger import now_ms

DAY = 86_400_000


def _config(**overrides: object) -> SimpleNamespace:
    values = {"silent_days": 0, **overrides}
    return SimpleNamespace(self_build=SelfBuildConfig(**values))


def legacy_proposal(ledger: BuildLedger, kind: Kind, signature: str, title: str) -> str:
    """A card an older version left waiting for the person's OK. Written by hand:
    the ledger no longer opens one."""
    build_id = uuid.uuid4().hex[:16]
    stamp = now_ms()
    conn = sqlite3.connect(str(ledger.path))
    try:
        conn.execute(
            "INSERT INTO builds (id, kind, state, signature, title, created_ms, updated_ms)"
            " VALUES (?, ?, 'proposed', ?, ?, ?, ?)",
            (build_id, Kind(kind).value, signature, title, stamp, stamp),
        )
        conn.execute(
            "INSERT INTO history (build_id, ts_ms, src, dst, note)"
            " VALUES (?, ?, '', 'proposed', 'opened')",
            (build_id, stamp),
        )
        conn.commit()
    finally:
        conn.close()
    return build_id


@pytest.fixture
def ledger(tmp_path: Path) -> BuildLedger:
    book = BuildLedger(tmp_path / "self_build.db")
    yield book
    book.close()


# ------------------------------------------------------------------ ledger


def test_open_case_starts_building_with_evidence_and_history(ledger: BuildLedger) -> None:
    record = ledger.open_case(
        Kind.SKILL, "weekly-report", "Builds the Monday report", evidence=["turn:1", "turn:2"]
    )
    assert record.state == State.BUILDING
    assert record.evidence == ("turn:1", "turn:2")
    assert record.caller == f"self_build:{record.id}"
    assert [h["to"] for h in ledger.history(record.id)] == ["building"]


def test_one_open_build_per_signature(ledger: BuildLedger) -> None:
    ledger.open_case(Kind.SKILL, "sig", "first")
    with pytest.raises(DuplicateBuild):
        ledger.open_case(Kind.ROUTINE, "sig", "second")


def test_closed_build_frees_its_signature(ledger: BuildLedger) -> None:
    first = ledger.open_case(Kind.SKILL, "sig", "first")
    ledger.set_state(first.id, State.UNDONE)
    second = ledger.open_case(Kind.SKILL, "sig", "again")
    assert second.id != first.id
    assert ledger.rejections("sig") == 1


def test_lifecycle_refuses_impossible_moves(ledger: BuildLedger) -> None:
    record = ledger.open_case(Kind.MEMORY, "sig", "note")
    with pytest.raises(TransitionError):
        ledger.set_state(record.id, State.KEPT)
    with pytest.raises(TransitionError):
        ledger.set_state(record.id, State.PROPOSED)
    trial = ledger.set_state(record.id, State.TRIAL)
    assert trial.trial_started_ms > 0
    ledger.set_state(record.id, State.UNDONE)
    with pytest.raises(TransitionError):
        ledger.set_state(record.id, State.TRIAL)


def test_an_old_proposal_can_only_be_archived_or_turned_down(ledger: BuildLedger) -> None:
    build_id = legacy_proposal(ledger, Kind.SKILL, "sig", "card")
    with pytest.raises(TransitionError):
        ledger.set_state(build_id, State.BUILDING)  # nobody builds it on a click any more
    assert ledger.set_state(build_id, State.ARCHIVED).state == State.ARCHIVED


def test_uses_and_outcomes_are_counted(ledger: BuildLedger) -> None:
    record = ledger.open_case(Kind.SKILL, "sig", "skill")
    ledger.record_use(record.id, Outcome.ACCEPTED)
    ledger.record_use(record.id, Outcome.CORRECTED)
    updated = ledger.record_use(record.id, Outcome.IGNORED)
    assert updated.uses == 2
    assert updated.outcomes == {"accepted": 1, "corrected": 1, "ignored": 1}


def test_change_hook_sees_every_commit(tmp_path: Path) -> None:
    seen: list[str] = []
    book = BuildLedger(tmp_path / "db.sqlite", on_change=lambda r: seen.append(r.state.value))
    record = book.open_case(Kind.SKILL, "sig", "skill")
    book.set_state(record.id, State.TRIAL)
    book.close()
    assert seen == ["building", "trial"]


def test_hook_failure_never_loses_the_write(tmp_path: Path) -> None:
    def boom(_: object) -> None:
        raise RuntimeError("listener broke")

    book = BuildLedger(tmp_path / "db.sqlite", on_change=boom)
    record = book.open_case(Kind.SKILL, "sig", "skill")
    assert book.get(record.id) is not None
    book.close()


# ------------------------------------------------------------------ policy


def test_autonomy_is_fixed_whatever_the_config_says(ledger: BuildLedger) -> None:
    for kind in (Kind.MEMORY, Kind.SKILL, Kind.ROUTINE, Kind.AGENT):
        assert policy.autonomy(kind) == policy.Autonomy.FULL
    assert policy.autonomy(Kind.CODE) == policy.Autonomy.WATCH
    # The old switch and stages are ignored: "off" and "suggest" change nothing.
    old = _config(enabled=False, memory="off", skill="suggest", routine="trial", agent="off")
    for kind in (Kind.MEMORY, Kind.SKILL, Kind.ROUTINE):
        assert policy.admit(ledger, old, kind, f"s-{kind}", undoable=True).build
    assert policy.admit(ledger, old, Kind.CODE, "c", undoable=True).start is None


def test_paused_or_a_bare_config_admit_nothing(ledger: BuildLedger) -> None:
    bare = SimpleNamespace()
    assert policy.admit(ledger, bare, Kind.MEMORY, "s", undoable=True).reason == "off"
    policy.set_paused(ledger, True)
    verdict = policy.admit(ledger, _config(), Kind.MEMORY, "s", undoable=True)
    assert (verdict.start, verdict.reason) == (None, "paused")


def test_admit_never_proposes(ledger: BuildLedger) -> None:
    """Every "not now" is ``start=None`` with its reason; nothing waits for an OK."""
    stamp = now_ms()
    ledger.open_case(Kind.AGENT, "open", "agent")
    for _ in range(2):
        undone = ledger.open_case(Kind.SKILL, "undone", "skill")
        ledger.set_state(undone.id, State.UNDONE)

    def cfg(**overrides: object) -> SimpleNamespace:
        return _config(**{"max_builds_per_day": 50, **overrides})

    cases = [
        (cfg(), Kind.SKILL, "open", True, "already open"),
        (cfg(), Kind.SKILL, "undone", True, "undone before"),
        (cfg(silent_days=7), Kind.SKILL, "fresh", True, "silent"),
        (cfg(), Kind.SKILL, "fresh", False, "no undo for this kind"),
        (cfg(max_builds_per_day=1), Kind.SKILL, "fresh", True, "daily build cap"),
        (cfg(max_open_trials=0), Kind.SKILL, "fresh", True, "trial cap"),
        (cfg(max_agents_per_week=1), Kind.AGENT, "fresh", True, "weekly agent cap"),
        (cfg(code="full"), Kind.CODE, "fresh", True, "watch"),
        (cfg(skill="suggest"), Kind.SKILL, "fresh", True, ""),
    ]
    for cfg, kind, signature, undoable, reason in cases:
        verdict = policy.admit(ledger, cfg, kind, signature, undoable=undoable, now=stamp)
        assert verdict.start in (None, State.BUILDING), (signature, reason)
        assert verdict.start != State.PROPOSED
        if reason:
            assert (verdict.start, verdict.reason) == (None, reason)
        else:
            assert verdict.build
    policy.set_paused(ledger, True)
    assert policy.admit(ledger, _config(), Kind.SKILL, "fresh", undoable=True).start is None


def test_silent_days_open_nothing_then_build(ledger: BuildLedger) -> None:
    cfg = _config(silent_days=7)
    start = now_ms()
    verdict = policy.admit(ledger, cfg, Kind.MEMORY, "s", undoable=True, now=start)
    assert (verdict.start, verdict.reason) == (None, "silent")
    later = start + 8 * DAY
    assert policy.admit(ledger, cfg, Kind.MEMORY, "s", undoable=True, now=later).build


def test_archived_old_proposals_do_not_count_as_builds(ledger: BuildLedger) -> None:
    build_id = legacy_proposal(ledger, Kind.SKILL, "s", "card")
    ledger.set_state(build_id, State.ARCHIVED, "archived")
    assert ledger.count_since(now_ms() - DAY, built_only=True) == 0
    cfg = _config(max_builds_per_day=1)
    assert policy.admit(ledger, cfg, Kind.SKILL, "s", undoable=True).build


def test_trial_settles_by_use(ledger: BuildLedger) -> None:
    cfg = _config(trial_uses=3)
    record = ledger.open_case(Kind.SKILL, "s", "skill")
    ledger.set_state(record.id, State.TRIAL)
    for _ in range(3):
        record = ledger.record_use(record.id, Outcome.ACCEPTED)
    assert policy.trial_over(record, cfg)
    assert policy.settle(record) == State.KEPT


def test_unused_trial_is_archived(ledger: BuildLedger) -> None:
    cfg = _config(trial_days=14)
    record = ledger.open_case(Kind.SKILL, "s", "skill")
    record = ledger.set_state(record.id, State.TRIAL)
    assert not policy.trial_over(record, cfg)
    assert policy.trial_over(record, cfg, now=record.trial_started_ms + 15 * DAY)
    assert policy.settle(record) == State.ARCHIVED


def test_config_keeps_the_old_keys_loadable() -> None:
    cfg = JarvisConfig().self_build
    assert cfg.silent_days == 7 and cfg.max_rejections == 2
    # A config file of an older version still loads; its stages are ignored.
    old = SelfBuildConfig(enabled=False, memory="off", skill="suggest", code="full")
    assert (old.enabled, old.memory, old.skill, old.code) == (False, "off", "suggest", "full")


# ------------------------------------------------------------------ service + undo


@pytest.fixture
def service(tmp_path: Path) -> SelfBuild:
    # Old stage keys in the config: ignored, every kind settles by use.
    svc = SelfBuild(tmp_path, lambda: _config(memory="trial", skill="suggest", trial_uses=2))
    yield svc
    svc.ledger.close()


async def test_undo_turns_down_an_old_proposal(service: SelfBuild) -> None:
    build_id = legacy_proposal(service.ledger, Kind.SKILL, "s", "skill")
    undone = await service.undo_build(build_id)
    assert undone.state == State.REJECTED


async def test_undo_calls_the_kind_undoer(service: SelfBuild) -> None:
    removed: list[str] = []

    async def remove(rec: object) -> None:
        removed.append(rec.artefact["id"])  # type: ignore[attr-defined]

    service.undo.register(Kind.SKILL, remove)
    record = service.ledger.open_case(Kind.SKILL, "s", "skill")
    service.ledger.attach_artefact(record.id, {"type": "skill", "id": "weekly"}, {"slug": "weekly"})
    service.ledger.set_state(record.id, State.TRIAL)
    undone = await service.undo_build(record.id)
    assert undone.state == State.UNDONE
    assert removed == ["weekly"]


async def test_undo_without_undoer_is_refused(service: SelfBuild) -> None:
    record = service.ledger.open_case(Kind.AGENT, "s", "agent")
    service.ledger.attach_artefact(record.id, {"type": "agent", "id": "a"}, {})
    with pytest.raises(UndoUnavailable):
        await service.undo_build(record.id)
    assert service.ledger.get(record.id).state == State.BUILDING  # type: ignore[union-attr]


def test_the_service_has_no_accept_or_keep(service: SelfBuild) -> None:
    assert not hasattr(service, "accept")
    assert not hasattr(service, "keep")


async def test_sweep_keeps_a_used_trial_without_a_click_for_every_kind(
    service: SelfBuild,
) -> None:
    used: dict[Kind, str] = {}
    for kind in (Kind.MEMORY, Kind.SKILL, Kind.ROUTINE, Kind.AGENT, Kind.CODE):
        record = service.ledger.open_case(kind, f"used-{kind}", f"used {kind}")
        service.ledger.set_state(record.id, State.TRIAL)
        for _ in range(2):
            service.ledger.record_use(record.id, Outcome.ACCEPTED)
        used[kind] = record.id
    corrected = service.ledger.open_case(Kind.SKILL, "corrected", "corrected")
    service.ledger.set_state(corrected.id, State.TRIAL)
    for _ in range(2):
        service.ledger.record_use(corrected.id, Outcome.CORRECTED)
    await service.sweep()
    for kind, build_id in used.items():
        record = service.ledger.get(build_id)
        assert record is not None and record.state == State.KEPT, kind
        assert record.note == "kept: used and accepted"
    assert service.ledger.get(corrected.id).state == State.ARCHIVED  # type: ignore[union-attr]


async def test_paused_sweep_settles_nothing(service: SelfBuild) -> None:
    record = service.ledger.open_case(Kind.SKILL, "s", "skill")
    service.ledger.set_state(record.id, State.TRIAL)
    for _ in range(2):
        service.ledger.record_use(record.id, Outcome.ACCEPTED)
    service.set_paused(True)
    assert await service.sweep() == []
    assert service.ledger.get(record.id).state == State.TRIAL  # type: ignore[union-attr]


def test_old_proposals_are_archived_once_and_only_once(tmp_path: Path) -> None:
    service_mod.reset_for_tests()
    book = BuildLedger(tmp_path / "self_build.db")
    first = legacy_proposal(book, Kind.SKILL, "weekly-report", "A skill for the report")
    second = legacy_proposal(book, Kind.ROUTINE, "monday", "A Monday routine")
    live = book.open_case(Kind.MEMORY, "memo", "memo")
    book.close()
    try:
        svc = service_mod.start(tmp_path, lambda: _config())
        for build_id in (first, second):
            record = svc.ledger.get(build_id)
            assert record is not None  # never deleted
            assert record.state == State.ARCHIVED
            assert record.note == service_mod.RETIRED_NOTE
        assert svc.ledger.get(live.id).state == State.BUILDING  # type: ignore[union-attr]
        assert svc.ledger.list(states=[State.PROPOSED]) == []
        service_mod.reset_for_tests()
        svc = service_mod.start(tmp_path, lambda: _config())
        for build_id in (first, second):
            moves = [(h["from"], h["to"]) for h in svc.ledger.history(build_id)]
            assert moves == [("", "proposed"), ("proposed", "archived")]
        assert len(svc.ledger.list()) == 3
        # The need is free again: the loop may build it on trial on its own.
        assert svc.admit(Kind.SKILL, "weekly-report").start is None  # no undoer here
        svc.undo.register(Kind.SKILL, lambda rec: None)
        assert svc.admit(Kind.SKILL, "weekly-report").build
    finally:
        service_mod.reset_for_tests()


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


def test_routes_list_pause_and_undo_and_nothing_to_approve(tmp_path: Path) -> None:
    from dodaios.ui.web.self_build_routes import router

    svc = SelfBuild(tmp_path, lambda: _config(enabled=False, skill="suggest"))
    app = FastAPI()
    app.state.self_build = svc
    app.include_router(router)
    client = TestClient(app)
    record = svc.ledger.open_case(Kind.SKILL, "s", "Weekly report")

    listing = client.get("/api/self-build").json()
    assert [b["id"] for b in listing["builds"]] == [record.id]
    status = listing["status"]
    assert status["paused"] is False and "enabled" not in status
    assert status["autonomy"] == {
        "memory": "full",
        "skill": "full",
        "routine": "full",
        "agent": "full",
        "code": "watch",
    }

    assert client.post("/api/self-build/pause", json={"paused": True}).json()["paused"] is True
    detail = client.get(f"/api/self-build/{record.id}").json()
    assert detail["build"]["title"] == "Weekly report"
    assert detail["history"][0]["to"] == "building"

    undone = client.post(f"/api/self-build/{record.id}/undo").json()
    assert undone["build"]["state"] == "undone"
    for gone in ("accept", "keep"):
        assert client.post(f"/api/self-build/{record.id}/{gone}").status_code in (404, 405)
    assert client.get("/api/self-build/nope").status_code == 404
    svc.ledger.close()
