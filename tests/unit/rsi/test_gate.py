"""The measured gate: its rules, its error budget, and whole decisions in a sandbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dodaios.rsi import night as nights
from dodaios.rsi import params
from dodaios.rsi.bench.model import Domain, Source, Split
from dodaios.rsi.bench.store import BenchStore
from dodaios.rsi.gate.alpha import ALPHA, MAX_DECISIONS, AlphaLedger
from dodaios.rsi.gate.evidence import Effect, Evidence, Verdict
from dodaios.rsi.gate.rules import Compared, admit_verdict, keep_verdict
from dodaios.rsi.sequential import Interval
from dodaios.self_change import Draft, State, Surface

from . import fakeworld
from .fakeworld import BLIND, LIMIT, SCORE


def compared(mean: float, low: float, high: float, n: int = 100, cost: float = 1.0) -> Compared:
    return Compared("recall", Interval(mean, low, high, n), 100.0, 100.0 * cost)


def admit(target: Compared, *others: Compared) -> Evidence:
    return admit_verdict(target, tuple(others), alpha=0.05, baseline="fp", split="select")


# -------------------------------------------------------------------- rules


def test_a_candidate_goes_in_when_it_is_clearly_better_or_as_good_and_cheaper() -> None:
    assert admit(compared(0.08, 0.02, 0.15)).verdict is Verdict.ACCEPT
    assert admit(compared(0.08, 0.02, 0.15, cost=9.0)).verdict is Verdict.ACCEPT  # quality first
    capped = Compared("coding", Interval(0.08, 0.02, 0.15, 100), 100.0, 130.0)
    assert admit(capped).verdict is Verdict.REJECT  # a domain without an entry: 10 % at most
    cheaper = admit(compared(0.0, -0.03, 0.04, cost=0.7))
    assert cheaper.accepted and "30% cheaper" in cheaper.reason
    assert cheaper.target == Effect("recall", 0.0, -0.03, 0.04, 100, cost_diff=-30.0)


@pytest.mark.parametrize(
    ("found", "why"),
    [
        (compared(-0.09, -0.2, -0.02), "worse"),
        (compared(0.01, -0.05, 0.07, cost=1.2), "no gain, and it costs 20% more"),
        (compared(0.0, -0.06, 0.06, cost=0.7), "no clear difference"),  # cheaper, not sure as good
        (compared(0.0, -0.03, 0.04, cost=0.97), "no clear difference"),  # as good, not cheaper
    ],
)
def test_a_candidate_stays_out_otherwise(found: Compared, why: str) -> None:
    evidence = admit(found)
    assert evidence.verdict is Verdict.REJECT and why in evidence.reason


def test_too_few_tasks_decide_nothing_and_another_domain_must_not_lose() -> None:
    few = admit(compared(0.5, 0.2, 0.8, n=12))
    assert few.verdict is Verdict.UNDECIDED and "30 are needed" in few.reason
    other = Compared("skill", Interval(-0.1, -0.2, -0.01, 80), 0.0, 0.0)
    hurt = admit(compared(0.08, 0.02, 0.15), other)
    assert hurt.verdict is Verdict.REJECT and hurt.reason == "it makes skill worse"
    assert hurt.others[0].domain == "skill"


def test_a_change_in_effect_stays_when_it_shows_no_harm_and_goes_when_its_gain_is_gone() -> None:
    assert keep_verdict(compared(0.03, -0.1, 0.16, n=39), None).verdict is Verdict.ACCEPT
    assert keep_verdict(compared(-0.2, -0.4, -0.01, n=39), None).verdict is Verdict.REJECT
    unsure = compared(-0.03, -0.2, 0.14, n=39)
    assert keep_verdict(unsure, None).verdict is Verdict.UNDECIDED
    assert keep_verdict(unsure, compared(0.05, -0.01, 0.11)).verdict is Verdict.UNDECIDED
    gone = keep_verdict(unsure, compared(-0.01, -0.07, 0.05))
    assert gone.verdict is Verdict.REJECT and "gone" in gone.reason
    assert keep_verdict(compared(0.4, 0.1, 0.7, n=9), None).verdict is Verdict.UNDECIDED
    dear = Compared("coding", Interval(0.0, -0.1, 0.1, 39), 100.0, 150.0)
    assert keep_verdict(dear, None).verdict is Verdict.UNDECIDED


# ------------------------------------------------------------- error budget


def test_a_split_decides_a_limited_number_of_times_until_new_tasks_arrive(tmp_path: Path) -> None:
    store = BenchStore(tmp_path / "bench.db")
    ledger = AlphaLedger(store)
    select = (Domain.RECALL, Split.SELECT)
    assert ledger.left(*select, groups=40) == MAX_DECISIONS
    levels = [ledger.spend(*select, groups=40) for _ in range(MAX_DECISIONS)]
    assert levels == [ALPHA] * MAX_DECISIONS and ledger.left(*select, groups=40) == 0
    assert ledger.spend(*select, groups=40) == 0.0  # used up: no further decision
    assert ledger.spend(*select, groups=44) == 0.0  # too few new tasks
    assert ledger.spend(Domain.RECALL, Split.GUARD, groups=10) == ALPHA  # its own budget
    assert ledger.left(*select, groups=50) == MAX_DECISIONS  # a quarter more: a new budget
    assert ledger.spend(*select, groups=50) == ALPHA
    assert ledger.state(*select) == {"epoch": 2, "decisions": 1, "groups": 50}
    store.close()
    again = AlphaLedger(BenchStore(tmp_path / "bench.db"))  # the count survives a restart
    assert again.left(*select, groups=50) == MAX_DECISIONS - 1


# ---------------------------------------------- whole decisions, sandbox


@pytest.fixture
def box(tmp_path: Path, monkeypatch):
    built = fakeworld.sandbox(tmp_path, monkeypatch, learners=())
    yield built
    built.close()


def propose(box: Any, name: str, value: Any) -> Any:
    text = params.text_for(params.INDEX.by_name(name), value)
    return box.registry.propose(Draft(Surface.PARAMETER, name, text, author="tuner"))


def learned(box: Any, name: str, value: Any) -> None:
    """Put a value in effect the way a past night would have left it."""
    box.store.write(name, params.text_for(params.INDEX.by_name(name), value))


def test_a_better_value_is_measured_let_in_and_then_confirmed(box) -> None:
    gate, splits = box.night.gate, fakeworld.splits()
    learned(box, SCORE, BLIND)  # a bad value is in effect: nothing is looked up
    before = gate.live().id
    change = propose(box, SCORE, 0.0)
    decision = gate.consider(change)
    assert decision.outcome == "admitted", decision.evidence.reason
    found = decision.evidence
    assert found.target.low > 0.3 and found.target.n == splits["select"]
    assert (found.split, found.baseline, found.alpha) == ("select", before, ALPHA)
    assert params.get(SCORE) == 0.0
    assert box.registry.store.get(change.id).state is State.TRIAL
    assert gate.live().id != before  # the assistant is another one now

    (kept,) = gate.settle_all()
    assert kept.outcome == "kept" and kept.evidence.split == "guard"
    assert kept.evidence.target.n == splits["guard"]
    assert box.registry.store.get(change.id).state is State.LIVE
    steps = [e["step"] for e in box.registry.store.evidence(change.id)]
    assert steps == ["admit", "settle"]
    # Every run is on record under the state it ran in: the baseline was the live state.
    assert len(box.bench.results(found.baseline)) == splits["select"]


def test_a_value_as_good_and_cheaper_goes_in_on_the_cost_rule(box) -> None:
    decision = box.night.gate.consider(propose(box, LIMIT, 2))
    assert decision.outcome == "admitted"
    assert decision.evidence.target.diff == 0.0 and decision.evidence.target.low > -0.05
    assert "67% cheaper" in decision.evidence.reason and params.get(LIMIT) == 2


def test_a_worse_value_and_one_without_effect_stay_out(box) -> None:
    gate = box.night.gate
    worse = gate.consider(propose(box, SCORE, BLIND))
    assert worse.outcome == "declined" and "worse" in worse.evidence.reason
    same = gate.consider(propose(box, "recall.fetch_factor", 12))
    assert same.outcome == "declined" and "no clear difference" in same.evidence.reason
    dearer = gate.consider(propose(box, LIMIT, 10))
    assert dearer.outcome == "declined" and "costs 67% more" in dearer.evidence.reason
    assert params.learned() == {}
    assert {c.state for c in box.registry.store.list()} == {State.BLOCKED}


def test_a_change_that_does_harm_is_taken_back_with_its_exact_previous_value(box) -> None:
    gate = box.night.gate
    change = propose(box, SCORE, BLIND)
    lucky = Evidence(Verdict.ACCEPT, baseline=gate.live().id, reason="let in by mistake")
    box.registry.admit(change.id, lucky, live=gate.live().id)
    assert params.get(SCORE) == BLIND
    (decision,) = gate.settle_all()
    assert decision.outcome == "taken back" and "worse on" in decision.evidence.reason
    assert params.get(SCORE) == 0.0 and box.store.read(SCORE) is None
    assert box.registry.store.get(change.id).state is State.REVERTED
    assert box.registry.learned_ids() == ()


def test_candidates_are_decided_one_after_the_other_each_against_the_state_before_it(box) -> None:
    gate = box.night.gate
    learned(box, SCORE, BLIND)
    first = propose(box, SCORE, 0.0)
    second = propose(box, "recall.fetch_factor", 12)
    decisions = gate.consider_all()
    assert [d.change_id for d in decisions] == [first.id, second.id]
    assert [d.outcome for d in decisions] == ["admitted", "declined"]
    assert decisions[0].evidence.baseline != decisions[1].evidence.baseline
    assert decisions[0].public()["evidence"]["verdict"] == "accept"
    assert gate.consider_all() == []


def test_the_same_question_gives_the_same_answer_every_time(tmp_path: Path, monkeypatch) -> None:
    answers = []
    for run_number in (1, 2):
        box = fakeworld.sandbox(tmp_path / str(run_number), monkeypatch, learners=())
        try:
            decision = box.night.gate.consider(propose(box, LIMIT, 4))
            target = decision.evidence.target
            answers.append((decision.outcome, target.diff, target.low, target.high, target.n))
        finally:
            box.close()
    assert answers[0] == answers[1]  # the order of a comparison follows the question alone


def test_an_installation_without_tasks_of_its_own_measures_nothing_and_applies_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    box = fakeworld.sandbox(tmp_path, monkeypatch, learners=())
    home = nights.Night(box.registry, box.bench, lambda: {}, sources=(Source.MINED,))
    try:
        change = propose(box, LIMIT, 2)
        decision = home.gate.consider(change)
        assert decision.outcome == "waiting"
        assert decision.evidence.verdict is Verdict.UNMEASURED
        assert "no tasks yet" in decision.evidence.reason
        assert params.get(LIMIT) == 6
        assert box.registry.store.get(change.id).state is State.PROPOSED
        assert home.gate.check(change).verdict is Verdict.UNDECIDED
        assert not home.gate.can_decide(Domain.RECALL)
    finally:
        box.close()
