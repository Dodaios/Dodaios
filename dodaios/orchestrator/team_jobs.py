"""Jobs for team threads (ADR-0042): the thread's own row is the evidence.

A team thread runs for a long time and is paused, resumed, stopped or finished by
the person or by its own limits. The job reads the thread's state from the
thread store; it never asks a model and never moves the thread.
"""

from __future__ import annotations

import logging
from typing import Any

from dodaios.core.delegated_work import DelegatedWork, register_delegated_work
from dodaios.orchestrator import jobs

log = logging.getLogger(__name__)


def team_probe(store: Any, team_id: str):
    """A read-only probe of one team thread."""

    async def probe() -> dict[str, Any] | None:
        team = store.get(team_id)
        ref = f"team_thread:{team_id}"
        if team is None:
            return {"status": "failed", "report": "The team thread no longer exists."}
        state = str(team.get("state") or "")
        reason = str(team.get("reason") or "")
        note = str(team.get("note") or "")
        cost = (team.get("work") or {}).get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            jobs.get_ledger().update(_job_id(team_id), cost_usd=float(cost))
        if state == "running":
            progress = f"{team.get('phase')}:{team.get('updated_ms')}"
            return {"status": "running", "progress": progress}
        if state == "done":
            return {
                "status": "completed",
                "report": "The team thread finished.",
                "result_ref": ref,
            }
        if state == "failed":
            return {
                "status": "failed",
                "report": note or "The team thread failed.",
                "result_ref": ref,
            }
        if state == "stopped":
            return {
                "status": "cancelled",
                "report": "The team thread was stopped.",
                "result_ref": ref,
            }
        if state == "paused" and reason == "interrupted":
            return {
                "status": "interrupted",
                "report": note or "The team thread was interrupted.",
                "result_ref": ref,
            }
        # Paused, or waiting for the person (a limit, a question): it needs input.
        return {
            "status": "needs_input",
            "report": note or f"The team thread is waiting ({reason or state}).",
            "result_ref": ref,
        }

    return probe


def _job_id(team_id: str) -> str:
    return jobs.job_id_for("team_thread", team_id)


def begin(store: Any, team_id: str, title: str) -> str | None:
    """Write the job for a team thread that just started; hold the turn for it."""
    job_id = _job_id(team_id)
    probe = team_probe(store, team_id)
    started = jobs.start(
        "team_thread", job_id=job_id, target=f"team_thread:{team_id}", title=title,
        ref=team_id, probe=probe, meta={"team_id": team_id},
    )
    if started is None:
        return None
    register_delegated_work(
        DelegatedWork(key=f"team:{team_id}", name=title or "team thread",
                      probe=jobs.probe_for(job_id) or probe)
    )
    return job_id

