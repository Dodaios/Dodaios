"""The person's clock without a UI zone, and deciding only while the person is quiet in Dodaios."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from dodaios.self_build import Kind, State, clock, loop
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


# ------------------------------------------------------------------ quiet: the person in Dodaios


async def test_decide_waits_while_the_person_talks_to_dodaios(world: Any) -> None:
    world.brain.answers = [ROUTINE_ANSWER]
    readings: list[float | None] = [10.0]
    world.loop._idle = lambda: readings[0]
    await _weekly_sales(world)
    assert world.loop._queue  # a need waits
    await world.loop._when_quiet()
    assert world.brain.decide_calls == 0 and world.loop._queue
    assert world.loop._timer is not None  # looks again after another quiet stretch

    readings[0] = 120.0  # quiet in Dodaios, whatever the mouse does elsewhere
    await world.loop._when_quiet()
    await world.loop.drain()
    assert world.brain.decide_calls == 1 and not world.loop._queue
    assert world.loop._queued_at is None
    assert len(world.service.ledger.list(kinds=[Kind.ROUTINE])) == 1


async def test_no_activity_seen_since_start_is_quiet(world: Any) -> None:
    world.brain.answers = [ROUTINE_ANSWER]
    world.loop._idle = lambda: None
    await _weekly_sales(world)
    await world.loop._when_quiet()
    assert world.brain.decide_calls == 1


async def test_constant_activity_still_decides_within_the_hard_wait(
    world: Any, monkeypatch
) -> None:
    world.brain.answers = [ROUTINE_ANSWER]
    world.loop._idle = lambda: 0.0  # talking to Dodaios the whole time
    await _weekly_sales(world)
    clock_now = [loop.time.monotonic()]
    monkeypatch.setattr(loop.time, "monotonic", lambda: clock_now[0])
    world.loop._queued_at = clock_now[0]
    await world.loop._when_quiet()
    assert world.brain.decide_calls == 0
    # Re-armed, never later than the deadline.
    clock_now[0] += loop.MAX_WAIT_S - 30
    world.loop._arm()
    assert world.loop._timer is not None
    assert world.loop._timer.when() - asyncio.get_running_loop().time() <= 31
    clock_now[0] += 31
    await world.loop._when_quiet()
    assert world.brain.decide_calls == 1


async def test_turns_keep_the_timer_short_of_the_deadline(world: Any, monkeypatch) -> None:
    clock_now = [1000.0]
    monkeypatch.setattr(loop.time, "monotonic", lambda: clock_now[0])
    world.loop._queue["x"] = object()  # type: ignore[assignment]
    world.loop._queued_at = None
    world.loop._arm()
    assert world.loop._queued_at == 1000.0
    first = world.loop._timer.when() - asyncio.get_running_loop().time()
    assert 85 <= first <= 90.5
    clock_now[0] += loop.MAX_WAIT_S + 5  # every later turn re-arms; the deadline holds
    world.loop._arm()
    assert world.loop._timer.when() - asyncio.get_running_loop().time() <= 0.5
    world.loop._timer.cancel()
    world.loop._queue.clear()


async def test_an_unreadable_presence_reading_does_not_block_deciding(world: Any) -> None:
    world.brain.answers = [ROUTINE_ANSWER]

    def broken() -> float:
        raise OSError("no reading")

    world.loop._idle = broken
    await _weekly_sales(world)
    await world.loop._when_quiet()
    assert world.brain.decide_calls == 1


async def test_turns_and_calls_mark_the_person_present(world: Any) -> None:
    from types import SimpleNamespace

    from dodaios.core import presence

    presence.reset_for_tests()
    assert presence.idle_s() is None
    await _weekly_sales(world)  # old turns: not "just now"
    assert presence.idle_s() > loop.QUIET_S
    await world.loop._on_voice_started(SimpleNamespace(session_id="s1"))
    assert presence.idle_s() == 0.0  # an open call is talking to Dodaios
    world.loop._idle = loop._dodaios_idle_s
    assert world.loop._busy()
    await world.loop._on_voice_ended(SimpleNamespace(session_id="s1"))
    assert not presence.in_call() and presence.idle_s() < 5
    presence.reset_for_tests()


def test_presence_readings() -> None:
    from dodaios.core import presence

    presence.reset_for_tests()
    presence.note(presence.PANE, at=100.0)
    presence.note(presence.TURN, at=50.0)
    presence.note(presence.TURN, at=40.0)  # older stamps never move it back
    assert presence.idle_s(now=160.0) == 60.0
    assert presence.idle_s(sources=[presence.TURN], now=160.0) == 110.0
    assert presence.idle_s(sources=[presence.PANE], now=160.0) == 60.0
    presence.call_started("c")
    assert presence.idle_s(sources=[presence.TURN]) == 0.0
    assert presence.idle_s(sources=[presence.PANE], now=160.0) == 60.0  # a call is not typing
    presence.call_ended("c")
    assert not presence.in_call()
    presence.reset_for_tests()


# ------------------------------------------------------------------ the code builder's idle


def test_the_code_builder_waits_for_the_person_not_for_agent_prompts(monkeypatch) -> None:
    from types import SimpleNamespace

    from dodaios.core import presence
    from dodaios.self_build.code import idle

    presence.reset_for_tests()
    monkeypatch.setattr(idle, "os_idle_s", lambda: None)  # headless: no OS reading
    # Jarvis typed a brief into a pane a second ago: that stamps last_input_at,
    # but it is not the person at the keyboard.
    term = SimpleNamespace(last_input_at=loop.time.time())
    registry = SimpleNamespace(sessions=[SimpleNamespace(terminals=[term])])
    from dodaios.agentic_ide import session as ide_session

    monkeypatch.setattr(ide_session, "get_registry", lambda: registry)
    assert idle.person_idle(60)
    presence.note(presence.PANE)  # the person typed in a pane's terminal
    assert not idle.person_idle(60)
    presence.reset_for_tests()
    presence.note(presence.TURN)  # the person spoke to Dodaios
    assert not idle.person_idle(60)
    presence.reset_for_tests()
    monkeypatch.setattr(idle, "os_idle_s", lambda: 3.0)  # someone at the keyboard elsewhere
    assert not idle.person_idle(60)
    monkeypatch.setattr(idle, "os_idle_s", lambda: 3600.0)
    assert idle.person_idle(60)
