"""The ledger's vocabulary: kinds, statuses and one item."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

#: What an item is about. One switch per kind in the settings.
KINDS: Final[tuple[str, ...]] = (
    "birthday",  # birthdays and anniversaries
    "appointment",  # an appointment to book
    "renewal",  # renewal, subscription, expiry
    "bill",  # a bill or payment due
    "shopping",  # shopping or restock
    "document",  # a document or deadline
    "follow_up",  # a follow-up
)

NOTICED: Final[str] = "noticed"
PREPARED: Final[str] = "prepared"
WAITING: Final[str] = "waiting"  # shown to the owner, a draft waits for their yes
DONE: Final[str] = "done"
DISMISSED: Final[str] = "dismissed"
STATUSES: Final[tuple[str, ...]] = (NOTICED, PREPARED, WAITING, DONE, DISMISSED)
OPEN_STATUSES: Final[tuple[str, ...]] = (NOTICED, PREPARED, WAITING)

#: Kinds that come back every year; a finished one reopens for the next date.
RECURRING: Final[frozenset[str]] = frozenset({"birthday"})

_MAX_TITLE: Final[int] = 120
_SPACE = re.compile(r"\s+")


def clean(text: str, limit: int = _MAX_TITLE) -> str:
    """One line, no control characters, shortened: outside text is data."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text or ""))
    return _SPACE.sub(" ", text).strip()[:limit].rstrip()


def norm(text: str) -> str:
    return _SPACE.sub(" ", re.sub(r"[^\w\s]", " ", str(text or "").casefold())).strip()


@dataclass(frozen=True)
class Found:
    """What an extractor saw, before it is in the ledger."""

    kind: str
    title: str
    due: date | None
    #: ``{"type": mail|calendar|vault|contact|open_loop|model, "ref": ..., ...}``.
    evidence: dict[str, Any] = field(default_factory=dict)
    #: The person or thing the item is about (birthday key, gift list).
    subject: str = ""

    @property
    def key(self) -> str:
        if self.kind in RECURRING:
            return f"{self.kind}|{norm(self.subject or self.title)}"
        return f"{self.kind}|{norm(self.title)}|{self.due.isoformat() if self.due else ''}"

    @property
    def item_id(self) -> str:
        return hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:16]  # noqa: S324 - an id, not security


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    title: str
    due: date | None
    status: str
    evidence: dict[str, Any]
    subject: str = ""
    draft: dict[str, Any] | None = None
    version: int = 1
    shown_version: int = 0
    created_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "due": self.due.isoformat() if self.due else None,
            "status": self.status,
            "evidence": self.evidence,
            "subject": self.subject,
            "draft": self.draft,
        }
