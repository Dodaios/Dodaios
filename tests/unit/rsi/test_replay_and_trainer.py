"""Replaying a tighter steering policy on the record, and the loop that changes policies."""

from __future__ import annotations

import time
from itertools import count
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.orchestrator.verification.store import VerificationStore
from dodaios.rsi import replay, selector, trainer
from dodaios.rsi.policy import ACTIVE, CANDIDATE, DEFAULT, Policy, PolicyStore, target_for

CELL = "backend|claude-opus-5-5|claude-cli 2.1"
_ids = count()


@pytest.fixture
def runs(tmp_path):
    store = VerificationStore(tmp_path / "verification.db")
    yield store
    store.close()


def record(
    store: VerificationStore,
    *,
    policy: Policy = DEFAULT,
    outputs: list[dict[str, Any]],
    verdict: str = "verified",
    reason: str = "",
    gate_status: str = "clean",
    started_ms: int | None = None,
) -> str:
    """One finished run with one step set per output (turn, scan, evidence)."""
    run_id = f"job_{next(_ids)}"
    start = started_ms or int(time.time() * 1000)
    store.start_run(
        run_id, "s1", started_ms=start, root_span_id=f"root-{run_id}",
        primary_domain="backend", model_requested="claude-opus-5-5",
        policy_id=policy.id, policy_json=policy.to_text(), arm=ACTIVE,
    )
    total_cost, total_ms = 0.0, 0
    for k, out in enumerate(outputs):
        ended = start + 1000 * (k + 1) * 600
        store.add_step(run_id, k, "turn_finished", status="done", ts_ms=ended, detail={
            "cost_usd": out.get("cost", 0.10), "duration_ms": out.get("ms", 60_000),
            "tokens_out": 100,
        })
        store.add_step(run_id, k, "gates", status="clean", ts_ms=ended + 1, detail={
            "added": out.get("added", 10), "deleted": 0,
        })
        store.add_step(run_id, k, "evidence", status="merged/passing",
                       ts_ms=ended + 1000 * out.get("settle_s", 60), detail={})
        total_cost += out.get("cost", 0.10)
        total_ms += out.get("ms", 60_000)
    store.update_run(
        run_id, state="ended", verdict=verdict, verdict_reason=reason,
        follow_ups=len(outputs) - 1, cost_usd=total_cost, wall_ms=total_ms,
        churn_lines=outputs[-1].get("added", 10), gate_status=gate_status,
        runner="claude-cli", harness_line="2.1", turn_status="done",
    )
    return run_id


def rows(store: VerificationStore) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    return [(r, store.steps(r["run_id"])) for r in store.runs()]


# ------------------------------------------------------------------- replay


def test_a_run_inside_the_candidates_limits_replays_as_recorded(runs):
    record(runs, outputs=[{}])
    (row, steps), = rows(runs)
    assert replay.replay_run(row, steps, Policy(p_max=1)) == selector.metrics_of(row)


def test_a_run_that_needed_more_follow_ups_is_cut_where_one_was_due(runs):
    record(runs, outputs=[{"cost": 0.4, "ms": 120_000, "added": 30}, {"cost": 0.3, "ms": 60_000}])
    (row, steps), = rows(runs)
    cut = replay.replay_run(row, steps, Policy(p_max=0))
    assert cut is not None
    assert (cut.passed, cut.one, cut.p, cut.churn) == (0.0, 0.0, 0.0, 30.0)
    assert cut.cost == pytest.approx(0.4 + 0.001 * 120)


def test_a_shorter_wait_misses_checks_that_settled_later(runs):
    record(runs, outputs=[{"settle_s": 30 * 60}])
    (row, steps), = rows(runs)
    assert replay.replay_run(row, steps, Policy(evidence_wait_s=20 * 60)).passed == 0.0
    assert replay.replay_run(row, steps, Policy(evidence_wait_s=40 * 60)).passed == 1.0


def test_nothing_beyond_the_record_is_replayed(runs):
    record(runs, policy=Policy(p_max=1), outputs=[{}, {}])
    (row, steps), = rows(runs)
    assert replay.replay_run(row, steps, Policy(p_max=2)) is None
    assert replay.replay_run(row, steps, DEFAULT) is None


def test_a_record_without_each_turns_cost_cannot_be_cut(runs):
    run_id = record(runs, outputs=[{}, {}])
    runs.add_step(run_id, 0, "turn_finished:old", ts_ms=1, detail={})
    row = runs.get(run_id)
    steps = [s for s in runs.steps(run_id) if s["step"] != "turn_finished" or s["iteration"]]
    assert replay.replay_run(row, steps, Policy(p_max=0)) is None


CLAIM = selector.Claim(CELL, "B", "cost")


def test_follow_ups_that_never_helped_can_go(runs):
    for _ in range(50):
        record(runs, outputs=[{}])
    for _ in range(10):
        record(runs, outputs=[{}, {"cost": 0.5}], verdict="failed")
    found = replay.replay_cell(CLAIM, rows(runs), Policy(p_max=0))
    assert found.answer == "accept", found.reasons
    assert found.coverage == 1.0


def test_follow_ups_that_fixed_runs_are_kept(runs):
    for _ in range(45):
        record(runs, outputs=[{}])
    for _ in range(15):
        record(runs, outputs=[{}, {"cost": 0.5}])  # the follow-up made it pass
    found = replay.replay_cell(CLAIM, rows(runs), Policy(p_max=0))
    assert found.answer == "reject"
    assert found.reasons == ["the PassRate drops"]


def test_too_little_record_or_too_few_runs_ask_for_a_canary(runs):
    for _ in range(10):
        record(runs, outputs=[{}])
    assert "fewer than 40" in replay.replay_cell(CLAIM, rows(runs), Policy(p_max=1)).reasons[0]
    for _ in range(50):
        record(runs, policy=Policy(p_max=1), outputs=[{}, {}])
    outside = replay.replay_cell(CLAIM, rows(runs), DEFAULT)
    assert outside.answer == "inconclusive"
    assert "a canary is needed" in outside.reasons[0]


# ------------------------------------------------------------------ trainer


@pytest.fixture
def world(tmp_path, runs):
    from dodaios.self_change.registry import SelfChangeRegistry
    from dodaios.self_change.surfaces import Surface

    policies = PolicyStore(tmp_path / "rsi.db")
    registry = SelfChangeRegistry(
        tmp_path / "changes", audit=lambda: SimpleNamespace(record=lambda _row: None)
    )
    registry.register_handler(Surface.CODING_POLICY, policies)
    made = trainer.Trainer(runs, policies, lambda: registry, samples=300)
    yield SimpleNamespace(runs=runs, policies=policies, registry=registry, trainer=made)
    registry.close()
    policies.close()


def test_with_too_few_runs_nothing_is_proposed(world):
    record(world.runs, outputs=[{}])
    assert world.trainer.consider(CELL) == "waiting for runs"
    assert world.policies.cells() == {}


def _cell_where_follow_ups_never_help(store: VerificationStore, n: int = 70) -> None:
    for i in range(n):
        if i % 7:
            record(store, outputs=[{}])
        else:
            record(store, outputs=[{}, {"cost": 0.5}], verdict="failed")


def test_a_candidate_the_replay_allows_goes_on_trial_with_its_claim_fixed(world):
    _cell_where_follow_ups_never_help(world.runs)
    done = world.trainer.consider(CELL)
    assert done == f"candidate {Policy(p_max=0).id} on trial", done
    assert world.policies.policy(CELL, CANDIDATE) == Policy(p_max=0)
    [claim] = world.trainer.claims()
    assert (claim["branch"], claim["target"], claim["outcome"]) == ("B", "cost", "")
    assert world.trainer.consider(CELL) == "trial goes on"
    [change] = [c for c in world.registry.store.list() if c.target.endswith("#candidate")]
    assert (change.author, change.state.value) == ("rsi-selector", "trial")
    assert "replay" in change.reason


def test_a_canary_that_wins_makes_the_candidate_active(world):
    _cell_where_follow_ups_never_help(world.runs)
    world.trainer.consider(CELL)
    later = int(time.time() * 1000) + 10_000
    for _ in range(65):
        record(world.runs, policy=Policy(p_max=0), outputs=[{"cost": 0.05}], started_ms=later)
        record(world.runs, outputs=[{"cost": 0.20}], started_ms=later)
    done = world.trainer.consider(CELL)
    assert done == "trial ended: accept", done
    assert world.policies.policy(CELL, ACTIVE) == Policy(p_max=0)
    assert world.policies.policy(CELL, CANDIDATE) is None
    assert world.trainer.claims()[0]["outcome"] == "accept"


def test_a_canary_that_loses_ends_the_trial_and_keeps_the_active_policy(world):
    _cell_where_follow_ups_never_help(world.runs)
    world.trainer.consider(CELL)
    later = int(time.time() * 1000) + 10_000
    for i in range(65):
        record(world.runs, policy=Policy(p_max=0), outputs=[{}], started_ms=later,
               verdict="failed" if i % 3 == 0 else "verified")
        record(world.runs, outputs=[{}], started_ms=later)
    assert world.trainer.consider(CELL) == "trial ended: reject"
    assert world.policies.policy(CELL, ACTIVE) is None
    assert world.policies.policy(CELL, CANDIDATE) is None


def test_the_first_weakened_check_under_a_new_policy_rolls_it_back(world):
    target = target_for(CELL, ACTIVE)
    world.registry.propose(trainer.Trainer._draft(target, Policy(p_max=1), "accepted"))
    assert world.policies.policy(CELL, ACTIVE) == Policy(p_max=1)
    record(world.runs, policy=Policy(p_max=1), outputs=[{}], gate_status="violations",
           verdict="failed", started_ms=int(time.time() * 1000) + 5_000)
    done = world.trainer.consider(CELL)
    assert done.startswith(f"rolled back {Policy(p_max=1).id}")
    assert world.policies.policy(CELL, ACTIVE) is None


def test_an_owner_who_rolled_the_candidate_back_ends_its_trial(world):
    _cell_where_follow_ups_never_help(world.runs)
    world.trainer.consider(CELL)
    [change] = [c for c in world.registry.store.list() if c.target.endswith("#candidate")]
    world.registry.rollback(change.id)
    assert world.trainer.consider(CELL) == "trial withdrawn"
    assert world.trainer.claims()[0]["outcome"] == "withdrawn"


def test_without_a_registry_nothing_changes(runs, tmp_path):
    policies = PolicyStore(tmp_path / "rsi2.db")
    try:
        assert trainer.Trainer(runs, policies, lambda: None).consider(CELL) == (
            "no self-change registry in this process"
        )
    finally:
        policies.close()


def test_the_grid_only_steers_and_never_writes_text_for_agents():
    assert all(not p.domain_block for p in trainer.GRID)
    assert all(p.p_max <= DEFAULT.p_max for p in trainer.GRID)


# ---------------------------------------------------- text candidates (Phase 5)


def _record_with_follow_up(store: VerificationStore, reason: str, template: str = "T2") -> None:
    run_id = record(store, outputs=[{}, {"cost": 0.5}])  # the follow-up made it pass
    store.add_step(run_id, 0, "follow_up_intent", status=template, ts_ms=1,
                   detail={"reason": reason})


def test_when_no_steering_candidate_survives_a_mined_line_waits_for_the_owner(world):
    for _ in range(50):
        record(world.runs, outputs=[{}])
    for _ in range(15):
        _record_with_follow_up(world.runs, "the change weakens the checks (C1 tests/test_a.py)")

    done = world.trainer.consider(CELL)

    assert done.startswith("text candidate") and done.endswith("(proposed)"), done
    [change] = [c for c in world.registry.store.list() if c.target.endswith("#candidate")]
    assert change.state.value == "proposed"
    assert "it changes what coding agents are told" in change.core_reasons
    assert "spared the follow-up orders of 15 runs" in change.reason
    assert world.policies.policy(CELL, CANDIDATE) is None  # nothing changes before approval
    assert world.trainer.consider(CELL) == "a text candidate waits for the owner"

    world.registry.approve(change.id)

    assert world.trainer.consider(CELL) == "trial goes on"
    [claim] = world.trainer.claims()
    assert (claim["branch"], claim["target"], claim["outcome"]) == ("B", "p", "")
    assert world.policies.policy(CELL, CANDIDATE).domain_block.startswith("Keep every")
