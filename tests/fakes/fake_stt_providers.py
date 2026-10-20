"""Speech-to-text provider doubles for the dictation lane and the fallback chain.

Each one honours the ``transcribe_pcm(pcm, language=...)`` contract the chain
and the lane call, and records what happened to it so a test can assert on the
provider's side of the story (asked? cancelled? how often?).
"""

from __future__ import annotations

import asyncio
from typing import Any

from dodaios.core.protocols import Transcript


class AnsweringSTT:
    """Answers every call with ``text``."""

    supports_concurrent_requests = True

    def __init__(self, text: str, *, language: str = "en") -> None:
        self.text = text
        self.language = language
        self.calls = 0
        self.audio_bytes: list[int] = []

    async def transcribe_pcm(
        self, pcm: bytes, sample_rate: int = 16_000, language: str | None = None
    ) -> Transcript:
        self.calls += 1
        self.audio_bytes.append(len(pcm))
        return Transcript(text=self.text, language=self.language, confidence=0.9)


class FailingSTT:
    """Raises ``error`` on every call."""

    supports_concurrent_requests = True

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    async def transcribe_pcm(
        self, pcm: bytes, sample_rate: int = 16_000, language: str | None = None
    ) -> Transcript:
        self.calls += 1
        raise self.error


class WedgedSTT:
    """The 2026-10-20 local worker: takes the call and never answers.

    Serial like the on-device engine (``supports_concurrent_requests`` False),
    so the chain routes it through its per-provider lock.
    """

    supports_concurrent_requests = False
    runs_on_device = True

    def __init__(self) -> None:
        self.calls = 0
        self.cancelled = 0

    async def transcribe_pcm(
        self, pcm: bytes, sample_rate: int = 16_000, language: str | None = None
    ) -> Transcript:
        self.calls += 1
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        raise AssertionError("unreachable")  # pragma: no cover


class SlowSTT:
    """Answers ``text`` after ``delay_s`` — slow, but not wedged."""

    supports_concurrent_requests = True

    def __init__(self, text: str, delay_s: float) -> None:
        self.text = text
        self.delay_s = delay_s
        self.calls = 0

    async def transcribe_pcm(
        self, pcm: bytes, sample_rate: int = 16_000, language: str | None = None
    ) -> Transcript:
        self.calls += 1
        await asyncio.sleep(self.delay_s)
        return Transcript(text=self.text, language="en", confidence=0.9)


class RecordingBuilder:
    """``FallbackSTT``'s ``build`` callable over a fixed name → provider map."""

    def __init__(self, providers: dict[str, Any]) -> None:
        self._providers = dict(providers)
        self.built: list[str] = []

    def __call__(self, name: str) -> Any:
        self.built.append(name)
        return self._providers[name]


__all__ = [
    "AnsweringSTT",
    "FailingSTT",
    "RecordingBuilder",
    "SlowSTT",
    "WedgedSTT",
]
