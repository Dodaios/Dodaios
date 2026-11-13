"""A long dictation is broken into paragraphs where they make sense.

Three cues, all without a model: a long pause between two sentences, a
sentence that opens a new topic, and a paragraph that has grown long. A short
dictation stays one paragraph, a sentence is never split, and a spoken list
keeps its lines.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from dodaios.dictation import take as take_module
from dodaios.dictation.formatting import (
    PARAGRAPH_MIN_WORDS,
    auto_paragraphs,
    break_before_sentences,
    format_dictation,
    sentence_spans,
)
from dodaios.dictation.speech_map import SAMPLE_RATE, SpeechMap, condense_marked
from dodaios.dictation.take import Recognizer, read_recording
from dodaios.plugins.stt.parakeet_local import _sentence_segments


def _sentences(count: int, words: int = 10, start: str = "Here") -> str:
    """``count`` plain sentences of ``words`` words each."""
    body = " ".join(["word"] * (words - 1))
    return " ".join(f"{start} {body}." for _ in range(count))


def _paragraph_sizes(text: str) -> list[int]:
    return [len(part.split()) for part in text.split("\n\n")]


# --------------------------------------------------------------------------
# Sentences
# --------------------------------------------------------------------------


def test_sentences_end_at_full_stops_question_and_exclamation_marks() -> None:
    text = "One two. Three four? Five six! Seven"

    assert [text[a:b].strip() for a, b in sentence_spans(text)] == [
        "One two.",
        "Three four?",
        "Five six!",
        "Seven",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Das ist z. B. ein Satz mit Abkürzung.",  # i18n-allow: German fixture
        "Ruf Dr. Müller an und frag ihn.",  # i18n-allow: German fixture
        "Es kostet ca. zehn Euro inkl. Versand.",  # i18n-allow: German fixture
    ],
)
def test_an_abbreviation_does_not_end_a_sentence(text: str) -> None:
    assert len(sentence_spans(text)) == 1


def test_a_break_goes_before_the_named_sentence_only() -> None:
    text = "One. Two. Three. Four."

    assert break_before_sentences(text, {2}) == "One. Two.\n\nThree. Four."
    assert break_before_sentences(text, {0, 9}) == text


# --------------------------------------------------------------------------
# Automatic paragraphs from the text
# --------------------------------------------------------------------------


def test_a_short_dictation_stays_one_paragraph() -> None:
    text = _sentences(4, words=10)
    assert len(text.split()) < PARAGRAPH_MIN_WORDS

    assert auto_paragraphs(text, language="en") == (text, 0)


def test_a_sentence_on_a_new_topic_starts_a_paragraph() -> None:
    text = (
        _sentences(3, words=12, start="Erst")  # i18n-allow: German fixture
        + " Außerdem brauchen wir noch eine Lösung für die Absätze im Text."  # i18n-allow
        + " "
        + _sentences(2, words=10, start="Dann")
    )

    out, made = auto_paragraphs(text, language="de")

    assert made == 1
    assert out.split("\n\n")[1].startswith("Außerdem")  # i18n-allow: German fixture


def test_a_topic_word_right_at_the_start_breaks_nothing() -> None:
    """Too little before it: a topic word in the second sentence of a long
    text is not yet a new paragraph."""
    text = "Kurz vorab. Außerdem " + _sentences(6, words=12)  # i18n-allow: fixture

    out, _made = auto_paragraphs(text, language="de")

    assert not out.split("\n\n")[0].endswith("vorab.")


def test_german_also_is_not_a_new_topic_in_german() -> None:
    """In German "Also" is "so", how many sentences begin."""
    text = _sentences(3, words=12) + " Also das war es dann eigentlich schon. " + _sentences(
        2, words=8
    )  # i18n-allow: German fixture

    out, made = auto_paragraphs(text, language="de")

    assert made == 0, out


def test_a_long_paragraph_is_closed_at_a_sentence_end() -> None:
    text = _sentences(13, words=10)

    out, made = auto_paragraphs(text, language="en")

    assert made >= 1
    assert all(size <= 80 for size in _paragraph_sizes(out))
    assert out.replace("\n\n", " ") == text


def test_no_tiny_last_paragraph_is_split_off() -> None:
    text = _sentences(8, words=10)  # 80 words: 70 and a rest of 10 is too little

    out, made = auto_paragraphs(text, language="en")

    assert made == 0, out


def test_a_single_long_sentence_is_never_split() -> None:
    text = "And " + " ".join(["word"] * 150) + "."

    assert auto_paragraphs(text, language="en") == (text, 0)


def test_a_spoken_list_keeps_its_lines() -> None:
    items = "\n".join(f"Item number {n} with a few words in it." for n in range(12))

    out, made = auto_paragraphs(items, language="en")

    assert (out, made) == (items, 0)


# --------------------------------------------------------------------------
# The whole formatting pass
# --------------------------------------------------------------------------


def test_a_blank_line_from_the_recording_survives_formatting() -> None:
    raw = "First topic here. Ähm, more of it.\n\nSecond topic... starts here."  # i18n-allow

    out = format_dictation(raw, language="de").text

    assert out == "First topic here. More of it.\n\nSecond topic starts here."


def test_paragraphs_off_keeps_one_paragraph_but_spoken_commands_work() -> None:
    raw = (
        "First part.\n\nSecond part. " + _sentences(10, words=10)
        + " Neuer Absatz. Last part."  # i18n-allow: German fixture
    )

    out = format_dictation(raw, language="de", paragraphs=False).text

    assert out.count("\n\n") == 1
    assert out.endswith("\n\nLast part.")


def test_a_single_line_break_of_a_recognizer_is_no_paragraph() -> None:
    out = format_dictation(" Hallo,\n wie geht es dir?\n Gut.", language="de").text

    assert out == "Hallo, wie geht es dir? Gut."


# --------------------------------------------------------------------------
# Long pauses in the recording
# --------------------------------------------------------------------------


def test_condensing_marks_where_a_long_pause_was() -> None:
    pcm = np.ones(SAMPLE_RATE * 10, dtype=np.int16).tobytes()
    speech = SpeechMap(
        spans=(
            (0, SAMPLE_RATE),
            (SAMPLE_RATE * 2, SAMPLE_RATE * 3),
            (SAMPLE_RATE * 6, SAMPLE_RATE * 7),
        ),
        total_samples=SAMPLE_RATE * 10,
        detector="energy",
    )

    clip, marks = condense_marked(pcm, speech, mark_pause_s=2.0)

    # 1 s speech, 1 s pause kept, 1 s speech, 3 s pause shortened to 0.5 s, 1 s speech.
    assert len(clip) / 2 / SAMPLE_RATE == pytest.approx(4.5)
    assert marks == [pytest.approx(3.25)]


def test_the_local_model_reports_its_sentences_with_times() -> None:
    tokens = [" Das", " ist", " gut", ".", " Jetzt", " weiter", "."]  # i18n-allow
    times = [0.3, 0.5, 0.7, 0.9, 3.5, 3.7, 3.9]

    segments = _sentence_segments(tokens, times, offset_s=0.3)

    assert [s["text"] for s in segments] == ["Das ist gut.", "Jetzt weiter."]  # i18n-allow
    assert segments[0]["start"] == pytest.approx(0.0)
    assert segments[1]["start"] == pytest.approx(3.2)
    assert segments[0]["end"] < segments[1]["start"]


def test_mismatched_times_give_no_segments() -> None:
    assert _sentence_segments([" a", " b"], [0.1], offset_s=0.0) == ()


@pytest.fixture
def _loud_is_speech(speech_by_loudness: None) -> None:
    """Tones stand in for a voice; loudness decides what counts as speech."""


def _loud(seconds: float) -> bytes:
    return (np.ones(int(seconds * SAMPLE_RATE), dtype=np.int16) * 6_000).tobytes()


def _silent(seconds: float) -> bytes:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16).tobytes()


class _TimedRecognizer:
    """Answers with two sentences and a segment time for each.

    The second sentence starts where the clip's second stretch of speech
    starts, which is how a recognizer with times reports it.
    """

    def __init__(self) -> None:
        self.clips: list[bytes] = []

    async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
        self.clips.append(pcm)
        samples = np.frombuffer(pcm, dtype=np.int16)
        loud = np.flatnonzero(samples != 0)
        gaps = np.flatnonzero(np.diff(loud) > SAMPLE_RATE // 4)
        second_start = (loud[gaps[0] + 1] / SAMPLE_RATE) if gaps.size else 0.0
        first_end = (loud[gaps[0]] / SAMPLE_RATE) if gaps.size else 0.0
        return SimpleNamespace(
            text="First thought ends here. Second thought starts here.",
            language="en",
            segments=(
                {"start": 0.0, "end": first_end, "text": "First thought ends here."},
                {
                    "start": second_start,
                    "end": second_start + 1.0,
                    "text": "Second thought starts here.",
                },
            ),
        )


@pytest.mark.usefixtures("_loud_is_speech")
@pytest.mark.parametrize(("pause_s", "expected"), [(3.0, "\n\n"), (0.8, " ")])
async def test_a_long_pause_between_sentences_is_a_paragraph(
    pause_s: float, expected: str
) -> None:
    recording = _loud(2.0) + _silent(pause_s) + _loud(2.0)

    result = await read_recording(recording, [Recognizer("timed", _TimedRecognizer())])

    assert result.text == f"First thought ends here.{expected}Second thought starts here."


@pytest.mark.usefixtures("_loud_is_speech")
async def test_a_recognizer_without_times_gets_no_pause_paragraph() -> None:
    class _Plain:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            return SimpleNamespace(text="One. Two.", language="en")

    result = await read_recording(
        _loud(2.0) + _silent(3.0) + _loud(2.0), [Recognizer("plain", _Plain())]
    )

    assert result.text == "One. Two."


@pytest.mark.usefixtures("_loud_is_speech")
async def test_a_long_pause_between_two_pieces_is_a_paragraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(take_module, "PIECE_MIN_S", 1.9)
    monkeypatch.setattr(take_module, "_CUT_LADDER", ((1.9, 0.9),))
    monkeypatch.setattr(take_module, "PIECE_MAX_S", 30.0)
    answers = iter(["The first piece ends.", "The second piece starts.", "Third."])

    class _Pieces:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            await asyncio.sleep(0)
            return SimpleNamespace(text=next(answers), language="en")

    recording = _loud(2.0) + _silent(3.0) + _loud(2.0) + _silent(1.0) + _loud(2.0)

    result = await read_recording(recording, [Recognizer("pieces", _Pieces())])

    assert result.pieces == 3
    assert result.text == "The first piece ends.\n\nThe second piece starts. Third."
