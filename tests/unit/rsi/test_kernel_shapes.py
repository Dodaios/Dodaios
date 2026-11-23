"""The kernel's shared shapes: storage that survives updates, overlays, tasks, fingerprints."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections import Counter
from pathlib import Path

import pytest

from dodaios.rsi import overlay
from dodaios.rsi.bench.model import (
    LEARNER_SPLITS,
    SPLIT_SHARES,
    Domain,
    Result,
    Source,
    Split,
    Task,
    split_of,
    task_id,
)
from dodaios.rsi.fingerprint import Fingerprint, params_hash
from dodaios.rsi.gate.evidence import Effect, Evidence, Verdict
from dodaios.rsi.storage import Schema, open_db
from dodaios.self_change import surfaces

PINNED_DRAW = {"alpha": "select", "beta": "practice", "gamma": "guard", "delta": "guard"}

V1 = "CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, value TEXT NOT NULL);"
V2 = "ALTER TABLE items ADD COLUMN note TEXT NOT NULL DEFAULT '';"
TRIGGER = (
    "CREATE TRIGGER items_keep BEFORE DELETE ON items\n"
    "BEGIN SELECT RAISE(ABORT, 'kept'); END;\n"
    "CREATE INDEX items_value ON items(value);"
)


# ------------------------------------------------------------------ storage


def test_a_new_file_is_built_at_the_newest_version(tmp_path: Path) -> None:
    db = open_db(tmp_path / "k.db", Schema("k", (V1, V2)))
    assert (db.version, db.readonly) == (2, False)
    db.conn.execute("INSERT INTO items (id, value, note) VALUES ('a', '1', 'n')")
    db.conn.commit()
    db.close()


def test_an_update_keeps_what_was_learned_and_adds_the_new_columns(tmp_path: Path) -> None:
    path = tmp_path / "k.db"
    old = open_db(path, Schema("k", (V1,)))
    old.conn.execute("INSERT INTO items (id, value) VALUES ('a', 'learned')")
    old.conn.commit()
    old.close()

    new = open_db(path, Schema("k", (V1, V2, TRIGGER)))
    row = new.conn.execute("SELECT value, note FROM items WHERE id='a'").fetchone()
    assert (row["value"], row["note"], new.version) == ("learned", "", 3)
    with pytest.raises(sqlite3.Error, match="kept"):
        new.conn.execute("DELETE FROM items")
    new.close()
    # The file as it was before the migration is put aside, once.
    copies = sorted(p.name for p in tmp_path.glob("k.db.before-v*"))
    assert copies == ["k.db.before-v1"]
    aside = sqlite3.connect(tmp_path / copies[0])
    assert aside.execute("SELECT value FROM items").fetchone()[0] == "learned"
    aside.close()


def test_a_file_from_before_versioning_is_adopted_not_rebuilt(tmp_path: Path) -> None:
    path = tmp_path / "k.db"
    raw = sqlite3.connect(path)
    raw.execute(V1)
    raw.execute("INSERT INTO items (id, value) VALUES ('a', 'old')")
    raw.commit()
    raw.close()
    db = open_db(path, Schema("k", (V1, V2)))
    assert db.conn.execute("SELECT value FROM items").fetchone()[0] == "old"
    assert db.version == 2
    db.close()


def test_a_failing_step_leaves_the_file_at_its_old_version(tmp_path: Path) -> None:
    path = tmp_path / "k.db"
    open_db(path, Schema("k", (V1,))).close()
    broken = "ALTER TABLE items ADD COLUMN extra TEXT;\nALTER TABLE nowhere ADD COLUMN x TEXT;"
    with pytest.raises(sqlite3.Error):
        open_db(path, Schema("k", (V1, broken)))
    raw = sqlite3.connect(path)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "extra" not in {r[1] for r in raw.execute("PRAGMA table_info(items)")}
    raw.close()


def test_an_older_app_only_reads_a_file_a_newer_app_wrote(tmp_path: Path) -> None:
    path = tmp_path / "k.db"
    newer = open_db(path, Schema("k", (V1, V2)))
    newer.conn.execute("INSERT INTO items (id, value) VALUES ('a', 'learned')")
    newer.conn.commit()
    newer.close()

    older = open_db(path, Schema("k", (V1,)))
    assert (older.readonly, older.version) == (True, 2)
    assert older.conn.execute("SELECT value FROM items").fetchone()[0] == "learned"
    with pytest.raises(sqlite3.OperationalError):
        older.conn.execute("INSERT INTO items (id, value) VALUES ('b', 'x')")
    older.close()


# ------------------------------------------------------------------ overlay


def test_without_an_overlay_nothing_is_a_replay() -> None:
    assert overlay.current() is None
    assert not overlay.replaying()
    assert abs(overlay.now_ms() - __import__("time").time() * 1000) < 5_000


def test_an_overlay_holds_for_the_task_and_the_tasks_it_starts() -> None:
    candidate = overlay.Overlay(label="c", params={"a.b": 2}, now_ms=1_000)

    async def child() -> tuple[bool, int]:
        return overlay.replaying(), overlay.now_ms()

    async def main() -> tuple[bool, int]:
        with overlay.active(candidate):
            return await asyncio.create_task(child())

    assert asyncio.run(main()) == (True, 1_000)
    assert overlay.current() is None


def test_another_thread_finds_the_overlay_by_its_session_id() -> None:
    seen: list[overlay.Overlay | None] = []

    def gateway() -> None:  # a tool call that arrives outside the run's own task
        seen.append(overlay.current())
        seen.append(overlay.current("sess-1"))
        seen.append(overlay.current("someone-else"))

    with overlay.for_session("sess-1", overlay.FACTORY) as running:
        thread = threading.Thread(target=gateway)
        thread.start()
        thread.join()
        with pytest.raises(RuntimeError):
            with overlay.for_session("sess-1", overlay.FACTORY):
                pass
    assert seen == [None, running, None]
    assert overlay.current("sess-1") is None


def test_factory_and_ablation_say_which_learned_changes_a_run_may_not_see() -> None:
    assert overlay.FACTORY.excludes("anything")
    ablation = overlay.Overlay(without={"chg1"})
    assert ablation.excludes("chg1") and not ablation.excludes("chg2")
    with pytest.raises(TypeError):
        ablation.params["x"] = 1  # type: ignore[index]


# -------------------------------------------------------------- tasks, splits


def test_a_group_always_lands_in_the_same_split_and_siblings_stay_together() -> None:
    first = Task("t1", Domain.RECALL, Source.MINED, group="g-17", payload={"q": "a"})
    second = Task("t2", Domain.RECALL, Source.MINED, group="g-17", payload={"q": "b"})
    assert first.split is second.split is split_of(Domain.RECALL, "g-17")
    assert LEARNER_SPLITS == {Split.PRACTICE}


def test_the_draw_is_pinned_for_ever() -> None:
    # An update that moved this draw would show sealed tasks to the learners.
    drawn = {g: split_of(Domain.RECALL, g).value for g in ("alpha", "beta", "gamma", "delta")}
    assert drawn == PINNED_DRAW


def test_the_shares_are_what_the_table_says() -> None:
    assert sum(share for _, share in SPLIT_SHARES) == 100
    counts = Counter(split_of(Domain.SKILL, f"group-{i}") for i in range(4000))
    for split, share in SPLIT_SHARES:
        assert abs(counts[split] / 4000 * 100 - share) < 3, (split, counts[split])


def test_a_tasks_digest_follows_its_content_and_its_id_does_not() -> None:
    key = "memory:42:question:1"
    ident = task_id(Domain.RECALL, Source.SEED, key)
    one = Task(ident, Domain.RECALL, Source.SEED, "g", {"q": "a"})
    fixed = Task(one.id, Domain.RECALL, Source.SEED, "g", {"q": "a, corrected"})
    assert one.id == fixed.id == task_id(Domain.RECALL, Source.SEED, key)
    assert one.digest != fixed.digest
    assert one.digest == Task(one.id, Domain.RECALL, Source.SEED, "other", {"q": "a"}).digest
    with pytest.raises(TypeError):
        one.payload["q"] = "x"  # type: ignore[index]


def test_a_result_is_a_score_between_zero_and_one_and_can_be_void() -> None:
    assert Result("t", "d", "fp_x", 1.0).counts
    assert not Result("t", "d", "fp_x", 0.0, void="the seat changed").counts
    with pytest.raises(ValueError):
        Result("t", "d", "fp_x", 1.5)


# -------------------------------------------------------------- fingerprints


def test_a_fingerprint_names_the_state_not_the_order_things_were_listed_in() -> None:
    one = Fingerprint.of(app="5.7.0", changes=["b", "a"], params={"x": 1, "y": 2}, model="m")
    two = Fingerprint.of(app="5.7.0", changes=["a", "b", "a"], params={"y": 2, "x": 1}, model="m")
    assert one == two and one.id == two.id
    assert one.id != Fingerprint.of(app="5.8.0", changes=["a", "b"], params={"x": 1, "y": 2}).id
    assert params_hash({"x": 1}) != params_hash({"x": 2})


def test_a_pair_needs_the_same_model_seat_cli_and_app() -> None:
    base = Fingerprint.of(app="5.7.0", model="m1", seat="claude-cli", cli="2.1")
    assert base.same_platform(Fingerprint.of(app="5.7.0", changes=["c"], model="m1",
                                             seat="claude-cli", cli="2.1"))
    assert not base.same_platform(Fingerprint.of(app="5.7.0", model="m2",
                                                 seat="claude-cli", cli="2.1"))
    assert not base.same_platform(Fingerprint.of(app="5.8.0", model="m1",
                                                 seat="claude-cli", cli="2.1"))


# ------------------------------------------------------------------ evidence


def test_evidence_carries_the_numbers_a_decision_rests_on() -> None:
    found = Evidence(
        Verdict.ACCEPT,
        target=Effect("recall", diff=0.08, low=0.01, high=0.15, n=120),
        others=(Effect("skill", diff=0.0, low=-0.02, high=0.02, n=90),),
        baseline="fp_abc",
        split="select",
        alpha=0.01,
    )
    assert found.accepted
    public = found.public()
    assert public["verdict"] == "accept" and public["target"]["n"] == 120
    assert public["others"][0]["domain"] == "skill"
    assert not Evidence(Verdict.UNMEASURED, reason="no jury").accepted


# ------------------------------------------------------------- kernel paths


def test_the_assistant_can_never_change_its_kernel_or_its_evidence() -> None:
    for path in (
        "dodaios/rsi/bench/model.py",
        "dodaios/rsi/gate/evidence.py",
        "dodaios/agent_chat/store.py",
        "dodaios/agent_chat/control_eval.py",
        "dodaios/skills/eval_harness.py",
        "dodaios/self_build/brain.py",
        ".github/workflows/ci.yml",
        "./.github/workflows/release.yml",
        "dodaios\\rsi\\storage.py",
    ):
        assert surfaces.is_kernel_path(path), path
        assert surfaces.core_reasons(surfaces.Surface.CODE, "x", "text", (path,)), path
    for path in ("dodaios/learners/tuner.py", "dodaios/briefs/kit.py", "github/workflows/x"):
        assert not surfaces.is_kernel_path(path), path
    # The scan of ordinary coding runs keeps its narrower list.
    assert not surfaces.is_core_path("dodaios/agent_chat/store.py")


