"""Group ``brain``: a language-model provider.

Implement :class:`Brain` and register the class under ``dodaios.brain``.
Every answer is a stream: a provider that cannot stream yields one delta.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ImageBlock:
    """An image input. ``data_b64`` is base64 of the raw bytes, no data-URI prefix."""

    mime: str
    data_b64: str
    source_hash: str = ""


@dataclass(frozen=True, slots=True)
class BrainMessage:
    """One message of the conversation."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str | list[dict[str, Any]]
    tool_call_id: str | None = None
    name: str | None = None
    images: tuple[ImageBlock, ...] = ()


#: Reasoning levels, ascending. A provider without a knob ignores it; one that
#: lacks a level uses the nearest it has.
ReasoningEffort = Literal[
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "ultracode"
]


@dataclass(frozen=True, slots=True)
class BrainRequest:
    """What the host asks of a brain."""

    messages: tuple[BrainMessage, ...]
    tools: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    system: str | None = None
    temperature: float = 0.7
    max_tokens: int = 32_768
    stream: bool = True
    reasoning_effort: ReasoningEffort | None = None


@dataclass(frozen=True, slots=True)
class BrainDelta:
    """One stream chunk: text, a tool call, or the finish signal."""

    content: str | None = None
    tool_call: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None  # input_tokens, output_tokens, cache_hit_tokens


@runtime_checkable
class Brain(Protocol):
    """An LLM provider."""

    name: str
    context_window: int
    supports_tools: bool
    supports_vision: bool

    # Declared without ``async``: implementations are async generators, so the
    # call returns the iterator directly (``async for d in brain.complete(r)``).
    def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        """Stream a response. With ``stream=False`` everything is in the first delta."""
        ...

    def estimate_cost(self, req: BrainRequest) -> float:
        """Rough cost in USD; 0.0 for local models."""
        ...
