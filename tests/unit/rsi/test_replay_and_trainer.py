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
        run_id,
        "s1",
        started_ms=start,
        root_span_id=f"root-{run_id}",
        primary_domain="backend",
        model_requested="claude-opus-5-5",
        policy_id=policy.id,
        policy_json=policy.to_text(),
        arm=ACTIVE,
    )
    total_cost, total_ms = 0.0, 0
    for k, out in enumerate(outputs):
        ended = start + 1000 * (k + 1) * 600
        store.add_step(
            run_id,
            k,
            "turn_finished",
            status="done",
            ts_ms=ended,
            detail={
                "cost_usd": out.get("cost", 0.10),
                "duration_ms": out.get("ms", 60_000),
                "tokens_out": 100,
            },
        )
        store.add_step(
            run_id,
            k,
            "gates",
            status="clean",
            ts_ms=ended + 1,
            detail={
                "added": out.get("added", 10),
                "deleted": 0,
            },
        )
        store.add_step(
            run_id,
            k,
            "evidence",
            status="merged/passing",
            ts_ms=ended + 1000 * out.get("settle_s", 60),
            detail={},
        )
        total_cost += out.get("cost", 0.10)
        total_ms += out.get("ms", 60_000)
    store.update_run(
        run_id,
        state="ended",
        verdict=verdict,
        verdict_reason=reason,
        follow_ups=len(outputs) - 1,
        cost_usd=total_cost,
        wall_ms=total_ms,
        churn_lines=outputs[-1].get("added", 10),
        gate_status=gate_status,
        runner="claude-cli",
        harness_line="2.1",
        turn_status="done",
    )
    return run_id


def rows(store: VerificationStore) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    return [(r, store.steps(r["run_id"])) for r in store.runs()]


# ------------------------------------------------------------------- replay


def test_a_run_inside_the_candidates_limits_replays_as_recorded(runs):
    record(runs, outputs=[{}])
    ((row, steps),) = rows(runs)
    assert replay.replay_run(row, steps, Policy(p_max=1)) == selector.metrics_of(row)


def test_a_run_that_needed_more_follow_ups_is_cut_where_one_was_due(runs):
    record(runs, outputs=[{"cost": 0.4, "ms": 120_000, "added": 30}, {"cost": 0.3, "ms": 60_000}])
    ((row, steps),) = rows(runs)
    cut = replay.replay_run(row, steps, Policy(p_max=0))
    assert cut is not None
    assert (cut.passed, cut.one, cut.p, cut.churn) == (0.0, 0.0, 0.0, 30.0)
    assert cut.cost == pytest.approx(0.4 + 0.001 * 120)


def test_a_shorter_wait_misses_checks_that_settled_later(runs):
    record(runs, outputs=[{"settle_s": 30 * 60}])
    ((row, steps),) = rows(runs)
    assert replay.replay_run(row, steps, Policy(evidence_wait_s=20 * 60)).passed == 0.0
    assert replay.replay_run(row, steps, Policy(evidence_wait_s=40 * 60)).passed == 1.0


def test_nothing_beyond_the_record_is_replayed(runs):
    record(runs, policy=Policy(p_max=1), outputs=[{}, {}])
    ((row, steps),) = rows(runs)
    assert replay.replay_run(row, steps, Policy(p_max=2)) is None
    assert replay.replay_run(row, steps, DEFAULT) is None


def test_a_record_without_each_turns_cost_cannot_be_cut(runs):
    run_id = record(runs, outputs=[{}, {}])
    runs.add_step(run_id, 0, "turn_finished:old", ts_ms=1, detail={})
    row = runs.get(run_id)
    steps = [s for s in runs.steps(run_id) if s["step"] != "turn_finished" or s["iteration"]]
    assert replay.replay_run(row, steps, Policy(p_max=0)) is None


def test_a_hold_cannot_be_replayed_and_the_record_only_bounds_its_gain(runs):
    for _ in range(45):
        record(runs, outputs=[{}])
    for _ in range(10):
        record(runs, outputs=[{}], verdict="failed")  # a follow-up order could have reached it
    for _ in range(5):
        record(runs, outputs=[{}], verdict="unverified")  # its checks never settled
    claim = selector.Claim(CELL, "A", "pass")

    found = replay.replay_hold(claim, rows(runs), Policy(hold=True))

    assert found.answer == "inconclusive"  # never "accept": the orders were never sent
    assert (found.runs, found.covered) == (60, 50)
    assert found.bounds["pass"]["max_rise"] == pytest.approx(10 / 60)
    assert "a canary has to show it" in found.reasons[0]
    # A hold that would wait longer for checks could reach the unverified runs too.
    short_run = [
        ({**r, "policy_json": Policy(evidence_wait_s=600).to_text()}, s) for r, s in rows(runs)
    ]
    longer = replay.replay_hold(claim, short_run, Policy(hold=True))
    assert longer.covered == 45
    assert longer.bounds["pass"]["max_rise"] == pytest.approx(15 / 60)


def test_a_hold_whose_best_case_is_short_of_branch_a_is_rejected_by_the_record(runs):
    for _ in range(57):
        record(runs, outputs=[{}])
    for _ in range(3):
        record(runs, outputs=[{}], verdict="failed")
    found = replay.replay_hold(selector.Claim(CELL, "A", "pass"), rows(runs), Policy(hold=True))
    assert found.answer == "reject"
    assert "at most 0.05" in found.reasons[0]


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


HELD = Policy(hold=True)


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
    # The grid only means something where the active policy holds its runs.
    policies.write(target_for(CELL, ACTIVE), HELD.to_text())
    yield SimpleNamespace(runs=runs, policies=policies, registry=registry, trainer=made)
    registry.close()
    policies.close()


def test_with_too_few_runs_nothing_is_proposed(world):
    record(world.runs, policy=HELD, outputs=[{}])
    assert world.trainer.consider(CELL) == "waiting for runs"
    assert set(world.policies.cells()[CELL]) == {ACTIVE}


# ------------------------------------------------- holding, learned like the rest


def _withheld(store: VerificationStore, policy: Policy = DEFAULT, **more: Any) -> str:
    """A run that was not held: a follow-up order was due, withheld, and the run failed."""
    run_id = record(store, policy=policy, outputs=[{}], verdict="failed", **more)
    store.add_step(
        run_id,
        0,
        "follow_up_withheld",
        status="T1",
        ts_ms=1,
        detail={
            "template": "T1",
            "reason": "the repository's checks fail (unit)",
        },
    )
    return run_id


def _factory_cell(store: VerificationStore, *, passing: int, withheld: int) -> None:
    for _ in range(passing):
        record(store, outputs=[{}])
    for _ in range(withheld):
        _withheld(store)


HOLD = Policy(hold=True)  # the factory's follow-up limits, held


@pytest.fixture
def factory(world):
    world.policies.write(target_for(CELL, ACTIVE), None)  # the factory policy: nothing held
    return world


def test_a_cell_that_does_not_hold_gets_holding_as_a_candidate(factory):
    _factory_cell(factory.runs, passing=50, withheld=15)

    done = factory.trainer.consider(CELL)

    assert done == f"candidate {HOLD.id} on trial", done
    assert factory.policies.policy(CELL, CANDIDATE) == HOLD
    assert (HOLD.p_max, HOLD.evidence_wait_s) == (DEFAULT.p_max, DEFAULT.evidence_wait_s)
    [claim] = factory.trainer.claims()
    assert (claim["branch"], claim["target"], claim["outcome"]) == ("A", "pass", "")
    [change] = [c for c in factory.registry.store.list() if c.target.endswith("#candidate")]
    assert (change.author, change.state.value, change.core) == ("rsi-selector", "trial", False)
    assert "cannot replay the follow-up orders" in change.reason
    [kept] = factory.registry.store.evidence(change.id)
    assert kept["step"] == "propose"
    assert kept["evidence"]["claim"] == {"branch": "A", "target": "pass"}
    assert kept["evidence"]["reference"] == DEFAULT.to_text()
    assert kept["evidence"]["replay"]["covered"] == 50
    assert factory.trainer.consider(CELL) == "trial goes on"


def test_a_hold_that_could_not_raise_the_pass_rate_enough_is_not_tried(factory):
    _factory_cell(factory.runs, passing=62, withheld=4)  # at most +0.06 even if all were fixed

    done = factory.trainer.consider(CELL)

    assert done.startswith("nothing proposed: even if every run"), done
    assert "at most 0.06" in done
    assert factory.policies.policy(CELL, CANDIDATE) is None
    assert factory.trainer.claims() == []


def test_the_hold_on_trial_splits_the_requests_and_only_its_arm_is_held(factory):
    from dodaios.orchestrator.verification.recorder import holds_policy
    from dodaios.rsi import bind

    _factory_cell(factory.runs, passing=50, withheld=15)
    factory.trainer.consider(CELL)
    bind.set_store(factory.policies)
    try:
        bound = [bind.binding_fields(CELL, f"root-{n}") for n in range(200)]
        again = [bind.binding_fields(CELL, f"root-{n}") for n in range(200)]
    finally:
        bind.set_store(None)
    assert {b["arm"] for b in bound} == {ACTIVE, CANDIDATE}
    held = [b for b in bound if b["arm"] == CANDIDATE]
    assert 70 <= len(held) <= 130
    assert all(b["policy_id"] == HOLD.id and holds_policy(b["policy_json"]) for b in held)
    assert all(
        b["policy_id"] == DEFAULT.id and not holds_policy(b["policy_json"])
        for b in bound
        if b["arm"] == ACTIVE
    )
    assert again == bound  # the same request always draws the same arm


def _hold_trial(world, *, held_pass: int, ref_pass: int = 42, cost: float = 0.10) -> None:
    """65 requests per arm after the hold went on trial."""
    _factory_cell(world.runs, passing=50, withheld=15)
    world.trainer.consider(CELL)
    later = int(time.time() * 1000) + 10_000
    for i in range(65):
        if i < held_pass:
            record(world.runs, policy=HOLD, outputs=[{"cost": cost}], started_ms=later)
        else:
            record(
                world.runs,
                policy=HOLD,
                outputs=[{"cost": cost}],
                verdict="failed",
                started_ms=later,
            )
        if i < ref_pass:
            record(world.runs, outputs=[{}], started_ms=later)
        else:
            _withheld(world.runs, started_ms=later)


def test_a_hold_that_passes_more_becomes_the_cells_policy_with_its_measurement(factory):
    _hold_trial(factory, held_pass=60)

    done = factory.trainer.consider(CELL)

    assert done == "trial ended: accept", done
    assert factory.policies.policy(CELL, ACTIVE) == HOLD
    assert factory.policies.policy(CELL, CANDIDATE) is None
    assert factory.trainer.claims()[0]["outcome"] == "accept"
    [change] = [c for c in factory.registry.store.list() if c.target.endswith("#active")]
    assert (change.state.value, change.author) == ("trial", "rsi-selector")
    [admit] = factory.registry.store.evidence(change.id)
    assert (admit["step"], admit["verdict"]) == ("admit", "accept")
    found = admit["evidence"]
    assert found["claim"] == {"branch": "A", "target": "pass"}
    assert found["target"]["metric"] == "pass"
    assert found["target"]["diff"] == pytest.approx(60 / 65 - 42 / 65)
    assert found["target"]["low"] > 0
    assert (found["target"]["n"], found["target"]["n_reference"]) == (65, 65)
    assert found["arms"]["candidate"]["pass"] == pytest.approx(60 / 65)
    assert found["arms"]["reference"]["pass"] == pytest.approx(42 / 65)
    # Once the cell holds, the steering grid is what comes next, never another hold.
    assert not factory.trainer.consider(CELL).startswith(f"candidate {HOLD.id}")


def test_a_hold_that_does_not_pass_more_is_rejected_and_not_tried_again_soon(factory):
    _hold_trial(factory, held_pass=63, ref_pass=62)  # +0.015: not the 0.10 branch A asks for

    assert factory.trainer.consider(CELL) == "trial ended: reject"
    assert factory.policies.policy(CELL, ACTIVE) is None  # still the factory policy
    assert factory.policies.policy(CELL, CANDIDATE) is None
    [change] = [
        c
        for c in factory.registry.store.list()
        if c.target.endswith("#candidate") and c.after is not None
    ]
    assert [e["step"] for e in factory.registry.store.evidence(change.id)] == [
        "propose",
        "decline",
    ]
    again = factory.trainer.consider(CELL)
    assert again == "nothing proposed: holding was tried here less than 28 days ago"
    factory.trainer._clock = lambda: time.time() + 29 * 86400
    assert factory.trainer.consider(CELL) == f"candidate {HOLD.id} on trial"


def test_a_hold_that_costs_past_the_budget_is_rejected(factory):
    _hold_trial(factory, held_pass=60, cost=0.5)
    assert factory.trainer.consider(CELL) == "trial ended: reject"
    assert factory.policies.policy(CELL, ACTIVE) is None


def test_a_weakened_check_under_a_new_hold_rolls_it_back(factory):
    _hold_trial(factory, held_pass=60)
    assert factory.trainer.consider(CELL) == "trial ended: accept"
    record(
        factory.runs,
        policy=HOLD,
        outputs=[{}],
        gate_status="violations",
        verdict="failed",
        started_ms=int(time.time() * 1000) + 60_000,
    )

    done = factory.trainer.consider(CELL)

    assert done.startswith(f"rolled back {HOLD.id}"), done
    assert factory.policies.policy(CELL, ACTIVE) is None
    assert factory.trainer.consider(CELL).startswith("nothing proposed: holding was tried")


def _cell_where_follow_ups_never_help(store: VerificationStore, n: int = 70) -> None:
    for i in range(n):
        if i % 7:
            record(store, policy=HELD, outputs=[{}])
        else:
            record(store, policy=HELD, outputs=[{}, {"cost": 0.5}], verdict="failed")


def test_a_candidate_the_replay_allows_goes_on_trial_with_its_claim_fixed(world):
    _cell_where_follow_ups_never_help(world.runs)
    done = world.trainer.consider(CELL)
    assert done == f"candidate {Policy(p_max=0, hold=True).id} on trial", done
    assert world.policies.policy(CELL, CANDIDATE) == Policy(p_max=0, hold=True)
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
        record(
            world.runs,
            policy=Policy(p_max=0, hold=True),
            outputs=[{"cost": 0.05}],
            started_ms=later,
        )
        record(world.runs, policy=HELD, outputs=[{"cost": 0.20}], started_ms=later)
    done = world.trainer.consider(CELL)
    assert done == "trial ended: accept", done
    assert world.policies.policy(CELL, ACTIVE) == Policy(p_max=0, hold=True)
    assert world.policies.policy(CELL, CANDIDATE) is None
    assert world.trainer.claims()[0]["outcome"] == "accept"


def test_a_canary_that_loses_ends_the_trial_and_keeps_the_active_policy(world):
    _cell_where_follow_ups_never_help(world.runs)
    world.trainer.consider(CELL)
    later = int(time.time() * 1000) + 10_000
    for i in range(65):
        record(
            world.runs,
            policy=Policy(p_max=0, hold=True),
            outputs=[{}],
            started_ms=later,
            verdict="failed" if i % 3 == 0 else "verified",
        )
        record(world.runs, policy=HELD, outputs=[{}], started_ms=later)
    assert world.trainer.consider(CELL) == "trial ended: reject"
    assert world.policies.policy(CELL, ACTIVE) == HELD
    assert world.policies.policy(CELL, CANDIDATE) is None


def test_the_first_weakened_check_under_a_new_policy_rolls_it_back(world):
    target = target_for(CELL, ACTIVE)
    world.registry.propose(trainer.Trainer._draft(target, Policy(p_max=1, hold=True), "accepted"))
    assert world.policies.policy(CELL, ACTIVE) == Policy(p_max=1, hold=True)
    record(
        world.runs,
        policy=Policy(p_max=1, hold=True),
        outputs=[{}],
        gate_status="violations",
        verdict="failed",
        started_ms=int(time.time() * 1000) + 5_000,
    )
    done = world.trainer.consider(CELL)
    assert done.startswith(f"rolled back {Policy(p_max=1, hold=True).id}")
    assert world.policies.policy(CELL, ACTIVE) == HELD


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
    run_id = record(store, policy=HELD, outputs=[{}, {"cost": 0.5}])  # the follow-up made it pass
    store.add_step(
        run_id, 0, "follow_up_intent", status=template, ts_ms=1, detail={"reason": reason}
    )


def _cell_where_one_line_was_missing(store: VerificationStore) -> None:
    for _ in range(50):
        record(store, policy=HELD, outputs=[{}])
    for _ in range(15):
        _record_with_follow_up(store, "the change weakens the checks (C1 tests/test_a.py)")


def test_when_no_steering_candidate_survives_a_mined_line_goes_on_trial_by_itself(world):
    _cell_where_one_line_was_missing(world.runs)

    done = world.trainer.consider(CELL)

    candidate = world.policies.policy(CELL, CANDIDATE)
    assert candidate is not None and candidate.domain_block.startswith("Keep every")
    assert done == f"candidate {candidate.id} on trial", done
    [change] = [c for c in world.registry.store.list() if c.target.endswith("#candidate")]
    assert (change.state.value, change.core, change.core_reasons) == ("trial", False, [])
    assert "spared the follow-up orders of 15 runs" in change.reason
    [claim] = world.trainer.claims()
    assert (claim["branch"], claim["target"], claim["outcome"]) == ("B", "p", "")
    [kept] = world.registry.store.evidence(change.id)
    assert kept["evidence"]["line"] == candidate.domain_block
    assert len(kept["evidence"]["cited"]) == 15
    assert world.trainer.consider(CELL) == "trial goes on"


def test_a_mined_line_is_measured_like_any_candidate(world):
    _cell_where_one_line_was_missing(world.runs)
    world.trainer.consider(CELL)
    line = world.policies.policy(CELL, CANDIDATE)
    later = int(time.time() * 1000) + 10_000
    for _ in range(65):
        record(world.runs, policy=line, outputs=[{}], started_ms=later)  # no follow-up needed
        run_id = record(world.runs, policy=HELD, outputs=[{}, {}], started_ms=later)
        world.runs.add_step(
            run_id, 0, "follow_up_intent", status="T2", ts_ms=1, detail={"reason": "C1"}
        )

    assert world.trainer.consider(CELL) == "trial ended: accept"
    assert world.policies.policy(CELL, ACTIVE) == line


def test_a_candidate_the_owner_let_in_by_hand_is_still_claimed_before_its_data(world):
    block = "Run `make check` before you commit."  # not a fixed line: the owner's call
    change = world.registry.propose(
        trainer.Trainer._draft(
            target_for(CELL, CANDIDATE),
            Policy(domain_block=block, hold=True),
            "by hand",
        )
    )
    assert change.state.value == "proposed"
    assert "it changes what coding agents are told" in change.core_reasons
    world.registry.approve(change.id)

    assert world.trainer.consider(CELL) == "trial goes on"
    [claim] = world.trainer.claims()
    assert (claim["branch"], claim["target"]) == ("B", "p")
