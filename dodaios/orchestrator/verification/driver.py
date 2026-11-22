"""What happens after a coding run's output was checked: accept, wait, ask again, or stop.

With ``[rsi] verify = "enforce"`` a run is not over when its thread's turn
ends. The app checks what the turn left behind (the output scan, then what
GitHub says about the commit) and decides here, without a model:

* a check was weakened, or the repository's checks fail: one follow-up order to
  the same thread, built from what was found (:mod:`prompts`);
* checks still run: wait for them, for a bounded time;
* nothing wrong: the run is over, ``verified`` when passing checks prove it,
  else ``unverified`` with the reason.

This module is the decision alone: a pure function of the record. Sending,
waiting and writing are the recorder's. It never looks at an agent while it
works, only at what a finished turn left behind.

**The limits are constants of the code.** No prompt, policy or setting can
raise them: at most :data:`MAX_FOLLOW_UPS` follow-up orders per run and
:data:`MAX_ROOT_FOLLOW_UPS` per request of the person, never the same finding
twice, never after a turn that changed nothing, and never across an app
restart (the thread's CLI may have changed under it).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Final

from . import evidence, gates, prompts

__all__ = [
    "EVIDENCE_WAIT_S",
    "FAILED",
    "MAX_FOLLOW_UPS",
    "MAX_ROOT_FOLLOW_UPS",
    "MAX_RUN_TOKENS_OUT",
    "NEEDS_DECISION",
    "SUPERSEDED",
    "UNVERIFIED",
    "VERDICTS",
    "VERIFIED",
    "Decision",
    "decide",
    "result_line",
]

VERIFIED: Final[str] = "verified"
UNVERIFIED: Final[str] = "unverified"
FAILED: Final[str] = "failed"
#: The person, or a new order, took the thread over: this run is nobody's result.
SUPERSEDED: Final[str] = "superseded"
#: The agent says the next step is not its to take.
NEEDS_DECISION: Final[str] = "needs_decision"
VERDICTS: Final[tuple[str, ...]] = (VERIFIED, UNVERIFIED, FAILED, SUPERSEDED, NEEDS_DECISION)

#: Follow-up orders one run may get: three outputs at most.
MAX_FOLLOW_UPS: Final[int] = 2
#: Follow-up orders all runs of one request of the person may get together.
MAX_ROOT_FOLLOW_UPS: Final[int] = 16
#: Output tokens after which a run gets no further follow-up order.
MAX_RUN_TOKENS_OUT: Final[int] = 400_000
#: How long after an output's end its checks are waited for.
EVIDENCE_WAIT_S: Final[int] = 45 * 60

WAIT: Final[str] = "wait"
FOLLOW_UP: Final[str] = "follow_up"
CLOSE: Final[str] = "close"
#: Ask one model for a second opinion first (:mod:`review`).
REVIEW: Final[str] = "review"

_RESULT = re.compile(
    r"^\s*RESULT:\s*(fixed|cannot-fix|needs-decision)\b[:\s]*(.*)$", re.IGNORECASE
)
_SAID_MAX: Final[int] = 600


@dataclass(frozen=True, slots=True)
class Decision:
    """What to do with a run after its newest output was checked."""

    action: str
    verdict: str = ""
    reason: str = ""
    #: For a follow-up: which template, the order itself, and what it answers.
    template: str = ""
    prompt: str = ""
    signature: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def _close(verdict: str, reason: str) -> Decision:
    return Decision(CLOSE, verdict=verdict, reason=reason)


def _signature(kind: str, parts: list[str]) -> str:
    text = json.dumps(sorted(parts), separators=(",", ":"))
    return f"{kind}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def result_line(text: str) -> tuple[str, str]:
    """``(word, what follows)`` of the closing ``RESULT:`` line of an answer.

    ``("", "")`` without one. The word is a hint for stopping early, never
    proof: ``fixed`` is believed only when the next check agrees.
    """
    for line in reversed((text or "").strip().splitlines()[-6:]):
        found = _RESULT.match(line.strip().strip("`*"))
        if found:
            return found[1].lower(), found[2].strip().strip("`*")[:_SAID_MAX]
    return "", ""


def _policy_limits(run: dict[str, Any]) -> tuple[int, int]:
    """``(follow-up orders, seconds to wait for checks)`` the run's policy allows.

    A policy chooses less than the code's limits, never more; a run without a
    readable policy has the code's limits.
    """
    text = str(run.get("policy_json") or "")
    if not text:
        return MAX_FOLLOW_UPS, EVIDENCE_WAIT_S
    try:
        data = json.loads(text)
        p_max = int(data.get("p_max", MAX_FOLLOW_UPS))
        wait = int(data.get("evidence_wait_s", EVIDENCE_WAIT_S))
    except (TypeError, ValueError):  # an unreadable policy leaves the code's own limits
        return MAX_FOLLOW_UPS, EVIDENCE_WAIT_S
    return max(0, min(p_max, MAX_FOLLOW_UPS)), max(60, min(wait, EVIDENCE_WAIT_S))


def _follow_up_budget(run: dict[str, Any], root_follow_ups: int, same_boot: bool) -> str:
    """Why this run gets no further follow-up order, or ``""`` when it may."""
    if not same_boot:
        return "the app restarted since the run began"
    allowed, _wait = _policy_limits(run)
    if int(run.get("follow_ups") or 0) >= allowed:
        if allowed < MAX_FOLLOW_UPS:
            return f"its policy allows {allowed} follow-up order(s)"
        return f"it already got {MAX_FOLLOW_UPS} follow-up orders"
    if root_follow_ups >= MAX_ROOT_FOLLOW_UPS:
        return "the request's budget of follow-up orders is spent"
    if int(run.get("tokens_out") or 0) >= MAX_RUN_TOKENS_OUT:
        return "the run's token budget is spent"
    return ""


def decide(
    run: dict[str, Any],
    scan: dict[str, Any] | None,
    found: dict[str, Any] | None,
    *,
    now_ms: int,
    said: str = "",
    root_follow_ups: int = 0,
    same_boot: bool = True,
    previous_tree: str = "",
    reviewed: dict[str, Any] | None = None,
    review_trigger: str = "",
    review_budget: str = "",
) -> Decision:
    """The next step for ``run`` after its newest output.

    ``scan`` is the detail of the output scan of that output, ``found`` the
    detail of the newest reading of landing and checks (``None``: not read),
    ``said`` the agent's final message of the turn, ``previous_tree`` the tree
    the output before this one left (after a follow-up order). ``reviewed`` is
    the review of this output when one ran, ``review_trigger`` why one is due
    (``""``: none is), ``review_budget`` why none may run.
    """
    if run.get("person_intervened"):
        return _close(SUPERSEDED, "the person wrote into the thread")
    turn = str(run.get("turn_status") or "")
    if turn == "cancelled":
        return _close(SUPERSEDED, "the turn was stopped")
    if turn != "done":
        return _close(FAILED, f"the thread's turn ended as {turn or 'unknown'}")
    seen = set(json.loads(run.get("signatures_json") or "[]"))
    word, rest = result_line(said)
    if seen and word == "needs-decision":
        return _close(NEEDS_DECISION, rest or "the agent asks for a decision")
    if seen and word == "cannot-fix":
        return _close(FAILED, "the agent could not fix it: " + (rest or "no reason given"))
    scan = scan or {}
    status = str(scan.get("status") or "")
    tree = str(scan.get("tree_id") or "")
    unchanged = bool(seen) and bool(tree) and tree == previous_tree
    budget = _follow_up_budget(run, root_follow_ups, same_boot)

    def ask_again(template: str, signature: str, prompt: str, what: str) -> Decision:
        if unchanged:
            return _close(FAILED, f"{what}, and the follow-up order changed nothing")
        if signature in seen:
            return _close(FAILED, f"{what} again after a follow-up order")
        if budget:
            return _close(FAILED, f"{what}; no further follow-up order because {budget}")
        return Decision(
            FOLLOW_UP, reason=what, template=template, prompt=prompt, signature=signature
        )

    def after_review(close: Decision) -> Decision:
        """``close``, unless a review of this output is due or said otherwise."""
        if status not in (gates.CLEAN, gates.FINDINGS) or not int(scan.get("files") or 0):
            return close
        if reviewed is not None:
            verdict = str(reviewed.get("verdict") or "")
            if verdict == "object":
                findings = list(reviewed.get("findings") or [])
                shown = "; ".join(f"{f.get('file')}: {f.get('problem')}" for f in findings[:2])
                return ask_again(
                    prompts.T3,
                    _signature(
                        "review",
                        [f"{f.get('file')}|{str(f.get('problem'))[:80]}" for f in findings],
                    ),
                    prompts.review_findings(findings),
                    f"a review objects ({shown})",
                )
            if verdict == "approve" or close.verdict != VERIFIED:
                return close
            return _close(
                UNVERIFIED,
                f"{close.reason}, but the review proved nothing: {reviewed.get('reason') or ''}",
            )
        if not review_trigger:
            return close
        if review_budget:
            if close.verdict != VERIFIED:
                return close
            return _close(
                UNVERIFIED, f"{close.reason}, but a review was due ({review_trigger}) and "
                f"{review_budget}",
            )
        return Decision(REVIEW, reason=review_trigger)

    if status == gates.VIOLATIONS:
        violations = [
            f for f in (scan.get("findings") or []) if f.get("severity") == "violation"
        ]
        signature = _signature(
            "scan", [f"{f.get('rule')}|{f.get('path')}" for f in violations]
        )
        shown = "; ".join(f"{f.get('rule')} {f.get('path')}" for f in violations[:3])
        return ask_again(
            prompts.T2,
            signature,
            prompts.weakened_checks(violations, base=str(scan.get("base") or "")),
            f"the change weakens the checks ({shown or 'see the scan'})",
        )
    if status in (gates.UNATTRIBUTED, gates.UNREADABLE, ""):
        return _close(
            UNVERIFIED, str(scan.get("reason") or "the output could not be scanned")
        )
    found = found or {}
    checks = str(found.get("checks") or "")
    landing = str(found.get("landing") or "")
    reason = str(found.get("reason") or "")
    if checks == evidence.FAILING:
        names = [str(name) for name in found.get("failing") or []]
        return ask_again(
            prompts.T1,
            _signature("checks", names or [str(found.get("checked_sha") or "")]),
            prompts.failing_checks(names, where=reason, pr=int(found.get("pr") or 0)),
            "the repository's checks fail (" + (", ".join(names) or "see the pull request") + ")",
        )
    if checks == evidence.PASSING:
        if status != gates.CLEAN:
            return after_review(
                _close(UNVERIFIED, "the checks pass, but the scan left points to look at")
            )
        if not scan.get("committed"):
            return after_review(_close(
                UNVERIFIED,
                "the checks pass, but the work area holds changes beyond the commit they ran on",
            ))
        return after_review(
            _close(VERIFIED, f"{reason}; they pass" if reason else "the checks pass")
        )
    waited_s = (now_ms - int(run.get("ended_ms") or now_ms)) / 1000
    on_github = landing in (evidence.PUSHED, evidence.PR_OPEN, evidence.MERGED)
    if checks == evidence.RUNNING:
        if waited_s < _policy_limits(run)[1]:
            return Decision(WAIT, reason=f"{reason}; the checks run")
        return after_review(_close(UNVERIFIED, f"{reason}; the checks still ran after the wait"))
    # No check in sight yet (CI may not have started), or GitHub did not answer.
    may_come = on_github or bool(found.get("transient"))
    if found and may_come and waited_s < evidence.NO_CHECKS_GIVE_UP_S:
        return Decision(WAIT, reason=reason or "the checks have not been read yet")
    if on_github:
        return after_review(_close(UNVERIFIED, f"{reason}; the commit has no checks"))
    return after_review(_close(UNVERIFIED, reason or "nothing proves that the change works"))
