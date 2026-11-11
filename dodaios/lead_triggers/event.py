"""One normalized shape for everything that happens around the person.

Mail, calendar changes, code-host notifications and CI results, automation
events and chat messages that are not requests all become a
:class:`TriggerEvent` before anything decides what to do with them. The text
fields come from outside and are DATA: nothing here, and nothing downstream,
ever reads them as instructions.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Final

SOURCES: Final[tuple[str, ...]] = ("mail", "calendar", "github", "automation", "channel")
_MAX_SUMMARY: Final[int] = 300
_MAX_FIELD: Final[int] = 200
_MAX_IDS: Final[int] = 8


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


@dataclass(frozen=True, slots=True)
class TriggerEvent:
    source: str
    #: The repo, calendar, mailbox or chat the event belongs to.
    scope: str = ""
    sender: str = ""
    #: The conversation / PR / invite the event continues; events that share it
    #: are one thread.
    thread_key: str = ""
    summary: str = ""
    ids: tuple[str, ...] = ()
    received_at: float = field(default_factory=time.time)
    #: Where the full item can be read again (a URL or a tool reference); the
    #: event itself never carries the body.
    raw_ref: str = ""
    #: A machine author (bot, no-reply, automation), not a person.
    is_bot: bool = False

    @property
    def event_id(self) -> str:
        """A stable id: the producer's first id, else a hash of the content."""
        if self.ids:
            return f"{self.source}:{self.ids[0]}"
        digest = hashlib.sha256(
            f"{self.source}|{self.scope}|{self.sender}|{self.thread_key}|{self.summary}".encode()
        ).hexdigest()
        return f"{self.source}:h{digest[:16]}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ids"] = list(self.ids)
        data["event_id"] = self.event_id
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TriggerEvent:
        return normalize(str(data.get("source") or ""), data)


def normalize(source: str, payload: Mapping[str, Any]) -> TriggerEvent:
    """Build an event from any producer's payload; unknown keys are ignored.

    Raises ``ValueError`` for a source outside :data:`SOURCES`.
    """
    source = source.strip().lower()
    if source not in SOURCES:
        raise ValueError(f"unknown trigger source {source!r}")

    def pick(*keys: str) -> str:
        for key in keys:
            if payload.get(key):
                return _clip(payload[key], _MAX_FIELD)
        return ""

    raw_ids = payload.get("ids")
    ids = [str(i) for i in raw_ids] if isinstance(raw_ids, list | tuple) else []
    single = pick("id", "message_id", "event_id", "delivery_id")
    if single and single not in ids:
        ids.insert(0, single)
    received = payload.get("received_at")
    return TriggerEvent(
        source=source,
        scope=pick("scope", "repo", "calendar", "mailbox", "chat"),
        sender=pick("sender", "from", "author", "organizer"),
        thread_key=pick("thread_key", "thread_id", "threadId", "thread", "pr", "conversation"),
        summary=_clip(
            payload.get("summary") or payload.get("subject") or payload.get("title"),
            _MAX_SUMMARY,
        ),
        ids=tuple(_clip(i, _MAX_FIELD) for i in ids[:_MAX_IDS]),
        received_at=float(received) if isinstance(received, int | float) else time.time(),
        raw_ref=pick("raw_ref", "url", "html_url"),
        is_bot=bool(payload.get("is_bot") or payload.get("bot")),
    )


def source_of_hook(event_name: str) -> str:
    """The source an integration event name belongs to (``mail.received`` -> ``mail``)."""
    head = event_name.strip().lower().replace("_", ".").split(".", 1)[0]
    if head in ("gmail", "email"):
        return "mail"
    if head in ("gcal", "cal"):
        return "calendar"
    if head in ("git", "ci"):
        return "github"
    return head if head in SOURCES else "automation"
