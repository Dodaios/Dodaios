"""Project engine: progress from evidence, one re-plan, quiet reviews, a gated close.

Rules (theory criterion 4, long-horizon planning and credit assignment):

* A sub-goal is ``done`` only when its job's own ledger record says so (and
  ``verify_delegate`` agrees when the sub-goal asks for verified evidence), or the
  owner confirms it. The model can link a job and write a note; it cannot mark done.
* A failed sub-goal is re-planned once (back to pending, with the failure in its
  note, so the lead can change owner or wording). A second failure becomes a
  decision for the owner: resume, rescope or close.
* A review reads evidence, never calls a model for progress, and yields ONE short
  written line only when something changed or the owner must decide.
* A project completes only when every sub-goal is done AND an evaluator on another
  model family (the ``/goal`` evaluator) judges the success criteria met on that evidence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .models import (
    MAX_REPLANS,
    Project,
    SubGoal,
    derive_state,
    fingerprint,
    is_ready,
    now_ms,
    outstanding,
    validate_plan,
)
from .store import ProjectStore, get_store

log = logging.getLogger(__name__)

JobReader = Callable[[str], Awaitable[Any]]
Verifier = Callable[[str], Awaitable[tuple[str, str]]]
Evaluator = Callable[[Project, list[dict[str, Any]], bool], Awaitable[Any]]


class ProjectError(ValueError):
    """A refusal the lead can read and act on."""


class EvaluatorUnavailable(RuntimeError):
    """No evaluator may judge the project right now (no connected seat, or a key would bill)."""


@dataclass(slots=True)
class ReviewResult:
    #: The one written line, or ``None`` when nothing changed and nothing needs the owner.
    line: str | None = None
    #: The report fingerprint to store once the line was delivered.
    report_fp: str = ""
    closed: bool = False


@dataclass(slots=True)
class CloseResult:
    closed: bool
    status: str
    reason: str = ""
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "closed": self.closed,
            "status": self.status,
            "reason": self.reason,
            "missing": self.missing,
        }


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def _clip(text: Any, limit: int = 300) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


# ----------------------------------------------------------- default evidence readers


async def _read_job(job_id: str) -> Any:
    from dodaios.orchestrator import jobs

    job = jobs.get_ledger().get(job_id)
    return await jobs.refresh(job) if job is not None else None


async def _verify(job_id: str) -> tuple[str, str]:
    """``(verdict, summary)`` from ``verify_delegate`` for a settled job."""
    from dodaios.core.delegate_verify import Verification, verify_record
    from dodaios.plugins.tool.verify_delegate import resolve

    record = await resolve(job_id)
    if isinstance(record, Verification):
        return record.verdict, record.summary
    if isinstance(record, str):
        return "unverified", record
    result = await asyncio.to_thread(verify_record, record)
    return result.verdict, result.summary


async def _evaluate(project: Project, events: list[dict[str, Any]], background: bool) -> Any:
    """The ``/goal`` evaluator (another model family when one is connected) on the evidence."""
    from dodaios.agent_chat.control_eval import evaluate_goal, pick_evaluator
    from dodaios.agent_chat.lead import lead_session
    from dodaios.brain import background_policy
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    service = runtime.chat_service() if runtime is not None else None
    if service is None:
        raise EvaluatorUnavailable("The chat service is not running.")
    session = (
        service.store.get_session(project.owner_session) if project.owner_session else None
    ) or lead_session(service, create=False)
    if session is None:
        raise EvaluatorUnavailable("There is no conversation to judge the project from.")
    if background:
        # An unattended review never bills a key: it needs a cross-family seat the
        # background policy permits, or the worker's own seat to be one it permits.
        other = await asyncio.to_thread(pick_evaluator, session)
        own = background_policy.background_providers([session.provider]).permits(session.provider)
        if other is None and not own:
            raise EvaluatorUnavailable("No subscription or local seat is free for the check.")
    criteria = "\n".join(f"{i}. {c}" for i, c in enumerate(project.criteria, 1)) or "(none stated)"
    objective = (
        f"{project.goal}\nSUCCESS CRITERIA (every one needs supporting evidence):\n{criteria}"
    )
    return await evaluate_goal(session, objective, events)


# --------------------------------------------------------------------------- engine


class ProjectEngine:
    def __init__(
        self,
        store: ProjectStore | None = None,
        *,
        job_reader: JobReader | None = None,
        verifier: Verifier | None = None,
        evaluator: Evaluator | None = None,
        clock: Callable[[], int] = now_ms,
    ) -> None:
        self._store = store
        self._job_reader = job_reader or _read_job
        self._verifier = verifier or _verify
        self._evaluator = evaluator or _evaluate
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def store(self) -> ProjectStore:
        return self._store if self._store is not None else get_store()

    def _lock(self, project_id: str) -> asyncio.Lock:
        return self._locks.setdefault(project_id, asyncio.Lock())

    def _must_get(self, project_id: str) -> Project:
        project = self.store.get(str(project_id or "").strip())
        if project is None:
            raise ProjectError("No such project.")
        return project

    def _touch(self, project: Project, session: str = "") -> None:
        day = _day(self._clock())
        if day not in project.days:
            project.days.append(day)
        if session and session not in project.sessions:
            project.sessions.append(session)

    def _save(self, project: Project) -> None:
        project.updated_ms = self._clock()
        self.store.save(project)

    # ------------------------------------------------------------------ write calls

    def create(
        self,
        *,
        title: str,
        goal: str,
        criteria: list[str] | None = None,
        subgoals: list[dict[str, Any]] | None = None,
        owner_session: str = "",
        review_every_s: int | None = None,
        stall_days: int | None = None,
    ) -> Project:
        now = self._clock()
        plan = [self._subgoal(raw, now) for raw in subgoals or []]
        if (reason := validate_plan(plan)) != "":
            raise ProjectError(reason)
        fields: dict[str, Any] = {}
        if review_every_s:
            fields["review_every_s"] = max(3600, int(review_every_s))
        if stall_days:
            fields["stall_days"] = max(1, int(stall_days))
        try:
            project = Project(
                id="prj_" + uuid.uuid4().hex[:10],
                title=title.strip() or goal.strip()[:80],
                goal=goal.strip(),
                criteria=[str(c).strip() for c in criteria or [] if str(c).strip()],
                owner_session=owner_session,
                subgoals=plan,
                created_ms=now,
                updated_ms=now,
                last_progress_ms=now,
                **fields,
            )
        except ValueError as exc:
            raise ProjectError(f"Invalid project: {exc}") from exc
        project.next_review_ms = now + project.review_every_s * 1000
        project.reported_states = {s.id: s.state for s in plan}
        self._touch(project, owner_session)
        self.store.save(project)
        return project

    @staticmethod
    def _subgoal(raw: dict[str, Any], now: int) -> SubGoal:
        if not isinstance(raw, dict):
            raise ProjectError("Each sub-goal must be an object with an id and a title.")
        try:
            return SubGoal(
                id=str(raw.get("id") or "").strip(),
                title=str(raw.get("title") or "").strip(),
                owner=str(raw.get("owner") or "lead").strip(),
                depends_on=[str(d) for d in raw.get("depends_on") or []],
                evidence=str(raw.get("evidence") or "job"),  # type: ignore[arg-type]
                updated_ms=now,
            )
        except ValueError as exc:
            raise ProjectError(f"Invalid sub-goal {raw.get('id')!r}: {exc}") from exc

    async def plan(
        self,
        project_id: str,
        *,
        subgoals: list[dict[str, Any]] | None = None,
        drop: list[str] | None = None,
        criteria: list[str] | None = None,
        session: str = "",
    ) -> Project:
        """Add or edit sub-goals (only ones with no live job), or skip some."""
        async with self._lock(project_id):
            project = self._must_get(project_id)
            if project.is_closed:
                raise ProjectError(f"The project is already {project.status}.")
            now = self._clock()
            plan = [s.model_copy(deep=True) for s in project.subgoals]
            for raw in subgoals or []:
                new = self._subgoal(raw, now)
                old = next((s for s in plan if s.id == new.id), None)
                if old is None:
                    plan.append(new)
                    continue
                if old.state in ("done", "running", "skipped"):
                    raise ProjectError(
                        f"Sub-goal {old.id} is {old.state}; only pending, failed or blocked "
                        "sub-goals can be edited."
                    )
                old.title, old.owner = new.title, new.owner
                old.depends_on, old.evidence = new.depends_on, new.evidence
                old.updated_ms = now
            for sid in drop or []:
                target = next((s for s in plan if s.id == sid), None)
                if target is None:
                    raise ProjectError(f"No sub-goal {sid} to drop.")
                if target.state == "done":
                    raise ProjectError(f"Sub-goal {sid} is done; done work is not dropped.")
                target.state, target.updated_ms = "skipped", now
                target.note = "Dropped from the plan."
            if (reason := validate_plan(plan)) != "":
                raise ProjectError(reason)
            project.subgoals = plan
            if criteria is not None:
                project.criteria = [str(c).strip() for c in criteria if str(c).strip()]
            if project.status in ("blocked", "paused"):
                project.status, project.decision, project.decision_kind = "active", "", ""
            project.last_progress_ms = now
            self._touch(project, session)
            self._save(project)
            return project

    async def link_job(
        self, project_id: str, subgoal_id: str, job_id: str, *, session: str = ""
    ) -> Project:
        """Attach the job a sub-goal runs as. The job must exist in the ledger."""
        async with self._lock(project_id):
            project = self._must_get(project_id)
            sub = project.subgoal(subgoal_id)
            if project.is_closed or sub is None:
                raise ProjectError("No open sub-goal with that id.")
            if sub.evidence == "owner":
                raise ProjectError(f"Sub-goal {sub.id} is confirmed by the owner, not by a job.")
            if sub.state in ("done", "skipped"):
                raise ProjectError(f"Sub-goal {sub.id} is already {sub.state}.")
            if sub.state == "running":
                raise ProjectError(f"Sub-goal {sub.id} already runs as {sub.job_id}.")
            waiting = [
                d
                for d in sub.depends_on
                if (dep := project.subgoal(d)) is None or dep.state not in ("done", "skipped")
            ]
            if waiting:
                raise ProjectError(f"Sub-goal {sub.id} waits for: {', '.join(waiting)}.")
            if await self._job_reader(job_id) is None:
                raise ProjectError("That job id is not in the jobs ledger.")
            if sub.job_id:
                sub.history.append(sub.job_id)
            now = self._clock()
            sub.job_id, sub.state, sub.note = job_id, "running", ""
            sub.attempts += 1
            sub.updated_ms = now
            project.last_progress_ms = now
            if project.status == "paused":
                project.status = "active"
            self._touch(project, session)
            self._save(project)
            return project

    async def note(
        self, project_id: str, subgoal_id: str, text: str, *, session: str = ""
    ) -> Project:
        async with self._lock(project_id):
            project = self._must_get(project_id)
            sub = project.subgoal(subgoal_id)
            if sub is None:
                raise ProjectError("No sub-goal with that id.")
            sub.note = _clip(text, 400)
            self._touch(project, session)
            self._save(project)
            return project

    async def confirm(self, project_id: str, subgoal_id: str) -> Project:
        """The owner's confirmation of a sub-goal that asks for it (API and ``/project`` only)."""
        async with self._lock(project_id):
            project = self._must_get(project_id)
            sub = project.subgoal(subgoal_id)
            if sub is None or sub.evidence != "owner":
                raise ProjectError("Only a sub-goal with evidence 'owner' is confirmed this way.")
            now = self._clock()
            sub.state, sub.proof = "done", "Confirmed by the owner."
            sub.done_ms = sub.updated_ms = now
            project.last_progress_ms = now
            self._touch(project)
            self._save(project)
            return project

    async def set_status(
        self, project_id: str, status: str, *, decision: str = "", kind: str = ""
    ) -> Project:
        """Pause, resume or block for a decision (the watchdog's resume and rescope)."""
        async with self._lock(project_id):
            project = self._must_get(project_id)
            if project.is_closed:
                raise ProjectError(f"The project is already {project.status}.")
            now = self._clock()
            project.status = status  # type: ignore[assignment]
            project.decision, project.decision_kind = decision, kind  # type: ignore[assignment]
            if status == "active":
                project.last_progress_ms = now  # a resumed project gets a fresh stall window
                project.next_review_ms = now
            self._save(project)
            return project

    # ------------------------------------------------------------------ progress

    async def _derive(self, project: Project) -> bool:
        """Re-read every linked job; set sub-goal states from the evidence. True if any moved."""
        now = self._clock()
        moved = False
        live: list[str] = []
        for sub in project.subgoals:
            if sub.state in ("done", "skipped") or not sub.job_id or sub.evidence == "owner":
                live.append(f"{sub.id}:{sub.state}")
                continue
            job = await self._job_reader(sub.job_id)
            summary = ""
            if job is None:
                state, why, stamp = "blocked", "The job is not in the ledger.", 0
            else:
                verdict, detail = "", ""
                if job.state == "done" and sub.evidence == "verified":
                    verdict, detail = await self._verifier(sub.job_id)
                state, why = derive_state(job.state, verdict, sub.evidence)
                if job.state != "done":
                    why = _clip(f"{why} {job.error or job.summary}".strip()) if why else ""
                elif detail and state != "done":
                    why = _clip(f"{why} {detail}".strip())
                summary = _clip(
                    f"Job {job.id} done: {job.summary or job.title}"
                    + (f" ({job.result_ref})" if job.result_ref else "")
                    + (f"; verified: {detail}" if verdict == "verified" else "")
                )
                stamp = job.updated_ms
            live.append(f"{sub.id}:{state}:{stamp}")
            if state != sub.state or (state != "done" and why != sub.note):
                moved = moved or state != sub.state
                sub.state, sub.note, sub.updated_ms = state, why, now
                if state == "done":
                    sub.proof, sub.done_ms = summary, now
        fp = "|".join(live)
        if fp != project.evidence_fp:
            project.evidence_fp = fp
            project.last_progress_ms = now
            self._touch(project)
        return moved

    def _replan(self, project: Project) -> tuple[list[SubGoal], list[SubGoal]]:
        """Reset failed sub-goals once. Returns ``(re-planned, stuck)``."""
        now = self._clock()
        replanned: list[SubGoal] = []
        stuck: list[SubGoal] = []
        for sub in project.subgoals:
            failed = sub.state == "failed"
            # A blocked job may still be answered: re-plan it only after a full interval.
            stale_block = (
                sub.state == "blocked" and now - sub.updated_ms >= project.review_every_s * 1000
            )
            if not (failed or stale_block):
                continue
            if sub.replans < MAX_REPLANS:
                if sub.job_id:
                    sub.history.append(sub.job_id)
                sub.note = _clip(f"Re-planned after: {sub.note or sub.state}", 400)
                sub.job_id, sub.state, sub.updated_ms = "", "pending", now
                sub.replans += 1
                replanned.append(sub)
            else:
                stuck.append(sub)
        return replanned, stuck

    @staticmethod
    def _events(project: Project) -> list[dict[str, Any]]:
        events = []
        for i, sub in enumerate((s for s in project.subgoals if s.state == "done"), 1):
            output = json.dumps(
                {
                    "sub_goal": sub.title,
                    "state": "done",
                    "owner": sub.owner,
                    "evidence": sub.proof,
                },
                ensure_ascii=False,
            )
            events.append(
                {"seq": i, "kind": "tool_result", "payload": {"output": output, "is_error": False}}
            )
        return events

    async def close(
        self,
        project_id: str,
        outcome: str = "complete",
        *,
        reason: str = "",
        background: bool = False,
        session: str = "",
    ) -> CloseResult:
        """``complete`` needs all sub-goals done and the evaluator; ``abandon`` is the owner's."""
        async with self._lock(project_id):
            project = self._must_get(project_id)
            return await self._close(project, outcome, reason, background, session)

    async def _close(
        self, project: Project, outcome: str, reason: str, background: bool, session: str
    ) -> CloseResult:
        if project.is_closed:
            return CloseResult(False, project.status, f"The project is already {project.status}.")
        now = self._clock()
        if outcome == "abandon":
            project.status, project.closed_ms = "abandoned", now
            project.close_note = _clip(reason or "Closed by the owner.")
            project.decision, project.decision_kind = "", ""
            self._touch(project, session)
            self._save(project)
            return CloseResult(True, "abandoned", project.close_note)
        if outcome != "complete":
            raise ProjectError("outcome must be 'complete' or 'abandon'.")
        await self._derive(project)
        missing = [f"{s.id}: {s.title} ({s.state})" for s in outstanding(project)]
        if not project.subgoals:
            missing = ["The project has no sub-goals yet; plan it first."]
        if missing:
            self._save(project)
            return CloseResult(False, project.status, "Not every sub-goal is done.", missing)
        done_fp = fingerprint(project)
        try:
            verdict = await self._evaluator(project, self._events(project), background)
        except EvaluatorUnavailable as exc:
            self._save(project)
            return CloseResult(False, project.status, f"The criteria could not be judged: {exc}")
        except Exception as exc:  # noqa: BLE001 - a failed check never closes a project
            log.warning("projects: evaluator failed for %s", project.id, exc_info=True)
            self._save(project)
            return CloseResult(False, project.status, f"The criteria check failed: {_clip(exc)}")
        project.evaluated_fp = done_fp
        if verdict.status != "complete":
            project.decision_kind = "criteria"
            project.decision = _clip(
                "All sub-goals are done, but the success criteria are not shown as met: "
                f"{verdict.reason}",
                500,
            )
            self._save(project)
            reason_text = _clip(verdict.reason, 600)
            return CloseResult(False, project.status, reason_text, [project.decision])
        project.status, project.closed_ms = "complete", now
        project.close_note = _clip(verdict.reason, 600)
        project.decision, project.decision_kind = "", ""
        self._touch(project, session)
        self._save(project)
        return CloseResult(True, "complete", project.close_note)

    # ------------------------------------------------------------------ views

    async def status(self, project_id: str) -> dict[str, Any]:
        """Summary-first view; refreshes the evidence first."""
        async with self._lock(project_id):
            project = self._must_get(project_id)
            if not project.is_closed:
                await self._derive(project)
                self._save(project)
            return self.view(project)

    def view(self, project: Project) -> dict[str, Any]:
        done = sum(1 for s in project.subgoals if s.state in ("done", "skipped"))
        return {
            "id": project.id,
            "title": project.title,
            "status": project.status,
            "goal": project.goal,
            "criteria": project.criteria,
            "progress": f"{done} of {len(project.subgoals)} sub-goals done",
            **({"decision": project.decision} if project.decision else {}),
            **({"closed": project.close_note} if project.close_note else {}),
            "subgoals": [
                {
                    "id": s.id,
                    "title": s.title,
                    "owner": s.owner,
                    "state": s.state,
                    "depends_on": s.depends_on,
                    "evidence": s.evidence,
                    **({"job_id": s.job_id} if s.job_id else {}),
                    **({"ready": True} if is_ready(project, s) else {}),
                    **({"note": s.note} if s.note else {}),
                    **({"proof": s.proof} if s.proof else {}),
                }
                for s in project.subgoals
            ],
        }

    def summaries(self, *, open_only: bool = True) -> list[dict[str, Any]]:
        out = []
        for p in self.store.list(open_only=open_only):
            done = sum(1 for s in p.subgoals if s.state in ("done", "skipped"))
            out.append(
                {
                    "id": p.id,
                    "title": p.title,
                    "status": p.status,
                    "progress": f"{done} of {len(p.subgoals)}",
                    **({"decision": p.decision} if p.decision else {}),
                }
            )
        return out

    # ------------------------------------------------------------------ review

    def due(self) -> list[str]:
        now = self._clock()
        return [
            p.id
            for p in self.store.list(open_only=True)
            if p.status in ("active", "blocked") and p.next_review_ms <= now
        ]

    async def review(self, project_id: str, *, background: bool = True) -> ReviewResult:
        """One review: read evidence, re-plan once, maybe close; the line to write, if any."""
        async with self._lock(project_id):
            project = self._must_get(project_id)
            if project.is_closed or project.status == "paused":
                return ReviewResult()
            now = self._clock()
            await self._derive(project)
            replanned, stuck = self._replan(project)
            if stuck:
                first = stuck[0]
                project.status, project.decision_kind = "blocked", "stuck"
                project.decision = _clip(
                    f"Sub-goal {first.id} ({first.title}) failed again after a re-plan: "
                    f"{first.note}. Resume it, rescope the project or close it.",
                    500,
                )
            elif project.decision_kind == "stuck":
                project.status, project.decision, project.decision_kind = "active", "", ""
            closed = False
            if (
                project.subgoals
                and not outstanding(project)
                and project.status == "active"
                and project.evaluated_fp != fingerprint(project)
            ):
                closed = (await self._close(project, "complete", "", background, "")).closed
                if not closed and project.decision_kind != "criteria":
                    project.decision_kind = "ready"
                    project.decision = (
                        "All sub-goals are done. Ask me to close the project so its "
                        "criteria can be checked."
                    )
            project.next_review_ms = now + project.review_every_s * 1000
            line, fp = self._line(project, replanned)
            self._save(project)
            return ReviewResult(line=line, report_fp=fp, closed=closed)

    @staticmethod
    def _report_fp(project: Project) -> str:
        return f"{fingerprint(project)}|{project.status}|{project.decision_kind}:{project.decision}"

    def _line(self, project: Project, replanned: list[SubGoal]) -> tuple[str | None, str]:
        fp = self._report_fp(project)
        if fp == project.reported_fp:
            return None, fp
        title = f'Project "{project.title}"'
        if project.status == "complete":
            return f"{title} is complete: {project.close_note}", fp
        if project.decision:
            return f"{title} needs your decision: {project.decision}", fp
        moved = [
            s
            for s in project.subgoals
            # Starting work (pending -> running) is not news; an ending or a block is.
            if project.reported_states.get(s.id) != s.state
            and s.state in ("done", "failed", "blocked")
        ]
        if not moved and not replanned:
            return None, fp
        done = sum(1 for s in project.subgoals if s.state in ("done", "skipped"))
        parts = [f"{done} of {len(project.subgoals)} sub-goals done"]
        finished = [s.title for s in moved if s.state == "done"]
        if finished:
            parts.append("finished: " + "; ".join(_clip(t, 60) for t in finished[:3]))
        if replanned:
            parts.append("re-planned once: " + "; ".join(_clip(s.title, 60) for s in replanned[:3]))
        ready = [s.title for s in project.subgoals if is_ready(project, s)]
        if ready:
            parts.append("next: " + _clip(ready[0], 80))
        return f"{title}: " + ", ".join(parts) + ".", fp

    async def mark_reported(self, project_id: str, report_fp: str) -> None:
        """Remember what was delivered, so the next line says only what moved after it."""
        async with self._lock(project_id):
            project = self.store.get(project_id)
            if project is None:
                return
            project.reported_fp = report_fp
            project.reported_states = {s.id: s.state for s in project.subgoals}
            self.store.save(project)


_engine: ProjectEngine | None = None


def get_engine() -> ProjectEngine:
    global _engine
    if _engine is None:
        _engine = ProjectEngine()
    return _engine


def set_engine(engine: ProjectEngine | None) -> None:
    global _engine
    _engine = engine


__all__ = [
    "CloseResult",
    "EvaluatorUnavailable",
    "ProjectEngine",
    "ProjectError",
    "ReviewResult",
    "get_engine",
    "set_engine",
]
