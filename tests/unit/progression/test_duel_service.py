"""``record_duel``: one row and one payment per set, within every cap (WP21 A21.1-A21.3)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import pytest

from dodaios.core import events
from dodaios.core.bus import EventBus
from dodaios.core.events import Event, ProgressionAwarded
from dodaios.progression.duel_stats import DuelResultError
from dodaios.progression.service import ProgressionService


def duel(match_id: str = "m_1", **over: Any) -> dict[str, Any]:
    """A ``duel.result`` payload as bridge-protocol 10 shows it: a won set against hard."""
    data: dict[str, Any] = {
        "match_id": match_id,
        "session_id": "s_1",
        "set_index": 1,
        "mode": "deathmatch_1v1",
        "ruleset": "endless/1",
        "opponent": {"kind": "bot", "tier": "hard", "adaptive": False},
        "started_at": 1793612200.0,
        "ended_at": 1793612500.0,
        "match_time_s": 296.4,
        "end_reason": "set_complete",
        "outcome": "won",
        "score": {"player": 10, "opponent": 7},
        "stats": {
            "kills": 10,
            "deaths": 7,
            "headshots": 4,
            "finishers": 0,
            "melee_kills": 1,
            "shots_fired": 540,
            "shots_hit": 201,
            "damage_dealt": 2760,
            "damage_taken": 2210,
            "walls_breached": 2,
            "bulwarks_placed": 3,
            "best_streak": 4,
        },
        "weapons": [
            {
                "weapon_id": "graveline",
                "kills": 8,
                "headshots": 4,
                "shots_fired": 410,
                "shots_hit": 152,
            }
        ],
        "build": {"version": "0.1.0", "changelist": "a1b2c3d"},
    }
    for key, value in over.items():
        if key in ("stats", "opponent", "score") and isinstance(value, dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return data


class Clock:
    def __init__(self, start_ms: int = 1_790_000_000_000) -> None:
        self.now = start_ms

    def __call__(self) -> int:
        return self.now


@pytest.fixture
async def setup(tmp_path: Path):
    bus = EventBus()
    seen: list[ProgressionAwarded] = []

    async def on_award(event: ProgressionAwarded) -> None:
        seen.append(event)

    bus.subscribe(ProgressionAwarded, on_award)
    clock = Clock()
    service = ProgressionService(tmp_path / "progression.db", bus=bus, clock=clock)
    try:
        yield service, bus, seen, clock
    finally:
        service.close()


def _person_xp(service: ProgressionService) -> int:
    return next((r["xp"] for r in service.snapshot() if r["subject_id"] == "person"), 0)


def _ledger(service: ProgressionService) -> list[tuple[str, int]]:
    return [(r["source"], r["xp"]) for r in service.store.recent(limit=200)]


# ------------------------------------------------------------------ A21.1 idempotency


async def test_a_hundred_sends_of_one_match_store_one_row_and_pay_once(setup):
    service, _, seen, _ = setup
    first = await service.record_duel(duel("m_same"))
    replies = [await service.record_duel(duel("m_same")) for _ in range(99)]
    assert service.duels.count() == 1
    assert _ledger(service) == [("duel_won", 60)]
    assert len(seen) == 1
    assert first["awards"] == [{"xp_source": "duel_won", "xp": 60}]
    for reply in replies:
        assert reply["recorded"] is True
        assert reply["awards"] == first["awards"]
        assert reply["duel_stats"]["matches"] == 1


async def test_concurrent_sends_of_one_match_still_pay_once(setup):
    service, _, _, _ = setup
    await asyncio.gather(*(service.record_duel(duel("m_race")) for _ in range(100)))
    assert service.duels.count() == 1
    assert _ledger(service) == [("duel_won", 60)]
    assert _person_xp(service) == 60


async def test_a_row_whose_awards_a_crash_cut_off_is_paid_on_the_next_send(setup):
    service, _, _, _ = setup
    from dodaios.progression.duel_stats import parse_duel_result

    service.duels.insert(parse_duel_result(duel("m_cut")))  # stored, never paid
    reply = await service.record_duel(duel("m_cut"))
    assert reply["awards"][0]["xp_source"] == "duel_won"
    again = await service.record_duel(duel("m_cut"))
    assert again["awards"] == reply["awards"]
    assert _ledger(service) == [("duel_won", 60)]


async def test_a_crash_after_paying_before_finish_keeps_the_paid_awards(setup, monkeypatch):
    service, _, _, _ = setup
    real_finish = service.duels.finish
    monkeypatch.setattr(service.duels, "finish", lambda *a, **k: None)  # the crash
    first = await service.record_duel(duel("m_paid"))
    assert _ledger(service) == [("duel_won", 60)]
    assert service.duels.get("m_paid")["awards_done"] is False
    monkeypatch.setattr(service.duels, "finish", real_finish)
    again = await service.record_duel(duel("m_paid"))
    assert [(a["xp_source"], a["xp"]) for a in again["awards"]] == [("duel_won", 60)]
    assert again["awards"] == first["awards"]
    stored = service.duels.get("m_paid")
    assert stored["awards_done"] is True
    assert [(a["xp_source"], a["xp"]) for a in stored["awards"]] == [("duel_won", 60)]
    assert _ledger(service) == [("duel_won", 60)]


# ------------------------------------------------------------------ A21.2 XP


@pytest.mark.parametrize(
    ("tier", "adaptive", "xp"),
    [
        ("normal", False, 40),
        ("hard", False, 60),
        ("elite", False, 80),
        ("elite", True, 60),
        ("mystery", False, 40),
    ],
)
async def test_a_won_set_pays_the_tier_multiplier(setup, tier, adaptive, xp):
    service, _, _, _ = setup
    reply = await service.record_duel(duel(opponent={"tier": tier, "adaptive": adaptive}))
    assert reply["awards"] == [{"xp_source": "duel_won", "xp": xp}]


async def test_a_lost_set_pays_duel_lost_and_finishers_pay_in_a_paying_set(setup):
    service, _, _, _ = setup
    await service.record_duel(duel("m_l", outcome="lost", stats={"finishers": 2}))
    assert _ledger(service) == [("duel_lost", 10), ("duel_finisher", 10)]


async def test_the_daily_caps_hold(setup):
    service, _, _, clock = setup
    for i in range(10):  # 10 x 80 (elite) asks for 800; the cap is 200
        await service.record_duel(duel(f"w{i}", opponent={"tier": "elite"}, stats={"finishers": 3}))
        clock.now += 1000
    for i in range(10):  # 10 x 10 asks for 100; the cap is 50
        await service.record_duel(duel(f"l{i}", outcome="lost"))
        clock.now += 1000
    paid: dict[str, int] = {}
    for source, xp in _ledger(service):
        paid[source] = paid.get(source, 0) + xp
    assert paid == {"duel_won": 200, "duel_lost": 50, "duel_finisher": 25}
    # The next local day the caps open again.
    clock.now += 86_400_000
    reply = await service.record_duel(duel("next_day"))
    assert [a["xp"] for a in reply["awards"]] == [60]


async def test_a_set_under_sixty_seconds_pays_nothing_but_counts(setup):
    service, _, _, _ = setup
    reply = await service.record_duel(
        duel("short", match_time_s=59.0, stats={"kills": 10, "finishers": 1})
    )
    assert reply["awards"] == []
    assert _person_xp(service) == 0
    assert reply["duel_stats"]["matches"] == 1 and reply["duel_stats"]["wins"] == 1


async def test_an_unfinished_set_pays_nothing_and_still_updates_the_stats(setup):
    service, _, _, _ = setup
    reply = await service.record_duel(
        duel(
            "left", outcome="unfinished", end_reason="player_left", stats={"kills": 3, "deaths": 2}
        )
    )
    assert reply["awards"] == []
    assert _person_xp(service) == 0
    stats = reply["duel_stats"]
    assert (stats["matches"], stats["unfinished"], stats["kills"], stats["deaths"]) == (1, 1, 3, 2)


async def test_a_mode_that_does_not_pay_still_counts(setup):
    service, _, _, _ = setup
    reply = await service.record_duel(duel("tdm", mode="team_deathmatch"))
    assert reply["awards"] == [] and reply["duel_stats"]["wins"] == 1


# ------------------------------------------------------------------ A21.3 clamp


async def test_more_than_one_kill_per_two_seconds_is_clamped_and_logged(setup, caplog):
    service, _, _, _ = setup
    caplog.set_level(logging.WARNING, logger="dodaios.progression.service")
    reply = await service.record_duel(
        duel(
            "fast",
            match_time_s=100.0,
            stats={"kills": 80, "deaths": 60, "headshots": 70, "best_streak": 80},
            score={"player": 80},
        )
    )
    stats = reply["duel_stats"]
    assert (stats["kills"], stats["deaths"], stats["headshots"], stats["best_streak"]) == (
        50,
        50,
        50,
        50,
    )
    row = service.duels.get("fast")
    assert row is not None and "kills: 80 -> 50" in row["clamped"]
    assert any(
        "duel fast clamped" in r.getMessage() and "kills: 80 -> 50" in r.getMessage()
        for r in caplog.records
    )
    # Weapon kills never exceed the set's kills.
    assert service.duel_stats()["by_weapon"]["graveline"]["kills"] <= 50


async def test_a_plausible_set_is_not_clamped(setup, caplog):
    service, _, _, _ = setup
    caplog.set_level(logging.WARNING, logger="dodaios.progression.service")
    await service.record_duel(duel("ok"))
    assert service.duels.get("ok")["clamped"] == []
    assert not [r for r in caplog.records if "clamped" in r.getMessage()]


# ------------------------------------------------------------------ refusals and events


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"match_id": ""},
        {"match_id": "x", "outcome": "draw"},
        {"match_id": "x", "outcome": "won", "stats": {"kills": "ten"}},
        {"match_id": "x", "outcome": "won", "opponent": {"adaptive": "yes"}},
        {"match_id": "x", "outcome": "won", "weapons": {}},
    ],
)
async def test_a_payload_that_is_no_result_is_a_bad_request(setup, bad):
    service, _, _, _ = setup
    with pytest.raises(DuelResultError) as err:
        await service.record_duel(bad)
    assert err.value.code == "bad_request"
    assert service.duels.count() == 0


async def test_every_award_is_announced_and_the_set_is_published_once(setup, monkeypatch):
    service, bus, seen, _ = setup

    @dataclass(frozen=True, slots=True, kw_only=True)
    class FakeVerseDuelRecorded(Event):
        match_id: str = ""
        outcome: str = ""
        kills: int = 0
        deaths: int = 0

    monkeypatch.setattr(events, "VerseDuelRecorded", FakeVerseDuelRecorded, raising=False)
    published: list[Any] = []

    async def on_duel(event: Any) -> None:
        published.append(event)

    bus.subscribe(FakeVerseDuelRecorded, on_duel)
    for _ in range(3):
        await service.record_duel(duel("m_ev", stats={"finishers": 1}))
    assert [(e.xp_source, e.xp) for e in seen] == [("duel_won", 60), ("duel_finisher", 5)]
    assert [(e.match_id, e.outcome, e.kills, e.deaths) for e in published] == [
        ("m_ev", "won", 10, 7)
    ]


async def test_without_the_event_type_the_result_still_records(setup, monkeypatch):
    service, _, _, _ = setup
    monkeypatch.delattr(events, "VerseDuelRecorded", raising=False)
    reply = await service.record_duel(duel("m_noevent"))
    assert reply["recorded"] is True
