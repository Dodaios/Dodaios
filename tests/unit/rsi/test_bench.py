"""The benchmark: the seed suite, the recall domain, runs under overlays, and ``bench.db``."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi import overlay
from dodaios.rsi.bench import recall, run, seedsuite
from dodaios.rsi.bench.__main__ import main as bench_main
from dodaios.rsi.bench.model import Domain, Result, Source, Split, Task
from dodaios.rsi.bench.store import BenchStore, PracticeView


@pytest.fixture(scope="module")
def world():
    built = seedsuite.build_world()
    yield built
    built.close()


@pytest.fixture(scope="module")
def worlds(world):
    return {seedsuite.SEED_WORLD: recall.RecallWorld(world.vault, world.ids)}


# ----------------------------------------------------------- the seed suite


def test_the_seed_file_is_complete_and_names_only_memories_that_exist() -> None:
    data = seedsuite.recall_data()
    assert (len(data["memories"]), len(data["queries"])) == (150, 330)
    tasks = seedsuite.recall_tasks()
    assert len({t.id for t in tasks}) == 330
    assert all(t.payload["world"] == seedsuite.SEED_WORLD for t in tasks)
    used = {key for t in tasks for key in t.check["gold"]}
    assert used == {m["key"] for m in data["memories"]}  # every memory is asked about
    assert Counter(t.payload["style"] for t in tasks)["none"] == 60
    for task in tasks:
        if task.check["stale"]:
            assert task.payload["style"] == "fresh", task.id
            assert not set(task.check["stale"]) & set(task.check["gold"]), task.id


def test_every_question_about_a_cluster_is_in_the_same_split() -> None:
    data = seedsuite.recall_data()
    cluster = {m["key"]: m["cluster"] for m in data["memories"]}
    split_of_cluster: dict[str, Split] = {}
    for task in seedsuite.recall_tasks():
        for key in task.check["gold"][:1]:
            assert split_of_cluster.setdefault(cluster[key], task.split) is task.split
    counts = Counter(t.split for t in seedsuite.recall_tasks())
    assert all(counts[split] >= 30 for split in Split), counts


def test_the_seed_world_is_the_same_on_every_machine_and_every_day(world) -> None:
    assert len(world.ids) == 150
    assert world.vault.now() == seedsuite.recall_data()["now"]
    again = seedsuite.build_world()
    try:
        texts = lambda v: sorted((m.text, m.recorded_at, m.pinned) for m in v.list())  # noqa: E731
        assert texts(again.vault) == texts(world.vault)
    finally:
        again.close()
    lessons = [m for m in world.vault.list(kind="procedural") if m.source.get("note")]
    assert lessons and all(m.source.get("trigger") for m in lessons)


# ------------------------------------------------------------- the scoring


def _task(query: str, gold: list[str], stale: list[str] | None = None) -> Task:
    return Task(
        "t",
        Domain.RECALL,
        Source.MADE,
        "g",
        {"query": query, "world": "w"},
        {"gold": gold, "stale": stale or []},
    )


def test_a_task_scores_whether_the_model_got_the_memory_it_needed(tmp_path: Path) -> None:
    clock = {"now": "2024-01-10T12:00:00+00:00"}
    vault = MemoryVault(":memory:", clock=lambda: clock["now"])
    old = vault.remember("I trained for the harbour ten kilometre race.", "episode").memory
    clock["now"] = "2026-03-01T12:00:00+00:00"
    new = vault.remember("I train for the harbour half marathon race now.", "episode").memory
    other = vault.remember("We painted the kitchen green last spring.", "episode").memory
    assert old and new and other
    for filler in (  # enough unrelated memories for the keyword ranking to mean something
        "The dentist moved to the new practice by the station.",
        "My sister plays the cello in a quartet.",
        "We adopted a grey cat called Pepper.",
        "The library card expires in August.",
        "I prefer window seats on long train rides.",
        "Our neighbour waters the tomatoes when we travel.",
        "The bike needs new brake pads before summer.",
        "I am learning to bake rye bread.",
        "The choir rehearses on Tuesday evenings.",
        "We keep the spare keys in the blue tin.",
    ):
        vault.remember(filler, "episode")
    world = recall.RecallWorld(vault, {"old": old.id, "new": new.id, "kitchen": other.id})

    kitchen = "which colour did we paint the kitchen"
    assert recall.score(_task(kitchen, ["kitchen"]), world).score == 1.0
    missed = recall.score(_task(kitchen, ["new"]), world)
    assert missed.score == 0 and "missing" in missed.detail
    half = recall.score(_task(kitchen, ["kitchen", "new"]), world)  # one of two it needed
    assert half.score == 0.5 and half.detail == "missing: new"
    # A message that needs no memory scores when nothing is looked up for it.
    assert recall.score(_task("thanks, that is all", []), world).score == 1.0
    noisy = recall.score(_task("tell me about the kitchen", []), world)
    assert noisy.score == 0.0 and noisy.tokens > 0

    # The outdated memory shown first: the right one counts half.
    query = "the harbour ten kilometre race I trained for"
    with overlay.active(overlay.Overlay(params={"recall.relative_floor": 0.05})):
        found = recall.vault_runtime.recall_for(vault, query)
        assert [m.id for m in found.chosen][:2] == [old.id, new.id]
        behind = recall.score(_task(query, ["new"], stale=["old"]), world)
        assert behind.score == 0.5 and "outdated" in behind.detail
        assert recall.score(_task(query, ["old"], stale=["new"]), world).score == 1.0
    with overlay.active(overlay.Overlay(params={"recall.relative_floor": 0.9})):
        # A strict floor shows only the best hit: the newer one is missing, not half right.
        assert recall.score(_task(query, ["new"], stale=["old"]), world).score == 0.0
    vault.close()


# ---------------------------------------------------------- runs and pairs


def test_a_run_leaves_the_world_as_it_was_and_names_the_state_it_ran_in(world, worlds) -> None:
    tasks = seedsuite.recall_tasks()[:60]
    shipped = run.measure(tasks, overlay.FACTORY, worlds)
    tight = overlay.Overlay(label="tight", params={"recall.turn_limit": 2})
    other = run.measure(tasks, tight, worlds)
    assert all(m.use_count == 0 for m in world.vault.list())
    assert overlay.current() is None
    assert len({r.arm for r in shipped}) == 1 and shipped[0].arm != other[0].arm
    assert shipped[0].arm == run.arm_of(overlay.FACTORY).id
    assert all(r.counts and 0.0 <= r.score <= 1.0 for r in shipped)
    assert sum(r.tokens for r in other) < sum(r.tokens for r in shipped)
    assert run.measure(tasks, overlay.FACTORY, worlds)[0].score == shipped[0].score


def test_a_task_that_cannot_run_is_void_and_the_run_goes_on(worlds) -> None:
    lost = Task("x", Domain.RECALL, Source.MADE, "g", {"query": "q", "world": "nowhere"})
    unknown = Task("y", Domain.CODING, Source.MADE, "g", {})
    good = seedsuite.recall_tasks()[0]
    results = run.measure([lost, unknown, good], overlay.FACTORY, worlds)
    assert [r.counts for r in results] == [False, False, True]
    assert "no memory" in results[0].detail and "coding" in results[1].detail


def test_a_pair_is_one_difference_per_task_both_states_measured_on_the_same_content() -> None:
    def result(task: str, digest: str, arm: str, score: float, **more) -> Result:
        return Result(task, digest, arm, score, **more)

    base = [
        result("a", "1", "b", 0.0, tokens=100),
        result("b", "1", "b", 1.0, tokens=100),
        result("c", "1", "b", 1.0),
        result("d", "OLD", "b", 1.0),
    ]
    cand = [
        result("a", "1", "c", 1.0, tokens=50),
        result("b", "1", "c", 1.0, tokens=50),
        result("c", "1", "c", 0.0, void="the seat changed"),
        result("d", "NEW", "c", 0.0),
        result("e", "1", "c", 1.0),
    ]
    paired = run.pair(base, cand)
    assert paired.task_ids == ("a", "b") and paired.differences == (1.0, 0.0)
    assert (paired.baseline_mean, paired.candidate_mean) == (0.5, 1.0)
    assert (paired.baseline_tokens, paired.candidate_tokens) == (100.0, 50.0)
    assert run.pair([], cand).n == 0


def test_the_order_of_a_comparison_is_fixed_before_any_result_is_known() -> None:
    tasks = seedsuite.recall_tasks()[:40]
    one = [t.id for t in run.shuffled(tasks, "night-1")]
    assert one == [t.id for t in run.shuffled(list(reversed(tasks)), "night-1")]
    assert one != [t.id for t in run.shuffled(tasks, "night-2")]
    assert sorted(one) == sorted(t.id for t in tasks)


# ----------------------------------------------------------------- bench.db


def test_tasks_and_results_survive_a_restart_and_results_cannot_be_edited(tmp_path: Path) -> None:
    store = BenchStore(tmp_path / "bench.db")
    tasks = seedsuite.recall_tasks()
    assert store.put_tasks(tasks) == 330 and store.put_tasks(tasks) == 0
    sealed = store.tasks(Domain.RECALL, splits=(Split.SEALED,))
    assert sealed and all(t.split is Split.SEALED for t in sealed)
    store.add_results([Result(sealed[0].id, sealed[0].digest, "fp_a", 1.0, tokens=12)])
    store.close()

    again = BenchStore(tmp_path / "bench.db")
    assert sum(again.counts()["recall"].values()) == 330
    (kept,) = again.results("fp_a")
    assert (kept.task_id, kept.score, kept.tokens) == (sealed[0].id, 1.0, 12)
    assert again.results("fp_other") == []
    for statement in ("UPDATE results SET score = 0", "DELETE FROM results"):
        with pytest.raises(sqlite3.Error, match="append-only"):
            again._db.conn.execute(statement)
    again.close()


def test_a_corrected_task_keeps_its_id_and_its_split_and_a_retired_one_is_left_out(
    tmp_path: Path,
) -> None:
    store = BenchStore(tmp_path / "bench.db")
    task = Task("recall-1", Domain.RECALL, Source.SEED, "group-a", {"query": "old wording"})
    store.put_tasks([task])
    moved = Task("recall-1", Domain.RECALL, Source.SEED, "another-group", {"query": "new wording"})
    assert store.put_tasks([moved]) == 0
    (stored,) = store.tasks(Domain.RECALL)
    assert stored.payload["query"] == "new wording" and stored.digest == moved.digest
    assert stored.group == "group-a" and stored.split is task.split
    store.retire(["recall-1"])
    assert store.tasks(Domain.RECALL) == []
    store.put_tasks([task])  # the seed suite ships it again: it is in use again
    assert len(store.tasks(Domain.RECALL)) == 1
    store.close()


def test_a_learner_only_ever_sees_practice_tasks(tmp_path: Path) -> None:
    store = BenchStore(tmp_path / "bench.db")
    store.put_tasks(seedsuite.recall_tasks())
    seen = PracticeView(store).tasks(Domain.RECALL)
    assert seen and {t.split for t in seen} == {Split.PRACTICE}
    assert not hasattr(PracticeView(store), "results")
    assert len(seen) == store.counts()["recall"]["practice"]
    store.close()


def test_an_older_app_reads_a_newer_bench_file_and_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "bench.db"
    newer = BenchStore(path)
    newer.put_tasks(seedsuite.recall_tasks()[:5])
    newer.close()
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 99")
    raw.commit()
    raw.close()
    older = BenchStore(path)
    assert older.readonly and len(older.tasks(Domain.RECALL)) == 5
    with pytest.raises(sqlite3.OperationalError):
        older.put_tasks(seedsuite.recall_tasks()[5:6])
    older.close()


# ---------------------------------------------------------- the public run


def test_the_command_prints_the_same_numbers_for_everybody(capsys) -> None:
    assert bench_main(["--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert bench_main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert first["tasks"] == 330 and set(first["splits"]) == {s.value for s in Split}
    assert all(0.3 < s["score"] <= 1.0 for s in first["splits"].values())

    assert bench_main(["--set", "recall.turn_limit=2", "--json"]) == 0
    compared = json.loads(capsys.readouterr().out)
    sealed = compared["splits"]["sealed"]
    assert sealed["low"] <= sealed["diff"] <= sealed["high"]
    assert sealed["candidate_tokens"] < sealed["tokens"]
    with pytest.raises(Exception, match="must be"):
        bench_main(["--set", "recall.turn_limit=99"])
