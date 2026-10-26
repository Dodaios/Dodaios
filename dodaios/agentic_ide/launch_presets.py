"""Saved workspace lineups ("presets") for the New-workspace dialog.

A preset is a name plus a lineup: which coding agents to start and how many of
each, for example two Claude Code, one Codex and one Kimi Code. Picking it in
the dialog fills the lineup in one click.

Stored in the backend for the same reason as ``ui_prefs``: the desktop window
starts every run with empty browser storage, so presets kept in the page would
be gone after each restart. One JSON file under the per-user data directory,
written atomically; a broken file reads as "no presets" instead of breaking the
dialog.

Agent names are not checked against the installed agents. A preset may name an
agent that is not installed right now (or only on another computer); the dialog
shows it as unavailable instead of the store silently dropping it.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

MAX_PRESETS = 24
MAX_NAME = 40
MAX_AGENT_NAME = 64
#: Same ceiling as one workspace start request.
MAX_SESSIONS = 100

_AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _store_path() -> Path:
    from dodaios.core.paths import user_data_dir

    return user_data_dir() / "agentic_ide" / "launch_presets.json"


def _clean_preset(raw: Any) -> dict[str, Any] | None:
    """One preset in canonical form, or None when it cannot be used."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()[:MAX_NAME]
    if not name:
        return None
    lineup: list[dict[str, Any]] = []
    total = 0
    for entry in raw.get("agents") or []:
        if not isinstance(entry, dict):
            continue
        agent = str(entry.get("agent") or "").strip()
        if not agent or len(agent) > MAX_AGENT_NAME or not _AGENT_RE.match(agent):
            continue
        try:
            count = int(entry.get("count", 1))
        except (TypeError, ValueError):  # A non-numeric count drops only that entry.
            continue
        count = max(0, min(count, MAX_SESSIONS - total))
        if count <= 0:
            continue
        # Same agent twice merges into one entry, keeping its first position.
        existing = next((item for item in lineup if item["agent"] == agent), None)
        if existing:
            existing["count"] += count
        else:
            lineup.append({"agent": agent, "count": count})
        total += count
    if not lineup:
        return None
    preset_id = str(raw.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", preset_id):
        preset_id = uuid.uuid4().hex[:12]
    return {"id": preset_id, "name": name, "agents": lineup}


def clean_presets(raw: Any) -> list[dict[str, Any]]:
    """Every usable preset, in order, without duplicate ids or names."""
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        preset = _clean_preset(item)
        if preset is None or preset["name"].casefold() in seen_names:
            continue
        while preset["id"] in seen_ids:
            preset["id"] = uuid.uuid4().hex[:12]
        seen_ids.add(preset["id"])
        seen_names.add(preset["name"].casefold())
        result.append(preset)
        if len(result) >= MAX_PRESETS:
            break
    return result


def _load_raw() -> dict[str, Any] | None:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except FileNotFoundError:  # A first run has no presets file by design.
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Agentic IDE: unreadable launch presets, starting empty: {}", exc)
        return {}
    return data if isinstance(data, dict) else {}


def stored() -> bool:
    """True once presets were ever saved, even if the list was emptied since.

    The dialog offers starter presets only before that, so deleting them all
    does not bring them back.
    """
    return _load_raw() is not None


def list_presets() -> list[dict[str, Any]]:
    data = _load_raw() or {}
    return clean_presets(data.get("presets"))


def save_presets(presets: Any) -> list[dict[str, Any]]:
    """Replace the whole list. Returns what was stored, in canonical form."""
    cleaned = clean_presets(presets)
    target = _store_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"presets": cleaned}, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        logger.warning("Agentic IDE: could not persist launch presets: {}", exc)
    return cleaned
