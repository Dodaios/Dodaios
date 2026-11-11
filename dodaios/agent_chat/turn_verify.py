"""The lead's cheap, deterministic check of an answer against the turn's tool log.

The tool-use loop calls this where it would otherwise finish
(:class:`dodaios.brain.loop_control.LoopControl.verify`). The only evidence is
the log of tools that really ran: an answer that says "I sent / created /
started ..." while no successful tool of that kind ran is sent back ONCE with a
corrective instruction (run the tool now, or say plainly what was not done).
No model call is made; a verdict that cannot be sure accepts the answer.
"""

from __future__ import annotations

import re
from typing import Final

from dodaios.brain.loop_control import Ask, LoopControl, ToolRecord, VerifyOutcome, VerifyRequest

__all__ = ["claimed_actions", "lead_loop_control", "verify_answer", "verify_answer_sync"]

#: action family -> (first-person past-tense claim, tool-name words that satisfy it)
_FAMILIES: Final[dict[str, tuple[re.Pattern[str], tuple[str, ...]]]] = {
    "sent": (
        re.compile(
            r"\b(?:i(?:'ve| have)?|i just) (?:sent|emailed|messaged|replied|posted)\b"
            r"|\bich habe\b[^.\n]{0,80}\b(?:gesendet|geschickt|verschickt|gepostet|beantwortet)\b",
            re.I,
        ),
        ("send", "mail", "message", "reply", "post", "slack", "chat", "notify", "whatsapp"),
    ),
    "created": (
        re.compile(
            r"\b(?:i(?:'ve| have)?|i just) "
            r"(?:created|saved|wrote|written|added|scheduled|booked|updated|edited)\b"
            r"|\bich habe\b[^.\n]{0,80}\b(?:erstellt|angelegt|gespeichert|geschrieben|hinzugefügt|"  # i18n-allow  # noqa: E501
            r"geplant|gebucht|aktualisiert|geändert)\b",  # i18n-allow
            re.I,
        ),
        (
            "create", "write", "save", "upsert", "add", "edit", "update", "note", "schedule",
            "book", "routine", "memory", "remember", "bash", "shell", "run", "exec", "patch",
            "file", "artifact", "page",
        ),
    ),
    "deleted": (
        re.compile(
            r"\b(?:i(?:'ve| have)?|i just) (?:deleted|removed|cancelled|canceled|archived)\b"
            r"|\bich habe\b[^.\n]{0,80}\b(?:gelöscht|entfernt|abgesagt|archiviert)\b",  # i18n-allow
            re.I,
        ),
        ("delete", "remove", "cancel", "archive", "bash", "shell", "run", "exec"),
    ),
    "started": (
        re.compile(
            r"\b(?:i(?:'ve| have)?|i just) "
            r"(?:started|launched|delegated|dispatched|spawned|opened|assigned)\b"
            r"|\bich habe\b[^.\n]{0,80}\b(?:gestartet|delegiert|beauftragt|geöffnet|zugewiesen)\b",  # i18n-allow  # noqa: E501
            re.I,
        ),
        (
            "start", "launch", "delegate", "dispatch", "spawn", "open", "assign", "run", "task",
            "mission", "agent", "worker", "computer", "bash", "shell", "exec",
        ),
    ),
}

_REVISE: Final = (
    "Your draft says you {claims}, but this turn's tool log has no successful tool call of "
    "that kind{failed}. Do not claim work that did not happen. Either run the missing tool "
    "now, or rewrite the answer to say plainly what was done and what was not (an action "
    "from an earlier turn may stay as history, say so)."
)


def claimed_actions(answer: str) -> list[str]:
    """The action families the answer claims to have performed (first person, past tense)."""
    return [name for name, (pattern, _) in _FAMILIES.items() if pattern.search(answer or "")]


def _satisfied(family: str, log: tuple[ToolRecord, ...]) -> bool:
    """Whether a successful tool of this kind ran AND, where the executor gave
    receipts, the receipt backs the claim: a call without a side effect backs
    nothing, and "I sent" needs a send receipt with hard evidence (a message id),
    not just a tool that returned ok. A record with no receipt state (a path that
    does not go through the executor) is judged by its name, as before."""
    words = _FAMILIES[family][1]
    return any(
        record.ok
        and not record.blocked
        and any(w in record.name.lower() for w in words)
        and record.receipt != "read"
        and not (family == "sent" and record.receipt == "none")
        for record in log
    )


def verify_answer_sync(
    answer: str, tool_log: tuple[ToolRecord, ...]
) -> VerifyOutcome:
    """The deterministic verdict; the lead's post-turn contract calls it on every seat."""
    missing = [f for f in claimed_actions(answer) if not _satisfied(f, tool_log)]
    if not missing:
        return VerifyOutcome(accepted=True)
    failed = [r.name for r in tool_log if not r.ok or r.blocked]
    names = ", ".join(sorted(set(failed))[:6])
    note = f" (these failed or were blocked: {names})" if failed else ""
    claims = "; ".join(f"{m} something" for m in missing)
    return VerifyOutcome(
        accepted=False,
        instruction=_REVISE.format(claims=claims, failed=note),
        detail="claimed actions without a matching successful tool call: " + ", ".join(missing),
    )


async def verify_answer(request: VerifyRequest, ask: Ask) -> VerifyOutcome:  # noqa: ARG001
    """Accept, or send the turn back once when the answer claims unproven actions."""
    return verify_answer_sync(request.answer, request.tool_log)


def lead_loop_control(drain_steer) -> LoopControl:  # type: ignore[no-untyped-def]
    """The lead's hooks: the deterministic check (one revision) and the steering inbox."""
    return LoopControl(drain_steer=drain_steer, verify=verify_answer, max_verify=1)
