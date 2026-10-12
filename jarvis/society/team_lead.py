"""Team leads: one member manages a team toward the person's goals.

A team is a society chat group. Its lead is one of its members, an
``orchestrator`` on the roster, and the only member that hands out work. The
person gives the TEAM a goal; from there the lead works on its own:

1. **Plan.** The lead gets a managing turn in its own chat: the goal, the
   team's mission and who is on the team. It breaks the goal into tasks and
   hands each to a member with ``society_team_assign`` (``team_tools.py``).
2. **Work.** Every task is one ``ASSIGN`` on the board, on its own trace. The
   scheduler — trusted Python — decides whether the member starts. A busy
   member is not a failure: the task waits and knocks again by itself.
3. **Review.** When a result lands, this module wakes the lead with it. The
   lead accepts, sends rework, re-assigns a blocked task or asks the person.
   Results that arrive while the lead is mid-turn are batched into the next.
4. **Report.** The lead closes the goal with ``society_team_report``; the
   next queued goal starts. A goal that came in as a board assignment (from
   Jarvis by voice, or a quest) answers that assignment with its report.

Nothing here calls a model. The lead's turns run on the lead's own seat, the
members' on theirs, and every turn belongs to a goal the person started (or a
check-in they switched on, which is an ordinary agent routine). Opening the
app never resumes one: goals that were running when the app closed come back
``paused`` and wait for the person.

Bounds, so a goal can never run away: one active goal per team, a turn budget
per goal (:data:`MAX_LEAD_TURNS`, reset when the person resumes), a task cap
(:data:`MAX_TASKS_PER_GOAL`) and the society kill switch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Final

from jarvis.missions.ids import uuid7_str

from .events import (
    USER_ACTOR,
    AgentState,
    MsgType,
    SocietyEnvelope,
    TeamGoalState,
    TeamTaskState,
    Tier,
    now_ms,
)
from .roster import LEAD_AGENT_ID, AgentRecord, slugify

log = logging.getLogger(__name__)

__all__ = [
    "CHECKIN_TAG",
    "MAX_LEAD_TURNS",
    "MAX_TASKS_PER_GOAL",
    "TRACE_PREFIX",
    "TeamGoal",
    "TeamLeadError",
    "TeamLeads",
    "TeamTask",
]

TRACE_PREFIX: Final[str] = "team:"
#: Run id the scheduler gets for work handed to a lead: the goal, not a turn.
GOAL_RUN_PREFIX: Final[str] = "goal:"
#: Managing turns a lead may spend on one goal before it pauses for the person.
MAX_LEAD_TURNS: Final[int] = 24
MAX_TASKS_PER_GOAL: Final[int] = 40
#: Goals a team may hold that are not finished yet (the active one included).
MAX_OPEN_GOALS: Final[int] = 20
MAX_GOAL_TEXT: Final[int] = 20_000
MAX_MISSION: Final[int] = 4_000
#: How much of a member's result the lead reads per task in a review.
RESULT_CHARS: Final[int] = 3_000

#: Scheduler refusals that mean "not now" rather than "never".
WAIT_REASONS: Final[frozenset[str]] = frozenset({"target_busy", "concurrency_cap"})
RETRY_DELAY_S: Final[float] = 15.0
MAX_WAIT_ATTEMPTS: Final[int] = 120
#: Results landing close together reach the lead as one review.
REVIEW_DELAY_S: Final[float] = 1.5
LEAD_RETRY_S: Final[float] = 10.0
MAX_LEAD_WAIT_ATTEMPTS: Final[int] = 90
LEAD_TURN_TIMEOUT_S: Final[float] = 30 * 60.0
SWEEP_S: Final[float] = 60.0
#: A task with no sign of life for this long is checked against the scheduler.
STALL_MS: Final[int] = 3 * 60 * 1000

CHECKIN_TAG: Final[str] = "team-checkin:"
CHECKIN_MINUTES: Final[tuple[int, ...]] = (0, 60, 240, 1440)
_PROMOTED_KEY: Final[str] = "team_lead_promoted:"

GOAL_TERMINAL: Final[frozenset[TeamGoalState]] = frozenset(
    {TeamGoalState.DONE, TeamGoalState.FAILED, TeamGoalState.CANCELLED}
)
#: Every state a goal can still be closed from.
GOAL_OPEN: Final[tuple[TeamGoalState, ...]] = (
    TeamGoalState.QUEUED,
    TeamGoalState.RUNNING,
    TeamGoalState.NEEDS_INPUT,
    TeamGoalState.PAUSED,
)
#: States that hold the team: no other goal starts while one is in them.
GOAL_ACTIVE: Final[frozenset[TeamGoalState]] = frozenset(
    {TeamGoalState.RUNNING, TeamGoalState.NEEDS_INPUT, TeamGoalState.PAUSED}
)
TASK_OPEN: Final[frozenset[TeamTaskState]] = frozenset(
    {TeamTaskState.WAITING, TeamTaskState.ASSIGNED, TeamTaskState.RUNNING}
)
TASK_FINISHED: Final[frozenset[TeamTaskState]] = frozenset(
    {TeamTaskState.DONE, TeamTaskState.BLOCKED}
)

#: Standing instructions of a lead created from the team board.
LEAD_DESCRIPTION: Final[str] = (
    "You manage a team of agents for the person. You own the outcome of every goal the "
    "team is given: break it into concrete tasks, hand each task to the member whose role "
    "fits best, check what comes back against the goal, send rework when it falls short, "
    "and report the finished result. You plan, coordinate and review; the members do the "
    "specialist work. Keep work moving without being asked, and bring a decision to the "
    "person only when it is truly theirs to make."
)

_LEAD_RULES: Final[str] = (
    "How you lead:\n"
    "- Hand out work with society_team_assign: one task per call, to the member whose role "
    "fits. Give an independently actionable brief: objective, what you already know, scope, "
    "and what output proves it is done. Members work in parallel, so assign everything that "
    "can start now in the same turn.\n"
    "- Never wait or poll inside a turn. After assigning, end your turn with one short line "
    "on what is in progress. You are woken automatically the moment a result arrives.\n"
    "- When woken with results, judge them against the goal. Send follow-up or rework as a "
    "new assignment, give a blocked task to another member, or answer a member's question "
    "inside a new assignment so the answer is tracked.\n"
    "- Do a task yourself only when no member fits it.\n"
    "- Close the goal with society_team_report status=done and the complete result for the "
    "person: what was achieved, where the output is, what remains open. Use "
    "status=needs_input for a decision only the person can make (ask one precise question), "
    "status=progress for an interim update on long work, status=failed when the goal cannot "
    "be reached and why.\n"
    "- society_team_board shows the goal and every task at any time."
)

CHECKIN_PROMPT: Final[str] = (
    "Team check-in. Call society_team_board first. If a goal is stuck, blocked or waiting on "
    "a member, act on it: follow up, re-assign, or report to the person. If the team mission "
    "names standing duties that are due and no open goal covers them, start that work with "
    "society_team_assign. If nothing needs you, say so in one line and stop. Never invent "
    "work the mission or an open goal does not call for."
)

_NAME_UNSAFE: Final[re.Pattern[str]] = re.compile(r"[/\\:@#<>\"'`]")


class TeamLeadError(ValueError):
    """A team-lead request that cannot be honored; ``status`` is the HTTP answer."""

    def __init__(self, message: str, *, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def goal_title(text: str, explicit: str = "") -> str:
    """A short title: the explicit one, else the first line of the goal."""
    title = " ".join((explicit or "").split())
    if not title:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        title = " ".join(first.split())
    if not title:
        return "Goal"
    return title if len(title) <= 90 else title[:89].rstrip() + "…"


@dataclass(slots=True)
class TeamTask:
    task_id: str
    goal_id: str
    agent_id: str
    title: str
    brief: str
    state: TeamTaskState
    trace_id: str
    assign_event_id: str | None
    run_id: str
    result: str
    reviewed: bool
    attempts: int
    created_ms: int
    updated_ms: int
    done_ms: int | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> TeamTask:
        return cls(
            task_id=str(row["task_id"]),
            goal_id=str(row["goal_id"]),
            agent_id=str(row["agent_id"]),
            title=str(row.get("title") or ""),
            brief=str(row.get("brief") or ""),
            state=TeamTaskState(str(row.get("state") or "assigned")),
            trace_id=str(row["trace_id"]),
            assign_event_id=row.get("assign_event_id"),
            run_id=str(row.get("run_id") or ""),
            result=str(row.get("result") or ""),
            reviewed=bool(row.get("reviewed")),
            attempts=int(row.get("attempts") or 0),
            created_ms=int(row.get("created_ms") or 0),
            updated_ms=int(row.get("updated_ms") or 0),
            done_ms=row.get("done_ms"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal_id": self.goal_id,
            "agent_id": self.agent_id,
            "title": self.title,
            "brief": self.brief,
            "state": str(self.state),
            "result": self.result,
            "reviewed": self.reviewed,
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
            "done_ms": self.done_ms,
        }


@dataclass(slots=True)
class TeamGoal:
    goal_id: str
    group_id: str
    lead_agent_id: str
    title: str
    text: str
    state: TeamGoalState
    report: str
    note: str
    lead_turns: int
    lang: str
    origin: dict[str, Any]
    created_ms: int
    updated_ms: int
    done_ms: int | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> TeamGoal:
        return cls(
            goal_id=str(row["goal_id"]),
            group_id=str(row["group_id"]),
            lead_agent_id=str(row["lead_agent_id"]),
            title=str(row.get("title") or ""),
            text=str(row.get("text") or ""),
            state=TeamGoalState(str(row.get("state") or "queued")),
            report=str(row.get("report") or ""),
            note=str(row.get("note") or ""),
            lead_turns=int(row.get("lead_turns") or 0),
            lang=str(row.get("lang") or ""),
            origin=_loads(row.get("origin_json")),
            created_ms=int(row.get("created_ms") or 0),
            updated_ms=int(row.get("updated_ms") or 0),
            done_ms=row.get("done_ms"),
        )

    def to_dict(self, tasks: list[TeamTask] | None = None) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "group_id": self.group_id,
            "lead_agent_id": self.lead_agent_id,
            "title": self.title,
            "text": self.text,
            "state": str(self.state),
            "report": self.report,
            "note": self.note,
            "lead_turns": self.lead_turns,
            "source": str(self.origin.get("kind") or "board"),
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
            "done_ms": self.done_ms,
            "tasks": [task.to_dict() for task in tasks or []],
        }


class TeamLeads:
    """Leadership, goals and tasks of every team, over the society runtime."""

    def __init__(
        self,
        runtime: Any,
        *,
        publish: Callable[[Any], Any] | None = None,
        retry_delay_s: float = RETRY_DELAY_S,
        review_delay_s: float = REVIEW_DELAY_S,
        lead_retry_s: float = LEAD_RETRY_S,
        sweep_s: float = SWEEP_S,
    ) -> None:
        self._rt = runtime
        self._publish = publish
        self._retry_delay = retry_delay_s
        self._review_delay = review_delay_s
        self._lead_retry = lead_retry_s
        self._sweep_s = sweep_s
        self._unsubscribe: Callable[[], None] | None = None
        #: lead agent id -> the group it leads (a synchronous read for the tool set).
        self._leads: dict[str, str] = {}
        #: Every group as last read, for the synchronous prompt builders.
        self._groups: dict[str, dict[str, Any]] = {}
        #: goal id -> (lead session, turn id) of the managing turn in flight.
        self._turns: dict[str, tuple[str, str]] = {}
        #: lead agent id -> the goal its managing turn belongs to.
        self._lead_goal: dict[str, str] = {}
        #: What the person said about a goal that its lead has not read yet.
        self._told: dict[str, list[str]] = {}
        #: Goals the person resumed whose lead has not picked them up yet.
        self._resumed: set[str] = set()
        #: Goals whose lead was asked once for a typed report after a plain answer.
        self._nudged: set[str] = set()
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._sweeper: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ wiring

    async def start(self) -> None:
        """Subscribe to the board, load who leads what, park interrupted goals."""
        if self._unsubscribe is None:
            self._unsubscribe = self._rt.store.bus.subscribe_all(self._on_envelope)
        await self.refresh()
        await self._recover()
        if self._sweeper is None:
            self._sweeper = asyncio.create_task(self._sweep_loop(), name="society-team-sweep")

    def detach(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        for handle in self._timers.values():
            handle.cancel()
        self._timers.clear()
        if self._sweeper is not None:
            self._sweeper.cancel()
            self._sweeper = None
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    async def refresh(self) -> None:
        """Re-read the groups into the synchronous caches."""
        groups = await self._rt.store.list_chat_groups()
        self._groups = {str(g["group_id"]): g for g in groups}
        self._leads = {
            str(g["lead_agent_id"]): str(g["group_id"]) for g in groups if g.get("lead_agent_id")
        }

    def group_led_by(self, agent_id: str) -> str | None:
        """The group ``agent_id`` leads, else ``None``. Synchronous, no IO."""
        return self._leads.get(agent_id)

    def teams_snapshot(self) -> list[dict[str, Any]]:
        """Teams that have a lead, as last read. Synchronous, no IO."""
        return [dict(g) for g in self._groups.values() if g.get("lead_agent_id")]

    def _lock(self, group_id: str) -> asyncio.Lock:
        lock = self._locks.get(group_id)
        if lock is None:
            lock = self._locks[group_id] = asyncio.Lock()
        return lock

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(self._guarded(coro))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    @staticmethod
    async def _guarded(coro: Any) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a failed step is logged; the sweep parks a stuck goal
            log.warning("society team lead: background step failed", exc_info=True)

    def _arm(self, key: str, delay_s: float, factory: Callable[[], Any]) -> None:
        old = self._timers.pop(key, None)
        if old is not None:
            old.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def fire() -> None:
            self._timers.pop(key, None)
            self._spawn(factory())

        self._timers[key] = loop.call_later(max(0.0, delay_s), fire)

    def _disarm(self, key: str) -> None:
        handle = self._timers.pop(key, None)
        if handle is not None:
            handle.cancel()

    # ------------------------------------------------------------- reads

    async def get_goal(self, goal_id: str) -> TeamGoal | None:
        row = await self._rt.store.get_team_goal_row(goal_id)
        return TeamGoal.from_row(row) if row else None

    async def goals(self, group_id: str, *, limit: int = 50) -> list[TeamGoal]:
        rows = await self._rt.store.list_team_goal_rows(group_id=group_id, limit=limit)
        return [TeamGoal.from_row(r) for r in rows]

    async def tasks(self, goal_id: str) -> list[TeamTask]:
        return [TeamTask.from_row(r) for r in await self._rt.store.list_team_task_rows(goal_id)]

    async def _active_goal(self, group_id: str) -> TeamGoal | None:
        """The goal that holds the team right now (running, waiting or paused)."""
        active = [g for g in await self.goals(group_id, limit=200) if g.state in GOAL_ACTIVE]
        running = [g for g in active if g.state is TeamGoalState.RUNNING]
        pick = running or active
        return min(pick, key=lambda g: g.created_ms) if pick else None

    async def snapshot(self, group_id: str) -> dict[str, Any]:
        """Everything the team board shows; reading it never starts a turn."""
        group = await self._rt.store.get_chat_group(group_id)
        if group is None:
            raise TeamLeadError("chat group not found", status=404)
        lead_id = group.get("lead_agent_id")
        lead = await self._rt.roster.get(lead_id) if lead_id else None
        goals = await self.goals(group_id)
        rows = [goal.to_dict(await self.tasks(goal.goal_id)) for goal in goals]
        return {
            "group_id": group_id,
            "lead_agent_id": lead_id,
            "lead_available": lead is not None and lead.state is AgentState.ACTIVE,
            "mission": group.get("mission") or "",
            "checkin_minutes": await self.checkin_minutes(group_id) if lead is not None else 0,
            "goals": rows,
            "working": any(goal.goal_id in self._turns for goal in goals),
            "max_lead_turns": MAX_LEAD_TURNS,
        }

    # -------------------------------------------------------- leadership

    async def _require_group(self, group_id: str) -> dict[str, Any]:
        group = await self._rt.store.get_chat_group(group_id)
        if group is None:
            raise TeamLeadError("chat group not found", status=404)
        return group

    async def _promote(self, agent: AgentRecord) -> None:
        """A lead assigns work, which the scheduler allows an orchestrator only."""
        if agent.tier is not Tier.SPECIALIST:
            return
        await self._rt.store.set_meta(
            _PROMOTED_KEY + agent.agent_id,
            json.dumps({"max_concurrent_runs": agent.max_concurrent_runs}),
        )
        await self._rt.roster.update(
            agent.agent_id,
            {"tier": Tier.ORCHESTRATOR, "max_concurrent_runs": max(3, agent.max_concurrent_runs)},
        )

    async def _demote(self, agent_id: str) -> None:
        """Undo :meth:`_promote`; an agent that was an orchestrator before stays one."""
        saved = await self._rt.store.get_meta(_PROMOTED_KEY + agent_id, "")
        if not saved:
            return
        await self._rt.store.set_meta(_PROMOTED_KEY + agent_id, "")
        agent = await self._rt.roster.get(agent_id)
        if agent is None or agent.tier is not Tier.ORCHESTRATOR:
            return
        runs = int(_loads(saved).get("max_concurrent_runs") or 1)
        await self._rt.roster.update(
            agent_id, {"tier": Tier.SPECIALIST, "max_concurrent_runs": max(1, runs)}
        )

    async def set_lead(self, group_id: str, agent_id: str | None) -> dict[str, Any]:
        """Name the member that manages the team, or clear the lead with ``None``."""
        async with self._lock(group_id):
            group = await self._require_group(group_id)
            current = group.get("lead_agent_id")
            if agent_id == current:
                return group
            if current and await self._active_goal(group_id) is not None:
                raise TeamLeadError("Stop the team's current goal before changing its lead.")
            minutes = await self.checkin_minutes(group_id) if current else 0
            if agent_id is None:
                await self._drop_checkin(group_id)
                group = await self._rt.store.set_chat_group_lead(group_id, None)
                await self._demote(str(current))
                await self.refresh()
                await self._announce(group_id, reason="lead")
                return group
            agent = await self._rt.roster.get(agent_id)
            if agent is None or agent.state is AgentState.ARCHIVED:
                raise TeamLeadError("That agent is not available.", status=404)
            if agent.agent_id == LEAD_AGENT_ID:
                raise TeamLeadError(
                    "Jarvis already leads every agent; pick another member.", status=422
                )
            other = self._leads.get(agent.agent_id)
            if other and other != group_id:
                raise TeamLeadError(f"{agent.name} already leads another team.")
            if current:
                await self._drop_checkin(group_id)
            members = list(group["members"])
            if agent.agent_id not in members:
                members.append(agent.agent_id)
                await self._rt.store.update_chat_group(group_id, group["name"], members)
            await self._promote(agent)
            group = await self._rt.store.set_chat_group_lead(group_id, agent.agent_id)
            if current:
                await self._demote(str(current))
            await self.refresh()
            if minutes:
                try:
                    await self.set_checkin(group_id, minutes)
                except TeamLeadError:
                    log.info("society team lead: check-in not moved to the new lead")
            await self._announce(group_id, reason="lead")
            return group

    async def create_lead(
        self, group_id: str, *, name: str = "", fields: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], AgentRecord]:
        """Create a new agent whose job is managing this team, and make it the lead."""
        group = await self._require_group(group_id)
        if group.get("lead_agent_id") and await self._active_goal(group_id) is not None:
            raise TeamLeadError("Stop the team's current goal before changing its lead.")
        base = " ".join(_NAME_UNSAFE.sub(" ", name or f"{group['name']} Lead").split())[:36]
        base = base or "Team Lead"
        candidate, number = base, 2
        while await self._rt.roster.resolve(candidate) is not None:
            candidate = f"{base} {number}"
            number += 1
        agent, _ = await self._rt.roster.create(
            name=candidate,
            title="Team lead",
            description=LEAD_DESCRIPTION,
            tier=Tier.ORCHESTRATOR,
            **(fields or {}),
        )
        return await self.set_lead(group_id, agent.agent_id), agent

    async def set_mission(self, group_id: str, mission: str) -> dict[str, Any]:
        await self._require_group(group_id)
        group = await self._rt.store.set_chat_group_mission(group_id, mission.strip()[:MAX_MISSION])
        await self.refresh()
        await self._announce(group_id, reason="mission")
        return group

    async def members_changed(self, group_id: str, members: list[str]) -> None:
        """A group edit: a lead that left the team stops leading it."""
        group = self._groups.get(group_id) or await self._rt.store.get_chat_group(group_id) or {}
        lead_id = group.get("lead_agent_id")
        if lead_id and lead_id not in members:
            if await self._active_goal(group_id) is not None:
                raise TeamLeadError("Stop the team's current goal before removing its lead.")
            await self.set_lead(group_id, None)
        else:
            await self.refresh()

    async def group_deleted(self, group_id: str) -> None:
        """The team is gone: stop its goals, free its lead, forget its history."""
        for goal in await self.goals(group_id, limit=1000):
            if goal.state not in GOAL_TERMINAL:
                await self.cancel(goal.goal_id)
        group = await self._rt.store.get_chat_group(group_id)
        lead_id = (group or {}).get("lead_agent_id")
        if lead_id:
            await self._drop_checkin(group_id)
            await self._rt.store.set_chat_group_lead(group_id, None)
            await self._demote(str(lead_id))
        await self._rt.store.delete_team_goals(group_id)
        self._locks.pop(group_id, None)

    # ----------------------------------------------------------- check-ins

    async def _checkin_rows(self, group_id: str) -> list[dict[str, Any]]:
        store, _ = self._rt.task_services()
        group = self._groups.get(group_id) or {}
        lead_id = group.get("lead_agent_id")
        if store is None or not lead_id:
            return []
        from .routines import list_routines

        ended = {"completed", "cancelled", "failed", "interrupted"}
        return [
            row
            for row in await list_routines(store, str(lead_id))
            if CHECKIN_TAG + group_id in row.get("tags", ()) and row.get("state") not in ended
        ]

    async def checkin_minutes(self, group_id: str) -> int:
        """How often the lead looks at its team unprompted; ``0`` = never."""
        try:
            rows = await self._checkin_rows(group_id)
        except Exception:  # noqa: BLE001 — an unreadable task store reads as "off" on the board
            log.warning("society team lead: check-in state unreadable", exc_info=True)
            return 0
        for row in rows:
            seconds = float((row.get("trigger") or {}).get("interval_seconds") or 0)
            if seconds > 0:
                return int(round(seconds / 60))
        return 0

    async def _drop_checkin(self, group_id: str) -> None:
        store, scheduler = self._rt.task_services()
        if store is None or scheduler is None:
            return
        for row in await self._checkin_rows(group_id):
            task_id = str(row.get("id"))
            await scheduler.cancel_task(task_id)
            await store.delete(task_id)

    async def set_checkin(self, group_id: str, minutes: int) -> int:
        """Switch the lead's unprompted check-in on (an agent routine) or off."""
        if minutes not in CHECKIN_MINUTES:
            raise TeamLeadError("Unknown check-in interval.", status=422)
        group = await self._require_group(group_id)
        lead_id = group.get("lead_agent_id")
        lead = await self._rt.roster.get(lead_id) if lead_id else None
        if lead is None:
            raise TeamLeadError("This team has no lead yet.")
        store, scheduler = self._rt.task_services()
        if store is None or scheduler is None:
            raise TeamLeadError("The task scheduler is unavailable.", status=503)
        await self.refresh()
        await self._drop_checkin(group_id)
        if minutes:
            from .routines import build_task_spec, create_routine

            spec = build_task_spec(
                lead,
                title=f"Team check-in: {group['name']}",
                prompt=CHECKIN_PROMPT,
                schedule={"kind": "every", "interval_seconds": minutes * 60},
            )
            spec = spec.model_copy(update={"tags": (*spec.tags, CHECKIN_TAG + group_id)})
            await create_routine(store, scheduler, spec)
        await self._announce(group_id, reason="checkin")
        return minutes

    # ------------------------------------------------------------- goals

    def _language(self, text: str, lang: str | None) -> str:
        if lang:
            return str(lang)
        try:
            from jarvis.core.turn_language import resolve_output_language

            cfg = self._rt.config()
            pinned = getattr(getattr(cfg, "brain", None), "reply_language", "auto")
            return str(resolve_output_language(pinned, "", text) or "")
        except Exception:  # noqa: BLE001 — without a language the lead answers in the goal's own
            log.debug("society team lead: output language unresolved", exc_info=True)
            return ""

    async def start_goal(
        self,
        group_id: str,
        text: str,
        *,
        title: str = "",
        lang: str | None = None,
        origin: dict[str, Any] | None = None,
    ) -> TeamGoal:
        """Give the team a goal. It starts at once, or queues behind the current one."""
        clean = text.strip()[:MAX_GOAL_TEXT]
        if not clean:
            raise TeamLeadError("A goal needs a description.", status=422)
        group = await self._require_group(group_id)
        lead_id = group.get("lead_agent_id")
        if not lead_id:
            raise TeamLeadError("This team has no lead yet.")
        if await self._rt.store.kill_switch():
            raise TeamLeadError("The society is paused.")
        goals = await self.goals(group_id, limit=200)
        open_goals = [g for g in goals if g.state not in GOAL_TERMINAL]
        if len(open_goals) >= MAX_OPEN_GOALS:
            raise TeamLeadError("This team already has too many open goals.")
        goal_id = uuid7_str()
        stamp = now_ms()
        await self._rt.store.insert_team_goal(
            {
                "goal_id": goal_id,
                "group_id": group_id,
                "lead_agent_id": str(lead_id),
                "title": goal_title(clean, title),
                "text": clean,
                "state": str(TeamGoalState.QUEUED),
                "lang": self._language(clean, lang),
                "origin_json": json.dumps(origin or {}),
                "created_ms": stamp,
                "updated_ms": stamp,
            }
        )
        await self._announce(group_id, goal_id=goal_id, state=TeamGoalState.QUEUED)
        await self._advance(group_id)
        goal = await self.get_goal(goal_id)
        assert goal is not None
        return goal

    async def accept_assignment(self, lead: AgentRecord, env: SocietyEnvelope) -> str:
        """An ``ASSIGN`` to a team lead (from Jarvis, the person or a quest)
        becomes the team's goal; its report answers the assignment."""
        group_id = self._leads.get(lead.agent_id)
        if group_id is None:
            raise TeamLeadError("This agent leads no team.")
        goal = await self.start_goal(
            group_id,
            env.text or str(env.payload.get("task") or ""),
            title=str(env.payload.get("title") or ""),
            lang=str(env.payload.get("lang") or "") or None,
            origin={
                "kind": "jarvis" if env.from_agent == LEAD_AGENT_ID else "assignment",
                "event_id": env.event_id,
            },
        )
        return f"{GOAL_RUN_PREFIX}{goal.goal_id}"

    async def _advance(self, group_id: str) -> None:
        """Start the team's oldest queued goal when nothing else holds the team."""
        async with self._lock(group_id):
            goals = await self.goals(group_id, limit=200)
            if any(goal.state in GOAL_ACTIVE for goal in goals):
                return
            queued = sorted(
                (g for g in goals if g.state is TeamGoalState.QUEUED), key=lambda g: g.created_ms
            )
            if not queued:
                return
            goal = queued[0]
            if not await self._move(
                goal, TeamGoalState.RUNNING, (TeamGoalState.QUEUED,), lead_turns=0, note=""
            ):
                return
        self._wake_lead(goal.goal_id)

    async def tell(self, goal_id: str, text: str) -> TeamGoal:
        """The person answers the lead's question or steers a goal in progress."""
        message = text.strip()[:MAX_GOAL_TEXT]
        if not message:
            raise TeamLeadError("A message is required.", status=422)
        goal = await self._require_goal(goal_id)
        if goal.state in GOAL_TERMINAL or goal.state is TeamGoalState.QUEUED:
            raise TeamLeadError("This goal is not in progress.")
        if await self._rt.store.kill_switch():
            raise TeamLeadError("The society is paused.")
        # A goal that waited gets a fresh turn budget; one in progress keeps its own.
        waited = (TeamGoalState.NEEDS_INPUT, TeamGoalState.PAUSED)
        moved = await self._move(
            goal, TeamGoalState.RUNNING, waited, note="", lead_turns=0
        ) or await self._move(goal, TeamGoalState.RUNNING, (TeamGoalState.RUNNING,), note="")
        if not moved:
            raise TeamLeadError("This goal is not in progress.")
        self._nudged.discard(goal_id)
        self._told.setdefault(goal_id, []).append(message)
        self._wake_lead(goal_id)
        return await self._require_goal(goal_id)

    async def resume(self, goal_id: str) -> TeamGoal:
        """Continue a paused goal, retry a failed one, or start a queued one."""
        goal = await self._require_goal(goal_id)
        if goal.state is TeamGoalState.QUEUED:
            await self._advance(goal.group_id)
            return await self._require_goal(goal_id)
        if goal.state not in (TeamGoalState.PAUSED, TeamGoalState.FAILED):
            raise TeamLeadError("This goal is not paused.")
        if await self._rt.store.kill_switch():
            raise TeamLeadError("The society is paused.")
        stopped = (TeamGoalState.PAUSED, TeamGoalState.FAILED)
        active = await self._active_goal(goal.group_id)
        if active is not None and active.goal_id != goal_id:
            # Another goal holds the team: the retried one waits its turn.
            if not await self._move(
                goal, TeamGoalState.QUEUED, stopped, note="", done_ms=None
            ):
                raise TeamLeadError("This goal is not paused.")
            return await self._require_goal(goal_id)
        if not await self._move(
            goal, TeamGoalState.RUNNING, stopped, lead_turns=0, note="", done_ms=None
        ):
            raise TeamLeadError("This goal is not paused.")
        self._nudged.discard(goal_id)
        self._resumed.add(goal_id)
        self._wake_lead(goal_id)
        return await self._require_goal(goal_id)

    async def cancel(self, goal_id: str) -> TeamGoal:
        """Stop a goal: its lead turn and every member task that still runs."""
        goal = await self._require_goal(goal_id)
        if goal.state in GOAL_TERMINAL:
            return goal
        turn = self._turns.get(goal_id)
        await self._finish(goal, TeamGoalState.CANCELLED, note="cancelled")
        if turn is not None and turn[1]:
            await self._cancel_turn(turn[0], turn[1])
        return await self._require_goal(goal_id)

    async def halt(self) -> int:
        """The kill switch: every running goal pauses; nothing is retried."""
        for key in list(self._timers):
            self._disarm(key)
        paused = 0
        for row in await self._rt.store.list_team_goal_rows(limit=1000):
            goal = TeamGoal.from_row(row)
            if goal.state is TeamGoalState.RUNNING and await self._move(
                goal, TeamGoalState.PAUSED, (TeamGoalState.RUNNING,), note="society_paused"
            ):
                paused += 1
        return paused

    async def _require_goal(self, goal_id: str) -> TeamGoal:
        goal = await self.get_goal(goal_id)
        if goal is None:
            raise TeamLeadError("goal not found", status=404)
        return goal

    async def _move(
        self,
        goal: TeamGoal,
        state: TeamGoalState,
        expected: tuple[TeamGoalState, ...],
        **fields: Any,
    ) -> bool:
        """Move a goal to ``state`` only while it is in one of ``expected``.

        Every state change goes through here, so a stop that lands while
        another caller holds a stale read wins instead of being undone.
        """
        fields["state"] = str(state)
        fields["updated_ms"] = now_ms()
        moved = await self._rt.store.transition_team_goal(
            goal.goal_id, [str(s) for s in expected], fields
        )
        if moved:
            await self._announce(goal.group_id, goal_id=goal.goal_id, state=state)
        return bool(moved)

    async def _cancel_turn(self, session_id: str, turn_id: str) -> None:
        svc = self._rt.chat_service()
        if svc is None or not turn_id:
            return
        try:
            await svc.cancel(session_id, expected_turn_id=turn_id)
        except Exception:  # noqa: BLE001 — the goal is closed either way; the turn ends on its own
            log.warning("society team lead: turn %s could not be stopped", turn_id, exc_info=True)

    async def _finish(
        self, goal: TeamGoal, state: TeamGoalState, *, report: str | None = None, note: str = ""
    ) -> bool:
        """Close a goal: stop what still runs, answer its origin, start the next.

        ``False`` when the goal was already closed by someone else.
        """
        fields: dict[str, Any] = {"note": note, "done_ms": now_ms()}
        if report is not None:
            fields["report"] = report
        if not await self._move(goal, state, GOAL_OPEN, **fields):
            return False
        self._disarm(f"lead:{goal.goal_id}")
        self._told.pop(goal.goal_id, None)
        self._resumed.discard(goal.goal_id)
        self._nudged.discard(goal.goal_id)
        for task in await self.tasks(goal.goal_id):
            if task.state not in TASK_OPEN:
                continue
            self._disarm(f"task:{task.task_id}")
            await self._rt.store.update_team_task(
                task.task_id,
                {
                    "state": str(TeamTaskState.CANCELLED),
                    "updated_ms": now_ms(),
                    "done_ms": now_ms(),
                    "reviewed": 1,
                },
            )
            if task.run_id:
                self._rt.scheduler.note_run_ended(task.run_id)
            if task.run_id.startswith("turn:"):
                from .roster import canonical_session_id

                await self._cancel_turn(
                    canonical_session_id(task.agent_id), task.run_id.removeprefix("turn:")
                )
        await self._answer_origin(goal, state, report if report is not None else goal.report, note)
        await self._announce(goal.group_id, goal_id=goal.goal_id, state=state)
        if goal.goal_id not in self._turns:
            await self._advance(goal.group_id)
        return True

    async def _answer_origin(
        self, goal: TeamGoal, state: TeamGoalState, report: str, note: str
    ) -> None:
        """A goal that came in as a board assignment answers it with a RESULT."""
        event_id = str(goal.origin.get("event_id") or "")
        if not event_id or goal.origin.get("answered"):
            return
        request = await self._rt.store.get_event(event_id)
        if request is None:
            return
        done = state is TeamGoalState.DONE
        summary = (report or note or "The team goal ended without a report.").strip()
        try:
            await self._rt.store.append_and_publish(
                SocietyEnvelope(
                    msg_type=MsgType.RESULT,
                    from_agent=goal.lead_agent_id,
                    to_agent=request.from_agent if request.from_agent != USER_ACTOR else None,
                    trace_id=request.trace_id,
                    parent_event_id=request.event_id,
                    payload={
                        "run_id": f"{GOAL_RUN_PREFIX}{goal.goal_id}",
                        "status": "done" if done else "blocked",
                        "done": summary[:2000],
                        "output": [f"team:{goal.group_id}"],
                        "evidence": [],
                        "open": [] if done else [(note or str(state))[:500]],
                        "next_owner": None,
                        "text": summary[:500],
                    },
                )
            )
        except Exception:  # noqa: BLE001 — the report stays on the team board either way
            log.warning("society team lead: origin of %s not answered", goal.goal_id, exc_info=True)
            return
        await self._rt.store.update_team_goal(
            goal.goal_id, {"origin_json": json.dumps({**goal.origin, "answered": True})}
        )
        lead = await self._rt.roster.get(goal.lead_agent_id)
        if lead is not None:
            await self._rt.report_to_lead(
                lead, request, status="done" if done else "blocked", summary=summary
            )

    # ------------------------------------------------------ the lead turn

    def _roster_lines(self, group: Mapping[str, Any], lead_id: str) -> list[str]:
        by_id = {a.agent_id: a for a in self._rt.roster.snapshot()}
        lines: list[str] = []
        for member_id in group.get("members", []):
            agent = by_id.get(member_id)
            if agent is None or member_id in (lead_id, LEAD_AGENT_ID):
                continue
            if agent.state is AgentState.ARCHIVED:
                continue
            line = f"- {agent.name}"
            if agent.title.strip():
                line += f" — {agent.title.strip()}"
            state = "paused" if agent.state is AgentState.PAUSED else (
                "working" if self._rt.scheduler.active_runs(agent.agent_id) else "free"
            )
            lines.append(f"{line} ({state})")
        return lines

    def _name(self, agent_id: str) -> str:
        for agent in self._rt.roster.snapshot():
            if agent.agent_id == agent_id:
                return str(agent.name)
        return agent_id

    def _board_lines(self, tasks: list[TeamTask], *, results: bool) -> list[str]:
        lines: list[str] = []
        for task in tasks:
            line = f'- {self._name(task.agent_id)} — "{task.title}": {task.state}'
            lines.append(line)
            if results and task.state in TASK_FINISHED and task.result:
                lines.append("  " + task.result[:RESULT_CHARS].replace("\n", "\n  "))
        return lines

    def _frame(self, goal: TeamGoal, kind: str, body: list[str]) -> str:
        group = self._groups.get(goal.group_id) or {}
        lines = [f"[{kind} for team {group.get('name') or goal.group_id}]", *body]
        lines.append(f"Goal id: {goal.goal_id}. Managing turns left: "
                     f"{max(0, MAX_LEAD_TURNS - goal.lead_turns - 1)}.")
        return "\n".join(lines)

    def _plan_prompt(self, goal: TeamGoal) -> tuple[str, str, list[str]]:
        group = self._groups.get(goal.group_id) or {}
        team = self._roster_lines(group, goal.lead_agent_id)
        body = ["The person gave your team this goal:", goal.text, ""]
        if str(group.get("mission") or "").strip():
            body += ["Team mission: " + str(group["mission"]).strip(), ""]
        body += ["Your team right now:", *(team or ["- (no other members yet)"]), ""]
        body += [
            "Plan the work and hand out every task that can start now. If the goal is too "
            "unclear to plan, ask the person with society_team_report status=needs_input.",
        ]
        return self._frame(goal, "team goal", body), goal.text, []

    def _news_body(self, goal: TeamGoal, tasks: list[TeamTask]) -> tuple[list[str], list[str]]:
        """What happened since the lead last looked, and the task ids it covers."""
        news = [t for t in tasks if t.state in TASK_FINISHED and not t.reviewed]
        open_tasks = [t for t in tasks if t.state in TASK_OPEN]
        body: list[str] = []
        if news:
            body += ["New results:", *self._board_lines(news, results=True), ""]
        if open_tasks:
            body += ["Still in progress:", *self._board_lines(open_tasks, results=False), ""]
        elif not news:
            body += ["No task is in progress.", ""]
        return body, [t.task_id for t in news]

    def _compose(self, goal: TeamGoal, tasks: list[TeamTask]) -> tuple[str, str, list[str]] | None:
        """What the lead needs to hear now: the person's words first, then a
        resume, the first plan, or new results. ``None`` = nothing to say."""
        told = self._told.get(goal.goal_id)
        if told:
            news, reported = self._news_body(goal, tasks)
            body = [f"Goal: {goal.title}", "", "The person says about this goal:", *told, ""]
            body += [*news, "Continue leading the goal with this answer."]
            return self._frame(goal, "team goal reply", body), told[-1], reported
        if goal.goal_id in self._resumed:
            news, reported = self._news_body(goal, tasks)
            body = ["The person asked you to continue this goal:", goal.text, ""]
            body += news if tasks else ["No task was handed out yet.", ""]
            body.append(
                "Pick the goal up from this state: re-assign what was interrupted or "
                "blocked, then lead it to its report."
            )
            return self._frame(goal, "team goal resumed", body), goal.title, reported
        if not tasks and goal.lead_turns == 0:
            return self._plan_prompt(goal)
        news, reported = self._news_body(goal, tasks)
        if not reported:
            if goal.goal_id not in self._nudged or any(t.state in TASK_OPEN for t in tasks):
                return None
            body = [
                f"Goal: {goal.title}",
                "",
                "Your last turn ended with no task running and no report, so the person "
                "has no result yet. If the goal is achieved, call society_team_report "
                "status=done with the complete result. If only the person can decide "
                "something, use status=needs_input with one question. If work is still "
                "needed, hand it out now.",
            ]
            return self._frame(goal, "team goal check", body), goal.title, []
        body = [f"Goal: {goal.title}", "", *news]
        body.append(
            "Decide now. Accept what is good, send rework or the next step as a new "
            "assignment, re-assign what is blocked, or close the goal with "
            "society_team_report. If work is still running and nothing needs a decision, "
            "end the turn in one line; you are woken again."
        )
        shown = f"{goal.title}: {len(reported)} result" + ("s" if len(reported) != 1 else "")
        return self._frame(goal, "team update", body), shown, reported

    async def _park(self, goal: TeamGoal, note: str) -> None:
        """Pause a running goal with the reason; a goal already stopped stays so."""
        if await self._move(goal, TeamGoalState.PAUSED, (TeamGoalState.RUNNING,), note=note):
            self._disarm(f"lead:{goal.goal_id}")

    def _wake_lead(self, goal_id: str, delay_s: float = 0.0, attempt: int = 0) -> None:
        """Ask for a managing turn; several asks before it starts become one."""
        self._arm(f"lead:{goal_id}", delay_s, lambda: self._lead_turn(goal_id, attempt))

    async def _lead_turn(self, goal_id: str, attempt: int = 0) -> None:
        """Give the lead one managing turn for ``goal_id``; a busy lead is retried.

        One turn per goal at a time. Whatever arrives while it runs — a result,
        the person's reply — stays pending and :meth:`_after_lead_turn` asks
        again, so nothing is lost and nothing is said twice.
        """
        if goal_id in self._turns:
            return
        # Claimed before the first await, so a second caller cannot start a twin.
        self._turns[goal_id] = ("", "")
        lead_id = ""
        started = False
        try:
            goal = await self.get_goal(goal_id)
            if goal is None or goal.state is not TeamGoalState.RUNNING:
                return
            lead_id = goal.lead_agent_id
            if await self._rt.store.kill_switch():
                await self._park(goal, "society_paused")
                return
            lead = await self._rt.roster.get(lead_id)
            svc = self._rt.chat_service()
            if lead is None or lead.state is not AgentState.ACTIVE or svc is None:
                await self._park(goal, "lead_unavailable")
                return
            if goal.lead_turns >= MAX_LEAD_TURNS:
                await self._park(goal, "turn_budget")
                return
            await self.refresh()
            await self._rt.roster.refresh()
            built = self._compose(goal, await self.tasks(goal_id))
            if built is None:
                return
            prompt, shown, reported = built
            told = len(self._told.get(goal_id, ()))
            from jarvis.agent_chat.service import SessionBusy

            from .chat_binding import agent_busy, ensure_session

            self._lead_goal[lead_id] = goal_id
            try:
                session = ensure_session(svc, self._rt.config(), lead)
                if svc.is_running(session.session_id) or agent_busy(svc, lead):
                    raise SessionBusy(session.session_id)
                self._turns[goal_id] = (session.session_id, "")
                turn_id = str(
                    await svc.send(
                        session.session_id,
                        prompt,
                        direct_user=False,
                        display_text=shown[:2000],
                        output_language=goal.lang,
                    )
                )
            except SessionBusy:
                if attempt >= MAX_LEAD_WAIT_ATTEMPTS:
                    await self._park(goal, "lead_busy")
                else:
                    self._wake_lead(goal_id, self._lead_retry, attempt + 1)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the person sees why and can resume
                log.warning("society team lead: turn for %s did not start", goal_id, exc_info=True)
                await self._park(goal, f"error:{str(exc)[:300] or type(exc).__name__}")
                return
            self._turns[goal_id] = (session.session_id, turn_id)
            fresh = await self.get_goal(goal_id)
            if fresh is None or fresh.state is not TeamGoalState.RUNNING:
                # Stopped or paused while the turn was starting: it must not run on.
                await self._cancel_turn(session.session_id, turn_id)
                return
            started = True
            # Only what this prompt carried is consumed; later words stay pending.
            rest = self._told.get(goal_id, [])[told:]
            if rest:
                self._told[goal_id] = rest
            else:
                self._told.pop(goal_id, None)
            self._resumed.discard(goal_id)
            await self._rt.store.update_team_goal(
                goal_id, {"lead_turns": goal.lead_turns + 1, "updated_ms": now_ms()}
            )
            for task_id in reported:
                await self._rt.store.update_team_task(task_id, {"reviewed": 1})
            await self._announce(goal.group_id, goal_id=goal_id, state=goal.state, reason="turn")
            self._spawn(self._watch_lead(goal_id, lead_id, session.session_id, turn_id))
        finally:
            if not started:
                self._release_turn(goal_id, lead_id)

    def _release_turn(self, goal_id: str, lead_id: str) -> None:
        self._turns.pop(goal_id, None)
        if lead_id and self._lead_goal.get(lead_id) == goal_id:
            self._lead_goal.pop(lead_id, None)

    async def _watch_lead(self, goal_id: str, lead_id: str, session_id: str, turn_id: str) -> None:
        """Wait for the managing turn to end, then decide what the goal needs."""
        svc = self._rt.chat_service()
        ok, final, error = False, "", ""
        try:
            try:
                await asyncio.wait_for(svc.wait_turn(session_id), timeout=LEAD_TURN_TIMEOUT_S)
            except TimeoutError:  # A turn this long is stopped; the person may resume.
                error = "The lead's turn took too long and was stopped."
                await self._cancel_turn(session_id, turn_id)
            else:
                terminal = None
                for _ in range(6):
                    terminal = await asyncio.to_thread(
                        svc.store.turn_terminal, session_id, turn_id
                    )
                    if terminal is not None:
                        break
                    await asyncio.sleep(0.5)
                payload = (terminal or {}).get("payload", {})
                ok = payload.get("status") in ("ok", "done", "completed")
                if not ok:
                    error = str(payload.get("error") or payload.get("status") or "")
                    error = error or "The lead's turn did not finish."
                events = await asyncio.to_thread(svc.store.list_events, session_id, tail=200)
                final = next(
                    (
                        str(e["payload"].get("text") or "")
                        for e in reversed(events)
                        if e["kind"] == "assistant_text" and e["payload"].get("turn_id") == turn_id
                    ),
                    "",
                )
        except asyncio.CancelledError:
            self._release_turn(goal_id, lead_id)
            raise
        except Exception as exc:  # noqa: BLE001 — an unreadable turn pauses the goal, visibly
            log.warning("society team lead: turn %s could not be read", turn_id, exc_info=True)
            ok, error = False, str(exc)[:300] or type(exc).__name__
        self._release_turn(goal_id, lead_id)
        await self._after_lead_turn(goal_id, ok=ok, final=final.strip(), error=error)

    async def _after_lead_turn(self, goal_id: str, *, ok: bool, final: str, error: str) -> None:
        goal = await self.get_goal(goal_id)
        if goal is None:
            return
        if goal.state in GOAL_TERMINAL:
            await self._advance(goal.group_id)
            return
        await self._announce(goal.group_id, goal_id=goal_id, state=goal.state, reason="turn")
        if goal.state is not TeamGoalState.RUNNING:
            return
        if goal_id in self._turns:
            return  # A newer turn owns the goal now; it decides what comes next.
        if self._told.get(goal_id) or goal_id in self._resumed:
            # The person spoke or resumed after this turn began (a turn the
            # kill switch stopped ends "cancelled"): their turn comes next.
            self._wake_lead(goal_id)
            return
        if not ok:
            await self._park(goal, f"error:{error}")
            return
        tasks = await self.tasks(goal_id)
        if any(t.state in TASK_FINISHED and not t.reviewed for t in tasks):
            self._wake_lead(goal_id)
            return
        if any(t.state in TASK_OPEN for t in tasks):
            return
        if goal_id not in self._nudged:
            # Nothing is running and nothing was reported. A plain answer may be
            # the result or a question; the lead says which, once, in a typed
            # report. Its answer stays visible on the board meanwhile.
            self._nudged.add(goal_id)
            if final:
                await self._rt.store.update_team_goal(goal_id, {"report": final})
            self._wake_lead(goal_id)
            return
        # Asked and still no report: the lead's answer is the result.
        await self._finish(goal, TeamGoalState.DONE, report=final or goal.report)

    # ----------------------------------------------------- the lead's tools

    async def _goal_for_lead(self, lead_id: str, *, create_title: str = "") -> TeamGoal:
        """The goal a lead's tool call belongs to; a lead working from its own
        chat with no goal open starts one."""
        group_id = self._leads.get(lead_id)
        if group_id is None:
            raise TeamLeadError("You do not lead a team.")
        goal_id = self._lead_goal.get(lead_id)
        goal = await self.get_goal(goal_id) if goal_id else None
        if goal is not None and goal.state is TeamGoalState.RUNNING:
            return goal
        if goal_id:
            # This is a managing turn whose goal was closed, stopped or handed to
            # the person meanwhile. It must not adopt or start another goal.
            raise TeamLeadError(
                "This goal is no longer in progress. End your turn; you are woken "
                "when there is something to do."
            )
        active = await self._active_goal(group_id)
        if active is not None:
            if active.state is not TeamGoalState.RUNNING:
                raise TeamLeadError(
                    f'The goal "{active.title}" is {active.state}; the person continues it '
                    "from the team board."
                )
            return active
        if not create_title:
            raise TeamLeadError("Your team has no goal in progress.")
        new_id = uuid7_str()
        stamp = now_ms()
        await self._rt.store.insert_team_goal(
            {
                "goal_id": new_id,
                "group_id": group_id,
                "lead_agent_id": lead_id,
                "title": goal_title(create_title),
                "text": create_title,
                "state": str(TeamGoalState.RUNNING),
                "lead_turns": 1,
                "origin_json": json.dumps({"kind": "lead"}),
                "created_ms": stamp,
                "updated_ms": stamp,
            }
        )
        await self._announce(group_id, goal_id=new_id, state=TeamGoalState.RUNNING)
        created = await self.get_goal(new_id)
        assert created is not None
        return created

    def _resolve_member(self, group: Mapping[str, Any], lead_id: str, wanted: str) -> AgentRecord:
        by_id = {a.agent_id: a for a in self._rt.roster.snapshot()}
        members = [
            by_id[m]
            for m in group.get("members", [])
            if m in by_id and m not in (lead_id, LEAD_AGENT_ID)
        ]
        key = wanted.strip()
        fold = key.casefold()
        for agent in members:
            if key == agent.agent_id or fold == agent.name.casefold():
                return agent
        slug = slugify(key)
        for agent in members:
            if slug in (agent.agent_id, slugify(agent.name)):
                return agent
        names = ", ".join(a.name for a in members) or "nobody yet"
        raise TeamLeadError(f"{key!r} is not a member of your team. Members: {names}.")

    async def assign(
        self, lead_id: str, *, member: str, title: str, brief: str, goal_title_hint: str = ""
    ) -> dict[str, Any]:
        """A lead hands one task to a member: a task row and its ``ASSIGN``."""
        if await self._rt.store.kill_switch():
            raise TeamLeadError("The society is paused.")
        if not title.strip() or not brief.strip():
            raise TeamLeadError("A task needs a title and a brief.")
        await self.refresh()
        group_id = self._leads.get(lead_id)
        if group_id is None:
            raise TeamLeadError("You do not lead a team.")
        await self._rt.roster.refresh()
        group = self._groups[group_id]
        target = self._resolve_member(group, lead_id, member)
        if target.state is not AgentState.ACTIVE:
            raise TeamLeadError(f"{target.name} is {target.state} and cannot take work.")
        goal = await self._goal_for_lead(lead_id, create_title=goal_title_hint or title)
        tasks = await self.tasks(goal.goal_id)
        if len(tasks) >= MAX_TASKS_PER_GOAL:
            raise TeamLeadError("This goal reached its task limit; report to the person.")
        task_id = uuid7_str()
        stamp = now_ms()
        env = self._assign_envelope(goal, lead_id, target.agent_id, task_id, title, brief)
        await self._rt.store.insert_team_task(
            {
                "task_id": task_id,
                "goal_id": goal.goal_id,
                "agent_id": target.agent_id,
                "title": " ".join(title.split())[:160],
                "brief": brief.strip(),
                "state": str(TeamTaskState.ASSIGNED),
                "trace_id": env.trace_id,
                "assign_event_id": env.event_id,
                "created_ms": stamp,
                "updated_ms": stamp,
            }
        )
        await self._rt.store.append_and_publish(env)
        row = await self._rt.store.get_team_task_row(task_id)
        task = TeamTask.from_row(row or {"task_id": task_id, "goal_id": goal.goal_id,
                                         "agent_id": target.agent_id, "trace_id": env.trace_id})
        await self._announce(group_id, goal_id=goal.goal_id, state=goal.state, reason="task")
        return {
            "task_id": task_id,
            "goal_id": goal.goal_id,
            "member": target.name,
            "state": str(task.state),
            "note": {
                TeamTaskState.RUNNING: f"{target.name} started.",
                TeamTaskState.WAITING: f"{target.name} is busy; the task starts by itself "
                "when they are free.",
                TeamTaskState.BLOCKED: task.result or "The task could not start.",
            }.get(task.state, "Recorded; the start is not confirmed yet."),
        }

    def _assign_envelope(
        self,
        goal: TeamGoal,
        lead_id: str,
        member_id: str,
        task_id: str,
        title: str,
        brief: str,
        attempt: int = 0,
    ) -> SocietyEnvelope:
        # Every knock gets its own trace: the scheduler caps the messages of
        # one trace, and a long wait on a busy member must not hit that cap.
        trace = f"{TRACE_PREFIX}{goal.goal_id}:{task_id}"
        if attempt:
            trace += f":{attempt}"
        text = f"{' '.join(title.split())}\n\n{brief.strip()}"
        payload: dict[str, Any] = {
            "text": text,
            "title": title,
            "reply_policy": "always",
            "team_goal_id": goal.goal_id,
            "team_task_id": task_id,
        }
        if goal.lang:
            payload["lang"] = goal.lang
        return SocietyEnvelope(
            msg_type=MsgType.ASSIGN,
            from_agent=lead_id,
            to_agent=member_id,
            trace_id=trace,
            payload=payload,
        )

    async def board(self, lead_id: str) -> dict[str, Any]:
        """What a lead sees of its team: mission, members and its goals."""
        await self.refresh()
        group_id = self._leads.get(lead_id)
        if group_id is None:
            raise TeamLeadError("You do not lead a team.")
        group = self._groups[group_id]
        await self._rt.roster.refresh()
        goals = [g for g in await self.goals(group_id, limit=30) if g.state not in GOAL_TERMINAL]
        rows = []
        for goal in sorted(goals, key=lambda g: g.created_ms):
            tasks = await self.tasks(goal.goal_id)
            rows.append(
                {
                    "goal_id": goal.goal_id,
                    "title": goal.title,
                    "goal": goal.text[:2000],
                    "state": str(goal.state),
                    "tasks": [
                        {
                            "member": self._name(t.agent_id),
                            "title": t.title,
                            "state": str(t.state),
                            "result": t.result[:RESULT_CHARS],
                        }
                        for t in tasks
                    ],
                }
            )
        return {
            "team": group.get("name"),
            "mission": group.get("mission") or "",
            "members": self._roster_lines(group, lead_id),
            "goals": rows,
        }

    async def report(self, lead_id: str, *, status: str, summary: str) -> dict[str, Any]:
        """A lead reports on its goal: progress, a question, the result or a failure."""
        text = summary.strip()
        if not text:
            raise TeamLeadError("A report needs a summary.")
        goal = await self._goal_for_lead(lead_id)
        if status == "progress":
            await self._rt.store.update_team_goal(
                goal.goal_id, {"report": text, "updated_ms": now_ms()}
            )
            await self._announce(goal.group_id, goal_id=goal.goal_id, state=goal.state)
        elif status == "needs_input":
            if not await self._move(
                goal,
                TeamGoalState.NEEDS_INPUT,
                (TeamGoalState.RUNNING,),
                report=text,
                note="question",
            ):
                raise TeamLeadError("This goal is no longer in progress.")
        elif status in ("done", "failed"):
            closed = (
                await self._finish(goal, TeamGoalState.DONE, report=text)
                if status == "done"
                else await self._finish(
                    goal, TeamGoalState.FAILED, report=text, note="reported_failed"
                )
            )
            if not closed:
                raise TeamLeadError("This goal is no longer in progress.")
        else:
            raise TeamLeadError("status must be progress, needs_input, done or failed")
        return {"goal_id": goal.goal_id, "title": goal.title, "recorded": status}

    # --------------------------------------------------------- the board

    async def _on_envelope(self, env: SocietyEnvelope) -> None:
        if not env.trace_id.startswith(TRACE_PREFIX):
            run_id = str(env.payload.get("run_id") or "")
            if env.msg_type is MsgType.CLAIM and run_id.startswith(GOAL_RUN_PREFIX):
                # A goal is not a run: it may queue, wait for the person or pause
                # for days. Holding one of the lead's run slots that long would
                # refuse every later assignment; the team's own queue bounds it.
                self._rt.scheduler.note_run_ended(run_id)
            return
        if env.msg_type not in (MsgType.CLAIM, MsgType.RESULT, MsgType.VETO):
            return
        row = await self._rt.store.get_team_task_row_by_trace(env.trace_id)
        if row is None:
            return
        task = TeamTask.from_row(row)
        if task.state not in TASK_OPEN or env.parent_event_id != task.assign_event_id:
            return
        stamp = now_ms()
        if env.msg_type is MsgType.CLAIM:
            await self._rt.store.update_team_task(
                task.task_id,
                {
                    "state": str(TeamTaskState.RUNNING),
                    "run_id": str(env.payload.get("run_id") or ""),
                    "updated_ms": stamp,
                },
            )
            await self._task_changed(task, news=False)
            return
        if env.msg_type is MsgType.RESULT:
            if env.from_agent != task.agent_id:
                return
            blocked = str(env.payload.get("status") or "done") == "blocked"
            result = str(env.payload.get("done") or env.text or "").strip()
            await self._close_task(
                task, TeamTaskState.BLOCKED if blocked else TeamTaskState.DONE, result
            )
            return
        reason = str(env.payload.get("reason") or "")
        if reason in WAIT_REASONS and task.attempts < MAX_WAIT_ATTEMPTS:
            # Not now, not never: the task waits and knocks again by itself.
            await self._rt.store.update_team_task(
                task.task_id,
                {
                    "state": str(TeamTaskState.WAITING),
                    "attempts": task.attempts + 1,
                    "updated_ms": stamp,
                },
            )
            self._arm(
                f"task:{task.task_id}", self._retry_delay, lambda: self._reassign(task.task_id)
            )
            await self._task_changed(task, news=False)
            return
        await self._close_task(
            task, TeamTaskState.BLOCKED, f"Could not start: {env.text or reason or 'refused'}"
        )

    async def _close_task(self, task: TeamTask, state: TeamTaskState, result: str) -> None:
        stamp = now_ms()
        self._disarm(f"task:{task.task_id}")
        await self._rt.store.update_team_task(
            task.task_id,
            {
                "state": str(state),
                "result": result[:20_000],
                "reviewed": 0,
                "updated_ms": stamp,
                "done_ms": stamp,
            },
        )
        await self._task_changed(task, news=True)

    async def _task_changed(self, task: TeamTask, *, news: bool) -> None:
        goal = await self.get_goal(task.goal_id)
        if goal is None:
            return
        await self._announce(goal.group_id, goal_id=goal.goal_id, state=goal.state, reason="task")
        if not news or goal.state is not TeamGoalState.RUNNING:
            return
        self._wake_lead(goal.goal_id, self._review_delay)

    async def _reassign(self, task_id: str) -> None:
        """A waiting task knocks again: a fresh ``ASSIGN`` on a fresh trace."""
        row = await self._rt.store.get_team_task_row(task_id)
        if row is None:
            return
        task = TeamTask.from_row(row)
        goal = await self.get_goal(task.goal_id)
        if task.state is not TeamTaskState.WAITING or goal is None:
            return
        if goal.state in GOAL_TERMINAL:
            return
        if await self._rt.store.kill_switch():
            return
        env = self._assign_envelope(
            goal,
            goal.lead_agent_id,
            task.agent_id,
            task_id,
            task.title,
            task.brief,
            attempt=task.attempts,
        )
        await self._rt.store.update_team_task(
            task_id,
            {
                "state": str(TeamTaskState.ASSIGNED),
                "trace_id": env.trace_id,
                "assign_event_id": env.event_id,
                "updated_ms": now_ms(),
            },
        )
        await self._rt.store.append_and_publish(env)

    # ----------------------------------------------------- recovery, sweep

    async def _recover(self) -> None:
        """Goals that were running when the app closed come back paused: their
        turns died with the process, and nothing resumes paid work on boot."""
        for row in await self._rt.store.list_team_goal_rows(limit=1000):
            goal = TeamGoal.from_row(row)
            if goal.state is not TeamGoalState.RUNNING:
                continue
            for task in await self.tasks(goal.goal_id):
                if task.state in TASK_OPEN:
                    stamp = now_ms()
                    await self._rt.store.update_team_task(
                        task.task_id,
                        {
                            "state": str(TeamTaskState.BLOCKED),
                            "result": "Interrupted when the app closed.",
                            "reviewed": 0,
                            "updated_ms": stamp,
                            "done_ms": stamp,
                        },
                    )
            await self._rt.store.update_team_goal(
                goal.goal_id,
                {"state": str(TeamGoalState.PAUSED), "note": "interrupted", "updated_ms": now_ms()},
            )

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_s)
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — one failed pass; the next one runs in a minute
                log.warning("society team lead: sweep failed", exc_info=True)

    async def sweep(self) -> None:
        """Find work that died without a word (AP-19: judged per task, by its
        own last sign of life) so the lead hears about it instead of waiting."""
        stamp = now_ms()
        running = self._rt.scheduler.running
        for row in await self._rt.store.list_team_goal_rows(limit=1000):
            goal = TeamGoal.from_row(row)
            if goal.state is not TeamGoalState.RUNNING:
                continue
            tasks = await self.tasks(goal.goal_id)
            for task in tasks:
                if task.state not in TASK_OPEN or stamp - task.updated_ms < STALL_MS:
                    continue
                if task.state is TeamTaskState.WAITING:
                    if f"task:{task.task_id}" not in self._timers:
                        self._arm(
                            f"task:{task.task_id}", 0.0, partial(self._reassign, task.task_id)
                        )
                    continue
                if task.state is TeamTaskState.RUNNING and task.run_id in running:
                    continue
                await self._close_task(
                    task,
                    TeamTaskState.BLOCKED,
                    "The run ended without a result."
                    if task.state is TeamTaskState.RUNNING
                    else "The assignment was never picked up.",
                )
            idle = goal.goal_id not in self._turns and f"lead:{goal.goal_id}" not in self._timers
            if not idle or stamp - goal.updated_ms < STALL_MS:
                continue
            fresh = await self.tasks(goal.goal_id)
            if any(t.state in TASK_OPEN for t in fresh):
                continue
            if any(t.state in TASK_FINISHED and not t.reviewed for t in fresh):
                self._wake_lead(goal.goal_id)
            else:
                await self._park(goal, "stalled")

    # ------------------------------------------------------------ pushes

    async def _announce(
        self,
        group_id: str,
        *,
        goal_id: str = "",
        state: TeamGoalState | str = "",
        reason: str = "goal",
    ) -> None:
        """``SocietyTeamChanged`` on the app bus; the team board re-reads at once."""
        try:
            from jarvis.core.events import SocietyTeamChanged

            event = SocietyTeamChanged(
                source_layer="society",
                group_id=group_id,
                goal_id=goal_id,
                state=str(state),
                reason=reason,
            )
            if self._publish is not None:
                maybe = self._publish(event)
            else:
                from jarvis.core.bus import get_default_bus

                maybe = get_default_bus().publish(event)
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception:  # noqa: BLE001 — a window that misses the push falls back to its poll
            log.debug("society team lead: change not pushed", exc_info=True)

    # --------------------------------------------------------- briefings

    def briefing(self, agent_id: str) -> str:
        """The standing part of an agent's prompt about its team. Byte-stable
        between team edits (no goal or run state), so the prompt cache holds."""
        parts: list[str] = []
        by_id = {a.agent_id: a for a in self._rt.roster.snapshot()}
        group_id = self._leads.get(agent_id)
        if group_id is not None:
            group = self._groups.get(group_id) or {}
            lines = [f'## You lead the team "{group.get("name") or group_id}"']
            members = []
            for member_id in group.get("members", []):
                mate = by_id.get(member_id)
                if mate is None or member_id in (agent_id, LEAD_AGENT_ID):
                    continue
                members.append(mate.name + (f" — {mate.title}" if mate.title.strip() else ""))
            lines.append("Members you manage: " + ("; ".join(members) or "nobody yet") + ".")
            if str(group.get("mission") or "").strip():
                lines.append("Team mission: " + str(group["mission"]).strip())
            lines.append(_LEAD_RULES)
            parts.append("\n".join(lines))
        for group in self._groups.values():
            lead_id = group.get("lead_agent_id")
            if not lead_id or lead_id == agent_id or agent_id not in group.get("members", []):
                continue
            lead = by_id.get(str(lead_id))
            if lead is None:
                continue
            parts.append(
                f'## Your team\nYou are a member of the team "{group["name"]}", led by '
                f"{lead.name}. Tasks from {lead.name} are your team's work: report the "
                "actual outcome and evidence in your final answer, and put a blocker or an "
                f"open question there too, so {lead.name} can act on it."
            )
        return "\n\n".join(parts)
