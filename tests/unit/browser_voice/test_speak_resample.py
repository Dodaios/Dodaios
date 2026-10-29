"""Off-rate TTS audio is resampled as ONE stream per utterance.

The French Piper voice speaks at 22,050 Hz and the browser plays 24 kHz. Each
chunk used to be resampled on its own (a fresh `audioop.ratecv` state), which
the telephony module documents as a per-chunk click at every boundary.
"""
from __future__ import annotations

import asyncio
import math
import struct

import pytest

from dodaios.browser_voice.audio import TTS_SAMPLE_RATE
from dodaios.core.protocols import AudioChunk
from dodaios.telephony.audio import Resampler

from tests.unit.browser_voice.test_session import _make_session, _Sink

PIPER_RATE = 22_050


def _tone(samples: int, start: int, amp: int = 6_000, freq: float = 220.0) -> bytes:
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * (start + i) / PIPER_RATE)))
        for i in range(samples)
    )


class _PiperLikeTTS:
    """Yields one continuous tone in uneven 22,050 Hz chunks, like the voice."""

    def __init__(self, sizes: list[int]) -> None:
        self.chunks: list[bytes] = []
        position = 0
        for size in sizes:
            self.chunks.append(_tone(size, position))
            position += size

    async def synthesize(self, text, language_code="fr-FR", voice=None):
        for pcm in self.chunks:
            yield AudioChunk(pcm=pcm, sample_rate=PIPER_RATE, timestamp_ns=0, channels=1)


@pytest.fixture(autouse=True)
def _unity_gain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measure the resampling alone: the output gain stage is left out."""
    from dodaios.audio import gain

    monkeypatch.setattr(gain, "apply_output_gain_pcm16", lambda pcm, *_a, **_k: pcm)


def test_chunks_are_resampled_as_one_continuous_stream() -> None:
    tts = _PiperLikeTTS([4_410, 1_103, 7_001, 2_205, 3_307])
    sink = _Sink()
    session = _make_session(sink, tts=tts)

    asyncio.run(session._speak("Bonjour"))  # i18n-allow: French fixture

    reference = Resampler(PIPER_RATE, TTS_SAMPLE_RATE)
    expected = b"".join(reference.process(pcm) for pcm in tts.chunks)
    assert b"".join(sink.binary) == expected


def test_every_utterance_starts_a_fresh_resampler() -> None:
    tts = _PiperLikeTTS([2_205, 2_205])
    sink = _Sink()
    session = _make_session(sink, tts=tts)

    asyncio.run(session._speak("Un"))  # i18n-allow: French fixture
    first = b"".join(sink.binary)
    sink.binary.clear()
    asyncio.run(session._speak("Un"))  # i18n-allow: French fixture
    assert b"".join(sink.binary) == first, "no filter state leaks into the next answer"
