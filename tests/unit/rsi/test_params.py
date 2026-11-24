"""Parameters: shipped defaults, learned values, benchmark overlays, and app updates."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi import overlay, params
from dodaios.rsi.params import Index, Param, ParamError, ParamStore
from dodaios.rsi.params.live import DORMANT, LIVE, RESTALE
from dodaios.self_change import Draft, SelfChangeRegistry, State, Surface


@pytest.fixture(autouse=True)
def _defaults_after_each_test():
    yield
    params.install(None)


def _store(tmp_path: Path, *specs: Param) -> ParamStore:
    return ParamStore(tmp_path / "params.db", index=Index(specs) if specs else params.INDEX)


BOOST = Param("recall.entity_boost", 1.5, 1.0, 3.0, domains=("recall",))


# ----------------------------------------------------------------- catalog


def test_the_shipped_defaults_are_the_constants_the_code_had() -> None:
    assert params.values() == {
        "recall.entity_boost": 1.5,
        "recall.pinned_boost": 1.2,
        "recall.recency_floor": 0.7,
        "recall.recency_days": 365,
        "recall.fetch_factor": 4,
        "recall.turn_limit": 6,
        "recall.turn_max_chars": 900,
        "recall.relative_floor": 0.35,
        "recall.min_score": 0.0,
        "recall.lesson_base": 0.6,
        "recall.lesson_cap": 1.5,
        "lessons.recall_threshold": 0.4,
        "lessons.recall_limit": 3,
        "lead.first_line": True,
    }
    for param in params.CATALOG:
        assert param.doc and param.domains, param.name


def test_a_value_keeps_its_type_and_its_limits() -> None:
    whole = Param("a.count", 6, 2, 10)
    assert whole.coerce(8) == 8 and whole.coerce(8.0) == 8
    for bad in (8.5, 11, 1, True, "8", None, float("nan")):
        assert not whole.valid(bad), bad
    assert Param("a.ratio", 0.5, 0.0, 1.0).coerce(1) == 1.0
    switch = Param("a.on", False)
    assert switch.coerce(True) is True and not switch.valid(1)
    with pytest.raises(ParamError):
        Param("a.bad", 5, 6, 9)
    with pytest.raises(ParamError):
        Index((whole, Param("b.count", 1, 0, 2, aliases=("a.count",))))


# ----------------------------------------------------- what get() answers


def test_get_answers_overlay_then_learned_then_default(tmp_path: Path) -> None:
    assert params.get("recall.turn_limit") == 6
    store = params.install(tmp_path)
    assert store is params.installed() is params.install(tmp_path)
    store.write("recall.turn_limit", params.text_for(params.INDEX.by_name("recall.turn_limit"), 4))
    assert params.get("recall.turn_limit") == 4
    assert params.learned() == {"recall.turn_limit": 4}
    with overlay.active(overlay.Overlay(params={"recall.turn_limit": 8})):
        assert params.get("recall.turn_limit") == 8
        assert params.get("recall.entity_boost") == 1.5
    with overlay.active(overlay.FACTORY):  # the assistant as it ships
        assert params.get("recall.turn_limit") == 6
    with overlay.active(overlay.Overlay(params={"recall.turn_limit": 99})):
        with pytest.raises(ParamError):  # a run cannot leave the limits either
            params.get("recall.turn_limit")
    with pytest.raises(ParamError):
        params.get("recall.no_such_thing")


def test_a_learned_value_survives_a_restart(tmp_path: Path) -> None:
    first = _store(tmp_path)
    first.write("recall.entity_boost", params.text_for(BOOST, 1.8))
    first.close()
    again = _store(tmp_path)
    assert again.values() == {"recall.entity_boost": 1.8}
    assert again.read("recall.entity_boost") == '{"base":1.5,"value":1.8}'
    again.write("recall.entity_boost", None)  # a rollback of the first learned value
    assert again.values() == {} and again.read("recall.entity_boost") is None


# ----------------------------------------------------------- app updates


def test_a_changed_default_keeps_the_learned_value_and_asks_for_a_new_measurement(
    tmp_path: Path,
) -> None:
    old = _store(tmp_path, BOOST)
    old.write("recall.entity_boost", params.text_for(BOOST, 1.8))
    old.close()
    updated = _store(tmp_path, Param("recall.entity_boost", 1.7, 1.0, 3.0, domains=("recall",)))
    (entry,) = updated.entries()
    assert (entry.status, entry.value, entry.base) == (RESTALE, 1.8, 1.5)
    assert updated.values() == {"recall.entity_boost": 1.8}


def test_a_renamed_parameter_takes_its_learned_value_along(tmp_path: Path) -> None:
    old = _store(tmp_path, BOOST)
    old.write("recall.entity_boost", params.text_for(BOOST, 1.8))
    old.close()
    renamed = Param("search.entity_boost", 1.5, 1.0, 3.0, aliases=("recall.entity_boost",))
    updated = _store(tmp_path, renamed)
    assert updated.values() == {"search.entity_boost": 1.8}
    (entry,) = updated.entries()
    assert (entry.status, entry.stored_as, entry.name) == (LIVE, BOOST.name, "search.entity_boost")
    # Both names reach the one stored row: a rollback recorded under the old
    # name and a new change under the new one cannot end up as two values.
    assert updated.read("search.entity_boost") == updated.read("recall.entity_boost")
    updated.write("search.entity_boost", params.text_for(renamed, 2.0))
    assert updated.values() == {"search.entity_boost": 2.0} and len(updated.entries()) == 1
    updated.write("recall.entity_boost", None)
    assert updated.values() == {} and updated.entries() == []


def test_a_removed_parameter_rests_and_comes_back_with_a_version_that_knows_it(
    tmp_path: Path,
) -> None:
    old = _store(tmp_path, BOOST)
    old.write("recall.entity_boost", params.text_for(BOOST, 1.8))
    old.close()
    without = _store(tmp_path, Param("other.thing", 1, 0, 2))
    (entry,) = without.entries()
    assert entry.status == DORMANT and "no such parameter" in entry.why
    assert without.values() == {}
    without.close()
    assert _store(tmp_path, BOOST).values() == {"recall.entity_boost": 1.8}


def test_a_value_outside_new_limits_or_an_unreadable_one_rests(tmp_path: Path) -> None:
    old = _store(tmp_path, BOOST)
    old.write("recall.entity_boost", params.text_for(BOOST, 2.8))
    old.close()
    raw = sqlite3.connect(tmp_path / "params.db")
    raw.execute("INSERT INTO params (name, text, updated_ms) VALUES ('broken', 'not json', 0)")
    raw.commit()
    raw.close()
    narrowed = _store(tmp_path, Param("recall.entity_boost", 1.5, 1.0, 2.0))
    status = {e.stored_as: e.status for e in narrowed.entries()}
    assert status == {"recall.entity_boost": DORMANT, "broken": DORMANT}
    assert narrowed.values() == {}
    # A rollback may put back the exact earlier text even when it would rest today.
    narrowed.write("recall.entity_boost", '{"base":1.5,"value":2.9}')
    assert narrowed.values() == {}


def test_an_older_app_reads_what_a_newer_one_learned_and_writes_nothing(tmp_path: Path) -> None:
    newer = _store(tmp_path, BOOST)
    newer.write("recall.entity_boost", params.text_for(BOOST, 1.8))
    newer.close()
    raw = sqlite3.connect(tmp_path / "params.db")
    raw.execute("PRAGMA user_version = 99")
    raw.commit()
    raw.close()
    older = _store(tmp_path, BOOST)
    assert older.readonly and older.values() == {"recall.entity_boost": 1.8}
    with pytest.raises(ParamError, match="newer version"):
        older.write("recall.entity_boost", None)


def test_a_file_that_cannot_be_opened_costs_the_learned_values_not_the_start(
    tmp_path: Path,
) -> None:
    from dodaios.self_change import wiring

    (tmp_path / "params.db").write_bytes(b"this is not a database")
    assert wiring._install_params(tmp_path) is None
    assert params.installed() is None and params.get("recall.turn_limit") == 6


# ------------------------------------------------------------ the registry


def test_a_parameter_change_is_recorded_but_not_applied_before_it_is_measured(
    tmp_path: Path,
) -> None:
    store = params.install(tmp_path)
    registry = SelfChangeRegistry(tmp_path)
    registry.register_handler(Surface.PARAMETER, store)
    text = params.text_for(params.INDEX.by_name("recall.turn_limit"), 4)
    change = registry.propose(Draft(Surface.PARAMETER, "recall.turn_limit", text, author="tuner"))
    assert change.state is State.PROPOSED and not change.core
    assert params.get("recall.turn_limit") == 6

    for target, after in (
        ("recall.turn_limit", '{"base":6,"value":99}'),
        ("recall.turn_limit", '{"base":6,"value":"many"}'),
        ("recall.no_such_thing", '{"base":1,"value":1}'),
        ("recall.turn_limit", "seven"),
    ):
        blocked = registry.propose(Draft(Surface.PARAMETER, target, after, author="tuner"))
        assert blocked.state is State.BLOCKED, (target, after)
    registry.close()


# ---------------------------------------------- the vault reads its values


@pytest.fixture
def vault(tmp_path: Path):
    v = MemoryVault(tmp_path / "vault.db")
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


def test_recall_follows_the_values_in_effect(vault: MemoryVault) -> None:
    for i in range(20):
        vault.remember(f"Concert number {i} with the jazz band was great.", "episode")
    assert len(vault_runtime.recall_for(vault, "jazz concert").chosen) == 6
    with overlay.active(overlay.Overlay(params={"recall.turn_limit": 2})):
        found = vault_runtime.recall_for(vault, "jazz concert")
        assert len(found.chosen) == 2 and found.shows(found.chosen[0].id)
        assert found.chars == len(vault_runtime.turn_block("jazz concert"))
    with overlay.active(overlay.Overlay(params={"recall.turn_max_chars": 300})):
        assert vault_runtime.recall_for(vault, "jazz concert").chars <= 300 + 200


def test_a_benchmark_run_counts_nothing_as_used_and_leaves_the_cache_alone(
    vault: MemoryVault,
) -> None:
    vault.remember("I live in Berlin.", "profile")
    vault.remember("We hiked the Zugspitze with Lea last summer.", "episode", entities=["Lea"])
    live_block = vault_runtime.prompt_block()
    generation = dict(vault_runtime._cache)
    with overlay.active(overlay.FACTORY):
        assert "Zugspitze" in vault_runtime.turn_block("Zugspitze hike with Lea")
        assert vault_runtime.prompt_block() == live_block
    assert all(m.use_count == 0 for m in vault.list())
    assert vault_runtime._cache == generation

    copy = MemoryVault(vault.path)  # a second handle, as a benchmark run opens one
    vault_runtime._cache.clear()
    vault_runtime.prompt_block(vault=copy)
    assert vault_runtime._cache == {}  # a read of another vault never fills the live cache
    assert "Zugspitze" in vault_runtime.turn_block("Zugspitze hike with Lea", vault=copy)
    assert all(m.use_count == 0 for m in vault.list())

    assert "Zugspitze" in vault_runtime.turn_block("Zugspitze hike with Lea")
    assert sum(m.use_count for m in vault.list()) == 1  # a live turn still counts
    copy.close()
