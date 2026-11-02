"""Data types of the personal memory vault (ADR-0044)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

#: What a memory is about. The profile block and the UI group by it.
KINDS: tuple[str, ...] = (
    "profile",  # who the user is: name, role, home, languages
    "preference",  # likes, dislikes, how they want things done
    "relationship",  # people and how they relate to the user
    "project",  # ongoing goals, plans, deadlines, decisions
    "procedural",  # standing rules and corrections for the assistant
    "episode",  # a notable event or conversation
    "reference",  # where things are: accounts, places, files
    "ephemeral",  # true for a short while; carries an end date
)

#: Who put the memory there.
ORIGINS: tuple[str, ...] = ("user", "inferred", "imported")

#: ``sensitive`` memories never enter the always-on profile block.
SENSITIVITIES: tuple[str, ...] = ("normal", "sensitive")

_SPACE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """One canonical spelling of a memory sentence, for duplicate detection."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = _SPACE.sub(" ", folded).strip()
    return folded.rstrip(" .!")


def content_hash(kind: str, text: str) -> str:
    """Stable id of what a memory says, independent of when it was said."""
    digest = hashlib.sha256(f"{kind}\n{normalize_text(text)}".encode()).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True)
class Memory:
    """One atomic memory: a single sentence about the user or their world."""

    id: str
    content_hash: str
    kind: str
    text: str
    recorded_at: str
    origin: str
    entities: tuple[str, ...] = ()
    scope: str = "global"
    valid_from: str | None = None
    valid_to: str | None = None
    expired_at: str | None = None
    supersedes_id: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    sensitivity: str = "normal"
    pinned: bool = False
    use_count: int = 0
    last_used_at: str | None = None

    def is_current(self, now: str) -> bool:
        """True while the memory is neither replaced nor past its end date."""
        if self.expired_at is not None:
            return False
        return self.valid_to is None or self.valid_to > now

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entities"] = list(self.entities)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Memory:
        known = {f for f in cls.__dataclass_fields__}
        values = {k: v for k, v in data.items() if k in known}
        values["entities"] = tuple(values.get("entities") or ())
        values["pinned"] = bool(values.get("pinned", False))
        values["source"] = dict(values.get("source") or {})
        return cls(**values)

    def source_json(self) -> str:
        return json.dumps(self.source, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class WriteResult:
    """What a write did.

    ``action`` is one of ``added``, ``existing`` (the same memory was already
    current), ``superseded``, ``refused`` (it looked like a secret) or
    ``blocked`` (the user had told the assistant to forget it).
    """

    action: str
    memory: Memory | None = None
    reason: str = ""


@dataclass(frozen=True)
class SearchHit:
    memory: Memory
    score: float
