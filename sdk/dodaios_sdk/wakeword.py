"""Group ``wakeword``: wake-word detection. Register under ``dodaios.wakeword``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class WakeWordProvider(Protocol):
    """Detects wake words in the microphone stream."""

    name: str
    supported_keywords: tuple[str, ...]

    async def start(self) -> None:
        """Load the model and open the audio stream."""
        ...

    async def stop(self) -> None:
        """Stop cleanly and release resources."""
        ...

    async def stream(self) -> AsyncIterator[float]:
        """Yield confidence values (0.0 to 1.0); a high value means the wake word."""
        ...
