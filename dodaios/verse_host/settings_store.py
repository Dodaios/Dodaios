"""The ``verse.*`` settings: one small JSON store under ``<DATA_DIR>/verse/``.

Contract 3.2 and 14: ``welcome.settings`` carries them, ``settings.set``
writes them, ``settings.changed`` announces them, and the one-time
``POST /api/verse/settings/import`` moves the values the web Verse kept in
browser storage. The file layout is internal (not frozen by the contract).

Keys also kept here that never cross the bridge: ``told_seq`` (the highest
award Verse has shown), ``unreal_preview`` (the launcher card flag),
``dev_bridge`` (dev discovery file), ``imported`` (import done) and
``arcade_best`` (the simulator record imported from the web arcade).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Final

from .env import getenv

log = logging.getLogger(__name__)

DEFAULT_SETTINGS: Final[dict[str, Any]] = {
    "gore": "full",
    "reduced_motion": False,
    "return_key": "F10",
    "ui_sound": True,
    "level_sound": True,
    "uniform": "standard",
    "view": {
        "mode": "third",
        "sensitivity": 1.0,
        "invert_y": False,
        "fov_third": 70,
        "fov_first": 85,
        "quality": "auto",
        "volume": 0.7,
    },
}
_KEY_NAME = re.compile(r"^[A-Za-z0-9_+\-]{1,24}$")


class SettingsError(ValueError):
    """A ``settings.set`` value or key the contract does not allow."""


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _check_view(view: Any) -> dict[str, Any]:
    if not isinstance(view, dict) or not view:
        raise SettingsError("view must be a non-empty object")
    out: dict[str, Any] = {}
    for key, value in view.items():
        if key == "mode":
            if value not in ("overview", "third", "first"):
                raise SettingsError(f"view.mode {value!r}")
        elif key == "quality":
            if value not in ("auto", "high", "low"):
                raise SettingsError(f"view.quality {value!r}")
        elif key == "invert_y":
            if not isinstance(value, bool):
                raise SettingsError("view.invert_y must be a boolean")
        elif key == "sensitivity":
            if not _is_number(value) or value <= 0 or value > 20:
                raise SettingsError("view.sensitivity must be a number above 0")
        elif key in ("fov_third", "fov_first"):
            if not _is_number(value) or not 30 <= value <= 130:
                raise SettingsError(f"view.{key} must be 30..130")
        elif key == "volume":
            if not _is_number(value) or not 0 <= value <= 1:
                raise SettingsError("view.volume must be 0..1")
        else:
            raise SettingsError(f"unknown setting view.{key}")
        out[key] = value
    return out


def validate(patch: Any) -> dict[str, Any]:
    """A ``settings.set`` body checked key by key; unknown keys raise."""
    if not isinstance(patch, dict) or not patch:
        raise SettingsError("settings.set needs at least one setting")
    out: dict[str, Any] = {}
    for key, value in patch.items():
        if key == "gore":
            if value not in ("full", "reduced"):
                raise SettingsError(f"gore {value!r}")
        elif key in ("reduced_motion", "ui_sound", "level_sound"):
            if not isinstance(value, bool):
                raise SettingsError(f"{key} must be a boolean")
        elif key == "return_key":
            if not isinstance(value, str) or not _KEY_NAME.match(value) or value == "Escape":
                raise SettingsError("return_key must be a key name other than Escape")
        elif key == "uniform":
            if not isinstance(value, str) or not 1 <= len(value) <= 40:
                raise SettingsError("uniform must be a short id")
        elif key == "view":
            value = _check_view(value)
        else:
            raise SettingsError(f"unknown setting {key}")
        out[key] = value
    return out


class SettingsStore:
    """Thread-safe JSON file of the Verse settings and its small state."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            from dodaios.core.config import DATA_DIR

            path = Path(DATA_DIR) / "verse" / "settings.json"
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._data is None:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = raw if isinstance(raw, dict) else {}
            except FileNotFoundError:  # first run: no settings file yet
                self._data = {}
            except (OSError, ValueError):
                log.warning("verse: settings file unreadable, starting from defaults")
                self._data = {}
        return self._data

    def _save(self) -> None:
        assert self._data is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        """Every bridge setting: stored values over the defaults."""
        with self._lock:
            stored = self._load().get("settings", {})
        out = copy.deepcopy(DEFAULT_SETTINGS)
        for key, value in stored.items():
            if key == "view" and isinstance(value, dict):
                out["view"].update(value)
            elif key in out:
                out[key] = value
        return out

    def is_set(self, key: str) -> bool:
        with self._lock:
            stored = self._load().get("settings", {})
        head, _, sub = key.partition(".")
        if sub:
            return isinstance(stored.get(head), dict) and sub in stored[head]
        return head in stored

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Write a validated patch; returns every setting after the write."""
        patch = validate(patch)
        with self._lock:
            data = self._load()
            stored = data.setdefault("settings", {})
            for key, value in patch.items():
                if key == "view":
                    stored.setdefault("view", {}).update(value)
                else:
                    stored[key] = value
            self._save()
        return self.settings()

    # ------------------------------------------------------------------ state
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._load().get(key, default)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._load()[key] = value
            self._save()

    def told_seq(self) -> int:
        value = self.get("told_seq", 0)
        return value if isinstance(value, int) and value >= 0 else 0

    def raise_told_seq(self, seq: int) -> int:
        """Store ``seq`` when it is higher; returns the stored value."""
        with self._lock:
            data = self._load()
            current = data.get("told_seq", 0)
            if not isinstance(current, int) or seq > current:
                data["told_seq"] = seq
                self._save()
            return int(data["told_seq"]) if "told_seq" in data else 0

    def flag(self, name: str, env: str | None = None) -> bool:
        """A boolean flag of this store, overridden by ``env`` when set."""
        value = getenv(env) if env else ""
        if value:
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(self.get(name, False))

    def set_flag(self, name: str, value: bool) -> None:
        self.put(name, bool(value))
