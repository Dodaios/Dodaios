"""Strip model markup out of a streamed answer before anyone sees or hears it.

Local reasoning models (Qwen, DeepSeek-R1 distills, Gemma-based coders) write
their chain of thought into the answer as ``<think>…</think>``, and a server
that does not parse tool calls returns them as ``<tool_call>{…}</tool_call>``
or ``[TOOL_CALLS][…]`` text. Left in the stream, the chat shows the reasoning,
TTS reads it aloud, and a tool call turns into an empty reply once the voice
scrubber removes the tag.

:class:`StreamMarkupFilter` is the single place this is handled for every
OpenAI-compatible transport. It is fed the raw ``delta.content`` chunks and
returns only the visible answer, while recovered tool calls (offered tools
only — see :func:`dodaios.brain.tool_call_recovery.extract_tagged_tool_calls`)
are collected for the transport to emit as structured calls.

It copes with tags split across chunks (a partial marker at the end of a chunk
is held back until the next one decides it), an unclosed ``<think>`` (hidden
to the end), and a stray ``</think>`` with no opener — some Qwen chat templates
put the opening tag into the PROMPT, so the reply starts mid-thought. The text
before such a closer is reasoning; once a model is seen doing this, its next
replies are held back until the closer (or the end) so nothing leaks.
"""

from __future__ import annotations

import logging
from typing import Any

from .tool_call_recovery import (
    MISTRAL_TOOL_CALLS,
    TOOL_CALL_CLOSE,
    TOOL_CALL_OPEN,
    extract_tagged_tool_calls,
)

log = logging.getLogger(__name__)

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"

_TEXT_MARKERS = (THINK_OPEN, THINK_CLOSE, TOOL_CALL_OPEN, MISTRAL_TOOL_CALLS)

#: How much of a reply from a model of unknown habit is held back while
#: waiting to see whether it opens with reasoning that ends in a bare
#: ``</think>``. Only local providers ask for this, and only until the model
#: has answered once without any think markup.
PREFIX_HOLD_CHARS = 1500

# (endpoint, model) -> "implicit" (reply starts inside a think block) or
# "plain". Process lifetime; a wrong "plain" is corrected by the next stray
# closer, a wrong "implicit" only costs streaming latency.
_THINK_HABIT: dict[tuple[str, str], str] = {}


def reset_think_habits() -> None:
    """Forget what was learned about models (tests)."""
    _THINK_HABIT.clear()


def _partial_marker_suffix(buffer: str, markers: tuple[str, ...]) -> int:
    """Length of the longest buffer suffix that could start one of ``markers``."""
    lowered = buffer.lower()
    longest = 0
    for marker in markers:
        marker = marker.lower()
        for size in range(min(len(marker) - 1, len(lowered)), 0, -1):
            if lowered.endswith(marker[:size]):
                longest = max(longest, size)
                break
    return longest


class StreamMarkupFilter:
    """Incremental filter: ``feed`` chunks, then ``finish``; read ``calls``."""

    def __init__(
        self,
        tools: Any = None,
        *,
        habit_key: tuple[str, str] | None = None,
        hold_unknown_prefix: bool = False,
    ) -> None:
        self._tools = tools
        self._habit_key = habit_key
        habit = _THINK_HABIT.get(habit_key) if habit_key else None
        # "prefix": the reply may begin inside a think block whose opener was
        # in the prompt. Held back until a closer, the end, or the bound.
        if habit == "implicit":
            self._state = "prefix"
            self._prefix_limit: int | None = None
        elif habit is None and hold_unknown_prefix:
            self._state = "prefix"
            self._prefix_limit = PREFIX_HOLD_CHARS
        else:
            self._state = "text"
            self._prefix_limit = None
        self._buffer = ""
        self._emitted_fences = 0
        self._strip_leading = False
        self._saw_think = False
        self._saw_stray_close = False
        self._emitted_any = False
        self.calls: list[dict[str, Any]] = []

    # -- public -----------------------------------------------------------

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        return self._drain(final=False)

    def finish(self) -> str:
        out = self._drain(final=True)
        self._learn()
        return out

    # -- internals --------------------------------------------------------

    def _emit(self, text: str) -> str:
        if self._strip_leading:
            text = text.lstrip()
            if not text:
                return ""
            self._strip_leading = False
        if text:
            self._emitted_fences += text.count("```")
            self._emitted_any = True
        return text

    def _in_fence(self, pending: str = "") -> bool:
        return (self._emitted_fences + pending.count("```")) % 2 == 1

    def _drain(self, *, final: bool) -> str:
        out: list[str] = []
        while True:
            progressed = getattr(self, f"_step_{self._state}")(out, final)
            if not progressed:
                break
        return "".join(out)

    def _step_prefix(self, out: list[str], final: bool) -> bool:
        lowered = self._buffer.lower()
        close = lowered.find(THINK_CLOSE)
        opener = lowered.find(THINK_OPEN)
        if opener != -1 and (close == -1 or opener < close):
            # An explicit opener after all: the normal think path handles it.
            self._state = "text"
            return True
        if close != -1:
            self._saw_think = True
            self._saw_stray_close = True
            self._buffer = self._buffer[close + len(THINK_CLOSE):]
            self._strip_leading = True
            self._state = "text"
            return True
        limit = self._prefix_limit
        if final or (limit is not None and len(self._buffer) > limit):
            # No closer: this reply did not start inside a think block.
            self._state = "text"
            return True
        return False

    def _step_text(self, out: list[str], final: bool) -> bool:
        lowered = self._buffer.lower()
        hits = [
            (index, marker)
            for marker in _TEXT_MARKERS
            if (index := lowered.find(marker.lower())) != -1
        ]
        if not hits:
            if final:
                out.append(self._emit(self._buffer))
                self._buffer = ""
                return False
            keep = _partial_marker_suffix(self._buffer, _TEXT_MARKERS)
            ready = self._buffer[: len(self._buffer) - keep] if keep else self._buffer
            out.append(self._emit(ready))
            self._buffer = self._buffer[len(ready):]
            return False
        index, marker = min(hits)
        before = self._buffer[:index]
        rest = self._buffer[index + len(marker):]
        tool_marker = marker in (TOOL_CALL_OPEN, MISTRAL_TOOL_CALLS)
        if tool_marker and self._in_fence(before):
            # Markup inside a code block is an example, not a call.
            out.append(self._emit(before + self._buffer[index: index + len(marker)]))
            self._buffer = rest
            return True
        out.append(self._emit(before))
        if marker == THINK_OPEN:
            self._saw_think = True
            self._buffer = rest
            self._state = "think"
        elif marker == THINK_CLOSE:
            # A closer with no opener: whatever reasoning preceded it was
            # already handed on (it could not be known as such); drop the tag
            # and remember the habit so the next reply is held back.
            self._saw_think = True
            self._saw_stray_close = True
            self._buffer = rest
            self._strip_leading = True
        elif marker == TOOL_CALL_OPEN:
            self._buffer = self._buffer[index:]
            self._state = "tool_tag"
        else:
            self._buffer = self._buffer[index:]
            self._state = "mistral"
        return True

    def _step_think(self, out: list[str], final: bool) -> bool:
        close = self._buffer.lower().find(THINK_CLOSE)
        if close == -1:
            if final:
                # Unclosed reasoning (cut off by the token limit): never shown.
                self._buffer = ""
                return False
            keep = _partial_marker_suffix(self._buffer, (THINK_CLOSE,))
            self._buffer = self._buffer[len(self._buffer) - keep:] if keep else ""
            return False
        self._buffer = self._buffer[close + len(THINK_CLOSE):]
        self._strip_leading = True
        self._state = "text"
        return True

    def _step_tool_tag(self, out: list[str], final: bool) -> bool:
        close = self._buffer.lower().find(TOOL_CALL_CLOSE)
        if close == -1 and not final:
            return False
        end = len(self._buffer) if close == -1 else close + len(TOOL_CALL_CLOSE)
        block = self._buffer[:end]
        self._buffer = self._buffer[end:]
        self._state = "text"
        calls, remaining = extract_tagged_tool_calls(block, self._tools)
        if calls:
            self.calls.extend(calls)
            self._strip_leading = True
        elif remaining == block:
            # Not a call at all (prose about the tag): keep it as text.
            out.append(self._emit(block))
        else:
            log.warning(
                "stream_markup: dropped a text tool call naming no offered tool"
            )
            self._strip_leading = True
        return True

    def _step_mistral(self, out: list[str], final: bool) -> bool:
        # ``[TOOL_CALLS]`` has no closing tag; it runs to the end of the reply.
        if not final:
            return False
        block = self._buffer
        self._buffer = ""
        self._state = "text"
        calls, remaining = extract_tagged_tool_calls(block, self._tools)
        self.calls.extend(calls)
        if remaining == block:
            out.append(self._emit(block))
        elif remaining:
            out.append(self._emit(remaining))
        elif not calls:
            log.warning(
                "stream_markup: dropped a text tool call naming no offered tool"
            )
        return False

    def _learn(self) -> None:
        if self._habit_key is None:
            return
        if self._saw_stray_close:
            if _THINK_HABIT.get(self._habit_key) != "implicit":
                log.info(
                    "stream_markup: %s starts its replies inside a think block; "
                    "holding its replies back until the reasoning ends.",
                    self._habit_key[1],
                )
            _THINK_HABIT[self._habit_key] = "implicit"
        elif self._habit_key not in _THINK_HABIT and (self._emitted_any or self._saw_think):
            _THINK_HABIT[self._habit_key] = "plain"


__all__ = [
    "PREFIX_HOLD_CHARS",
    "THINK_CLOSE",
    "THINK_OPEN",
    "StreamMarkupFilter",
    "reset_think_habits",
]
