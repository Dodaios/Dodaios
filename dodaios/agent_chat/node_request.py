"""A new node asked for from the chat, with the type chip in front.

"New" in the Nodes library opens the lead conversation with a chip that names
the type ("Dodaios Slides") in front of the composer. The composer sends the
chip as one first line, ``[node: slides]``, and the person's description after
it. That line is what the bubble draws as the chip again, so it stays in what
the timeline shows (``typed``); the turn receives an explicit request instead,
so the type never depends on the model reading a bracket.
"""

from __future__ import annotations

import re
from typing import Final

from dodaios.nodes.types import DISPLAY_NAMES, NODE_TYPES

#: The chip line: the first line of the message, nothing else on it.
_CHIP_LINE: Final[re.Pattern[str]] = re.compile(r"\A\[node:\s*([a-z]+)\]\s*(?:\n|\Z)")


def split_node_request(text: str) -> tuple[str, str] | None:
    """``(type, description)`` when ``text`` starts with a known chip line."""
    match = _CHIP_LINE.match(text.lstrip())
    if match is None or match[1] not in NODE_TYPES:
        return None
    return match[1], text.lstrip()[match.end() :].strip()


def expand_node_request(text: str) -> str | None:
    """The request the turn receives for a chip message, or ``None`` for any other text."""
    parts = split_node_request(text)
    if parts is None:
        return None
    kind, description = parts
    name = DISPLAY_NAMES[kind]
    return (
        f'The person chose "New {name}" in the Nodes library and asks you to build a new '
        f'{name} node (node tool, type "{kind}") from the description below. Make exactly '
        "one node of this type, in the language of the description, and work it through "
        "the way the type's guide says.\n\n"
        f"Description: {description}"
    )
