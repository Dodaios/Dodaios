"""The second look before anything leaves in the person's name.

:func:`check_outbound` reads an outbound call (mail, message, post) and returns
findings. Each finding carries a ``severity``:

``block``   the call must not run as it is (a secret in the text).
``ask``     a person must look first (a recipient never written to before, a
            domain that looks mistyped, a tone that reads wrong).

Rules, not a model: the check runs on every send, offline, in microseconds,
and a model that wrote the message cannot talk it out of a finding. A model
reviewer can be added later through :func:`set_reviewer`; its findings join
these, they never replace them.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final

from dodaios.core.redact import redact_secrets

from .hard_limits import BODY_KEYS, is_outbound, recipients_of
from .recipients import normalize_recipient

log = logging.getLogger(__name__)

Severity = str  # "block" | "ask"


@dataclass(frozen=True, slots=True)
class OutboundFinding:
    code: str
    severity: Severity
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "detail": self.detail}


#: Credential shapes the redactor does not label but a mail must never carry.
_SECRET_SHAPES: Final[re.Pattern[str]] = re.compile(
    r"(-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}\b"
    r"|\bxox[abprs]-[A-Za-z0-9-]{20,}\b"
    r"|\bsk-[A-Za-z0-9_-]{20,}\b"
    r"|\bAIza[0-9A-Za-z_-]{30,}\b"
    r"|\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b)"
)
#: "password: hunter2" in any casing, in English or German.
_SPELLED_SECRET: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(password|passwort|passwd|pin)\s*(is|ist|:|=)\s*\S{4,}"  # i18n-allow: input vocab
)

_COMMON_DOMAINS: Final[tuple[str, ...]] = (
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
    "gmx.de",
    "gmx.net",
    "web.de",
    "t-online.de",
    "posteo.de",
    "mail.com",
    "aol.com",
)

_PROFANITY: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(fuck\w*|\w*shit\w*|asshole|bastard|bitch|idiot\w*|moron\w*|stupid|dumbass"
    r"|scheiß\w*|arschloch|verdammt|blöd\w*|dumm\w*)\b"  # i18n-allow: input vocab
)
_SHOUTING_MIN_WORDS: Final[int] = 5


def _texts(args: dict[str, Any]) -> list[str]:
    nested = args.get("arguments")
    pool = [args, nested] if isinstance(nested, dict) else [args]
    out: list[str] = []
    for part in pool:
        for key in BODY_KEYS:
            value = part.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value)
    return out


def _domain(address: str) -> str:
    key = normalize_recipient(address)
    return key.rsplit("@", 1)[1] if "@" in key else ""


def _edit_distance_le_one(a: str, b: str) -> bool:
    """One typo apart: a changed, missing, extra or swapped letter (``gmial``)."""
    if a == b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1 :] == short:
            return True
    return False


def _mistyped_domain(address: str) -> str | None:
    domain = _domain(address)
    if not domain or domain in _COMMON_DOMAINS:
        return None
    for known in _COMMON_DOMAINS:
        if _edit_distance_le_one(domain, known):
            return known
    return None


def _tone_problem(text: str) -> str | None:
    if _PROFANITY.search(text):
        return "profanity"
    if re.search(r"!{3,}", text):
        return "exclamation"
    words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", text)  # letters incl. accented ones
    if len(words) >= _SHOUTING_MIN_WORDS:
        shouting = sum(1 for w in words if w.isupper())
        if shouting / len(words) >= 0.6:
            return "shouting"
    return None


Reviewer = Callable[[str, dict[str, Any]], Iterable[OutboundFinding]]
_REVIEWER: list[Reviewer] = []


def set_reviewer(reviewer: Reviewer | None) -> None:
    """Install an extra reviewer (a cheap model, say). Its findings are added."""
    _REVIEWER.clear()
    if reviewer is not None:
        _REVIEWER.append(reviewer)


def check_outbound(
    tool_name: str,
    args: dict[str, Any] | None,
    *,
    recipients_known: Callable[[Iterable[str]], bool] | None = None,
) -> list[OutboundFinding]:
    """Findings for an outbound call; empty for anything else or anything fine."""
    args = args if isinstance(args, dict) else {}
    if not is_outbound(tool_name, args):
        return []
    findings: list[OutboundFinding] = []
    texts = _texts(args)

    for text in texts:
        if (
            redact_secrets(text) != text
            or _SECRET_SHAPES.search(text)
            or _SPELLED_SECRET.search(text)
        ):
            findings.append(OutboundFinding("secret", "block"))
            break

    recipients = recipients_of(tool_name, args)
    if recipients:
        if recipients_known is None:
            from .recipients import known_recipients

            recipients_known = known_recipients().knows_all
        unknown = [r for r in recipients if not recipients_known([r])]
        if unknown:
            findings.append(OutboundFinding("unknown_recipient", "ask", ", ".join(unknown)[:200]))
        for recipient in recipients:
            meant = _mistyped_domain(recipient)
            if meant:
                shown = f"{normalize_recipient(recipient)} → {meant}"
                findings.append(OutboundFinding("mistyped_domain", "ask", shown))
                break

    for text in texts:
        problem = _tone_problem(text)
        if problem:
            findings.append(OutboundFinding("tone", "ask", problem))
            break

    for reviewer in _REVIEWER:
        try:
            findings.extend(reviewer(tool_name, args))
        except Exception:  # noqa: BLE001 — an extra reviewer never breaks the send
            log.warning("outbound check: reviewer failed", exc_info=True)
    return findings


def blocks(findings: Iterable[OutboundFinding]) -> bool:
    return any(f.severity == "block" for f in findings)


def asks(findings: Iterable[OutboundFinding]) -> bool:
    return any(f.severity == "ask" for f in findings)


__all__ = ["OutboundFinding", "asks", "blocks", "check_outbound", "set_reviewer"]
