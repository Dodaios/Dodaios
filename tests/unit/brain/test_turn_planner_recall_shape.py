"""Recall-shaped openers read as lookups, not orders.

The recall pattern once held literal backspace characters where word
boundaries belonged, so it never matched and a spoken "do you remember ..."
(no question mark in speech) was treated as an order to save something.
"""

from __future__ import annotations

import pytest

from dodaios.brain.turn_planner import _RECALL_QUESTION_RE, is_lookup_shape


def test_recall_pattern_holds_no_control_characters() -> None:
    assert not any(ord(char) < 32 for char in _RECALL_QUESTION_RE.pattern)


@pytest.mark.parametrize(
    "utterance",
    [
        "do you remember my sister",
        "do you recall the meeting",
        "erinnerst du dich an gestern",  # i18n-allow: German speech-input fixture
        "kennst du den film noch",  # i18n-allow: German speech-input fixture
        "te acuerdas de mi hermana",  # i18n-allow: Spanish speech-input fixture
    ],
)
def test_recall_openers_are_lookup_shaped(utterance: str) -> None:
    assert is_lookup_shape(utterance)


@pytest.mark.parametrize(
    "utterance",
    [
        "save my notes",
        "remember that my sister is called Anna",
        "sabeston",
    ],
)
def test_orders_and_word_fragments_are_not_recall_questions(utterance: str) -> None:
    assert not _RECALL_QUESTION_RE.search(utterance)
