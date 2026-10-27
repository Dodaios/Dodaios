"""The user's own game settings, one profile per game, in one JSON file.

Lives at ``<DATA_DIR>/games/profiles.json``::

    {"version": 1, "dpi": 800,
     "games": {"fortnite": {"values": {"mouse_sens_x": 6.4},
                            "keybinds": {"jump": "Space"},
                            "dpi": null, "notes": "", "updated_at": "..."}}}

``dpi`` at the top is the mouse DPI every game uses unless its profile sets
its own. Values are checked against the catalog before they are written, and
the file is replaced atomically so a crash never leaves half a file.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dodaios.games.catalog import get_game, keybind_ids, settings_by_key

log = logging.getLogger(__name__)

DEFAULT_DPI = 800
MIN_DPI, MAX_DPI = 50, 64000
MAX_KEY_LEN = 40
MAX_TEXT_LEN = 200
MAX_NOTES_LEN = 4000

_LOCK = threading.Lock()


class UnknownGameError(LookupError):
    """The game id is not in the catalog."""


def store_path(data_dir: Path | None = None) -> Path:
    if data_dir is None:
        from dodaios.core import config

        data_dir = config.DATA_DIR
    return Path(data_dir) / "games" / "profiles.json"


def _empty() -> dict[str, Any]:
    return {"version": 1, "dpi": DEFAULT_DPI, "games": {}}


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:  # no profile saved yet: a fresh install starts empty
        return _empty()
    except (OSError, ValueError) as exc:
        log.warning("game profiles unreadable, starting empty: %s", exc)
        return _empty()
    if not isinstance(raw, dict) or not isinstance(raw.get("games"), dict):
        return _empty()
    raw.setdefault("version", 1)
    if not isinstance(raw.get("dpi"), int):
        raw["dpi"] = DEFAULT_DPI
    return raw


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def check_dpi(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("DPI must be a number")
    dpi = int(round(value))
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError(f"DPI must be between {MIN_DPI} and {MAX_DPI}")
    return dpi


def check_value(setting: dict[str, Any], value: Any) -> Any:
    """``value`` normalized for ``setting``, or ``ValueError`` when it does not fit."""
    if value is None:
        return None
    kind = setting["type"]
    label = setting["label"]
    if kind == "toggle":
        if not isinstance(value, bool):
            raise ValueError(f"{label}: expected on or off")
        return value
    if kind == "select":
        if value not in setting.get("options", []):
            raise ValueError(f"{label}: not one of the game's options")
        return value
    if kind == "text":
        if not isinstance(value, str) or len(value) > MAX_TEXT_LEN:
            raise ValueError(f"{label}: text up to {MAX_TEXT_LEN} characters")
        return value.strip()
    # slider / number
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}: expected a number")
    low, high = setting.get("min"), setting.get("max")
    if low is not None and value < low:
        raise ValueError(f"{label}: at least {low}")
    if high is not None and value > high:
        raise ValueError(f"{label}: at most {high}")
    return value


def check_key(value: Any) -> str:
    if not isinstance(value, str) or len(value) > MAX_KEY_LEN:
        raise ValueError(f"A key name is text up to {MAX_KEY_LEN} characters")
    return value.strip()


def _game_or_raise(game_id: str) -> dict[str, Any]:
    game = get_game(game_id)
    if game is None:
        raise UnknownGameError(game_id)
    return game


def _blank_profile() -> dict[str, Any]:
    return {"values": {}, "keybinds": {}, "dpi": None, "notes": "", "updated_at": None}


class GameProfileStore:
    """Read and change the profiles file. Every method is safe across threads."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or store_path()

    def snapshot(self) -> dict[str, Any]:
        with _LOCK:
            return _read(self.path)

    def profile(self, game_id: str) -> dict[str, Any]:
        _game_or_raise(game_id)
        data = self.snapshot()
        return {**_blank_profile(), **data["games"].get(game_id, {})}

    def set_default_dpi(self, dpi: Any) -> int:
        value = check_dpi(dpi)
        with _LOCK:
            data = _read(self.path)
            data["dpi"] = value
            _write(self.path, data)
        return value

    def update(
        self,
        game_id: str,
        *,
        values: dict[str, Any] | None = None,
        keybinds: dict[str, Any] | None = None,
        dpi: Any = ...,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Merge a change into one game's profile and return the whole profile.

        A value or keybind of ``None`` removes it (back to the game default).
        ``dpi=None`` makes the game follow the default DPI again; leaving it
        out keeps what is saved. Everything is checked before anything is
        written, so one bad field leaves the file untouched.
        """
        game = _game_or_raise(game_id)
        settings = settings_by_key(game)
        binds = keybind_ids(game)
        clean_values: dict[str, Any] = {}
        for key, value in (values or {}).items():
            if key not in settings:
                raise ValueError(f"Unknown setting: {key}")
            clean_values[key] = check_value(settings[key], value)
        clean_binds: dict[str, str | None] = {}
        for key, value in (keybinds or {}).items():
            if key not in binds:
                raise ValueError(f"Unknown keybind: {key}")
            clean_binds[key] = None if value is None else check_key(value)
        clean_dpi = None if dpi is None or dpi is ... else check_dpi(dpi)
        if notes is not None and (not isinstance(notes, str) or len(notes) > MAX_NOTES_LEN):
            raise ValueError(f"Notes are text up to {MAX_NOTES_LEN} characters")

        with _LOCK:
            data = _read(self.path)
            profile = {**_blank_profile(), **data["games"].get(game_id, {})}
            for key, value in clean_values.items():
                if value is None:
                    profile["values"].pop(key, None)
                else:
                    profile["values"][key] = value
            for key, value in clean_binds.items():
                if value is None:
                    profile["keybinds"].pop(key, None)
                else:
                    profile["keybinds"][key] = value
            if dpi is not ...:
                profile["dpi"] = clean_dpi
            if notes is not None:
                profile["notes"] = notes
            profile["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            data["games"][game_id] = profile
            _write(self.path, data)
        return profile

    def reset(self, game_id: str) -> bool:
        """Forget one game's profile. Returns whether there was one."""
        _game_or_raise(game_id)
        with _LOCK:
            data = _read(self.path)
            existed = data["games"].pop(game_id, None) is not None
            if existed:
                _write(self.path, data)
        return existed
