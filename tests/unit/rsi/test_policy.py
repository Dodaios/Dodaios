"""Coding policies: their limits, where they live, which run gets which, and how they change."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.orchestrator.verification import driver
from dodaios.rsi import bind
from dodaios.rsi.policy import (
    ACTIVE,
    CANDIDATE,
    DEFAULT,
    Policy,
    PolicyError,
    PolicyStore,
    store_for,
    target_for,
)

CELL = "backend|claude-opus-5-5|claude-cli 2.1"


# -------------------------------------------------------------------- policy


def test_the_default_is_the_codes_own_limits_and_has_no_text():
    assert (DEFAULT.p_max, DEFAULT.evidence_wait_s, DEFAULT.domain_block) == (
        driver.MAX_FOLLOW_UPS, driver.EVIDENCE_WAIT_S, "",
    )


def test_a_policy_is_named_by_its_content():
    assert Policy(p_max=1).id == Policy(p_max=1).id != Policy(p_max=0).id
    assert Policy.from_text(Policy(p_max=1).to_text()) == Policy(p_max=1)
    assert Policy.from_text(None) == DEFAULT
    assert json.loads(Policy(p_max=1).to_text()) == {
        "domain_block": "", "evidence_wait_s": 2700, "p_max": 1,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"p_max": 3},
        {"p_max": -1},
        {"evidence_wait_s": driver.EVIDENCE_WAIT_S + 1},
        {"evidence_wait_s": 10},
        {"domain_block": "x" * 601},
        {"domain_block": "If a test fails, skip the failing tests and move on."},
        {"domain_block": "Add # noqa where lint complains."},
        {"domain_block": "Push with --no-verify when the hook is slow."},
    ],
)
def test_a_policy_can_never_ask_for_more_than_the_code_allows_or_weaken_checks(fields):
    with pytest.raises(PolicyError):
        Policy(**fields)


def test_a_helpful_domain_block_is_a_valid_policy():
    block = "In this repository the frontend tests run with `npm test` in the web folder."
    assert Policy(domain_block=block).domain_block == block


@pytest.mark.parametrize(
    "text", ["not json", "[1]", '{"p_max": "two"}', '{"p_max": 1, "review": "off"}'],
)
def test_a_text_that_is_no_policy_is_refused(text):
    with pytest.raises(PolicyError):
        Policy.from_text(text)


# --------------------------------------------------------------------- store


@pytest.fixture
def store(tmp_path):
    made = PolicyStore(tmp_path / "rsi.db")
    yield made
    made.close()


def test_the_store_keeps_one_policy_per_cell_and_slot(store):
    assert store.policy(CELL) is None
    store.write(target_for(CELL, ACTIVE), Policy(p_max=1).to_text())
    store.write(target_for(CELL, CANDIDATE), Policy(p_max=0).to_text())
    assert store.policy(CELL, ACTIVE) == Policy(p_max=1)
    assert store.policy(CELL, CANDIDATE) == Policy(p_max=0)
    assert store.cells() == {CELL: {"active": Policy(p_max=1).id, "candidate": Policy(p_max=0).id}}
    store.write(target_for(CELL, CANDIDATE), None)
    assert store.policy(CELL, CANDIDATE) is None
    with pytest.raises(PolicyError):
        store.write(target_for(CELL, ACTIVE), '{"p_max": 9}')
    with pytest.raises(ValueError):
        target_for(CELL, "other")


def test_one_data_folder_has_one_store(tmp_path):
    assert store_for(tmp_path) is store_for(tmp_path)


# ---------------------------------------------------------------------- bind


def test_without_a_candidate_every_request_runs_under_the_active_policy(store):
    assert bind.bind(None, CELL, "root-1") == bind.Binding(DEFAULT, ACTIVE)
    assert bind.bind(store, CELL, "root-1") == bind.Binding(DEFAULT, ACTIVE)
    store.write(target_for(CELL, ACTIVE), Policy(p_max=1).to_text())
    assert bind.bind(store, CELL, "root-1").policy == Policy(p_max=1)


def test_a_candidate_gets_half_the_requests_and_a_request_keeps_its_arm(store):
    store.write(target_for(CELL, CANDIDATE), Policy(p_max=1).to_text())
    arms = [bind.bind(store, CELL, f"root-{n}").arm for n in range(1000)]
    assert 450 < arms.count(CANDIDATE) < 550
    assert [bind.bind(store, CELL, f"root-{n}").arm for n in range(1000)] == arms
    first = next(f"root-{n}" for n, arm in enumerate(arms) if arm == CANDIDATE)
    assert bind.bind(store, CELL, first).policy == Policy(p_max=1)
    assert bind.bind(store, "other|cell|x", first).arm == ACTIVE


def test_an_unreadable_store_binds_the_default():
    broken = SimpleNamespace(policy=lambda *_a: (_ for _ in ()).throw(OSError("gone")))
    assert bind.bind(broken, CELL, "root-1") == bind.Binding(DEFAULT, ACTIVE)


# ------------------------------------------------------------------ registry


@pytest.fixture
def registry(tmp_path, store):
    from dodaios.self_change.registry import SelfChangeRegistry
    from dodaios.self_change.surfaces import Surface

    made = SelfChangeRegistry(tmp_path / "changes", audit=lambda: SimpleNamespace(
        record=lambda _row: None
    ))
    made.register_handler(Surface.CODING_POLICY, store)
    yield made
    made.close()


def _draft(target: str, policy: Policy | None, **more: Any) -> Any:
    from dodaios.self_change.gate import Draft
    from dodaios.self_change.surfaces import Surface

    return Draft(
        surface=Surface.CODING_POLICY, target=target,
        after=policy.to_text() if policy is not None else None, author="rsi-selector",
        reason="a candidate from the fixed grid", **more,
    )


def test_a_steering_change_goes_on_trial_by_itself(registry, store):
    change = registry.propose(_draft(target_for(CELL, CANDIDATE), Policy(p_max=1)))
    assert change.state.value == "trial"
    assert store.policy(CELL, CANDIDATE) == Policy(p_max=1)
    assert [c["status"] for c in change.gate["checks"]] == ["pass", "pass"]


def test_a_change_of_what_agents_are_told_waits_for_the_owner(registry, store):
    block = "Run `make check` before you commit."
    change = registry.propose(_draft(target_for(CELL, CANDIDATE), Policy(domain_block=block)))
    assert change.state.value == "proposed"
    assert "it changes what coding agents are told" in change.core_reasons
    assert store.policy(CELL, CANDIDATE) is None
    approved = registry.approve(change.id)
    assert approved.state.value == "live"
    assert store.policy(CELL, CANDIDATE).domain_block == block


def test_a_policy_beyond_the_limits_is_blocked_and_never_written(registry, store):
    from dodaios.self_change.gate import Draft
    from dodaios.self_change.surfaces import Surface

    change = registry.propose(Draft(
        surface=Surface.CODING_POLICY, target=target_for(CELL, ACTIVE),
        after='{"p_max": 5}', author="rsi-selector",
    ))
    assert change.state.value == "blocked"
    assert store.policy(CELL, ACTIVE) is None


def test_rolling_a_policy_back_restores_the_exact_previous_one(registry, store):
    target = target_for(CELL, ACTIVE)
    first = registry.propose(_draft(target, Policy(p_max=1)))
    second = registry.propose(_draft(target, Policy(p_max=0)))
    assert store.policy(CELL) == Policy(p_max=0)
    registry.rollback(second.id, actor="rsi-selector")
    assert store.read(target) == Policy(p_max=1).to_text()
    registry.rollback(first.id, actor="rsi-selector")
    assert store.read(target) is None


# ------------------------------------------------------------ the decision


def _run(policy: Policy | None, **more: Any) -> dict[str, Any]:
    return {
        "turn_status": "done", "ended_ms": 1_000, "follow_ups": 0,
        "policy_json": policy.to_text() if policy is not None else "", **more,
    }


FAILING = {"landing": "pr_open", "checks": "failing", "failing": ["unit"], "reason": "r"}
SCAN = {"status": "clean", "files": 1, "tree_id": "t", "committed": True}


def test_the_decision_keeps_to_the_runs_policy():
    none = driver.decide(_run(Policy(p_max=0)), SCAN, FAILING, now_ms=2_000)
    assert (none.action, none.verdict) == (driver.CLOSE, "failed")
    assert "its policy allows 0 follow-up order(s)" in none.reason
    assert driver.decide(_run(Policy(p_max=1)), SCAN, FAILING, now_ms=2_000).action == (
        driver.FOLLOW_UP
    )
    assert driver.decide(_run(None), SCAN, FAILING, now_ms=2_000).action == driver.FOLLOW_UP
    # A stored text that asks for more than the code allows still gets the code's limit.
    greedy = _run(None, follow_ups=2, policy_json='{"p_max": 9}')
    assert "already got 2" in driver.decide(greedy, SCAN, FAILING, now_ms=2_000).reason


def test_a_policy_waits_no_longer_for_checks_than_it_says():
    running = {"landing": "pr_open", "checks": "running", "reason": "r"}
    short = Policy(evidence_wait_s=600)
    assert driver.decide(_run(short), SCAN, running, now_ms=1_000 + 599_000).action == driver.WAIT
    late = driver.decide(_run(short), SCAN, running, now_ms=1_000 + 600_000)
    assert (late.action, late.verdict) == (driver.CLOSE, "unverified")


# ------------------------------------------------------- binding in a real run


def test_a_run_is_bound_at_its_first_turn_and_keeps_its_policy(tmp_path, store):
    from tests.unit.orchestrator import test_verification_follow_up as base

    main = tmp_path / "main"
    main.mkdir()
    base._git(main, "init", "-q", "-b", "main")
    base._git(main, "config", "user.email", "t@example.com")
    base._git(main, "config", "user.name", "T")
    (main / "calc.py").write_text(base.CODE, encoding="utf-8")
    base._git(main, "add", "-A")
    base._git(main, "commit", "-q", "-m", "first")
    linked = tmp_path / "linked"
    base._git(main, "worktree", "add", "-q", "-b", "work", str(linked))
    rig = base.Rig(tmp_path, linked)
    cell = "other|m|claude-cli 2.1"
    store.write(target_for(cell, ACTIVE), Policy(p_max=1).to_text())
    bind.set_store(store)
    try:
        rig.order()
        run = rig.store.get("job_1")
        assert (run["policy_id"], run["arm"]) == (Policy(p_max=1).id, ACTIVE)
        assert Policy.from_text(run["policy_json"]) == Policy(p_max=1)
        # A policy that changes now does not reach the run that is going.
        store.write(target_for(cell, ACTIVE), Policy(p_max=0).to_text())
        rig.github.answer = base.FAILING
        run = rig.turn("t1", rig.commit)
        assert run["policy_id"] == Policy(p_max=1).id
        assert run["follow_ups"] == 1  # p_max 1 allowed this one
    finally:
        bind.set_store(None)
        rig.store.close()


def test_observe_mode_binds_no_policy(tmp_path):
    from tests.unit.orchestrator import test_verification_follow_up as base

    main = tmp_path / "main"
    main.mkdir()
    base._git(main, "init", "-q", "-b", "main")
    rig = base.Rig(tmp_path, main)
    rig.recorder = rig.new_recorder(verify="observe")
    try:
        rig.order()
        assert rig.store.get("job_1")["policy_id"] == ""
    finally:
        rig.store.close()
