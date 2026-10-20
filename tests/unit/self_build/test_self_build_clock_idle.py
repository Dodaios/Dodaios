"""The person's clock without a UI zone, and deciding only while the person is away."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from dodaios.self_build import Kind, State, clock
from dodaios.self_build.miner import Miner, Observation
from dodaios.self_build.signals import UNKNOWN_CLOCK, SignalStore

from .test_self_build_loop import (  # noqa: F401 - _person_zone is an autouse fixture
    ROUTINE_ANSWER,
    _mondays,
    _ms,
    _person_zone,
    _settle,
    _weekly_sales,
)


@pytest.fixture(autouse=True)
def _fresh_clock():
    clock.reset_for_tests()
    yield
    clock.reset_for_tests()


def _weekly(miner: Miner) -> list[Any]:
    needs: list[Any] = []
    for monday in _mondays():
        _, needs = miner.observe(
            Observation(
                text="Show me the sales summary for last week",
                channel="voice",
                conversation=f"voice:{monday}",
                ts_ms=_ms(monday, 8, 30),
                tools=("mcp:crm/report",),
            )
        )
    return needs


# ------------------------------------------------------------------ the computer's zone


def test_the_computers_zone_matches_what_the_os_reports() -> None:
    name = clock.system_zone_name()
    assert name, "no IANA zone matches this computer's offsets"
    now = datetime.now(UTC)
    assert now.astimezone(ZoneInfo(name)).utcoffset() == datetime.now().astimezone().utcoffset()


def test_a_tz_variable_that_does_not_match_the_os_is_not_trusted(monkeypatch) -> None:
    here = datetime.now().astimezone().utcoffset()
    now = datetime.now(UTC)
    wrong = next(
        name
        for name in ("Pacific/Kiritimati", "Etc/GMT+12")
        if now.astimezone(ZoneInfo(name)).utcoffset() != here
    )
    monkeypatch.setattr(clock, "_tz_variable", lambda: wrong)
    clock.reset_for_tests()
    assert clock.system_zone_name() != wrong


def test_windows_zone_keys_map_to_real_zones() -> None:
    for key, name in clock.WINDOWS_ZONES.items():
        assert clock._zone(name) is not None, key


def test_habits_use_the_computers_zone_until_the_ui_reports_one(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", None)
    monkeypatch.setattr(clock, "system_zone_name", lambda: "UTC")
    with caplog.at_level(logging.INFO, logger="dodaios.self_build.clock"):
        (need,) = _weekly(Miner(SignalStore(tmp_path / "s.db")))
    assert "weekly" in need.reasons and Kind.ROUTINE in need.rungs
    assert need.schedule == {"kind": "calendar", "local_time": "08:15", "weekdays": [0]}
    logged = [r.getMessage() for r in caplog.records if "has not reported" in r.getMessage()]
    assert len(logged) == 1 and "UTC" in logged[0]  # said once, not per turn


def test_the_ui_zone_wins_over_the_computers(monkeypatch) -> None:
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", "Asia/Tokyo")
    monkeypatch.setattr(clock, "system_zone_name", lambda: "UTC")
    assert clock.person_zone_name() == "Asia/Tokyo"


def test_turns_filed_without_a_clock_get_one_later(tmp_path: Path, monkeypatch) -> None:
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", None)
    monkeypatch.setattr(clock, "system_zone_name", lambda: None)
    store = SignalStore(tmp_path / "s.db")
    miner = Miner(store)
    (need,) = _weekly(miner)
    assert need.schedule is None
    assert {t.minute for t in store.recent_turns(since_ms=0)} == {UNKNOWN_CLOCK}
    monkeypatch.setattr(context, "_reported_ui_timezone", "UTC")
    assert store.fill_clocks() == 3
    assert {t.minute for t in store.recent_turns(since_ms=0)} == {8 * 60 + 30}
    found = miner.cluster_need(need.cluster)
    assert found is not None and "weekly" in found.reasons


async def test_a_routine_without_a_ui_zone_runs_on_the_computers(world: Any, monkeypatch) -> None:
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", None)
    monkeypatch.setattr(clock, "system_zone_name", lambda: "UTC")
    world.brain.answers = [ROUTINE_ANSWER]
    await _weekly_sales(world)
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    assert record.state == State.TRIAL, record.note  # never stuck in "building"
    spec = world.scheduler.specs[record.artefact["task_id"]]
    assert spec.trigger.timezone == "UTC"


# ------------------------------------------------------------------ idle


async def test_decide_waits_while_the_person_is_at_the_keyboard(world: Any) -> None:
    world.brain.answers = [ROUTINE_ANSWER]
    asked: list[float] = []

    def busy(seconds: float) -> bool:
        asked.append(seconds)
        return False

    world.loop._idle = busy
    await _weekly_sales(world)
    assert world.loop._queue  # a need waits
    await world.loop._when_quiet()
    assert asked == [90.0]
    assert world.brain.decide_calls == 0 and world.loop._queue
    assert world.loop._timer is not None  # looks again after another quiet stretch

    world.loop._idle = lambda _seconds: True
    await world.loop._when_quiet()
    await world.loop.drain()
    assert world.brain.decide_calls == 1 and not world.loop._queue
    assert len(world.service.ledger.list(kinds=[Kind.ROUTINE])) == 1


async def test_an_unreadable_idle_clock_does_not_block_deciding(world: Any) -> None:
    world.brain.answers = [ROUTINE_ANSWER]

    def broken(_seconds: float) -> bool:
        raise OSError("no input clock")

    world.loop._idle = broken
    await _weekly_sales(world)
    await world.loop._when_quiet()
    assert world.brain.decide_calls == 1
