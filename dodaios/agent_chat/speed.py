"""A coding CLI's speed tier: faster answers that use more of the plan.

Two coding CLIs have one, and both say per model whether it is offered:

* Claude Code: fast mode, ``--fast-mode on``. Its ``initialize`` handshake
  lists ``supportsFastMode`` per model (claude 2.1.319: Opus 5.5, Opus 5 and
  Opus 4.8). On any other model the CLI keeps the standard speed itself.
* Codex: a service tier, ``-c service_tier="<id>"``. ``model/list`` gives each
  model's ``serviceTiers`` for the signed-in account (``priority`` = "Fast";
  Ultrafast on the plans and API keys that have it). A free plan gets none,
  and Codex drops a tier its catalog does not advertise.

The other coding CLIs (Grok Build, Kimi Code, OpenCode, agy, Cursor) have no
speed switch: their fast variants are separate models in the model picker.

``""`` is always the standard speed: no flag, and the CLI's own config stands.
"""

from __future__ import annotations

import re
from typing import Any, Final

#: The one tier Claude Code has.
CLAUDE_FAST: Final[str] = "fast"

#: Runners with a speed switch.
SPEED_RUNNERS: Final[frozenset[str]] = frozenset({"claude-cli", "codex-cli"})

#: A tier id as a CLI catalog spells it; anything else is dropped, never
#: passed to a command line.
_TIER_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")


def normalize_speed(speed: str | None) -> str:
    """The stored form of a speed pick: a lower-case tier id, or ``""``."""
    value = (speed or "").strip().lower()
    if value in ("", "standard", "default"):
        return ""
    return value if _TIER_ID.match(value) else ""


def claude_speeds() -> list[dict[str, str]]:
    """The tiers a fast-mode Claude model offers, in catalog-row form."""
    return [{"id": CLAUDE_FAST, "label": "Fast", "note": "Faster output, uses more of your plan"}]


def codex_speeds(model: dict[str, Any]) -> list[dict[str, str]]:
    """A Codex ``model/list`` entry's ``serviceTiers``, in catalog-row form."""
    tiers = model.get("serviceTiers")
    if not isinstance(tiers, list):
        return []
    rows: list[dict[str, str]] = []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        tier_id = normalize_speed(str(tier.get("id") or ""))
        if not tier_id or any(row["id"] == tier_id for row in rows):
            continue
        rows.append(
            {
                "id": tier_id,
                "label": str(tier.get("name") or tier_id).strip() or tier_id,
                "note": str(tier.get("description") or "").strip(),
            }
        )
    return rows


def speed_args(runner: str, speed: str) -> list[str]:
    """The flags that start ``runner`` at ``speed``; none for the standard speed."""
    tier = normalize_speed(speed)
    if not tier:
        return []
    if runner == "claude-cli":
        return ["--fast-mode", "on"] if tier == CLAUDE_FAST else []
    if runner == "codex-cli":
        return ["-c", f'service_tier="{tier}"']
    return []


def apply_speed(argv: list[str], runner: str, speed: str) -> None:
    """Add the speed flags to a planned command line, in place.

    Codex reads its prompt from stdin after a final ``-``; the flags go in
    front of it.
    """
    extra = speed_args(runner, speed)
    if not extra:
        return
    at = len(argv) - 1 if runner == "codex-cli" and argv and argv[-1] == "-" else len(argv)
    argv[at:at] = extra
