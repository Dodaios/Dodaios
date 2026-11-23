"""Changes that are decided by measurement: candidate, admit, decline, settle, the stack."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from dodaios.rsi import params
from dodaios.rsi.gate.evidence import Effect, Evidence, Verdict
from dodaios.self_change import (
    GATE,
    MEASUREMENT,
    OWNER,
    Draft,
    SelfChangeError,
    SelfChangeRegistry,
    StaleEvidence,
    State,
    Surface,
)
from dodaios.self_change.registry import FileHandler

LIMIT = "recall.turn_limit"


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.notices: list[dict[str, Any]] = []
        self.moves: list[tuple[str, str]] = []
        self.audit: list[dict[str, Any]] = []
        self.params = params.install(tmp_path)
        self.registry = SelfChangeRegistry(
            tmp_path,
            notify=self.notices.append,
            audit=lambda: self,
            changed=lambda change: self.moves.append((change.id, change.state.value)),
        )
        self.registry.register_handler(Surface.PARAMETER, self.params)
        self.registry.register_handler(
            Surface.INSTRUCTIONS, FileHandler(lambda _t: tmp_path / "instructions.md")
        )

    def record(self, entry: dict[str, Any]) -> None:  # the audit log's interface
        self.audit.append(entry)

    def candidate(self, value: int, name: str = LIMIT) -> Any:
        text = params.text_for(params.INDEX.by_name(name), value)
        return self.registry.propose(Draft(Surface.PARAMETER, name, text, author="tuner"))


@pytest.fixture
def world(tmp_path: Path):
    built = World(tmp_path)
    yield built
    built.registry.close()
    params.install(None)


def better(baseline: str = "fp_now", **more: Any) -> Evidence:
    return Evidence(
        Verdict.ACCEPT,
        target=Effect("recall", diff=0.06, low=0.01, high=0.11, n=100),
        baseline=baseline,
        split="select",
        alpha=0.06,
        **more,
    )


def worse(reason: str = "worse on new tasks") -> Evidence:
    target = Effect("recall", diff=-0.04, low=-0.09, high=-0.01, n=39)
    return Evidence(Verdict.REJECT, target=target, split="guard", reason=reason)


# ---------------------------------------------------------------- candidate


def test_a_candidate_is_recorded_not_applied_and_nobody_is_asked(world: World) -> None:
    change = world.candidate(4)
    assert (change.state, change.waits) == (State.PROPOSED, MEASUREMENT)
    assert params.get(LIMIT) == 6
    assert world.notices == []  # the loop never writes into the conversation
    assert world.moves == [(change.id, "proposed")]
    assert world.audit[-1]["outcome"] == "candidate"
    assert world.registry.candidates() == [change]
    summary = world.registry.summary()
    assert (summary["candidates"], summary["waiting"]) == (1, 0)
    with pytest.raises(SelfChangeError, match="measurement"):
        world.registry.approve(change.id)  # no approval stands in for a measurement
    assert params.get(LIMIT) == 6


def test_a_malformed_candidate_is_blocked_without_a_notice(world: World) -> None:
    blocked = world.registry.propose(
        Draft(Surface.PARAMETER, LIMIT, '{"base":6,"value":99}', author="tuner")
    )
    assert blocked.state is State.BLOCKED and world.notices == []


# ------------------------------------------------------------ admit, decline


def test_accepting_evidence_lets_a_candidate_in_on_trial(world: World) -> None:
    change = world.candidate(4)
    admitted = world.registry.admit(change.id, better(), live="fp_now")
    assert admitted.state is State.TRIAL and params.get(LIMIT) == 4
    assert world.notices == []
    (stored,) = world.registry.store.evidence(change.id)
    assert (stored["step"], stored["verdict"]) == ("admit", "accept")
    assert stored["evidence"]["target"]["n"] == 100
    assert world.registry.detail(change.id)["evidence"] == [stored]
    assert world.audit[-1]["origin_detail"] == GATE
    with pytest.raises(SelfChangeError):
        world.registry.admit(change.id, better(), live="fp_now")  # only a candidate is admitted


def test_evidence_measured_against_an_older_state_admits_nothing(world: World) -> None:
    first, second = world.candidate(4), world.candidate(8, "recall.fetch_factor")
    world.registry.admit(first.id, better("fp_before"), live="fp_before")
    with pytest.raises(StaleEvidence):
        # Measured while the first change was not in yet: the two were never measured together.
        world.registry.admit(second.id, better("fp_before"), live="fp_after_first")
    assert world.registry.store.get(second.id).state is State.PROPOSED
    assert params.get("recall.fetch_factor") == 4
    assert world.registry.store.evidence(second.id) == []


def test_a_candidate_whose_target_moved_is_blocked_not_applied(world: World) -> None:
    first, second = world.candidate(4), world.candidate(5)
    world.registry.admit(first.id, better(), live="fp_now")
    late = world.registry.admit(second.id, better("fp_2"), live="fp_2")
    assert late.state is State.BLOCKED and "target changed" in late.note
    assert params.get(LIMIT) == 4


def test_only_matching_evidence_moves_a_candidate(world: World) -> None:
    change = world.candidate(4)
    with pytest.raises(SelfChangeError):
        world.registry.admit(change.id, worse(), live="fp_now")
    with pytest.raises(SelfChangeError):
        world.registry.decline(change.id, better())
    declined = world.registry.decline(change.id, worse("no gain on the select tasks"))
    assert declined.state is State.BLOCKED and declined.note == "no gain on the select tasks"
    assert params.get(LIMIT) == 6 and world.notices == []
    assert world.registry.store.evidence(change.id)[0]["step"] == "decline"


# -------------------------------------------------------------------- settle


def test_a_second_measurement_confirms_a_change_or_takes_it_back(world: World) -> None:
    kept, popped = world.candidate(4), world.candidate(8, "recall.fetch_factor")
    world.registry.admit(kept.id, better("fp_0"), live="fp_0")
    world.registry.admit(popped.id, better("fp_1"), live="fp_1")

    held = Evidence(Verdict.ACCEPT, target=Effect("recall", 0.05, -0.02, 0.12, 39), split="guard")
    assert world.registry.settle(kept.id, held).state is State.LIVE
    assert world.registry.settle(kept.id, held).state is State.LIVE  # a live one stays

    gone = world.registry.settle(popped.id, worse())
    assert gone.state is State.REVERTED and gone.note == "worse on new tasks"
    assert params.get("recall.fetch_factor") == 4 and params.get(LIMIT) == 4
    assert world.params.read("recall.fetch_factor") is None  # the exact state from before
    assert world.notices == []
    steps = [e["step"] for e in world.registry.store.evidence(popped.id)]
    assert steps == ["admit", "settle"]
    with pytest.raises(SelfChangeError):
        world.registry.settle(popped.id, held)  # nothing in effect to settle


def test_taking_a_change_back_also_takes_back_what_was_built_on_it(world: World) -> None:
    first = world.candidate(4)
    world.registry.admit(first.id, better("fp_0"), live="fp_0")
    second = world.candidate(3)
    world.registry.admit(second.id, better("fp_1"), live="fp_1")
    assert params.get(LIMIT) == 3
    world.registry.settle(first.id, worse())
    states = {c.id: c.state for c in world.registry.store.list()}
    assert states == {first.id: State.REVERTED, second.id: State.REVERTED}
    assert params.get(LIMIT) == 6


def test_what_the_owner_made_is_not_decided_by_measurement(world: World) -> None:
    mine = world.registry.propose(
        Draft(Surface.INSTRUCTIONS, "instructions", "Answer briefly.", author=OWNER)
    )
    assert mine.waits == ""
    if mine.state is State.PROPOSED:
        mine = world.registry.approve(mine.id)
    with pytest.raises(SelfChangeError, match="owner"):
        world.registry.settle(mine.id, worse())


# --------------------------------------------------------------------- stack


def test_the_stack_lists_what_was_learned_in_the_order_it_went_in(world: World) -> None:
    a, b = world.candidate(4), world.candidate(8, "recall.fetch_factor")
    c = world.candidate(2, "lessons.recall_limit")
    world.registry.admit(b.id, better("fp_0"), live="fp_0")
    world.registry.admit(a.id, better("fp_1"), live="fp_1")
    assert world.registry.learned_ids() == (b.id, a.id)
    stack = world.registry.stack()
    assert [row["id"] for row in stack] == [b.id, a.id]
    assert all(row["since_ms"] > 0 and row["evidence"][0]["step"] == "admit" for row in stack)
    world.registry.settle(b.id, worse())
    assert world.registry.learned_ids() == (a.id,)
    assert [x.id for x in world.registry.candidates()] == [c.id]
    states = [state for _, state in world.moves]
    assert states.count("trial") == 2 and states[-1] == "reverted"


def test_evidence_cannot_be_edited_and_an_older_file_gains_the_new_parts(tmp_path: Path) -> None:
    old = sqlite3.connect(tmp_path / "self_changes.db")
    old.executescript(
        """
        CREATE TABLE changes (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
            surface TEXT NOT NULL, target TEXT NOT NULL, version INTEGER NOT NULL,
            before_text TEXT, after_text TEXT, diff TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL, turn TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL, core INTEGER NOT NULL DEFAULT 0,
            core_reasons TEXT NOT NULL DEFAULT '[]', gate TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT '', ref TEXT NOT NULL DEFAULT '',
            created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL
        );
        INSERT INTO changes (id, surface, target, version, author, state, created_ms, updated_ms)
        VALUES ('old1', 'skill', 'notes', 1, 'agent', 'live', 1, 1);
        """
    )
    old.close()
    registry = SelfChangeRegistry(tmp_path)  # the app after an update opens the old file
    kept = registry.store.get("old1")
    assert kept is not None and (kept.state, kept.waits) == (State.LIVE, "")
    registry.store.record_evidence("old1", "settle", "accept", "{}")
    for statement in ("UPDATE evidence SET verdict = 'x'", "DELETE FROM evidence"):
        with pytest.raises(sqlite3.Error, match="append-only"):
            registry.store._db().execute(statement)
    registry.close()
