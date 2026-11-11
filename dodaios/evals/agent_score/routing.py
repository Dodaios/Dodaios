"""Routing-eval results as a score input and as self-change evidence.

``eval-results/lead-routing-<stamp>.json`` files (written by
``scripts/lead_routing_eval.py``, see docs/lead-routing-evals.md) give, per seat,
an accuracy per routing category. Two uses, both read-only:

* the newest run's per-category accuracy, mapped onto task classes, is blended
  into a class's utility (``routing_blend`` weight);
* a drop in overall accuracy between two consecutive runs of one seat is a
  *self-change regression* (Tier-C gate).

The synthetic reference seat proves plumbing, not a model, so it is skipped.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

#: Routing eval category -> task classes it speaks for.
CATEGORY_CLASSES: Final[dict[str, tuple[str, ...]]] = {
    "delegate_agent": ("coding_delegation",),
    "coding_pane": ("coding_delegation",),
    "team_thread": ("coding_delegation",),
    "ask_agent": ("coding_delegation",),
    "mission_artifact": ("artifacts",),
    "status": ("status_orchestration",),
    "memory": ("memory",),
    "settings": ("settings",),
    "mail_calendar": ("mail", "calendar"),
    "web_browser": ("research_web",),
    "computer_use": ("computer_use",),
    "answer_directly": ("chit_chat",),
}
_SKIP_SEATS: Final[frozenset[str]] = frozenset({"reference", "recorded"})
_STAMP: Final[re.Pattern[str]] = re.compile(r"(\d{8})-(\d{6})")


@dataclass(frozen=True, slots=True)
class RoutingRun:
    ts_ms: int
    seat: str
    accuracy: float
    categories: dict[str, float]


def _stamp_ms(name: str, fallback: float) -> int:
    m = _STAMP.search(name)
    if m:
        try:
            dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            return int(dt.replace(tzinfo=UTC).timestamp() * 1000)
        except ValueError:
            pass
    return int(fallback * 1000)


def load_runs(results_dir: Path | None) -> list[RoutingRun]:
    """All real routing runs, oldest first. Missing or damaged files are skipped."""
    if results_dir is None or not Path(results_dir).is_dir():
        return []
    runs: list[RoutingRun] = []
    for path in sorted(Path(results_dir).glob("lead-routing-*.json")):
        if path.name.endswith(".recording.json"):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            log.warning("agent score: %s is not readable", path)
            continue
        ts = _stamp_ms(path.name, mtime)
        for seat in (raw.get("seats") if isinstance(raw, dict) else None) or []:
            run = _run_from(seat, ts)
            if run is not None:
                runs.append(run)
    runs.sort(key=lambda r: r.ts_ms)
    return runs


def _run_from(seat: Any, ts_ms: int) -> RoutingRun | None:
    if not isinstance(seat, dict) or str(seat.get("seat") or "") in _SKIP_SEATS:
        return None
    acc = seat.get("accuracy")
    if not isinstance(acc, (int, float)):
        return None
    cats: dict[str, float] = {}
    for name, block in (seat.get("categories") or {}).items():
        value = block.get("accuracy") if isinstance(block, dict) else None
        if isinstance(value, (int, float)):
            cats[str(name)] = float(value)
    return RoutingRun(ts_ms, str(seat.get("seat") or ""), float(acc), cats)


def class_accuracy(runs: list[RoutingRun], until_ms: int | None = None) -> dict[str, float]:
    """Task class -> accuracy from the newest run (up to ``until_ms``) that covers it."""
    out: dict[str, float] = {}
    for run in sorted(runs, key=lambda r: r.ts_ms, reverse=True):
        if until_ms is not None and run.ts_ms > until_ms:
            continue
        sums: dict[str, list[float]] = {}
        for category, value in run.categories.items():
            for cls in CATEGORY_CLASSES.get(category, ()):
                sums.setdefault(cls, []).append(value)
        for cls, values in sums.items():
            out.setdefault(cls, sum(values) / len(values))
    return out


def regressions(runs: list[RoutingRun], tolerance: float) -> list[RoutingRun]:
    """Runs whose accuracy fell more than ``tolerance`` below the seat's previous run."""
    last: dict[str, float] = {}
    bad: list[RoutingRun] = []
    for run in sorted(runs, key=lambda r: r.ts_ms):
        before = last.get(run.seat)
        if before is not None and before - run.accuracy > tolerance:
            bad.append(run)
        last[run.seat] = run.accuracy
    return bad
