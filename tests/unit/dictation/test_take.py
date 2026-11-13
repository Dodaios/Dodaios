"""One dictation from the first sample to the recognized words.

A take promises the speaker five things, and each has its tests here:

* silence is never sent to a recognizer, so none can invent words for it;
* every stretch of the recording is read once, a long one in pieces cut at
  the speaker's own pauses and joined in the order they were spoken;
* a recognizer that fails hands the piece to the next one and stops being the
  first choice for the rest of the take;
* a piece nobody could read is reported, never dropped quietly, and the
  recording stays available to be read again;
* the recognizer is told a language only when it cannot find it by itself.

The recognizers are plain objects that record their calls. The recordings are
tones and silence, which is why every test that needs speech asks for the
``speech_by_loudness`` fixture.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from dodaios.dictation import take as take_module
from dodaios.dictation.take import (
    Recognizer,
    RecordingReader,
    RecordingUnread,
    Take,
    TakeResult,
    read_recording,
    spoken_text,
)

_RATE = 16_000
_BYTES_PER_SECOND = _RATE * 2


def _silence(seconds: float) -> bytes:
    return np.zeros(int(seconds * _RATE), dtype=np.int16).tobytes()


def _speech(seconds: float) -> bytes:
    """A loud tone: speech for the loudness detector."""
    t = np.arange(int(seconds * _RATE)) / _RATE
    return (np.sin(2 * np.pi * 220 * t) * 9000).astype(np.int16).tobytes()


#: Three stretches of speech with a clear pause after the first two.
_THREE_PARTS = _speech(2.5) + _silence(1.0) + _speech(2.5) + _silence(1.0) + _speech(1.0)


class _Scripted:
    """A recognizer that records every call and answers from a script.

    Each entry is the answer to one call, the last one repeats. A string is
    recognized text; an exception is raised.
    """

    def __init__(self, *script: str | BaseException, language: str = "en") -> None:
        self._script = list(script) or ["words"]
        self._language = language
        self.calls: list[SimpleNamespace] = []

    async def transcribe_pcm(self, pcm: bytes, language: str | None = None) -> Any:
        self.calls.append(SimpleNamespace(pcm=pcm, language=language))
        answer = self._script[min(len(self.calls), len(self._script)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return SimpleNamespace(text=answer, raw_text=answer, language=self._language)

    @property
    def seconds_heard(self) -> list[float]:
        return [len(call.pcm) / _BYTES_PER_SECOND for call in self.calls]


class _NeverAnswers:
    """A recognizer whose service hangs."""

    def __init__(self) -> None:
        self.calls = 0
        self.interrupted = 0

    async def transcribe_pcm(self, pcm: bytes, language: str | None = None) -> Any:
        self.calls += 1
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.interrupted += 1
            raise
        raise AssertionError("the take must not wait this long")


def _bad_key() -> RuntimeError:
    return RuntimeError("HTTP 401 Unauthorized")


def _busy() -> RuntimeError:
    return RuntimeError("HTTP 503 Service Unavailable")


@pytest.fixture(autouse=True)
def _no_waiting_before_a_second_try(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pause before a second attempt would only slow these tests down."""
    monkeypatch.setattr(take_module, "_RETRY_DELAY_S", 0.0)


@pytest.fixture
def short_pieces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cut a take after two seconds instead of thirty, so a "long" recording
    is a few seconds of audio."""
    monkeypatch.setattr(take_module, "PIECE_MIN_S", 2.0)
    monkeypatch.setattr(take_module, "_CUT_LADDER", ((2.0, 0.5),))
    monkeypatch.setattr(take_module, "PIECE_MAX_S", 6.0)


def _hanging_services_time_out_fast(monkeypatch: pytest.MonkeyPatch, *ids: str) -> None:
    """Give the named recognizers a time limit of a few milliseconds."""

    def _limit(recognizer: Recognizer, audio_s: float, *, has_stand_in: bool) -> float:
        return 0.05 if recognizer.id in ids else 30.0

    monkeypatch.setattr(take_module, "_time_limit_s", _limit)


async def _record(take: Take, pcm: bytes) -> None:
    """Feed a recording the way a microphone does, a tenth of a second at a
    time, leaving the take room to read finished pieces in between."""
    block = 3200
    for offset in range(0, len(pcm), block):
        take.feed(pcm[offset : offset + block])
        await asyncio.sleep(0)


# --------------------------------------------------------------------------
# Silence is never sent
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_recording_without_speech_makes_no_recognizer_call() -> None:
    """Digital silence, judged by whichever detector this machine has."""
    recognizer = _Scripted("Thank you.")

    result = await read_recording(_silence(3.0), [Recognizer("first", recognizer)])

    assert recognizer.calls == []
    assert result.text == ""
    assert result.error is None
    assert result.calls == 0
    assert result.lost_audio_s == 0
    assert result.duration_s == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_a_key_tap_makes_no_recognizer_call(speech_by_loudness: None) -> None:
    """A click is shorter than any word, so there is nothing to read."""
    recognizer = _Scripted("Thank you.")
    tap = _silence(0.5) + _speech(0.05) + _silence(0.5)

    result = await read_recording(tap, [Recognizer("first", recognizer)])

    assert recognizer.calls == []
    assert result.text == ""
    assert result.error is None


@pytest.mark.asyncio
async def test_a_silent_piece_of_a_long_take_makes_no_call(
    speech_by_loudness: None, short_pieces: None
) -> None:
    """Someone who stops talking for a while and then goes on: the silent
    stretch in between is a piece of its own and is skipped."""
    recognizer = _Scripted("one", "two")
    recording = _speech(2.5) + _silence(5.0) + _speech(1.0)

    result = await read_recording(recording, [Recognizer("first", recognizer)])

    assert result.pieces > 2
    assert len(recognizer.calls) == 2
    assert result.text == "one two"
    assert result.error is None


# --------------------------------------------------------------------------
# A short recording is one request
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_short_recording_is_exactly_one_call(speech_by_loudness: None) -> None:
    recognizer = _Scripted("hello world", language="en-US")
    recording = _silence(1.0) + _speech(2.0) + _silence(1.0)

    result = await read_recording(
        recording, [Recognizer("first", recognizer, model="model-a")]
    )

    assert len(recognizer.calls) == 1
    assert result.text == "hello world"
    assert result.error is None
    assert result.calls == 1
    assert result.pieces == 1
    assert result.pieces_read_early == 0
    assert result.recognizers == ("first",)
    assert result.models == ("model-a",)
    assert result.language == "en"
    assert result.duration_s == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_silence_around_the_words_is_not_sent(speech_by_loudness: None) -> None:
    recognizer = _Scripted()
    recording = _silence(1.0) + _speech(2.0) + _silence(1.0)

    result = await read_recording(recording, [Recognizer("first", recognizer)])

    heard = recognizer.seconds_heard[0]
    assert 2.0 <= heard < 3.0
    assert result.audio_sent_s == pytest.approx(heard)
    assert result.audio_sent_s < result.duration_s
    assert result.speech_s == pytest.approx(heard)


@pytest.mark.asyncio
async def test_a_long_pause_is_shortened_before_it_is_sent(speech_by_loudness: None) -> None:
    recognizer = _Scripted()
    recording = _speech(1.0) + _silence(4.0) + _speech(1.0)

    await read_recording(recording, [Recognizer("first", recognizer)])

    assert len(recognizer.calls) == 1
    assert 2.0 <= recognizer.seconds_heard[0] < 3.5


@pytest.mark.asyncio
async def test_a_very_short_clip_is_padded_with_silence(speech_by_loudness: None) -> None:
    """Recognizers misread clips of a fraction of a second."""
    recognizer = _Scripted()
    recording = _silence(0.5) + _speech(0.4) + _silence(0.5)

    await read_recording(recording, [Recognizer("first", recognizer)])

    clip = recognizer.calls[0].pcm
    assert len(clip) / _BYTES_PER_SECOND >= 1.25
    assert len(clip) % 2 == 0
    assert _speech(0.4)[3200:9600] in clip


@pytest.mark.asyncio
async def test_every_short_clip_reaches_the_minimum_length(speech_by_loudness: None) -> None:
    recognizer = _Scripted()
    recording = _silence(0.5) + _speech(0.35) + _silence(0.5)

    await read_recording(recording, [Recognizer("first", recognizer)])

    assert len(recognizer.calls[0].pcm) / _BYTES_PER_SECOND >= 1.25


# --------------------------------------------------------------------------
# A long recording is cut at pauses
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_long_recording_is_cut_at_its_pauses_and_joined_in_order(
    speech_by_loudness: None, short_pieces: None
) -> None:
    recognizer = _Scripted("one", "two", "three")

    result = await read_recording(_THREE_PARTS, [Recognizer("first", recognizer)])

    assert result.text == "one two three"
    assert result.pieces == 3
    # Every piece went to the recognizer once, and none of them twice.
    assert len(recognizer.calls) == 3
    assert result.calls == 3
    # The first two were closed by a pause while the recording still ran.
    assert result.pieces_read_early == 2
    assert result.error is None
    assert result.lost_audio_s == 0
    # Cut inside the pauses: each piece holds its own stretch of speech only.
    first, second, third = recognizer.seconds_heard
    assert 2.5 <= first < 3.5
    assert 2.5 <= second < 3.5
    assert 1.0 <= third < 2.0


@pytest.mark.asyncio
async def test_pieces_are_read_while_the_recording_still_runs(
    speech_by_loudness: None, short_pieces: None
) -> None:
    """After the stop only the last piece is left to read."""
    recognizer = _Scripted("one", "two", "three")
    take = Take([Recognizer("first", recognizer)])

    await _record(take, _THREE_PARTS)
    read_before_the_stop = len(recognizer.calls)
    result = await take.finish()

    assert read_before_the_stop == 2
    assert len(recognizer.calls) == 3
    assert result.text == "one two three"


@pytest.mark.asyncio
async def test_a_recording_without_any_pause_is_still_cut(
    speech_by_loudness: None, short_pieces: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone who never stops for breath must not grow one endless piece."""
    monkeypatch.setattr(take_module, "PIECE_MAX_S", 3.0)
    recognizer = _Scripted("one", "two")

    result = await read_recording(_speech(5.0), [Recognizer("first", recognizer)])

    assert result.pieces == 2
    assert result.pieces_read_early == 1
    assert result.text == "one two"
    assert recognizer.seconds_heard == [pytest.approx(3.0), pytest.approx(2.0)]


@pytest.mark.asyncio
async def test_an_empty_answer_for_a_piece_leaves_no_gap_in_the_text(
    speech_by_loudness: None, short_pieces: None
) -> None:
    recognizer = _Scripted("one", "", "three")

    result = await read_recording(_THREE_PARTS, [Recognizer("first", recognizer)])

    assert result.text == "one three"
    assert result.error is None


# --------------------------------------------------------------------------
# A recognizer that fails
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failing_recognizer_hands_the_piece_to_the_next(
    speech_by_loudness: None,
) -> None:
    first = _Scripted(_bad_key())
    second = _Scripted("hello world")

    result = await read_recording(
        _silence(0.5) + _speech(2.0) + _silence(0.5),
        [Recognizer("first", first), Recognizer("second", second)],
    )

    assert result.text == "hello world"
    # Nothing was lost, so there is nothing to tell the person.
    assert result.error is None
    assert result.lost_audio_s == 0
    # The record of what happened names who answered and what went wrong.
    assert result.recognizers == ("second",)
    assert result.errors == ("bad_key",)
    assert result.calls == 2
    # Both were given the same audio.
    assert first.calls[0].pcm == second.calls[0].pcm


@pytest.mark.asyncio
async def test_a_failed_recognizer_is_not_asked_first_again_in_the_same_take(
    speech_by_loudness: None, short_pieces: None
) -> None:
    first = _Scripted(_bad_key())
    second = _Scripted("one", "two", "three")

    result = await read_recording(
        _THREE_PARTS, [Recognizer("first", first), Recognizer("second", second)]
    )

    assert len(first.calls) == 1
    assert len(second.calls) == 3
    assert result.text == "one two three"
    assert result.recognizers == ("second",)
    assert result.errors == ("bad_key",)
    assert result.error is None
    assert result.lost_audio_s == 0


@pytest.mark.asyncio
async def test_a_recognizer_that_does_not_answer_in_time_costs_its_limit_once(
    speech_by_loudness: None, short_pieces: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead service is waited for once, not once for every piece."""
    _hanging_services_time_out_fast(monkeypatch, "slow")
    slow = _NeverAnswers()
    second = _Scripted("one", "two", "three")

    result = await read_recording(
        _THREE_PARTS, [Recognizer("slow", slow), Recognizer("second", second)]
    )

    assert slow.calls == 1
    assert slow.interrupted == 1
    assert result.text == "one two three"
    assert result.recognizers == ("second",)
    assert result.errors == ("unavailable",)
    assert result.error is None
    assert result.lost_audio_s == 0


@pytest.mark.asyncio
async def test_a_set_aside_recognizer_is_still_the_stand_in(
    speech_by_loudness: None, short_pieces: None
) -> None:
    """Set aside means asked last, not never: when the other one fails later,
    the first gets the piece back."""
    first = _Scripted(_bad_key(), "two", "three")
    second = _Scripted("one", _bad_key())

    result = await read_recording(
        _THREE_PARTS, [Recognizer("first", first), Recognizer("second", second)]
    )

    assert result.text == "one two three"
    assert result.recognizers == ("second", "first")
    assert result.error is None
    assert result.lost_audio_s == 0


@pytest.mark.asyncio
async def test_all_recognizers_failing_reports_the_loss_and_keeps_the_recording(
    speech_by_loudness: None,
) -> None:
    first = _Scripted(_bad_key())
    second = _Scripted(RuntimeError("HTTP 402 Payment Required"))
    recording = _silence(0.5) + _speech(2.0) + _silence(0.5)
    take = Take([Recognizer("first", first), Recognizer("second", second)])

    await _record(take, recording)
    result = await take.finish()

    assert result.text == ""
    # The first failure is the one the person is told about.
    assert result.error == "bad_key"
    assert "first" in result.error_detail
    assert result.errors == ("bad_key", "no_credit")
    assert result.lost_audio_s == pytest.approx(2.0, abs=0.1)
    assert result.recognizers == ()
    assert result.calls == 2
    # The recording is whole, so it can be read again.
    assert take.audio == recording


@pytest.mark.asyncio
async def test_a_lost_piece_does_not_cost_the_pieces_that_were_read(
    speech_by_loudness: None, short_pieces: None
) -> None:
    recognizer = _Scripted("one", _bad_key(), "three")

    result = await read_recording(_THREE_PARTS, [Recognizer("first", recognizer)])

    assert result.text == "one three"
    assert result.error == "bad_key"
    assert result.lost_audio_s == pytest.approx(2.5, abs=0.2)
    assert result.recognizers == ("first",)


@pytest.mark.asyncio
async def test_speech_without_any_recognizer_is_reported(speech_by_loudness: None) -> None:
    result = await read_recording(_silence(0.5) + _speech(2.0) + _silence(0.5), [])

    assert result.text == ""
    assert result.error == "no_stt"
    assert result.lost_audio_s == pytest.approx(result.speech_s)
    assert result.lost_audio_s > 0
    assert result.calls == 0


@pytest.mark.asyncio
async def test_silence_without_any_recognizer_is_no_error(speech_by_loudness: None) -> None:
    result = await read_recording(_silence(2.0), [])

    assert result.text == ""
    assert result.error is None
    assert result.lost_audio_s == 0


# --------------------------------------------------------------------------
# One more try
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_busy_service_is_asked_once_more(speech_by_loudness: None) -> None:
    """A rate limit passes; the dictation should not be lost to one."""
    recognizer = _Scripted(RuntimeError("HTTP 429 Too Many Requests"), "hello world")

    result = await read_recording(
        _silence(0.5) + _speech(2.0) + _silence(0.5), [Recognizer("first", recognizer)]
    )

    assert result.text == "hello world"
    assert result.lost_audio_s == 0
    assert result.error is None
    assert result.calls == 2
    assert len(recognizer.calls) == 2
    assert result.errors == ("rate_limited",)
    assert result.recognizers == ("first",)


@pytest.mark.asyncio
async def test_a_wrong_key_is_not_asked_about_twice(speech_by_loudness: None) -> None:
    recognizer = _Scripted(_bad_key())

    result = await read_recording(
        _silence(0.5) + _speech(2.0) + _silence(0.5), [Recognizer("first", recognizer)]
    )

    assert len(recognizer.calls) == 1
    assert result.calls == 1
    assert result.error == "bad_key"
    assert result.lost_audio_s > 0


@pytest.mark.asyncio
async def test_two_busy_services_give_the_first_one_more_try(speech_by_loudness: None) -> None:
    first = _Scripted(_busy())
    second = _Scripted(_busy())

    result = await read_recording(
        _silence(0.5) + _speech(2.0) + _silence(0.5),
        [Recognizer("first", first), Recognizer("second", second)],
    )

    assert len(first.calls) == 2
    assert len(second.calls) == 1
    assert result.calls == 3
    assert result.text == ""
    assert result.error == "unavailable"
    assert result.lost_audio_s > 0


@pytest.mark.asyncio
async def test_the_second_try_can_save_the_piece(speech_by_loudness: None) -> None:
    first = _Scripted(_busy(), "hello world")
    second = _Scripted(_busy())

    result = await read_recording(
        _silence(0.5) + _speech(2.0) + _silence(0.5),
        [Recognizer("first", first), Recognizer("second", second)],
    )

    assert result.text == "hello world"
    assert result.error is None
    assert result.lost_audio_s == 0
    assert result.calls == 3
    assert result.recognizers == ("first",)


@pytest.mark.asyncio
async def test_a_recognizer_that_sat_out_its_time_limit_is_not_asked_again(
    speech_by_loudness: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Waiting the whole limit a second time would double the wait for nothing."""
    _hanging_services_time_out_fast(monkeypatch, "slow")
    slow = _NeverAnswers()

    result = await read_recording(
        _silence(0.5) + _speech(2.0) + _silence(0.5), [Recognizer("slow", slow)]
    )

    assert slow.calls == 1
    assert result.calls == 1
    assert result.error == "unavailable"
    assert "slow" in result.error_detail
    assert result.lost_audio_s > 0


# --------------------------------------------------------------------------
# Language
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [2.0, 7.0])
@pytest.mark.asyncio
async def test_a_pinned_language_is_passed_to_the_recognizer(
    speech_by_loudness: None, seconds: float
) -> None:
    recognizer = _Scripted()

    await read_recording(_speech(seconds), [Recognizer("first", recognizer)], language="de")

    assert [call.language for call in recognizer.calls] == ["de"]


@pytest.mark.asyncio
async def test_a_short_clip_is_told_the_language_hint(speech_by_loudness: None) -> None:
    """A few words are too little for a recognizer to tell the language from."""
    recognizer = _Scripted()

    await read_recording(
        _speech(2.0), [Recognizer("first", recognizer)], language="auto", language_hint="de"
    )

    assert [call.language for call in recognizer.calls] == ["de"]


@pytest.mark.asyncio
async def test_a_long_clip_is_left_to_the_recognizer_to_detect(speech_by_loudness: None) -> None:
    """With enough speech the recognizer hears the language better than a
    hint from an earlier dictation knows it."""
    recognizer = _Scripted()

    await read_recording(
        _speech(7.0), [Recognizer("first", recognizer)], language="auto", language_hint="de"
    )

    assert [call.language for call in recognizer.calls] == ["auto"]


@pytest.mark.asyncio
async def test_without_a_hint_a_short_clip_is_detected_too(speech_by_loudness: None) -> None:
    recognizer = _Scripted()

    await read_recording(_speech(2.0), [Recognizer("first", recognizer)])

    assert [call.language for call in recognizer.calls] == ["auto"]


@pytest.mark.asyncio
async def test_later_pieces_follow_the_language_the_take_was_heard_in(
    speech_by_loudness: None, short_pieces: None
) -> None:
    recognizer = _Scripted("one", "two", "three", language="en-US")

    result = await read_recording(
        _THREE_PARTS, [Recognizer("first", recognizer)], language_hint="de"
    )

    assert [call.language for call in recognizer.calls] == ["de", "en", "en"]
    assert result.language == "en"
    assert result.languages == ("en",)


@pytest.mark.asyncio
async def test_a_recognizer_without_a_language_keyword_still_answers(
    speech_by_loudness: None,
) -> None:
    """The recognizer contract allows a bare ``transcribe_pcm(pcm)``."""

    class _Bare:
        def __init__(self) -> None:
            self.clips: list[bytes] = []

        async def transcribe_pcm(self, pcm: bytes) -> Any:
            self.clips.append(pcm)
            return SimpleNamespace(text="hello world", language="en")

    bare = _Bare()

    result = await read_recording(_speech(2.0), [Recognizer("bare", bare)], language="de")

    assert result.text == "hello world"
    assert result.error is None
    assert len(bare.clips) == 1
    assert result.recognizers == ("bare",)


@pytest.mark.asyncio
async def test_a_type_error_inside_a_recognizer_is_a_failure_like_any_other(
    speech_by_loudness: None,
) -> None:
    """Only the missing keyword is worked around; a recognizer's own bug must
    not be answered by calling it a second time."""
    broken = _Scripted(TypeError("unsupported operand"))
    second = _Scripted("hello world")

    result = await read_recording(
        _speech(2.0), [Recognizer("broken", broken), Recognizer("second", second)]
    )

    assert len(broken.calls) == 1
    assert result.text == "hello world"
    assert result.recognizers == ("second",)


# --------------------------------------------------------------------------
# spoken_text
# --------------------------------------------------------------------------


def test_spoken_text_prefers_what_the_recognizer_really_returned() -> None:
    """``raw_text`` is the recognizer's own output; ``text`` may be edited."""
    assert spoken_text(SimpleNamespace(text="edited", raw_text=" heard as said ")) == (
        "heard as said"
    )
    assert spoken_text(SimpleNamespace(text=" only this ", raw_text="")) == "only this"
    assert spoken_text(SimpleNamespace(text=" plain ")) == "plain"
    assert spoken_text(SimpleNamespace()) == ""


@pytest.mark.parametrize(
    "invented",
    [
        {"text": "Thank you.", "no_speech_prob": 0.9, "avg_logprob": -1.5},
        {"text": "la la la la la la", "compression_ratio": 3.1},
        SimpleNamespace(text="Thank you.", no_speech_prob=0.61, avg_logprob=-1.01),
        SimpleNamespace(text="la la la la la la", compression_ratio=2.41),
    ],
    ids=["no-speech dict", "repeating dict", "no-speech object", "repeating object"],
)
def test_spoken_text_drops_a_segment_the_model_marks_as_invented(invented: Any) -> None:
    transcript = SimpleNamespace(
        text="Real words. Thank you. More words.",
        raw_text="Real words. Thank you. More words.",
        segments=[
            {"text": " Real words. ", "no_speech_prob": 0.01, "avg_logprob": -0.2},
            invented,
            {"text": "More words.", "no_speech_prob": 0.02, "avg_logprob": -0.3},
        ],
    )

    assert spoken_text(transcript) == "Real words. More words."


@pytest.mark.parametrize(
    "segment",
    [
        # Unsure whether there is speech, but sure of the words: kept.
        {"text": "quiet words", "no_speech_prob": 0.9, "avg_logprob": -0.4},
        # Unsure of the words, but sure there is speech: kept.
        {"text": "mumbled words", "no_speech_prob": 0.1, "avg_logprob": -1.8},
        # Exactly at the limits is not beyond them.
        {"text": "at the limit", "no_speech_prob": 0.6, "avg_logprob": -1.0},
        {"text": "at the limit", "compression_ratio": 2.4},
        # No figures at all: nothing marks it.
        {"text": "no figures"},
        {"text": "odd figures", "no_speech_prob": "n/a", "avg_logprob": None},
    ],
    ids=["sure words", "sure speech", "at the limits", "ratio at limit", "bare", "unreadable"],
)
def test_spoken_text_keeps_the_text_untouched_when_nothing_is_invented(segment: Any) -> None:
    """Without an invented segment the text is the recognizer's own, not a
    re-join of its segments."""
    transcript = SimpleNamespace(
        text="edited", raw_text="  The  recognizer's own   text. ", segments=[segment]
    )

    assert spoken_text(transcript) == "The  recognizer's own   text."


def test_spoken_text_of_only_invented_segments_is_empty() -> None:
    transcript = SimpleNamespace(
        text="Thank you.",
        segments=[{"text": "Thank you.", "no_speech_prob": 0.95, "avg_logprob": -2.0}],
    )

    assert spoken_text(transcript) == ""


@pytest.mark.asyncio
async def test_an_invented_segment_never_reaches_the_take_result(
    speech_by_loudness: None,
) -> None:
    class _Inventing:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None) -> Any:
            return SimpleNamespace(
                text="Hello world. Thank you.",
                language="en",
                segments=[
                    {"text": "Hello world.", "no_speech_prob": 0.02, "avg_logprob": -0.2},
                    {"text": "Thank you.", "no_speech_prob": 0.9, "avg_logprob": -1.6},
                ],
            )

    result = await read_recording(_speech(2.0), [Recognizer("first", _Inventing())])

    assert result.text == "Hello world."


# --------------------------------------------------------------------------
# The ends of a take
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finish_after_feeding_nothing_is_an_empty_result() -> None:
    recognizer = _Scripted()

    result = await Take([Recognizer("first", recognizer)]).finish()

    assert isinstance(result, TakeResult)
    assert result.text == ""
    assert result.error is None
    assert result.calls == 0
    assert result.pieces == 0
    assert result.duration_s == 0
    assert result.lost_audio_s == 0
    assert recognizer.calls == []


@pytest.mark.asyncio
async def test_cancel_before_anything_was_read_does_not_raise() -> None:
    take = Take([Recognizer("first", _Scripted())])
    take.feed(_silence(0.5))

    take.cancel()

    assert take.audio == _silence(0.5)


@pytest.mark.asyncio
async def test_cancel_stops_reading_and_keeps_the_recording(
    speech_by_loudness: None, short_pieces: None
) -> None:
    hanging = _NeverAnswers()
    take = Take([Recognizer("hanging", hanging)])
    recording = _speech(2.5) + _silence(1.0) + _speech(2.5) + _silence(1.0)

    await _record(take, recording)
    assert hanging.calls == 1
    take.cancel()
    for _ in range(5):
        await asyncio.sleep(0)

    assert hanging.interrupted == 1
    # The second piece was waiting; it is not started after the cancel.
    assert hanging.calls == 1
    assert take.audio == recording
    assert take.duration_s == pytest.approx(7.0)


@pytest.mark.asyncio
async def test_take_reports_what_it_has_recorded(speech_by_loudness: None) -> None:
    take = Take([])
    assert take.heard_speech is False

    take.feed(_silence(0.5))
    assert take.heard_speech is False
    take.feed(_speech(0.5))

    assert take.heard_speech is True
    assert take.duration_s == pytest.approx(1.0)
    assert take.audio == _silence(0.5) + _speech(0.5)


def test_the_audit_of_a_result_holds_no_content() -> None:
    """These facts go into the history, where the words must not follow."""
    result = TakeResult(text="my private words", pieces=3, pieces_read_early=2, detector="silero")

    facts = result.audit()

    assert "pieces:3" in facts
    assert "pieces_read_early:2" in facts
    assert "speech_detector:silero" in facts
    assert not any("private" in fact for fact in facts)


# --------------------------------------------------------------------------
# RecordingReader
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reader_returns_a_transcript(speech_by_loudness: None) -> None:
    recognizer = _Scripted("hello world", language="en")
    reader = RecordingReader([Recognizer("first", recognizer, model="model-a")])

    transcript = await reader.transcribe_pcm(_silence(0.5) + _speech(2.0) + _silence(0.5))

    assert transcript.text == "hello world"
    assert transcript.raw_text == "hello world"
    assert transcript.language == "en"
    assert reader.last_used_provider == "first"
    assert reader.last_used_model == "model-a"
    assert len(recognizer.calls) == 1


@pytest.mark.asyncio
async def test_the_reader_cuts_a_long_recording_like_a_live_take(
    speech_by_loudness: None, short_pieces: None
) -> None:
    recognizer = _Scripted("one", "two", "three")
    reader = RecordingReader([Recognizer("first", recognizer)])

    transcript = await reader.transcribe_pcm(_THREE_PARTS)

    assert transcript.text == "one two three"
    assert len(recognizer.calls) == 3


@pytest.mark.asyncio
async def test_the_reader_passes_language_and_hint_on(speech_by_loudness: None) -> None:
    recognizer = _Scripted()
    reader = RecordingReader([Recognizer("first", recognizer)], language_hint=lambda: "de")

    await reader.transcribe_pcm(_speech(2.0))
    await reader.transcribe_pcm(_speech(2.0), language="fr")

    assert [call.language for call in recognizer.calls] == ["de", "fr"]


@pytest.mark.asyncio
async def test_the_reader_answers_silence_with_an_empty_transcript() -> None:
    recognizer = _Scripted("Thank you.")
    reader = RecordingReader([Recognizer("first", recognizer)])

    transcript = await reader.transcribe_pcm(_silence(2.0))

    assert transcript.text == ""
    assert recognizer.calls == []


@pytest.mark.asyncio
async def test_the_reader_raises_when_nothing_could_be_read(speech_by_loudness: None) -> None:
    reader = RecordingReader([Recognizer("first", _Scripted(_bad_key()))])

    with pytest.raises(RecordingUnread) as excinfo:
        await reader.transcribe_pcm(_speech(2.0))

    assert excinfo.value.reason == "bad_key"
    assert isinstance(excinfo.value, RuntimeError)
    assert "first" in str(excinfo.value)


@pytest.mark.asyncio
async def test_the_reader_asks_for_its_recognizers_on_every_call(
    speech_by_loudness: None,
) -> None:
    """A key saved between two calls must count for the second."""
    available: list[Recognizer] = []
    reader = RecordingReader(lambda: available)

    with pytest.raises(RecordingUnread) as excinfo:
        await reader.transcribe_pcm(_speech(2.0))
    available.append(Recognizer("first", _Scripted("hello world")))
    transcript = await reader.transcribe_pcm(_speech(2.0))

    assert excinfo.value.reason == "no_stt"
    assert transcript.text == "hello world"


@pytest.mark.asyncio
async def test_the_reader_rejects_another_sample_rate(speech_by_loudness: None) -> None:
    """Audio at another rate would be read at the wrong speed."""
    recognizer = _Scripted()
    reader = RecordingReader([Recognizer("first", recognizer)])

    with pytest.raises(ValueError, match="16000"):
        await reader.transcribe_pcm(_speech(2.0), sample_rate=8_000)

    assert recognizer.calls == []


# --------------------------------------------------------------------------
# A take whose recognizers arrive while it records
# --------------------------------------------------------------------------


async def test_a_take_started_without_recognizers_reads_once_they_arrive(
    monkeypatch: pytest.MonkeyPatch, speech_by_loudness: None
) -> None:
    """The microphone opens before the recognizers are known. A piece closed
    meanwhile waits for them instead of being counted as unreadable."""
    monkeypatch.setattr(take_module, "PIECE_MIN_S", 1.0)
    monkeypatch.setattr(take_module, "_CUT_LADDER", ((1.0, 0.9),))
    monkeypatch.setattr(take_module, "PIECE_MAX_S", 1.0)
    calls: list[int] = []

    class _Late:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            calls.append(len(pcm))
            return SimpleNamespace(text="word", language="en")

    take = Take(None)
    loud = (np.ones(_RATE, dtype=np.int16) * 6_000).tobytes()
    take.feed(loud)
    take.feed(loud)
    for _ in range(10):
        await asyncio.sleep(0)
    assert calls == [], "a piece was read before any recognizer was known"

    take.set_recognizers([Recognizer(id="late", provider=_Late())])
    result = await take.finish()

    assert result.text == "word word"
    assert result.error is None
    assert result.recognizers == ("late",)


async def test_a_take_that_never_learns_its_recognizers_reports_none(
    speech_by_loudness: None,
) -> None:
    take = Take(None)
    take.feed((np.ones(_RATE, dtype=np.int16) * 6_000).tobytes())

    result = await take.finish()

    assert result.text == ""
    assert result.error == "no_stt"


async def test_half_a_sample_is_carried_to_the_next_chunk(speech_by_loudness: None) -> None:
    """A chunk that ends between the two bytes of a sample must not shift the
    recording against its speech map."""
    received: list[bytes] = []

    class _Echo:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            received.append(pcm)
            return SimpleNamespace(text="ok", language="en")

    loud = (np.ones(_RATE * 2, dtype=np.int16) * 6_000).tobytes()
    take = Take([Recognizer(id="echo", provider=_Echo())])
    take.feed(loud[:1001])
    take.feed(loud[1001:])

    result = await take.finish()

    assert take.audio == loud
    assert result.text == "ok"
    assert len(received[0]) % 2 == 0
    samples = np.frombuffer(received[0], dtype=np.int16)
    assert set(np.unique(samples)) <= {0, 6_000}, "samples were read across their bytes"


async def test_finish_after_cancel_returns_what_there_is(
    monkeypatch: pytest.MonkeyPatch, speech_by_loudness: None
) -> None:
    monkeypatch.setattr(take_module, "PIECE_MIN_S", 1.0)
    monkeypatch.setattr(take_module, "_CUT_LADDER", ((1.0, 0.9),))
    monkeypatch.setattr(take_module, "PIECE_MAX_S", 1.0)
    release = asyncio.Event()

    class _Stuck:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            await release.wait()
            return SimpleNamespace(text="late", language="en")

    take = Take([Recognizer(id="stuck", provider=_Stuck())])
    loud = (np.ones(_RATE, dtype=np.int16) * 6_000).tobytes()
    take.feed(loud)
    take.feed(loud)
    await asyncio.sleep(0)

    take.cancel()
    result = await take.finish()

    assert result.text == ""
    assert take.audio == loud + loud


async def test_a_recognizer_that_timed_out_is_not_the_one_tried_again(
    monkeypatch: pytest.MonkeyPatch, speech_by_loudness: None
) -> None:
    """The retry is for a failure that may pass. A recognizer that sat out its
    whole time limit already had its time."""
    monkeypatch.setattr(take_module, "_RETRY_DELAY_S", 0.0)
    monkeypatch.setattr(
        take_module,
        "_time_limit_s",
        lambda recognizer, audio_s, *, has_stand_in: 0.05 if recognizer.id == "slow" else 5.0,
    )
    calls: list[str] = []

    class _Slow:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            calls.append("slow")
            await asyncio.sleep(1.0)

    class _Busy:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            calls.append("busy")
            raise RuntimeError("503 Service Unavailable")

    result = await read_recording(
        (np.ones(_RATE * 2, dtype=np.int16) * 6_000).tobytes(),
        [Recognizer(id="slow", provider=_Slow()), Recognizer(id="busy", provider=_Busy())],
    )

    assert calls == ["slow", "busy"]
    assert result.text == ""
    assert result.lost_audio_s > 0
