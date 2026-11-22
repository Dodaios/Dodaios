"""What the record says about a delegated coding run, as a delegate verdict.

``verify_delegate`` answers ``verified`` / ``unverified`` / ``failed`` for a job.
For a coding thread the evidence is the run's record: how its turn ended and
what the output scan found. A scan that found a weakened check or an
off-limits change fails the job. A clean scan does not prove the change works,
so without independent test evidence the answer stays ``unverified``.
"""

from __future__ import annotations

from typing import Any

from dodaios.core.delegate_verify import Check, Verification

from . import gates
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


def from_run(run: dict[str, Any], steps: list[dict[str, Any]]) -> Verification:
    """The verdict the record of ``run`` supports."""
    job_id = str(run.get("run_id") or "")
    if run.get("state") != ENDED:
        return Verification(
            job_id, "coding", "unverified", "The run's end is not on record.",
            [Check("turn", None, f"the run is {run.get('state') or 'unknown'}")],
        )
    turn = str(run.get("turn_status") or "")
    checks = [Check("turn", turn == "done", f"the thread's turn ended as {turn or 'unknown'}")]
    gate = next((step for step in reversed(steps) if step.get("step") == "gates"), None)
    checks.append(_scan_check(gate))
    checks.append(Check("tests", None, "no independent test evidence was read for this run"))
    if any(check.ok is False for check in checks):
        failed = next(check for check in checks if check.ok is False)
        return Verification(
            job_id, "coding", "failed", "The claim does not hold: " + failed.detail, checks
        )
    return Verification(
        job_id, "coding", "unverified",
        "Nothing contradicts the result, but nothing proves it works either "
        "(no independent test evidence).",
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
