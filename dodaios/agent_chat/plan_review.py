"""A person's review of an agent's plan, as the agent reads it.

A plan card opens a review window (``PlanReviewDialog.tsx``): the person reads
the plan at full size, changes its text and comments on passages. What they did
reaches the agent with their answer:

* **Build** hands the plan back as the person left it. Their comments ride along
  as a closing "Notes from the person" section, so the agent builds with them in
  view.
* **Keep planning** sends the comments, and the person's version of the plan when
  they changed it, as the reason the plan is not approved yet.

Claude Code takes both on its own ``ExitPlanMode`` approval: the edited plan as
the tool's input (the CLI saves it to its plan file and builds it), the comments
as the message of the declined call. Every other coding CLI gets them as its
next message (``turn_prompts``, ``AgentChatService.resolve_turn_plan``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

#: The tools that hand a finished plan to the person (compared in lower case).
PLAN_TOOLS: Final[frozenset[str]] = frozenset({"exitplanmode", "exit_plan_mode"})

MAX_COMMENTS: Final[int] = 200
QUOTE_CHARS: Final[int] = 400
COMMENT_CHARS: Final[int] = 4_000
NOTE_CHARS: Final[int] = 4_000
#: The longest plan a review may hand back (``approval_preview.EDIT_CHARS``).
PLAN_CHARS: Final[int] = 100_000

NOTES_HEADING: Final[str] = "## Notes from the person"
_NOTES_INTRO: Final[str] = (
    "The person approved this plan with the notes below. Follow them while you build; "
    "where a note and the plan disagree, the note wins."
)
_NOT_APPROVED: Final[str] = (
    "The person reviewed your plan and did not approve it yet. Do not build anything."
)


def is_plan_tool(name: str) -> bool:
    """Whether ``name`` is a tool that asks the person to approve a plan."""
    return str(name or "").strip().lower() in PLAN_TOOLS


@dataclass(frozen=True, slots=True)
class PlanComment:
    """One comment: the passage it is about (``""`` for none) and what the person said."""

    quote: str
    text: str


@dataclass(frozen=True, slots=True)
class PlanReview:
    """What the person did in the review window before they answered."""

    #: The plan as the person left it; ``None`` when they did not touch its text.
    plan: str | None = None
    comments: tuple[PlanComment, ...] = ()
    #: A remark on the whole plan.
    note: str = ""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def review_from(
    *, plan: Any = None, comments: Iterable[Any] | None = None, note: Any = ""
) -> PlanReview:
    """A review from request data. Raises ``ValueError`` for one that does not fit.

    A comment without words is dropped; a comment is a mapping or an object with
    ``quote`` and ``text``.
    """
    if plan is not None and not isinstance(plan, str):
        raise ValueError("the plan must be text")
    if plan is not None and len(plan) > PLAN_CHARS:
        raise ValueError("the plan is too long")
    if plan is not None and not plan.strip():
        raise ValueError("the plan cannot be empty")
    rows: list[PlanComment] = []
    for raw in comments or ():
        quote = raw.get("quote") if isinstance(raw, dict) else getattr(raw, "quote", "")
        text = raw.get("text") if isinstance(raw, dict) else getattr(raw, "text", "")
        said = _text(text)[:COMMENT_CHARS]
        if said:
            rows.append(PlanComment(_one_line(_text(quote), QUOTE_CHARS), said))
    if len(rows) > MAX_COMMENTS:
        raise ValueError(f"at most {MAX_COMMENTS} comments")
    return PlanReview(plan, tuple(rows), _text(note)[:NOTE_CHARS])


def _one_line(text: str, limit: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _same(a: str, b: str) -> bool:
    """Two plan texts that read the same (line ends and outer blank lines aside)."""

    def norm(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    return norm(a) == norm(b)


def edited(original: str, review: PlanReview) -> bool:
    """Whether the person changed the plan's text."""
    return review.plan is not None and not _same(review.plan, original)


def is_empty(original: str, review: PlanReview | None) -> bool:
    """Whether the review says nothing: no edit, no comment, no note."""
    return review is None or not (edited(original, review) or review.comments or review.note)


def _indented(text: str) -> str:
    """A comment's later lines under its number, so the list stays a list."""
    first, *rest = text.splitlines() or [""]
    return "\n".join([first, *(f"   {line}" if line.strip() else "" for line in rest)])


def comment_lines(review: PlanReview) -> list[str]:
    """The comments as a numbered list, the note on the whole plan last."""
    lines = [
        f'{n}. On "{c.quote}": {_indented(c.text)}' if c.quote else f"{n}. {_indented(c.text)}"
        for n, c in enumerate(review.comments, 1)
    ]
    if review.note:
        lines.append(f"{len(lines) + 1}. On the whole plan: {_indented(review.note)}")
    return lines


def approved_plan(original: str, review: PlanReview | None) -> str:
    """The plan the agent builds: the person's version, their comments as closing notes.

    Returns ``original`` itself when the review changes nothing.
    """
    if review is None or is_empty(original, review):
        return original
    plan = review.plan.strip() if edited(original, review) and review.plan else original.rstrip()
    lines = comment_lines(review)
    if not lines:
        return plan
    return "\n\n".join([plan, NOTES_HEADING, _NOTES_INTRO, "\n".join(lines)])


def changes_wanted(original: str, review: PlanReview | None) -> str:
    """What the agent is told when the person keeps planning; ``""`` for an empty review."""
    if review is None or is_empty(original, review):
        return ""
    parts = [_NOT_APPROVED]
    lines = comment_lines(review)
    if lines:
        parts.append("Their comments:\n" + "\n".join(lines))
    if edited(original, review) and review.plan:
        parts.append(
            ("They also edited" if lines else "They edited")
            + " the plan itself. Their version replaces yours; carry on from it:\n\n"
            + f"<plan>\n{review.plan.strip()}\n</plan>"
        )
    parts.append(
        "Revise the plan so that it answers every comment, then present it again."
        if lines
        else "Go on planning from their version, then present the plan again."
    )
    return "\n\n".join(parts)


def go_ahead(original: str, review: PlanReview | None, approved: str) -> str:
    """The go-ahead message for a CLI whose plan is its reply (``approved`` = the plain one)."""
    if review is None or is_empty(original, review):
        return approved
    parts = [approved]
    if edited(original, review) and review.plan:
        parts.append(
            "The person edited the plan before approving it. Build their version, not yours:\n\n"
            f"<plan>\n{review.plan.strip()}\n</plan>"
        )
    lines = comment_lines(review)
    if lines:
        parts.append(f"{_NOTES_INTRO}\n" + "\n".join(lines))
    return "\n\n".join(parts)


def shown(original: str, review: PlanReview | None, lead: str) -> str:
    """What the timeline shows as the person's message: ``lead``, then their own words."""
    if review is None or is_empty(original, review):
        return lead
    lines = [lead]
    if edited(original, review):
        lines.append("(I edited the plan.)")
    lines.extend(f"“{c.quote}” — {c.text}" if c.quote else c.text for c in review.comments)
    if review.note:
        lines.append(review.note)
    return "\n".join(lines)


__all__ = [
    "COMMENT_CHARS",
    "MAX_COMMENTS",
    "NOTES_HEADING",
    "NOTE_CHARS",
    "PLAN_CHARS",
    "PLAN_TOOLS",
    "QUOTE_CHARS",
    "PlanComment",
    "PlanReview",
    "approved_plan",
    "changes_wanted",
    "comment_lines",
    "edited",
    "go_ahead",
    "is_empty",
    "is_plan_tool",
    "review_from",
    "shown",
]
