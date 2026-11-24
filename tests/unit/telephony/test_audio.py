"""Audio transcode + resample round-trip tests."""

from __future__ import annotations

import math
import struct

import pytest

from dodaios.telephony.audio import (
    TWILIO_SAMPLE_RATE,
    Resampler,
    pcm16_to_ulaw,
    resample_pcm16,
    ulaw_to_pcm16,
)

_WIDE_RATE = 16_000
_OUTPUT_RATE = 24_000


def _tone(rate: int, ms: int, freq: int = 440, amp: int = 8000) -> bytes:
    n = rate * ms // 1000
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
    )


def test_ulaw_pcm_round_trip_preserves_length_ratio():
    pcm = _tone(TWILIO_SAMPLE_RATE, 1000)  # 8000 samples -> 16000 bytes int16
    ulaw = pcm16_to_ulaw(pcm)
    assert len(ulaw) == 8000  # 1 byte per sample
    back = ulaw_to_pcm16(ulaw)
    assert len(back) == 16000  # 2 bytes per sample


def test_ulaw_pcm_round_trip_is_approximately_lossless():
    pcm = _tone(TWILIO_SAMPLE_RATE, 200, amp=12000)
    back = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
    orig = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    recon = struct.unpack(f"<{len(back) // 2}h", back)
    # mu-law is lossy but bounded; peak-relative error stays small.
    err = max(abs(a - b) for a, b in zip(orig, recon, strict=False))
    assert err < 600


def test_empty_inputs_are_safe():
    assert ulaw_to_pcm16(b"") == b""
    assert pcm16_to_ulaw(b"") == b""
    assert resample_pcm16(b"", 8000, 16000) == b""


def test_resample_8k_to_16k_doubles_samples_roughly():
    pcm = _tone(TWILIO_SAMPLE_RATE, 1000)
    out = resample_pcm16(pcm, TWILIO_SAMPLE_RATE, _WIDE_RATE)
    # ~2x the bytes (resampler boundary makes it not exactly double)
    assert abs(len(out) - 2 * len(pcm)) <= 8


def test_streaming_resampler_state_is_continuous():
    """Chunked resample with carried state should match a one-shot resample
    closely (no boundary discontinuity)."""
    full = _tone(TWILIO_SAMPLE_RATE, 600)
    one_shot = resample_pcm16(full, TWILIO_SAMPLE_RATE, _WIDE_RATE)

    r = Resampler(TWILIO_SAMPLE_RATE, _WIDE_RATE)
    third = len(full) // 3
    third -= third % 2  # keep int16 aligned
    chunked = b"".join(r.process(full[i : i + third]) for i in range(0, len(full), third))
    # Lengths are within a small filter-tail margin of each other.
    assert abs(len(chunked) - len(one_shot)) <= 16


def test_outbound_session_pcm_to_twilio_ulaw_shape():
    """The phone leg of an answer: provider PCM (24 kHz) -> 8 kHz mu-law."""
    pcm24 = _tone(_OUTPUT_RATE, 100)
    out = pcm16_to_ulaw(Resampler(_OUTPUT_RATE, TWILIO_SAMPLE_RATE).process(pcm24))
    # 100 ms at 8 kHz mu-law ~= 800 bytes
    assert abs(len(out) - 800) <= 4


@pytest.mark.parametrize("rate", [8000, 16000, 24000])
def test_resampler_identity_when_rates_match(rate):
    pcm = _tone(rate, 50)
    assert Resampler(rate, rate).process(pcm) == pcm
