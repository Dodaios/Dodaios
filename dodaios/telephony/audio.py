"""Audio transcode helpers for the Twilio Media Streams bridge.

Twilio Media Streams carry 8 kHz mono 8-bit **mu-law** PCM, base64-encoded.
A realtime voice session takes and gives 16-bit linear PCM at its provider's
rates. This module owns the codec and the outbound resample between them; the
session resamples the caller's 8 kHz audio itself.

Conversions use the stdlib ``audioop`` module (Python 3.11/3.12 here). On Python
3.13+ ``audioop`` is removed from the stdlib; the ``[telephony]`` extra then
pulls in the ``audioop-lts`` backport (declared in ``pyproject.toml``). The
import below transparently falls back to it.

State discipline (AD-T5): ``audioop.ratecv`` is stateful — feeding it audio
in chunks without carrying its filter state forward produces clicks at every
chunk boundary. ``Resampler`` holds that state per stream + direction.
"""

from __future__ import annotations

from typing import Any

try:  # stdlib on <=3.12, backport ("audioop-lts") on >=3.13
    import audioop
except ModuleNotFoundError:  # pragma: no cover - exercised only on 3.13+
    import audioop_lts as audioop  # type: ignore[no-redef]

# Twilio Media Streams wire format.
TWILIO_SAMPLE_RATE: int = 8_000

# int16 is 2 bytes/sample.
_WIDTH = 2


# ---------------------------------------------------------------------------
# mu-law <-> linear PCM
# ---------------------------------------------------------------------------


def ulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    """Decode 8-bit mu-law bytes to 16-bit linear PCM (same sample rate)."""
    if not ulaw_bytes:
        return b""
    return audioop.ulaw2lin(ulaw_bytes, _WIDTH)


def pcm16_to_ulaw(pcm_bytes: bytes) -> bytes:
    """Encode 16-bit linear PCM to 8-bit mu-law (same sample rate)."""
    if not pcm_bytes:
        return b""
    return audioop.lin2ulaw(pcm_bytes, _WIDTH)


# ---------------------------------------------------------------------------
# Stateful resampler (one instance per stream + direction)
# ---------------------------------------------------------------------------


class Resampler:
    """Carries ``audioop.ratecv`` state across chunks for one direction.

    The outbound leg of a call (the provider's output rate -> 8 kHz) keeps one
    instance for the whole answer, which eliminates the per-chunk click a
    stateless resample causes.
    """

    def __init__(self, from_rate: int, to_rate: int, *, channels: int = 1) -> None:
        self.from_rate = from_rate
        self.to_rate = to_rate
        self.channels = channels
        # Opaque ``audioop.ratecv`` filter state; carried back into ratecv as-is.
        self._state: Any = None

    def process(self, pcm16: bytes) -> bytes:
        """Resample one chunk of int16 PCM, carrying filter state forward."""
        if not pcm16:
            return b""
        if self.from_rate == self.to_rate:
            return pcm16
        converted, self._state = audioop.ratecv(
            pcm16, _WIDTH, self.channels, self.from_rate, self.to_rate, self._state
        )
        return converted

    def reset(self) -> None:
        """Drop accumulated filter state (e.g. after a barge-in flush)."""
        self._state = None


def resample_pcm16(pcm16: bytes, from_rate: int, to_rate: int) -> bytes:
    """Stateless one-shot resample. Use ``Resampler`` for streaming legs."""
    return Resampler(from_rate, to_rate).process(pcm16)


__all__ = [
    "TWILIO_SAMPLE_RATE",
    "Resampler",
    "pcm16_to_ulaw",
    "resample_pcm16",
    "ulaw_to_pcm16",
]
