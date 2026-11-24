"""The lines that ride beside every lead message, and which of them may be learned.

The lead's message is the person's text with standing lines beside it
(``dodaios_harness.message_lines``): how much to think, the line before the
first tool, the reply's shape, how to brief an agent, where a question goes.
Each was added after a live incident, and each costs tokens on every message
and stays in the conversation.

A line may be changed by a learner only where a benchmark can see what the
change does. A change that the measurement cannot see would pass the gate as
"as good and cheaper" while the harm happens where nothing looks. So every line
is listed here with the domain that sees its effect, or with why none does;
only the ones with a domain have a parameter in the catalog. A line has one of
two kinds of parameter:

* a **switch** (``bool``, default on): the line is in the message or not;
* a **wording** (``int``, default 0): which of a few fixed texts written in
  ``dodaios_harness`` stands in the message. Never text a model wrote.

=====================  ===================  ==========================================
line                   parameter            why
=====================  ===================  ==========================================
``FIRST_LINE``         ``lead.first_line``  its effect is the first move: a short line
                       (switch)             before the first tool call (``first_move``
                                            scores it)
``BRIEF_LINE``         ``lead.brief_line``  the wordings differ only in the look-up
                       (wording)            before the brief, whose effect is the files
                                            the brief names and its length (``brief``
                                            scores both). The rest of the line (the
                                            outcome first, a checkable done, the git
                                            default, the real limits) is the same in
                                            every wording: no domain sees it, so the
                                            whole line can never be switched off
``EFFORT_LINE``        none                 how long the model works; no first move shows
``REPLY_SHAPE_LINE``   none                 the reply's shape and length
``QUESTION_CARD_LINE`` none                 a question that comes up later in the turn;
                                            the seed set's ask cases still expect text
``SECRET_FIELD_LINE``  none                 only beside a message that names a secret;
                                            what it guards is the person's key, not a move
=====================  ===================  ==========================================

The kernel owns this list (``dodaios/rsi`` is a core path): no self-change can
make a line learnable. Adding a parameter means adding a measurement first.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "LEARNABLE",
    "LINES",
    "StandingLine",
    "alternatives",
    "apply",
    "is_switch",
    "switches",
]


def _harness(name: str) -> Callable[[], str]:
    def text() -> str:
        from dodaios.agent_chat import dodaios_harness

        return str(getattr(dodaios_harness, name))

    return text


@dataclass(frozen=True, slots=True)
class StandingLine:
    #: The constant in ``dodaios_harness``.
    name: str
    #: The parameter that changes it ("" when it cannot be changed).
    param: str
    #: The benchmark domain that sees its effect ("" when none does).
    domain: str
    #: Why it is, or is not, learnable. Read by people, kept beside the parameter.
    why: str
    #: The line before which this one stands when it is put back into a message
    #: that lacks it (its successor in ``message_lines``). For a switch.
    before: str = ""
    #: The constants of the fixed wordings, by the parameter's value; ``()`` for a
    #: switch. The first is the line the app ships with.
    wordings: tuple[str, ...] = ()

    def text(self) -> str:
        return _harness(self.name)()

    def texts(self) -> tuple[str, ...]:
        """The wordings' texts, by value."""
        return tuple(_harness(name)() for name in self.wordings)


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
        "BRIEF_LINE",
        "lead.brief_line",
        "brief",
        "Its wordings differ only in the look-up before the brief (asked for, asked for in "
        "fewer words, not asked for). Its effect is the files the brief names and how long "
        "the brief is, which the brief check scores. The rest of the line (the outcome first, "
        "a done the agent can check, the git default, the real limits) is the same in every "
        "wording because nothing measures it; for that reason the line is never dropped "
        "whole.",
        wordings=("BRIEF_LINE", "BRIEF_LINE_SHORT_LOOK", "BRIEF_LINE_NO_LOOK"),
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

#: The lines a learner may change, by parameter name.
LEARNABLE: Final[Mapping[str, StandingLine]] = {line.param: line for line in LINES if line.param}


def is_switch(param: str) -> bool:
    """True when ``param`` changes a standing line (a switch or a wording)."""
    return param in LEARNABLE


def _default(param: str) -> Any:
    from dodaios.rsi import params

    return params.INDEX.by_name(param).default


def switches(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Every line parameter with its value in effect (the active overlay's, in a benchmark run)."""
    from dodaios.rsi import params

    if values is not None:
        return {name: values.get(name, _default(name)) for name in LEARNABLE}
    return {name: params.get(name) for name in LEARNABLE}


def alternatives(param: str, current: Any) -> list[Any]:
    """What a learner may try instead of ``current``: a drop, or another wording.

    Only away from what ships: putting a line back, or the shipped wording, is
    what an undo or the gate's own check of a change in effect does.
    """
    line = LEARNABLE[param]
    if not line.wordings:
        return [False] if bool(current) else []
    shipped = _default(param)
    return [value for value in range(len(line.wordings)) if value not in (current, shipped)]


def _wording(line: StandingLine, value: Any) -> int:
    try:
        index = int(value)
    except (TypeError, ValueError):  # an unreadable value is the shipped wording
        return 0
    return index if 0 <= index < len(line.wordings) else 0


def apply(message: str, on: Mapping[str, Any]) -> str | None:
    """A recorded lead message with each line parameter's value applied.

    A switch that is off takes its line out; one that is on puts a missing line
    back where ``message_lines`` puts it: in front of the line it stands before.
    A wording replaces whichever of the line's wordings the message holds. ``None``
    when a line has to be put back or worded and its place is not in the message
    (a message without the lines at all: a slash command, a turn that carried a
    running task on, a message from before the lines existed).
    """
    out = message
    for name, line in LEARNABLE.items():
        wanted = on.get(name, _default(name))
        if line.wordings:
            texts = line.texts()
            want = texts[_wording(line, wanted)]
            present = next((text for text in texts if text in out), None)
            if present is None:
                if want == texts[0]:
                    continue  # nothing to change: the message stays as recorded
                return None
            out = out.replace(present, want, 1)
            continue
        text = line.text()
        if not bool(wanted) and text in out:
            out = out.replace(text, "", 1)
        elif bool(wanted) and text not in out:
            anchor = _harness(line.before)() if line.before else ""
            if not anchor or anchor not in out:
                return None
            out = out.replace(anchor, text + anchor, 1)
    return out
