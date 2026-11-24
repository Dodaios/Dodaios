"""Group ``turn``: end-of-turn detection. Register under ``dodaios.turn``.

The contract is declared; the host ships no provider for it yet.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .common import AudioChunk


@runtime_checkable
class TurnDetector(Protocol):
    """Decides when the person has finished speaking. Input is 16 kHz mono PCM."""

    name: str
    supports_semantic: bool  # True = model-based, False = silence only

    async def start(self) -> None:
        """Load the model (lazily)."""
        ...

    async def stop(self) -> None:
        """Release resources."""
        ...

    async def detect_end_of_turn(self, audio: AsyncIterator[AudioChunk]) -> bytes:
        """Consume frames until the turn ends; return the utterance as int16 PCM.

        A detector whose end-of-turn comes from the STT provider returns ``b""``.
        """
        ...
