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

from dodaios.core.redact import redact_secrets
from dodaios.speech.hangup import END_CALL_SIGNAL

__all__ = ["readable_text"]


def readable_text(text: str) -> str:
    """``text`` as the person reads it in a chat: words, links, code and lines kept.

    Only the hang-up marker of a call and anything shaped like a key or token
    are removed.
    """
    out = (text or "").replace(END_CALL_SIGNAL, "")
    return redact_secrets(out).strip()
