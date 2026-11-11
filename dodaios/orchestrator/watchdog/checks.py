"""Code checks of the watchdog: plain functions over a snapshot, no model, no I/O.

Many failures of long work are not crashes. A turn keeps going and says nothing,
a job sits in ``running`` for hours, an agent claimed a task and never reported,
a routine did not fire, a model repeats one tool call forever. Each check reads
evidence that already exists (the chat store, the jobs ledger, the society board,
the scheduler, the provider health record) and returns a :class:`Finding` with
the numbers that justify it. Nothing here repairs, notifies or asks a model.

Time limits are deliberately generous: coding-agent turns have no time limit, so a
finding means "no new evidence for a long time", never "this took too long".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final

#: Offered one-click actions (``watchdog_act``).
ACT_NUDGE: Final[str] = "nudge"
ACT_STOP_TURN: Final[str] = "stop_turn"
ACT_CLOSE_TURN: Final[str] = "close_turn"
ACT_REQUEUE: Final[str] = "requeue"
ACT_MARK_INTERRUPTED: Final[str] = "mark_interrupted"
ACT_DISMISS: Final[str] = "dismiss"

KIND_STUCK_TURN: Final[str] = "stuck_turn"
KIND_LOST_TURN: Final[str] = "lost_turn"
KIND_LOOP: Final[str] = "tool_loop"
KIND_STUCK_JOB: Final[str] = "stuck_job"
KIND_INTERRUPTED_JOB: Final[str] = "interrupted_job"
KIND_CLAIM: Final[str] = "claim_without_result"
KIND_ROUTINE: Final[str] = "missed_routine"
KIND_SEAT: Final[str] = "seat_failure"
KIND_LOOP_WEDGED: Final[str] = "app_unresponsive"
KIND_DOWNTIME: Final[str] = "app_was_down"

#: Findings that may ask for the owner's attention beyond a written notice (the opt-in
#: "call me for urgent decisions"): a runaway tool loop and an app that stopped answering.
CRITICAL_KINDS: Final[frozenset[str]] = frozenset({KIND_LOOP, KIND_LOOP_WEDGED})


def severity_of(kind: str) -> str:
    return "critical" if kind in CRITICAL_KINDS else "warning"


#: Open jobs that count as "still working" evidence for the turn that owns them.
_OPEN_JOB_STATES: Final[frozenset[str]] = frozenset({"queued", "running"})
#: Provider statuses (``brain.provider_test``) that are a seat failure. Transient
#: outcomes (rate limit, unreachable) age out by themselves and are not reported.
_SEAT_FAILURES: Final[frozenset[str]] = frozenset({"bad_key", "no_credits", "model_unavailable"})


@dataclass(frozen=True, slots=True)
class Limits:
    """How long the absence of new evidence may last before a check fires (seconds)."""

    lead_turn_idle_s: int = 15 * 60
    other_turn_idle_s: int = 30 * 60
    lost_turn_s: int = 10 * 60
    job_idle_s: dict[str, int] = field(
        default_factory=lambda: {
            "mission": 3 * 3600,
            "artifact": 3600,
            "society_assignment": 3600,
            "ide_submission": 45 * 60,
            "team_thread": 3600,
            "routine": 3600,
        }
    )
    default_job_idle_s: int = 3600
    claim_s: int = 3600
    routine_late_s: int = 15 * 60
    loop_repeats: int = 6
    loop_window: int = 40
    seat_fresh_s: int = 24 * 3600


@dataclass(frozen=True, slots=True)
class TurnView:
    session_id: str
    turn_id: str
    surface: str
    started_ms: int
    last_event_ms: int
    #: The service says a runner holds this seat (``None`` = unknown).
    running: bool | None = None
    steerable: bool = False
    #: Legitimately idle: an approval, a question or a credential card is open.
    waiting_on_person: bool = False
    #: ``name:digest`` of the newest tool calls, newest last.
    tool_signatures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JobView:
    id: str
    kind: str
    title: str
    state: str
    owner_session: str
    #: When the evidence last CHANGED (the watchdog tracks a fingerprint of it).
    progress_ms: int
    created_ms: int
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ClaimView:
    trace_id: str
    agent: str
    claimed_ms: int


@dataclass(frozen=True, slots=True)
class RoutineView:
    task_id: str
    title: str
    due_ms: int


@dataclass(frozen=True, slots=True)
class SeatView:
    provider: str
    modality: str
    status: str
    at_ms: int


@dataclass(slots=True)
class Snapshot:
    now_ms: int
    turns: list[TurnView] = field(default_factory=list)
    jobs: list[JobView] = field(default_factory=list)
    claims: list[ClaimView] = field(default_factory=list)
    routines: list[RoutineView] = field(default_factory=list)
    seats: list[SeatView] = field(default_factory=list)
    #: ``False`` when the app's event loop did not answer a ping in time.
    loop_ok: bool = True
    loop_stalled_s: int = 0


@dataclass(frozen=True, slots=True)
class Finding:
    """One suspicion with the evidence behind it. ``key`` is its dedupe identity."""

    key: str
    kind: str
    title: str
    evidence: dict[str, Any]
    #: The reversible repair the watchdog may try once by itself ("" = none).
    repair: str = ""
    #: One-click actions offered to the person (see ``watchdog_act``).
    actions: tuple[str, ...] = (ACT_DISMISS,)
    #: Where to open it in the app (a session id or a job id), "" = nowhere.
    open_ref: str = ""
    #: Subject for the optional judge: ``(goal, evidence text)``.
    judge: tuple[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.key,
            "kind": self.kind,
            "title": self.title,
            "evidence": self.evidence,
            "actions": list(self.actions),
            **({"open": self.open_ref} if self.open_ref else {}),
        }


def _minutes(seconds: float) -> int:
    return max(1, round(seconds / 60))


def _age_s(now_ms: int, then_ms: int) -> int:
    return max(0, (now_ms - then_ms) // 1000)


def _turn_actions(steerable: bool) -> tuple[str, ...]:
    if steerable:
        return (ACT_NUDGE, ACT_STOP_TURN, ACT_DISMISS)
    return (ACT_STOP_TURN, ACT_DISMISS)


def check_turns(snap: Snapshot, limits: Limits) -> Iterable[Finding]:
    busy_sessions = {j.owner_session for j in snap.jobs if j.state in _OPEN_JOB_STATES}
    for turn in snap.turns:
        idle = _age_s(snap.now_ms, turn.last_event_ms)
        subject = f"{turn.session_id}:{turn.turn_id}"
        loop = _loop_signature(turn.tool_signatures, limits)
        if loop is not None and turn.running is not False:
            name, count = loop
            yield Finding(
                key=f"{KIND_LOOP}:{subject}",
                kind=KIND_LOOP,
                title=f"A turn repeats the same call to {name}",
                evidence={"tool": name, "repeats": count, "session": turn.session_id,
                          "idle_min": _minutes(idle)},
                repair=ACT_NUDGE if turn.steerable else "",
                actions=_turn_actions(turn.steerable),
                open_ref=turn.session_id,
            )
            continue
        if turn.waiting_on_person or turn.session_id in busy_sessions:
            continue
        if turn.running is False:
            if idle >= limits.lost_turn_s:
                yield Finding(
                    key=f"{KIND_LOST_TURN}:{subject}",
                    kind=KIND_LOST_TURN,
                    title="A turn is open but nothing runs it any more",
                    evidence={"session": turn.session_id, "idle_min": _minutes(idle)},
                    actions=(ACT_CLOSE_TURN, ACT_DISMISS),
                    open_ref=turn.session_id,
                )
            continue
        limit = limits.lead_turn_idle_s if turn.surface == "jarvis" else limits.other_turn_idle_s
        if idle >= limit:
            yield Finding(
                key=f"{KIND_STUCK_TURN}:{subject}",
                kind=KIND_STUCK_TURN,
                title="A turn has been silent for a long time",
                evidence={"session": turn.session_id, "idle_min": _minutes(idle),
                          "open_min": _minutes(_age_s(snap.now_ms, turn.started_ms))},
                repair=ACT_NUDGE if turn.steerable else "",
                actions=_turn_actions(turn.steerable),
                open_ref=turn.session_id,
                judge=(f"turn in session {turn.session_id}",
                       f"No new event for {_minutes(idle)} minutes."),
            )


def _loop_signature(signatures: tuple[str, ...], limits: Limits) -> tuple[str, int] | None:
    """The tool call repeated identically (same name, same arguments) too often."""
    window = signatures[-limits.loop_window:]
    if not window:
        return None
    sig, count = Counter(window).most_common(1)[0]
    if count < limits.loop_repeats:
        return None
    return sig.partition(":")[0] or "a tool", count


def check_jobs(snap: Snapshot, limits: Limits) -> Iterable[Finding]:
    for job in snap.jobs:
        if job.state == "interrupted":
            yield Finding(
                key=f"{KIND_INTERRUPTED_JOB}:{job.id}",
                kind=KIND_INTERRUPTED_JOB,
                title=f"Work was interrupted: {job.title}",
                evidence={"job_id": job.id, "kind": job.kind, "state": job.state,
                          "detail": job.detail},
                repair=ACT_REQUEUE,
                actions=(ACT_REQUEUE, ACT_DISMISS),
                open_ref=job.id,
            )
            continue
        if job.state != "running":
            continue
        limit = limits.job_idle_s.get(job.kind, limits.default_job_idle_s)
        idle = _age_s(snap.now_ms, job.progress_ms)
        if idle >= limit:
            yield Finding(
                key=f"{KIND_STUCK_JOB}:{job.id}",
                kind=KIND_STUCK_JOB,
                title=f"No progress on: {job.title}",
                evidence={"job_id": job.id, "kind": job.kind, "idle_min": _minutes(idle),
                          "age_min": _minutes(_age_s(snap.now_ms, job.created_ms)),
                          "status": job.detail or job.state},
                actions=(ACT_MARK_INTERRUPTED, ACT_DISMISS),
                open_ref=job.id,
                judge=(job.title, f"State {job.detail or job.state}; unchanged for "
                       f"{_minutes(idle)} minutes."),
            )


def check_claims(snap: Snapshot, limits: Limits) -> Iterable[Finding]:
    for claim in snap.claims:
        idle = _age_s(snap.now_ms, claim.claimed_ms)
        if idle >= limits.claim_s:
            yield Finding(
                key=f"{KIND_CLAIM}:{claim.trace_id}",
                kind=KIND_CLAIM,
                title=f"{claim.agent} took a task and never reported back",
                evidence={"agent": claim.agent, "trace": claim.trace_id,
                          "claimed_min_ago": _minutes(idle)},
            )


def check_routines(snap: Snapshot, limits: Limits) -> Iterable[Finding]:
    for routine in snap.routines:
        late = _age_s(snap.now_ms, routine.due_ms)
        if late >= limits.routine_late_s:
            yield Finding(
                key=f"{KIND_ROUTINE}:{routine.task_id}:{routine.due_ms}",
                kind=KIND_ROUTINE,
                title=f"A routine did not run: {routine.title}",
                evidence={"task_id": routine.task_id, "late_min": _minutes(late)},
            )


def check_seats(snap: Snapshot, limits: Limits) -> Iterable[Finding]:
    for seat in snap.seats:
        if seat.status in _SEAT_FAILURES and _age_s(snap.now_ms, seat.at_ms) <= limits.seat_fresh_s:
            yield Finding(
                key=f"{KIND_SEAT}:{seat.provider}:{seat.modality}:{seat.status}",
                kind=KIND_SEAT,
                title=f"{seat.provider} ({seat.modality}) is failing: {seat.status}",
                evidence={"provider": seat.provider, "modality": seat.modality,
                          "status": seat.status},
            )


def check_loop(snap: Snapshot, _limits: Limits) -> Iterable[Finding]:
    if not snap.loop_ok:
        yield Finding(
            key=f"{KIND_LOOP_WEDGED}:{snap.now_ms // (3600 * 1000)}",
            kind=KIND_LOOP_WEDGED,
            title="The app stopped answering",
            evidence={"stalled_s": snap.loop_stalled_s},
        )


def run_checks(snap: Snapshot, limits: Limits | None = None) -> list[Finding]:
    """Every finding of one scan, in a stable order."""
    limits = limits or Limits()
    out: list[Finding] = []
    for check in (check_loop, check_turns, check_jobs, check_claims, check_routines, check_seats):
        out.extend(check(snap, limits))
    return out


__all__ = [
    "ACT_CLOSE_TURN", "ACT_DISMISS", "ACT_MARK_INTERRUPTED", "ACT_NUDGE", "ACT_REQUEUE",
    "ACT_STOP_TURN", "ClaimView", "Finding", "JobView", "Limits", "RoutineView", "SeatView",
    "Snapshot", "TurnView", "run_checks",
]
