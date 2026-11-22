"""The values the brief pipeline passes around.

An *order* is one hand-off of work to a coding agent: the draft a writer
produced (the lead, the live voice model, the voice composer or a society
agent), who receives it, and the person's own words it came out of. Every
stage of the pipeline reads an order and none of them changes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "SEVERITY_NOTE",
    "SEVERITY_REVISE",
    "WRITERS",
    "WRITER_COMPOSER",
    "WRITER_LEAD",
    "WRITER_SOCIETY",
    "WRITER_VOICE",
    "BriefDraft",
    "Finding",
    "Order",
    "Recipient",
]

WRITER_LEAD: Final[str] = "lead"
WRITER_VOICE: Final[str] = "voice"
WRITER_COMPOSER: Final[str] = "composer"
WRITER_SOCIETY: Final[str] = "society"
WRITERS: Final[tuple[str, ...]] = (WRITER_LEAD, WRITER_VOICE, WRITER_COMPOSER, WRITER_SOCIETY)

#: A finding the writer has to fix before the brief leaves (one round at most).
SEVERITY_REVISE: Final[str] = "revise"
#: A finding that is recorded and shown, and never holds a brief back.
SEVERITY_NOTE: Final[str] = "note"


@dataclass(frozen=True, slots=True)
class Recipient:
    """Who receives the brief, as far as the hand-off knows it.

    ``cli`` is the coding CLI's registry key (``claude``, ``codex``, ...) and
    ``model`` the model it will run on; both may be empty when the caller left
    the choice to the CLI. ``folder`` is the working folder, empty when it is
    not known yet. ``first_order`` says no earlier order from Dodaios is in
    this agent's conversation, and ``system_channel`` that the app can hand
    this CLI standing text outside the message.
    """

    kind: str = "coding_agent"
    cli: str = ""
    model: str = ""
    effort: str = ""
    folder: str = ""
    first_order: bool = True
    system_channel: bool = False


@dataclass(frozen=True, slots=True)
class BriefDraft:
    """A brief as its writer produced it: the task and its two optional parts."""

    task: str
    context: str = ""
    criteria: str = ""

    def text(self) -> str:
        """The draft as one text, the parts under plain labels."""
        parts = [self.task.strip()]
        if self.context.strip():
            parts.append("Context:\n" + self.context.strip())
        if self.criteria.strip():
            parts.append("Done when:\n" + self.criteria.strip())
        return "\n\n".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class Order:
    """One hand-off: the draft, the recipient and what the person said."""

    writer: str
    draft: BriefDraft
    recipient: Recipient = field(default_factory=Recipient)
    #: The person's own message the order came out of, verbatim; empty when unknown.
    person_words: str = ""
    #: The person's standing wishes for every brief (``dodaios.core.brief_wishes``).
    wishes: str = ""
    #: The writer's own conversation, for the one-revision bookkeeping.
    writer_session: str = ""


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing the check found in a brief.

    ``message`` is a sentence the writer can act on; ``evidence`` quotes the
    part of the brief it is about.
    """

    code: str
    severity: str
    message: str
    evidence: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.evidence:
            out["evidence"] = self.evidence
        return out
