"""The "[used tool NAME]" history marker, and the model text that imitates it.

The chat replays earlier tool calls to the model as one prose line per call,
``[used tool search_web: ...]`` (``agent_chat.runner_brain``). A small model
reads that line as part of how the assistant talks and starts writing it itself
instead of calling the tool. Live 2026-10-28 on the BC-250: after one real search,
every later Qwen3 1.7B answer opened with "[used tool search_web]" while no tool
ran, and the text after it was invented. Each invented answer was then replayed
as history and taught the next turn the same habit.

A marker is only ever produced by the replay code from a real ``tool_use``
block. A marker found inside model TEXT is therefore always an imitation.
"""

from __future__ import annotations

import re

#: A marker opening a line, as the replay writes it or as a model copies it:
#: "[used tool search_web]" or "[used tool search_web: query]". Text that
#: follows on the same line is kept.
_MARKER_LINE_RE = re.compile(
    r"^[ \t]*\[used tool ([A-Za-z0-9_.:-]+)(?::[^\]\n]*)?\][ \t]*\n?",
    re.MULTILINE,
)


def strip_tool_markers(text: str) -> tuple[str, tuple[str, ...]]:
    """Remove marker lines from ``text``; return the rest and the tool names."""
    if not text or "[used tool" not in text:
        return text, ()
    names = tuple(match.group(1) for match in _MARKER_LINE_RE.finditer(text))
    if not names:
        return text, ()
    cleaned = _MARKER_LINE_RE.sub("", text).strip()
    return cleaned, names


__all__ = ["strip_tool_markers"]
