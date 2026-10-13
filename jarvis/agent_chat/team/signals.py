"""Reading the typed end of a peer's reply: its vote or its review verdict.

A voter or reviewer ends its reply with a fenced ``team-verdict`` block
holding one JSON object. A reply without a readable verdict never counts as
agreement: silence is not consent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = ["BLOCK", "Finding", "Verdict", "parse_review", "parse_vote"]

BLOCK: Final[str] = "team-verdict"

_FENCE = re.compile(r"```[ \t]*team-verdict[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
_LOOSE = re.compile(r'"verdict"\s*:\s*"([a-z_]+)"', re.IGNORECASE)
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


def _block(reply: str) -> tuple[dict[str, Any] | None, str]:
    """The last verdict object of ``reply`` and the reply without the block."""
    matches = list(_FENCE.finditer(reply or ""))
    if not matches:
        return None, (reply or "").strip()
    last = matches[-1]
    body = ((reply[: last.start()]) + reply[last.end() :]).strip()
    try:
        data = json.loads(last.group(1).strip())
    except ValueError:  # malformed JSON: only a "no" can still be read out of it
        loose = _LOOSE.search(last.group(1))
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
