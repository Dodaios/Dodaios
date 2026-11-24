"""Group ``channel``: a two-way message channel (web UI, Telegram, ...).

Register under ``dodaios.channel``.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

ChannelMessageKind = Literal["text", "voice", "system", "action", "event_mirror"]


def _now_ns() -> int:
    return time.time_ns()


@dataclass(frozen=True, slots=True)
class ChannelMedia:
    """A picture or voice note that came with a message."""

    kind: Literal["image", "voice"]
    name: str
    data: bytes
    mime: str = ""


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    """A message flowing through a channel in either direction."""

    session_id: UUID
    kind: ChannelMessageKind
    content: str
    trace_id: UUID = field(default_factory=uuid4)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = field(default_factory=_now_ns)
    media: tuple[ChannelMedia, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelSession:
    """One connected conversation partner."""

    session_id: UUID
    channel_name: str
    user_handle: str = ""
    locale: str = "de"
    connected_at_ns: int = field(default_factory=_now_ns)


@runtime_checkable
class ChannelAdapter(Protocol):
    """Bidirectional message channel. ``broadcast_event`` receives a host event object."""

    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_message(self, msg: ChannelMessage) -> None: ...
    async def broadcast_event(self, event: Any) -> None: ...
    async def messages(self) -> AsyncIterator[ChannelMessage]: ...
    async def sessions(self) -> list[ChannelSession]: ...
