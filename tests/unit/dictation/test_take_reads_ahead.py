"""A dictation is read while the person still speaks.

What the speaker waits for after the stop is the reading of what is left. An
engine on this computer therefore reads the open piece at the speaker's
pauses, and the take keeps what such a reading settles:

* a reading the speaker added nothing to is the text, with no call after the
  stop;
* a reading that ends a sentence, or its part up to a break the recognizer
  marked, stays as read, and only the rest is read after the stop;
* nothing a reading returned is used twice or shown before the stop;
* a paid service is never sent audio whose reading may be thrown away;
* a reading that fails costs nothing: no error, no change of recognizer.

The recognizers are plain objects that answer from a script. The recordings
are tones and silence, judged by loudness.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from dodaios.dictation import take as take_module
from dodaios.dictation.take import Recognizer, Take, read_recording

pytestmark = pytest.mark.usefixtures("speech_by_loudness")

_RATE = 16_000
_BYTES_PER_SECOND = _RATE * 2


def _silence(seconds: float) -> bytes:
    return np.zeros(int(seconds * _RATE), dtype=np.int16).tobytes()


def _speech(seconds: float) -> bytes:
    t = np.arange(int(seconds * _RATE)) / _RATE
    return (np.sin(2 * np.pi * 220 * t) * 9000).astype(np.int16).tobytes()


class _Engine:
    """An engine on this computer that answers from a script, call by call.

    An entry is the recognized text, a ``(text, segments)`` pair where each
    segment is ``(start_s, end_s, text)``, or an exception to raise.
    """

    def __init__(self, *script: Any, language: str = "de", confidence: float = 0.0) -> None:
        self._script = list(script) or ["words"]
        self._language = language
        self._confidence = confidence
        self.calls: list[SimpleNamespace] = []

    async def transcribe_pcm(self, pcm: bytes, language: str | None = None) -> Any:
        self.calls.append(SimpleNamespace(pcm=pcm, language=language))
        answer = self._script[min(len(self.calls), len(self._script)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        segments: tuple[dict[str, Any], ...] = ()
        if isinstance(answer, tuple):
            answer, timed = answer
            segments = tuple({"start": a, "end": b, "text": t} for a, b, t in timed)
        return SimpleNamespace(
            text=answer,
            raw_text=answer,
            language=self._language,
            confidence=self._confidence,
            segments=segments,
        )

    @property
    def seconds_heard(self) -> list[float]:
        return [len(call.pcm) / _BYTES_PER_SECOND for call in self.calls]


def _on_this_computer(engine: Any) -> list[Recognizer]:
    return [Recognizer("engine", engine, on_device=True)]


async def _record(take: Take, pcm: bytes) -> None:
    """Feed a recording as a microphone does, leaving room to read in between."""
    block = 3200
    for offset in range(0, len(pcm), block):
        take.feed(pcm[offset : offset + block])
        for _ in range(4):
            await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def _no_engine_is_known_as_slow() -> Any:
    """What one test measured about an engine must not reach the next."""
    take_module._slow_until.clear()
    yield
    take_module._slow_until.clear()


@pytest.fixture
def short_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let two seconds of speech be enough to keep, so tests stay short."""
    monkeypatch.setattr(take_module, "KEEP_MIN_S", 2.0)


# --------------------------------------------------------------------------
# A reading the speaker added nothing to is the text
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_pause_before_the_stop_leaves_nothing_to_read_after_it() -> None:
    engine = _Engine("All of it.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.8))
    read_before_the_stop = len(engine.calls)
    result = await take.finish()

    assert read_before_the_stop == 1
    assert len(engine.calls) == 1
    assert result.text == "All of it."
    assert result.reads_ahead == 1
    assert result.reads_ahead_kept == 1
    assert result.pieces == 1
    assert result.error is None
    assert result.lost_audio_s == 0


@pytest.mark.asyncio
async def test_a_reading_is_not_used_when_the_speaker_carried_on() -> None:
    """Its text would end before the last words."""
    engine = _Engine("The first half", "The first half and the second.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.6) + _speech(2.0))
    result = await take.finish()

    assert result.text == "The first half and the second."
    assert len(engine.calls) == 2
    # The second call heard the whole recording, not only what was new.
    assert engine.seconds_heard[1] > 4.0
    assert result.reads_ahead_kept == 0


@pytest.mark.asyncio
async def test_a_breath_after_the_last_word_is_not_read_by_itself(short_parts: None) -> None:
    """A recognizer invents words for a sound that short."""
    engine = _Engine("A whole sentence.", "A whole sentence. Yes.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(3.0) + _silence(0.6) + _speech(0.5))
    result = await take.finish()

    assert result.text == "A whole sentence. Yes."
    assert engine.seconds_heard[-1] > 3.5
    assert result.pieces == 1


@pytest.mark.asyncio
async def test_one_short_word_after_the_last_pause_is_never_dropped(short_parts: None) -> None:
    """A "yes" of a fifth of a second is a word, however short."""
    engine = _Engine("A whole sentence.", "A whole sentence. Yes.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(3.0) + _silence(0.6) + _speech(0.2))
    result = await take.finish()

    assert len(engine.calls) == 2
    assert result.text == "A whole sentence. Yes."
    assert engine.seconds_heard[-1] > 3.5


@pytest.mark.asyncio
async def test_the_voice_only_has_to_stop_for_a_moment_to_be_read() -> None:
    """Somebody who lets go of the key right after the last word."""
    engine = _Engine("All of it.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.25))
    read_before_the_stop = len(engine.calls)
    result = await take.finish()

    assert read_before_the_stop == 1
    assert len(engine.calls) == 1
    assert result.text == "All of it."


# --------------------------------------------------------------------------
# What a reading settles stays as read
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_finished_sentence_is_kept_and_only_the_rest_is_read(short_parts: None) -> None:
    engine = _Engine("The first sentence.", "And the second one.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(3.0) + _silence(0.6) + _speech(2.0))
    result = await take.finish()

    assert result.text == "The first sentence. And the second one."
    assert len(engine.calls) == 2
    first, second = engine.seconds_heard
    assert 3.0 <= first < 3.6
    assert 2.0 <= second < 2.8
    assert result.pieces == 2
    assert result.reads_ahead_kept == 1
    assert result.pieces_read_early == 1


@pytest.mark.asyncio
async def test_a_short_piece_is_not_kept_even_when_it_ends_a_sentence() -> None:
    """Two seconds are too little for a recognizer to spell a name from."""
    engine = _Engine("Short.", "Short. And more.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.6) + _speech(2.0))
    result = await take.finish()

    assert result.text == "Short. And more."
    assert result.pieces == 1


@pytest.mark.asyncio
async def test_the_part_up_to_a_finished_sentence_is_kept_from_a_longer_reading(
    short_parts: None,
) -> None:
    """The speaker paused in mid-sentence; the sentence before it is final."""
    whole = "The first sentence. the second is still"
    engine = _Engine(
        (whole, [(0.0, 3.0, " The first sentence."), (3.15, 6.15, " the second is still")]),
        "The second is still going",
        "The second is still going on.",
    )
    take = Take(_on_this_computer(engine))
    recording = (
        _speech(3.0) + _silence(0.15) + _speech(3.0) + _silence(0.6) + _speech(2.0)
    )

    await _record(take, recording)
    result = await take.finish()

    assert result.text == "The first sentence. The second is still going on."
    assert result.pieces == 2
    # After the stop only the second sentence was read, from the gap on.
    assert 5.0 <= engine.seconds_heard[-1] < 6.2
    assert result.reads_ahead_kept == 1


@pytest.mark.asyncio
async def test_no_part_is_kept_without_a_gap_in_the_speech_to_cut_in(short_parts: None) -> None:
    """A cut on the recognizer's time alone could fall inside a word."""
    whole = "The first sentence. the second is still"
    engine = _Engine(
        (whole, [(0.0, 3.0, " The first sentence."), (3.0, 6.0, " the second is still")]),
        "The first sentence. The second is still going on.",
    )
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(6.0) + _silence(0.6) + _speech(2.0))
    result = await take.finish()

    assert result.text == "The first sentence. The second is still going on."
    assert result.pieces == 1
    assert engine.seconds_heard[-1] > 8.0


@pytest.mark.asyncio
async def test_no_part_is_kept_when_the_text_is_not_the_segments_text(short_parts: None) -> None:
    """Corrected text cannot be cut by the segments' word counts."""
    engine = _Engine(
        (
            "The first corrected sentence here. the second is still",
            [(0.0, 3.0, " The first sentence."), (3.15, 6.15, " the second is still")],
        ),
        "Everything in one reading.",
    )
    take = Take(_on_this_computer(engine))
    recording = (
        _speech(3.0) + _silence(0.15) + _speech(3.0) + _silence(0.6) + _speech(2.0)
    )

    await _record(take, recording)
    result = await take.finish()

    assert result.text == "Everything in one reading."
    assert result.pieces == 1


@pytest.mark.asyncio
async def test_a_full_stop_before_words_that_carry_on_becomes_a_comma(short_parts: None) -> None:
    """The recognizer wrote the next piece as the rest of the sentence."""
    engine = _Engine("It is set up like this.", "so that two of them show.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(3.0) + _silence(0.6) + _speech(2.0))
    result = await take.finish()

    assert result.text == "It is set up like this, so that two of them show."


# --------------------------------------------------------------------------
# Somebody who talks on without a pause
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speech_without_any_pause_is_still_read_while_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(take_module, "_AHEAD_LADDER", ((0.6, 0.3), (1.0, 0.12), (2.0, 0.0)))
    engine = _Engine("part", "all of it")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(3.5))
    read_before_the_stop = len(engine.calls)
    result = await take.finish()

    assert read_before_the_stop >= 1
    # A reading that ended inside a word is never the text.
    assert result.text == "all of it"
    assert engine.seconds_heard[-1] == pytest.approx(3.5, abs=0.2)


# --------------------------------------------------------------------------
# A paid service, a finished recording
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_service_is_asked_once_and_only_after_the_stop() -> None:
    service = _Engine("Everything.")
    take = Take([Recognizer("service", service, on_device=False)])

    await _record(take, _speech(3.0) + _silence(0.8) + _speech(3.0) + _silence(0.8))
    asked_before_the_stop = len(service.calls)
    result = await take.finish()

    assert asked_before_the_stop == 0
    assert len(service.calls) == 1
    assert result.reads_ahead == 0
    assert result.text == "Everything."


@pytest.mark.asyncio
async def test_a_finished_recording_is_read_once() -> None:
    """Nobody is still speaking, so there is no wait a reading could shorten."""
    engine = _Engine("Everything.")

    result = await read_recording(
        _speech(3.0) + _silence(0.8) + _speech(3.0), _on_this_computer(engine)
    )

    assert len(engine.calls) == 1
    assert result.reads_ahead == 0


# --------------------------------------------------------------------------
# A reading that fails costs nothing
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_reading_at_a_pause_is_no_error_and_changes_no_order() -> None:
    """An engine that was still starting must read the dictation at the stop."""
    engine = _Engine(RuntimeError("HTTP 503 the engine is still starting"), "All of it.")
    service = _Engine("from the service")
    take = Take(
        [Recognizer("engine", engine, on_device=True), Recognizer("service", service)]
    )

    await _record(take, _speech(2.0) + _silence(0.8))
    result = await take.finish()

    assert result.text == "All of it."
    assert result.recognizers == ("engine",)
    assert service.calls == []
    assert result.errors == ()
    assert result.error is None


@pytest.mark.asyncio
async def test_the_audit_says_how_much_was_read_ahead() -> None:
    take = Take(_on_this_computer(_Engine("All of it.")))

    await _record(take, _speech(2.0) + _silence(0.8))
    audit = (await take.finish()).audit()

    assert "reads_ahead:1" in audit
    assert "reads_ahead_kept:1" in audit


# --------------------------------------------------------------------------
# The language is found out once
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_take_whose_language_is_sure_is_not_asked_for_it_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(take_module, "SHORT_FOR_DETECTION_S", 1.5)
    engine = _Engine("First half", "First half and second.", language="de", confidence=0.97)
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.6) + _speech(2.0))
    await take.finish()

    assert [call.language for call in engine.calls] == ["auto", "de"]


@pytest.mark.asyncio
async def test_an_unsure_language_is_found_out_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(take_module, "SHORT_FOR_DETECTION_S", 1.5)
    engine = _Engine("First half", "First half and second.", language="de", confidence=0.4)
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.6) + _speech(2.0))
    await take.finish()

    assert [call.language for call in engine.calls] == ["auto", "auto"]


# --------------------------------------------------------------------------
# Giving up
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_lets_an_engine_on_this_computer_finish_its_clip() -> None:
    """Cutting its call off costs the engine itself, and the next dictation
    would wait for a new one."""

    class _Slow:
        def __init__(self) -> None:
            self.release = asyncio.Event()
            self.interrupted = False
            self.finished = False

        async def transcribe_pcm(self, pcm: bytes, language: str | None = None) -> Any:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.interrupted = True
                raise
            self.finished = True
            return SimpleNamespace(text="late", raw_text="late", language="de")

    engine = _Slow()
    take = Take(_on_this_computer(engine))
    await _record(take, _speech(2.0) + _silence(0.8))

    take.cancel()
    await asyncio.sleep(0)
    engine.release.set()
    for _ in range(10):
        await asyncio.sleep(0)

    assert engine.finished
    assert not engine.interrupted
    assert (await take.finish()).text == ""


# --------------------------------------------------------------------------
# An engine too slow to read ahead with
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_slow_engine_is_not_read_ahead_with_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its reading would still be running at the stop, and the stop would wait
    for it. Whisper on a processor alone is such an engine."""
    # Every reading counts as slow: the scripted engine answers at once.
    monkeypatch.setattr(take_module, "_AHEAD_SLOW_BASE_S", -1.0)
    engine = _Engine("First part", "First part and second part", "All of it.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.6) + _speech(2.0) + _silence(0.6))
    read_before_the_stop = len(engine.calls)
    result = await take.finish()

    # The first pause was read, and that reading showed the engine as slow.
    assert read_before_the_stop == 1
    assert result.text == "First part and second part"

    # The next dictation is not read ahead at all.
    later = Take(_on_this_computer(engine))
    await _record(later, _speech(2.0) + _silence(0.8))
    assert len(engine.calls) == 2
    assert (await later.finish()).text == "All of it."
    assert len(engine.calls) == 3


@pytest.mark.asyncio
async def test_a_fast_reading_brings_reading_ahead_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every dictation's last reading measures the engine again."""
    engine = _Engine("One.", "Two.")
    take_module._slow_until["engine"] = take_module.time.perf_counter() + 300.0
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.8))
    assert engine.calls == []  # known as slow: nothing before the stop
    await take.finish()
    assert len(engine.calls) == 1  # and that reading was fast

    later = Take(_on_this_computer(engine))
    await _record(later, _speech(2.0) + _silence(0.8))
    assert len(engine.calls) == 2  # read ahead again
    await later.finish()
    assert len(engine.calls) == 2


# --------------------------------------------------------------------------
# Reading ahead is a help, never a gate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fault_in_reading_ahead_never_costs_the_dictation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever goes wrong in deciding what to keep, the stop reads the
    recording as it always did."""

    def broken(self: Take, piece: Any) -> bool:
        raise ValueError("a segment nobody expected")

    monkeypatch.setattr(Take, "_keepable", broken)
    engine = _Engine("First part.", "First part. Second part.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.6) + _speech(2.0))
    result = await take.finish()

    assert result.text == "First part. Second part."
    assert result.error is None
    assert result.lost_audio_s == 0


@pytest.mark.asyncio
async def test_a_fault_in_starting_a_reading_does_not_stop_the_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self: Take) -> Any:
        raise RuntimeError("no lead")

    monkeypatch.setattr(Take, "_lead", broken)
    engine = _Engine("All of it.")
    take = Take(_on_this_computer(engine))

    await _record(take, _speech(2.0) + _silence(0.6) + _speech(2.0))
    assert take.duration_s == pytest.approx(4.6, abs=0.05)
    monkeypatch.undo()
    result = await take.finish()

    assert result.text == "All of it."
    assert len(engine.calls) == 1
