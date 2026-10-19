"""How often each tool actually ran, read from the flight recorder.

The flight recorder already writes every ``ActionExecuted`` event, on every
surface, into ``data/flight_recorder/YYYY-MM-DD.jsonl``. Nothing counted them:
the question "which tools does this install really use" could only be answered
per voice session (``dodaios/runs``), or as a days-used histogram that never
filled. This module answers it for a window of days, from the files that are
already there. It records nothing and changes no behaviour.

The numbers exist to decide how many tools a model has to be SHOWN: when a
dozen tools carry nine calls in ten, the rest can wait behind a lookup
(``dodaios/brain/tool_shortlist.py``). ``coverage`` states exactly that.

Synchronous file reads; call it off the event loop.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["DEFAULT_DATA_DIR", "tool_usage"]

#: Where the desktop app's flight recorder writes (``server._init_flight_recorder``).
DEFAULT_DATA_DIR = Path("data") / "flight_recorder"

_EVENT = "ActionExecuted"
#: Shares of all calls for which ``coverage`` says how many tools carry them.
_COVERAGE_SHARES = (50, 80, 90, 95, 99)


def _file_day(path: Path) -> date | None:
    """The day a recorder file covers: ``2026-10-13.jsonl``, ``2026-10-13-2.jsonl``."""
    try:
        return date.fromisoformat(path.name[:10])
    except ValueError:  # not a recorder day file (a stray .jsonl in the folder)
        return None


def _executions(path: Path) -> Iterable[tuple[str, bool, int]]:
    """``(tool name, succeeded, ts_ms)`` for every execution recorded in ``path``."""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.debug("tool usage: %s could not be opened: %s", path.name, exc)
        return
    with handle:
        for line in handle:
            # A day's file holds every bus event; skip the rest before parsing.
            if _EVENT not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:  # a line cut off by a crash in the middle of a write
                continue
            if not isinstance(record, dict) or record.get("event") != _EVENT:
                continue
            payload = record.get("payload")
            name = payload.get("tool_name") if isinstance(payload, dict) else None
            if not isinstance(name, str) or not name:
                continue
            ts_ns = record.get("ts_ns")
            ts_ms = int(ts_ns) // 1_000_000 if isinstance(ts_ns, (int, float)) else 0
            yield name, payload.get("success") is not False, ts_ms


def tool_usage(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    days: int = 30,
    registered: Iterable[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Executions per tool over the last ``days`` days (today included).

    ``registered`` are the tool names the brain currently holds; given, the
    result also lists the ones that never ran in the window. ``days`` of ``0``
    reads everything on disk.

    Returns ``window_days``, ``total_calls``, ``distinct_tools``, ``tools``
    (most used first, each with ``calls``, ``succeeded``, ``failed``,
    ``days_used``, ``last_used_ms`` and ``share`` of all calls) and
    ``coverage``: for each share in :data:`_COVERAGE_SHARES`, how many of the
    most used tools carry that share of all calls.
    """
    end = today or datetime.now().date()
    start = end - timedelta(days=days - 1) if days > 0 else None
    calls: dict[str, int] = {}
    failed: dict[str, int] = {}
    last: dict[str, int] = {}
    used_on: dict[str, set[date]] = {}
    files = sorted(data_dir.glob("*.jsonl")) if data_dir.is_dir() else []
    for path in files:
        day = _file_day(path)
        if day is None or day > end or (start is not None and day < start):
            continue
        for name, succeeded, ts_ms in _executions(path):
            calls[name] = calls.get(name, 0) + 1
            if not succeeded:
                failed[name] = failed.get(name, 0) + 1
            if ts_ms > last.get(name, 0):
                last[name] = ts_ms
            used_on.setdefault(name, set()).add(day)
    total = sum(calls.values())
    ranked = sorted(calls, key=lambda name: (-calls[name], name))
    tools = [
        {
            "tool": name,
            "calls": calls[name],
            "succeeded": calls[name] - failed.get(name, 0),
            "failed": failed.get(name, 0),
            "days_used": len(used_on[name]),
            "last_used_ms": last.get(name, 0),
            "share": round(calls[name] / total, 4) if total else 0.0,
        }
        for name in ranked
    ]
    coverage: dict[str, int] = {}
    running = 0
    wanted = list(_COVERAGE_SHARES)
    for position, name in enumerate(ranked, start=1):
        running += calls[name]
        while wanted and running * 100 >= wanted[0] * total:
            coverage[str(wanted.pop(0))] = position
    result: dict[str, Any] = {
        "window_days": days,
        "total_calls": total,
        "distinct_tools": len(ranked),
        "tools": tools,
        "coverage": coverage,
    }
    if registered is not None:
        names = sorted(set(registered))
        result["registered"] = len(names)
        result["never_used"] = [name for name in names if name not in calls]
    return result
