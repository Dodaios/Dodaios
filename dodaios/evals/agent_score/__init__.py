"""User-weighted lifetime score of the lead, from local data only.

``python -m dodaios.evals.agent_score`` prints the table and writes the JSON
report into ``eval-results/``. See docs/agent-score.md.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import ScoreConfig, load_config
from .routing import load_runs
from .score import compute_score
from .turns import read_lead_turns

__all__ = ["ScoreConfig", "build_report", "format_table", "load_config"]


def build_report(
    chat_db: Path,
    results_dir: Path | None = None,
    cfg: ScoreConfig | None = None,
    *,
    since_ms: int = 0,
    until_ms: int | None = None,
) -> dict[str, Any]:
    """Read the lead's turns and the routing results, return the JSON-ready report."""
    cfg = cfg or ScoreConfig()
    report = compute_score(
        read_lead_turns(chat_db, since_ms, until_ms), cfg, load_runs(results_dir)
    )
    report["generated_ms"] = int(time.time() * 1000)
    return report


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:5.1f}%"


def format_table(report: dict[str, Any]) -> str:
    """The report as plain text: lifetime line, latest window classes, gates, weekly curve."""
    life = report["lifetime"]
    lines = [
        f"Lead score ({report['method']})",
        f"turns analysed: {report['turns']}",
        f"lifetime score: {_pct(life['score'])}   rated weeks: {life['rated_windows']}   "
        f"not rated: {life['not_rated_windows']}",
    ]
    if life["trend_per_week"] is not None:
        lines.append(f"trend: {life['trend_per_week'] * 100:+.2f} points per week")
    if life["efficiency"] is not None:
        lines.append(
            f"efficiency (score per USD-equivalent of cost+latency): {life['efficiency']:.1f}"
        )
    for flag in life["forgetting"]:
        lines.append(f"forgetting: {flag['class']} fell {_pct(flag['from'])} -> {_pct(flag['to'])}")
    latest = report.get("latest_window")
    if latest:
        lines += ["", f"Latest week ({_day(latest['start_ms'])}): {latest['status']}"]
        lines.append(f"  {'class':<22}{'turns':>6}{'weight':>9}{'utility':>9}")
        for c in latest["classes"]:
            lines.append(
                f"  {c['class']:<22}{c['turns']:>6}{_pct(c['weight']):>9}{_pct(c['utility']):>9}"
            )
        lines.append("  gates:")
        for g in latest["gates"]:
            lines.append(f"    [{g['status']:<7}] {g['label']}: {g['detail']}")
    if report["windows"]:
        lines += ["", "Weekly curve:"]
        for w in report["windows"]:
            score = _pct(w["upsilon"]) if w["rated"] else "not rated"
            lines.append(f"  {_day(w['start_ms'])}  turns {w['turns']:>4}  {score}")
    return "\n".join(lines)


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%d")
