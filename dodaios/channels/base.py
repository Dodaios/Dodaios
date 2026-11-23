"""Channel base types (dataclasses) + re-export of the protocol.

All dataclasses are ``frozen=True, slots=True`` — consistent with the rest
of the codebase (see :mod:`dodaios.core.protocols` and
:mod:`dodaios.core.events`). Immutability is a prerequisite for
flight-recorder replay.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID, uuid4

from dodaios.core.protocols import ChannelAdapter

__all__ = [
    "FIRST_CONTACT_CLOCK_SKEW_S",
    "FIRST_CONTACT_PAIRING_WINDOW_S",
    "ChannelAdapter",
    "ChannelMedia",
    "ChannelMessage",
    "ChannelSession",
    "sent_in_pairing_window",
]

#: How long after a chat channel comes up (app start, or the fresh instance a
#: marketplace connect builds) its EMPTY allowlist may still be claimed by the
#: first direct message. Messaging the bot is prompting Jarvis with its tools,
#: and a bot's username is public, so an unbounded first-contact claim let any
#: stranger who found the bot before its owner did take it over for good. The
#: owner pairs right after connecting; after this window an empty allowlist
#: stays closed until the next start or reconnect.
FIRST_CONTACT_PAIRING_WINDOW_S = 600.0

#: A message's own send time may run this far behind this computer's clock and
#: still count as sent inside the pairing window: the chat service and this
#: computer do not share a clock.
FIRST_CONTACT_CLOCK_SKEW_S = 120.0


def sent_in_pairing_window(opened_at: float, sent_at: float | None) -> bool:
    """Whether a first-contact message was sent after the pairing window opened.

    A chat service keeps the messages for a bot that is offline and hands them
    over when it connects. Such a message was not written to the channel that
    has just come up, so it must not claim the empty allowlist: only a message
    sent while the window is open counts. ``opened_at`` and ``sent_at`` are
    seconds since the epoch; a message without a readable send time never
    counts.
    """
    return sent_at is not None and sent_at >= opened_at - FIRST_CONTACT_CLOCK_SKEW_S


def _now_ns() -> int:
    return time.time_ns()


ChannelMessageKind = Literal["text", "voice", "system", "action", "event_mirror"]


@dataclass(frozen=True, slots=True)
class ChannelMedia:
    """A picture or a voice note that came with an inbound chat message.

    ``kind="image"`` travels to the turn as an attachment (and is drawn in the
    app's chat); ``kind="voice"`` is transcribed and becomes the message text.
    """

    kind: Literal["image", "voice"]
    name: str
    data: bytes
    mime: str = ""


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    """A message flowing through a channel in either direction.

    - ``kind="text"`` / ``"voice"``: user input from the UI.
    - ``kind="system"`` / ``"action"``: server -> client (status lines, tool runs).
    - ``kind="event_mirror"``: serialised bus event for UI rendering.

    ``media`` holds what came with an inbound message besides its text: the
    pictures and voice notes of a phone chat (see :class:`ChannelMedia`).
    """

    session_id: UUID
    kind: ChannelMessageKind
    content: str
    trace_id: UUID = field(default_factory=uuid4)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = field(default_factory=_now_ns)
    media: tuple[ChannelMedia, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelSession:
    """A connected client (a WebSocket session, a Telegram chat, ...)."""

    session_id: UUID
    channel_name: str
    user_handle: str = ""
    locale: str = "de"
    connected_at_ns: int = field(default_factory=_now_ns)
