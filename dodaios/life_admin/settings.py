"""What the owner switched on for life admin. Everything is off until chosen."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Final

from .model import KINDS

log = logging.getLogger(__name__)

META_KEY: Final[str] = "life_admin"
#: Weekday names in the order of ``datetime.weekday()``.
DAYS: Final[tuple[str, ...]] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_DIGEST_TIME: Final[str] = "09:00"
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class LifeAdminSettings:
    enabled: bool = False
    #: ``off`` or one of :data:`DAYS`: the weekly written digest.
    digest_day: str = "off"
    digest_time: str = DEFAULT_DIGEST_TIME
    #: The morning brief carries the items too (only if the owner has a brief).
    in_brief: bool = True
    categories: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(KINDS, True))
    timezone: str = ""

    @property
    def digest_on(self) -> bool:
        return self.enabled and self.digest_day in DAYS

    def kinds_on(self) -> tuple[str, ...]:
        return tuple(k for k in KINDS if self.categories.get(k, True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "digest_day": self.digest_day,
            "digest_time": self.digest_time,
            "in_brief": self.in_brief,
            "categories": {k: bool(self.categories.get(k, True)) for k in KINDS},
            "timezone": self.timezone,
        }

    @classmethod
    def from_dict(cls, data: Any) -> LifeAdminSettings:
        """Settings from any stored or posted shape; unknown values fall back to off."""
        if not isinstance(data, dict):
            return cls()
        day = str(data.get("digest_day") or "off").strip().lower()
        if day not in DAYS:
            day = "off"
        time_ = str(data.get("digest_time") or DEFAULT_DIGEST_TIME).strip()
        if not _TIME_RE.match(time_):
            time_ = DEFAULT_DIGEST_TIME
        raw = data.get("categories")
        categories = {
            k: bool(raw.get(k, True)) if isinstance(raw, dict) else True for k in KINDS
        }
        return cls(
            enabled=data.get("enabled") is True,
            digest_day=day,
            digest_time=time_,
            in_brief=data.get("in_brief") is not False,
            categories=categories,
            timezone=str(data.get("timezone") or "").strip(),
        )


async def load_settings(store: Any) -> LifeAdminSettings:
    """The saved settings, or the all-off defaults."""
    if store is None:
        return LifeAdminSettings()
    try:
        raw = await store.get_meta(META_KEY, "")
    except Exception:  # noqa: BLE001 - an unreadable row reads as off
        log.warning("life admin: settings unreadable", exc_info=True)
        return LifeAdminSettings()
    if not raw:
        return LifeAdminSettings()
    try:
        return LifeAdminSettings.from_dict(json.loads(raw))
    except ValueError:
        log.warning("life admin: stored settings are not JSON; using the defaults")
        return LifeAdminSettings()


async def save_settings(settings: LifeAdminSettings, store: Any) -> None:
    if store is None:
        raise RuntimeError("The agent society is not running")
    await store.set_meta(META_KEY, json.dumps(settings.to_dict(), ensure_ascii=False))
