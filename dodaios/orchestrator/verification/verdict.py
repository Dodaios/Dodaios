"""What the record says about a delegated coding run, as a delegate verdict.

``verify_delegate`` answers ``verified`` / ``unverified`` / ``failed`` for a job.
For a coding thread the evidence is the run's record: how its turn ended, what
the output scan found, and what the repository's checks say about the commit
the run left behind.

* ``failed``: the turn failed, the scan found a weakened check or an off-limits
  change, or the checks on the run's commit fail.
* ``verified``: the turn ended well, the scan found nothing at all, the work
  area held nothing beyond the commit, and the checks on that commit (for
  merged work: on the merge commit) pass.
* ``unverified``: everything else. A clean scan alone does not prove the change
  works.
"""

from __future__ import annotations

from typing import Any

from dodaios.core.delegate_verify import Check, Verification

from . import driver, evidence, gates
from .store import ENDED

__all__ = ["for_job", "from_run"]

_SHOWN = 3


def _scan_check(gate: dict[str, Any] | None) -> Check:
    if gate is None:
        return Check("output_scan", None, "the output was not scanned")
    detail = gate.get("detail") or {}
    status = str(detail.get("status") or gate.get("status") or "")
    size = (
        f"{detail.get('files', 0)} file(s), "
        f"+{detail.get('added', 0)}/-{detail.get('deleted', 0)}"
    )
    if status == gates.VIOLATIONS:
        shown = [
            f"{f.get('rule')} {f.get('path')}: {f.get('note')}"
            for f in (detail.get("findings") or [])
            if f.get("severity") == "violation"
        ][:_SHOWN]
        return Check("output_scan", False, "; ".join(shown) or "a check was weakened")
    if status in (gates.UNATTRIBUTED, gates.UNREADABLE):
        return Check("output_scan", None, str(detail.get("reason") or status))
    if status == gates.FINDINGS:
        return Check(
            "output_scan", True,
            f"{size}; no weakened check on its face, "
            f"{detail.get('ambiguous', 0)} point(s) to look at",
        )
    return Check("output_scan", True, f"{size}; no weakened check, no off-limits path")


def _checks_check(found: dict[str, Any] | None) -> Check:
    """What the repository's checks say about the commit the run left behind."""
    if found is None:
        return Check("checks", None, "no independent test evidence was read for this run")
    detail = found.get("detail") or {}
    landing = str(detail.get("landing") or "")
    checks = str(detail.get("checks") or "")
    reason = str(detail.get("reason") or landing or "nothing is known about the commit")
    if checks == evidence.PASSING:
        return Check("checks", True, f"{reason}; they pass")
    if checks == evidence.FAILING:
        names = ", ".join(detail.get("failing") or []) or "see the pull request"
        return Check("checks", False, f"{reason}; failing: {names}")
    if checks == evidence.RUNNING:
        return Check("checks", None, f"{reason}; they still run")
    if landing in (evidence.PUSHED, evidence.PR_OPEN, evidence.MERGED):
        return Check("checks", None, f"{reason}; the commit has no checks")
    return Check("checks", None, reason)


def from_run(run: dict[str, Any], steps: list[dict[str, Any]]) -> Verification:
    """The verdict the record of ``run`` supports."""
    job_id = str(run.get("run_id") or "")
    if run.get("state") != ENDED:
        return Verification(
            job_id, "coding", "unverified", "The run's end is not on record.",
            [Check("turn", None, f"the run is {run.get('state') or 'unknown'}")],
        )
    judged = str(run.get("verdict") or "")
    if judged in (driver.SUPERSEDED, driver.NEEDS_DECISION):
        # Nobody's result, or a question: neither is a claim that could hold.
        reason = str(run.get("verdict_reason") or judged)
        said = "The run was not judged" if judged == driver.SUPERSEDED else "The agent asks"
        return Verification(
            job_id, "coding", "unverified", f"{said}: {reason}.",
            [Check("turn", None, reason)],
        )
    turn = str(run.get("turn_status") or "")
    checks = [Check("turn", turn == "done", f"the thread's turn ended as {turn or 'unknown'}")]
    gate = next((step for step in reversed(steps) if step.get("step") == "gates"), None)
    checks.append(_scan_check(gate))
    found = next((step for step in reversed(steps) if evidence.is_step(step)), None)
    checks.append(_checks_check(found))
    if any(check.ok is False for check in checks):
        failed = next(check for check in checks if check.ok is False)
        return Verification(
            job_id, "coding", "failed", "The claim does not hold: " + failed.detail, checks
        )
    scan = (gate or {}).get("detail") or {}
    if all(check.ok for check in checks):
        if str(scan.get("status") or "") != gates.CLEAN:
            hold = "the scan left points someone has to look at"
        elif not scan.get("committed"):
            hold = "the work area holds changes beyond the commit the checks ran on"
        else:
            return Verification(
                job_id, "coding", "verified",
                "The turn ended well, the scan found nothing, and the repository's checks "
                "pass on the commit the run left behind.",
                checks,
            )
        return Verification(
            job_id, "coding", "unverified", f"The checks pass, but {hold}.", checks
        )
    return Verification(
        job_id, "coding", "unverified",
        "Nothing contradicts the result, but nothing proves it works either: "
        + next(check.detail for check in checks if check.ok is None) + ".",
        checks,
    )


def for_job(job_id: str) -> Verification | None:
    """The verdict for a thread job, or ``None`` when no run is on record for it."""
    from .recorder import recorder

    current = recorder()
    if current is None:
        return None
    run = current.store.get(job_id)
    if run is None:
        return None
    return from_run(run, current.store.steps(job_id))
