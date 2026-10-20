"""The coordinator of a team thread.

A deterministic policy over thread sessions: it decides whose turn runs and
what that peer reads, and it decides when a step is over. Models fill in the
contributions and nothing else, so a team thread is never an open model loop:

    draft      every member plans alone, without seeing the others
    challenge  every member reads the other plans and challenges them
    converge   one member writes the master plan, the others agree or object
    build      the plan's author implements it
    review     the others review; findings go back to the builder until all approve

That is the ``peers`` mode. The ``planner_builder`` mode gives each member a
role instead: one owns a living plan, one builds it a step at a time, the
others review the plan and every step (``plan_mode.PlannedWork``).

Every step is derived from the entries already in the thread, so a paused or
interrupted thread continues where it stopped. Nothing resumes by itself: a
thread that was running when the app closed comes back paused.

Rounds, turns, time and cost are bounded. When a bound is reached or the
members cannot agree, the thread stops with a typed reason and the open
points, and waits for the person.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from . import prompts
from .plan_mode import PlannedWork, default_roles, plan_issues
from .port import TurnPort, TurnResult
from .signals import parse_review, parse_vote
from .store import MODES, ROLES, TeamThreadStore
from .workspace import GitWorkspace

log = logging.getLogger(__name__)

__all__ = ["MAX_MEMBERS", "MIN_MEMBERS", "Limits", "SeatPick", "TeamError", "TeamThreads"]

MIN_MEMBERS: Final[int] = 2
#: A swarm: more members than this cost more than another review catches.
MAX_MEMBERS: Final[int] = 8
#: Model turns each member brings to a team's default turn bound.
_TURNS_PER_MEMBER: Final[int] = 10
_MAX_TASK: Final[int] = 40_000
_MAX_TEXT: Final[int] = 60_000

#: What a member's own thread shows for each coordinator message.
_STEP_LABEL: Final[dict[str, str]] = {
    "draft": "Team thread: your own plan",
    "critique": "Team thread: challenge the other plans",
    "plan": "Team thread: write the master plan",
    "vote": "Team thread: agree or object",
    "build": "Team thread: build the plan",
    "review": "Team thread: review the change",
    "fix": "Team thread: answer the review",
    "plan_version": "Team thread: write the plan",
    "plan_review": "Team thread: review the plan",
    "step_build": "Team thread: build a step",
    "step_review": "Team thread: review a step",
}

#: needs_input reasons a message from the person settles with one more round.
_DISAGREEMENTS: Final[tuple[str, ...]] = (
    "plan_disagreement",
    "review_disagreement",
    "step_disagreement",
)


class TeamError(ValueError):
    """A request the thread's current state does not allow."""


class _Halt(Exception):
    """The run stopped itself; the state is already written."""


@dataclass(frozen=True, slots=True)
class SeatPick:
    """One member: the coding agent or provider and the model it runs."""

    provider: str
    model: str = ""
    effort: str = ""
    name: str = ""
    family: str = ""
    #: The model's short display name, where the person picked the model;
    #: it follows the seat's name ("Anthropic Claude · Opus 5.5").
    model_label: str = ""
    #: A model the account lists. Tried once when the seat's own default is
    #: refused on the member's first turn, so a CLI configured for a model the
    #: signed-in account may not use does not cost the team a member.
    fallback_model: str = ""


@dataclass(frozen=True, slots=True)
class Limits:
    #: Working time of the whole thread; paused time does not count.
    max_minutes: int = 90
    #: Model turns of the whole thread.
    max_turns: int = 40
    #: Master plans written before the thread asks the person.
    plan_rounds: int = 3
    #: Review rounds before the thread asks the person.
    review_rounds: int = 3
    #: One turn's own time; a turn over it counts as stalled.
    turn_minutes: int = 30
    #: 0 = no cap. Counted only where the runner reports a price.
    max_cost_usd: float = 0.0

    @classmethod
    def for_team(cls, members: int) -> Limits:
        """The default bounds of a team this size: a bigger team takes more turns per step."""
        return cls(max_turns=max(cls().max_turns, _TURNS_PER_MEMBER * members))

    @classmethod
    def of(cls, raw: dict[str, Any] | None, *, members: int = 0) -> Limits:
        base = cls.for_team(members)
        raw = raw or {}

        def whole(key: str, low: int, high: int) -> int:
            try:
                return max(low, min(high, int(raw.get(key, getattr(base, key)))))
            except (TypeError, ValueError):  # not a number: the default bound applies
                return int(getattr(base, key))

        try:
            cost = max(0.0, float(raw.get("max_cost_usd", base.max_cost_usd)))
        except (TypeError, ValueError):  # not a number: the default cap applies
            cost = base.max_cost_usd
        return cls(
            max_minutes=whole("max_minutes", 5, 24 * 60),
            max_turns=whole("max_turns", 6, 400),
            plan_rounds=whole("plan_rounds", 1, 10),
            review_rounds=whole("review_rounds", 1, 10),
            turn_minutes=whole("turn_minutes", 2, 180),
            max_cost_usd=cost,
        )


class TeamThreads(PlannedWork):
    def __init__(
        self,
        store: TeamThreadStore,
        port: TurnPort,
        *,
        workspace: GitWorkspace | None = None,
        language: Callable[[str], str] | None = None,
    ) -> None:
        self._store = store
        self._port = port
        self._workspace = workspace or GitWorkspace()
        self._language = language or (lambda _task: "")
        self._tasks: dict[str, asyncio.Task[None]] = {}
        #: team -> member -> when its running turn started (ms).
        self._working: dict[str, dict[str, int]] = {}
        #: team -> monotonic start of the run segment whose time is not banked yet.
        self._segment: dict[str, float] = {}
        self._closing = False
        # Paid work never restarts by itself (the person started it once, in
        # another process); it waits for Resume.
        store.interrupt_running(note="The app closed while the team was working.")

    # ------------------------------------------------------------ commands

    async def start(
        self,
        *,
        task: str,
        cwd: str,
        seats: list[SeatPick],
        limits: dict[str, Any] | None = None,
        title: str = "",
        mode: str = "peers",
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        task = (task or "").strip()
        if not task:
            raise TeamError("A team thread needs a task.")
        if len(task) > _MAX_TASK:
            raise TeamError("The task is too long for a team thread.")
        if not MIN_MEMBERS <= len(seats) <= MAX_MEMBERS:
            raise TeamError(f"A team thread has {MIN_MEMBERS} to {MAX_MEMBERS} members.")
        if mode not in MODES:
            raise TeamError(f"Unknown team mode: {mode}")
        picked = _roles_of(mode, roles, len(seats))
        if self._closing:
            raise TeamError("Team threads are shutting down.")
        folder = Path(cwd or "")
        if not cwd or not await asyncio.to_thread(folder.is_dir):
            raise TeamError("The project folder does not exist.")
        title = (title or "").strip() or _title_from(task)
        names = _unique_names(seats)
        members: list[dict[str, Any]] = []
        try:
            for index, (seat, name) in enumerate(zip(seats, names, strict=True)):
                session_id = self._port.open(
                    provider=seat.provider,
                    model=seat.model,
                    effort=seat.effort,
                    cwd=str(folder),
                    title=f"{title} · {name}",
                )
                members.append(
                    {
                        "member_id": f"m{index + 1}",
                        "session_id": session_id,
                        "provider": seat.provider,
                        "model": seat.model,
                        "fallback_model": seat.fallback_model,
                        "effort": seat.effort,
                        "name": name,
                        "family": seat.family,
                    }
                )
        except Exception as exc:
            for member in members:
                self._discard(member["session_id"])
            raise TeamError(f"A member could not be seated: {exc}") from exc
        work: dict[str, Any] = {}
        if picked:
            work = {
                "roles": {m["member_id"]: role for m, role in zip(members, picked, strict=True)},
                "builder": members[picked.index("builder")]["member_id"],
                "plan_round": 1,
                "plan_base": 1,
            }
        try:
            team_id = self._store.create(
                title=title,
                task=task,
                cwd=str(folder),
                lang=self._language(task),
                limits=asdict(Limits.of(limits, members=len(seats))),
                members=members,
                mode=mode,
                work=work,
            )
        except Exception:
            for member in members:
                self._discard(member["session_id"])
            raise
        first = "planning" if picked else "draft"
        self._store.append(team_id, kind="user", author="user", phase=first, payload={"text": task})
        families = {seat.family or seat.provider for seat in seats}
        if len(families) == 1:
            # Honest about what a one-family team cannot give (AP-22).
            self._notice(team_id, first, "same_family")
        self._spawn(team_id)
        return await asyncio.to_thread(self.snapshot, team_id)

    async def message(self, team_id: str, text: str) -> dict[str, Any]:
        """The person steps in. Every member reads it with its next turn."""
        team = self._require(team_id)
        text = (text or "").strip()
        if not text:
            raise TeamError("The message is empty.")
        if team["state"] in ("done", "stopped", "failed"):
            raise TeamError("This team thread is over. Start a new one.")
        self._store.append(
            team_id,
            kind="user",
            author="user",
            phase=team["phase"],
            payload={"text": text[:_MAX_TASK]},
        )
        if team["state"] == "needs_input" and team["reason"] in _DISAGREEMENTS:
            # The answer settles the open points: one more round with it.
            return await self.resume(team_id)
        return await asyncio.to_thread(self.snapshot, team_id)

    async def pause(self, team_id: str) -> dict[str, Any]:
        team = self._require(team_id)
        if team["state"] != "running":
            raise TeamError("Only a working team thread can be paused.")
        self._store.update(team_id, state="paused", reason="user", note="")
        await self._cancel_run(team_id)
        self._notice(team_id, team["phase"], "paused")
        return await asyncio.to_thread(self.snapshot, team_id)

    async def stop(self, team_id: str) -> dict[str, Any]:
        team = self._require(team_id)
        if team["state"] not in ("running", "paused", "needs_input"):
            raise TeamError("This team thread is already over.")
        self._store.update(team_id, state="stopped", reason="user", note="")
        await self._cancel_run(team_id)
        self._notice(team_id, team["phase"], "stopped")
        return await asyncio.to_thread(self.snapshot, team_id)

    async def resume(self, team_id: str) -> dict[str, Any]:
        """Continue a paused or waiting thread; a reached bound grows by half."""
        team = self._require(team_id)
        if team["state"] not in ("paused", "needs_input"):
            raise TeamError("Only a paused or waiting team thread can continue.")
        if self._closing:
            raise TeamError("Team threads are shutting down.")
        limits = dict(team["limits"])
        work = dict(team["work"])
        reason = team["reason"] if team["state"] == "needs_input" else ""
        if reason == "plan_disagreement":
            limits["plan_rounds"] = int(limits["plan_rounds"]) + 1
            work["plan_round"] = int(work.get("plan_round", 1)) + 1
        elif reason in ("review_disagreement", "step_disagreement"):
            limits["review_rounds"] = int(limits["review_rounds"]) + 1
        elif reason == "plan_unreadable":
            # The planner gets its two tries again, from here.
            work["plan_retry_from"] = self._store.entries(team_id)[-1]["seq"]
        elif reason == "limit_time":
            limits["max_minutes"] = int(limits["max_minutes"]) + max(
                30, int(limits["max_minutes"]) // 2
            )
        elif reason == "limit_turns":
            limits["max_turns"] = int(limits["max_turns"]) + max(10, int(limits["max_turns"]) // 2)
        elif reason == "limit_cost":
            limits["max_cost_usd"] = float(limits["max_cost_usd"]) * 1.5 + 1.0
        if len(self._active(team_id)) < MIN_MEMBERS:
            raise TeamError("Fewer than two members are left; start a new team thread.")
        self._store.update(team_id, state="running", reason="", note="", limits=limits, work=work)
        self._notice(team_id, team["phase"], "resumed", {"after": reason or team["reason"]})
        self._spawn(team_id)
        return await asyncio.to_thread(self.snapshot, team_id)

    async def accept(self, team_id: str) -> dict[str, Any]:
        """The person ends a disagreement: take the plan, or the work, as it is."""
        team = self._require(team_id)
        if team["state"] != "needs_input" or team["reason"] not in _DISAGREEMENTS:
            raise TeamError("There is no disagreement to settle.")
        if self._closing:
            raise TeamError("Team threads are shutting down.")
        if team["mode"] == "planner_builder":
            self._accept_planned(team)
            if self._store.get(team_id)["state"] == "running":  # type: ignore[index]
                self._spawn(team_id)
        elif team["reason"] == "plan_disagreement":
            round_no = int(team["work"].get("plan_round", 1))
            plan = self._last(team_id, "plan", round_no)
            if plan is None:
                raise TeamError("There is no master plan to accept yet.")
            self._adopt(team_id, plan, by_user=True)
            self._store.update(team_id, state="running", reason="", note="")
            self._spawn(team_id)
        else:
            self._finish(team_id, accepted_open=True)
        return await asyncio.to_thread(self.snapshot, team_id)

    async def delete(self, team_id: str) -> None:
        team = self._require(team_id)
        if team["state"] == "running":
            raise TeamError("Stop the team thread before deleting it.")
        for member in self._store.members(team_id):
            self._discard(member["session_id"])
        self._store.delete(team_id)

    async def close(self) -> None:
        """App shutdown: stop coordinating. The threads come back paused."""
        self._closing = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=25)

    async def settled(self, team_id: str) -> None:
        """Return once the coordinator has nothing running for this thread."""
        task = self._tasks.get(team_id)
        if task is not None:
            await asyncio.wait({task})

    # ------------------------------------------------------------ reads

    def threads(self) -> list[dict[str, Any]]:
        rows = []
        for team in self._store.list():
            members = self._store.members(team["team_id"])
            rows.append(
                {
                    "team_id": team["team_id"],
                    "title": team["title"],
                    "cwd": team["cwd"],
                    "mode": team["mode"],
                    "state": team["state"],
                    "phase": team["phase"],
                    "reason": team["reason"],
                    "created_ms": team["created_ms"],
                    "updated_ms": team["updated_ms"],
                    "members": [
                        {
                            "member_id": m["member_id"],
                            "name": m["name"],
                            "provider": m["provider"],
                            "family": m["family"],
                            "state": m["state"],
                        }
                        for m in members
                    ],
                }
            )
        return rows

    def session_teams(self) -> dict[str, str]:
        return self._store.session_teams()

    def snapshot(self, team_id: str, *, after: int = 0) -> dict[str, Any]:
        team = self._require(team_id)
        work = team["work"]
        working = self._working.get(team_id, {})
        planned = team["mode"] == "planner_builder"
        roles = dict(work.get("roles") or {})
        members = []
        for member in self._store.members(team_id):
            busy = member["member_id"] in working
            members.append(
                {
                    **{
                        k: member[k]
                        for k in (
                            "member_id",
                            "name",
                            "provider",
                            "model",
                            "effort",
                            "family",
                            "session_id",
                            "state",
                            "left_reason",
                        )
                    },
                    "working": busy,
                    "since_ms": working.get(member["member_id"], 0),
                    "waiting": busy and self._waiting(member["session_id"]),
                    # "" in the peers mode, where nobody holds a role.
                    "role": roles.get(member["member_id"], ""),
                }
            )
        all_entries = self._store.entries(team_id)
        done = team["state"] == "done" and not work.get("accepted_open")
        if planned:
            done = team["state"] == "done" and not work.get("accepted_open_all")
        return {
            "team_id": team_id,
            "title": team["title"],
            "task": team["task"],
            "cwd": team["cwd"],
            "mode": team["mode"],
            "state": team["state"],
            "phase": team["phase"],
            "reason": team["reason"],
            "note": team["note"],
            "limits": team["limits"],
            "usage": {
                "elapsed_ms": self._elapsed_ms(team),
                "turns": int(work.get("turns", 0)),
                "cost_usd": float(work.get("cost_usd", 0.0)),
                # Some turns ran on a seat that reports no price.
                "cost_partial": bool(work.get("cost_partial", False)),
            },
            "rounds": self._planned_rounds(team)
            if planned
            else {
                "plan": int(work.get("plan_round", 0)),
                "review": int(work.get("review_round", 0)),
            },
            "builder": work.get("builder", ""),
            "members": members,
            # The living plan of the planner-and-builder mode; None for peers.
            "plan": self._plan_view(team, all_entries) if planned else None,
            "entries": [e for e in all_entries if e["seq"] > after],
            "issues": plan_issues(all_entries, done=done)
            if planned
            else _issues(all_entries, done=done),
            "created_ms": team["created_ms"],
            "updated_ms": team["updated_ms"],
        }

    # ------------------------------------------------------------ the run

    def _spawn(self, team_id: str) -> None:
        running = self._tasks.get(team_id)
        if running is not None and not running.done():
            return
        task = asyncio.create_task(self._run(team_id))
        self._tasks[team_id] = task
        task.add_done_callback(lambda done: self._ended(team_id, done))

    def _ended(self, team_id: str, task: asyncio.Task[None]) -> None:
        """The run task is gone, however it went (even cancelled before its first step)."""
        if self._tasks.get(team_id) is task:
            self._tasks.pop(team_id, None)
        if self._closing or team_id in self._tasks:
            return
        team = self._store.get(team_id)
        if team is not None and team["state"] == "running":
            # Neither Pause, Stop nor shutdown ended this run. Never leave a
            # thread "working" with nobody working: it waits for Continue.
            log.warning("team thread %s: its run ended without a state", team_id)
            self._store.update(team_id, state="paused", reason="interrupted", note="")

    async def _cancel_run(self, team_id: str) -> None:
        task = self._tasks.get(team_id)
        if task is None:
            return
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=30)
        if not done:
            log.warning("team thread %s is still stopping its turns", team_id)

    async def _run(self, team_id: str) -> None:
        self._segment[team_id] = time.monotonic()
        try:
            while True:
                team = self._store.get(team_id)
                if team is None or team["state"] != "running":
                    return
                self._check_bounds(team)
                await getattr(self, f"_phase_{team['phase']}")(team)
        except _Halt:  # the run stopped itself and already filed why
            return
        except asyncio.CancelledError:
            raise  # Pause, Stop or shutdown; anything else is parked by ``_ended``
        except Exception as exc:  # noqa: BLE001 - one broken thread must not take others down
            log.exception("team thread %s failed", team_id)
            self._store.update(team_id, state="failed", reason="error", note=str(exc)[:500])
        finally:
            self._bank_time(team_id)
            self._working.pop(team_id, None)

    def _bank_time(self, team_id: str) -> None:
        started = self._segment.pop(team_id, None)
        team = self._store.get(team_id)
        if started is None or team is None:
            return
        work = dict(team["work"])
        work["active_ms"] = int(work.get("active_ms", 0)) + int((time.monotonic() - started) * 1000)
        self._store.update(team_id, work=work)

    def _elapsed_ms(self, team: dict[str, Any]) -> int:
        banked = int(team["work"].get("active_ms", 0))
        started = self._segment.get(team["team_id"])
        return banked + (int((time.monotonic() - started) * 1000) if started is not None else 0)

    def _check_bounds(self, team: dict[str, Any]) -> None:
        limits = team["limits"]
        if self._elapsed_ms(team) >= int(limits["max_minutes"]) * 60_000:
            self._halt(team, "needs_input", "limit_time")
        cap = float(limits.get("max_cost_usd") or 0.0)
        if cap > 0 and float(team["work"].get("cost_usd", 0.0)) >= cap:
            self._halt(team, "needs_input", "limit_cost")

    def _halt(
        self,
        team: dict[str, Any],
        state: str,
        reason: str,
        *,
        note: str = "",
        summary: dict[str, Any] | None = None,
    ) -> None:
        team_id = team["team_id"]
        if summary is not None:
            self._store.append(
                team_id,
                kind="summary",
                author="team",
                phase=team["phase"],
                payload={"outcome": reason, **summary},
            )
        else:
            self._notice(team_id, team["phase"], reason, {"note": note} if note else None)
        self._store.update(team_id, state=state, reason=reason, note=note)
        raise _Halt

    # ------------------------------------------------------------ phases

    async def _phase_draft(self, team: dict[str, Any]) -> None:
        team_id = team["team_id"]
        done = self._authors(team_id, "draft")
        todo = [m for m in self._active(team_id) if m["member_id"] not in done]
        roster = self._roster(team_id)
        await self._batch(
            team,
            todo,
            kind="draft",
            prompt=lambda m, notes: prompts.draft(
                name=m["name"], roster=roster, cwd=team["cwd"], task=team["task"], notes=notes
            ),
            guard=True,
        )
        self._advance(team_id, "challenge")

    async def _phase_challenge(self, team: dict[str, Any]) -> None:
        team_id = team["team_id"]
        done = self._authors(team_id, "critique")
        active = self._active(team_id)
        todo = [m for m in active if m["member_id"] not in done]
        roster = self._roster(team_id)
        drafts = self._texts(team_id, "draft")

        def prompt(member: dict[str, Any], notes: list[str]) -> str:
            others = {
                other["name"]: drafts.get(other["member_id"], "")
                for other in active
                if other["member_id"] != member["member_id"]
            }
            return prompts.challenge(
                name=member["name"], roster=roster, cwd=team["cwd"], drafts=others, notes=notes
            )

        await self._batch(team, todo, kind="critique", prompt=prompt, guard=True)
        work = self._work(team_id)
        work["plan_round"] = 1
        self._store.update(team_id, work=work)
        self._advance(team_id, "converge")

    async def _phase_converge(self, team: dict[str, Any]) -> None:
        team_id = team["team_id"]
        round_no = int(team["work"].get("plan_round", 1))
        active = self._active(team_id)
        ids = {m["member_id"] for m in active}
        roster = self._roster(team_id)
        plan = self._last(team_id, "plan", round_no)
        if plan is None or plan["author"] not in ids:
            # A new author each round, so no single member owns the plan.
            author = active[(round_no - 1) % len(active)]
            names = {m["member_id"]: m["name"] for m in self._store.members(team_id)}
            previous = self._last(team_id, "plan", round_no - 1) if round_no > 1 else None
            objections: dict[str, list[str]] = {}
            if previous is not None:
                for vote in self._votes(team_id, previous):
                    if not vote["payload"].get("agree"):
                        objections[names.get(vote["author"], vote["author"])] = list(
                            vote["payload"].get("objections") or []
                        )
            drafts = self._texts(team_id, "draft")
            critiques = self._texts(team_id, "critique")
            await self._batch(
                team,
                [author],
                kind="plan",
                round_no=round_no,
                prompt=lambda m, notes: prompts.master_plan(
                    name=m["name"],
                    roster=roster,
                    cwd=team["cwd"],
                    drafts={names[k]: v for k, v in drafts.items() if k in ids},
                    critiques={names[k]: v for k, v in critiques.items() if k in ids},
                    previous=str(previous["payload"].get("text") or "") if previous else "",
                    objections=objections,
                    notes=notes,
                ),
                guard=True,
            )
            return  # The loop comes back with the plan (or with a new author).
        author_name = next(m["name"] for m in active if m["member_id"] == plan["author"])
        voted = {v["author"] for v in self._votes(team_id, plan)}
        voters = [
            m for m in active if m["member_id"] != plan["author"] and m["member_id"] not in voted
        ]
        plan_text = str(plan["payload"].get("text") or "")

        def record(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
            verdict = parse_vote(result.text)
            return {
                "text": verdict.text[:_MAX_TEXT],
                "agree": verdict.positive,
                "stated": verdict.stated,
                "objections": list(verdict.objections),
                # A vote is on one plan: a plan rewritten in the same round
                # (its author left) is voted on again.
                "plan_seq": plan["seq"],
            }

        await self._batch(
            team,
            voters,
            kind="vote",
            round_no=round_no,
            prompt=lambda m, notes: prompts.vote(
                name=m["name"],
                roster=roster,
                cwd=team["cwd"],
                author=author_name,
                plan=plan_text,
                notes=notes,
            ),
            record=record,
            guard=True,
        )
        ids = {m["member_id"] for m in self._active(team_id)}
        if plan["author"] not in ids:
            return  # The author left while the others voted: a new plan is due.
        votes = [v for v in self._votes(team_id, plan) if v["author"] in ids]
        against = [v for v in votes if not v["payload"].get("agree")]
        if not against:
            self._adopt(team_id, plan, by_user=False)
            return
        limits = self._store.get(team_id)["limits"]  # type: ignore[index]
        if round_no >= int(limits["plan_rounds"]):
            names = {m["member_id"]: m["name"] for m in self._store.members(team_id)}
            self._halt(
                team,
                "needs_input",
                "plan_disagreement",
                summary={
                    "rounds": round_no,
                    "plan_seq": plan["seq"],
                    "plan_by": plan["author"],
                    "open": [
                        {
                            "member_id": v["author"],
                            "name": names.get(v["author"], v["author"]),
                            "items": list(v["payload"].get("objections") or []),
                        }
                        for v in against
                    ],
                },
            )
        work = self._work(team_id)
        work["plan_round"] = round_no + 1
        self._store.update(team_id, work=work)

    def _adopt(self, team_id: str, plan: dict[str, Any], *, by_user: bool) -> None:
        work = self._work(team_id)
        work["author"] = plan["author"]
        work["builder"] = plan["author"]
        work["plan_seq"] = plan["seq"]
        self._store.update(team_id, work=work, phase="build")
        self._notice(
            team_id,
            "converge",
            "plan_accepted_by_user" if by_user else "plan_agreed",
            {"rounds": int(plan["round"]), "by": plan["author"]},
        )

    async def _phase_build(self, team: dict[str, Any]) -> None:
        team_id = team["team_id"]
        builder = self._builder(team)
        if not self._round(team_id, "build", 0):
            work = self._work(team_id)
            if "baseline" not in work:
                work["baseline"] = (
                    await asyncio.to_thread(self._workspace.snapshot, team["cwd"]) or ""
                )
                self._store.update(team_id, work=work)
                if not work["baseline"]:
                    self._notice(team_id, "build", "no_git")
            plan = self._plan(team)
            roster = self._roster(team_id)
            baseline = work["baseline"]

            async def record(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
                return {
                    "text": result.text[:_MAX_TEXT],
                    **await self._change_summary(team["cwd"], baseline),
                }

            await self._batch(
                team,
                [builder],
                kind="build",
                prompt=lambda m, notes: prompts.build(
                    name=m["name"],
                    roster=roster,
                    cwd=team["cwd"],
                    plan=str(plan["payload"].get("text") or ""),
                    own_plan=plan["author"] == m["member_id"],
                    notes=notes,
                ),
                record=record,
            )
            if not self._round(team_id, "build", 0):
                return  # The builder left; the loop seats another one.
        work = self._work(team_id)
        work["review_round"] = 1
        self._store.update(team_id, work=work)
        self._advance(team_id, "review")

    async def _phase_review(self, team: dict[str, Any]) -> None:
        team_id = team["team_id"]
        round_no = int(team["work"].get("review_round", 1))
        builder = self._builder(team)
        roster = self._roster(team_id)
        baseline = str(team["work"].get("baseline") or "")
        reviewed = {r["author"] for r in self._round(team_id, "review", round_no)}
        reviewers = [m for m in self._active(team_id) if m["member_id"] != builder["member_id"]]
        todo = [m for m in reviewers if m["member_id"] not in reviewed]
        if todo:
            plan = self._plan(team)
            report = self._report(team_id)
            change = await self._change(team["cwd"], baseline) if baseline else None
            before = (
                {
                    r["author"]: list(r["payload"].get("findings") or [])
                    for r in self._round(team_id, "review", round_no - 1)
                }
                if round_no > 1
                else {}
            )

            def record(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
                verdict = parse_review(result.text)
                return {
                    "text": verdict.text[:_MAX_TEXT],
                    "approve": verdict.positive,
                    "stated": verdict.stated,
                    "findings": [f.to_dict() for f in verdict.findings],
                }

            await self._batch(
                team,
                todo,
                kind="review",
                round_no=round_no,
                prompt=lambda m, notes: prompts.review(
                    name=m["name"],
                    roster=roster,
                    cwd=team["cwd"],
                    builder=builder["name"],
                    plan=str(plan["payload"].get("text") or ""),
                    report=report,
                    change=change,
                    again=round_no > 1,
                    earlier=before.get(m["member_id"], []),
                    notes=notes,
                ),
                record=record,
                guard=True,
            )
        ids = {m["member_id"] for m in self._active(team_id)}
        if builder["member_id"] not in ids:
            return
        reviews = [
            r
            for r in self._round(team_id, "review", round_no)
            if r["author"] in ids and r["author"] != builder["member_id"]
        ]
        open_reviews = [r for r in reviews if not r["payload"].get("approve")]
        if reviews and not open_reviews:
            self._finish(team_id)
            raise _Halt
        names = {m["member_id"]: m["name"] for m in self._store.members(team_id)}
        limits = self._store.get(team_id)["limits"]  # type: ignore[index]
        if round_no >= int(limits["review_rounds"]):
            self._halt(
                team,
                "needs_input",
                "review_disagreement",
                summary={
                    "rounds": round_no,
                    "open": [
                        {
                            "member_id": r["author"],
                            "name": names.get(r["author"], r["author"]),
                            "items": [
                                (f"{f['where']}: " if f.get("where") else "") + f["issue"]
                                for f in r["payload"].get("findings") or []
                                if f.get("severity") == "blocking"
                            ],
                        }
                        for r in open_reviews
                    ],
                },
            )
        if not self._round(team_id, "fix", round_no):
            findings = {
                names.get(r["author"], r["author"]): list(r["payload"].get("findings") or [])
                for r in open_reviews
            }

            async def fixed(member: dict[str, Any], result: TurnResult) -> dict[str, Any]:
                return {
                    "text": result.text[:_MAX_TEXT],
                    **await self._change_summary(team["cwd"], baseline),
                }

            await self._batch(
                team,
                [builder],
                kind="fix",
                round_no=round_no,
                prompt=lambda m, notes: prompts.fix(
                    name=m["name"], roster=roster, cwd=team["cwd"], findings=findings, notes=notes
                ),
                record=fixed,
            )
            if not self._round(team_id, "fix", round_no):
                return
        work = self._work(team_id)
        work["review_round"] = round_no + 1
        self._store.update(team_id, work=work)

    async def _phase_done(self, team: dict[str, Any]) -> None:
        self._finish(team["team_id"])
        raise _Halt

    def _finish(self, team_id: str, *, accepted_open: bool = False) -> None:
        team = self._store.get(team_id)
        assert team is not None
        if team["mode"] == "planner_builder":
            self._finish_planned(team_id, accepted_open=accepted_open)
            return
        work = dict(team["work"])
        work["accepted_open"] = accepted_open
        entries = self._store.entries(team_id)
        findings = [
            f for e in entries if e["kind"] == "review" for f in e["payload"].get("findings") or []
        ]
        last_change = next(
            (e["payload"] for e in reversed(entries) if e["kind"] in ("fix", "build")), {}
        )
        self._store.update(team_id, state="done", phase="done", reason="", note="", work=work)
        self._store.append(
            team_id,
            kind="summary",
            author="team",
            phase="done",
            payload={
                "outcome": "accepted_by_user" if accepted_open else "done",
                "plan_rounds": int(work.get("plan_round", 1)),
                "review_rounds": int(work.get("review_round", 1)),
                "builder": work.get("builder", ""),
                "finding_count": len(findings),
                "blocking": sum(1 for f in findings if f.get("severity") == "blocking"),
                "objections": sum(
                    len(e["payload"].get("objections") or [])
                    for e in entries
                    if e["kind"] == "vote"
                ),
                "files": list(last_change.get("files") or []),
                "stat": str(last_change.get("stat") or ""),
            },
        )

    # ------------------------------------------------------------ turns

    async def _batch(
        self,
        team: dict[str, Any],
        members: list[dict[str, Any]],
        *,
        kind: str,
        prompt: Callable[[dict[str, Any], list[str]], str],
        round_no: int = 0,
        record: Callable[[dict[str, Any], TurnResult], Any] | None = None,
        guard: bool = False,
        label: str = "",
    ) -> None:
        """Run one turn per member at once and file each answer as it arrives.

        A member whose turn fails leaves the team; a turn over its time halts
        the thread. ``guard`` checks that a step that must not change files
        left the folder as it was. ``label`` is what the member's own thread
        shows for the turn (the step's default label without it).
        """
        if not members:
            return
        team_id = team["team_id"]
        fresh = self._store.get(team_id)
        assert fresh is not None
        limits = fresh["limits"]
        if int(fresh["work"].get("turns", 0)) + len(members) > int(limits["max_turns"]):
            self._halt(team, "needs_input", "limit_turns")
        turn_s = int(limits["turn_minutes"]) * 60
        left_s = int(limits["max_minutes"]) * 60 - self._elapsed_ms(fresh) // 1000
        timeout_s = float(max(60, min(turn_s, left_s)))
        phase = fresh["phase"]
        before = await asyncio.to_thread(self._workspace.snapshot, team["cwd"]) if guard else None
        notes_upto = self._store.entries(team_id)[-1]["seq"]
        seen = dict(fresh["work"].get("notes_seen") or {})
        # Everything the person wrote after the task itself.
        user_notes = [e for e in self._store.entries(team_id) if e["kind"] == "user"][1:]
        timed_out: list[str] = []
        said_before = {e["author"] for e in self._store.entries(team_id)}

        failed: list[tuple[dict[str, Any], str]] = []

        async def file(member: dict[str, Any], result: TurnResult) -> None:
            payload: Any = {"text": result.text[:_MAX_TEXT]}
            if record is not None:
                payload = record(member, result)
                if asyncio.iscoroutine(payload):
                    payload = await payload
            self._store.append(
                team_id,
                kind=kind,
                author=member["member_id"],
                phase=phase,
                round=round_no,
                payload=payload,
            )

        async def one(member: dict[str, Any]) -> None:
            mid = member["member_id"]
            notes = [
                str(e["payload"].get("text") or "")
                for e in user_notes
                if e["seq"] > int(seen.get(mid, 0))
            ]
            text = prompt(member, notes)
            started = int(time.time() * 1000)
            self._working.setdefault(team_id, {})[mid] = started
            try:
                result = await self._turn(
                    team_id, member, text, kind, fresh["lang"], timeout_s, label=label
                )
                if result.status == "failed":
                    # One more try before the member counts as failed: an
                    # overloaded provider or a dropped connection passes. Where
                    # the seat's own default model was refused before the member
                    # said anything, the retry runs on a model its account lists.
                    fallback = str(member.get("fallback_model") or "")
                    if fallback and fallback != member["model"] and mid not in said_before:
                        self._port.remodel(member["session_id"], fallback)
                        self._store.member_model(team_id, mid, fallback)
                        self._notice(
                            team_id,
                            phase,
                            "member_model_changed",
                            {"member_id": mid, "model": fallback, "error": result.error[:500]},
                        )
                    result = await self._turn(
                        team_id, member, text, kind, fresh["lang"], timeout_s, label=label
                    )
            finally:
                if self._working.get(team_id, {}).get(mid) == started:
                    self._working[team_id].pop(mid, None)
            if result.status == "ok":
                self._notes_read(team_id, mid, notes_upto)
                filing = asyncio.ensure_future(file(member, result))
                try:
                    await asyncio.shield(filing)
                except asyncio.CancelledError:
                    # The answer exists and is paid for: file it before the stop
                    # goes on, or Continue would ask for the same work again.
                    await asyncio.wait({filing})
                    raise
            elif result.status == "timeout":
                timed_out.append(member["name"])
            else:
                failed.append((member, result.error))

        turns = [asyncio.create_task(one(member)) for member in members]
        try:
            await asyncio.gather(*turns)
        except BaseException:
            # gather hands the first cancelled turn on at once. Pause and Stop
            # must return only when EVERY member's turn has stopped: a CLI still
            # unwinding would be busy when Continue asks it again.
            for turn in turns:
                # Not a second time: that would cut short the stop a turn is in.
                if not turn.done() and not turn.cancelling():
                    turn.cancel()
            await asyncio.wait(turns)
            raise
        if before:
            after = await asyncio.to_thread(self._workspace.snapshot, team["cwd"])
            if after and after != before:
                # Named, so the person can tell a cache a check left behind from an edit.
                change = await asyncio.to_thread(
                    self._workspace.change, team["cwd"], before, after, limit=0
                )
                self._notice(
                    team_id,
                    phase,
                    "files_changed",
                    {"step": kind, "files": list(change.files[:8])},
                )
        if failed:
            if len(self._active(team_id)) - len(failed) >= MIN_MEMBERS:
                for member, error in failed:
                    self._store.member_left(team_id, member["member_id"], error)
                    self._notice(
                        team_id,
                        phase,
                        "member_left",
                        {"member_id": member["member_id"], "error": error[:500]},
                    )
            else:
                # Without them no team is left. That does not end the thread:
                # the seat may only be signed out or over its quota for now, and
                # Continue asks again.
                self._halt(
                    team,
                    "needs_input",
                    "member_failed",
                    note="; ".join(f"{member['name']}: {error[:300]}" for member, error in failed),
                )
        if timed_out:
            self._halt(
                team,
                "needs_input",
                "limit_time" if left_s <= turn_s else "stalled",
                note=", ".join(timed_out),
            )
        if len(self._active(team_id)) < MIN_MEMBERS:
            self._halt(team, "failed", "not_enough_members")

    async def _turn(
        self,
        team_id: str,
        member: dict[str, Any],
        text: str,
        kind: str,
        language: str,
        timeout_s: float,
        *,
        label: str = "",
    ) -> TurnResult:
        """One member turn, counted against the bounds.

        Counted when it starts, not when it ends: a turn that Pause or Stop cut
        short was still run, and it must not be free.
        """
        work = self._work(team_id)
        work["turns"] = int(work.get("turns", 0)) + 1
        self._store.update(team_id, work=work)
        try:
            result = await self._port.ask(
                member["session_id"],
                text,
                display=label or _STEP_LABEL[kind],
                language=language,
                timeout_s=timeout_s,
            )
        except asyncio.CancelledError:
            self._price(team_id, None)  # stopped half way: what it cost is unknown
            raise
        self._price(team_id, result.cost_usd)
        if (
            result.status == "ok"
            and not result.text.strip()
            and kind not in ("build", "fix", "step_build")
        ):
            # A plan, a vote or a review without words is no contribution. A
            # build without a report still changed the files, and counts.
            return TurnResult(
                "failed",
                error="The turn ended without an answer.",
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
            )
        return result

    def _price(self, team_id: str, cost_usd: float | None) -> None:
        work = self._work(team_id)
        if cost_usd is None:
            work["cost_partial"] = True
        else:
            work["cost_usd"] = float(work.get("cost_usd", 0.0)) + cost_usd
        self._store.update(team_id, work=work)

    def _notes_read(self, team_id: str, member_id: str, notes_upto: int) -> None:
        work = self._work(team_id)
        read = dict(work.get("notes_seen") or {})
        read[member_id] = notes_upto
        work["notes_seen"] = read
        self._store.update(team_id, work=work)

    async def _change(self, cwd: str, baseline: str) -> dict[str, Any] | None:
        head = await asyncio.to_thread(self._workspace.snapshot, cwd)
        if not head:
            return None
        change = await asyncio.to_thread(self._workspace.change, cwd, baseline, head)
        return {
            "files": list(change.files),
            "stat": change.stat,
            "patch": change.patch,
            "truncated": change.truncated,
        }

    async def _change_summary(self, cwd: str, baseline: str) -> dict[str, Any]:
        """What an entry keeps of the change: the files and the stat, not the patch."""
        change = await self._change(cwd, baseline) if baseline else None
        if change is None:
            return {"files": [], "stat": ""}
        return {"files": change["files"][:200], "stat": change["stat"][:8000]}

    # ------------------------------------------------------------ helpers

    def _require(self, team_id: str) -> dict[str, Any]:
        team = self._store.get(team_id)
        if team is None:
            raise KeyError(team_id)
        return team

    def _work(self, team_id: str) -> dict[str, Any]:
        team = self._store.get(team_id)
        return dict(team["work"]) if team else {}

    def _advance(self, team_id: str, phase: str) -> None:
        self._store.update(team_id, phase=phase)

    def _notice(
        self, team_id: str, phase: str, code: str, data: dict[str, Any] | None = None
    ) -> None:
        self._store.append(
            team_id,
            kind="notice",
            author="team",
            phase=phase,
            payload={"code": code, **(data or {})},
        )

    def _active(self, team_id: str) -> list[dict[str, Any]]:
        return [m for m in self._store.members(team_id) if m["state"] == "active"]

    def _roster(self, team_id: str) -> list[str]:
        return [m["name"] for m in self._active(team_id)]

    def _authors(self, team_id: str, kind: str) -> set[str]:
        return {e["author"] for e in self._store.entries(team_id) if e["kind"] == kind}

    def _texts(self, team_id: str, kind: str) -> dict[str, str]:
        return {
            e["author"]: str(e["payload"].get("text") or "")
            for e in self._store.entries(team_id)
            if e["kind"] == kind
        }

    def _round(self, team_id: str, kind: str, round_no: int) -> list[dict[str, Any]]:
        return [
            e for e in self._store.entries(team_id) if e["kind"] == kind and e["round"] == round_no
        ]

    def _last(self, team_id: str, kind: str, round_no: int) -> dict[str, Any] | None:
        rows = self._round(team_id, kind, round_no)
        return rows[-1] if rows else None

    def _votes(self, team_id: str, plan: dict[str, Any]) -> list[dict[str, Any]]:
        """The votes cast on exactly this master plan."""
        return [
            vote
            for vote in self._round(team_id, "vote", int(plan["round"]))
            if vote["payload"].get("plan_seq") == plan["seq"]
        ]

    def _plan(self, team: dict[str, Any]) -> dict[str, Any]:
        seq = int(team["work"].get("plan_seq", 0))
        for entry in self._store.entries(team["team_id"]):
            if entry["seq"] == seq:
                return entry
        raise RuntimeError("the agreed master plan is missing")

    def _report(self, team_id: str) -> str:
        """The builder's latest word: the build report or the newest fix report."""
        for entry in reversed(self._store.entries(team_id)):
            if entry["kind"] in ("fix", "build"):
                return str(entry["payload"].get("text") or "") or "No report was written."
        return ""

    def _builder(self, team: dict[str, Any]) -> dict[str, Any]:
        """The member that builds; another one takes over when it left."""
        team_id = team["team_id"]
        active = self._active(team_id)
        wanted = str(self._work(team_id).get("builder") or "")
        for member in active:
            if member["member_id"] == wanted:
                return member
        if len(active) < MIN_MEMBERS:
            self._halt(team, "failed", "not_enough_members")
        work = self._work(team_id)
        work["builder"] = active[0]["member_id"]
        self._store.update(team_id, work=work)
        self._notice(
            team_id, team["phase"], "builder_changed", {"member_id": active[0]["member_id"]}
        )
        return active[0]

    def _waiting(self, session_id: str) -> bool:
        try:
            return bool(self._port.waiting(session_id))
        except Exception:  # noqa: BLE001 - a status hint; the thread itself is unaffected
            log.debug("team thread: waiting state unavailable", exc_info=True)
            return False

    def _discard(self, session_id: str) -> None:
        try:
            self._port.discard(session_id)
        except Exception:  # noqa: BLE001 - a leftover member thread is harmless and visible
            log.warning("team thread: member session %s was not removed", session_id, exc_info=True)


def _title_from(task: str) -> str:
    line = " ".join(task.split())
    return line if len(line) <= 60 else line[:59].rstrip() + "…"


def _roles_of(mode: str, roles: list[str] | None, count: int) -> list[str]:
    """Each member's role in the planner-and-builder mode; ``[]`` for peers.

    Without a pick, member 1 plans, member 2 builds and the rest review. A pick
    needs exactly one planner and one builder, so every plan and every step is
    reviewed by someone who did not write it.
    """
    if mode != "planner_builder":
        return []
    picked = [str(role or "").strip().lower() for role in roles or []]
    if not any(picked):
        return default_roles(count)
    if len(picked) != count or any(role not in ROLES for role in picked):
        raise TeamError(f"Give each member one role of: {', '.join(ROLES)}.")
    if picked.count("planner") != 1 or picked.count("builder") != 1:
        raise TeamError("A team needs exactly one planner and one builder.")
    return picked


def _unique_names(seats: list[SeatPick]) -> list[str]:
    """Each member's display name, unique in the team.

    A member is named after its seat, and a model the person picked follows
    the name ("Anthropic Claude · Opus 5.5"), so two members on one seat with
    different models read apart. Members that still share a name are told
    apart by number ("Anthropic Claude 1", "Anthropic Claude 2").
    """
    base = []
    for seat in seats:
        name = (seat.name or seat.model or seat.provider).strip() or seat.provider
        label = seat.model_label.strip()
        base.append(f"{name} · {label}" if label and not name.endswith(label) else name)
    counts: dict[str, int] = {}
    names = []
    for name in base:
        counts[name] = counts.get(name, 0) + 1
        names.append(name if base.count(name) == 1 else f"{name} {counts[name]}")
    return names


def _issues(entries: list[dict[str, Any]], *, done: bool) -> list[dict[str, Any]]:
    """Everything the members caught in each other's work, oldest first.

    An objection is settled once its author agreed to a later plan or wrote the
    next one itself (or the team agreed on a plan); a finding once its reviewer
    approved a later round.
    """
    issues: list[dict[str, Any]] = []
    agreed_after: dict[str, int] = {}
    approved_after: dict[str, int] = {}
    plan_settled = any(
        e["kind"] == "notice" and e["payload"].get("code") in ("plan_agreed",) for e in entries
    )
    for entry in entries:
        if entry["kind"] == "plan" or (entry["kind"] == "vote" and entry["payload"].get("agree")):
            agreed_after[entry["author"]] = max(
                agreed_after.get(entry["author"], 0), entry["round"]
            )
        if entry["kind"] == "review" and entry["payload"].get("approve"):
            approved_after[entry["author"]] = max(
                approved_after.get(entry["author"], 0), entry["round"]
            )
    for entry in entries:
        if entry["kind"] == "vote":
            for text in entry["payload"].get("objections") or []:
                issues.append(
                    {
                        "seq": entry["seq"],
                        "stage": "plan",
                        "round": entry["round"],
                        "by": entry["author"],
                        "severity": "blocking",
                        "where": "",
                        "issue": text,
                        "fix": "",
                        "resolved": plan_settled
                        or agreed_after.get(entry["author"], 0) > entry["round"],
                    }
                )
        elif entry["kind"] == "review":
            for finding in entry["payload"].get("findings") or []:
                issues.append(
                    {
                        "seq": entry["seq"],
                        "stage": "review",
                        "round": entry["round"],
                        "by": entry["author"],
                        **finding,
                        "resolved": done or approved_after.get(entry["author"], 0) > entry["round"],
                    }
                )
    return issues
