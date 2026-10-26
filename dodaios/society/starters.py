"""Job-shaped starter agents for the New-agent dialog.

A starter is an agent template (``agent_template``) plus what the dialog
needs to offer it: the area it belongs to, a one-line outcome, the tools it
suggests, the first message it proposes and, optionally, one routine. The
catalogue is our own data under ``starters/*.json`` (one file per area) and
every template in it passes ``agent_template.validate_template`` — the same
stranger-safety rules a marketplace template meets. So a starter carries no
seat (the installer's provider and runtime decide), names no machine, and
never widens approvals: ``require_approval`` can only add confirmations.

Pure functions over the files and the capability catalog; the routes in
``dodaios/ui/web/society_routes.py`` serve them.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from .agent_template import validate_template

log = logging.getLogger(__name__)

__all__ = [
    "AREAS",
    "ROUTINE_SCHEDULES",
    "Starter",
    "StarterError",
    "load_starters",
    "preview_payload",
    "routine_schedule",
    "starter_by_id",
    "starter_payload",
    "starter_template",
    "template_summary",
    "validate_starter",
]

#: Display order of the gallery's areas.
AREAS: Final[tuple[str, ...]] = ("coding", "research", "inbox", "writing", "ops", "personal")

#: The routine times a starter may propose, as cron in the person's own zone.
#: Named slots keep the gallery's schedule sentence translatable.
ROUTINE_SCHEDULES: Final[dict[str, str]] = {
    "weekday_morning": "0 8 * * 1-5",
    "daily_morning": "0 8 * * *",
    "daily_evening": "0 18 * * *",
    "weekly_monday": "0 9 * * 1",
    "weekly_friday": "0 16 * * 5",
}

_DATA_DIR: Final[Path] = Path(__file__).with_name("starters")
_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_ICON_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9-]{1,40}$")
_CAPABILITY_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z]+:[A-Za-z0-9_.:-]{1,80}$")
_MAX_TOOLS: Final[int] = 8
_MAX_OUTCOME: Final[int] = 140
_MAX_FIRST_MESSAGE: Final[int] = 400
_BULLET_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)


class StarterError(ValueError):
    """A starter file or a starter request is not usable; user-facing message."""


@dataclass(frozen=True, slots=True)
class Starter:
    id: str
    area: str
    icon: str
    outcome: str
    tools: tuple[str, ...]
    first_message: str
    template: Mapping[str, Any]
    routine: Mapping[str, str] | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


def validate_starter(raw: Any, area: str) -> list[str]:
    """Every problem with one starter entry, as sentences (empty = usable)."""
    if not isinstance(raw, dict):
        return ["a starter is a JSON object"]
    errors: list[str] = []
    sid = raw.get("id")
    label = sid if isinstance(sid, str) else "?"
    if not isinstance(sid, str) or not _ID_RE.fullmatch(sid):
        errors.append(f"{label}: id must be 1-40 characters of a-z 0-9 -")
    if area not in AREAS:
        errors.append(f"{label}: area {area!r} is not one of {', '.join(AREAS)}")
    if not isinstance(raw.get("icon"), str) or not _ICON_RE.fullmatch(raw["icon"]):
        errors.append(f"{label}: icon must be a lowercase icon name")
    outcome = raw.get("outcome")
    if not isinstance(outcome, str) or not outcome.strip() or len(outcome) > _MAX_OUTCOME:
        errors.append(f"{label}: outcome must be one line of at most {_MAX_OUTCOME} characters")
    first = raw.get("first_message")
    if not isinstance(first, str) or not first.strip() or len(first) > _MAX_FIRST_MESSAGE:
        errors.append(f"{label}: first_message must be at most {_MAX_FIRST_MESSAGE} characters")
    tools = raw.get("tools", [])
    if (
        not isinstance(tools, list)
        or len(tools) > _MAX_TOOLS
        or not all(isinstance(t, str) and _CAPABILITY_RE.fullmatch(t) for t in tools)
    ):
        errors.append(f"{label}: tools must be at most {_MAX_TOOLS} capability ids")
    routine = raw.get("routine")
    if routine is not None:
        if not isinstance(routine, dict):
            errors.append(f"{label}: routine must be an object")
        else:
            if routine.get("when") not in ROUTINE_SCHEDULES:
                errors.append(f"{label}: routine.when must be one of {sorted(ROUTINE_SCHEDULES)}")
            for key, limit in (("title", 200), ("prompt", 2_000)):
                value = routine.get(key)
                if not isinstance(value, str) or not value.strip() or len(value) > limit:
                    errors.append(f"{label}: routine.{key} is missing or too long")
    template = raw.get("template")
    errors += [f"{label}: {problem}" for problem in validate_template(template)]
    if isinstance(template, dict) and template.get("focus"):
        errors.append(f"{label}: the template's focus comes from tools, leave it out")
    return errors


def _from_file(path: Path) -> list[Starter]:
    data = json.loads(path.read_text(encoding="utf-8"))
    area = str(data.get("area") or "")
    out: list[Starter] = []
    for raw in data.get("starters") or []:
        problems = validate_starter(raw, area)
        if problems:
            # A broken entry is a bug in our own data; the rest of the gallery stays.
            log.error("starters: %s skipped: %s", path.name, "; ".join(problems))
            continue
        out.append(
            Starter(
                id=raw["id"],
                area=area,
                icon=raw["icon"],
                outcome=" ".join(raw["outcome"].split()),
                tools=tuple(dict.fromkeys(raw.get("tools") or [])),
                first_message=raw["first_message"],
                template=raw["template"],
                routine=dict(raw["routine"]) if raw.get("routine") else None,
            )
        )
    return out


@lru_cache(maxsize=1)
def load_starters(directory: Path | None = None) -> tuple[Starter, ...]:
    """Every usable starter, in area order and then file order; ids are unique."""
    folder = directory or _DATA_DIR
    found: list[Starter] = []
    seen: set[str] = set()
    for path in sorted(folder.glob("*.json")):
        try:
            entries = _from_file(path)
        except (OSError, ValueError):
            log.exception("starters: unreadable file %s", path)
            continue
        for entry in entries:
            if entry.id in seen:
                log.error("starters: duplicate id %s in %s skipped", entry.id, path.name)
                continue
            seen.add(entry.id)
            found.append(entry)
    order = {area: index for index, area in enumerate(AREAS)}
    return tuple(sorted(found, key=lambda s: order.get(s.area, len(AREAS))))


def starter_by_id(starter_id: str) -> Starter:
    for starter in load_starters():
        if starter.id == starter_id:
            return starter
    raise StarterError(f"There is no starter called {starter_id!r}")


def routine_schedule(starter: Starter, timezone: str) -> dict[str, Any] | None:
    """The routine's schedule for ``RoutineBody`` in the person's zone, or ``None``."""
    if starter.routine is None:
        return None
    return {
        "kind": "cron",
        "expression": ROUTINE_SCHEDULES[starter.routine["when"]],
        "timezone": timezone,
    }


def starter_template(
    starter: Starter, *, name: str | None = None, tools: Iterable[str] | None = None
) -> dict[str, Any]:
    """The starter's template with the picked name and tools applied.

    ``tools`` narrows the suggestion: only ids the starter suggests can be
    picked, so a request can never hand the agent a focus the gallery did not
    show. ``None`` keeps every suggested tool.
    """
    template = copy.deepcopy(dict(starter.template))
    if name is not None and name.strip():
        template["name"] = " ".join(name.split())
    picked = starter.tools if tools is None else tuple(t for t in starter.tools if t in set(tools))
    if picked:
        template["focus"] = list(picked)
    return template


def template_summary(
    template: Mapping[str, Any], *, routines: int = 0, tools: Iterable[str] | None = None
) -> dict[str, Any]:
    """What a template brings, counted the same way for starters and imports."""
    instructions = str(template.get("instructions") or "")
    skills = template.get("skills")
    tool_ids = list(tools) if tools is not None else list(template.get("focus") or [])
    return {
        "instructions_words": len(instructions.split()),
        "instructions_rules": len(_BULLET_RE.findall(instructions)),
        # ``None`` = the template does not narrow skills: every skill on the box.
        "skills": len(skills) if isinstance(skills, list) else None,
        "routines": routines,
        "tools": len(tool_ids),
        "asks_before": len(template.get("require_approval") or []),
        "limited_tools": template.get("grant_mode") == "allowlist",
    }


def _tool_rows(tool_ids: Iterable[str], catalog: Iterable[Any]) -> list[dict[str, Any]]:
    rows = {getattr(row, "id", ""): row for row in catalog}
    out: list[dict[str, Any]] = []
    for cap_id in tool_ids:
        row = rows.get(cap_id)
        out.append(
            {
                "id": cap_id,
                "label": getattr(row, "label", "") or cap_id.split(":", 1)[-1],
                "available": row is not None,
                "connected": bool(row is not None and getattr(row, "connected", False)),
            }
        )
    return out


def starter_payload(starter: Starter, catalog: Iterable[Any]) -> dict[str, Any]:
    """One gallery entry: the starter, its tools on THIS box, and its counts."""
    template = dict(starter.template)
    return {
        "id": starter.id,
        "area": starter.area,
        "icon": starter.icon,
        "name": template["name"],
        "title": template.get("title", ""),
        "outcome": starter.outcome,
        "instructions": template["instructions"],
        "first_message": starter.first_message,
        "tools": _tool_rows(starter.tools, catalog),
        "routine": (
            {
                "title": starter.routine["title"],
                "when": starter.routine["when"],
                "cron": ROUTINE_SCHEDULES[starter.routine["when"]],
            }
            if starter.routine
            else None
        ),
        "summary": template_summary(
            template, routines=1 if starter.routine else 0, tools=starter.tools
        ),
    }


def preview_payload(template: Any, catalog: Iterable[Any]) -> dict[str, Any]:
    """An imported template, checked and counted before anything is created."""
    errors = validate_template(template)
    if not isinstance(template, dict):
        return {"ok": False, "errors": errors, "template": None, "summary": None, "tools": []}
    focus = [t for t in template.get("focus") or [] if isinstance(t, str)]
    return {
        "ok": not errors,
        "errors": errors,
        "template": {
            "name": template.get("name", ""),
            "title": template.get("title", ""),
            "instructions": template.get("instructions", ""),
            "require_approval": list(template.get("require_approval") or []),
        },
        "summary": template_summary(template),
        "tools": _tool_rows(focus, catalog),
    }
