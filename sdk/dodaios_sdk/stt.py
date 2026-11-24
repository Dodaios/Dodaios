"""Group ``stt``: speech to text.

Implement :class:`STTProvider` and register the class under the entry-point
group ``dodaios.stt``. The host builds the class with no arguments.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .common import AudioChunk


@dataclass(frozen=True, slots=True)
class Transcript:
    """One recognition result.

    ``text`` is what a consumer normally reads (the provider may clean it).
    ``raw_text`` is what the recognizer returned; leave it empty when you do
    not filter. ``language`` is a code such as ``"de"`` or ``"en"``.
    """

    text: str
    language: str
    confidence: float
    is_partial: bool = False
    segments: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    raw_text: str = ""


@runtime_checkable
class STTProvider(Protocol):
    """Speech-to-text, local or cloud. Audio arrives as 16 kHz mono PCM chunks."""

    name: str
    supports_streaming: bool

    async def transcribe(self, audio: AsyncIterator[AudioChunk]) -> Transcript:
        """Read the whole input, then return one final transcript."""
        ...

    async def stream_transcribe(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        """Yield partial transcripts, then the final one."""
        ...
