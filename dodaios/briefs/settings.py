"""The ``[briefs]`` switches, as the pipeline reads them.

The app hands its config in once at start (:func:`configure`); every stage
asks :func:`current`. Before that, and in tests, the defaults apply, which are
the behaviour the app ships with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["BriefSettings", "configure", "current", "reset"]

log = logging.getLogger(__name__)

_CHECK_MODES: Final[tuple[str, ...]] = ("revise", "note", "off")


@dataclass(frozen=True, slots=True)
class BriefSettings:
    """One value per ``[briefs]`` key; see ``dodaios.core.config.BriefsConfig``."""

    check: str = "revise"
    auto_effort: bool = True
    standing_rules: bool = True
    lead_answers_questions: bool = True
    acceptance: bool = True
    record: bool = True


_CURRENT: BriefSettings = BriefSettings()


def configure(config: Any) -> BriefSettings:
    """Take the switches from the app's config; unreadable values keep their default."""
    global _CURRENT
    section = getattr(config, "briefs", None)
    defaults = BriefSettings()
    try:
        check = str(getattr(section, "check", defaults.check) or defaults.check).strip().lower()
        _CURRENT = BriefSettings(
            check=check if check in _CHECK_MODES else defaults.check,
            auto_effort=bool(getattr(section, "auto_effort", defaults.auto_effort)),
            standing_rules=bool(getattr(section, "standing_rules", defaults.standing_rules)),
            lead_answers_questions=bool(
                getattr(section, "lead_answers_questions", defaults.lead_answers_questions)
            ),
            acceptance=bool(getattr(section, "acceptance", defaults.acceptance)),
            record=bool(getattr(section, "record", defaults.record)),
        )
    except Exception:  # noqa: BLE001 - a broken section must not stop the app from starting
        log.warning("brief settings: [briefs] is not readable, defaults apply", exc_info=True)
        _CURRENT = defaults
    return _CURRENT


def current() -> BriefSettings:
    return _CURRENT


def reset() -> None:
    """Back to the defaults (tests)."""
    global _CURRENT
    _CURRENT = BriefSettings()
