"""The last step before a brief leaves: the text the agent actually reads.

The writer's brief is not changed. Three things are added around it, each for
a reason the writer cannot be relied on to remember every time:

* **the order of its parts** for the receiving model: outcome first for most,
  long context first and the task last where the vendor's guide says so;
* **the person's own words**, verbatim, after the brief. The brief is a
  reading of them, and a reading can be wrong; the agent can then see what was
  really said;
* **one closing line** where the receiving model's guide asks for it, and the
  **standing rules** when this is the first order in a conversation that has
  no other way to get them (``dodaios.briefs.standing``).

What the person sees in the thread stays the writer's brief; this text is what
is sent.
"""

from __future__ import annotations

import re
from typing import Final

from dodaios.agentic_ide.task_kind import KIND_IMPLEMENT, KIND_NEUTRAL
from dodaios.briefs import standing
from dodaios.briefs.model import Order
from dodaios.briefs.profiles import Profile

__all__ = ["MAX_QUOTE_CHARS", "assemble", "quote_of"]

#: A longer message of the person covers more than one order: it is not appended.
MAX_QUOTE_CHARS: Final[int] = 1_500
# The words were said to the assistant, often as "send an agent to ...". Read
# as an order, they made a coding agent start an agent of its own (a real run
# on 2026-11-22), so the head says whom they were said to and who that agent is.
_QUOTE_HEAD: Final[str] = (
    "For reference: what the person said to Dodaios, their assistant, word for word. Your "
    "order is the brief above, which Dodaios wrote from these words. Where they ask for an "
    "agent to be sent or started, that agent is you."
)
_BRIDGE: Final[str] = "Based on the context above:"
_ASKS_TO_VERIFY = re.compile(r"(?i)\b(?:verify|say what you checked|what you checked)\b")
_TRAILING_REFERENCE = re.compile(r"[@/][\w./\\-]*$")


def _squash(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def quote_of(order: Order) -> str:
    """The person's words as the block appended to a brief, ``""`` when none is added.

    Nothing is added when the words are unknown, too long to belong to one
    order, or already in the brief.
    """
    words = (order.person_words or "").strip()
    if not words or len(words) > MAX_QUOTE_CHARS:
        return ""
    if _squash(words) in _squash(order.draft.text()):
        return ""
    quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in words.splitlines())
    return f"{_QUOTE_HEAD}\n{quoted}"


def _body(order: Order, profile: Profile) -> str:
    draft = order.draft
    task, context, criteria = draft.task.strip(), draft.context.strip(), draft.criteria.strip()
    if profile.task_last and context:
        parts = ["Context:\n" + context, f"{_BRIDGE}\n{task}"]
    else:
        parts = [task]
        if context:
            parts.append("Context:\n" + context)
    if criteria:
        parts.append("Done when:\n" + criteria)
    return "\n\n".join(part for part in parts if part)


def assemble(
    order: Order,
    profile: Profile,
    *,
    kind: str = KIND_NEUTRAL,
    rules_in_message: bool = False,
) -> str:
    """The text sent to the agent for ``order``.

    ``kind`` is the kind of work (a closing line about verifying belongs to a
    change, not to a question); ``rules_in_message`` asks for the standing
    rules at the end, for a conversation that gets them no other way.
    """
    parts = [_body(order, profile)]
    quote = quote_of(order)
    if quote:
        parts.append(quote)
    if (
        profile.closing
        and kind in (KIND_IMPLEMENT, KIND_NEUTRAL)
        and not _ASKS_TO_VERIFY.search(parts[0][-600:])
    ):
        parts.append(profile.closing)
    if rules_in_message and not standing.has_rules(parts[0]):
        parts.append(standing.WORK_ORDER_RULES)
    text = "\n\n".join(part for part in parts if part.strip())
    if _TRAILING_REFERENCE.search(text.rstrip()):
        # A trailing file reference keeps a terminal CLI's completion popup open,
        # and the Enter that follows picks a suggestion instead of sending.
        text = text.rstrip() + "\n\nThat is the whole order."
    return text
