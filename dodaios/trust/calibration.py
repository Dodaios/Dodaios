"""Calibration of the lead's pre-action predictions (read-only, no model call).

Each stored prediction (``dodaios.trust.expectations``) has a stated confidence
and a verdict. A ``hit`` counts as 1 and a ``miss`` as 0; ``unknown`` verdicts
and predictions without a confidence are counted but not scored.

* Brier score: mean of ``(confidence - outcome) ** 2``; 0 is perfect, 0.25 is
  what always saying 50 % earns.
* Reliability table: predictions grouped by stated confidence; in a calibrated
  agent the share of hits in a bin matches the bin's mean confidence.

The same numbers are given overall, per tool class, per seat and per week.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Final

WEEK_MS: Final = 7 * 24 * 3600 * 1000
#: Monday 1970-01-05 00:00 UTC, so weeks line up with the agent score windows.
_EPOCH_MONDAY_MS: Final = 4 * 24 * 3600 * 1000
BINS: Final = 5


def brier(pairs: Iterable[tuple[float, int]]) -> float | None:
    """Brier score of ``(confidence, outcome)`` pairs; ``None`` without any."""
    items = list(pairs)
    if not items:
        return None
    return sum((p - o) ** 2 for p, o in items) / len(items)


def reliability(pairs: Iterable[tuple[float, int]], bins: int = BINS) -> list[dict[str, Any]]:
    """One row per non-empty confidence bin (equal widths over 0..1)."""
    grouped: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p, o in pairs:
        grouped[min(bins - 1, int(p * bins))].append((p, o))
    rows = []
    for idx in sorted(grouped):
        items = grouped[idx]
        mean_conf = sum(p for p, _ in items) / len(items)
        hit_rate = sum(o for _, o in items) / len(items)
        rows.append(
            {
                "low": idx / bins,
                "high": (idx + 1) / bins,
                "n": len(items),
                "mean_confidence": mean_conf,
                "hit_rate": hit_rate,
                "gap": mean_conf - hit_rate,  # positive: overconfident
            }
        )
    return rows


def _pairs(rows: Iterable[dict[str, Any]]) -> list[tuple[float, int]]:
    pairs: list[tuple[float, int]] = []
    for r in rows:
        conf = r.get("confidence")
        verdict = r.get("verdict")
        if isinstance(conf, (int, float)) and verdict in ("hit", "miss"):
            pairs.append((float(conf), 1 if verdict == "hit" else 0))
    return pairs


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = _pairs(rows)
    hits = sum(o for _, o in pairs)
    score = brier(pairs)
    return {
        "predictions": len(rows),
        "scored": len(pairs),
        "unknown": sum(1 for r in rows if r.get("verdict") == "unknown"),
        "unscored": len(rows) - len(pairs) - sum(1 for r in rows if r.get("verdict") == "unknown"),
        "hits": hits,
        "brier": score,
        "mean_confidence": sum(p for p, _ in pairs) / len(pairs) if pairs else None,
        "hit_rate": hits / len(pairs) if pairs else None,
        "reliability": reliability(pairs),
    }


def _group(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[str(r.get(key) or "unknown")].append(r)
    return {name: _summary(items) for name, items in sorted(grouped.items())}


def week_start(ts_ms: int) -> int:
    return ts_ms - ((ts_ms - _EPOCH_MONDAY_MS) % WEEK_MS)


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The calibration report for stored predictions (see ``AuditLog.predictions``)."""
    by_week: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_week[week_start(int(r.get("ts_ms") or 0))].append(r)
    total = _summary(rows)
    return {
        **total,
        # 1 is perfect, 0.75 is what a constant 50 % earns: a score to read, not to chase.
        "calibration_score": None if total["brier"] is None else 1.0 - total["brier"],
        "by_class": _group(rows, "class"),
        "by_seat": _group(rows, "seat"),
        "weekly": [
            {"start_ms": start, **{k: v for k, v in _summary(items).items() if k != "reliability"}}
            for start, items in sorted(by_week.items())
        ],
    }


def audit_report(audit: Any, since_ms: int = 0) -> dict[str, Any]:
    """The report straight from an :class:`~dodaios.trust.audit.AuditLog`."""
    return build_report(audit.predictions(since_ms))


def format_lines(report: dict[str, Any]) -> list[str]:
    """Plain-text lines for the agent score table."""
    if not report.get("predictions"):
        return ["Calibration: no stated predictions yet"]
    brier_value = report["brier"]
    lines = [
        f"Calibration: {report['scored']} scored of {report['predictions']} predictions"
        + (f", Brier {brier_value:.3f}" if brier_value is not None else ""),
    ]
    for row in report["reliability"]:
        lines.append(
            f"  stated {row['low']:.0%}-{row['high']:.0%}: n={row['n']:<4} "
            f"mean {row['mean_confidence']:.0%}, hit {row['hit_rate']:.0%}"
        )
    return lines


__all__ = ["audit_report", "brier", "build_report", "format_lines", "reliability", "week_start"]
