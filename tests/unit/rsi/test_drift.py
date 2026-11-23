"""New models and CLI versions: which cell follows which, inheritance, and the drift note."""

from __future__ import annotations

import random
from typing import Any

from dodaios.rsi import bind, drift
from dodaios.rsi.policy import ACTIVE, DEFAULT, Policy, PolicyStore, target_for

OLD = "backend|claude-opus-5-5|claude-cli 2.1"
NEW = "backend|claude-opus-5-5|claude-cli 2.2"


def test_a_cell_follows_the_closest_earlier_line_of_the_same_domain_model_and_runner():
    known = [
        OLD, "backend|claude-opus-5-5|claude-cli 1.9", "backend|claude-opus-5-5|claude-cli 2.3",
        "frontend|claude-opus-5-5|claude-cli 2.1", "backend|claude-haiku|claude-cli 2.1",
        "backend|claude-opus-5-5|codex-cli 2.1", "backend|claude-opus-5-5|claude-cli 2.10",
    ]
    assert drift.predecessor(NEW, known) == OLD
    assert drift.predecessor("backend|claude-opus-5-5|claude-cli 2.11", known) == (
        "backend|claude-opus-5-5|claude-cli 2.10"
    )
    assert drift.predecessor("backend|claude-opus-5-5|claude-cli 1.0", known) == ""
    assert drift.predecessor("other|m|claude-cli", known) == ""


def test_a_new_epoch_runs_under_its_predecessors_policy_until_it_has_its_own(tmp_path):
    store = PolicyStore(tmp_path / "rsi.db")
    try:
        assert bind.active_policy(store, NEW) == DEFAULT
        store.write(target_for(OLD, ACTIVE), Policy(p_max=1).to_text())
        assert bind.active_policy(store, NEW) == Policy(p_max=1)
        assert bind.bind(store, NEW, "root-1").policy == Policy(p_max=1)
        store.write(target_for(NEW, ACTIVE), Policy(p_max=0).to_text())
        assert bind.active_policy(store, NEW) == Policy(p_max=0)
    finally:
        store.close()


def _runs(cell: str, n: int, pass_share: float, seed: int, start: int, cost: float = 0.1
          ) -> list[dict[str, Any]]:
    rng = random.Random(seed)  # noqa: S311 - test data
    domain, model, harness = cell.split("|")
    runner, line = harness.split(" ")
    return [{
        "run_id": f"{cell}-{i}", "root_span_id": f"{cell}-{i}", "state": "ended",
        "verdict": "verified" if rng.random() < pass_share else "unverified",
        "primary_domain": domain, "model_requested": model, "runner": runner,
        "harness_line": line, "started_ms": start + i, "cost_usd": cost, "wall_ms": 0,
        "follow_ups": 0, "gate_status": "clean",
    } for i in range(n)]


def test_one_note_per_new_epoch_with_enough_runs():
    runs = _runs(OLD, 60, 0.9, 1, 0) + _runs(NEW, 45, 0.9, 2, 10_000)
    [note] = drift.notes(runs, samples=300)
    assert (note.cell, note.previous, note.runs) == (NEW, OLD, drift.N_EPOCH)
    assert note.recommendation == "no difference shown; nothing to do"
    assert drift.notes(_runs(OLD, 60, 0.9, 1, 0) + _runs(NEW, 30, 0.9, 2, 10_000)) == []


def test_a_worse_new_version_is_named_and_nothing_is_switched():
    runs = _runs(OLD, 60, 0.95, 1, 0) + _runs(NEW, 40, 0.5, 2, 10_000)
    [note] = drift.notes(runs, samples=300)
    assert note.pass_diff < 0
    assert "pin the earlier model or CLI version" in note.recommendation


def test_a_costlier_new_version_is_worth_a_look():
    runs = _runs(OLD, 60, 0.9, 1, 0) + _runs(NEW, 40, 0.9, 1, 10_000, cost=0.5)
    [note] = drift.notes(runs, samples=300)
    assert note.cost_ratio > 1.25
    assert "costs over a quarter more" in note.recommendation
