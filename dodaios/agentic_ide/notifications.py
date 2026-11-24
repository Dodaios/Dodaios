"""Tell the user when a pane stopped needing them to watch it.

Watches every pane of every open workspace and files an entry per event: the IDE
bell carries the count, the panel jumps to the pane. Kinds, each established by
the pane itself: ``completed`` (given a job, was working, now quiet; never a
claim that the work is correct), ``needs_input`` (question on screen), ``exited``
(process gone), ``failed`` (agent could not start).

``completed`` also needs a job: a CLI paints a banner and stands still on
startup, which looks like finishing, so a stop counts only after the pane was
GIVEN something (``Terminal.last_submit_at``; the flag latches). A pane must be
settled for :data:`SETTLE_S` first (TUIs drop their busy hint between steps) and
is armed once per episode.

Entries live in a bounded deque and are lost with the process (a stale "jump to
pane" is worse than none). Each sweep prunes and relabels entries of closed or
renamed panes (:meth:`NotificationCenter.retain`); a pane closed by name is
cleared at once (:meth:`NotificationCenter.forget_pane`) because keys are reused.
One task per registry; nothing runs on the boot path (AP-26).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from itertools import count
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from loguru import logger

from .activity import (
    RESIZE_SHADOW_S,
    STILL_S,
    WORK_CONFIRM_S,
    Activity,
    in_submit_wake,
    is_moving,
    is_settled,
    read_activity,
    screen_digest,
    stamp,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Mapping

    from .session import Registry

Kind = Literal["completed", "needs_input", "exited", "failed", "stopped"]

#: Settle time before a stop is reported; outlasts the gap between TUI steps.
SETTLE_S = 5.0

SWEEP_INTERVAL_S = 2.0

#: Movement resuming within this long of the badge last wearing "working"
#: skips re-confirmation (a TUI pauses between tool steps).
WORK_RESUME_GRACE_S = 15.0

#: How long the badge keeps saying "working" after the screen stopped moving, so
#: a slow tool call or resize redraw is not published as "done". Equal to the
#: bell's ``SETTLE_S`` so the badge never says "done" before the bell. ``waiting``
#: only; a question takes over at once.
WORK_HOLD_S = SETTLE_S

#: How many entries are kept; the oldest fall off.
MAX_ENTRIES = 200

#: How long the config switch is trusted (``load_config`` parses TOML per call).
SWITCH_TTL_S = 15.0

DETAIL_CHARS = 160

_ids = count(1)


class PaneLabel(NamedTuple):
    """What a live pane is called now and the tab it sits in; entries are refreshed from it."""

    pane: str
    workspace: str


@dataclass(frozen=True, slots=True)
class Notification:
    """One thing that happened in one pane."""

    id: str
    kind: Kind
    #: Workspace id and tab name; a call-sign alone ("T3") is ambiguous.
    workspace_id: str
    workspace: str
    pane_key: str
    pane: str
    agent: str
    display_name: str
    #: One clause, written here so CLI and UI agree.
    title: str
    detail: str
    created_at: float
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "workspace_id": self.workspace_id,
            "workspace": self.workspace,
            "pane_key": self.pane_key,
            "pane": self.pane,
            "agent": self.agent,
            "display_name": self.display_name,
            "title": self.title,
            "detail": self.detail,
            "created_at": self.created_at,
            "read": self.read,
        }


class NotificationCenter:
    """The bounded list of entries, newest first. Event-loop only, not thread-safe."""

    def __init__(self, limit: int = MAX_ENTRIES) -> None:
        self._entries: deque[Notification] = deque(maxlen=limit)

    def add(self, entry: Notification) -> Notification:
        self._entries.append(entry)
        return entry

    def list(self) -> list[Notification]:
        """Newest first — the order the panel renders."""
        return list(reversed(self._entries))

    @property
    def unread(self) -> int:
        return sum(1 for entry in self._entries if not entry.read)

    def mark_read(self, ids: Iterable[str] | None = None) -> int:
        """Mark the given entries read (all without ids); returns how many CHANGED."""
        wanted = None if ids is None else {str(i) for i in ids}
        changed = 0
        for index, entry in enumerate(self._entries):
            if entry.read or (wanted is not None and entry.id not in wanted):
                continue
            # Frozen: replaced, not mutated, so a handed-out list keeps its content.
            self._entries[index] = Notification(**{**entry.to_dict(), "read": True})
            changed += 1
        return changed

    def clear(self, ids: Iterable[str] | None = None) -> int:
        """Drop the given entries; without ids, all of them."""
        if ids is None:
            dropped = len(self._entries)
            self._entries.clear()
            return dropped
        wanted = {str(i) for i in ids}
        kept = [entry for entry in self._entries if entry.id not in wanted]
        dropped = len(self._entries) - len(kept)
        self._entries.clear()
        self._entries.extend(kept)
        return dropped

    def forget_workspace(self, workspace_id: str) -> int:
        """Drop the entries of a closed workspace (their "jump to pane" cannot work)."""
        return self.clear(entry.id for entry in self._entries if entry.workspace_id == workspace_id)

    def forget_pane(self, workspace_id: str, pane_key: str) -> int:
        """Drop the entries of a just-closed pane (keys are reused, so do not wait for a sweep)."""
        return self.clear(
            entry.id
            for entry in self._entries
            if entry.workspace_id == workspace_id and entry.pane_key == pane_key
        )

    def retain(self, live: Mapping[tuple[str, str], PaneLabel]) -> int:
        """Keep only entries whose pane still exists and relabel those; returns the DROPPED count.

        ``live`` maps ``(workspace_id, pane_key)`` to its current label.
        """
        kept: list[Notification] = []
        for entry in self._entries:
            label = live.get((entry.workspace_id, entry.pane_key))
            if label is None:
                continue
            if entry.pane == label.pane and entry.workspace == label.workspace:
                kept.append(entry)
                continue
            kept.append(
                Notification(
                    **{**entry.to_dict(), "pane": label.pane, "workspace": label.workspace}
                )
            )
        dropped = len(self._entries) - len(kept)
        if dropped:
            self._entries.clear()
            self._entries.extend(kept)
            return dropped
        for index, entry in enumerate(kept):
            self._entries[index] = entry
        return 0


@dataclass(slots=True)
class _PaneWatch:
    """What one pane was last seen doing, and whether that was reported."""

    activity: Activity
    since: float
    worked: bool = False
    #: Ever given an instruction? Latch; rules out the startup stretch.
    tasked: bool = False
    announced: bool = False
    #: Interruption evidence last checkpointed to disk.
    resume_needed: bool = False
    #: Screen fingerprint at the previous sweep and when it last CHANGED (the detector).
    digest: str = ""
    changed_at: float = 0.0
    process_generation: int = 0
    moving_since: float | None = None
    stamped_working_at: float = 0.0


def _stopped_at(term: Any, watch: _PaneWatch) -> float:
    """When this pane's screen last moved (output byte or observed change); 0 reads as "now"."""
    out_at = float(getattr(term, "last_output_at", 0.0) or 0.0)
    return max(out_at, float(watch.changed_at or 0.0))


def _detail(term: Any) -> str:
    """One line about what the pane was doing, from state it already keeps."""
    text = " ".join(str(getattr(term, "last_prompt", "") or "").split())
    if not text:
        return ""
    return text if len(text) <= DETAIL_CHARS else f"{text[:DETAIL_CHARS].rsplit(' ', 1)[0]}…"


def _title(kind: Kind, term: Any) -> str:
    """What the entry says; a quiet pane is "finished", never "done" or "succeeded"."""
    if kind == "stopped":
        return "Its task was interrupted"
    if kind == "completed":
        return "Finished and waiting at its prompt"
    if kind == "needs_input":
        return "Waiting for your answer"
    if kind == "failed":
        problem = " ".join(str(getattr(term, "error", "") or "").split())
        return f"Could not start — {problem}" if problem else "Its agent could not be started"
    code = getattr(term, "exit_code", None)
    if code in (0, None):
        return "Its agent exited"
    return f"Its agent exited with code {code}"


class ActivityWatcher:
    """Turns pane state transitions into notifications; synchronous, testable without a PTY."""

    def __init__(self, center: NotificationCenter) -> None:
        self.center = center
        self._panes: dict[tuple[str, str], _PaneWatch] = {}
        self._resume_dirty = False
        self._results: list[tuple[str, Any, Any]] = []

    def take_results(self) -> list[tuple[str, Any, Any]]:
        results, self._results = self._results, []
        return results

    def take_resume_dirty(self) -> bool:
        """Return and clear whether activity changed the resume checkpoint."""
        changed = self._resume_dirty
        self._resume_dirty = False
        return changed

    def forget_workspace(self, workspace_id: str) -> None:
        """Drop the per-pane memory of a workspace that is gone."""
        for key in [k for k in self._panes if k[0] == workspace_id]:
            del self._panes[key]

    def poll(
        self,
        registry: Registry,
        *,
        now: float | None = None,
        emit: bool = True,
    ) -> list[Notification]:
        """Look at every pane once and file whatever has just happened."""
        moment = time.time() if now is None else now
        filed: list[Notification] = []
        alive: dict[tuple[str, str], PaneLabel] = {}

        for session in registry.sessions:
            for term in session.terminals:
                if not _is_agent(term):
                    continue
                ident = (session.id, str(getattr(term, "key", "") or ""))
                alive[ident] = PaneLabel(
                    pane=str(getattr(term, "name", "") or ""),
                    workspace=str(getattr(session, "name", "") or ""),
                )
                entry = self._step(session, term, ident, moment, emit=emit)
                if entry is not None:
                    filed.append(entry)

        # Closed panes take their memory with them (else the dict grows unbounded).
        for gone in self._panes.keys() - alive.keys():
            del self._panes[gone]
        # And their entries (the sweep sees every way a pane can disappear).
        self.center.retain(alive)
        return filed

    def _step(
        self,
        session: Any,
        term: Any,
        ident: tuple[str, str],
        now: float,
        *,
        emit: bool,
    ) -> Notification | None:
        watch = self._panes.get(ident)
        process_generation = int(getattr(term, "process_generation", 0))
        digest = screen_digest(term)
        if watch is None or watch.process_generation != process_generation:
            # First sight: nothing is filed. The screen is recorded as still for a
            # LONG time; assuming movement would "stop" and ring for every quiet
            # terminal. Assuming stillness only costs one sweep of latency.
            settled_at = now - STILL_S - 1.0
            activity = read_activity(term, now=now, still_since=settled_at)
            # An agent that worked while the app was closed is seeded as a job in
            # progress, so it reports "completed" later (RUB-102).
            detached_work = bool(getattr(term, "worked_while_detached", False))
            if detached_work:
                term.worked_while_detached = False
            watch = _PaneWatch(
                activity="working" if detached_work else activity,
                since=now,
                announced=not detached_work,
                worked=detached_work,
                tasked=_tasked(term) or detached_work,
                resume_needed=bool(getattr(term, "resume_continuation_needed", False)),
                digest=digest,
                changed_at=settled_at,
                process_generation=process_generation,
            )
            self._panes[ident] = watch
            stamp(
                term,
                self._confirmed(term, watch, activity, now),
                now=now,
                since=watch.moving_since,
            )
            self._checkpoint_resume_state(term, activity, watch, now)
            return None

        if digest != watch.digest:
            watch.digest = digest
            # A changed picture is movement unless it is a resize redraw (shadow
            # plus one sweep: the redraw is compared up to an interval late).
            resized_at = float(getattr(term, "last_resize_at", 0.0) or 0.0)
            if not (0 <= now - resized_at <= RESIZE_SHADOW_S + SWEEP_INTERVAL_S):
                watch.changed_at = now
        if not watch.tasked and _tasked(term):
            watch.tasked = True
        activity = read_activity(term, now=now, still_since=watch.changed_at)
        if is_settled(activity) and not is_moving(term, now, watch.changed_at):
            term.idle_seen = True

        if activity != watch.activity:
            # ``worked`` demands a CONFIRMED episode, judged like the badge (raw
            # "working" covers the tail of any lone printout).
            if watch.activity == "working" and self._episode_confirmed(term, watch):
                watch.worked = True
            watch.activity = activity
            watch.since = now
            watch.announced = False

        # Publish the reading before deciding on a bell entry. The CONFIRMED word,
        # not the raw one (raw covers the tail of any printout and would spin the
        # badge over an idle prompt). ``since`` dates the episode start, or a
        # stopped pane's last movement (the hold delays the notice).
        confirmed = self._confirmed(term, watch, activity, now)
        stamp(
            term,
            confirmed,
            now=now,
            since=watch.moving_since if confirmed == "working" else _stopped_at(term, watch),
        )
        self._checkpoint_resume_state(term, activity, watch, now)

        if watch.announced:
            return None

        kind = self._kind(activity, watch)
        from .task_state import evidence

        proof = evidence(term, now=now)
        if proof is not None:
            if proof.state == "completed" and activity == "waiting" and watch.tasked:
                kind = "completed"
            elif kind == "completed":
                kind = None
        if kind is None:
            return None
        # A mere STOP must hold still first; a dead or broken pane is news at once.
        if is_settled(activity) and now - watch.since < SETTLE_S:
            return None

        watch.announced = True
        watch.worked = False
        pending = getattr(term, "delegation_result", None)
        if pending is not None:
            self._results.append((kind, term, pending))
        if not emit:
            return None
        return self.center.add(
            Notification(
                id=f"n{next(_ids)}",
                kind=kind,
                workspace_id=str(session.id),
                workspace=str(getattr(session, "name", "") or ""),
                pane_key=ident[1],
                pane=str(getattr(term, "name", "") or ""),
                agent=str(getattr(term, "agent", "") or ""),
                display_name=str(getattr(term, "display_name", "") or ""),
                title=_title(kind, term),
                detail=_detail(term),
                created_at=now,
            )
        )

    def _confirmed(self, term: Any, watch: _PaneWatch, activity: Activity, now: float) -> Activity:
        """The word the badge wears: movement must outlast a single burst.

        ``waiting`` until the episode lasted ``WORK_CONFIRM_S``, except one that
        began in the wake of a submission or resumes within
        :data:`WORK_RESUME_GRACE_S`. On the way down :data:`WORK_HOLD_S` keeps
        "working" through a short still spell (``moving_since`` survives it);
        a question outranks the hold.
        """
        from .task_state import evidence

        proof = evidence(term, now=now)
        if proof is not None and proof.state != "unknown":
            if activity == "working":
                watch.moving_since = watch.moving_since or now
                watch.stamped_working_at = now
            else:
                watch.moving_since = None
            return activity
        if activity != "working":
            if activity == "waiting" and 0 <= now - watch.stamped_working_at <= WORK_HOLD_S:
                return "working"
            watch.moving_since = None
            return activity
        if watch.moving_since is None:
            watch.moving_since = now
        if in_submit_wake(term, watch.moving_since):
            watch.stamped_working_at = now
            return activity
        if (
            now - watch.moving_since < WORK_CONFIRM_S
            and now - watch.stamped_working_at > WORK_RESUME_GRACE_S
        ):
            return "waiting"
        watch.stamped_working_at = now
        return activity

    @staticmethod
    def _episode_confirmed(term: Any, watch: _PaneWatch) -> bool:
        """Did the movement episode that just ended count as real work?

        Judged by how long the screen kept CHANGING, not the clock at flip time
        (the ``STILL_S`` tail would let a lone burst confirm itself).
        """
        began = watch.moving_since
        if began is None:
            return False
        if in_submit_wake(term, began):
            return True
        return watch.changed_at - began >= WORK_CONFIRM_S

    def _checkpoint_resume_state(
        self, term: Any, activity: Activity, watch: _PaneWatch, now: float
    ) -> None:
        """Remember only turns proven interrupted while working (read after a restart)."""
        if activity == "working":
            self._set_resume_needed(term, watch, True)
            return
        if activity in {"asking", "failed", "stopped", "unknown"}:
            self._set_resume_needed(term, watch, False)
            return
        if activity == "exited":
            if getattr(term, "exit_code", None) in (0, None):
                self._set_resume_needed(term, watch, False)
            return
        if activity == "waiting" and now - watch.since >= SETTLE_S:
            self._set_resume_needed(term, watch, False)

    def _set_resume_needed(self, term: Any, watch: _PaneWatch, needed: bool) -> None:
        term.resume_continuation_needed = needed
        if watch.resume_needed == needed:
            return
        watch.resume_needed = needed
        self._resume_dirty = True

    @staticmethod
    def _kind(activity: Activity, watch: _PaneWatch) -> Kind | None:
        """Which entry this state deserves, or none at all."""
        if activity == "stopped":
            return "stopped"
        if activity == "failed":
            return "failed"
        if activity == "exited":
            return "exited"
        if activity == "asking":
            # Reported even if it never worked (startup MCP auth or trust prompt).
            return "needs_input"
        if activity == "waiting" and watch.worked and watch.tasked:
            # Both are load-bearing: a starting CLI's banner satisfies only ``worked``.
            return "completed"
        return None


def _tasked(term: Any) -> bool:
    """Has anybody given this pane an instruction it could have finished?

    ``last_submit_at`` or the ``prompts_sent`` counter (survives a restore).
    STRICTER than :func:`~.activity.has_work_behind_it`: a restored pane
    repainting its transcript must not ring once per terminal on every restart.
    """
    if getattr(term, "last_submit_at", None):
        return True
    try:
        return int(getattr(term, "prompts_sent", 0) or 0) > 0
    except (TypeError, ValueError):  # a test double may carry anything
        return False


def _is_agent(term: Any) -> bool:
    """Does this pane run an agent, rather than being a bare shell?"""
    try:
        from .session import accepts_prompts

        return bool(accepts_prompts(str(getattr(term, "agent", "") or "")))
    except Exception:  # noqa: BLE001 - a sweep must never fail on a lookup
        return True


_switch: tuple[float, bool] = (0.0, True)


def enabled() -> bool:
    """Is pane notification switched on? Cached; an unreadable config answers "on"."""
    global _switch
    cached_at, value = _switch
    now = time.monotonic()
    if now - cached_at < SWITCH_TTL_S:
        return value
    try:
        from dodaios.core.config import load_config

        value = bool(getattr(load_config().agentic_ide, "pane_notifications", True))
    except Exception:  # noqa: BLE001 - never let a config read stop the sweep
        value = True
    _switch = (now, value)
    return value


async def _enabled_off_loop() -> bool:
    """The same switch with the TOML parse off the event loop (AP-9/AP-26)."""
    cached_at, value = _switch
    if time.monotonic() - cached_at < SWITCH_TTL_S:
        return value
    return await asyncio.to_thread(enabled)


def reset_switch_cache() -> None:
    """Forget the cached switch — for tests, and for a live config change."""
    global _switch
    _switch = (0.0, True)


_CENTER = NotificationCenter()
_WATCHER = ActivityWatcher(_CENTER)


class ActivityFeed:
    """Which panes' PUBLISHED reading changed since the last sweep.

    Compared on what a client would SHOW (:meth:`Terminal.reading`, ``worked``,
    status) so a row and the event that patched it cannot disagree.
    """

    def __init__(self) -> None:
        self._last: dict[tuple[str, str], tuple[str, str, float, bool]] = {}

    def changes(self, registry: Registry) -> list[dict[str, Any]]:
        # Local import: ``session`` imports this module's siblings.
        """The rows whose reading differs from the last call — and drop the gone."""
        from .activity import has_work_behind_it

        changed: list[dict[str, Any]] = []
        alive: set[tuple[str, str]] = set()
        for session in registry.sessions:
            for term in session.terminals:
                ident = (str(session.id), str(getattr(term, "key", "") or ""))
                alive.add(ident)
                reading = term.reading()
                status = str(getattr(term, "status", "") or "")
                activity = str(reading.activity)
                since = float(reading.since or 0.0)
                worked = has_work_behind_it(term)
                mark = (status, activity, since, worked)
                if self._last.get(ident) != mark:
                    self._last[ident] = mark
                    changed.append(
                        {
                            "session_id": ident[0],
                            "key": ident[1],
                            "name": str(getattr(term, "name", "") or ""),
                            "status": status,
                            "activity": activity,
                            "activity_since": since,
                            "worked": worked,
                        }
                    )
        for gone in self._last.keys() - alive:
            del self._last[gone]
        return changed

    def clear(self) -> None:
        self._last.clear()


_FEED = ActivityFeed()

#: The app bus's ``publish``, handed in by the web server at router mount
#: (the registry has no bus). ``None`` = nobody listening.
Publisher = Callable[[Any], Awaitable[None]]
_publisher: Publisher | None = None


def set_publisher(publish: Publisher | None) -> None:
    """Route pane activity changes onto ``publish`` (``None`` to stop)."""
    global _publisher
    _publisher = publish


async def _publish_changes(registry: Registry) -> None:
    """Send every pane whose reading changed this sweep to the bus."""
    publish = _publisher
    changed = _FEED.changes(registry)
    if publish is None or not changed:
        return
    from dodaios.core.events import AgenticIdePaneActivity

    for row in changed:
        try:
            await publish(AgenticIdePaneActivity(**row, source_layer="agentic_ide.notifications"))
        except Exception as exc:  # noqa: BLE001 - a deaf bus must not end the sweep
            logger.warning("Agentic IDE: could not publish activity for {}: {}", row["name"], exc)


def center() -> NotificationCenter:
    """The process-wide store the routes read."""
    return _CENTER


def watcher() -> ActivityWatcher:
    """The process-wide watcher the sweep drives."""
    return _WATCHER


def reset() -> None:
    """Drop everything — for tests, and for a registry that was torn down."""
    _CENTER.clear()
    _WATCHER._panes.clear()  # noqa: SLF001 - same module, one owner
    _WATCHER._resume_dirty = False  # noqa: SLF001 - same module, one owner
    _WATCHER.take_results()
    _FEED.clear()
    from .task_state import reset as reset_task_state

    reset_task_state()
    set_publisher(None)
    reset_switch_cache()


@dataclass(slots=True)
class _Sweep:
    """The one background task, and the handle that keeps it single."""

    task: asyncio.Task[None] | None = field(default=None)


_sweep = _Sweep()


async def _run(registry: Registry) -> None:
    """Poll until the last workspace closes, then finish (self-terminating)."""
    try:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_S)
            if not registry.sessions:
                return
            try:
                from .task_state import refresh

                await refresh(registry)
                _WATCHER.poll(registry, emit=await _enabled_off_loop())
                from .followthrough import poll_ready, publish_result

                for kind, term, pending in _WATCHER.take_results():
                    if not await publish_result(kind, term, pending, _publisher):
                        from .followthrough import current

                        if current(term, pending):
                            _WATCHER._results.append((kind, term, pending))
                await poll_ready(registry, _publisher)
                if _WATCHER.take_resume_dirty():
                    await registry.persist_resume_activity()
                await _publish_changes(registry)
            except Exception as exc:  # noqa: BLE001 - one bad pane must not end the sweep
                logger.warning("Agentic IDE: pane notification sweep failed: {}", exc)
    except asyncio.CancelledError:  # pragma: no cover - shutdown
        raise
    finally:
        _sweep.task = None


def start(registry: Registry) -> None:
    """Make sure the sweep is running. Idempotent; never on the boot path (AP-26)."""
    if _sweep.task is not None and not _sweep.task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop (a synchronous test, a CLI path). Nothing to schedule, and the
        # feature is additive — the routes still answer from an empty store.
        return
    _sweep.task = loop.create_task(_run(registry), name="agentic-ide-notifications")


def stop() -> None:
    """Cancel the sweep — for tests and for a full shutdown."""
    task = _sweep.task
    _sweep.task = None
    if task is not None and not task.done():
        task.cancel()


def watching() -> bool:
    """Is the sweep actually running? An empty bell is ambiguous without it."""
    task = _sweep.task
    return task is not None and not task.done()


def state() -> dict[str, Any]:
    """Everything the bell needs in one response."""
    entries = _CENTER.list()
    return {
        "enabled": enabled(),
        "watching": watching(),
        "panes_watched": len(_WATCHER._panes),  # noqa: SLF001 - same module, one owner
        "unread": sum(1 for entry in entries if not entry.read),
        "notifications": [entry.to_dict() for entry in entries],
    }


__all__ = [
    "DETAIL_CHARS",
    "MAX_ENTRIES",
    "SETTLE_S",
    "SWEEP_INTERVAL_S",
    "WORK_HOLD_S",
    "WORK_RESUME_GRACE_S",
    "ActivityFeed",
    "ActivityWatcher",
    "Kind",
    "Notification",
    "NotificationCenter",
    "PaneLabel",
    "center",
    "enabled",
    "reset",
    "set_publisher",
    "reset_switch_cache",
    "start",
    "state",
    "stop",
    "watcher",
]
