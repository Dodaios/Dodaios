"""The shared TTS sentence splitter splits exactly like the pattern it replaced, in linear time."""

from __future__ import annotations

import random
import re
import time

from dodaios.plugins.tts.sentences import split_sentences

# The pattern each streaming TTS plugin used until 2026-11-18.
_OLD = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÄÖÜ])")  # i18n-allow: German capitals


def _old_split(text: str) -> list[str]:
    return [part.strip() for part in _OLD.split(text) if part.strip()]


def test_splits_at_a_mark_space_and_capital() -> None:
    text = "Hello there. How are you? Fine!  Über alles… Ja."  # i18n-allow
    assert split_sentences(text) == [
        "Hello there.", "How are you?", "Fine!", "Über alles…", "Ja.",  # i18n-allow
    ]


def test_keeps_abbreviations_and_lowercase_together() -> None:
    text = "See e.g. the docs. version 2.1 is out"
    assert split_sentences(text) == [text]


def test_matches_the_old_pattern_on_random_text() -> None:
    rng = random.Random(1118)  # noqa: S311 - test data, not crypto
    alphabet = ["a", "B", "Ä", "z", ".", "!", "?", "…",  # i18n-allow
                " ", "  ", "\n", "\t", "x", "Q"]
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        assert split_sentences(text) == _old_split(text), repr(text)


def test_long_whitespace_runs_stay_fast() -> None:
    text = "a." + " " * 200_000 + "b"
    started = time.perf_counter()
    assert split_sentences(text) == [text.strip()]
    assert time.perf_counter() - started < 1.0
