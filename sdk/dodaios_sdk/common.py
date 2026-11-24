"""Types shared by more than one plugin group."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: How much a tool call or harness task needs the person's say-so.
RiskTier = Literal["safe", "monitor", "ask", "block"]


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """Raw PCM audio (signed 16-bit little endian) with sample rate and timestamp."""

    pcm: bytes
    sample_rate: int
    timestamp_ns: int
    channels: int = 1
