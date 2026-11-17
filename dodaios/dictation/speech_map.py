"""Where the speech is in one dictation recording.

A recognizer handed silence invents text: a credit line, a "Thank you.", three
dots for every pause. So the recording is mapped before it is recognized:

* a recording without speech is never sent to a recognizer at all;
* silence before the first and after the last word is cut off;
* a long pause inside the recording is shortened to a short one.

The map is built while the microphone is open (:meth:`SpeechMapper.feed`), so
it costs no time after the stop.

Speech is found with the Silero model that ships with the app, on the CPU.
Where that model or its runtime cannot load, the loudness of the recording
decides instead: less exact, and tuned to keep quiet speech rather than to cut
every pause.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("dodaios.dictation.speech_map")

SAMPLE_RATE = 16_000
_BYTES_PER_SAMPLE = 2
#: Silero reads 512 samples (32 ms) at a time, plus 64 samples of context.
_FRAME = 512
_CONTEXT = 64

#: A frame at or above this is speech; a run of speech ends below ``_OFF``.
_ON = 0.5
_OFF = 0.35
#: Speech shorter than this is a click, not a word.
_MIN_SPEECH_S = 0.12
#: Two stretches of speech closer than this are one stretch.
_MERGE_GAP_S = 0.25
#: Kept on both sides of every stretch, so a soft first or last sound stays.
_PAD_S = 0.2

#: Loudness detector: a frame is speech above this share of the loudest frame
#: and above this multiple of the quietest tenth, whichever is higher.
_ENERGY_PEAK_SHARE = 0.06
_ENERGY_FLOOR_FACTOR = 3.0
#: Below this loudness (about -52 dBFS) nothing was recorded but the room.
_ENERGY_ABSOLUTE_MIN = 0.0025
#: A moment between two words is at most this share as loud as the speech
#: around it, measured over this many frames (about a second) on both sides.
_DIP_SHARE = 0.25
_DIP_CONTEXT_FRAMES = 30


@dataclass(frozen=True, slots=True)
class SpeechMap:
    """The stretches of speech in a recording, as sample offsets."""

    spans: tuple[tuple[int, int], ...]
    total_samples: int
    detector: str

    @property
    def has_speech(self) -> bool:
        return bool(self.spans)

    @property
    def speech_s(self) -> float:
        return sum(end - start for start, end in self.spans) / SAMPLE_RATE

    @property
    def duration_s(self) -> float:
        return self.total_samples / SAMPLE_RATE


def _spans_from_flags(flags: np.ndarray, total_samples: int) -> tuple[tuple[int, int], ...]:
    """Frame-wise speech flags -> padded, merged sample spans."""
    if flags.size == 0 or not flags.any():
        return ()
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    runs = [
        (int(a) * _FRAME, int(b) * _FRAME)
        for a, b in zip(edges[::2], edges[1::2], strict=True)
    ]
    min_speech = int(_MIN_SPEECH_S * SAMPLE_RATE)
    merge_gap = int(_MERGE_GAP_S * SAMPLE_RATE)
    pad = int(_PAD_S * SAMPLE_RATE)
    merged: list[list[int]] = []
    for start, end in runs:
        if merged and start - merged[-1][1] <= merge_gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    spans: list[tuple[int, int]] = []
    for start, end in merged:
        if end - start < min_speech:
            continue
        start = max(0, start - pad)
        end = min(total_samples, end + pad)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    return tuple(spans)


def _hysteresis(probabilities: np.ndarray) -> np.ndarray:
    """Speech starts at ``_ON`` and lasts until a frame falls below ``_OFF``."""
    flags = np.zeros(probabilities.shape, dtype=bool)
    speaking = False
    for index, value in enumerate(probabilities):
        if speaking:
            speaking = value >= _OFF
        else:
            speaking = value >= _ON
        flags[index] = speaking
    return flags


class SpeechMapper:
    """Builds a :class:`SpeechMap` from the recording as it arrives."""

    def __init__(self) -> None:
        self._pending = np.zeros(0, dtype=np.float32)
        self._probabilities: list[float] = []
        self._levels: list[float] = []
        #: Frame-wise "speech" as judged while the audio arrived.
        self._live: list[bool] = []
        self._speaking = False
        self._speech_frames = 0
        self._peak = 0.0
        self._total_samples = 0
        self._session = None
        self._state: np.ndarray | None = None
        self._context: np.ndarray | None = None
        self._model_failed = False

    def _ensure_model(self) -> bool:
        if self._session is not None:
            return True
        if self._model_failed:
            return False
        try:
            import onnxruntime

            from dodaios.assets import bundled_silero_vad_model

            path = bundled_silero_vad_model()
            if path is None:
                raise RuntimeError("the speech model is not part of this install")
            options = onnxruntime.SessionOptions()
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            self._session = onnxruntime.InferenceSession(
                str(path), providers=["CPUExecutionProvider"], sess_options=options
            )
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
            self._context = np.zeros((1, _CONTEXT), dtype=np.float32)
        except Exception as exc:  # noqa: BLE001 - the loudness detector takes over
            self._model_failed = True
            self._session = None
            log.info(
                "Dictation speech model unavailable (%s: %s); judging by loudness.",
                type(exc).__name__,
                exc,
            )
            return False
        return True

    def _score(self, frame: np.ndarray) -> float:
        if not self._ensure_model():
            return -1.0
        try:
            assert self._session is not None and self._context is not None
            block = np.concatenate([self._context, frame.reshape(1, -1)], axis=1)
            out, state = self._session.run(
                None,
                {
                    "input": block,
                    "state": self._state,
                    "sr": np.array(SAMPLE_RATE, dtype=np.int64),
                },
            )
            self._state = state
            self._context = block[:, -_CONTEXT:]
            return float(np.asarray(out).reshape(-1)[0])
        except Exception as exc:  # noqa: BLE001 - the loudness detector takes over
            self._model_failed = True
            self._session = None
            log.info(
                "Dictation speech model failed (%s: %s); judging by loudness.",
                type(exc).__name__,
                exc,
            )
            return -1.0

    def feed(self, pcm: bytes) -> None:
        """Add 16 kHz mono int16 audio. Never raises."""
        if not pcm:
            return
        try:
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            self._total_samples += samples.size
            data = np.concatenate([self._pending, samples]) if self._pending.size else samples
            usable = (data.size // _FRAME) * _FRAME
            for offset in range(0, usable, _FRAME):
                frame = np.ascontiguousarray(data[offset : offset + _FRAME])
                level = float(np.sqrt(np.mean(np.square(frame))))
                score = self._score(frame)
                self._levels.append(level)
                self._probabilities.append(score)
                self._peak = max(self._peak, level)
                if score >= 0:
                    self._speaking = (
                        score >= (_OFF if self._speaking else _ON)
                        and level >= _ENERGY_ABSOLUTE_MIN / 2
                    )
                else:
                    self._speaking = level >= max(
                        _ENERGY_ABSOLUTE_MIN, self._peak * _ENERGY_PEAK_SHARE
                    )
                self._live.append(self._speaking)
                self._speech_frames += self._speaking
            self._pending = data[usable:].copy()
        except Exception:  # noqa: BLE001 - a map is a help, never a gate
            log.debug("dictation speech map: a chunk could not be read", exc_info=True)

    @property
    def total_samples(self) -> int:
        """Samples fed so far."""
        return self._total_samples

    @property
    def heard_speech(self) -> bool:
        """Whether any frame so far was judged speech."""
        return self._speech_frames > 0

    @property
    def speech_so_far_s(self) -> float:
        """Seconds judged speech since the recording began."""
        return self._speech_frames * _FRAME / SAMPLE_RATE

    def silence_run_s(self) -> float:
        """How long the recording has been without speech at its end."""
        run = 0
        for flag in reversed(self._live):
            if flag:
                break
            run += 1
        return (run * _FRAME + self._pending.size) / SAMPLE_RATE

    def pause_around(self, at: int) -> float:
        """How long the speaker is silent around sample ``at``, so far."""
        frames = len(self._live)
        frame = min(max(0, at // _FRAME), frames)
        first = frame
        while first > 0 and not self._live[first - 1]:
            first -= 1
        last = frame
        while last < frames and not self._live[last]:
            last += 1
        quiet = (last - first) * _FRAME
        if last == frames:
            quiet += self._pending.size  # audio the detector has not judged yet
        return quiet / SAMPLE_RATE

    def quiet_near(self, at: int, *, within_s: float, min_quiet_s: float) -> int | None:
        """The middle of the gap in the speech nearest to sample ``at``.

        A recognizer's own times for where a sentence ends are approximate. A
        cut placed in the nearest real gap falls between two words; one placed
        on the time itself may fall inside a word. ``None`` when no gap of at
        least ``min_quiet_s`` has its middle within ``within_s`` of ``at``.
        """
        frames = len(self._live)
        if not frames:
            return None
        centre = at / _FRAME
        reach = within_s * SAMPLE_RATE / _FRAME
        needed = max(1, round(min_quiet_s * SAMPLE_RATE / _FRAME))
        first = max(0, int(centre - reach) - needed)
        last = min(frames, int(centre + reach) + needed + 1)
        best: tuple[float, int] | None = None
        index = first
        while index < last:
            if self._live[index]:
                index += 1
                continue
            run_start = index
            while index < frames and not self._live[index]:
                index += 1
            if index - run_start < needed:
                continue
            middle = (run_start + index) / 2
            distance = abs(middle - centre)
            if distance <= reach and (best is None or distance < best[0]):
                best = (distance, int(middle * _FRAME))
        if best is not None:
            return min(best[1], self._total_samples)
        # No gap long enough to count as silence. Somebody who runs one
        # sentence into the next still drops the voice between them: the
        # quietest moment near ``at`` is that place, when it is clearly
        # quieter than the speech around it.
        low = max(0, int(centre - reach))
        high = min(len(self._levels), int(centre + reach) + 1)
        if high - low < 3:
            return None
        around = self._levels[max(0, low - _DIP_CONTEXT_FRAMES) : high + _DIP_CONTEXT_FRAMES]
        loud = float(np.percentile(np.asarray(around, dtype=np.float32), 75))
        quietest = min(range(low, high), key=lambda frame: self._levels[frame])
        if loud <= 0.0 or self._levels[quietest] > loud * _DIP_SHARE:
            return None
        return min(int((quietest + 0.5) * _FRAME), self._total_samples)

    def speech_between(self, start: int, end: int) -> float:
        """Seconds judged speech between two sample offsets."""
        first = max(0, start // _FRAME)
        last = min(len(self._live), -(-end // _FRAME))
        return sum(self._live[first:last]) * _FRAME / SAMPLE_RATE

    def _flags(self) -> tuple[np.ndarray, str]:
        levels = np.asarray(self._levels, dtype=np.float32)
        probabilities = np.asarray(self._probabilities, dtype=np.float32)
        if not self._model_failed and probabilities.size and (probabilities >= 0).all():
            # Judged frame by frame as the audio arrived; nothing to redo.
            return np.asarray(self._live, dtype=bool), "silero"
        peak = float(levels.max()) if levels.size else 0.0
        if peak < _ENERGY_ABSOLUTE_MIN:
            return np.zeros(levels.shape, dtype=bool), "energy"
        floor = float(np.percentile(levels, 10))
        threshold = max(
            _ENERGY_ABSOLUTE_MIN, peak * _ENERGY_PEAK_SHARE, floor * _ENERGY_FLOOR_FACTOR
        )
        # A recording that is loud throughout has no quiet tenth to compare
        # with; it is then kept whole rather than cut on a guess.
        if threshold >= peak:
            threshold = peak * _ENERGY_PEAK_SHARE
        return levels >= threshold, "energy"

    def map(self, start: int = 0, end: int | None = None) -> SpeechMap:
        """The speech between two sample offsets, relative to ``start``."""
        total = self._total_samples
        stop = total if end is None else max(0, min(end, total))
        begin = max(0, min(start, stop))
        length = stop - begin
        if not self._levels or length <= 0:
            # Shorter than one frame: nothing a person could have said.
            return SpeechMap(spans=(), total_samples=max(0, length), detector="none")
        flags, detector = self._flags()
        first = begin // _FRAME
        last = min(flags.size, -(-stop // _FRAME))
        spans = _spans_from_flags(flags[first:last], total)
        offset = first * _FRAME - begin
        relative: list[tuple[int, int]] = []
        for span_start, span_end in spans:
            a = max(0, span_start + offset)
            b = min(length, span_end + offset)
            if b > a:
                relative.append((a, b))
        return SpeechMap(spans=tuple(relative), total_samples=length, detector=detector)

    def finish(self) -> SpeechMap:
        """The map of everything fed so far."""
        return self.map()


def map_speech(pcm: bytes) -> SpeechMap:
    """Map a finished recording in one call."""
    mapper = SpeechMapper()
    mapper.feed(pcm)
    return mapper.finish()


def condense(
    pcm: bytes,
    speech: SpeechMap,
    *,
    max_pause_s: float = 1.2,
    shortened_pause_s: float = 0.5,
) -> bytes:
    """The recording without its silence, long pauses shortened.

    The speech itself is never touched, and a pause up to ``max_pause_s``
    stays as it was: pauses are what a recognizer punctuates by. A longer one
    is cut to ``shortened_pause_s``, half from its start and half from its
    end, so the room tone around the words stays natural. With no speech
    mapped the result is empty.
    """
    return condense_marked(
        pcm, speech, max_pause_s=max_pause_s, shortened_pause_s=shortened_pause_s
    )[0]


def condensed_ranges(
    speech: SpeechMap,
    *,
    max_pause_s: float = 1.2,
    shortened_pause_s: float = 0.5,
) -> list[tuple[int, int]]:
    """The stretches of a recording its condensed clip is made of, in order.

    Sample offsets into the recording, laid end to end exactly as
    :func:`condense_marked` joins them. With them a time in the clip can be
    traced back to where it was in the recording (:func:`recording_offset`).
    """
    longest = max(0, int(max_pause_s * SAMPLE_RATE))
    half = max(0, int(shortened_pause_s * SAMPLE_RATE)) // 2
    ranges: list[tuple[int, int]] = []
    previous_end: int | None = None
    for start, end in speech.spans:
        if previous_end is not None:
            if start - previous_end <= longest:
                ranges.append((previous_end, start))
            else:
                ranges.append((previous_end, previous_end + half))
                ranges.append((start - half, start))
        ranges.append((start, end))
        previous_end = end
    return [(a, b) for a, b in ranges if b > a]


def recording_offset(ranges: list[tuple[int, int]], clip_s: float) -> int | None:
    """Where ``clip_s`` seconds into a condensed clip was in the recording.

    ``None`` for a time outside the clip (in the padding behind it).
    """
    remaining = int(clip_s * SAMPLE_RATE)
    if remaining < 0:
        return None
    for start, end in ranges:
        length = end - start
        if remaining <= length:
            return start + remaining
        remaining -= length
    return None


def condense_marked(
    pcm: bytes,
    speech: SpeechMap,
    *,
    max_pause_s: float = 1.2,
    shortened_pause_s: float = 0.5,
    mark_pause_s: float = 2.0,
) -> tuple[bytes, list[float]]:
    """:func:`condense`, plus where its long pauses were.

    The second value lists, in seconds of the condensed clip, the middle of
    every pause that lasted at least ``mark_pause_s`` in the recording. Once
    shortened, such a pause can no longer be told from an ordinary one in the
    clip; the marks keep the fact that the speaker stopped for a while there,
    which is where a new paragraph most likely begins.
    """
    if not speech.spans:
        return b"", []
    longest = max(0, int(max_pause_s * SAMPLE_RATE))
    half = max(0, int(shortened_pause_s * SAMPLE_RATE)) // 2
    mark_at = max(0, int(mark_pause_s * SAMPLE_RATE))
    parts: list[bytes] = []
    marks: list[float] = []
    written = 0
    previous_end: int | None = None
    for start, end in speech.spans:
        if previous_end is not None:
            gap = start - previous_end
            if gap <= longest:
                kept = pcm[previous_end * _BYTES_PER_SAMPLE : start * _BYTES_PER_SAMPLE]
            else:
                cut = previous_end + half
                kept = (
                    pcm[previous_end * _BYTES_PER_SAMPLE : cut * _BYTES_PER_SAMPLE]
                    + pcm[(start - half) * _BYTES_PER_SAMPLE : start * _BYTES_PER_SAMPLE]
                )
            if gap >= mark_at:
                marks.append((written + len(kept) / _BYTES_PER_SAMPLE / 2) / SAMPLE_RATE)
            parts.append(kept)
            written += len(kept) // _BYTES_PER_SAMPLE
        chunk = pcm[start * _BYTES_PER_SAMPLE : end * _BYTES_PER_SAMPLE]
        parts.append(chunk)
        written += len(chunk) // _BYTES_PER_SAMPLE
        previous_end = end
    return b"".join(parts), marks


__all__ = [
    "SAMPLE_RATE",
    "SpeechMap",
    "SpeechMapper",
    "condense",
    "condense_marked",
    "condensed_ranges",
    "recording_offset",
    "map_speech",
]
