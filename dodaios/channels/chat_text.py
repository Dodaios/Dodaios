"""The text a chat message carries: read on a screen, never spoken.

The speech filter (``brain.output_filter.scrub_for_voice``) prepares words
for a voice: it drops links ("the website"), code blocks, list marks and
stack traces, and squeezes lines together. A chat message is read, so that
filter must not touch it: an approval would show a different command than
the one that runs, and a reply would lose its links.

What a chat message still needs: the call's hang-up marker never shows, and
no key or token ever leaves the computer in it (``core.redact``).
"""

from __future__ import annotations

import html

from dodaios.core.redact import redact_secrets
from dodaios.speech.hangup import END_CALL_SIGNAL

__all__ = ["readable_text", "telegram_html", "without_fences"]

#: The line that opens and closes a code block in an approval's text.
_FENCE = "```"
_NL = "\n"


def readable_text(text: str) -> str:
    """``text`` as the person reads it in a chat: words, links, code and lines kept.

    Only the hang-up marker of a call and anything shaped like a key or token
    are removed.
    """
    out = (text or "").replace(END_CALL_SIGNAL, "")
    return redact_secrets(out).strip()


def telegram_html(text: str) -> str:
    """``text`` for Telegram's HTML parse mode: escaped, each fenced block as ``<pre>``.

    Only ``&``, ``<`` and ``>`` are escaped, so the command inside a block is
    the very command that runs. A block left open runs to the end.
    """
    out: list[str] = []
    block: list[str] | None = None
    for line in (text or "").split(_NL):
        if line.strip() == _FENCE:
            if block is None:
                block = []
            else:
                out.append(_pre(block))
                block = None
        elif block is not None:
            block.append(line)
        else:
            out.append(html.escape(line, quote=False))
    if block is not None:
        out.append(_pre(block))
    return _NL.join(out)


def without_fences(text: str) -> str:
    """``text`` with the fence lines of its code blocks left out (plain text)."""
    return _NL.join(line for line in (text or "").split(_NL) if line.strip() != _FENCE)


def _pre(lines: list[str]) -> str:
    return "<pre>" + html.escape(_NL.join(lines), quote=False) + "</pre>"
