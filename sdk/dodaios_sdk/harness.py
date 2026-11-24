"""Group ``harness``: a sub-agent framework. Register under ``dodaios.harness``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .common import RiskTier


@dataclass(frozen=True, slots=True)
class HarnessTask:
    """A task handed to a harness."""

    prompt: str
    cwd: str = "."
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: int = 600
    risk_tier: RiskTier = "monitor"
    allow_computer_use: bool = False


@dataclass(frozen=True, slots=True)
class HarnessResult:
    """One element of the result stream; the last one has ``is_final=True``."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    cost_usd: float = 0.0
    duration_ms: int = 0
    is_final: bool = False


@runtime_checkable
class Harness(Protocol):
    """A sub-agent framework the host can start tasks on."""

    name: str
    version: str
    supports_versions: str  # PEP 440 specifier, e.g. ">=2.0,<3.0"

    async def health(self) -> bool:
        """Whether the harness is available and callable."""
        ...

    async def invoke(self, task: HarnessTask) -> AsyncIterator[HarnessResult]:
        """Run a task, streaming progress and the final result."""
        ...

    async def cancel(self) -> None:
        """Cancel the running task."""
        ...
