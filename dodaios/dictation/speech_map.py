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
        return any(self._live)

    def silence_run_s(self) -> float:
        """How long the recording has been without speech at its end."""
        run = 0
        for flag in reversed(self._live):
            if flag:
                break
            run += 1
        return (run * _FRAME + self._pending.size) / SAMPLE_RATE

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
    if not speech.spans:
        return b""
    longest = max(0, int(max_pause_s * SAMPLE_RATE))
    half = max(0, int(shortened_pause_s * SAMPLE_RATE)) // 2
    parts: list[bytes] = []
    previous_end: int | None = None
    for start, end in speech.spans:
        if previous_end is not None:
            if start - previous_end <= longest:
                parts.append(pcm[previous_end * _BYTES_PER_SAMPLE : start * _BYTES_PER_SAMPLE])
            else:
                cut = previous_end + half
                parts.append(pcm[previous_end * _BYTES_PER_SAMPLE : cut * _BYTES_PER_SAMPLE])
                parts.append(pcm[(start - half) * _BYTES_PER_SAMPLE : start * _BYTES_PER_SAMPLE])
        parts.append(pcm[start * _BYTES_PER_SAMPLE : end * _BYTES_PER_SAMPLE])
        previous_end = end
    return b"".join(parts)


__all__ = ["SAMPLE_RATE", "SpeechMap", "SpeechMapper", "condense", "map_speech"]
