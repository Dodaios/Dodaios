"""Away-parking: pause routines whose results nobody reads.

A routine that keeps producing results while the person has not looked at
that agent's routine results for a while spends seats on reports that go
unread. When one of those routines fires again, this module pauses the
agent's unread time-based routines and records why, once per away period.
The person then sees one banner in the agent's routine list with three
choices: keep running, keep paused, or keep running and never ask again.

Deterministic code only: it reads task steps and one chat tail, writes the
pause through the scheduler and a JSON record into ``society_meta``. It never
calls a model, never bills anything and never speaks.

What counts as "the person looked":
* opening the agent's routine list or a routine's run history
  (``POST /agents/{id}/routines/seen``), and
* writing to the agent in its own chat.

What is never parked:
* runs the person started (Run now / Test run): the check is skipped;
* routines with a non-time trigger (webhooks, events, forms, sources), which
  serve something outside that the person set up to react to;
* a routine the person ran by hand within the window;
* goal-derived background work and routines that announce their result
  elsewhere (their result is read where it is delivered).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Final

from dodaios.core.trigger_context import CapacityDeferred

from .routine_history import parse_runs

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_DAYS",
    "ParkingState",
    "RoutineActivity",
    "RoutineParked",
    "activity_of",
    "apply_choice",
    "load_days",
    "load_state",
    "mark_seen",
    "maybe_park",
    "parking_candidates",
    "save_days",
    "save_state",
]

DAY_MS: Final[int] = 86_400_000
#: Default away window; ``0`` switches away-parking off.
DEFAULT_DAYS: Final[int] = 7
MAX_DAYS: Final[int] = 90
#: Fewer unread results than this is not "keeps producing results".
MIN_UNREAD_RESULTS: Final[int] = 3
#: Triggers that fire on their own clock. Everything else reacts to the outside.
TIME_TRIGGERS: Final[frozenset[str]] = frozenset({"every", "calendar", "cron"})

_DAYS_KEY: Final[str] = "routine_parking:days"
_AGENT_KEY: Final[str] = "routine_parking:agent:"
#: How long a parked run waits for its own task to leave ``running``.
_IDLE_WAIT_S: Final[float] = 120.0

#: Stable reason word for the skipped run's history line.
PARKED_CODE: Final[str] = "away_parked"

CHOICES: Final[frozenset[str]] = frozenset(
    {"keep_running", "keep_paused", "never_ask", "ask_again"}
)


class RoutineParked(CapacityDeferred):
    """The run was skipped because its agent's routines were parked."""


@dataclass
class ParkingState:
    """What away-parking remembers per agent (``society_meta`` JSON)."""

    seen_ms: int = 0
    parked_ms: int = 0
    parked_ids: list[str] = field(default_factory=list)
    unread: int = 0
    days: int = 0
    #: A park the person has not answered yet: the banner shows.
    banner: bool = False
    never_ask: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> ParkingState:
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:  # a corrupt parking file starts fresh with defaults
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls(
            seen_ms=int(data.get("seen_ms") or 0),
            parked_ms=int(data.get("parked_ms") or 0),
            parked_ids=[str(v) for v in data.get("parked_ids") or [] if v],
            unread=int(data.get("unread") or 0),
            days=int(data.get("days") or 0),
            banner=bool(data.get("banner")),
            never_ask=bool(data.get("never_ask")),
        )


@dataclass(frozen=True)
class RoutineActivity:
    """The facts the parking decision needs about one routine task."""

    task_id: str
    state: str
    trigger_type: str
    #: Finish times (ms) of runs that fired on their own and completed.
    result_ms: tuple[int, ...] = ()
    #: Start time (ms) of the newest run the person started, or 0.
    last_manual_ms: int = 0
    autonomous: bool = False
    announces: bool = False


def parking_candidates(
    activities: Iterable[RoutineActivity],
    *,
    seen_ms: int,
    now_ms: int,
    days: int,
    never_ask: bool = False,
) -> tuple[list[str], int]:
    """Which routines to park now, and how many unread results they made.

    Pure: the same facts always give the same answer. A routine qualifies when
    it fires on a clock, is live, made results after ``seen_ms`` and was not
    run by hand inside the window. The agent as a whole qualifies when those
    routines made at least :data:`MIN_UNREAD_RESULTS` unread results, the
    person has not looked for ``days`` days, and results are still coming in
    (the newest one is inside the window).
    """
    if days <= 0 or never_ask:
        return [], 0
    window = days * DAY_MS
    chosen: list[str] = []
    unread_times: list[int] = []
    for item in activities:
        if item.state not in ("scheduled", "running"):
            continue
        if item.trigger_type not in TIME_TRIGGERS or item.autonomous or item.announces:
            continue
        if item.last_manual_ms and item.last_manual_ms >= now_ms - window:
            continue
        unread = [at for at in item.result_ms if at > seen_ms]
        if not unread:
            continue
        chosen.append(item.task_id)
        unread_times.extend(unread)
    if len(unread_times) < MIN_UNREAD_RESULTS:
        return [], 0
    reference = seen_ms or min(unread_times)
    if now_ms - reference < window or max(unread_times) < now_ms - window:
        return [], 0
    return chosen, len(unread_times)


def activity_of(row: dict[str, Any]) -> RoutineActivity:
    """One routine's activity from its full task row (with ``steps``)."""
    spec: dict[str, Any] = {}
    raw = row.get("spec_json")
    if raw:
        try:
            spec = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except ValueError:  # an unreadable spec reads as a routine with no trigger
            spec = {}
    trigger = spec.get("trigger") or {}
    tags = [str(t) for t in spec.get("tags") or []]
    task_id = str(row.get("id") or "")
    runs = parse_runs(task_id, list(row.get("steps") or []))
    results = tuple(
        int(run.finished_ms)
        for run in runs
        if run.origin == "automatic" and run.status == "completed" and run.finished_ms
    )
    manual = max((int(run.started_ms or 0) for run in runs if run.origin == "manual"), default=0)
    return RoutineActivity(
        task_id=task_id,
        state=str(row.get("state") or ""),
        trigger_type=str(row.get("trigger_type") or trigger.get("type") or ""),
        result_ms=results,
        last_manual_ms=manual,
        autonomous="autonomous" in tags,
        announces=bool(spec.get("announce_on_success")),
    )


# ------------------------------------------------------------------ storage


async def load_days(society_store: Any) -> int:
    raw = await society_store.get_meta(_DAYS_KEY, "")
    try:
        days = int(raw) if raw != "" else DEFAULT_DAYS
    except ValueError:  # a non-numeric setting falls back to the default window
        days = DEFAULT_DAYS
    return max(0, min(MAX_DAYS, days))


async def save_days(society_store: Any, days: int) -> int:
    value = max(0, min(MAX_DAYS, int(days)))
    await society_store.set_meta(_DAYS_KEY, str(value))
    return value


async def load_state(society_store: Any, agent_id: str) -> ParkingState:
    return ParkingState.from_json(await society_store.get_meta(_AGENT_KEY + agent_id, ""))


async def save_state(society_store: Any, agent_id: str, state: ParkingState) -> None:
    await society_store.set_meta(_AGENT_KEY + agent_id, state.to_json())


async def mark_seen(society_store: Any, agent_id: str, now_ms: int | None = None) -> ParkingState:
    state = await load_state(society_store, agent_id)
    state.seen_ms = max(state.seen_ms, int(now_ms if now_ms is not None else _now_ms()))
    await save_state(society_store, agent_id, state)
    return state


def last_person_message_ms(chat_service: Any, session_id: str, *, tail: int = 300) -> int:
    """When the person last wrote in the agent's own chat (0 when unknown).

    Messages from Jarvis, teammates, chat controls and background results
    carry an ``origin`` or ``author``; the person's own typed messages do not.
    """
    store = getattr(chat_service, "store", None)
    if store is None or not session_id:
        return 0
    try:
        events = store.list_events(session_id, tail=tail)
    except Exception:  # noqa: BLE001 — an unreadable chat reads as "no message"
        return 0
    for event in reversed(events):
        payload = event.get("payload") or {}
        if (
            event.get("kind") == "user_message"
            and not payload.get("origin")
            and not payload.get("author")
        ):
            return int(event.get("ts_ms") or 0)
    return 0


# ------------------------------------------------------------------ actions


async def _pause_when_idle(
    society_store: Any, task_store: Any, scheduler: Any, agent_id: str, task_id: str
) -> None:
    """Pause ``task_id`` once its current (skipped) run has settled.

    Re-reads the park record first: when the person already chose "keep
    running" in the meantime, the routine stays on.
    """
    deadline = time.monotonic() + _IDLE_WAIT_S
    while time.monotonic() < deadline:
        row = await task_store.get(task_id)
        if row is None:
            return
        if row.get("state") == "paused":
            return
        if row.get("state") == "scheduled":
            if task_id not in (await load_state(society_store, agent_id)).parked_ids:
                return
            try:
                await scheduler.pause(task_id)
            except Exception:  # noqa: BLE001 — a conflict means the person acted first
                log.info("routine parking: %s not paused (state changed)", task_id)
            return
        if row.get("state") != "running":
            return
        await asyncio.sleep(0.5)


#: Delayed pauses still waiting for their run to settle, by task id.
_PENDING: dict[str, asyncio.Task[None]] = {}


async def maybe_park(
    runtime: Any,
    agent: Any,
    task_id: str,
    *,
    now_ms: int | None = None,
) -> None:
    """Before an unattended run: park the agent's unread routines, if due.

    Raises :class:`RoutineParked` when this run's own routine was parked, so
    the task runner records a skipped run and no seat is used. Any error in
    the check itself lets the run go on: parking is a saving, never a gate.
    """
    from dodaios.core.protocols import current_started_by_user

    if current_started_by_user.get():
        return
    services = getattr(runtime, "task_services", None)
    if services is None or getattr(runtime, "store", None) is None:
        return
    now = int(now_ms if now_ms is not None else _now_ms())
    try:
        task_store, scheduler = services()
        if task_store is None or scheduler is None:
            return
        days = await load_days(runtime.store)
        if days <= 0:
            return
        state = await load_state(runtime.store, agent.agent_id)
        if state.never_ask or state.banner:
            return
        from .routines import list_routines

        seen = max(
            state.seen_ms,
            last_person_message_ms(runtime.chat_service(), str(agent.session_id or "")),
        )
        activities = []
        for summary in await list_routines(task_store, agent.agent_id):
            row = await task_store.get(str(summary.get("id")))
            if row is not None:
                activities.append(activity_of(row))
        chosen, unread = parking_candidates(
            activities, seen_ms=seen, now_ms=now, days=days, never_ask=state.never_ask
        )
        if task_id not in chosen:
            return
        state.parked_ms = now
        state.parked_ids = chosen
        state.unread = unread
        state.days = days
        state.banner = True
        await save_state(runtime.store, agent.agent_id, state)
        for tid in chosen:
            await task_store.append_step(
                tid, "log", {"event": "parked", "reason": "away", "days": days, "unread": unread}
            )
            if tid == task_id:
                pending = asyncio.create_task(
                    _pause_when_idle(runtime.store, task_store, scheduler, agent.agent_id, tid)
                )
                _PENDING[tid] = pending
                pending.add_done_callback(lambda _t, key=tid: _PENDING.pop(key, None))
                continue
            try:
                await scheduler.pause(tid)
            except Exception:  # noqa: BLE001 — a running sibling is parked on its own turn
                log.info("routine parking: %s not paused now", tid)
        log.info(
            "routine parking: paused %d routine(s) of %s after %d unread result(s)",
            len(chosen),
            agent.agent_id,
            unread,
        )
    except Exception:  # noqa: BLE001 — parking must never stop a run on its own failure
        log.warning("routine parking check failed for %s", task_id, exc_info=True)
        return
    raise RoutineParked(
        f"Paused: this agent's routine results have not been opened for {days} days "
        f"({unread} unread). Resume it from the agent's routines.",
        code=PARKED_CODE,
    )


async def apply_choice(
    society_store: Any,
    task_store: Any,
    scheduler: Any,
    agent_id: str,
    choice: str,
    *,
    now_ms: int | None = None,
) -> ParkingState:
    """The person's answer to the banner.

    ``keep_running`` resumes every parked routine that is still paused and
    starts a new away period; ``keep_paused`` only closes the banner;
    ``never_ask`` resumes and switches parking off for this agent;
    ``ask_again`` switches it back on.
    """
    if choice not in CHOICES:
        raise ValueError(f"unknown choice {choice!r}")
    now = int(now_ms if now_ms is not None else _now_ms())
    state = await load_state(society_store, agent_id)
    if choice in ("keep_running", "never_ask"):
        for tid in state.parked_ids:
            waiting = _PENDING.pop(tid, None)
            if waiting is not None:
                waiting.cancel()
            row = await task_store.get(tid)
            if row is None or row.get("state") != "paused":
                continue
            try:
                await scheduler.resume(tid)
                await task_store.append_step(tid, "log", {"event": "unparked"})
            except Exception:  # noqa: BLE001 — one routine that cannot resume does not block the rest
                log.info("routine parking: %s not resumed", tid)
    if choice == "ask_again":
        state.never_ask = False
    else:
        state.banner = False
        state.seen_ms = now
        if choice != "keep_paused":
            state.parked_ids = []
            state.parked_ms = 0
            state.unread = 0
        if choice == "never_ask":
            state.never_ask = True
    await save_state(society_store, agent_id, state)
    return state


def _now_ms() -> int:
    return int(time.time() * 1000)
