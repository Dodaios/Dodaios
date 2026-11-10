"""Jobs for missions and artifact builds (which are missions underneath).

``spawn_worker`` and ``create_artifact`` return before their mission exists: the
mission is created in a background task. So the job is written first (the id
goes into the tool result), the mission id is linked when the dispatch has it,
and a dispatch that dies before that records the failure on the job.

The probe reads the mission store (state only; it dispatches nothing and calls
no model). It is registered as delegated work, so a chat turn that started the
mission is held open until the mission ends, or hands its seat to the next
message and continues later (ADR-0041).
"""

from __future__ import annotations

import logging
from typing import Any, Final

from dodaios.core.delegated_work import DelegatedWork, register_delegated_work
from dodaios.orchestrator import jobs

log = logging.getLogger(__name__)

#: Mission states that are still going. Their word is the evidence's progress.
_LIVE: Final[frozenset[str]] = frozenset(
    {"PENDING", "RUNNING", "CRITIQUING", "LOOPING", "WAITING_CAPACITY"}
)


def mission_probe(manager: Any, job_id: str, *, subject: str = "mission"):
    """A read-only probe of the mission behind ``job_id``."""

    async def probe() -> dict[str, Any] | None:
        job = jobs.get_ledger().get(job_id)
        if job is None:
            return None
        if not job.ref:
            if job.state in jobs.FINAL_STATES:
                # The dispatch ended before a mission existed.
                return {
                    "status": job.state,
                    "report": job.error or job.summary or f"The {subject} was not started.",
                }
            return {"status": "running", "progress": "dispatching"}
        view = await manager.mission(job.ref)
        if view is None:
            return {"status": "failed", "report": f"The {subject} record is gone."}
        state = str(getattr(view.state, "value", view.state))
        ref = f"mission:{job.ref}"
        if state in _LIVE:
            return {"status": "running", "progress": state, "detail": state.lower()}
        if state == "APPROVED":
            if subject == "mission":
                read = f"Read the result with the mission result for {job.ref}."
            elif job.meta.get("artifact_file"):
                read = f"The page {job.meta['artifact_file']} is in the Artifacts section."
            else:
                read = "The page is in the Artifacts section."
            return {
                "status": "completed",
                "report": f"The {subject} finished. {read}",
                "result_ref": ref,
            }
        if state == "CANCELLED":
            return {"status": "cancelled", "report": f"The {subject} was cancelled.",
                    "result_ref": ref}
        return {
            "status": "failed",
            "report": f"The {subject} ended as {state.lower().replace('_', ' ')}.",
            "result_ref": ref,
        }

    return probe


def begin(
    kind: str,
    *,
    ctx: Any,
    title: str,
    manager: Any,
    meta: dict[str, Any] | None = None,
) -> str | None:
    """Write the job for a mission about to be dispatched and hold the turn for it."""
    subject = "artifact" if kind == "artifact" else "mission"
    job_id = jobs.new_job_id()
    probe = mission_probe(manager, job_id, subject=subject)
    started = jobs.start(
        kind, job_id=job_id, ctx=ctx, title=title, target=subject, probe=probe, meta=meta
    )
    if started is None:
        return None
    register_delegated_work(
        DelegatedWork(
            key=f"{subject}:{job_id}",
            name=title or subject,
            probe=jobs.probe_for(job_id) or probe,
        )
    )
    return job_id


def linked(job_id: str | None, mission_id: str) -> None:
    """The dispatch has a mission id: the probe can read it from now on."""
    jobs.link(job_id, str(mission_id))


def failed(job_id: str | None, error: str) -> None:
    """The dispatch died before or while starting the mission."""
    jobs.finish(job_id, "failed", error=error)


def interrupted(job_id: str | None, reason: str) -> None:
    jobs.finish(job_id, "interrupted", summary=reason)


def _rehydrate(job: jobs.Job):
    """After a restart: a mission with an id can still be read from its store."""
    if not job.ref:
        return None
    try:
        from dodaios.brain.factory import _resolve_mission_manager

        manager = _resolve_mission_manager()
    except Exception:  # the mission stack is not up yet: nothing to re-read, the job is interrupted
        return None
    if manager is None:
        return None
    return jobs.ledgered(
        job.id,
        mission_probe(manager, job.id, subject="artifact" if job.kind == "artifact" else "mission"),
    )


jobs.register_rehydrator("mission", _rehydrate)
jobs.register_rehydrator("artifact", _rehydrate)

__all__ = ["begin", "failed", "interrupted", "linked", "mission_probe"]
