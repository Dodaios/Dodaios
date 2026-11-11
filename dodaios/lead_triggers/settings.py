"""What the owner configured: the accept mode, per-source rules and prose policies."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Final

from .event import SOURCES

ACCEPT_MODES: Final[tuple[str, ...]] = ("off", "observe", "auto")
SOURCE_MODES: Final[tuple[str, ...]] = ("explicit_only", "candidate", "ignore")
DEFAULT_ACCEPT: Final[str] = "observe"
MAX_POLICIES: Final[int] = 50
MAX_POLICY_CHARS: Final[int] = 600
MAX_LIST: Final[int] = 200
DEFAULT_RATE_PER_MINUTE: Final[int] = 30
DEFAULT_DEDUPE_WINDOW_S: Final[int] = 600
#: The pollers that feed the intake, by the plugin whose connection they read with.
PRODUCERS: Final[tuple[str, ...]] = ("gmail", "google_calendar", "github", "agentmail")
DEFAULT_POLL_INTERVAL_S: Final[int] = 180
MIN_POLL_INTERVAL_S: Final[int] = 60
MAX_POLL_INTERVAL_S: Final[int] = 3600


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    seen: dict[str, None] = {}
    for item in value:
        text = str(item).strip().lower()
        if text:
            seen[text[:200]] = None
    return tuple(seen)[:MAX_LIST]


@dataclass(frozen=True)
class SourceRule:
    """Stage 1 rule of one source.

    ``explicit_only``: the source only matters when the person asks (handled by
    the normal conversation); no trigger is considered. ``candidate``: the
    event goes on to the policies. ``ignore``: dropped on arrival.
    """

    mode: str = "explicit_only"
    #: Allow-lists; empty means "anyone" / "anywhere". An entry is an address,
    #: a ``*`` pattern or a ``@domain`` suffix.
    senders: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "senders": list(self.senders), "scopes": list(self.scopes)}

    @classmethod
    def from_dict(cls, data: Any) -> SourceRule:
        if not isinstance(data, dict):
            return cls()
        mode = str(data.get("mode") or "").strip().lower()
        return cls(
            mode=mode if mode in SOURCE_MODES else "explicit_only",
            senders=_strings(data.get("senders")),
            scopes=_strings(data.get("scopes")),
        )


@dataclass(frozen=True)
class Policy:
    """One owner-written sentence: what to do when what happens."""

    id: str
    text: str
    #: Sources it applies to; empty means every source.
    sources: tuple[str, ...] = ()
    #: Promoted by the owner: acts even while the install is still observing.
    auto: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "sources": list(self.sources), "auto": self.auto}

    @classmethod
    def from_dict(cls, data: Any) -> Policy | None:
        if not isinstance(data, dict):
            return None
        text = " ".join(str(data.get("text") or "").split())[:MAX_POLICY_CHARS]
        if not text:
            return None
        pid = re.sub(r"[^a-z0-9_-]", "", str(data.get("id") or "").lower())[:32]
        sources = tuple(s for s in _strings(data.get("sources")) if s in SOURCES)
        return cls(
            id=pid or f"p{uuid.uuid4().hex[:6]}",
            text=text,
            sources=sources,
            auto=data.get("auto") is True,
        )

    def covers(self, source: str) -> bool:
        return not self.sources or source in self.sources


@dataclass(frozen=True)
class TriggerSettings:
    accept: str = DEFAULT_ACCEPT
    sources: dict[str, SourceRule] = field(default_factory=dict)
    policies: tuple[Policy, ...] = ()
    #: The owner's own addresses and handles: events they sent never trigger.
    self_senders: tuple[str, ...] = ()
    rate_per_minute: int = DEFAULT_RATE_PER_MINUTE
    dedupe_window_s: int = DEFAULT_DEDUPE_WINDOW_S
    #: Per poller on/off. A poller still needs its source to be a ``candidate``
    #: source and the accept mode not ``off`` before it asks the provider anything.
    producers: dict[str, bool] = field(default_factory=dict)
    poll_interval_s: int = DEFAULT_POLL_INTERVAL_S
    #: The lead's own mail address (an inbox the owner created for it) and who may
    #: send it requests; empty senders fall back to ``self_senders``.
    agent_address: str = ""
    agent_senders: tuple[str, ...] = ()

    def producer_enabled(self, producer: str) -> bool:
        return self.producers.get(producer, True)

    def rule(self, source: str) -> SourceRule:
        return self.sources.get(source, SourceRule())

    def policy(self, policy_id: str) -> Policy | None:
        return next((p for p in self.policies if p.id == policy_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accept": self.accept,
            "sources": {s: self.rule(s).to_dict() for s in SOURCES},
            "policies": [p.to_dict() for p in self.policies],
            "self_senders": list(self.self_senders),
            "rate_per_minute": self.rate_per_minute,
            "dedupe_window_s": self.dedupe_window_s,
            "producers": {p: self.producer_enabled(p) for p in PRODUCERS},
            "poll_interval_s": self.poll_interval_s,
            "agent_address": self.agent_address,
            "agent_senders": list(self.agent_senders),
        }

    @classmethod
    def from_dict(cls, data: Any) -> TriggerSettings:
        if not isinstance(data, dict):
            return cls()
        accept = str(data.get("accept") or "").strip().lower()
        raw_sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
        raw_producers = data.get("producers") if isinstance(data.get("producers"), dict) else {}
        policies: list[Policy] = []
        for raw in data.get("policies") or []:
            policy = Policy.from_dict(raw)
            if policy is not None and all(policy.id != p.id for p in policies):
                policies.append(policy)
        return cls(
            accept=accept if accept in ACCEPT_MODES else DEFAULT_ACCEPT,
            sources={s: SourceRule.from_dict(raw_sources.get(s)) for s in SOURCES},
            policies=tuple(policies[:MAX_POLICIES]),
            self_senders=_strings(data.get("self_senders")),
            rate_per_minute=_positive(data.get("rate_per_minute"), DEFAULT_RATE_PER_MINUTE),
            dedupe_window_s=_positive(data.get("dedupe_window_s"), DEFAULT_DEDUPE_WINDOW_S),
            producers={p: raw_producers.get(p) is not False for p in PRODUCERS},
            poll_interval_s=min(
                MAX_POLL_INTERVAL_S,
                max(MIN_POLL_INTERVAL_S,
                    _positive(data.get("poll_interval_s"), DEFAULT_POLL_INTERVAL_S)),
            ),
            agent_address=_address(data.get("agent_address")),
            agent_senders=_strings(data.get("agent_senders")),
        )


def _positive(value: Any, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):  # a non-number keeps the default
        return fallback
    return number if number > 0 else fallback


def _address(value: Any) -> str:
    """One plain mail address, or empty when the text is not one."""
    text = str(value or "").strip().lower()
    return text[:200] if re.fullmatch(r"[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+", text) else ""
