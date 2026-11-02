"""The duel stats store: migration, totals, per tier and per weapon (WP21.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dodaios.progression.duel_stats import (
    SCHEMA_VERSION,
    DuelResultError,
    DuelStatsStore,
    parse_duel_result,
)
from dodaios.progression.rules import DUEL_TIER_MULTIPLIERS, duel_awards, duel_tier_key
from dodaios.progression.store import ProgressionStore

from .test_duel_service import duel


@pytest.fixture
def store(tmp_path: Path):
    s = DuelStatsStore(tmp_path / "progression.db", clock=lambda: 1_790_000_000_000)
    yield s
    s.close()


def test_the_migration_runs_once_and_shares_the_ledger_database(tmp_path: Path):
    path = tmp_path / "progression.db"
    ledger = ProgressionStore(path)
    assert ledger.latest_seq() == 0
    first = DuelStatsStore(path)
    assert first.schema_version() == SCHEMA_VERSION
    first.insert(parse_duel_result(duel("a")))
    first.close()
    again = DuelStatsStore(path)  # reopening keeps the rows and the version
    assert again.schema_version() == SCHEMA_VERSION and again.count() == 1
    again.close()
    ledger.close()
    tables = {
        row[0]
        for row in sqlite3.connect(path).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"progression_awards", "duel_results", "duel_weapons", "duel_schema"} <= tables


def test_one_match_id_is_one_row(store: DuelStatsStore):
    result = parse_duel_result(duel("same"))
    assert store.insert(result) is True
    assert store.insert(result) is False
    assert store.count() == 1


def test_totals_add_up_per_tier_and_per_weapon(store: DuelStatsStore):
    store.insert(parse_duel_result(duel("w1")))
    store.insert(
        parse_duel_result(
            duel(
                "l1",
                outcome="lost",
                stats={"kills": 6, "deaths": 10, "headshots": 2, "finishers": 1, "best_streak": 6},
                weapons=[
                    {"weapon_id": "graveline", "kills": 4, "shots_fired": 100, "shots_hit": 40},
                    {"weapon_id": "sidearm_k", "kills": 2, "shots_fired": 20, "shots_hit": 10},
                ],
            )
        )
    )
    store.insert(
        parse_duel_result(
            duel(
                "u1",
                outcome="unfinished",
                opponent={"tier": "elite", "adaptive": True},
                stats={"kills": 1, "deaths": 0, "headshots": 0, "best_streak": 1},
                weapons=[],
            )
        )
    )
    totals = store.totals()
    assert {k: totals[k] for k in ("matches", "wins", "losses", "unfinished")} == {
        "matches": 3,
        "wins": 1,
        "losses": 1,
        "unfinished": 1,
    }
    assert (totals["kills"], totals["deaths"], totals["headshots"], totals["finishers"]) == (
        17,
        17,
        6,
        1,
    )
    assert totals["kd"] == 1.0 and totals["best_streak"] == 6
    assert set(totals["by_tier"]) == {"hard", "adaptive"}
    assert totals["by_tier"]["hard"]["matches"] == 2
    assert totals["by_tier"]["adaptive"]["unfinished"] == 1
    assert totals["by_weapon"]["graveline"]["kills"] == 12
    assert totals["by_weapon"]["sidearm_k"] == {
        "kills": 2,
        "headshots": 0,
        "shots_fired": 20,
        "shots_hit": 10,
        "accuracy": 0.5,
    }


def test_an_empty_store_reads_zeroes(store: DuelStatsStore):
    totals = store.totals()
    assert totals["matches"] == 0 and totals["kd"] == 0.0
    assert totals["by_tier"] == {} and totals["by_weapon"] == {}
    assert store.recent() == []


def test_recent_lists_newest_first_with_weapons_and_awards(tmp_path: Path):
    now = {"ms": 1_000}
    store = DuelStatsStore(tmp_path / "p.db", clock=lambda: now["ms"])
    for i in range(25):
        store.insert(parse_duel_result(duel(f"m{i:02d}", set_index=i + 1)))
        store.finish(f"m{i:02d}", [{"xp_source": "duel_won", "xp": 60, "seq": i + 1}])
        now["ms"] += 10
    rows = store.recent(limit=20)
    assert len(rows) == 20 and rows[0]["match_id"] == "m24" and rows[-1]["match_id"] == "m05"
    assert rows[0]["xp"] == 60 and rows[0]["weapons"][0]["weapon_id"] == "graveline"
    assert rows[0]["opponent"] == {"kind": "bot", "tier": "hard", "adaptive": False}
    store.close()


def test_parsing_keeps_unknown_end_reasons_as_unknown_and_merges_weapon_lines():
    result = parse_duel_result(
        duel(
            "x",
            end_reason="meteor",
            weapons=[
                {"weapon_id": "graveline", "kills": 3},
                {"weapon_id": "graveline", "kills": 2, "headshots": 1},
                {"weapon_id": "", "kills": 9},
            ],
        )
    )
    assert result.end_reason == "unknown"
    assert [(w.weapon_id, w.kills, w.headshots) for w in result.weapons] == [("graveline", 5, 1)]


def test_negative_and_float_counts_are_floored_at_zero():
    result = parse_duel_result(duel("x", stats={"kills": -4, "deaths": 3.9}))
    assert result.stats["kills"] == 0 and result.stats["deaths"] == 3


def test_a_non_finite_number_is_refused():
    with pytest.raises(DuelResultError):
        parse_duel_result(duel("x", match_time_s=float("nan")))


def test_the_rulebook_pays_per_the_contract():
    assert DUEL_TIER_MULTIPLIERS == {"normal": 1.0, "hard": 1.5, "elite": 2.0, "adaptive": 1.5}
    assert duel_tier_key("bot", "elite", True) == "adaptive"
    assert duel_tier_key("person", "", False) == "person"
    pay = dict(
        duel_awards(
            mode="deathmatch_1v1", outcome="won", match_time_s=60.0, tier_key="hard", finishers=2
        )
    )
    assert pay == {"duel_won": 60, "duel_finisher": 10}
    assert (
        duel_awards(
            mode="deathmatch_1v1", outcome="won", match_time_s=59.99, tier_key="hard", finishers=0
        )
        == []
    )
    assert (
        duel_awards(
            mode="deathmatch_1v1",
            outcome="unfinished",
            match_time_s=600.0,
            tier_key="hard",
            finishers=3,
        )
        == []
    )
