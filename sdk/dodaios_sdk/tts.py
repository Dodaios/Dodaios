"""Group ``tts``: text to speech.

Implement :class:`TTSProvider` and register the class under ``dodaios.tts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .common import AudioChunk


@runtime_checkable
class TTSProvider(Protocol):
    """Text-to-speech, local or cloud."""

    name: str
    supports_streaming: bool

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        language_code: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        """Yield audio chunks for ``text``.

        ``language_code`` is a BCP-47 code such as ``"de-DE"``; ``None`` means
        unpinned (auto-detect). The keyword is part of the contract.
        """
        ...

    def list_voices(self, language: str | None = None) -> list[str]:
        """Voices on offer, optionally filtered by language."""
        ...
