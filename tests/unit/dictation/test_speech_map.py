"""Where the speech is in a dictation recording, and what is cut around it.

A recognizer that is handed silence invents words for it, so the map decides
what a recognizer gets to hear. These tests pin both sides of that: silence is
found and removed, and nothing that was spoken is touched.

The recordings are synthetic. The bundled speech model rightly hears no speech
in a tone, so the tests that need stretches of speech ask for the
``speech_by_loudness`` fixture, with which a loud stretch counts as speech.
The tests without it run on whichever detector this machine has and only say
what holds for both.
"""
from __future__ import annotations

import numpy as np
import pytest

from dodaios.dictation.speech_map import (
    SAMPLE_RATE,
    SpeechMap,
    SpeechMapper,
    condense,
    map_speech,
)

#: The detector judges 32 ms at a time, so an edge is exact to about one frame.
_FRAME_S = 0.032


def _samples(seconds: float) -> int:
    return int(seconds * SAMPLE_RATE)


def _silence(seconds: float) -> bytes:
    """Digital silence."""
    return np.zeros(_samples(seconds), dtype=np.int16).tobytes()


def _loud(seconds: float) -> bytes:
    """A steady tone at about a quarter of full scale."""
    t = np.arange(_samples(seconds)) / SAMPLE_RATE
    return (np.sin(2 * np.pi * 220 * t) * 9000).astype(np.int16).tobytes()


def _hiss(seconds: float) -> bytes:
    """Noise far below any voice, the same on every run."""
    noise = np.random.default_rng(7).integers(-30, 31, _samples(seconds))
    return noise.astype(np.int16).tobytes()


def _ramp(samples: int) -> bytes:
    """Audio in which every stretch is different, so a moved byte shows."""
    return (np.arange(samples) % 32000).astype(np.int16).tobytes()


def _cut(pcm: bytes, start: int, end: int) -> bytes:
    """The bytes of the samples ``start`` to ``end``."""
    return pcm[start * 2 : end * 2]


# --------------------------------------------------------------------------
# With the detector this machine has
# --------------------------------------------------------------------------


@pytest.mark.parametrize("recording", [_silence(2.0), _hiss(2.0)], ids=["silence", "hiss"])
def test_silence_and_room_noise_contain_no_speech(recording: bytes) -> None:
    """A recording like this is never sent to a recognizer."""
    speech = map_speech(recording)

    assert speech.has_speech is False
    assert speech.spans == ()
    assert speech.speech_s == 0
    assert speech.duration_s == pytest.approx(2.0)


def test_feeding_never_raises() -> None:
    """The map is a help while the microphone is open; it may never stop a take."""
    mapper = SpeechMapper()

    mapper.feed(b"")
    mapper.feed(b"\x01")
    mapper.feed(bytes(range(256)) * 9 + b"\x7f")
    mapper.feed(_loud(0.5))
    mapper.feed(_silence(0.2))

    assert isinstance(mapper.finish(), SpeechMap)
    assert mapper.silence_run_s() >= 0


def test_nothing_fed_is_an_empty_map() -> None:
    speech = SpeechMapper().finish()

    assert speech.has_speech is False
    assert speech.total_samples == 0
    assert speech.duration_s == 0


# --------------------------------------------------------------------------
# Stretches of speech
# --------------------------------------------------------------------------


@pytest.mark.parametrize("recording", [_silence(2.0), _hiss(2.0)], ids=["silence", "hiss"])
def test_the_loudness_detector_hears_no_speech_in_silence(
    speech_by_loudness: None, recording: bytes
) -> None:
    speech = map_speech(recording)

    assert speech.spans == ()
    assert speech.detector == "energy"


def test_a_loud_stretch_between_silences_is_one_padded_span(speech_by_loudness: None) -> None:
    """Some room is kept on both sides so a soft first or last sound stays."""
    speech = map_speech(_silence(1.0) + _loud(1.0) + _silence(1.0))

    assert len(speech.spans) == 1
    start, end = speech.spans[0]
    assert _samples(0.5) < start < _samples(1.0)
    assert _samples(2.0) < end < _samples(2.5)
    assert speech.has_speech is True
    assert speech.speech_s == pytest.approx((end - start) / SAMPLE_RATE)
    assert speech.total_samples == _samples(3.0)


def test_padding_stays_inside_the_recording(speech_by_loudness: None) -> None:
    at_the_start = map_speech(_loud(1.0) + _silence(1.0))
    at_the_end = map_speech(_silence(1.0) + _loud(1.0))
    throughout = map_speech(_loud(3.0))

    assert at_the_start.spans[0][0] == 0
    assert at_the_end.spans[0][1] == at_the_end.total_samples == _samples(2.0)
    # A recording that is loud from end to end is kept whole.
    assert throughout.spans == ((0, _samples(3.0)),)


def test_a_long_pause_separates_two_spans(speech_by_loudness: None) -> None:
    speech = map_speech(
        _silence(1.0) + _loud(1.0) + _silence(1.0) + _loud(1.0) + _silence(1.0)
    )

    assert len(speech.spans) == 2
    (first_start, first_end), (second_start, second_end) = speech.spans
    assert first_start < _samples(1.0) < _samples(2.0) < first_end
    assert first_end < second_start
    assert second_start < _samples(3.0) < _samples(4.0) < second_end


def test_a_very_short_gap_does_not_split_a_span(speech_by_loudness: None) -> None:
    """The stop inside a word is not a pause."""
    speech = map_speech(
        _silence(1.0) + _loud(1.0) + _silence(0.1) + _loud(1.0) + _silence(1.0)
    )

    assert len(speech.spans) == 1
    start, end = speech.spans[0]
    assert start < _samples(1.0)
    assert end > _samples(3.1)


def test_a_blip_is_not_speech(speech_by_loudness: None) -> None:
    """A click or a key tap is shorter than any word."""
    speech = map_speech(_silence(1.0) + _loud(0.05) + _silence(1.0))

    assert speech.has_speech is False
    assert speech.spans == ()


def test_less_than_one_frame_holds_no_speech(speech_by_loudness: None) -> None:
    speech = map_speech(_loud(0.02))

    assert speech.has_speech is False
    assert speech.total_samples == _samples(0.02)


# --------------------------------------------------------------------------
# A part of the recording
# --------------------------------------------------------------------------


def test_map_of_a_range_is_relative_to_its_start_and_clipped(speech_by_loudness: None) -> None:
    """A long take is read piece by piece; each piece needs its own offsets."""
    mapper = SpeechMapper()
    mapper.feed(_silence(1.0) + _loud(2.0) + _silence(1.0))

    inside = mapper.map(_samples(1.5), _samples(2.5))
    first_half = mapper.map(0, _samples(2.0))
    before = mapper.map(0, _samples(0.5))
    after = mapper.map(_samples(3.5))

    # Speech fills the range: one span from its first to its last sample.
    assert inside.spans == ((0, _samples(1.0)),)
    assert inside.total_samples == _samples(1.0)
    # Speech runs out of the range: the span ends where the range ends.
    assert len(first_half.spans) == 1
    assert _samples(0.5) < first_half.spans[0][0] < _samples(1.0)
    assert first_half.spans[0][1] == first_half.total_samples == _samples(2.0)
    assert before.spans == ()
    assert before.total_samples == _samples(0.5)
    assert after.spans == ()
    assert after.total_samples == _samples(0.5)


def test_map_clips_a_range_to_the_recording(speech_by_loudness: None) -> None:
    mapper = SpeechMapper()
    mapper.feed(_silence(1.0) + _loud(1.0) + _silence(1.0))

    assert mapper.map(0, 10**9) == mapper.finish() == mapper.map()
    assert mapper.map(_samples(2.0), _samples(1.0)).total_samples == 0
    assert mapper.map(_samples(2.0), _samples(1.0)).spans == ()
    assert mapper.map(10**9).spans == ()


# --------------------------------------------------------------------------
# While the microphone is open
# --------------------------------------------------------------------------


def test_silence_run_grows_with_silence_and_resets_on_speech(speech_by_loudness: None) -> None:
    """The take cuts a long recording where this says the speaker paused."""
    mapper = SpeechMapper()
    assert mapper.silence_run_s() == 0

    mapper.feed(_loud(0.5))
    assert mapper.silence_run_s() <= _FRAME_S
    mapper.feed(_silence(0.5))
    assert mapper.silence_run_s() == pytest.approx(0.5, abs=_FRAME_S)
    mapper.feed(_silence(0.5))
    assert mapper.silence_run_s() == pytest.approx(1.0, abs=_FRAME_S)
    mapper.feed(_loud(0.3))
    assert mapper.silence_run_s() <= _FRAME_S


def test_silence_from_the_first_sample_counts_as_a_run(speech_by_loudness: None) -> None:
    mapper = SpeechMapper()

    mapper.feed(_silence(0.75))

    assert mapper.silence_run_s() == pytest.approx(0.75, abs=_FRAME_S)
    assert mapper.heard_speech is False


def test_heard_speech_and_total_samples_follow_the_feed(speech_by_loudness: None) -> None:
    mapper = SpeechMapper()

    mapper.feed(_silence(0.5))
    assert mapper.heard_speech is False
    mapper.feed(_loud(0.5))

    assert mapper.heard_speech is True
    assert mapper.total_samples == _samples(1.0)


def test_speech_between_two_offsets(speech_by_loudness: None) -> None:
    """How much speech a stretch held; what a lost piece is counted by."""
    mapper = SpeechMapper()
    mapper.feed(_silence(1.0) + _loud(1.0) + _silence(1.0))

    assert mapper.speech_between(0, _samples(0.9)) == 0
    assert mapper.speech_between(_samples(1.0), _samples(2.0)) == pytest.approx(
        1.0, abs=2 * _FRAME_S
    )
    assert mapper.speech_between(0, _samples(3.0)) == pytest.approx(1.0, abs=2 * _FRAME_S)
    assert mapper.speech_between(_samples(2.1), _samples(3.0)) == 0


def test_chunk_sizes_do_not_change_the_map(speech_by_loudness: None) -> None:
    """A microphone delivers blocks of any size; the map is of the recording."""
    recording = (
        _silence(0.7) + _loud(0.9) + _silence(1.4) + _loud(0.6) + _silence(0.1) + _loud(0.4)
        + _silence(0.5)
    )
    in_one = SpeechMapper()
    in_one.feed(recording)
    in_pieces = SpeechMapper()
    sizes = [1, 7, 333, 1000, 4097, 512, 160]
    offset = 0
    turn = 0
    while offset < len(recording):
        size = sizes[turn % len(sizes)] * 2
        in_pieces.feed(recording[offset : offset + size])
        offset += size
        turn += 1

    assert in_pieces.total_samples == in_one.total_samples
    assert in_pieces.finish() == in_one.finish()
    assert in_one.finish().has_speech is True
    assert in_pieces.silence_run_s() == in_one.silence_run_s()


# --------------------------------------------------------------------------
# condense
# --------------------------------------------------------------------------


def _map_of(pcm: bytes, *spans: tuple[int, int]) -> SpeechMap:
    return SpeechMap(spans=tuple(spans), total_samples=len(pcm) // 2, detector="energy")


def test_condense_without_speech_is_empty() -> None:
    pcm = _ramp(_samples(2.0))

    assert condense(pcm, _map_of(pcm)) == b""
    assert condense(b"", _map_of(b"")) == b""


def test_condense_cuts_the_silence_before_and_after() -> None:
    pcm = _ramp(_samples(4.0))

    out = condense(pcm, _map_of(pcm, (16_000, 40_000)))

    assert out == _cut(pcm, 16_000, 40_000)


@pytest.mark.parametrize("pause_s", [0.3, 1.0, 1.2])
def test_condense_leaves_a_short_pause_as_it_was(pause_s: float) -> None:
    """A recognizer punctuates by pauses, so an ordinary one is not touched."""
    pcm = _ramp(_samples(5.0))
    second_start = 20_000 + _samples(pause_s)

    out = condense(pcm, _map_of(pcm, (4_000, 20_000), (second_start, 70_000)))

    assert out == _cut(pcm, 4_000, 70_000)


def test_condense_shortens_a_long_pause_and_keeps_the_speech() -> None:
    """Half of the kept pause comes from its start and half from its end."""
    pcm = _ramp(_samples(8.0))
    first = (4_000, 20_000)
    second = (20_000 + _samples(3.0), 100_000)

    out = condense(pcm, _map_of(pcm, first, second))

    assert out == (
        _cut(pcm, *first)
        + _cut(pcm, first[1], first[1] + _samples(0.25))
        + _cut(pcm, second[0] - _samples(0.25), second[0])
        + _cut(pcm, *second)
    )
    assert len(out) // 2 == (first[1] - first[0]) + _samples(0.5) + (second[1] - second[0])


def test_condense_takes_its_pause_lengths_from_the_caller() -> None:
    pcm = _ramp(_samples(4.0))
    first = (0, 16_000)
    second = (16_000 + _samples(0.5), 48_000)
    speech = _map_of(pcm, first, second)

    kept = condense(pcm, speech, max_pause_s=0.5, shortened_pause_s=0.1)
    shortened = condense(pcm, speech, max_pause_s=0.4, shortened_pause_s=0.1)

    assert kept == _cut(pcm, 0, 48_000)
    assert len(shortened) // 2 == 16_000 + _samples(0.1) + (48_000 - second[0])
    assert shortened.startswith(_cut(pcm, *first))
    assert shortened.endswith(_cut(pcm, *second))


@pytest.mark.parametrize("shortened_pause_s", [0.5, 0.3333, 0.07, 0.0001, 0.0])
def test_condense_always_returns_whole_samples(shortened_pause_s: float) -> None:
    """Half a sample would shift every byte after it and turn speech into noise."""
    # One byte more than whole samples, as a cut-off write would leave it.
    pcm = _ramp(_samples(6.0)) + b"\x01"
    speech = _map_of(pcm, (1_001, 9_999), (40_001, 55_555), (90_003, 96_000))

    out = condense(pcm, speech, shortened_pause_s=shortened_pause_s)

    assert len(out) % 2 == 0
    for start, end in speech.spans:
        assert _cut(pcm, start, end) in out


def test_condense_of_a_mapped_recording(speech_by_loudness: None) -> None:
    """Map and condense together: the long pause shrinks, the rest of the
    silence goes, and every mapped stretch of speech is still there."""
    recording = _silence(1.0) + _loud(1.0) + _silence(3.0) + _loud(1.0) + _silence(1.0)
    speech = map_speech(recording)

    out = condense(recording, speech)

    assert len(speech.spans) == 2
    assert len(out) / 2 / SAMPLE_RATE == pytest.approx(speech.speech_s + 0.5, abs=0.001)
    assert len(out) < len(recording) / 2
    for start, end in speech.spans:
        assert _cut(recording, start, end) in out
    assert condense(_silence(2.0), map_speech(_silence(2.0))) == b""
