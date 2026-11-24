"""The lines that ride beside every lead message, and which of them may be learned away.

The lead's message is the person's text with standing lines beside it
(``dodaios_harness.message_lines``): how much to think, the line before the
first tool, the reply's shape, how to brief an agent, where a question goes.
Each was added after a live incident, and each costs tokens on every message
and stays in the conversation.

A line may be switched off by a learner only when a benchmark can see what the
line does. A drop that the measurement cannot see would pass the gate as "as
good and cheaper" while the harm happens where nothing looks. So every line is
listed here with the domain that sees its effect, or with why none does; only
the ones with a domain have a switch (a ``bool`` parameter in the catalog,
default on).

=====================  ==================  ===========================================
line                   switch              why
=====================  ==================  ===========================================
``FIRST_LINE``         ``lead.first_line``  its effect is the first move: a short line
                                           before the first tool call (``first_move``
                                           scores it)
``EFFORT_LINE``        none                how long the model works; no first move shows
``REPLY_SHAPE_LINE``   none                the reply's shape and length
``BRIEF_LINE``         none                a brief's wording, and what the agent then does
``QUESTION_CARD_LINE`` none                a question that comes up later in the turn; the
                                           seed set's ask cases still expect text
``SECRET_FIELD_LINE``  none                only beside a message that names a secret; what
                                           it guards is the person's key, not a move
=====================  ==================  ===========================================

The kernel owns this list (``dodaios/rsi`` is a core path): no self-change can
make a line learnable. Adding a switch means adding a measurement first.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["LEARNABLE", "LINES", "StandingLine", "apply", "is_switch", "switches"]


def _harness(name: str) -> Callable[[], str]:
    def text() -> str:
        from dodaios.agent_chat import dodaios_harness

        return str(getattr(dodaios_harness, name))

    return text


@dataclass(frozen=True, slots=True)
class StandingLine:
    #: The constant in ``dodaios_harness``.
    name: str
    #: The ``bool`` parameter that switches it ("" when it cannot be switched).
    param: str
    #: The benchmark domain that sees its effect ("" when none does).
    domain: str
    #: Why it is, or is not, learnable. Read by people, kept beside the switch.
    why: str
    #: The line before which this one stands when it is put back into a message
    #: that lacks it (its successor in ``message_lines``).
    before: str = ""

    def text(self) -> str:
        return _harness(self.name)()


LINES: Final[tuple[StandingLine, ...]] = (
    StandingLine(
        "FIRST_LINE",
        "lead.first_line",
        "first_move",
        "Its effect is the first move itself: a short line that takes the task on before the "
        "first tool call. The first_move check scores that line.",
        before="REPLY_SHAPE_LINE",
    ),
    StandingLine(
        "EFFORT_LINE",
        "",
        "",
        "It says how long the model may work. No first move shows that.",
    ),
    StandingLine(
        "REPLY_SHAPE_LINE",
        "",
        "",
        "It shapes the reply (length, headings, lists). The first move does not show it.",
    ),
    StandingLine(
        "BRIEF_LINE",
        "",
        "",
        "It shapes a brief's wording and the agent's work after it; the first move shows "
        "only that delegate was called.",
    ),
    StandingLine(
        "QUESTION_CARD_LINE",
        "",
        "",
        "It also covers a question that comes up later in the turn, which no first move "
        "shows; and the seed set's ask cases still expect a question in text.",
    ),
    StandingLine(
        "SECRET_FIELD_LINE",
        "",
        "",
        "It rides only beside a message that names a secret and guards the person's key; "
        "the harm of losing it is a leaked key, not a wrong move.",
    ),
)

#: The lines a learner may switch off, by parameter name.
LEARNABLE: Final[Mapping[str, StandingLine]] = {line.param: line for line in LINES if line.param}


def is_switch(param: str) -> bool:
    """True when ``param`` switches a standing line."""
    return param in LEARNABLE


def switches(values: Mapping[str, Any] | None = None) -> dict[str, bool]:
    """Every switch with its value in effect (the active overlay's, inside a benchmark run)."""
    from dodaios.rsi import params

    if values is not None:
        return {name: bool(values.get(name, True)) for name in LEARNABLE}
    return {name: bool(params.get(name)) for name in LEARNABLE}


def apply(message: str, on: Mapping[str, bool]) -> str | None:
    """A recorded lead message with each switched line taken out or put back.

    A line that is off and in the message is taken out. A line that is on and
    missing is put back where ``message_lines`` puts it: in front of the line it
    stands before. ``None`` when a line has to be put back and its place is not
    in the message (a message without the lines at all: a slash command, a turn
    that carried a running task on, a message from before the lines existed).
    """
    out = message
    for name, line in LEARNABLE.items():
        text = line.text()
        wanted = bool(on.get(name, True))
        if not wanted and text in out:
            out = out.replace(text, "", 1)
        elif wanted and text not in out:
            anchor = _harness(line.before)() if line.before else ""
            if not anchor or anchor not in out:
                return None
            out = out.replace(anchor, text + anchor, 1)
    return out
