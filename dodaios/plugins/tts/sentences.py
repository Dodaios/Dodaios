"""Sentence splitting shared by the streaming TTS plugins.

A sentence ends at ``.``, ``!``, ``?`` or ``…`` followed by whitespace and a
capital letter (ASCII or a German umlaut). Until 2026-11-18 each plugin split
with a lookbehind/lookahead pattern around ``\\s+``; it backtracks over long runs of
whitespace (polynomial time), which mattered once any text could reach it
(the read-aloud route). This walks each whitespace run once and splits the
same way.

The split stays this narrow on purpose (2026-04-24): semicolons, colons and
newlines as boundaries fragmented the text so much that the SAPI5 fallback
fired more often, and its different sample rate (22050 vs 24000) forced
mid-stream resample flushes that crackled.
"""

from __future__ import annotations

import re

# A sentence mark and the whitespace after it. The `\s+` always succeeds
# greedily, so matching is linear; the capital that must follow is checked in code.
_MARK_THEN_SPACE = re.compile(r"[.!?…](\s+)")
# i18n-allow: German capitals start a sentence too
_CAPITALS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜ")  # i18n-allow


def split_sentences(text: str) -> list[str]:
    """The sentences of *text*, stripped, empty ones dropped."""
    parts: list[str] = []
    start = 0
    for match in _MARK_THEN_SPACE.finditer(text):
        after = match.end(1)
        if after < len(text) and text[after] in _CAPITALS:
            parts.append(text[start : match.start(1)])
            start = after
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]
