"""Standing tasks at run time: taking one on, its backing routine, its runs.

A standing task is carried by ONE recurring lead routine (``society/routines.py``)
tagged ``TAG_PREFIX + id`` and :data:`~dodaios.agent_chat.proactive_checks.QUIET_TAG`:
no start card, and a run with nothing to say posts nothing. The routine's stored
prompt is one stable line; the real work order is composed for every run from the
task, its notes and its run log (:func:`run_context`). The run reports through the
lead's ``standing_task`` tool (:func:`report`), which carries the notes forward
and sets the pace of the next look.

Like every unattended run it never bills a per-token API key while a
subscription is connected: the routine is pinned to the subscription seat the
front page runs on when there is one, and the routine runner's billing hold
applies either way. How much a run may do is not only wording: a ``watch`` or
``prepare`` run gets a chat in the ``ask`` permission mode, an ``act`` run gets
at most what the chat it was accepted in allowed (:func:`permission_mode`).

The routine runner calls :func:`precheck_skip`, :func:`run_context`,
:func:`permission_mode`, :func:`run_not_started` and :func:`after_run`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from . import work_order
from .models import (
    AUTONOMY,
    DEFAULT_INTERVAL_MIN,
    MAX_GOAL_CHARS,
    MAX_INTERVAL_MIN,
    MAX_NOTES_CHARS,
    MAX_OPEN,
    MAX_TITLE_CHARS,
    MIN_INTERVAL_MIN,
    OPEN_STATES,
    ORIGINS,
    OUTCOMES,
    TAG_PREFIX,
    StandingError,
    StandingRun,
    StandingTask,
    clamp_interval,
    new_run_id,
    new_task_id,
    normalise_title,
    now_ms,
)
from .store import get_store

log = logging.getLogger(__name__)

#: ``error`` of :func:`after_run` for a run somebody stopped: not a failure.
CANCELLED: Final[str] = "cancelled"
#: A proposal the owner declined, or a task they ended, is not suggested again this long.
DECLINE_MEMORY_MS: Final[int] = 30 * 24 * 60 * 60 * 1000
#: This many failed runs in a row pause the task.
MAX_FAILURES_IN_A_ROW: Final[int] = 3
#: How long :func:`settle` waits for a run to end before it gives up.
SETTLE_WAIT_S: Final[float] = 120.0
#: What a call is told when it needed an approval in a run nobody watches.
UNATTENDED_DENIAL: Final[str] = (
    "Nobody is here to approve this: the run works on its own, so the call did NOT run. Do "
    "not retry it and do not look for another way. Get it ready instead, and say in your "
    "final reply what you would do and why, so the user can decide."
)
# Plain module values: tests shorten them.
_POLL_S: float = 0.5
#: The task runner still writes a run's last steps after the routine left ``running``.
_GRACE_S: float = 1.0
#: How long a stopped run may take to unwind before its routine's row is removed.
_UNWIND_S: float = 20.0

_MAX_TEXT_CHARS: Final[int] = 2000
_MAX_REASON_CHARS: Final[int] = 600
_MAX_SUMMARY_CHARS: Final[int] = 600
_MAX_ACTIONS: Final[int] = 20
_TERMINAL: Final[frozenset[str]] = frozenset({"completed", "cancelled", "failed", "interrupted"})
#: Permission modes a routine chat can have, least to most.
_MODE_ORDER: Final[dict[str, int]] = {"ask": 0, "accept-edits": 1, "bypass": 2}

#: When the current run of a task started (``run_context``), by task id.
_started: dict[str, int] = {}
_background: set[asyncio.Task[None]] = set()


# ----------------------------------------------------------------- plumbing


def _runtime() -> Any | None:
    from dodaios.society.runtime import current_runtime

    return current_runtime()


async def _services() -> tuple[Any, Any, Any, Any]:
    """``(runtime, task_store, scheduler, lead)``, or ``StandingError("unavailable")``."""
    from dodaios.society.roster import LEAD_AGENT_ID

    runtime = _runtime()
    if runtime is None:
        raise StandingError("unavailable", "The agent society is not running.")
    task_store, scheduler = runtime.task_services()
    if task_store is None or scheduler is None:
        raise StandingError("unavailable", "The task scheduler is not running.")
    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        raise StandingError("unavailable", "The assistant's agent record is missing.")
    return runtime, task_store, scheduler, lead


def _require(standing_id: str) -> StandingTask:
    task = get_store().get(str(standing_id or "").strip())
    if task is None:
        raise StandingError("not_found", f"There is no standing task {standing_id!r}.")
    return task


def _patch(standing_id: str, **fields: Any) -> StandingTask | None:
    """Change only ``fields`` on the task as it is stored now.

    Read and write happen without an ``await`` between them, so a run that
    reported its notes meanwhile is never overwritten by an older copy.
    """
    stored = get_store().get(standing_id)
    if stored is None:
        return None
    changed = replace(stored, **fields)
    get_store().save(changed)
    return changed


def _line(text: Any, limit: int) -> str:
    """``text`` on one line, cut to ``limit`` characters."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _validated(
    *, title: Any, goal: Any, how: Any, autonomy: Any, limits: Any, interval_min: Any
) -> dict[str, Any]:
    clean_title = " ".join(str(title or "").split())
    clean_goal = str(goal or "").strip()
    clean_how = str(how or "").strip()
    clean_limits = str(limits or "").strip()
    level = str(autonomy or "").strip().lower()
    if not clean_title:
        raise StandingError("invalid", "A standing task needs a title.")
    if len(clean_title) > MAX_TITLE_CHARS:
        raise StandingError("invalid", f"The title is longer than {MAX_TITLE_CHARS} characters.")
    if not clean_goal:
        raise StandingError("invalid", "A standing task needs a goal.")
    if len(clean_goal) > MAX_GOAL_CHARS:
        raise StandingError("invalid", f"The goal is longer than {MAX_GOAL_CHARS} characters.")
    if len(clean_how) > _MAX_TEXT_CHARS or len(clean_limits) > _MAX_TEXT_CHARS:
        raise StandingError(
            "invalid", f"'how' and 'limits' take at most {_MAX_TEXT_CHARS} characters each."
        )
    if level not in AUTONOMY:
        raise StandingError("invalid", "autonomy must be one of " + ", ".join(AUTONOMY) + ".")
    if level == "act" and not clean_limits:
        raise StandingError(
            "invalid", "A task that may act needs limits: what it may change, and how far."
        )
    return {
        "title": clean_title,
        "goal": clean_goal,
        "how": clean_how,
        "autonomy": level,
        "limits": clean_limits,
        "interval_min": clamp_interval(interval_min),
    }


def _twin(title: str, *, states: frozenset[str] = OPEN_STATES) -> StandingTask | None:
    """A task in one of ``states`` whose title reads the same, newest first."""
    key = normalise_title(title)
    matches = [
        task
        for task in get_store().list(include_ended=True)
        if task.state in states and normalise_title(task.title) == key
    ]
    return max(matches, key=lambda task: task.updated_ms) if matches else None


def _check_room() -> None:
    open_tasks = [t for t in get_store().list() if t.state in OPEN_STATES]
    if len(open_tasks) >= MAX_OPEN:
        raise StandingError(
            "limit",
            f"There are already {MAX_OPEN} standing tasks. End one before adding another.",
        )


async def _post(payload: dict[str, Any]) -> None:
    """One notice in the lead's conversation. Failures are logged, never raised."""
    try:
        from dodaios.society.roster import LEAD_AGENT_ID

        runtime = _runtime()
        if runtime is None:
            return
        lead = await runtime.roster.get(LEAD_AGENT_ID)
        if lead is None:
            return
        await runtime.post_chat_notice(lead, payload)
    except Exception:  # noqa: BLE001 — a notice is a projection; the task itself is stored
        log.warning("standing tasks: %s notice not posted", payload.get("kind"), exc_info=True)


# ------------------------------------------------------- the backing routine


def routine_prompt(task: StandingTask) -> str:
    """The routine's stored prompt: one stable line. The work order joins at run time."""
    return f"Standing task {task.id}: {task.title}"


def _routine_fields(task: StandingTask) -> dict[str, Any]:
    return {
        "title": task.title,
        "prompt": routine_prompt(task),
        "schedule": {"kind": "every", "interval_seconds": task.interval_min * 60},
    }


async def _create_routine(task: StandingTask, services: tuple[Any, Any, Any, Any]) -> str:
    from dodaios.agent_chat.proactive_checks import QUIET_TAG, _seat_for_checks
    from dodaios.society.routines import build_task_spec, create_routine

    runtime, task_store, scheduler, lead = services
    seat = await _seat_for_checks(runtime, lead)
    spec = build_task_spec(
        lead,
        **_routine_fields(task),
        # Pinned like the checks: the subscription seat when there is one, else the lead's own.
        provider=seat.get("provider"),
        model=seat.get("model"),
        effort=seat.get("effort"),
        account_id=seat.get("account_id"),
    )
    spec = spec.model_copy(update={"tags": (*spec.tags, TAG_PREFIX + task.id, QUIET_TAG)})
    return str(await create_routine(task_store, scheduler, spec))


def _out_of_step(spec: Any, task: StandingTask) -> bool:
    """Whether the routine's schedule or name no longer matches the task."""
    trigger = getattr(spec, "trigger", None)
    seconds = float(getattr(trigger, "interval_seconds", 0) or 0)
    prompt = str(getattr(getattr(spec, "action", None), "prompt", "") or "")
    return int(seconds) != task.interval_min * 60 or not prompt.endswith(routine_prompt(task))


async def _match_routine(
    task: StandingTask, services: tuple[Any, Any, Any, Any]
) -> StandingTask:
    """Make the backing routine match ``task``; returns the task with its routine id.

    Active: a routine exists, runs and has the task's pace. Paused: it is
    paused. Proposed or ended: there is none. A routine that is running right
    now is left alone (the scheduler refuses to change it); :func:`settle`
    does the rest when the run has ended.
    """
    from dodaios.society.routines import manage_routine

    _, task_store, scheduler, lead = services
    row = await task_store.get(task.task_id) if task.task_id else None
    state = str((row or {}).get("state") or "")
    running = row is not None and state == "running"
    live = row is not None and state not in _TERMINAL

    async def manage(operation: str, **more: Any) -> None:
        await manage_routine(
            lead, {"task_id": task.task_id, "operation": operation, **more}, task_store, scheduler
        )

    if task.state not in ("active", "paused"):
        if row is None:
            return replace(task, task_id="")
        if running:
            # Stop the run; its row goes when it has unwound (settle).
            await manage("cancel")
            return task
        await manage("delete")
        return replace(task, task_id="")
    if task.state == "paused":
        if live and not running and state != "paused":
            await manage("pause")
        return task
    if not live:
        if row is not None:
            # An app exit ended the old routine for good; a new one takes over.
            await task_store.delete(task.task_id)
        return replace(task, task_id=await _create_routine(task, services))
    if running:
        return task
    if _out_of_step(await task_store.get_spec(task.task_id), task):
        await manage("update", **_routine_fields(task))
    if state == "paused":
        await manage("resume")
    return task


async def _sync(task: StandingTask) -> StandingTask:
    """:func:`_match_routine` with its failures as ``StandingError``."""
    from dodaios.tasks.scheduler import TaskStateConflict

    services = await _services()
    try:
        return await _match_routine(task, services)
    except StandingError:
        raise
    except (TaskStateConflict, ValueError, LookupError) as exc:
        raise StandingError("state", f"The task's routine could not be changed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — the caller hears why, nothing is stored
        log.warning("standing tasks: routine of %s not changed", task.id, exc_info=True)
        raise StandingError(
            "unavailable", f"The task's routine could not be changed: {exc}"
        ) from exc


def _settle_later(standing_id: str, *, delay_s: float | None = None) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop (a synchronous caller): the next run settles it
        return
    job = loop.create_task(
        settle(standing_id, delay_s=delay_s), name=f"standing-settle-{standing_id}"
    )
    _background.add(job)
    job.add_done_callback(_background.discard)


async def settle(
    standing_id: str, *, wait_s: float | None = None, delay_s: float | None = None
) -> None:
    """Make the routine match the task once its run has ended. Never raises.

    A run reports its next pace, and the owner may pause or end a task, while
    the routine is running; the scheduler changes a routine only between runs.
    It starts after ``delay_s`` (default: the short grace the task runner
    needs to write a finished run's last steps).
    """
    try:
        await asyncio.sleep(_GRACE_S if delay_s is None else delay_s)
        deadline = time.monotonic() + (SETTLE_WAIT_S if wait_s is None else wait_s)
        waited = False
        while True:
            task = get_store().get(standing_id)
            if task is None:
                return
            services = await _services()
            row = await services[1].get(task.task_id) if task.task_id else None
            if row is None or row.get("state") != "running":
                break
            if time.monotonic() >= deadline:
                log.info("standing tasks: %s still runs; its routine is settled later", task.id)
                return
            waited = True
            await asyncio.sleep(_POLL_S)
        if waited:
            await asyncio.sleep(_GRACE_S)
            task = get_store().get(standing_id) or task
        if task.state == "active" and row is not None and row.get("state") == "cancelled":
            return  # the owner removed the routine; reading the task rests it
        synced = await _match_routine(task, services)
        next_run_ms = synced.next_run_ms
        if synced.state == "active":
            fresh = await services[1].get(synced.task_id) if synced.task_id else None
            due = (fresh or {}).get("due_at_ns")
            if due:
                next_run_ms = int(due) // 1_000_000
        if synced.task_id != task.task_id or next_run_ms != task.next_run_ms:
            _patch(standing_id, task_id=synced.task_id, next_run_ms=next_run_ms)
    except StandingError as exc:
        log.info("standing tasks: routine of %s not settled (%s)", standing_id, exc.message)
    except Exception:  # noqa: BLE001 — background upkeep; the next run settles again
        log.warning("standing tasks: routine of %s not settled", standing_id, exc_info=True)


async def drain() -> None:
    """Wait for the background upkeep that is under way (shutdown, tests)."""
    loop = asyncio.get_running_loop()
    while True:
        # Upkeep of a loop that is gone can never finish; it is dropped, not awaited.
        for job in [j for j in _background if j.done() or j.get_loop() is not loop]:
            _background.discard(job)
        if not _background:
            return
        await asyncio.gather(*list(_background), return_exceptions=True)


async def _live(task: StandingTask) -> StandingTask:
    """``task`` as it stands now: its next run read from the routine.

    Also repairs what happened to the routine behind the task's back: one the
    owner cancelled or deleted rests the task (paused) until they resume it;
    one an app exit ended is replaced so the task keeps running.
    """
    if task.state != "active":
        return task if task.next_run_ms is None else replace(task, next_run_ms=None)
    runtime = _runtime()
    task_store = runtime.task_services()[0] if runtime is not None else None
    if task_store is None:
        return task
    try:
        row = await task_store.get(task.task_id) if task.task_id else None
        state = str((row or {}).get("state") or "")
        if row is None or state == "cancelled":
            log.info("standing tasks: %s rests, its routine was removed", task.id)
            rested = _patch(
                task.id, state="paused", task_id="", next_run_ms=None, updated_ms=now_ms()
            )
            return rested or task
        if state in _TERMINAL:
            healed = await _match_routine(task, await _services())
            task = _patch(task.id, task_id=healed.task_id) or healed
            row = await task_store.get(task.task_id)
        due = (row or {}).get("due_at_ns")
        return replace(task, next_run_ms=int(due) // 1_000_000) if due else task
    except Exception:  # noqa: BLE001 — the stored task is still a true answer
        log.debug("standing tasks: routine of %s unreadable", task.id, exc_info=True)
        return task


# ---------------------------------------------------------------- reading


async def list_tasks(*, include_ended: bool = False) -> list[StandingTask]:
    return [await _live(task) for task in get_store().list(include_ended=include_ended)]


async def get_task(standing_id: str) -> StandingTask | None:
    task = get_store().get(str(standing_id or "").strip())
    return await _live(task) if task is not None else None


async def runs_of(standing_id: str, limit: int = 20) -> list[StandingRun]:
    """The task's run log, newest first."""
    return get_store().runs(str(standing_id or "").strip(), limit=max(1, min(int(limit), 200)))


async def overview() -> dict[str, Any]:
    """Everything the panel needs: the open tasks, the bounds and the levels."""
    runtime = _runtime()
    task_store, scheduler = runtime.task_services() if runtime is not None else (None, None)
    return {
        "available": task_store is not None and scheduler is not None,
        "tasks": [task.to_dict() for task in await list_tasks()],
        "limits": {
            "min_interval_min": MIN_INTERVAL_MIN,
            "max_interval_min": MAX_INTERVAL_MIN,
            "default_interval_min": DEFAULT_INTERVAL_MIN,
            "max_open": MAX_OPEN,
        },
        "autonomy": list(AUTONOMY),
    }


# ------------------------------------------------- proposing and taking on


async def propose(
    *,
    title: str,
    goal: str,
    how: str = "",
    autonomy: str = "prepare",
    limits: str = "",
    interval_min: int = DEFAULT_INTERVAL_MIN,
    reason: str = "",
) -> StandingTask:
    """The assistant suggests a task. Nothing runs until the owner accepts it.

    Suggesting the same thing twice returns the open task. Something the owner
    declined or ended in the last 30 days is refused (``state``), so the
    assistant does not nag.
    """
    fields = _validated(
        title=title, goal=goal, how=how, autonomy=autonomy, limits=limits,
        interval_min=interval_min,
    )
    twin = _twin(fields["title"])
    if twin is not None:
        return await _live(twin)
    gone = _twin(fields["title"], states=frozenset({"ended"}))
    now = now_ms()
    if gone is not None and now - gone.updated_ms < DECLINE_MEMORY_MS:
        raise StandingError(
            "state",
            f'The user declined or ended "{gone.title}" recently. Do not suggest it again '
            "unless they ask for it.",
        )
    _check_room()
    task = StandingTask(
        id=new_task_id(), state="proposed", origin="suggested",
        reason=_line(reason, _MAX_REASON_CHARS), notes="", task_id="", created_ms=now,
        updated_ms=now, last_run_ms=None, next_run_ms=None, last_outcome="", last_summary="",
        runs=0, **fields,
    )
    get_store().save(task)
    await _post(
        {
            "kind": "standing_proposal",
            "standing_id": task.id,
            "title": task.title,
            "goal": task.goal,
            "autonomy": task.autonomy,
            "limits": task.limits,
            "interval_min": task.interval_min,
            "reason": task.reason,
            "text": (
                f'I could look after "{task.title}" for you, '
                f"{work_order.pace(task.interval_min)}."
            ),
        }
    )
    return task


def _grant_of(runtime: Any, origin_session: str) -> str:
    """The permission mode the task's ``act`` runs may have at most.

    The mode of the chat the task was accepted in. A task the owner set up
    outside a chat gets what an ordinary lead routine gets.
    """
    if not origin_session:
        return "bypass"
    return _session_mode(runtime, origin_session) or "ask"


def _session_mode(runtime: Any, session_id: str) -> str:
    """The chat's permission mode as a routine chat can have it; ``""`` when the chat is gone."""
    try:
        service = runtime.chat_service() if runtime is not None else None
        session = service.store.get_session(session_id) if service is not None else None
    except Exception:  # noqa: BLE001 — an unreadable chat grants nothing
        log.debug("standing tasks: chat %s unreadable", session_id, exc_info=True)
        return "ask"
    if session is None:
        return ""
    mode = str(getattr(session, "permission_mode", "") or "")
    return mode if mode in _MODE_ORDER else "ask"


async def _activate(task: StandingTask, origin_session: str) -> StandingTask:
    """Create the routine, then store the task as active; nothing is left half-made."""
    services = await _services()
    now = now_ms()
    active = await _sync(
        replace(
            task, state="active", task_id="", updated_ms=now,
            next_run_ms=now + task.interval_min * 60_000,
        )
    )
    try:
        stored = get_store().get(active.id)
        if stored is not None and stored.state == "active":
            # Accepted twice at once: the first yes stands, this routine goes again.
            await _match_routine(replace(active, state="ended"), services)
            return await _live(stored)
        get_store().save(active)
        get_store().set_grant(active.id, origin_session, _grant_of(services[0], origin_session))
    except Exception:
        try:
            await _match_routine(replace(active, state="ended"), services)
        except Exception:  # noqa: BLE001 — the first failure is the one to report
            log.warning("standing tasks: routine %s left behind", active.task_id, exc_info=True)
        raise
    log.info(
        "standing tasks: %s taken on (%s, %s)",
        active.id, active.autonomy, work_order.pace(active.interval_min),
    )
    return await _live(active)


async def take_on(
    *,
    title: str,
    goal: str,
    how: str = "",
    autonomy: str = "prepare",
    limits: str = "",
    interval_min: int = DEFAULT_INTERVAL_MIN,
    origin: str = "owner",
    origin_session: str = "",
    timezone: str = "",
) -> StandingTask:
    """The owner hands a task over: it is active at once.

    ``origin_session`` is the chat this happened in; its permission mode is
    the most an ``act`` run of the task ever gets. ``timezone`` is accepted
    for callers that have it; an interval schedule needs none.
    """
    del timezone
    fields = _validated(
        title=title, goal=goal, how=how, autonomy=autonomy, limits=limits,
        interval_min=interval_min,
    )
    if origin not in ORIGINS:
        raise StandingError("invalid", "origin must be one of " + ", ".join(ORIGINS) + ".")
    twin = _twin(fields["title"])
    if twin is not None and twin.state != "proposed":
        raise StandingError(
            "state", f'A standing task "{twin.title}" already exists ({twin.id}).'
        )
    now = now_ms()
    if twin is not None:
        # The owner asks for what the assistant suggested: that is a yes to it.
        return await _activate(replace(twin, **fields), origin_session)
    _check_room()
    task = StandingTask(
        id=new_task_id(), state="proposed", origin=origin, reason="", notes="", task_id="",
        created_ms=now, updated_ms=now, last_run_ms=None, next_run_ms=None, last_outcome="",
        last_summary="", runs=0, **fields,
    )
    return await _activate(task, origin_session)


async def accept(standing_id: str, *, origin_session: str = "") -> StandingTask:
    """The owner says yes to a proposal: it becomes active."""
    task = _require(standing_id)
    if task.state != "proposed":
        raise StandingError("state", f'"{task.title}" is {task.state}, not a proposal.')
    return await _activate(task, origin_session)


async def decline(standing_id: str) -> StandingTask:
    """The owner says no to a proposal. It is remembered, so it is not suggested again."""
    task = _require(standing_id)
    if task.state != "proposed":
        raise StandingError("state", f'"{task.title}" is {task.state}, not a proposal.')
    ended = replace(task, state="ended", updated_ms=now_ms(), next_run_ms=None)
    get_store().save(ended)
    return ended


# ------------------------------------------------------------- changing one


async def update(
    standing_id: str,
    *,
    title: str | None = None,
    goal: str | None = None,
    how: str | None = None,
    autonomy: str | None = None,
    limits: str | None = None,
    interval_min: int | None = None,
) -> StandingTask:
    """Change what was given; the routine follows a new title or pace."""
    task = _require(standing_id)
    if task.state == "ended":
        raise StandingError("state", f'"{task.title}" has ended and cannot be changed.')
    fields = _validated(
        title=task.title if title is None else title,
        goal=task.goal if goal is None else goal,
        how=task.how if how is None else how,
        autonomy=task.autonomy if autonomy is None else autonomy,
        limits=task.limits if limits is None else limits,
        interval_min=task.interval_min if interval_min is None else interval_min,
    )
    twin = _twin(fields["title"])
    if twin is not None and twin.id != task.id:
        raise StandingError(
            "state", f'A standing task "{twin.title}" already exists ({twin.id}).'
        )
    changed = replace(task, updated_ms=now_ms(), **fields)
    if task.state == "active" and (
        changed.title != task.title or changed.interval_min != task.interval_min
    ):
        changed = await _sync(changed)
    stored = _patch(task.id, updated_ms=changed.updated_ms, task_id=changed.task_id, **fields)
    return await _live(stored or changed)


async def pause(standing_id: str) -> StandingTask:
    task = _require(standing_id)
    if task.state != "active":
        raise StandingError("state", f'"{task.title}" is {task.state}; only an active task pauses.')
    paused = await _sync(replace(task, state="paused", updated_ms=now_ms(), next_run_ms=None))
    stored = _patch(task.id, state="paused", updated_ms=paused.updated_ms, next_run_ms=None)
    return stored or paused


async def resume(standing_id: str) -> StandingTask:
    task = _require(standing_id)
    if task.state != "paused":
        raise StandingError("state", f'"{task.title}" is {task.state}; only a paused task resumes.')
    now = now_ms()
    active = await _sync(
        replace(
            task, state="active", updated_ms=now, next_run_ms=now + task.interval_min * 60_000
        )
    )
    stored = _patch(
        task.id, state="active", updated_ms=now, task_id=active.task_id,
        next_run_ms=active.next_run_ms,
    )
    return await _live(stored or active)


async def end(standing_id: str) -> StandingTask:
    """The owner takes the task back for good. Its notes and run log stay readable."""
    task = _require(standing_id)
    if task.state == "ended":
        raise StandingError("state", f'"{task.title}" has already ended.')
    ended = replace(task, state="ended", updated_ms=now_ms(), next_run_ms=None)
    if task.task_id:
        ended = await _sync(ended)
    ended = _patch(
        task.id, state="ended", updated_ms=ended.updated_ms, next_run_ms=None,
        task_id=ended.task_id,
    ) or ended
    if ended.task_id:
        # Its run was stopped just now; the routine's row goes when it has unwound.
        _settle_later(ended.id, delay_s=_UNWIND_S)
    return ended


async def run_now(standing_id: str) -> StandingTask:
    """Start a run now, outside the pace. The pace itself is untouched.

    Billing follows who asked: a caller that passes on the owner's own click
    wraps this in ``dodaios.core.protocols.started_by_user()``; without it the
    run is unattended work and the billing hold applies.
    """
    from dodaios.tasks.scheduler import TaskNotFound, TaskStateConflict

    task = _require(standing_id)
    if task.state != "active":
        raise StandingError("state", f'"{task.title}" is {task.state}; only an active task runs.')
    task = await _live(task)
    if task.state != "active" or not task.task_id:
        raise StandingError("state", f'"{task.title}" has no routine; resume it first.')
    _, _, scheduler, _ = await _services()
    try:
        await scheduler.run_now(task.task_id)
    except TaskStateConflict as exc:
        raise StandingError("state", f'"{task.title}" cannot run right now: {exc}') from exc
    except TaskNotFound as exc:
        raise StandingError("unavailable", f'The routine of "{task.title}" is missing.') from exc
    return task


async def add_note(standing_id: str, text: str) -> StandingTask:
    """Append one dated line to the working notes (the owner, or the assistant in a chat)."""
    task = _require(standing_id)
    if task.state == "ended":
        raise StandingError("state", f'"{task.title}" has ended.')
    line = _line(text, 1000)
    if not line:
        raise StandingError("invalid", "The note is empty.")
    stamp = time.strftime("%Y-%m-%d", time.localtime())
    notes = f"{task.notes.rstrip()}\n[{stamp}] {line}".strip()
    if len(notes) > MAX_NOTES_CHARS:
        # The newest lines are the ones the next run needs.
        notes = "…" + notes[-(MAX_NOTES_CHARS - 1):]
    noted = replace(task, notes=notes, updated_ms=now_ms())
    get_store().save(noted)
    return await _live(noted)


# ------------------------------------------------------------------- runs


def _record(
    task: StandingTask,
    *,
    outcome: str,
    summary: str,
    notes: str | None = None,
    actions: Sequence[str] = (),
    interval_min: int | None = None,
    session_id: str = "",
    run_id: str = "",
) -> StandingTask:
    """Write one run and the task's ``last_*`` fields. A run that reports twice
    from one chat, or is given ``run_id``, replaces its earlier row."""
    store = get_store()
    now = now_ms()
    interval = task.interval_min if interval_min is None else interval_min
    earlier = run_id or getattr(store.run_of_session(task.id, session_id), "id", "")
    store.add_run(
        StandingRun(
            id=earlier or new_run_id(), standing_id=task.id, at_ms=now, outcome=outcome,
            summary=summary, actions=tuple(actions), next_interval_min=interval,
            session_id=session_id,
        )
    )
    recorded = replace(
        task,
        notes=task.notes if notes is None else str(notes).strip()[:MAX_NOTES_CHARS],
        interval_min=interval,
        last_run_ms=now,
        next_run_ms=now + interval * 60_000 if task.state == "active" else None,
        last_outcome=outcome,
        last_summary=summary,
        runs=task.runs + (0 if earlier else 1),
        updated_ms=now,
    )
    store.save(recorded)
    return recorded


async def report(
    standing_id: str,
    *,
    outcome: str,
    summary: str,
    notes: str | None = None,
    actions: Sequence[str] = (),
    next_check_min: int | None = None,
    session_id: str = "",
) -> StandingTask:
    """A run says how it went, carries its notes forward and sets the next look.

    ``next_check_min`` is clamped to the bounds and becomes the task's pace, in
    both directions. The routine itself is re-paced as soon as it is not
    running (a run reports from inside the routine; :func:`after_run` follows).
    """
    task = _require(standing_id)
    if task.state != "active":
        raise StandingError(
            "state", f'"{task.title}" is {task.state}; only an active task takes a report.'
        )
    result = str(outcome or "").strip().lower()
    if result not in OUTCOMES:
        raise StandingError("invalid", "outcome must be one of " + ", ".join(OUTCOMES) + ".")
    said = _line(summary, _MAX_SUMMARY_CHARS)
    if not said and result != "quiet":
        raise StandingError("invalid", "A report needs a summary of one or two sentences.")
    if isinstance(actions, str):
        actions = [actions]
    done = [line for line in (_line(a, 200) for a in actions) if line][:_MAX_ACTIONS]
    recorded = _record(
        task, outcome=result, summary=said, notes=notes, actions=done,
        interval_min=None if next_check_min is None else clamp_interval(next_check_min),
        session_id=str(session_id or ""),
    )
    if recorded.interval_min != task.interval_min:
        try:
            await _sync(recorded)
        except StandingError as exc:
            # The pace is stored; the routine follows when its run has ended.
            log.info("standing tasks: pace of %s applied later (%s)", task.id, exc.message)
    return await _live(recorded)


def standing_id_of(tags: Sequence[str]) -> str:
    """The standing task behind a routine's tags, ``""`` when it is not one."""
    for tag in tags or ():
        text = str(tag)
        if text.startswith(TAG_PREFIX) and len(text) > len(TAG_PREFIX):
            return text[len(TAG_PREFIX):]
    return ""


async def precheck_skip(tags: Sequence[str]) -> str:
    """Why this run needs no model call, or ``""`` when it must run."""
    standing_id = standing_id_of(tags)
    if not standing_id:
        return ""
    task = get_store().get(standing_id)
    if task is None:
        return "the standing task no longer exists"
    if task.state != "active":
        # The routine fired although the task rests: put it back in step.
        _settle_later(standing_id)
        return f"the standing task is {task.state}"
    try:
        runtime = _runtime()
        if runtime is not None and await runtime.store.kill_switch():
            return "the society is halted"
    except Exception:  # noqa: BLE001 — an unreadable switch never hides a run; the runner's guard decides
        log.debug("standing tasks: kill switch unreadable", exc_info=True)
    return ""


async def run_context(tags: Sequence[str]) -> str:
    """The work order of this run, or ``""`` when the routine is no active standing task."""
    from dodaios.agent_chat.proactive_checks import NOTHING

    standing_id = standing_id_of(tags)
    if not standing_id:
        return ""
    task = get_store().get(standing_id)
    if task is None or task.state != "active":
        return ""
    _started[standing_id] = now_ms()
    runs = get_store().runs(standing_id, limit=work_order.LOG_LINES)
    return work_order.compose(task, runs, nothing=NOTHING)


async def permission_mode(
    tags: Sequence[str], *, provider: str = "", account_id: str = ""
) -> str:
    """The permission mode of this run's chat, ``""`` when it is no standing task.

    ``watch`` and ``prepare`` run in ``ask``: a call that changes something
    needs an approval, and the runner refuses such a card at once
    (:func:`refuse_open_cards`), so the call does not run. ``act`` runs in the
    mode of the chat the task was accepted in, never more, and less when that
    chat has been narrowed since.

    Raises ``RuntimeError`` when the run must ask but its seat (``provider``)
    cannot ask in a chat: such a run would act unasked, so it does not start.
    """
    standing_id = standing_id_of(tags)
    if not standing_id:
        return ""
    task = get_store().get(standing_id)
    mode = "ask"
    if task is not None and task.autonomy == "act":
        session_id, saved = get_store().grant(standing_id)
        mode = saved if saved in _MODE_ORDER else "ask"
        current = _session_mode(_runtime(), session_id) if session_id else ""
        if current and _MODE_ORDER[current] < _MODE_ORDER[mode]:
            mode = current
    if mode == "ask" and provider and not _can_ask(provider, account_id):
        raise RuntimeError(
            "This standing task may not act unasked, and its model cannot ask for an "
            "approval in a background run, so the run did not start. Pick a model for the "
            "assistant that can ask (Dodaios' own, Claude Code or Codex)."
        )
    return mode


def _can_ask(provider: str, account_id: str) -> bool:
    """Whether a routine chat on this seat honours the ``ask`` mode."""
    from dodaios.agent_chat.permissions import society_mode_supported
    from dodaios.agent_chat.service import resolve_runner
    from dodaios.society.chat_binding import SURFACE

    runner = resolve_runner(provider, surface=SURFACE, account_id=account_id)
    return society_mode_supported(runner, "ask")


#: A vendor CLI's own tools that only look. Its permission prompt asks about some of
#: them (a file outside the chat's folder, a web page); nobody is there to answer.
_LOOKING_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "Read", "Glob", "Grep", "LS", "Ls", "NotebookRead", "WebFetch", "WebSearch",
        "ToolSearch", "TodoWrite", "ListMcpResourcesTool", "ReadMcpResourceTool",
        "ReadMcpResourceDirTool",
    }
)
#: The same CLI's tools that write a file; a run above ``watch`` may keep what it
#: prepares in its own folder.
_FILE_WRITING_TOOLS: Final[frozenset[str]] = frozenset({"Write", "Edit", "MultiEdit"})


def _inside(path: str, folder: str) -> bool:
    if not path or not folder:
        return False
    try:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = Path(folder) / target
        return target.resolve().is_relative_to(Path(folder).resolve())
    except (OSError, ValueError, RuntimeError):
        log.info("standing tasks: path %r not placed, so not written unasked", path)
        return False


def run_may(name: str, args: dict[str, Any], *, autonomy: str, folder: str) -> bool:
    """Whether a call that asked for an approval may run in a run nobody watches.

    Looking is what every level is for. A level above ``watch`` may also write
    files inside the run's own folder (a draft, a table: "inside Dodaios").
    Everything else stays refused, whatever the level: a call reaches a card
    only when the chat's mode, a hard limit or the person's own rule wanted a
    person to decide.
    """
    bare = str(name or "").strip()
    if bare in _LOOKING_TOOLS:
        return True
    if autonomy != "watch" and bare in _FILE_WRITING_TOOLS:
        return _inside(str((args or {}).get("file_path") or (args or {}).get("path") or ""), folder)
    return False


def refuse_open_cards(service: Any, session_id: str, tags: Sequence[str] = ()) -> int:
    """Answer every approval card open in a standing task run's chat; returns how many
    were refused.

    Nobody watches that chat. A card left open would hold the run (and every
    later run of the task) until someone found it. A call that only looks
    (:func:`run_may`) is let through; anything else is refused with the reason,
    so the call does not run and the run goes on to prepare the step and ask.
    """
    refused = 0
    try:
        pending = list(service.pending_approvals(session_id))
        if not pending:
            return 0
        task = get_store().get(standing_id_of(tags)) if tags else None
        autonomy = task.autonomy if task is not None else "watch"
        session = service.store.get_session(session_id) if tags else None
        folder = str(getattr(session, "cwd", "") or "")
        calls = getattr(service, "_approval_call", {})
        for approval_id in pending:
            name, args = calls.get(approval_id) or ("", {})
            if tags and run_may(name, args, autonomy=autonomy, folder=folder):
                service.resolve_approval(session_id, approval_id, "allow")
                continue
            refused += bool(
                service.resolve_approval(
                    session_id, approval_id, "deny", feedback=UNATTENDED_DENIAL
                )
            )
    except Exception:  # noqa: BLE001 — a card that stays open is answered on the next pass
        log.warning("standing tasks: open card in %s not answered", session_id, exc_info=True)
    return refused


def _says_nothing(answer: str) -> bool:
    from dodaios.agent_chat.proactive_checks import quiet_result

    return quiet_result(
        {"kind": "society_result", "source": "routine", "status": "done", "text": answer}
    )


async def run_not_started(tags: Sequence[str], exc: BaseException) -> None:
    """A run that ended before its turn began: held back (skipped) or broken (failed)."""
    from dodaios.core.protocols import CapacityDeferred, RoutineDeferred

    standing_id = standing_id_of(tags)
    if not standing_id:
        return
    if not isinstance(exc, CapacityDeferred | RoutineDeferred):
        await after_run(tags, answer="", error=str(exc) or type(exc).__name__)
        return
    try:
        task = get_store().get(standing_id)
        if task is None or task.state != "active":
            return
        why = _line(exc, _MAX_SUMMARY_CHARS)
        latest = get_store().runs(standing_id, limit=1)
        again = bool(latest) and latest[0].outcome == "skipped" and latest[0].summary == why
        # The same hold run after run is one line in the log, with its newest time.
        _record(task, outcome="skipped", summary=why, run_id=latest[0].id if again else "")
    except Exception:  # noqa: BLE001 — bookkeeping never changes how the run ends
        log.warning("standing tasks: skipped run of %s not recorded", standing_id, exc_info=True)


async def after_run(
    tags: Sequence[str], *, answer: str, session_id: str = "", error: str = ""
) -> None:
    """The routine runner's call when a standing task's turn has ended. Never raises.

    A run that reported is left as it is. One that did not gets a run written
    for it: ``failed`` with the error, ``skipped`` when it was stopped,
    ``quiet`` for the :data:`~dodaios.agent_chat.proactive_checks.NOTHING`
    reply, else ``reported`` with the start of its answer. What the run wrote
    for the owner is posted into the conversation. Three failures in a row
    pause the task and say so once.
    """
    standing_id = standing_id_of(tags)
    if not standing_id:
        return
    try:
        await _after_run(standing_id, str(answer or ""), str(session_id or ""), str(error or ""))
    except Exception:  # noqa: BLE001 — bookkeeping never changes how the run ends
        log.warning("standing tasks: run of %s not recorded", standing_id, exc_info=True)
    _settle_later(standing_id)


async def _after_run(standing_id: str, answer: str, session_id: str, error: str) -> None:
    store = get_store()
    task = store.get(standing_id)
    if task is None:
        return
    started = _started.pop(standing_id, None)
    latest = store.runs(standing_id, limit=1)
    reported = store.run_of_session(standing_id, session_id) is not None or (
        started is not None and bool(latest) and latest[0].at_ms >= started
    )
    if not reported and task.state in ("active", "paused"):
        if error == CANCELLED:
            outcome, summary = "skipped", "The run was stopped before it finished."
        elif error:
            outcome, summary = "failed", _line(error, 300)
        elif _says_nothing(answer):
            outcome, summary = "quiet", ""
        else:
            outcome, summary = "reported", _line(answer, 200)
        task = _record(task, outcome=outcome, summary=summary, session_id=session_id)
    if not error and not _says_nothing(answer):
        from dodaios.society.display_name import display_name
        from dodaios.society.roster import LEAD_AGENT_ID

        runtime = _runtime()
        lead = await runtime.roster.get(LEAD_AGENT_ID) if runtime is not None else None
        await _post(
            {
                "kind": "society_result",
                "status": "done",
                "source": "routine",
                "text": answer[:4000],
                "agent_id": LEAD_AGENT_ID,
                "agent_name": display_name(lead) if lead is not None else "",
                "task_id": task.task_id,
                "session_id": session_id,
                "standing_id": task.id,
                "standing_title": task.title,
            }
        )
    recent = store.runs(standing_id, limit=MAX_FAILURES_IN_A_ROW)
    if (
        task.state == "active"
        and len(recent) == MAX_FAILURES_IN_A_ROW
        and all(run.outcome == "failed" for run in recent)
    ):
        _patch(task.id, state="paused", next_run_ms=None, updated_ms=now_ms())
        log.warning("standing tasks: %s paused after %d failed runs", task.id, len(recent))
        await _post(
            {
                "kind": "standing_paused",
                "standing_id": task.id,
                "title": task.title,
                "text": (
                    f'I paused the standing task "{task.title}": its last '
                    f"{MAX_FAILURES_IN_A_ROW} runs failed "
                    f"({recent[0].summary or 'no reason given'}). "
                    "Resume it when the cause is fixed."
                ),
            }
        )


async def brief_context(since_ms: int | None = None) -> str:
    """What the standing tasks did since ``since_ms`` (default: the last 24 hours),
    for the morning brief; ``""`` when no run is worth reading."""
    since = now_ms() - 24 * 60 * 60 * 1000 if since_ms is None else int(since_ms)
    store = get_store()
    entries = [
        (task, store.runs(task.id, limit=10, since_ms=since))
        for task in store.list(include_ended=True)
        if task.runs
    ]
    return work_order.brief_block(entries)


async def heal_after_start(*, wait_s: float = 120.0) -> None:
    """Once the scheduler is up after an app start, put every active task's routine
    back in step (an app exit in the middle of a run ends the old routine for good).

    Reads do the same repair, but a headless install may never open the panel.
    Best effort: a store or scheduler that never comes up leaves it to the next read.
    """
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        runtime = _runtime()
        task_store, scheduler = runtime.task_services() if runtime is not None else (None, None)
        if task_store is not None and scheduler is not None:
            try:
                await list_tasks()
            except Exception:  # noqa: BLE001 — upkeep after start; the next read repairs again
                log.warning("standing tasks: routines not checked after start", exc_info=True)
            return
        await asyncio.sleep(2.0)


__all__ = [
    "CANCELLED",
    "accept",
    "add_note",
    "after_run",
    "brief_context",
    "decline",
    "drain",
    "end",
    "get_task",
    "heal_after_start",
    "list_tasks",
    "overview",
    "pause",
    "permission_mode",
    "precheck_skip",
    "propose",
    "refuse_open_cards",
    "report",
    "resume",
    "routine_prompt",
    "run_context",
    "run_may",
    "run_not_started",
    "run_now",
    "runs_of",
    "settle",
    "standing_id_of",
    "take_on",
    "update",
]
