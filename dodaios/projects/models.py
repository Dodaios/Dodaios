"""The data of a project: pure models and rules, no I/O and no model calls.

A project is the owner's goal, the criteria that say when it is met, and a plan of
sub-goals. Each sub-goal names who does it, what it waits for and what evidence
counts as done. A sub-goal becomes ``done`` only through evidence (a job the ledger
shows as done, optionally verified, or the owner's own confirmation), never through
the model's say-so: :func:`derive_state` is the one rule.
"""

from __future__ import annotations

import re
import time
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SubGoalState = Literal["pending", "running", "done", "failed", "blocked", "skipped"]
ProjectStatus = Literal["active", "paused", "blocked", "complete", "abandoned"]
Evidence = Literal["job", "verified", "owner"]

#: A project that is over. Reviews and the watchdog leave it alone.
CLOSED: Final[frozenset[str]] = frozenset({"complete", "abandoned"})
#: Structural bounds of one project (a schema limit, not a cost lever).
MAX_SUBGOALS: Final[int] = 100
DAY_MS: Final[int] = 24 * 3600 * 1000
DEFAULT_REVIEW_S: Final[int] = 24 * 3600
DEFAULT_STALL_DAYS: Final[int] = 3
#: A sub-goal gets exactly one automatic re-plan after a failure.
MAX_REPLANS: Final[int] = 1

_OWNER = re.compile(r"^(lead|team|owner|agent:\S+|pane:\S+)$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def now_ms() -> int:
    return int(time.time() * 1000)


class SubGoal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str = Field(min_length=1, max_length=300)
    #: lead, agent:<name>, pane:<id>, team (a team thread) or owner (the person).
    owner: str = "lead"
    depends_on: list[str] = Field(default_factory=list)
    #: What proves it done: the job's own record, that plus verify_delegate, or the owner.
    evidence: Evidence = "job"
    state: SubGoalState = "pending"
    job_id: str = ""
    #: Earlier job ids of this sub-goal (a retry keeps the trail).
    history: list[str] = Field(default_factory=list)
    attempts: int = 0
    replans: int = 0
    #: The last failure or block reason, or the note of a re-plan.
    note: str = ""
    #: The evidence that closed it (job summary, result ref, verification verdict).
    proof: str = ""
    updated_ms: int = 0
    done_ms: int = 0


class Project(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=4000)
    criteria: list[str] = Field(default_factory=list)
    status: ProjectStatus = "active"
    owner_session: str = ""
    subgoals: list[SubGoal] = Field(default_factory=list)
    created_ms: int
    updated_ms: int
    #: When the evidence last changed (a sub-goal moved, a job changed).
    last_progress_ms: int
    review_every_s: int = DEFAULT_REVIEW_S
    next_review_ms: int = 0
    stall_days: int = DEFAULT_STALL_DAYS
    #: Fingerprint of the progress evidence at the last review, and of the last report sent.
    evidence_fp: str = ""
    reported_fp: str = ""
    #: What the owner must decide now ("" = nothing), and why: stuck (a sub-goal failed after
    #: its one re-plan), rescope (the owner or the watchdog asked), criteria (done but not met),
    #: ready (done, waiting for the check).
    decision: str = ""
    decision_kind: Literal["", "stuck", "rescope", "criteria", "ready"] = ""
    #: The sub-goal states at the last report, so the next line says only what moved.
    reported_states: dict[str, str] = Field(default_factory=dict)
    #: The done-set the evaluator last judged (it is asked again only when this changes).
    evaluated_fp: str = ""
    #: Chat sessions and calendar days that touched the project (the multi-session measure).
    sessions: list[str] = Field(default_factory=list)
    days: list[str] = Field(default_factory=list)
    closed_ms: int = 0
    close_note: str = ""

    def subgoal(self, sid: str) -> SubGoal | None:
        return next((s for s in self.subgoals if s.id == sid), None)

    @property
    def is_closed(self) -> bool:
        return self.status in CLOSED


def validate_plan(subgoals: list[SubGoal]) -> str:
    """The reason a plan is invalid, or ``""``. Ids unique, owners known, no cycles."""
    if len(subgoals) > MAX_SUBGOALS:
        return f"A project has at most {MAX_SUBGOALS} sub-goals."
    ids = [s.id for s in subgoals]
    if len(set(ids)) != len(ids):
        return "Sub-goal ids must be unique."
    for sub in subgoals:
        if not _ID.match(sub.id):
            return f"Sub-goal id '{sub.id}' must be letters, digits, '-' or '_' (max 40)."
        if not _OWNER.match(sub.owner):
            return f"Sub-goal {sub.id}: owner must be lead, team, owner, agent:<name> or pane:<id>."
        unknown = [d for d in sub.depends_on if d not in ids]
        if unknown or sub.id in sub.depends_on:
            return f"Sub-goal {sub.id} depends on an unknown or its own id: {unknown or [sub.id]}."
    # Kahn's algorithm: whatever cannot be ordered sits on a cycle.
    remaining = {s.id: set(s.depends_on) for s in subgoals}
    while remaining:
        free = [i for i, deps in remaining.items() if not deps]
        if not free:
            return "The sub-goal dependencies contain a cycle: " + ", ".join(sorted(remaining))
        for i in free:
            del remaining[i]
        for deps in remaining.values():
            deps.difference_update(free)
    return ""


def is_ready(project: Project, sub: SubGoal) -> bool:
    """A pending sub-goal with no job whose dependencies are all done (or skipped)."""
    if sub.state != "pending" or sub.job_id:
        return False
    return all(
        (d := project.subgoal(dep)) is not None and d.state in ("done", "skipped")
        for dep in sub.depends_on
    )


def outstanding(project: Project) -> list[SubGoal]:
    """Sub-goals that are not done or skipped yet."""
    return [s for s in project.subgoals if s.state not in ("done", "skipped")]


def derive_state(job_state: str, verdict: str, evidence: Evidence) -> tuple[SubGoalState, str]:
    """The sub-goal state a job's evidence supports, with the reason when it is not done.

    ``job_state`` is the ledger state; ``verdict`` the ``verify_delegate`` verdict
    (``""`` when none was asked for). Only ``done`` plus what ``evidence`` demands
    reads as done; an unknown or missing state never does.
    """
    if job_state in ("queued", "running"):
        return "running", ""
    if job_state == "done":
        if evidence == "verified" and verdict != "verified":
            reason = "verify_delegate could not confirm the result"
            return ("failed" if verdict == "failed" else "blocked"), (
                f"The job is done but {reason} ({verdict or 'unverified'})."
            )
        return "done", ""
    if job_state in ("failed", "interrupted", "cancelled"):
        return "failed", f"The job ended as {job_state}."
    return "blocked", f"The job is {job_state or 'unknown'}."


def fingerprint(project: Project) -> str:
    """What counts as progress: any sub-goal's state or job changing."""
    return "|".join(f"{s.id}:{s.state}:{s.job_id}:{s.replans}" for s in project.subgoals)
