"""Read, check and save designs (``<DATA_DIR>/designs.json``).

The file holds the person's own designs and which design is active::

    {"version": 1, "active": "deep-sea", "designs": [{...}, ...]}

Built-in designs (``presets.py``) are not written to the file; they are listed
first and cannot be changed or deleted. ``"standard"`` is the app's own look
and is what ``active`` falls back to when it names a design that is gone.

Every write goes through one lock and an atomic replace, so the settings page
and an assistant tool call that save at the same moment cannot tear the file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

FILE_NAME = "designs.json"
FORMAT_VERSION = 1

#: The app's own look. Not a design in the list; picking it switches designs off.
STANDARD_ID = "standard"

#: Colours a design may set, per appearance. Values are ``#rrggbb``.
COLOR_KEYS: tuple[str, ...] = (
    "background",  # the room: every full-window region
    "foreground",  # running text
    "accent",  # links, focus, selection, the sent chat bubble
    "sidebar",  # the rail and standing chrome
    "card",  # objects: cards, the composer, panels
    "popover",  # menus and other floating layers
    "surface",  # hover, selected rows, fields, tiles
    "border",  # hairlines
    "muted",  # secondary text: labels, meta
    "primary",  # filled buttons and marks
    "user_bubble",  # the person's own message bubble
    "bubble_out",  # the sent bubble in a chat with an agent
    "bubble_in",  # the received bubble in a chat with an agent
    "success",
    "warning",
    "destructive",
)

#: The colours every appearance of a design needs; the app derives the rest.
REQUIRED_KEYS: tuple[str, ...] = ("background", "foreground", "accent")

#: Animated backgrounds the app can draw.
BACKGROUND_STYLES: tuple[str, ...] = ("none", "glow", "waves", "stars", "gradient")
SPEEDS: tuple[str, ...] = ("slow", "medium", "fast")

MAX_NAME = 40
MAX_DESCRIPTION = 300
MAX_BACKGROUND_COLORS = 5
MAX_OWN_DESIGNS = 100

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

_lock = threading.Lock()


class DesignError(ValueError):
    """A design that cannot be saved, with a message the person can act on."""


class DesignNotFound(LookupError):
    """No design with that id."""


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def normalize_hex(value: object, *, field: str) -> str:
    """``#rrggbb`` in lower case, or :class:`DesignError`."""
    text = str(value or "").strip()
    match = _HEX_RE.match(text)
    if not match:
        raise DesignError(f"{field}: {text!r} is not a colour; use #rrggbb, for example #1e3a5f.")
    digits = match.group(1).lower()
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return f"#{digits}"


def check_palette(value: object, *, side: str) -> dict[str, str] | None:
    """One appearance's colours, checked; ``None`` when the side is left out."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DesignError(
            f'{side}: expected an object of colours, for example {{"background": "#0b1020"}}.'
        )
    if not value:
        return None
    unknown = sorted(set(value) - set(COLOR_KEYS))
    if unknown:
        raise DesignError(
            f"{side}: unknown colour {', '.join(unknown)} (allowed: {', '.join(COLOR_KEYS)})."
        )
    palette = {
        key: normalize_hex(value[key], field=f"{side}.{key}") for key in COLOR_KEYS if key in value
    }
    missing = [key for key in REQUIRED_KEYS if key not in palette]
    if missing:
        raise DesignError(
            f"{side}: needs {', '.join(missing)} "
            f"(every appearance needs {', '.join(REQUIRED_KEYS)})."
        )
    return palette


def check_background(value: object) -> dict[str, Any]:
    """The animated background, checked. ``None`` or ``{}`` means no animation."""
    if value is None or value == {}:
        return {"style": "none", "colors": [], "speed": "slow", "strength": 0.5}
    if not isinstance(value, dict):
        raise DesignError("background: expected an object with style, colors, speed and strength.")
    unknown = sorted(set(value) - {"style", "colors", "speed", "strength"})
    if unknown:
        raise DesignError(
            f"background: unknown field {', '.join(unknown)} "
            "(allowed: style, colors, speed, strength)."
        )
    style = str(value.get("style") or "none").strip().lower()
    if style not in BACKGROUND_STYLES:
        raise DesignError(
            f"background.style: {style!r} is not one of {', '.join(BACKGROUND_STYLES)}."
        )
    speed = str(value.get("speed") or "slow").strip().lower()
    if speed not in SPEEDS:
        raise DesignError(f"background.speed: {speed!r} is not one of {', '.join(SPEEDS)}.")
    raw_strength = value.get("strength", 0.5)
    if isinstance(raw_strength, bool) or not isinstance(raw_strength, (int, float)):
        raise DesignError("background.strength: expected a number from 0 to 1.")
    strength = round(min(1.0, max(0.0, float(raw_strength))), 3)
    raw_colors = value.get("colors") or []
    if not isinstance(raw_colors, list):
        raise DesignError("background.colors: expected a list of #rrggbb colours.")
    if len(raw_colors) > MAX_BACKGROUND_COLORS:
        raise DesignError(f"background.colors: at most {MAX_BACKGROUND_COLORS} colours.")
    colors = [normalize_hex(c, field=f"background.colors[{i}]") for i, c in enumerate(raw_colors)]
    if style != "none" and not colors:
        raise DesignError("background.colors: an animated background needs at least one colour.")
    return {"style": style, "colors": colors, "speed": speed, "strength": strength}


def _clean_text(value: object, *, field: str, limit: int, required: bool = False) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise DesignError(f"{field}: must not be empty.")
    if len(text) > limit:
        raise DesignError(f"{field}: at most {limit} characters.")
    return text


def slug_for(name: str, taken: set[str]) -> str:
    """A free id made from the name (``"Deep Sea"`` -> ``deep-sea``)."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "design"
    if len(base) < 2:
        base = f"design-{base}"
    candidate, n = base, 2
    while candidate in taken or candidate == STANDARD_ID:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def designs_path(data_dir: Path | None = None) -> Path:
    if data_dir is None:
        from dodaios.core import config

        data_dir = config.DATA_DIR
    return Path(data_dir) / FILE_NAME


def _read_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"active": STANDARD_ID, "designs": []}
    except (OSError, ValueError) as exc:
        log.warning("designs file %s unreadable, starting from the standard look: %s", path, exc)
        return {"active": STANDARD_ID, "designs": []}
    if not isinstance(raw, dict):
        return {"active": STANDARD_ID, "designs": []}
    designs: list[dict[str, Any]] = []
    for item in raw.get("designs") or []:
        try:
            designs.append(_stored_design(item))
        except (DesignError, TypeError, KeyError) as exc:
            log.warning("skipping a broken design in %s: %s", path, exc)
    return {"active": str(raw.get("active") or STANDARD_ID), "designs": designs}


def _stored_design(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise DesignError("not an object")
    design_id = str(item.get("id") or "")
    if not _ID_RE.match(design_id) or design_id == STANDARD_ID:
        raise DesignError(f"bad id {design_id!r}")
    dark = check_palette(item.get("dark"), side="dark")
    light = check_palette(item.get("light"), side="light")
    if dark is None and light is None:
        raise DesignError("no colours")
    return {
        "id": design_id,
        "name": _clean_text(item.get("name"), field="name", limit=MAX_NAME, required=True),
        "description": _clean_text(
            item.get("description"), field="description", limit=MAX_DESCRIPTION
        ),
        "builtin": False,
        "dark": dark,
        "light": light,
        "background": check_background(item.get("background")),
        "created_at": float(item.get("created_at") or 0.0),
        "updated_at": float(item.get("updated_at") or 0.0),
    }


def _write_file(path: Path, active: str, designs: list[dict[str, Any]]) -> None:
    payload = {
        "version": FORMAT_VERSION,
        "active": active,
        "designs": [{k: v for k, v in d.items() if k != "builtin"} for d in designs],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".designs-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


def _builtins() -> list[dict[str, Any]]:
    from dodaios.ui.designs.presets import builtin_designs

    return builtin_designs()


def _state(active: str, own: list[dict[str, Any]]) -> dict[str, Any]:
    every = [*_builtins(), *own]
    ids = {d["id"] for d in every}
    return {
        "active": active if active in ids else STANDARD_ID,
        "standard_id": STANDARD_ID,
        "designs": every,
    }


def load_state(data_dir: Path | None = None) -> dict[str, Any]:
    """Every design (built-in first) and the active id."""
    data = _read_file(designs_path(data_dir))
    return _state(data["active"], data["designs"])


def find_design(design_id: str, data_dir: Path | None = None) -> dict[str, Any] | None:
    for design in load_state(data_dir)["designs"]:
        if design["id"] == design_id:
            return design
    return None


def save_design(
    payload: dict[str, Any], *, apply: bool = True, data_dir: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a design, or change one of the person's own (``payload["id"]``).

    On a change, fields left out keep their value, and the colours given for an
    appearance are laid over the ones it had, so "make the accent warmer" can
    send just ``{"dark": {"accent": "#ff8a3d"}}``. Returns ``(design, state)``.
    """
    path = designs_path(data_dir)
    with _lock:
        data = _read_file(path)
        own: list[dict[str, Any]] = data["designs"]
        builtin_ids = {d["id"] for d in _builtins()}
        wanted_id = str(payload.get("id") or "").strip().lower()
        existing = next((d for d in own if d["id"] == wanted_id), None) if wanted_id else None
        if wanted_id and existing is None:
            if wanted_id in builtin_ids:
                raise DesignError(
                    f"'{wanted_id}' is a built-in design and cannot be changed; "
                    "save it without an id to make your own copy."
                )
            raise DesignNotFound(f"There is no design '{wanted_id}' of yours to change.")

        now = time.time()
        if existing is None:
            if len(own) >= MAX_OWN_DESIGNS:
                raise DesignError(f"You already have {MAX_OWN_DESIGNS} designs; delete one first.")
            name = _clean_text(payload.get("name"), field="name", limit=MAX_NAME, required=True)
            dark = check_palette(payload.get("dark"), side="dark")
            light = check_palette(payload.get("light"), side="light")
            if dark is None and light is None:
                raise DesignError("A design needs colours for dark, light or both.")
            design = {
                "id": slug_for(name, {d["id"] for d in own} | builtin_ids),
                "name": name,
                "description": _clean_text(
                    payload.get("description"), field="description", limit=MAX_DESCRIPTION
                ),
                "builtin": False,
                "dark": dark,
                "light": light,
                "background": check_background(payload.get("background")),
                "created_at": now,
                "updated_at": now,
            }
            own.append(design)
        else:
            design = dict(existing)
            if "name" in payload and payload["name"] is not None:
                design["name"] = _clean_text(
                    payload["name"], field="name", limit=MAX_NAME, required=True
                )
            if "description" in payload and payload["description"] is not None:
                design["description"] = _clean_text(
                    payload["description"], field="description", limit=MAX_DESCRIPTION
                )
            for side in ("dark", "light"):
                given = payload.get(side)
                if given is None:
                    continue
                if not isinstance(given, dict):
                    raise DesignError(f"{side}: expected an object of colours.")
                design[side] = (
                    check_palette({**(design.get(side) or {}), **given}, side=side)
                    if given
                    else None
                )
            if design["dark"] is None and design["light"] is None:
                raise DesignError("A design needs colours for dark, light or both.")
            if "background" in payload and payload["background"] is not None:
                given_bg = payload["background"]
                merged = (
                    {**design["background"], **given_bg}
                    if isinstance(given_bg, dict) and given_bg
                    else given_bg
                )
                design["background"] = check_background(merged)
            design["updated_at"] = now
            own[own.index(existing)] = design

        active = design["id"] if apply else data["active"]
        _write_file(path, active, own)
        return design, _state(active, own)


def set_active(design_id: str, data_dir: Path | None = None) -> dict[str, Any]:
    """Switch to a design, or back to the standard look with ``"standard"``."""
    wanted = str(design_id or "").strip().lower() or STANDARD_ID
    path = designs_path(data_dir)
    with _lock:
        data = _read_file(path)
        ids = {d["id"] for d in [*_builtins(), *data["designs"]]}
        if wanted != STANDARD_ID and wanted not in ids:
            raise DesignNotFound(f"There is no design '{wanted}'.")
        _write_file(path, wanted, data["designs"])
        return _state(wanted, data["designs"])


def delete_design(design_id: str, data_dir: Path | None = None) -> dict[str, Any]:
    """Delete one of the person's own designs; the standard look takes over if it was active."""
    wanted = str(design_id or "").strip().lower()
    path = designs_path(data_dir)
    with _lock:
        data = _read_file(path)
        if wanted in {d["id"] for d in _builtins()}:
            raise DesignError(f"'{wanted}' is a built-in design and cannot be deleted.")
        own = [d for d in data["designs"] if d["id"] != wanted]
        if len(own) == len(data["designs"]):
            raise DesignNotFound(f"There is no design '{wanted}' of yours.")
        active = STANDARD_ID if data["active"] == wanted else data["active"]
        _write_file(path, active, own)
        return _state(active, own)
