"""The rules that turn what a recognizer heard into the delivered dictation.

A dictation is the speaker's own words, so these tests pin two things at once:
what the rules change (pause marks, spoken layout commands, hesitation sounds,
the punctuation seams those leave) and what they must leave alone (every other
word, numbers, abbreviations, a phrase that is only talked about).
"""
from __future__ import annotations

import pytest

from dodaios.dictation import formatting
from dodaios.dictation.formatting import (
    LINE_COMMANDS,
    PARAGRAPH_COMMANDS,
    FormatResult,
    apply_layout_commands,
    format_dictation,
    remove_fillers,
    strip_pause_marks,
    tidy_punctuation,
)

# --------------------------------------------------------------------------
# Pause marks
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Ich glaube ... das passt.",  # i18n-allow: German dictation under test
        "Ich glaube… das passt.",  # i18n-allow: German dictation under test
        "Ich glaube . . . das passt.",  # i18n-allow: German dictation under test
        "Ich glaube.. das passt.",  # i18n-allow: German dictation under test
        "Ich glaube...das passt.",  # i18n-allow: German dictation under test
    ],
)
def test_a_pause_inside_a_sentence_becomes_a_space(text: str) -> None:
    """Every spelling of a hesitation before a lower-case word is one space."""
    result = format_dictation(text, language="de")

    assert result.text == "Ich glaube das passt."  # i18n-allow: German dictation under test
    assert result.pause_marks == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Das ist gut... Dann machen wir weiter.",  # i18n-allow: German dictation under test
            "Das ist gut. Dann machen wir weiter.",  # i18n-allow: German dictation under test
        ),
        (
            "Das ist gut… Vielleicht morgen.",  # i18n-allow: German dictation under test
            "Das ist gut. Vielleicht morgen.",  # i18n-allow: German dictation under test
        ),
        ("That works... Then we go on.", "That works. Then we go on."),
        ("That works … The rest can wait.", "That works. The rest can wait."),
    ],
)
def test_a_pause_before_a_sentence_opener_becomes_a_full_stop(text: str, expected: str) -> None:
    """A capital on a word that opens sentences means the sentence before ended."""
    assert format_dictation(text).text == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Wir fahren nach... Berlin.",  # i18n-allow: German dictation under test
            "Wir fahren nach Berlin.",  # i18n-allow: German dictation under test
        ),
        (
            "Ich rufe ... Anna an.",  # i18n-allow: German dictation under test
            "Ich rufe Anna an.",  # i18n-allow: German dictation under test
        ),
        ("I mean... New York is big.", "I mean New York is big."),
    ],
)
def test_a_pause_before_a_noun_or_a_name_keeps_the_sentence_going(
    text: str, expected: str
) -> None:
    """A capital alone is no sentence start: German nouns and names carry one."""
    assert format_dictation(text).text == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("That was all...", "That was all."),
        ("That was all…", "That was all."),
        ("That was all . . .", "That was all."),
        ("Is that all?...", "Is that all?"),
        ("Stop!…", "Stop!"),
    ],
)
def test_a_pause_at_the_end_closes_the_sentence(text: str, expected: str) -> None:
    """Trailing dots become one full stop unless the sentence already has its mark."""
    assert format_dictation(text).text == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Really?... Yes.", "Really? Yes."),
        ("Really? ... Yes.", "Really? Yes."),
        ("That is fine. ... Then go on.", "That is fine. Then go on."),
        ("Stop! … Then go on.", "Stop! Then go on."),
        ("Fine, ... then go on.", "Fine, then go on."),
        ("Fine ..., then go on.", "Fine, then go on."),
    ],
)
def test_a_mark_next_to_the_dots_stays_and_the_dots_go(text: str, expected: str) -> None:
    """The speaker's own punctuation wins over whatever the pause would become."""
    assert format_dictation(text).text == expected


def test_a_text_of_only_dots_becomes_empty() -> None:
    """A recognizer that heard only a pause must not deliver punctuation."""
    for text in ("...", "…", ". . .", "..", "… …", " ... "):
        assert format_dictation(text).text == "", text


def test_dots_before_the_first_word_leave_no_mark() -> None:
    result = format_dictation("... Hello everyone.")

    assert result.text == "Hello everyone."


def test_no_pause_mark_survives() -> None:
    """Whatever stands around them, no run of dots reaches the delivered text."""
    for text in (
        "Well... I think… we could . . . maybe.. try. ... Then stop...",
        "One … two … three …",
        "...and then... nothing... New paragraph... the end…",
        "Hmm... okay... Then... fine?...",
    ):
        delivered = format_dictation(text, language="en").text

        assert delivered, text
        assert ".." not in delivered, text
        assert "…" not in delivered, text
        assert ". ." not in delivered, text


@pytest.mark.parametrize(
    "text",
    [
        "Version 1.2.3 is out.",
        "Das ist z. B. so.",  # i18n-allow: German abbreviation under test
        "Nimm z.B. das hier.",  # i18n-allow: German abbreviation under test
        "Use e.g. this one.",
        "Call me at 5 p.m. tomorrow.",
    ],
)
def test_version_numbers_and_abbreviations_are_untouched(text: str) -> None:
    """Dots that belong to a number or an abbreviation are not pause marks."""
    result = format_dictation(text)

    assert result.text == text
    assert result.pause_marks == 0


def test_pause_marks_are_counted() -> None:
    result = format_dictation("First... second… third . . . done.")

    assert result.pause_marks == 3
    assert result.text == "First second third done."


def test_strip_pause_marks_returns_the_text_and_the_count() -> None:
    assert strip_pause_marks("I think ... that works.") == ("I think that works.", 1)
    assert strip_pause_marks("Nothing to do here.") == ("Nothing to do here.", 0)
    assert strip_pause_marks("") == ("", 0)


# --------------------------------------------------------------------------
# Spoken layout commands
# --------------------------------------------------------------------------


def test_every_paragraph_phrase_becomes_a_blank_line() -> None:
    for phrase in PARAGRAPH_COMMANDS:
        result = format_dictation(f"First part. {phrase} second part")

        assert result.text == "First part.\n\nSecond part", phrase
        assert result.layout_commands == 1, phrase


def test_every_line_phrase_becomes_a_line_break() -> None:
    for phrase in LINE_COMMANDS:
        result = format_dictation(f"First part. {phrase} second part")

        assert result.text == "First part.\nSecond part", phrase
        assert result.layout_commands == 1, phrase


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Erster Punkt. Neuer Absatz. Zweiter Punkt.",  # i18n-allow: German command under test
            "Erster Punkt.\n\nZweiter Punkt.",
        ),
        (
            "Erster Punkt, neuer Absatz, zweiter Punkt.",  # i18n-allow: German command under test
            "Erster Punkt\n\nZweiter Punkt.",
        ),
        (
            "Erster Punkt NEUER ABSATZ zweiter Punkt",  # i18n-allow: German command under test
            "Erster Punkt\n\nZweiter Punkt",
        ),
        (
            "Was machst du? Neue Zeile. gut!",  # i18n-allow: German command under test
            "Was machst du?\nGut!",  # i18n-allow: German dictation under test
        ),
        (
            "Hallo! Neuer Absatz und weiter.",  # i18n-allow: German command under test
            "Hallo!\n\nUnd weiter.",  # i18n-allow: German dictation under test
        ),
        ("First point. New paragraph. second point.", "First point.\n\nSecond point."),
        ("First point, NEW LINE, second point", "First point\nSecond point"),
        ("First point new line second point", "First point\nSecond point"),
        ("First point; New Line: second point.", "First point\nSecond point."),
    ],
)
def test_a_command_works_in_any_casing_and_with_any_punctuation_around_it(
    text: str, expected: str
) -> None:
    """The sentence before keeps its end mark, a comma that led up to the
    command goes with it, and the text after the break starts with a capital."""
    assert format_dictation(text).text == expected


def test_commands_are_understood_whatever_language_was_detected() -> None:
    """A person switches languages mid-dictation, and the detected language is
    only a guess: the command phrases may not depend on it."""
    for language in (None, "", "auto", "de", "en", "fr", "German", "English"):
        english = format_dictation("First point new line second point", language=language)
        german = format_dictation(
            "Erster Punkt neuer Absatz zweiter Punkt",  # i18n-allow: German command under test
            language=language,
        )

        assert english.text == "First point\nSecond point", language
        assert german.text == "Erster Punkt\n\nZweiter Punkt", language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("New line. Hello.", "Hello."),
        ("New paragraph hello", "Hello"),
        ("Hello. New line.", "Hello."),
        ("Hello. New paragraph", "Hello."),
        ("Hello new line", "Hello"),
        ("Neue Zeile. Hallo.", "Hallo."),  # i18n-allow: German command under test
        ("Hallo. Neuer Absatz.", "Hallo."),  # i18n-allow: German command under test
    ],
)
def test_a_command_at_the_start_or_the_end_leaves_no_break(text: str, expected: str) -> None:
    """A break with nothing before or after it would deliver an empty line."""
    result = format_dictation(text)

    assert result.text == expected
    assert result.layout_commands == 1


@pytest.mark.parametrize(
    "text",
    [
        "Bitte füge eine neue Zeile ein.",  # i18n-allow: German dictation under test
        "Mach hier keine neue Zeile.",  # i18n-allow: German dictation under test
        "Please add a new line after the header.",
        "Every new paragraph needs a heading.",
        "Put the new line before the total.",
    ],
)
def test_a_phrase_that_is_talked_about_stays_as_words(text: str) -> None:
    """Someone describing a document says these phrases without meaning them."""
    result = format_dictation(text)

    assert result.text == text
    assert result.layout_commands == 0


def test_layout_commands_can_be_switched_off() -> None:
    text = "First point new line second point new paragraph third point"

    result = format_dictation(text, layout_commands=False)

    assert result.text == text
    assert result.layout_commands == 0


def test_layout_commands_and_pause_marks_are_counted_separately() -> None:
    result = format_dictation("Hello ... new line ... world. New paragraph. The end.")

    assert result.text == "Hello\nWorld.\n\nThe end."
    assert result.layout_commands == 2
    assert result.pause_marks == 2


def test_apply_layout_commands_returns_the_text_and_the_count() -> None:
    text, count = apply_layout_commands("First point, new paragraph, second point. New line. End.")

    assert count == 2
    assert text.split() == ["First", "point", "second", "point.", "End."]
    assert "\n\n" in text
    assert apply_layout_commands("Nothing to do here.") == ("Nothing to do here.", 0)
    assert apply_layout_commands("") == ("", 0)


# --------------------------------------------------------------------------
# Hesitation sounds
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        (
            "Ähm, das ist äh wirklich gut.",  # i18n-allow: German dictation under test
            "de",
            "Das ist wirklich gut.",  # i18n-allow: German dictation under test
        ),
        (
            "Ähm, das ist äh wirklich gut.",  # i18n-allow: German dictation under test
            "de-DE",
            "Das ist wirklich gut.",  # i18n-allow: German dictation under test
        ),
        (
            "Ähm, das ist äh wirklich gut.",  # i18n-allow: German dictation under test
            "German",
            "Das ist wirklich gut.",  # i18n-allow: German dictation under test
        ),
        ("Uh, I think we should umm ship it.", "en", "I think we should ship it."),
        ("Uh, I think we should umm ship it.", "English", "I think we should ship it."),
    ],
)
def test_hesitation_sounds_are_removed(text: str, language: str, expected: str) -> None:
    """Recognizers name a language by code or by its English name; both work."""
    result = format_dictation(text, language=language)

    assert result.text == expected
    assert result.removed_words == 2
    assert result.filler_reason == ""
    assert result.raw == text


def test_fillers_off_keeps_every_sound_and_says_so() -> None:
    text = "Uh, I think we should umm ship it."

    result = format_dictation(text, language="en", fillers=False)

    assert result.text == text
    assert result.removed_words == 0
    assert result.filler_reason == "disabled"


def test_a_language_without_rules_keeps_every_sound() -> None:
    """One language's hesitation sound is another's word, so no guessing."""
    text = "Uh, I think we should umm ship it."

    for language in (None, "", "auto", "unknown", "fr", "Klingon"):
        result = format_dictation(text, language=language)

        assert result.text == text, language
        assert result.removed_words == 0, language
        assert result.filler_reason == "no_rules", language


@pytest.mark.parametrize(
    "text",
    [
        "hmm hmm hmm hmm okay",
        "uh umm",
        "Uh hmm umm erm yes fine then",
    ],
)
def test_the_ceiling_keeps_the_text_when_too_many_words_would_go(text: str) -> None:
    """Removing most of a dictation is a rule gone wrong, not a clean-up."""
    result = format_dictation(text, language="en")

    assert result.text == text
    assert result.removed_words == 0
    assert result.filler_reason == "ceiling"


def test_the_ceiling_of_a_long_text_is_a_share_of_its_words() -> None:
    text = "uh umm erm hmm one two three four five six seven eight nine"

    refused = remove_fillers(text, language="en")
    allowed = remove_fillers(text, language="en", max_removed_fraction=0.5)

    assert refused == (text, 0, "ceiling")
    assert allowed[0].split() == "one two three four five six seven eight nine".split()
    assert allowed[1:] == (4, "")


def test_a_hesitation_sound_inside_a_word_is_not_touched() -> None:
    text = "Wir kommen gleich, das Hemd ist da."  # i18n-allow: German dictation under test

    result = format_dictation(text, language="de")

    assert result.text == text
    assert result.removed_words == 0


def test_remove_fillers_reports_why_nothing_was_removed() -> None:
    assert remove_fillers("", language="en") == ("", 0, "empty")
    assert remove_fillers("Uh, fine.", language=None) == ("Uh, fine.", 0, "no_rules")
    assert remove_fillers("All fine here.", language="en") == ("All fine here.", 0, "")


# --------------------------------------------------------------------------
# Punctuation and capitals
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello , world .", "Hello, world."),
        ("Done.. Next", "Done. Next"),
        ("Yes., and no", "Yes. and no"),
        ("Fine,, then", "Fine, then"),
        ("Too   many    spaces", "Too many spaces"),
        ("one thing. another thing", "One thing. another thing"),
        ("first line\nsecond line", "First line\nSecond line"),
        ("A.\n\n\n\nB", "A.\n\nB"),
        (", hello", "Hello"),
        ("Das ist z. B. so", "Das ist z. B. so"),  # i18n-allow: German abbreviation under test
        ("Use e.g. this", "Use e.g. this"),
    ],
)
def test_tidy_punctuation_repairs_seams(text: str, expected: str) -> None:
    assert tidy_punctuation(text) == expected


def test_tidy_punctuation_can_leave_the_first_letter_alone() -> None:
    assert tidy_punctuation("one thing. another", capitalize_first=False) == "one thing. another"
    assert tidy_punctuation("   ") == ""


def test_a_dictation_that_starts_in_lower_case_stays_that_way() -> None:
    """A dictation into the middle of a sentence must not gain a capital."""
    assert format_dictation("and then we went home").text == "and then we went home"


@pytest.mark.parametrize(
    "text",
    [
        "Das kostet ca. zehn Euro.",  # i18n-allow: German dictation under test
        "Brot, Milch usw. und Eier.",  # i18n-allow: German dictation under test
        "We meet at approx. five.",
    ],
)
def test_a_text_without_a_seam_comes_out_as_it_went_in(text: str) -> None:
    assert format_dictation(text, language="de").text == text


# --------------------------------------------------------------------------
# The whole pass
# --------------------------------------------------------------------------


def test_recognizer_line_breaks_are_not_layout() -> None:
    """Recognizers break lines between their segments; only a spoken command
    makes a line break in the delivered text."""
    raw = " Hallo,\n wie geht es dir?"  # i18n-allow: German dictation under test

    result = format_dictation(raw, language="de")

    assert result.text == "Hallo, wie geht es dir?"  # i18n-allow: German dictation under test
    assert result.raw == raw
    assert result.layout_commands == 0


def test_empty_input_gives_empty_text() -> None:
    for text in ("", "   ", "\n\n", None):
        result = format_dictation(text)  # type: ignore[arg-type]

        assert isinstance(result, FormatResult)
        assert result.text == "", repr(text)
        assert result.removed_words == 0


@pytest.mark.parametrize(
    "rule",
    ["strip_pause_marks", "apply_layout_commands", "remove_fillers", "tidy_punctuation"],
)
def test_a_broken_rule_delivers_the_recognized_words(
    monkeypatch: pytest.MonkeyPatch, rule: str
) -> None:
    """The pass never raises: a failing rule costs the formatting, not the words."""

    def _broken(*args: object, **kwargs: object) -> object:
        raise RuntimeError("rule failed")

    monkeypatch.setattr(formatting, rule, _broken)

    result = format_dictation("  Uh, hello ... new line world.  ", language="en")

    assert result.text == "Uh, hello ... new line world."


def test_everything_together() -> None:
    raw = (
        "Uh, first we fix the login...\nthen we... ship it. New paragraph. "
        "the second topic is, umm, the invoice… New line thanks."
    )

    result = format_dictation(raw, language="en")

    assert result.text == (
        "First we fix the login then we ship it.\n\n"
        "The second topic is, the invoice\nThanks."
    )
    assert result.raw == raw
    assert result.pause_marks == 3
    assert result.layout_commands == 2
    assert result.removed_words == 2


def test_the_capital_of_a_removed_sound_moves_to_the_next_word() -> None:
    """A sentence that began with a hesitation sound still begins with a
    capital; a sound inside a sentence leaves the next word as it was."""
    text = "Das passt. Ähm, das auch. Und äh, weiter."  # i18n-allow: German dictation under test

    result = format_dictation(text, language="de")

    assert result.text == "Das passt. Das auch. Und weiter."  # i18n-allow: German dictation
    assert result.removed_words == 2


def test_a_full_stop_inside_a_line_is_not_taken_for_a_sentence_end() -> None:
    """An abbreviation ends in a full stop too. The word after it keeps its
    case, whatever else the rules change in the text."""
    text = "Ähm, das kostet ca. zehn Euro usw. und mehr."  # i18n-allow: German dictation

    assert format_dictation(text, language="de").text == (
        "Das kostet ca. zehn Euro usw. und mehr."  # i18n-allow: German dictation under test
    )
