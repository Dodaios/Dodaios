"""Seat health: what real calls taught us about one (provider, login) seat.

A *seat* is one provider under one account or login. Every real call outcome
(a brain turn, a coding-CLI turn, a society agent's run) is reported here, and
nothing in this module ever calls a provider: it is passive, like
:mod:`dodaios.brain.provider_health_ledger`, which feeds it for the brain's
own calls.

What is kept per seat (never an error body, a prompt or a key):

* the class of the last failure: ``quota`` (limit reached, with the reset time
  parsed from the message when it names one), ``rate_limit``, ``auth``,
  ``model_unavailable``, or ``other``;
* a verdict with an expiry. ``auth`` and ``model_unavailable`` hold for
  :data:`BLOCK_TTL_S`, or until the credential changes; ``quota`` holds until
  the parsed reset time (a bounded default when the message names none);
* a rolling 24 h count of failures per class and the current streak of
  same-class failures, which drives the one-time written notice.

Rules the readers rely on:

* A verdict never switches the owner's chosen provider. Callers use it to skip
  a dead FALLBACK, to make background work wait, to fail a preflight fast and
  to show a health line; the primary stays and its failure is reported.
* A success clears the seat at once.
* The record lives in memory and in ``DATA_DIR/state/seat_health.json`` so a
  restart keeps the verdicts. Nothing initialises at import time.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "BLOCK_TTL_S",
    "CLASS_AUTH",
    "CLASS_MODEL",
    "CLASS_OTHER",
    "CLASS_QUOTA",
    "CLASS_RATE",
    "NOTICE_STREAK",
    "SeatFailure",
    "SeatHealth",
    "SeatVerdict",
    "classify_seat_failure",
    "get_seat_health",
    "parse_reset_time",
    "set_seat_health",
]

CLASS_QUOTA: Final[str] = "quota"
CLASS_RATE: Final[str] = "rate_limit"
CLASS_AUTH: Final[str] = "auth"
CLASS_MODEL: Final[str] = "model_unavailable"
CLASS_OTHER: Final[str] = "other"
CLASSES: Final[tuple[str, ...]] = (CLASS_QUOTA, CLASS_RATE, CLASS_AUTH, CLASS_MODEL, CLASS_OTHER)

#: How long a dead key, a signed-out login or an unavailable model stands.
BLOCK_TTL_S: Final[float] = 6 * 3600.0
#: A transient rate limit clears on its own quickly.
RATE_COOLDOWN_S: Final[float] = 60.0
#: A quota hit that names no reset time: recheck after this long.
QUOTA_DEFAULT_S: Final[float] = 30 * 60.0
QUOTA_FIVE_HOUR_S: Final[float] = 60 * 60.0
QUOTA_WEEKLY_S: Final[float] = 6 * 3600.0
#: A parsed reset further away than this is not believed (a parse slip).
_MAX_RESET_S: Final[float] = 8 * 24 * 3600.0
_MIN_RESET_S: Final[float] = 30.0
#: Same-class failures in a row before one written notice goes to the lead.
NOTICE_STREAK: Final[int] = 3
_WINDOW_S: Final[float] = 24 * 3600.0
_RECENT_MAX: Final[int] = 60
FILE_NAME: Final[str] = "seat_health.json"
_FILE_VERSION: Final[int] = 1

_MODEL_RE = re.compile(
    r"(invalid model|model[^.\n]{0,60}(?:unavailable|not available|not supported|not found|"
    r"does not exist|no longer available)|unknown model|"
    r"selected model is (?:not|un)available|not available on this)",
    re.I,
)
_AUTH_EXTRA_RE = re.compile(
    r"(not logged in|log ?in required|login (?:expired|required)|please (?:log ?in|sign in)|"
    r"authentication failed|token (?:expired|revoked)|session expired|run [`'\"]?\w+ login)",
    re.I,
)
_QUOTA_EXTRA_RE = re.compile(
    r"(limit reached|usage limit|you(?:'|’)ve hit your|hit your (?:limit|usage)|"
    r"5[- ]hour limit|weekly limit|out of (?:usage|credits|messages))",
    re.I,
)

_UNIT_S: Final[dict[str, int]] = {
    "d": 86400, "day": 86400, "days": 86400,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
}
_DURATION_PART = r"(\d+(?:\.\d+)?)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b"
_RELATIVE_RE = re.compile(
    r"(?:try again|retry|resets?|available again|wait|come back)\s*(?:again\s*)?"
    r"(?:in|after)\s+((?:" + _DURATION_PART + r"[\s,]*(?:and\s+)?)+)",
    re.I,
)
_RETRY_AFTER_RE = re.compile(r"retry[- _]after\"?\s*[:=]?\s*\"?(\d+(?:\.\d+)?)\b", re.I)
_ABSOLUTE_RE = re.compile(
    r"resets?\s+(?:at\s+|around\s+|about\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?",
    re.I,
)


def _duration_seconds(text: str) -> float:
    total = 0.0
    for amount, unit in re.findall(_DURATION_PART, text, flags=re.I):
        total += float(amount) * _UNIT_S[unit.lower()]
    return total


def parse_reset_time(message: str | None, *, now: float | None = None) -> float | None:
    """The epoch second a limit message says the seat is usable again, or ``None``.

    Reads "try again in 2h 30m", "resets in 45 minutes", "retry-after: 120" and
    "resets 3pm" / "resets at 15:30" (the next such wall-clock time, local).
    """
    if not message:
        return None
    text = str(message)
    base = time.time() if now is None else now
    seconds: float | None = None
    match = _RELATIVE_RE.search(text)
    if match:
        seconds = _duration_seconds(match.group(1))
    else:
        match = _RETRY_AFTER_RE.search(text)
        if match:
            seconds = float(match.group(1))
        else:
            match = _ABSOLUTE_RE.search(text)
            if match:
                seconds = _seconds_until_clock(match, base)
    if seconds is None or seconds <= 0:
        return None
    seconds = max(_MIN_RESET_S, seconds)
    if seconds > _MAX_RESET_S:
        return None
    return base + seconds


def _seconds_until_clock(match: re.Match[str], base: float) -> float | None:
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower().replace(".", "")
    if meridiem and not 1 <= hour <= 12:
        return None
    if not meridiem and not match.group(2):
        return None  # "resets 3" alone is not a time
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    now = datetime.fromtimestamp(base)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def classify_seat_failure(error: BaseException | str | None) -> str:
    """Fold an error onto a seat class. Auth wins over quota ("check billing" in a 401)."""
    from dodaios.society.failure_reasons import FailureReason, classify_error

    text = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
    if _MODEL_RE.search(text):
        return CLASS_MODEL
    reason = classify_error(error)
    if reason is FailureReason.AUTH_FAILED or _AUTH_EXTRA_RE.search(text):
        return CLASS_AUTH
    if reason is FailureReason.PROVIDER_QUOTA_LIMIT or _QUOTA_EXTRA_RE.search(text):
        return CLASS_QUOTA
    if reason is FailureReason.RATE_LIMITED:
        return CLASS_RATE
    return CLASS_OTHER


def _quota_default_seconds(text: str) -> float:
    lowered = text.lower()
    if "week" in lowered:
        return QUOTA_WEEKLY_S
    if "5-hour" in lowered or "5 hour" in lowered or "five-hour" in lowered:
        return QUOTA_FIVE_HOUR_S
    return QUOTA_DEFAULT_S


@dataclass(frozen=True, slots=True)
class SeatVerdict:
    """Why a seat should not be used right now (or ``None`` from :meth:`SeatHealth.verdict`)."""

    provider: str
    account: str
    cls: str
    until: float
    #: ``True`` for auth / model failures that need a person, not just time.
    blocked: bool

    def reason(self, *, now: float | None = None) -> str:
        """One short readable sentence naming the cause and the wait."""
        wait = self.until - (time.time() if now is None else now)
        when = _clock(self.until)
        if self.cls == CLASS_QUOTA:
            return f"usage limit reached; usable again around {when}" if wait > 0 else "usage limit"
        if self.cls == CLASS_RATE:
            return "rate limited for a moment"
        if self.cls == CLASS_AUTH:
            return "login or key rejected; sign in again or replace the key"
        return "the selected model is not available on this account"


def _clock(epoch: float) -> str:
    at = datetime.fromtimestamp(epoch)
    if at.date() == datetime.now().date():
        return at.strftime("%H:%M")
    return at.strftime("%a %H:%M")


@dataclass(frozen=True, slots=True)
class SeatFailure:
    """What :meth:`SeatHealth.record_failure` decided."""

    cls: str
    until: float
    streak: int
    #: ``True`` exactly once per streak: time to write one notice to the lead.
    notify: bool


@dataclass
class _Seat:
    provider: str
    account: str
    last_class: str = ""
    last_at: float = 0.0
    last_ok_at: float = 0.0
    until: float = 0.0
    until_class: str = ""
    credential: str = ""
    model_blocks: dict[str, float] = field(default_factory=dict)
    streak_class: str = ""
    streak: int = 0
    notified: bool = False
    recent: list[list[Any]] = field(default_factory=list)  # [[ts, class], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "account": self.account,
            "last_class": self.last_class, "last_at": self.last_at,
            "last_ok_at": self.last_ok_at, "until": self.until,
            "until_class": self.until_class, "credential": self.credential,
            "model_blocks": self.model_blocks, "streak_class": self.streak_class,
            "streak": self.streak, "notified": self.notified, "recent": self.recent,
        }

    @classmethod
    def from_json(cls, raw: Any) -> _Seat | None:
        if not isinstance(raw, dict) or not str(raw.get("provider") or ""):
            return None
        try:
            seat = cls(provider=str(raw["provider"]), account=str(raw.get("account") or ""))
            seat.last_class = str(raw.get("last_class") or "")
            seat.last_at = float(raw.get("last_at") or 0.0)
            seat.last_ok_at = float(raw.get("last_ok_at") or 0.0)
            seat.until = float(raw.get("until") or 0.0)
            seat.until_class = str(raw.get("until_class") or "")
            seat.credential = str(raw.get("credential") or "")
            blocks = raw.get("model_blocks")
            seat.model_blocks = (
                {str(k): float(v) for k, v in blocks.items()} if isinstance(blocks, dict) else {}
            )
            seat.streak_class = str(raw.get("streak_class") or "")
            seat.streak = int(raw.get("streak") or 0)
            seat.notified = bool(raw.get("notified"))
            recent = raw.get("recent")
            seat.recent = [
                [float(r[0]), str(r[1])] for r in recent if isinstance(r, list) and len(r) == 2
            ] if isinstance(recent, list) else []
            return seat
        except (TypeError, ValueError):  # a malformed persisted seat is dropped, never fatal
            return None


def _key(provider: str | None, account: str | None) -> tuple[str, str]:
    return (str(provider or "").strip().casefold(), str(account or "").strip())


class SeatHealth:
    """The passive per-seat record. Thread-safe; every method is cheap."""

    def __init__(
        self, path: Path | None = None, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.RLock()
        self._seats: dict[tuple[str, str], _Seat] = {}
        self._loaded = path is None

    # ------------------------------------------------------------ writes

    def record_failure(
        self,
        provider: str | None,
        account: str | None,
        error: BaseException | str | None,
        *,
        model: str = "",
        credential: str = "",
    ) -> SeatFailure:
        """A real call on this seat failed. Only the class survives, never the message."""
        cls = classify_seat_failure(error)
        now = self._clock()
        text = str(error or "")
        with self._lock:
            self._ensure_loaded()
            seat = self._seats.setdefault(
                _key(provider, account), _Seat(*_key(provider, account))
            )
            seat.last_class, seat.last_at = cls, now
            seat.recent = [r for r in seat.recent if now - r[0] < _WINDOW_S][-_RECENT_MAX:]
            seat.recent.append([now, cls])
            if cls == seat.streak_class:
                seat.streak += 1
            else:
                seat.streak_class, seat.streak, seat.notified = cls, 1, False
            until = 0.0
            if cls == CLASS_QUOTA:
                until = parse_reset_time(text, now=now) or now + _quota_default_seconds(text)
            elif cls == CLASS_RATE:
                until = parse_reset_time(text, now=now) or now + RATE_COOLDOWN_S
            elif cls == CLASS_AUTH:
                until = now + BLOCK_TTL_S
            elif cls == CLASS_MODEL:
                until = now + BLOCK_TTL_S
                if model:
                    seat.model_blocks[model] = until
            if until and cls != CLASS_MODEL:
                seat.until, seat.until_class = until, cls
                if credential:
                    seat.credential = credential
            notify = (
                cls != CLASS_OTHER and seat.streak >= NOTICE_STREAK and not seat.notified
            )
            if notify:
                seat.notified = True
            self._save_locked()
            return SeatFailure(cls, until, seat.streak, notify)

    def record_success(
        self, provider: str | None, account: str | None, *, model: str = ""
    ) -> None:
        """A real call on this seat answered: the verdict, streak and notice reset."""
        with self._lock:
            self._ensure_loaded()
            seat = self._seats.get(_key(provider, account))
            if seat is None:
                return
            dirty = bool(seat.until or seat.streak or seat.model_blocks)
            seat.last_ok_at = self._clock()
            seat.until, seat.until_class, seat.credential = 0.0, "", ""
            seat.streak_class, seat.streak, seat.notified = "", 0, False
            seat.model_blocks.pop(model, None)
            if not model:
                seat.model_blocks.clear()
            if dirty:
                self._save_locked()

    def forget(self, provider: str | None, account: str | None = None) -> None:
        """A key or login changed: forget the provider's verdicts (all logins if none given)."""
        name = _key(provider, "")[0]
        with self._lock:
            self._ensure_loaded()
            drop = [
                k for k in self._seats if k[0] == name and (account is None or k[1] == account)
            ]
            for key in drop:
                del self._seats[key]
            if drop:
                self._save_locked()

    # ------------------------------------------------------------- reads

    def verdict(
        self,
        provider: str | None,
        account: str | None = "",
        *,
        model: str = "",
        credential: str = "",
    ) -> SeatVerdict | None:
        """Why this seat should not be used now, or ``None`` when nothing is known against it."""
        now = self._clock()
        with self._lock:
            self._ensure_loaded()
            seat = self._seats.get(_key(provider, account))
            if seat is None:
                return None
            if model:
                until = seat.model_blocks.get(model, 0.0)
                if until > now:
                    return SeatVerdict(seat.provider, seat.account, CLASS_MODEL, until, True)
            if seat.until <= now:
                return None
            if (
                seat.until_class == CLASS_AUTH
                and credential
                and seat.credential
                and credential != seat.credential
            ):
                return None  # the key changed since the verdict
            return SeatVerdict(
                seat.provider, seat.account, seat.until_class, seat.until,
                seat.until_class == CLASS_AUTH,
            )

    def failure_counts(self, provider: str | None, account: str | None = "") -> dict[str, int]:
        """Failures of the last 24 h per class."""
        now = self._clock()
        with self._lock:
            self._ensure_loaded()
            seat = self._seats.get(_key(provider, account))
            counts: dict[str, int] = {}
            for ts, cls in (seat.recent if seat else []):
                if now - ts < _WINDOW_S:
                    counts[cls] = counts.get(cls, 0) + 1
            return counts

    def any_verdict(self, provider: str | None) -> SeatVerdict | None:
        """The first verdict against any login of ``provider`` (a brain call has no account)."""
        name = _key(provider, "")[0]
        with self._lock:
            self._ensure_loaded()
            logins = sorted(k[1] for k in self._seats if k[0] == name)
        for account in logins:
            found = self.verdict(provider, account)
            if found is not None:
                return found
        return None

    def health_line(
        self, provider: str | None, account: str | None = "", *, model: str = ""
    ) -> str:
        """A short phrase for a troubled seat; ``""`` when nothing is known against it."""
        found = self.verdict(provider, account, model=model)
        if found is None:
            return ""
        if found.cls == CLASS_QUOTA:
            return f"usage limit, back around {_clock(found.until)}"
        if found.cls == CLASS_RATE:
            return "rate limited, retrying shortly"
        if found.cls == CLASS_AUTH:
            return "login or key rejected"
        return "model not available on this account"

    # ----------------------------------------------------------- storage

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8")) if self._path else {}
        except FileNotFoundError:  # no record yet: nothing has failed so far
            return
        except (OSError, ValueError):
            log.warning("seat health: unreadable record, starting empty")
            return
        rows = raw.get("seats") if isinstance(raw, dict) else None
        for item in rows if isinstance(rows, list) else []:
            seat = _Seat.from_json(item)
            if seat is not None:
                self._seats[_key(seat.provider, seat.account)] = seat

    def _save_locked(self) -> None:
        if self._path is None:
            return
        payload = {"version": _FILE_VERSION, "seats": [s.to_json() for s in self._seats.values()]}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".seat_health.")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self._path)
        except OSError:
            log.warning("seat health: could not persist the record", exc_info=True)


_guard = threading.Lock()
_instance: SeatHealth | None = None


def _record_path() -> Path:
    from dodaios.core import config as cfg_mod  # lazy: tests redirect DATA_DIR

    return Path(cfg_mod.DATA_DIR) / "state" / FILE_NAME


def get_seat_health() -> SeatHealth:
    """The process-wide record, created on first use (never at import)."""
    global _instance
    with _guard:
        if _instance is None:
            _instance = SeatHealth(_record_path())
        return _instance


def set_seat_health(health: SeatHealth | None) -> None:
    """Swap the process-wide record (tests; ``None`` rebuilds on next use)."""
    global _instance
    with _guard:
        _instance = health


def fallback_is_known_dead(provider: str, model: str | None = None) -> bool:
    """Whether a chain FALLBACK should be skipped: real calls found its seat unusable.

    Never consulted for the first entry of a chain (the owner's own choice).
    Any failure to answer reads as "not known dead".
    """
    try:
        found = get_seat_health().verdict(provider, "", model=model or "")
    except Exception:  # noqa: BLE001 — a health read never breaks a turn
        log.debug("seat health: fallback check failed", exc_info=True)
        return False
    # Only a rejected key or login (provider-wide) or an unavailable model is
    # skipped. A usage limit may be per model (a free sibling model of the same
    # provider can still answer), so the chain decides that itself.
    if found is not None and not found.blocked:
        return False
    if found is not None:
        log.info("Skipping fallback %s: %s", provider, found.reason())
    return found is not None


def wait_out_cooling_seats(
    attempts: list[tuple[str, str | None]],
) -> list[tuple[str, str | None]]:
    """Background work waits instead of burning attempts on a seat in cooldown.

    Seats with a live verdict (limit reached, login rejected) leave the list;
    when none is left the run is deferred with the reset time in its reason
    and a later run (the next occurrence, or a retry) picks the seat up again.
    The owner's seat is never swapped: nothing is added to the list.
    """
    from dodaios.brain.background_policy import BackgroundDeferred

    health = get_seat_health()
    kept: list[tuple[str, str | None]] = []
    waiting: list[SeatVerdict] = []
    for provider, model in attempts:
        found = health.verdict(provider, "", model=model or "")
        if found is None:
            kept.append((provider, model))
        else:
            waiting.append(found)
    if kept or not waiting:
        return kept if waiting else attempts
    first = min(waiting, key=lambda v: v.until)
    raise BackgroundDeferred(
        f"Background work is waiting on {first.provider}: {first.reason()}.",
        code="seat_cooldown",
        provider=first.provider,
    )
