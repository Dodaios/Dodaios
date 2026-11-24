"""Group ``tool``: one action the assistant can take. Register under ``dodaios.tool``.

Optional extension (read with ``getattr``, not part of the structural check):
``risk_tier_for_args(self, args) -> RiskTier`` refines the tier per call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from .common import RiskTier


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Passed to a tool at execution time."""

    trace_id: UUID
    user_utterance: str
    config: dict[str, Any]
    memory_read: Any  # read-only memory handle
    approved_by: str | None = None  # "auto" | "user" | None


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool returns. ``receipt`` is set by the host, never by a tool."""

    success: bool
    output: Any
    error: str | None = None
    artifacts: tuple[str, ...] = field(default_factory=tuple)
    receipt: dict[str, Any] | None = None


@runtime_checkable
class Tool(Protocol):
    """A single action: ``open_app``, ``search_web``, ..."""

    name: str
    schema: dict[str, Any]  # JSON schema of ``args`` for LLM tool use
    description: str
    risk_tier: RiskTier

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        """Run the action."""
        ...
