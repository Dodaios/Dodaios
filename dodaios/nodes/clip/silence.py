"""The quiet parts of a recording, so a take can be cut down to what is said.

The level is measured in 20 ms windows. What counts as quiet adapts to the
recording: a room tone is louder in one take than in another, so the bar is
12 dB above the quietest tenth of the recording, never below -45 dBFS. A
quiet stretch shorter than ``min_silence`` is a breath between words and
stays; ``pad`` of every quiet stretch is kept on both sides, so a cut never
clips the first or last sound of a word.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from dodaios.nodes.clip.media import read_audio

_RATE: Final[int] = 16_000
_WINDOW_S: Final[float] = 0.02
_FLOOR_DB: Final[float] = -45.0
_ABOVE_QUIET_DB: Final[float] = 12.0


def quiet_windows(samples: Any, rate: int = _RATE) -> tuple[Any, float]:
    """Which 20 ms windows of mono ``samples`` are quiet, and the bar in dBFS."""
    import numpy as np

    mono = samples[0] if samples.ndim == 2 else samples
    window = max(1, int(rate * _WINDOW_S))
    count = mono.shape[0] // window
    if count == 0:
        return np.zeros(0, dtype=bool), _FLOOR_DB
    frames = mono[: count * window].reshape(count, window).astype(np.float64)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    level = 20 * np.log10(np.maximum(rms, 1e-9))
    bar = max(_FLOOR_DB, float(np.percentile(level, 10)) + _ABOVE_QUIET_DB)
    # A recording that is loud all through (music, a steady tone) has no pauses:
    # the bar stays clearly under its loud parts.
    bar = min(bar, float(np.percentile(level, 95)) - 10.0)
    return level < bar, bar


def spans_of(
    quiet: Any, window_s: float, min_silence: float, pad: float
) -> list[tuple[float, float]]:
    """Runs of quiet windows as ``(start, end)`` seconds, padded and filtered."""
    spans: list[tuple[float, float]] = []
    run_start: int | None = None
    flags = list(bool(flag) for flag in quiet) + [False]
    for index, flag in enumerate(flags):
        if flag and run_start is None:
            run_start = index
        elif not flag and run_start is not None:
            start, end = run_start * window_s, index * window_s
            # The recording's own edges need no padding: nothing is said beyond them.
            inner_start = start + (pad if run_start > 0 else 0.0)
            inner_end = end - (pad if index < len(flags) - 1 else 0.0)
            if inner_end - inner_start >= min_silence:
                spans.append((round(inner_start, 3), round(inner_end, 3)))
            run_start = None
    return spans


def find_silences(
    path: Path,
    start: float = 0.0,
    end: float | None = None,
    min_silence: float = 0.5,
    pad: float = 0.12,
) -> list[tuple[float, float]]:
    """The quiet stretches of ``path`` between ``start`` and ``end``, in source seconds."""
    samples = read_audio(Path(path), start, end, rate=_RATE, channels=1)
    quiet, _ = quiet_windows(samples)
    return [
        (round(start + a, 3), round(start + b, 3))
        for a, b in spans_of(quiet, _WINDOW_S, max(0.05, min_silence), max(0.0, pad))
    ]


__all__ = ["find_silences", "quiet_windows", "spans_of"]
