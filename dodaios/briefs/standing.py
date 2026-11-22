"""What holds for every work order, told to a coding agent once.

Twenty of twenty-four real briefs ended on the same sentence about how to
report, and none said that nobody is watching the run. Things that hold for
every order do not belong in each brief: they are the agent's standing rules,
and it gets them once per conversation.

* A thread that an agent opened (the lead, a society agent) on a CLI with a
  system prompt has them there, on every turn, as one constant text.
* The same thread on a CLI without one gets them in front of the first message
  of each vendor conversation (also after a lost resume, when the CLI
  remembers nothing).
* A thread or pane the person opened gets them with the first order Dodaios
  sends into it (``dodaios.briefs.assemble``).

The rules say what the vendors' guides ask a harness to say for unattended
work: nobody is watching, the order sets the scope, an announced step is not a
done step, a claim rests on a result from this session, and the report is for
a reader who saw none of the work. They end on the case that keeps them true
when the person takes over: someone who writes in the thread is present.

The text travels on a command line. Behind a Windows ``.cmd`` shim that line
is read by ``cmd.exe``: a line break ends it and a percent sign or a double
quote changes it. So it is one paragraph without any of them, and a test holds
it to that.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "MARK",
    "WORK_ORDER_RULES",
    "for_first_message",
    "has_rules",
    "opened_by_agent",
    "tell_claude_code",
]

#: The words the rules open with; also how their presence in a text is recognised.
MARK: Final[str] = "Work orders:"

WORK_ORDER_RULES: Final[str] = (
    f"{MARK} this conversation takes work orders from Dodaios, the person's assistant, "
    "written on the person's behalf. While you work on one, the person is not watching and "
    "cannot answer mid-task: take the reversible steps that follow from the order without "
    "asking, and stop only for an irreversible step, a real change of scope, or something "
    "only the person can provide. The order sets the scope: do not quietly narrow, widen or "
    "swap it, and put anything else worth doing into your report as a suggestion. Do not "
    "end a turn on a plan, a list of next steps or an offer to continue; do that work, and "
    "work through ordinary obstacles such as an error, a timeout or a failing tool. You can "
    "ask: when a question truly blocks the work, or the order tells you to ask first, put "
    "it once through your question tool or question block and say what you already ruled "
    "out. The answer arrives in this conversation: Dodaios answers what it can and passes "
    "the rest to the person. Before you call "
    "something done, check it against a result from this session. Report for a reader who "
    "saw none of your work: the outcome first, then for each done-when point of the order "
    "the check you ran and what it showed, then what is open and any decision the person "
    "has to make, in plain full sentences. When the person writes here themselves, they "
    "are present: answer them directly."
)

#: Claude Code's flag for text added to its system prompt.
_APPEND_FLAG: Final[str] = "--append-system-prompt"


def opened_by_agent(handle: Any) -> str:
    """The id of the agent that opened a turn's thread, ``""`` when the person did."""
    return str(getattr(handle, "opened_by", "") or "")


def has_rules(text: str) -> bool:
    """Whether a text already carries the standing rules."""
    return MARK in (text or "")


def tell_claude_code(argv: list[str], handle: Any) -> None:
    """Add the rules to the system prompt of a thread an agent opened, in place.

    The planner may already append text; the rules join it, since the flag
    counts once. A turn whose prompt comes from a file (an assistant's
    identity) is no coding thread and is left alone. The text depends only on
    who opened the thread, so it is the same on every turn of it.
    """
    if not opened_by_agent(handle) or "--append-system-prompt-file" in argv:
        return
    if _APPEND_FLAG in argv:
        at = argv.index(_APPEND_FLAG) + 1
        if at < len(argv) and not has_rules(argv[at]):
            argv[at] = f"{argv[at]} {WORK_ORDER_RULES}"
        return
    argv += [_APPEND_FLAG, WORK_ORDER_RULES]


def for_first_message(user_text: str, handle: Any, *, new_conversation: bool) -> str:
    """``user_text`` with the rules in front, for a CLI that has no system prompt.

    Only at the start of a vendor conversation of a thread an agent opened;
    a slash command and a text that already carries the rules stay as they are.
    """
    if (
        not new_conversation
        or not opened_by_agent(handle)
        or user_text.lstrip().startswith("/")
        or has_rules(user_text)
    ):
        return user_text
    return f"{WORK_ORDER_RULES}\n\n{user_text}"
