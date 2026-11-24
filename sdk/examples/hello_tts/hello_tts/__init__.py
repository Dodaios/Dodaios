"""A tiny TTS plugin: one 100 ms tone per character. Needs only dodaios-sdk."""

from __future__ import annotations

import math
import struct
import time
from collections.abc import AsyncIterator

from dodaios_sdk import AudioChunk

_RATE = 24_000


class HelloTTS:
    """Satisfies ``dodaios_sdk.TTSProvider``."""

    name = "hello"
    supports_streaming = True

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        language_code: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        for ch in text:
            freq = 220 + (ord(ch) % 32) * 20
            n = _RATE // 10
            pcm = b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / _RATE)))
                for i in range(n)
            )
            yield AudioChunk(pcm=pcm, sample_rate=_RATE, timestamp_ns=time.time_ns())

    def list_voices(self, language: str | None = None) -> list[str]:
        return ["beep"]
