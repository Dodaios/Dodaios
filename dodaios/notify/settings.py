"""What the person allowed notifications to do.

One JSON file under the data directory (``notify/settings.json``); the
settings page reads and writes it through ``/api/notify/settings``. Defaults
are on: a reminder the person set is pointless if it stays inside a window
they are not looking at. Quiet hours are off until set.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: What a notification can be about. The settings page offers one switch each.
KINDS: tuple[str, ...] = ("reminder", "needs_you", "approval", "finished")

#: What the lead may send to the owner's phone chat (Telegram, Discord DM,
#: WhatsApp) while they are away, and whether each is on by default. Only
#: things the owner started or opted into: ``progress`` (step-by-step chatter)
#: is off, ``brief`` (a proactive daily brief) waits for the owner's choice.
PHONE_DEFAULTS: dict[str, bool] = {
    "decisions": True,  # an approval or a question the work waits on
    "results": True,  # the answer to a message the owner sent from that chat
    "failures": True,  # "I could not finish that"
    "progress": False,
    "brief": False,
}
PHONE_KINDS: tuple[str, ...] = tuple(PHONE_DEFAULTS)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class QuietHours:
    enabled: bool = False
    #: Local wall-clock times, ``HH:MM``; a window that crosses midnight is fine.
    start: str = "22:00"
    end: str = "07:00"

    def covers(self, now: datetime) -> bool:
        """True while ``now`` (local) falls inside the quiet window."""
        if not self.enabled:
            return False
        start, end = _parse(self.start), _parse(self.end)
        if start is None or end is None or start == end:
            return False
        moment = now.time().replace(second=0, microsecond=0)
        if start < end:
            return start <= moment < end
        return moment >= start or moment < end


@dataclass(frozen=True)
class NotifySettings:
    #: The one switch. Off: nothing reaches the operating system.
    enabled: bool = True
    kinds: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(KINDS, True))
    quiet_hours: QuietHours = field(default_factory=QuietHours)
    #: Send waiting approvals to the owner's Telegram with Allow / Deny buttons.
    telegram_approvals: bool = True
    #: Which kinds of lead updates reach the phone chat (see ``PHONE_DEFAULTS``).
    phone: dict[str, bool] = field(default_factory=lambda: dict(PHONE_DEFAULTS))

    def phone_allows(self, kind: str) -> bool:
        """Whether a lead update of ``kind`` may be sent to the phone chat."""
        return bool(self.phone.get(kind, False))

    def allows(self, kind: str) -> bool:
        return self.enabled and bool(self.kinds.get(kind, True))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kinds"] = {kind: bool(self.kinds.get(kind, True)) for kind in KINDS}
        data["phone"] = {k: bool(self.phone.get(k, d)) for k, d in PHONE_DEFAULTS.items()}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotifySettings:
        base = cls()
        raw_kinds = data.get("kinds") if isinstance(data.get("kinds"), dict) else {}
        kinds = {kind: bool(raw_kinds.get(kind, True)) for kind in KINDS}
        raw_phone = data.get("phone") if isinstance(data.get("phone"), dict) else {}
        phone = {k: bool(raw_phone.get(k, d)) for k, d in PHONE_DEFAULTS.items()}
        quiet_raw = data.get("quiet_hours") if isinstance(data.get("quiet_hours"), dict) else {}
        quiet = QuietHours(
            enabled=bool(quiet_raw.get("enabled", False)),
            start=_clock(quiet_raw.get("start"), base.quiet_hours.start),
            end=_clock(quiet_raw.get("end"), base.quiet_hours.end),
        )
        return cls(
            enabled=bool(data.get("enabled", True)),
            kinds=kinds,
            quiet_hours=quiet,
            telegram_approvals=bool(data.get("telegram_approvals", True)),
            phone=phone,
        )

    def patched(self, patch: dict[str, Any]) -> NotifySettings:
        """A copy with the given top-level fields changed; unknown keys are ignored."""
        merged = self.to_dict()
        for key in ("enabled", "telegram_approvals"):
            if key in patch:
                merged[key] = bool(patch[key])
        if isinstance(patch.get("kinds"), dict):
            merged["kinds"] = {**merged["kinds"], **patch["kinds"]}
        if isinstance(patch.get("phone"), dict):
            merged["phone"] = {**merged["phone"], **patch["phone"]}
        if isinstance(patch.get("quiet_hours"), dict):
            merged["quiet_hours"] = {**merged["quiet_hours"], **patch["quiet_hours"]}
        return NotifySettings.from_dict(merged)


def _parse(value: str) -> time | None:
    if not _TIME_RE.match(value or ""):
        return None
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _clock(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if _TIME_RE.match(text) else fallback


def valid_clock(value: str) -> bool:
    return bool(_TIME_RE.match(value or ""))


# ------------------------------------------------------------------ storage

_lock = threading.Lock()
_cache: dict[Path, NotifySettings] = {}


def settings_path(data_dir: Path | None = None) -> Path:
    if data_dir is None:
        from dodaios.core.config import DATA_DIR

        data_dir = DATA_DIR
    return Path(data_dir) / "notify" / "settings.json"


def load_settings(path: Path | None = None) -> NotifySettings:
    """The saved settings, defaults when nothing was saved yet or the file is unreadable."""
    target = path or settings_path()
    with _lock:
        cached = _cache.get(target)
        if cached is not None:
            return cached
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:  # nothing saved yet: the defaults apply
            data = {}
        except (OSError, ValueError):
            log.warning("notify: settings file unreadable, using defaults (%s)", target)
            data = {}
        settings = NotifySettings.from_dict(data if isinstance(data, dict) else {})
        _cache[target] = settings
        return settings


def save_settings(patch: dict[str, Any], path: Path | None = None) -> NotifySettings:
    """Apply ``patch`` to the saved settings and write them back."""
    target = path or settings_path()
    current = load_settings(target)
    updated = current.patched(patch)
    with _lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(updated.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)
        _cache[target] = updated
    return updated


def forget_cached(path: Path | None = None) -> None:
    """Drop the in-memory copy (tests, or after an external edit)."""
    with _lock:
        if path is None:
            _cache.clear()
        else:
            _cache.pop(path, None)


__all__ = [
    "KINDS",
    "PHONE_DEFAULTS",
    "PHONE_KINDS",
    "NotifySettings",
    "QuietHours",
    "forget_cached",
    "load_settings",
    "save_settings",
    "settings_path",
    "valid_clock",
]
