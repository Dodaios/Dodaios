"""Reading the typed end of a member's reply.

A voter or reviewer ends its reply with a fenced ``team-verdict`` block
holding one JSON object. A reply without a readable verdict never counts as
agreement: silence is not consent.

In the planner-and-builder mode the planner ends its plan with a
``team-plan`` block (the steps of the plan) and the builder ends each step
with a ``team-step`` block (done or blocked). A plan without a readable block
is never taken for a plan.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "BLOCK",
    "PLAN_BLOCK",
    "STEP_BLOCK",
    "Finding",
    "PlanReply",
    "PlanStep",
    "StepReport",
    "Verdict",
    "parse_plan",
    "parse_review",
    "parse_step",
    "parse_vote",
]

BLOCK: Final[str] = "team-verdict"
PLAN_BLOCK: Final[str] = "team-plan"
STEP_BLOCK: Final[str] = "team-step"

#: More steps than this is not a plan one builder works through in one thread.
MAX_STEPS: Final[int] = 20


def _fence(name: str) -> re.Pattern[str]:
    return re.compile(rf"```[ \t]*{re.escape(name)}[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


_FENCE = _fence(BLOCK)
_PLAN_FENCE = _fence(PLAN_BLOCK)
_STEP_FENCE = _fence(STEP_BLOCK)
_LOOSE = re.compile(r'"verdict"\s*:\s*"([a-z_]+)"', re.IGNORECASE)
_LOOSE_STATUS = re.compile(r'"status"\s*:\s*"([a-z_]+)"', re.IGNORECASE)
_SEVERITIES: Final[tuple[str, ...]] = ("blocking", "minor")
_NEGATIVE: Final[tuple[str, ...]] = ("object", "changes")


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    where: str
    issue: str
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "where": self.where,
            "issue": self.issue,
            "fix": self.fix,
        }


@dataclass(frozen=True, slots=True)
class Verdict:
    #: True = agree / approve.
    positive: bool
    #: Whether the reply carried a readable verdict at all.
    stated: bool
    #: The reply without its verdict block.
    text: str
    objections: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "blocking")


def _last_block(reply: str, fence: re.Pattern[str]) -> tuple[str | None, str]:
    """The body of the last ``fence`` block of ``reply`` and the reply without it."""
    matches = list(fence.finditer(reply or ""))
    if not matches:
        return None, (reply or "").strip()
    last = matches[-1]
    return last.group(1), ((reply[: last.start()]) + reply[last.end() :]).strip()


def _block(reply: str) -> tuple[dict[str, Any] | None, str]:
    """The last verdict object of ``reply`` and the reply without the block."""
    raw, body = _last_block(reply, _FENCE)
    if raw is None:
        return None, body
    try:
        data = json.loads(raw.strip())
    except ValueError:  # malformed JSON: only a "no" can still be read out of it
        loose = _LOOSE.search(raw)
        word = loose.group(1).lower() if loose else ""
        # The reasons were lost with the JSON. Consent read from a broken block
        # would drop objections or findings, so it counts as no verdict at all.
        return ({"verdict": word} if word in _NEGATIVE else None), body
    return (data if isinstance(data, dict) else None), body


def _strings(value: Any, limit: int = 12) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]  # one objection written as a sentence instead of a list
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip()[:1200] for item in value[:limit] if str(item).strip())


def parse_vote(reply: str) -> Verdict:
    """A vote on the master plan: ``agree`` or ``object`` with objections."""
    data, body = _block(reply)
    if data is None:
        return Verdict(
            positive=False,
            stated=False,
            text=body,
            objections=("No verdict was given, so this counts as an objection.",),
        )
    word = str(data.get("verdict") or "").strip().lower()
    objections = _strings(data.get("objections"))
    if word == "agree" and not objections:
        return Verdict(positive=True, stated=True, text=body)
    if word == "agree":
        # "Agree" with objections listed is not agreement yet.
        return Verdict(positive=False, stated=True, text=body, objections=objections)
    return Verdict(
        positive=False,
        stated=word == "object",
        text=body,
        objections=objections or ("Objected without naming a reason.",),
    )


def parse_review(reply: str) -> Verdict:
    """A review of the build: ``approve`` or ``changes`` with findings."""
    data, body = _block(reply)
    if data is None:
        return Verdict(
            positive=False,
            stated=False,
            text=body,
            findings=(
                Finding("blocking", "", "No verdict was given, so the change is not approved."),
            ),
        )
    word = str(data.get("verdict") or "").strip().lower()
    findings: list[Finding] = []
    raw = data.get("findings")
    if isinstance(raw, str | dict):
        raw = [raw]  # one finding written without the list around it
    for item in raw[:20] if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"issue": item}
        if not isinstance(item, dict):
            continue
        issue = str(item.get("issue") or "").strip()[:1500]
        if not issue:
            continue
        severity = str(item.get("severity") or "").strip().lower()
        findings.append(
            Finding(
                severity=severity if severity in _SEVERITIES else "blocking",
                where=str(item.get("where") or "").strip()[:300],
                issue=issue,
                fix=str(item.get("fix") or "").strip()[:1500],
            )
        )
    blocking = [f for f in findings if f.severity == "blocking"]
    if word == "approve" and not blocking:
        return Verdict(positive=True, stated=True, text=body, findings=tuple(findings))
    if not blocking:
        # "Changes" needs a reason the builder can act on.
        findings.append(
            Finding("blocking", "", "Changes were requested without a finding; see the review.")
        )
    return Verdict(
        positive=False, stated=word in ("approve", "changes"), text=body, findings=tuple(findings)
    )


@dataclass(frozen=True, slots=True)
class PlanStep:
    title: str
    goal: str
    #: The check a reviewer holds the step's result against.
    done_when: str

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "goal": self.goal, "done_when": self.done_when}


@dataclass(frozen=True, slots=True)
class PlanReply:
    #: Whether the reply carried a readable plan at all.
    valid: bool
    #: The reply without its plan block.
    text: str
    steps: tuple[PlanStep, ...] = ()
    #: Accepted steps (1-based, of the plan this one replaces) to do again.
    reopen: tuple[int, ...] = ()
    #: Why the plan could not be read; said to the planner when it is asked again.
    error: str = ""


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit] if not isinstance(value, dict | list) else ""


def parse_plan(reply: str) -> PlanReply:
    """The planner's plan: an ordered list of steps, each with its acceptance check."""
    raw, body = _last_block(reply, _PLAN_FENCE)
    if raw is None:
        return PlanReply(False, body, error=f"The reply has no ```{PLAN_BLOCK} block.")
    try:
        data = json.loads(raw.strip())
    except ValueError as exc:  # said to the planner, who is asked to write it again
        return PlanReply(False, body, error=f"The {PLAN_BLOCK} block is not valid JSON ({exc}).")
    if isinstance(data, list):
        data = {"steps": data}  # the list of steps written without the object around it
    items = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return PlanReply(False, body, error=f'The {PLAN_BLOCK} block has no "steps" list.')
    if len(items) > MAX_STEPS:
        return PlanReply(
            False, body, error=f"The plan has {len(items)} steps; at most {MAX_STEPS} are allowed."
        )
    steps: list[PlanStep] = []
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return PlanReply(False, body, error=f"Step {number} is not an object.")
        title = _clip(item.get("title"), 160)
        done_when = str(item.get("done_when") or "").strip()[:1500]
        if not title or not done_when:
            # A step without its check cannot be reviewed: never a valid plan.
            missing = "title" if not title else "done_when"
            return PlanReply(False, body, error=f'Step {number} has no "{missing}".')
        steps.append(PlanStep(title, str(item.get("goal") or "").strip()[:3000], done_when))
    reopen: list[int] = []
    asked = data.get("reopen")
    for value in asked if isinstance(asked, list) else []:
        try:
            number = int(value)
        except (TypeError, ValueError):  # a step named by its title: nothing to reopen by number
            continue
        if number > 0 and number not in reopen:
            reopen.append(number)
    return PlanReply(True, body, tuple(steps), tuple(reopen))


@dataclass(frozen=True, slots=True)
class StepReport:
    #: "done" or "blocked".
    status: str
    #: Whether the reply carried a readable step block.
    stated: bool
    #: The reply without its step block.
    text: str
    note: str = ""
    #: A change to the rest of the plan the builder asks the planner for.
    plan_change: str = ""


def parse_step(reply: str) -> StepReport:
    """The builder's word on one step: done (the reviewers check it) or blocked."""
    raw, body = _last_block(reply, _STEP_FENCE)
    if raw is None:
        # Nothing claimed: the reviewers check the step against its plan anyway.
        return StepReport("done", False, body)
    try:
        data = json.loads(raw.strip())
    except ValueError:  # malformed JSON: only "blocked" can still be read out of it
        loose = _LOOSE_STATUS.search(raw)
        blocked = bool(loose and loose.group(1).lower() == "blocked")
        return StepReport("blocked" if blocked else "done", False, body)
    if not isinstance(data, dict):
        return StepReport("done", False, body)
    status = str(data.get("status") or "").strip().lower()
    return StepReport(
        "blocked" if status == "blocked" else "done",
        status in ("done", "blocked"),
        body,
        note=str(data.get("note") or "").strip()[:2000],
        plan_change=str(data.get("plan_change") or "").strip()[:4000],
    )
