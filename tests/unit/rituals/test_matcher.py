"""Whether a sentence is a ritual's phrase: the phrase must carry the sentence."""

from __future__ import annotations

import pytest

from dodaios.rituals import matcher

WAKE = "Hey Nova"


@pytest.mark.parametrize(
    "said",
    [
        "Good morning",
        "good morning.",
        "Hey Nova, good morning!",
        "Good morning, Nova",
        "Okay, good morning please",
        "hey dodaios good morning",
        "Hey Jarvis, good morning",
    ],
)
def test_the_phrase_with_only_address_around_it_starts_the_ritual(said: str) -> None:
    assert matcher.says(said, "Good morning", wake_phrase=WAKE)


@pytest.mark.parametrize(
    "said",
    [
        "Good morning, how is the weather?",
        "I just wanted to say good morning",
        "morning",
        "good",
        "good evening",
        "",
        "Hey Nova",
    ],
)
def test_a_sentence_that_only_contains_the_phrase_starts_nothing(said: str) -> None:
    assert not matcher.says(said, "Good morning", wake_phrase=WAKE)


def test_accents_case_and_punctuation_do_not_matter() -> None:
    assert matcher.says("SCHÖNEN FEIERABEND!", "schönen Feierabend")  # i18n-allow: spoken input
    assert matcher.says("schonen feierabend", "Schönen Feierabend")  # i18n-allow: spoken input
    assert matcher.same_phrase("Good  Morning!", "good morning")
    assert not matcher.same_phrase("good morning", "good evening")


def test_the_assistants_name_is_compared_by_sound() -> None:
    # The recognizer spells a name in more than one way.
    assert matcher.says("Hey Nikko, focus time", "Focus time", wake_phrase="Hey Nico")
    assert matcher.says("Focus time, Niko", "Focus time", wake_phrase="Hey Nico")
    # Another name is not an address: the sentence is about somebody else.
    assert not matcher.says("Hey Maria, focus time", "Focus time", wake_phrase="Hey Nico")


def test_a_phrase_may_itself_begin_with_an_address_word() -> None:
    # "ok" is peeled as address only where it is not part of the phrase.
    assert matcher.says("ok go", "Ok go", wake_phrase=WAKE)
    assert matcher.says("Hey Nova, ok go", "Ok go", wake_phrase=WAKE)
    assert not matcher.says("go", "Ok go", wake_phrase=WAKE)


def test_what_makes_a_phrase_unusable() -> None:
    assert matcher.phrase_problem("Good morning", wake_phrase=WAKE) == ""
    assert "at least one word" in matcher.phrase_problem(" ?! ", wake_phrase=WAKE)
    assert "short" in matcher.phrase_problem("one two three four five six seven", wake_phrase=WAKE)
    assert "short" in matcher.phrase_problem("x" * 61, wake_phrase=WAKE)
    # The wake word, the name or a "please" alone would start it on anything said.
    for only_address in ("Hey Nova", "nova", "please", "hey"):
        assert "address" in matcher.phrase_problem(only_address, wake_phrase=WAKE)


@pytest.mark.parametrize(
    ("said", "phrase"),
    [
        ("What's up", "Whats up"),
        ("whats up", "What’s up"),
        ("Gruess Gott", "Grüß Gott"),  # i18n-allow: spoken-input vocabulary
        ("Gruss Gott", "Grüß Gott"),  # i18n-allow: spoken-input vocabulary
        ("Schoenen Tag", "Schönen Tag"),  # i18n-allow: spoken-input vocabulary
        ("Schönen Tag", "Schonen Tag"),  # i18n-allow: spoken-input vocabulary
        ("Guten Morgen, guten Morgen", "Guten Morgen"),  # i18n-allow: spoken-input vocabulary
        ("good morning good morning, Nova", "Good morning"),
    ],
)
def test_spellings_of_the_same_words_start_the_ritual(said: str, phrase: str) -> None:
    assert matcher.says(said, phrase, wake_phrase=WAKE)


def test_a_name_with_an_umlaut_is_address_in_either_spelling() -> None:
    spellings = ("Hey Jürgen, guten Morgen", "hey juergen guten morgen")  # i18n-allow: spoken input
    wake, phrase = "Hey Jürgen", "Guten Morgen"  # i18n-allow: spoken input
    for said in spellings:
        assert matcher.says(said, phrase, wake_phrase=wake)


def test_a_repeated_phrase_is_still_no_question() -> None:
    assert not matcher.says("good morning good morning how are you", "Good morning")
    assert matcher.same_phrase("What's up", "Whats up")
