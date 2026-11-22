"""``/clear`` in a coding thread: the conversation starts over.

In a terminal, ``/clear`` empties the screen and the agent's context. A thread
ran the command as a turn of the CLI instead: Claude Code answered with a new,
empty conversation under a new id, the thread went on resuming the old one,
and everything stayed on screen. Nothing was cleared (measured 2026-11-22: the
next message still knew a word from before the ``/clear``).

Here the thread does it itself, the same way for every coding agent:

* a ``conversation_cleared`` event marks where the conversation starts over.
  The store's readers begin at it, so the thread shows empty and no report,
  search or hand-over reads what came before. The earlier events stay stored;
* the session forgets its CLI conversation, so the next message opens a new
  one with an empty context;
* a name after the command (``/clear login bug``, as Claude Code offers it)
  becomes the thread's title. Without one, a title the first message gave goes
  with it and the next first message names the thread.

No turn runs for it and no message is written. While the agent works the
command waits like any other message typed then, and clears once the turn is
over; it is never typed into the running turn.

This module says what counts as the command; ``AgentChatService.send`` takes
it out of the messages and ``AgentChatService.clear_conversation`` clears.
"""

from __future__ import annotations

import re
from typing import Any, Final

__all__ = ["CLEAR_COMMANDS", "clear_name", "is_clear_command", "wants_clear"]

#: The command and the names Claude Code lists for it (its ``aliases``).
CLEAR_COMMANDS: Final[frozenset[str]] = frozenset({"clear", "reset", "new"})
#: The longest thread title a name after the command gives (as long as a rename allows).
_NAME_MAX_CHARS: Final[int] = 120

_COMMAND: Final[re.Pattern[str]] = re.compile(r"^\s*/([a-z]+)(?:\s+(.*))?$", re.DOTALL)


def clear_name(text: str) -> str | None:
    """The name given after a clear command, ``""`` for none; ``None`` when ``text`` is no clear."""
    match = _COMMAND.match(text or "")
    if match is None or match[1] not in CLEAR_COMMANDS:
        return None
    return " ".join((match[2] or "").split())[:_NAME_MAX_CHARS]


def is_clear_command(text: str) -> bool:
    """Whether a message is ``/clear`` (or ``/reset`` / ``/new``), with or without a name."""
    return clear_name(text) is not None


def wants_clear(session: Any, text: str, attachments: Any = None) -> bool:
    """Whether this message clears the thread it is sent to.

    Only a coding thread, and only the bare command: a message with files is a
    message, whatever its first word.
    """
    return (
        getattr(session, "surface", "") == "agent"
        and not attachments
        and is_clear_command(text)
    )

