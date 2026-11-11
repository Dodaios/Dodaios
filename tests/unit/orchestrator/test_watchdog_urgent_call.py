"""A critical watchdog finding reaches the opt-in urgent caller once; nothing else does."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from dodaios.notify import wiring
from dodaios.orchestrator.watchdog import checks, live
from dodaios.orchestrator.watchdog.checks import JobView, Snapshot, TurnView
from dodaios.orchestrator.watchdog.store import WatchdogStore
from dodaios.orchestrator.watchdog.supervisor import Watchdog
from dodaios.safety.stop_hold import StopHolds, set_stop_holds, stop_holds

NOW = 1_800_000_000_000
MIN = 60_000


class _Sources:
    def __init__(self, snap: Snapshot) -> None:
        self.snap = snap

    def snapshot(self, store: Any, now: int) -> Snapshot:
        return self.snap

    def drain_log(self) -> list[str]:
        return []


class _Actions:
    def __init__(self) -> None:
        self.urgent: list[str] = []

    def can_repair(self, finding: Any) -> bool:
        return False

    def repair(self, finding: Any) -> str | None:
        return None

    def post_notice(self, payload: dict[str, Any]) -> bool:
        return True

    def quiet_hours(self) -> bool:
        return False

    def judge(self, goal: str, evidence: str) -> None:
        return None

    def report_urgent(self, row: dict[str, Any]) -> None:
        self.urgent.append(row["key"])


def _loop_turn() -> TurnView:
    return TurnView(
        session_id="s1", turn_id="t1", surface="jarvis", started_ms=NOW - MIN,
        last_event_ms=NOW, running=True, steerable=False, waiting_on_person=False,
        tool_signatures=tuple(["Read:abc"] * 6),
    )


def _dog(tmp_path: Any, snap: Snapshot) -> tuple[Watchdog, _Actions, dict[str, int]]:
    actions, clock = _Actions(), {"now": NOW}
    dog = Watchdog(
        tmp_path, _Sources(snap), actions, store=WatchdogStore(":memory:"), boot_id="b",
        clock=lambda: clock["now"],
    )
    return dog, actions, clock


def test_critical_finding_is_reported_once(tmp_path: Any) -> None:
    dog, actions, clock = _dog(tmp_path, Snapshot(NOW, turns=[_loop_turn()]))
    dog.scan()
    clock["now"] += 5 * MIN
    dog.scan()
    assert len(actions.urgent) == 1 and actions.urgent[0].startswith(checks.KIND_LOOP)


def test_non_critical_finding_is_never_reported(tmp_path: Any) -> None:
    job = JobView("j1", "mission", "Brief", "running", "s1", NOW - 5 * 3600_000, NOW - 6 * 3600_000, "")
    dog, actions, _clock = _dog(tmp_path, Snapshot(NOW, jobs=[job]))
    assert dog.scan()["notified"] == 1
    assert actions.urgent == []


class _Caller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def report_finding(self, ref: str, summary: str, severity: str) -> str:
        self.calls.append((ref, summary, severity))
        return "rang"


_ROW = {"key": "tool_loop:s1:t1", "kind": checks.KIND_LOOP, "title": "A turn repeats", "open_ref": "s1"}


async def _live(caller: Any, monkeypatch: Any) -> list[Any]:
    monkeypatch.setattr(wiring, "_urgent_caller", caller)
    loop = asyncio.get_running_loop()
    hop = lambda factory, *_a: asyncio.run_coroutine_threadsafe(factory(), loop).result(5)  # noqa: E731
    actions = live.LiveActions(SimpleNamespace(chat_service=lambda: None), hop)  # type: ignore[arg-type]
    await asyncio.to_thread(actions.report_urgent, _ROW)
    await asyncio.sleep(0.05)
    return []


async def test_live_hands_the_finding_to_the_caller(monkeypatch: Any) -> None:
    caller = _Caller()
    await _live(caller, monkeypatch)
    assert caller.calls == [("tool_loop:s1:t1", "A turn repeats", "critical")]


async def test_nothing_happens_when_the_feature_is_not_installed(monkeypatch: Any) -> None:
    await _live(None, monkeypatch)  # the caller does not exist: no error, nothing to assert


async def test_an_everything_hold_suppresses_the_call(monkeypatch: Any, tmp_path: Any) -> None:
    caller = _Caller()
    set_stop_holds(StopHolds(tmp_path / "holds.json"))
    stop_holds().hold("everything", reason="stop", source="test")
    try:
        await _live(caller, monkeypatch)
    finally:
        set_stop_holds(None)
    assert caller.calls == []


async def test_off_by_default_the_real_caller_does_nothing() -> None:
    from dodaios.notify.settings import NotifySettings
    from dodaios.notify.urgent_call import OFF, UrgentCaller

    async def ring(*_a: Any) -> bool:
        raise AssertionError("must not ring")

    caller = UrgentCaller(
        ring_desktop=ring, ring_phone=ring, is_open=lambda _e: True,
        phone_allowed=lambda: True, settings=NotifySettings,
    )
    assert await caller.report_finding("k", "A turn repeats", "critical") == OFF
