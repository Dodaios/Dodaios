"""What the lead's wait is told about a thread job whose output is being checked.

A coding thread's job used to count as done the moment its turn ended. While
``[rsi] verify = "enforce"`` the job's probe goes through :func:`shape`, which
answers from the run's record instead:

* the run is still open (its output is being checked, checks are waited for, a
  follow-up order is on its way or its turn runs): ``running``, with a
  ``progress`` that moves while the check is alive, so the wait neither ends
  early nor gives up;
* the run got its verdict: the final answer, in the status words the jobs
  ledger knows (``completed`` with ``detail`` ``verified`` or ``unverified``,
  ``failed``, ``superseded``, ``needs_input``);
* the thread waits for the person (a question, an approval, a plan): that is
  passed on at once, whatever the check is doing.

It only reads. It never starts anything and never calls a model, and it falls
back to what the thread itself says when no run is on record or the one that
checks has gone silent (:data:`STALE_MS`): a dead check must not hold the
person's answer for ever.
"""

from __future__ import annotations

import time
from typing import Any, Final

from . import driver
from .store import CHECKING, ENDED, RUNNING

__all__ = ["STALE_MS", "shape"]

#: A run whose check showed no sign of life for this long is taken to be dead.
STALE_MS: Final[int] = 15 * 60 * 1000
#: Passed on untouched: the thread needs the person, or it is gone.
_PASS_ON: Final[frozenset[str]] = frozenset({"needs_input", "stopped"})


def _final(run: dict[str, Any], said: str) -> dict[str, Any]:
    verdict = str(run.get("verdict") or "")
    reason = str(run.get("verdict_reason") or "")
    if verdict == driver.VERIFIED:
        return {
            "status": "completed", "detail": "verified", "report": said,
            "evidence": f"Checked by the app, independent of the agent's report: {reason}",
        }
    if verdict == driver.FAILED:
        return {
            "status": "failed", "detail": "failed",
            "report": f"The app's check failed it: {reason}" + (f"\n\n{said}" if said else ""),
        }
    if verdict == driver.SUPERSEDED:
        return {"status": "superseded", "detail": "superseded", "report": f"Not judged: {reason}."}
    if verdict == driver.NEEDS_DECISION:
        return {
            "status": "needs_input", "detail": "needs_decision",
            "report": f"The agent asks for a decision: {reason}",
        }
    return {
        "status": "completed", "detail": "unverified", "report": said,
        "evidence": f"Not verified by the app: {reason or 'nothing proves that it works'}",
    }


def shape(job_id: str, found: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the wait is told about ``job_id``, given what its thread says (``found``)."""
    from .recorder import recorder

    current = recorder()
    if current is None or not current.enforcing or not job_id:
        return found
    try:
        run = current.store.get(job_id)
    except Exception:  # noqa: BLE001 - an unreadable record leaves the thread's own word
        return found
    if run is None:
        if current.is_noted(job_id) and str((found or {}).get("status") or "") not in _PASS_ON:
            # Noted a moment ago; its record is being written. A turn that ended
            # this fast is not over before its output was checked.
            return {"status": "running", "progress": "check:noted"}
        return found
    status = str((found or {}).get("status") or "")
    if status in _PASS_ON:
        return found
    state = str(run.get("state") or "")
    if state == ENDED and run.get("verdict"):
        return _final(run, str((found or {}).get("report") or ""))
    if status == "running":
        return found  # a turn runs: the thread's own progress keeps the wait alive
    if state in (RUNNING, CHECKING):
        now = int(time.time() * 1000)
        alive = max(
            int(run.get("heartbeat_ms") or 0), int(run.get("ended_ms") or 0),
            int(run.get("started_ms") or 0),
        )
        if found is not None and now - alive > STALE_MS:
            return found  # whoever checks went silent: the thread's word is all there is
        return {
            "status": "running",
            "progress": f"check:{run.get('iteration') or 0}:{run.get('heartbeat_ms') or 0}",
        }
    return found
