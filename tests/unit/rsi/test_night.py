"""The tuner and the night cycle, end to end in a sandbox."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import dodaios
from dodaios.learners.tuner import MIN_GAIN, Proposal, Trial, Tuner, neighbours
from dodaios.rsi import night as nights
from dodaios.rsi import params
from dodaios.rsi.bench.model import Domain
from dodaios.rsi.gate.alpha import MAX_DECISIONS
from dodaios.rsi.gate.evidence import Evidence, Verdict
from dodaios.rsi.params import Index, Param
from dodaios.self_change import Draft, State, Surface

from . import fakeworld
from .fakeworld import BLIND, LIMIT, SCORE

# ------------------------------------------------------------------- tuner

A = Param("x.a", 5, 0, 10, step=1, domains=("recall",))
B = Param("x.b", 0.5, 0.0, 1.0, step=0.1, domains=("recall",))
ELSEWHERE = Param("y.c", 5, 0, 10, step=1, domains=("skill",))
INDEX = Index((A, B, ELSEWHERE))
CURRENT = {"x.a": 5, "x.b": 0.5, "y.c": 5}


def trials(table: Mapping[tuple[str, Any], tuple[float, float]]):
    seen: list[dict[str, Any]] = []

    def try_values(values: Mapping[str, Any]) -> Trial:
        seen.append(dict(values))
        if not values:
            return Trial(0.80, 100.0, 50)
        ((name, value),) = values.items()
        score, cost = table.get((name, value), (0.80, 100.0))
        return Trial(score, cost, 50)

    return try_values, seen


def test_the_tuner_tries_near_and_far_values_inside_the_limits() -> None:
    assert neighbours(A, 5) == [4, 6, 3, 7, 1, 9]  # 8 steps away would leave the limits
    assert neighbours(A, 0) == [1, 2, 4, 8]
    assert neighbours(B, 0.5) == [0.4, 0.6, 0.3, 0.7, 0.1, 0.9]
    assert neighbours(Param("x.on", False), False) == [True]


def test_it_proposes_the_move_with_the_largest_gain_and_only_for_its_domain() -> None:
    try_values, seen = trials({("x.a", 7): (0.86, 120.0), ("x.b", 0.3): (0.83, 90.0)})
    found = Tuner(INDEX).propose("recall", CURRENT, try_values)
    assert found == Proposal("x.a", 7, 5, 0.06, 1.2, tried=12)
    assert "+0.060 score, 20% dearer (5 -> 7, best of 12 moves)" in found.reason()
    assert all("y.c" not in values for values in seen)  # another domain's parameter is not touched
    assert seen[0] == {} and all(len(values) == 1 for values in seen[1:])  # one move at a time


def test_without_a_gain_it_proposes_the_cheapest_move_that_scores_no_worse() -> None:
    table = {
        ("x.a", 4): (0.80, 80.0),
        ("x.a", 3): (0.79, 40.0),  # cheaper still, but it loses score
        ("x.b", 0.6): (0.80, 97.0),  # too small a saving
        ("x.b", 0.4): (0.80 + MIN_GAIN / 2, 99.0),  # too small a gain
    }
    try_values, _ = trials(table)
    found = Tuner(INDEX).propose("recall", CURRENT, try_values)
    assert (found.name, found.value, found.gain, found.cost_ratio) == ("x.a", 4, 0.0, 0.8)


def test_it_proposes_nothing_without_tasks_without_a_move_or_for_what_was_turned_down() -> None:
    try_values, _ = trials({("x.a", 7): (0.86, 100.0)})
    tuner = Tuner(INDEX)
    assert tuner.propose("recall", CURRENT, lambda values: Trial(0.0, 0.0, 0)) is None
    assert tuner.propose("recall", CURRENT, trials({})[0]) is None
    assert tuner.propose("recall", CURRENT, try_values, skip={("x.a", 7)}) is None
    assert tuner.propose("answer", CURRENT, try_values) is None


# ------------------------------------------------------------------- nights


@pytest.fixture
def box(tmp_path: Path, monkeypatch):
    """A sandbox on the made-up world, with the plainly bad value in effect."""
    built = fakeworld.sandbox(tmp_path, monkeypatch, plant={SCORE: BLIND})
    yield built
    built.close()


@pytest.fixture
def quiet_box(tmp_path: Path, monkeypatch):
    """A sandbox whose nights check and measure but let no learner propose."""
    built = fakeworld.sandbox(tmp_path, monkeypatch, learners=())
    yield built
    built.close()


def _draft(name: str, value: Any, author: str = "tuner") -> Draft:
    text = params.text_for(params.INDEX.by_name(name), value)
    return Draft(Surface.PARAMETER, name, text, author=author)


def _in_effect(box, name: str, value: Any, author: str = "tuner") -> Any:
    """Put a value in effect through the registry, as an earlier night would have."""
    change = box.registry.propose(_draft(name, value, author))
    live = box.night.gate.live().id
    box.registry.admit(change.id, Evidence(Verdict.ACCEPT, baseline=live), live=live)
    return change


def test_three_nights_repair_a_bad_value_then_save_cost_then_find_nothing_more(box) -> None:
    splits = fakeworld.splits()

    first = box.night.run()
    (proposed,) = first.proposed
    assert (proposed["target"], proposed["value"], proposed["current"]) == (SCORE, 8.0, BLIND)
    assert proposed["learner"] == "tuner" and proposed["gain"] > 0.5
    (decided,) = first.decided
    assert decided["outcome"] == "admitted" and decided["was"] == "proposed"
    found = decided["evidence"]
    assert found["split"] == "select" and found["target"]["n"] == splits["select"]
    assert found["target"]["low"] > 0.3 and found["reason"].startswith("better on")
    assert params.learned() == {SCORE: 8.0}
    (measured,) = first.measured
    assert (measured["split"], measured["source"]) == ("sealed", "own")
    assert measured["n"] == splits["sealed"]
    assert measured["diff"] == 0.0  # as good as the assistant as it ships again
    assert first.tasks["recall"] == splits

    second = box.night.run()
    (kept,) = second.settled
    assert (kept["target"], kept["outcome"], kept["was"]) == (SCORE, "kept", "trial")
    assert kept["evidence"]["split"] == "guard" and kept["evidence"]["target"]["diff"] > 0.5
    (cheaper,) = second.decided
    assert (cheaper["target"], cheaper["outcome"]) == (LIMIT, "admitted")
    reason = cheaper["evidence"]["reason"]
    assert "as good on" in reason and "67% cheaper" in reason
    assert params.learned() == {SCORE: 8.0, LIMIT: 2}
    point = second.measured[0]
    assert point["diff"] == 0.0 and point["now_tokens"] == 50 and point["factory_tokens"] == 150

    third = box.night.run()
    assert third.proposed == [] and third.decided == []
    assert {row["outcome"] for row in third.settled} == {"kept"}
    states = {c.target: c.state for c in box.registry.learned()}
    assert states == {SCORE: State.LIVE, LIMIT: State.LIVE}
    steps = [e["step"] for e in box.registry.store.evidence(box.registry.learned()[0].id)]
    assert steps[:2] == ["admit", "settle"]

    # What the nights did is on record, and so is the curve.
    recorded = box.bench.nights()
    assert len(recorded) == 3 and recorded[-1]["decided"][0]["outcome"] == "admitted"
    series = box.bench.series(domain="recall")
    assert [point["split"] for point in series] == ["sealed"] * 3
    assert series[0]["app"] == dodaios.__version__
    text = " ".join(first.lines())
    assert "Proposed recall.min_score = 8.0" in text and "Learned advantage in recall" in text
    assert "kept" in " ".join(second.lines())  # confirmed: that is news
    assert "kept" not in " ".join(box.night.run().lines())  # live and still live is not


def test_the_tuner_does_not_ask_again_for_what_the_gate_turned_down(
    tmp_path: Path, monkeypatch
) -> None:
    box = fakeworld.sandbox(tmp_path, monkeypatch)  # the shipped values: one saving to find
    try:
        declined = box.registry.propose(_draft(LIMIT, 2))
        box.registry.decline(declined.id, Evidence(Verdict.REJECT, reason="no clear difference"))
        report = box.night.run()
        (proposed,) = report.proposed
        assert (proposed["target"], proposed["value"]) == (LIMIT, 4)  # the next best, not 2 again
    finally:
        box.close()


def test_a_harmful_value_in_effect_is_taken_back_by_the_next_night(quiet_box) -> None:
    box = quiet_box
    change = _in_effect(box, SCORE, BLIND)  # let in by mistake
    report = box.night.run()
    (row,) = report.settled
    assert row["change_id"] == change.id and row["outcome"] == "taken back"
    assert "worse on" in row["evidence"]["reason"]
    assert params.get(SCORE) == 0.0 and report.proposed == []
    assert box.registry.store.get(change.id).state is State.REVERTED
    assert "taken back" in " ".join(report.lines())


def test_when_a_split_is_used_up_nothing_more_is_proposed_until_new_tasks_arrive(
    quiet_box,
) -> None:
    box = quiet_box
    gate = box.night.gate
    for value in range(MAX_DECISIONS):
        change = box.registry.propose(_draft("recall.recency_days", 400 + value, "x"))
        assert gate.consider(change).outcome == "declined"
    assert not gate.can_decide(Domain.RECALL)
    waiting = box.registry.propose(_draft(LIMIT, 2, "x"))
    decision = gate.consider(waiting)
    assert decision.outcome == "waiting" and "used up" in decision.evidence.reason
    assert box.registry.store.get(waiting.id).state is State.PROPOSED
    tuned = nights.Night(box.registry, box.bench, gate._worlds, sources=box.night.sources)
    assert tuned.run().proposed == []  # the tuner is not asked for what nothing could decide


def test_the_persons_stop_stops_everything_and_survives_a_restart(
    tmp_path: Path, monkeypatch
) -> None:
    box = fakeworld.sandbox(tmp_path, monkeypatch, plant={SCORE: BLIND})
    box.night.pause(True)
    report = box.night.run()
    assert report.paused and report.idle
    assert report.lines() == ["The loop is stopped; nothing was done."]
    assert box.registry.store.list() == [] and box.bench.nights() == []
    assert not box.night.due()
    box.close()
    again = fakeworld.sandbox(tmp_path, monkeypatch)
    assert again.night.paused()  # the stop is not lost with the process
    again.night.pause(False)
    assert again.night.due() and not again.night.run().paused
    assert not again.night.due()  # one night in twenty hours
    again.close()


def test_after_an_app_update_everything_learned_is_checked_again(quiet_box, monkeypatch) -> None:
    box = quiet_box
    names = [
        "recall.fetch_factor",
        "recall.recency_days",
        "lessons.recall_limit",
        "recall.lesson_cap",
        "recall.pinned_boost",
        "recall.entity_boost",
    ]
    values = [5, 395, 4, 1.6, 1.25, 1.6]
    for index, (name, value) in enumerate(zip(names, values, strict=True)):
        _in_effect(box, name, value, author=f"learner-{index}")
    before = dodaios.__version__
    ordinary = box.night.run()
    assert len(ordinary.settled) == 6 and ordinary.updated_from == ""
    assert {row["outcome"] for row in ordinary.settled} == {"kept"}
    assert len(box.night.run().settled) == 5  # live ones: only the newest five are looked at
    monkeypatch.setattr(dodaios, "__version__", "99.0.0")
    report = box.night.run()
    assert (report.updated_from, report.app) == (before, "99.0.0")
    assert len(report.settled) == 6
    assert "was updated" in report.lines()[0]
    assert box.bench.series(domain="recall")[-1]["app"] == "99.0.0"
    assert box.night.run().updated_from == ""


def test_an_installation_without_tasks_of_its_own_has_quiet_nights(tmp_path: Path) -> None:
    box = nights.sandbox(tmp_path)  # holds seed tasks only
    home = nights.Night(box.registry, box.bench, lambda: {})  # decides on the person's own tasks
    report = home.run()
    assert report.idle
    assert report.lines() == ["Nothing to do: there are no tasks to measure on yet."]
    assert params.learned() == {} and box.registry.store.list() == []
    box.close()


def test_the_command_runs_the_seed_sandbox_and_leaves_nothing_behind(
    capsys, tmp_path: Path
) -> None:
    home = tmp_path / "box"
    assert nights.main(["--sandbox", str(home), "--plant", f"{SCORE}={BLIND}"]) == 0
    out = capsys.readouterr().out
    assert "Night 1" in out and "Learned advantage in recall" in out
    assert "Proposed recall." in out and "In effect now:" in out
    assert params.installed() is None
    assert {p.name for p in home.iterdir()} >= {"bench.db", "params.db", "self_changes.db"}
    with pytest.raises(SystemExit):
        nights.main([])  # the app runs its own nights; the command only runs sandboxes


# ------------------------------------------------------------- in the app


def test_the_app_runs_a_night_only_when_one_is_due_and_the_person_is_away(quiet_box) -> None:
    away = {"now": False}
    service = nights.NightService(quiet_box.night, lambda: away["now"])
    assert service.tick() is None and quiet_box.bench.nights() == []  # the person is here
    away["now"] = True
    report = service.tick()
    assert report is not None and service.last is report and len(quiet_box.bench.nights()) == 1
    assert service.tick() is None  # not twice within twenty hours
    quiet_box.night.pause(True)
    assert service.tick() is None


def test_learning_is_work_to_keep_until_the_person_stops_the_loop(quiet_box) -> None:
    service = nights.NightService(quiet_box.night, lambda: True)
    assert service.learning() is True
    quiet_box.night.pause(True)
    assert service.learning() is False


def test_a_halt_ends_the_running_night_with_its_report_and_starts_no_other(quiet_box) -> None:
    import asyncio
    import concurrent.futures
    import threading

    service = nights.NightService(quiet_box.night, lambda: True)
    started = threading.Event()
    cut: list[str | None] = []

    def prepare() -> dict[str, Any]:
        # A model call in flight, waited for the way the task maker waits for one.
        started.set()
        call: concurrent.futures.Future[str] = concurrent.futures.Future()
        cut.append(nights._wait_for(call, lambda: service.halted, poll_s=0.01))
        return {}

    quiet_box.night._prepare = prepare
    worker = threading.Thread(target=service.tick, daemon=True)
    worker.start()
    assert started.wait(10) and service.busy
    assert asyncio.run(service.wind_down(10.0, poll_s=0.01)) is True
    worker.join(10)
    assert cut == [None]  # the call was cut, not answered
    assert not service.busy and service.halted
    # The night went on without a model and wrote its report, as when the person is back.
    assert len(quiet_box.bench.nights()) == 1 and quiet_box.night.last_ms() > 0
    quiet_box.bench.set_meta("loop", {})  # due again
    assert quiet_box.night.due() and service.tick() is None  # a halted backend starts none


def test_the_backend_loop_ending_halts_the_nights(quiet_box) -> None:
    import asyncio

    service = nights.NightService(quiet_box.night, lambda: True)

    async def backend() -> None:
        service.start()
        await asyncio.sleep(0)  # the watch is waiting for its next look

    asyncio.run(backend())  # the loop ends: its tasks are cancelled before its threads are joined
    assert service.halted and service.tick() is None


def test_a_waited_call_gives_up_at_its_time_limit_and_is_cancelled() -> None:
    import concurrent.futures

    future: concurrent.futures.Future[str] = concurrent.futures.Future()
    assert nights._wait_for(future, None, timeout_s=0.05, poll_s=0.01) is None
    assert future.cancelled()
    done: concurrent.futures.Future[str] = concurrent.futures.Future()
    done.set_result("an answer")
    assert nights._wait_for(done, lambda: False) == "an answer"


def test_a_halted_night_asks_no_model() -> None:
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        assert nights._model_ask(None, loop, lambda: True)("system", "prompt") is None
    finally:
        loop.close()


def test_the_installations_own_nights_never_decide_on_the_seed_suite(tmp_path: Path) -> None:
    from dodaios.rsi.bench.model import Source
    from dodaios.self_change import SelfChangeRegistry

    registry = SelfChangeRegistry(tmp_path)
    service = nights.install(tmp_path, registry)
    try:
        assert Source.SEED not in service.night.sources
        assert service.night.run().idle
        assert (tmp_path / "bench.db").exists()
    finally:
        service.night.bench.close()
        registry.close()


def test_the_first_nights_may_build_more_tasks_until_there_are_enough_to_decide_on(
    tmp_path: Path,
) -> None:
    import dataclasses

    from dodaios.rsi.bench.model import Source, Split, task_id
    from dodaios.rsi.bench.store import BenchStore
    from dodaios.rsi.gate.rules import MIN_PAIRS

    bench = BenchStore(tmp_path / "bench.db")
    try:
        assert nights.calls_tonight(bench) == nights.RAMP_MODEL_CALLS
        made = fakeworld.tasks(400)
        select = [t for t in made if t.split is Split.SELECT]
        assert len(select) > MIN_PAIRS and all(t.source is Source.MADE for t in select)
        bench.put_tasks([t for t in made if t.split is not Split.SELECT])
        bench.put_tasks(select[: MIN_PAIRS - 1])
        # Tasks of the other splits, or from the seed suite, do not count.
        seed = [
            dataclasses.replace(t, id=task_id(Domain.RECALL, Source.SEED, t.id), source=Source.SEED)
            for t in select
        ]
        bench.put_tasks(seed)
        assert nights.calls_tonight(bench) == nights.RAMP_MODEL_CALLS
        bench.put_tasks(select[MIN_PAIRS - 1 : MIN_PAIRS])
        assert nights.calls_tonight(bench) == nights.MAX_MODEL_CALLS
        assert nights.RAMP_MODEL_CALLS > nights.MAX_MODEL_CALLS
    finally:
        bench.close()
