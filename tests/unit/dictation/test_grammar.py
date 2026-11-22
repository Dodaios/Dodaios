"""A full stop ends a sentence only when the sentence is finished.

A recognizer writes a full stop wherever the speaker stops for a while, also
in the middle of a sentence. These rules tell such a stop from a real end by
German and English grammar: a word no sentence ends with, a German clause
still waiting for its verb, and a "sentence" that only carries on the one
before.
"""

from __future__ import annotations

import pytest

from dodaios.dictation.grammar import (
    continues_previous,
    joinable_tail,
    lowered_tail_start,
    unfinished,
)

# --------------------------------------------------------------------------
# Unfinished sentences
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "reason"),
    [
        ("Ich glaube, dass diese Absätze nicht wirklich sinnvoll.", "open_clause"),  # i18n-allow
        ("Wir haben Dateien, in denen wir dieses.", "open_clause"),  # i18n-allow
        ("Ich habe gesehen, dass noch irgendwelche Notizen.", "open_clause"),  # i18n-allow
        ("Es kommt darauf an, ob wir bis 2026.", "open_clause"),  # i18n-allow
        ("Wenn wir das so.", "open_clause"),  # i18n-allow
        ("Wir nehmen die rote und.", "dangling"),  # i18n-allow
        ("Wir treffen uns morgen zum.", "dangling"),  # i18n-allow
        ("Das ist besser als.", "dangling"),  # i18n-allow
    ],
)
def test_a_german_sentence_that_is_not_finished(sentence: str, reason: str) -> None:
    assert unfinished(sentence, language="de") == reason


@pytest.mark.parametrize(
    "sentence",
    [
        "Ich glaube, dass diese Absätze sinnvoll entstehen.",  # i18n-allow
        "Wir haben Dateien, in denen wir dieses Muster nutzen.",  # i18n-allow
        "Ich rufe dich morgen an.",  # a verb particle ends it  # i18n-allow
        "Mach bitte die Tür zu.",  # i18n-allow
        "Ich weiß nicht, wie.",  # i18n-allow
        "Das passt, weil das ist einfach besser.",  # verb second, as spoken  # i18n-allow
        "Wir prüfen, ob es klappt.",  # i18n-allow
        "Ich habe gesehen, was du gebaut hast.",  # i18n-allow
        "Er war schon da, als ich kam.",  # i18n-allow
        "Ich mag das.",  # i18n-allow
        "Ist das fertig?",  # a question mark is meant  # i18n-allow
        "Wir haben zwei Probleme, die Absätze und die Liste.",  # i18n-allow
        "Wir haben das Problem, das wir kennen.",  # i18n-allow
    ],
)
def test_a_finished_german_sentence(sentence: str) -> None:
    assert unfinished(sentence, language="de") == ""


@pytest.mark.parametrize(
    "sentence",
    ["We went to the.", "I want this because.", "It is bigger than.", "This is my.", "Red and."],
)
def test_an_english_sentence_that_is_not_finished(sentence: str) -> None:
    assert unfinished(sentence, language="en") == "dangling"


@pytest.mark.parametrize(
    "sentence",
    [
        "That is what I am afraid of.",
        "Come in.",
        "I like that.",
        "It is fine, though.",
        "Yes I am.",
        "Who are you going with.",
    ],
)
def test_a_finished_english_sentence(sentence: str) -> None:
    assert unfinished(sentence, language="en") == ""


def test_without_a_language_only_words_that_end_nothing_anywhere_count() -> None:
    assert unfinished("We went to the.", language=None) == "dangling"
    assert unfinished("Wir nehmen die rote und.", language=None) == "dangling"  # i18n-allow
    # German alone knows that this clause still waits for its verb.
    assert unfinished("Ich glaube, dass das nicht sinnvoll.", language=None) == ""  # i18n-allow
    # "an" ends a German sentence ("ich rufe an"), so it counts in English only.
    assert unfinished("I want an.", language=None) == ""
    assert unfinished("I want an.", language="en") == "dangling"


# --------------------------------------------------------------------------
# Sentences that only carry on the one before
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "reason"),
    [
        ("Entstehen.", "fragment"),  # i18n-allow
        ("Dann steht.", "fragment"),  # i18n-allow
        ("welche wir entfernen können.", "lower_case"),  # i18n-allow
        ("Welche wir entfernen können, welche nicht.", "clause_only"),  # i18n-allow
        ("Weil es schneller geht.", "clause_only"),  # i18n-allow
        ("Wobei das eigentlich egal ist.", "clause_only"),  # i18n-allow
    ],
)
def test_a_german_sentence_that_carries_on_the_one_before(sentence: str, reason: str) -> None:
    assert continues_previous(sentence, language="de") == reason


@pytest.mark.parametrize(
    "sentence",
    [
        "Danke dir.",  # i18n-allow
        "Viele Grüße.",  # i18n-allow
        "Zweitens.",  # i18n-allow
        "Genau.",  # i18n-allow
        "Welche Datei meinst du?",  # i18n-allow
        "Weil es schneller geht, nehmen wir das.",  # i18n-allow
        "Denen habe ich es schon gesagt.",  # i18n-allow
        "Das ist der nächste Punkt.",  # i18n-allow
    ],
)
def test_a_german_sentence_of_its_own(sentence: str) -> None:
    assert continues_previous(sentence, language="de") == ""


@pytest.mark.parametrize(
    ("sentence", "reason"),
    [
        ("Which we can remove.", "clause_only"),
        ("Because it is faster.", "clause_only"),
        ("and then it stops.", "lower_case"),
        ("Remove them.", "fragment"),
    ],
)
def test_an_english_sentence_that_carries_on_the_one_before(sentence: str, reason: str) -> None:
    assert continues_previous(sentence, language="en") == reason


@pytest.mark.parametrize(
    "sentence",
    ["Thanks a lot.", "Exactly.", "Which one do you mean?", "Because it is faster, we keep it."],
)
def test_an_english_sentence_of_its_own(sentence: str) -> None:
    assert continues_previous(sentence, language="en") == ""


# --------------------------------------------------------------------------
# Putting a split sentence back together
# --------------------------------------------------------------------------


def test_the_verb_that_closes_a_german_clause_joins_it_in_lower_case() -> None:
    before = "Ich glaube, dass diese Absätze nicht wirklich sinnvoll."  # i18n-allow
    after = "Entstehen."  # i18n-allow

    assert joinable_tail(before, after, language="de")
    assert lowered_tail_start(before, after, language="de")


def test_a_noun_after_an_article_keeps_its_capital() -> None:
    before = "Wir haben eine Liste, in denen wir dieses."  # i18n-allow
    after = "Muster nutzen."  # i18n-allow

    assert joinable_tail(before, after, language="de")
    assert not lowered_tail_start(before, after, language="de")


def test_a_function_word_loses_the_capital_the_pause_gave_it() -> None:
    before = "Wir nehmen die rote und."  # i18n-allow
    after = "Dann die blaue."  # i18n-allow

    assert joinable_tail(before, after, language="de")
    assert lowered_tail_start(before, after, language="de")


@pytest.mark.parametrize(
    ("before", "after", "language"),
    [
        ("Ich wollte noch sagen, dass.", "Ach, egal.", "de"),  # given up  # i18n-allow
        ("I went to the.", "The store was closed.", "en"),  # a new start, not a tail
        ("Das ist gut.", "Sehr gut.", "de"),  # finished before the pause  # i18n-allow
        ("Wir treffen uns, wenn wir das.", "Wirklich?", "de"),  # i18n-allow
    ],
)
def test_two_sentences_that_are_not_one(before: str, after: str, language: str) -> None:
    assert not joinable_tail(before, after, language=language)
