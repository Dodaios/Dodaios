"""What the recorded coding runs look like, per cell.

    python -m dodaios.rsi.report                 # table of the last 30 days
    python -m dodaios.rsi.report --since-days 7
    python -m dodaios.rsi.report --json

A *cell* is (domain when the run was bound, model, runner and CLI version line):
the group inside which runs are comparable. The report only reads
``verification.db`` (opened read-only) and calls no model.

The model of a run is the one that answered when the thread's own events named
it, else the requested one; ``(default)`` means the CLI picked it and did not
say which.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

__all__ = ["cells", "load_runs", "main", "render"]

_DAY_MS = 24 * 3600 * 1000


def default_db() -> Path:
    from dodaios.core.config import DATA_DIR

    return Path(DATA_DIR) / "verification.db"


def load_runs(db: Path | str, *, since_ms: int = 0) -> list[dict[str, Any]]:
    """Every run started at or after ``since_ms``; ``[]`` when there is no record yet."""
    path = Path(db)
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE started_ms >= ? ORDER BY started_ms", (int(since_ms),)
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _cell_of(run: dict[str, Any]) -> tuple[str, str, str]:
    model = str(run.get("model_resolved") or run.get("model_requested") or "(default)")
    runner = str(run.get("runner") or run.get("provider") or "?")
    line = str(run.get("harness_line") or "")
    return str(run.get("primary_domain") or "other"), model, f"{runner} {line}".strip()


def _mean(values: Iterable[Any]) -> float | None:
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return sum(numbers) / len(numbers) if numbers else None


def cells(runs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per cell, largest first."""
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(_cell_of(run), []).append(run)
    out: list[dict[str, Any]] = []
    for (domain, model, harness), members in grouped.items():
        ended = [r for r in members if r.get("state") == "ended"]
        wall = _mean(r.get("wall_ms") for r in ended)
        out.append(
            {
                "domain": domain,
                "model": model,
                "harness": harness,
                "runs": len(members),
                "ended": len(ended),
                "done": sum(1 for r in ended if r.get("turn_status") == "done"),
                "error": sum(1 for r in ended if r.get("turn_status") == "error"),
                "cancelled": sum(1 for r in ended if r.get("turn_status") == "cancelled"),
                "open": sum(1 for r in members if r.get("state") == "running"),
                "interrupted": sum(1 for r in members if r.get("state") == "interrupted"),
                "mixed_model": sum(1 for r in members if r.get("mixed_model")),
                "person_intervened": sum(1 for r in members if r.get("person_intervened")),
                "isolated": sum(1 for r in members if r.get("isolated")),
                "mean_minutes": round(wall / 60_000, 1) if wall is not None else None,
                "mean_tokens_out": _mean(r.get("tokens_out") for r in ended),
            }
        )
    return sorted(out, key=lambda c: (-c["runs"], c["domain"], c["model"], c["harness"]))


def render(rows: Sequence[dict[str, Any]], *, total: int) -> str:
    """The cells as a plain table."""
    if not rows:
        return "No coding runs on record. Set `[rsi] enabled = true` to record them."
    head = ("domain", "model", "harness", "runs", "done", "error", "cancelled", "open", "min")
    table = [
        (
            c["domain"], c["model"], c["harness"], str(c["runs"]), str(c["done"]),
            str(c["error"]), str(c["cancelled"]), str(c["open"]),
            "-" if c["mean_minutes"] is None else f"{c['mean_minutes']:.1f}",
        )
        for c in rows
    ]
    widths = [max(len(head[i]), *(len(line[i]) for line in table)) for i in range(len(head))]
    lines = ["  ".join(text.ljust(width) for text, width in zip(head, widths, strict=True))]
    lines += [
        "  ".join(text.ljust(width) for text, width in zip(line, widths, strict=True))
        for line in table
    ]
    lines.append(f"{total} run(s) in {len(rows)} cell(s).")
    return "\n".join(line.rstrip() for line in lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dodaios.rsi.report", description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="path of verification.db")
    parser.add_argument("--since-days", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="print the cells as JSON")
    args = parser.parse_args(argv)
    since_ms = int(time.time() * 1000 - max(0.0, args.since_days) * _DAY_MS)
    runs = load_runs(args.db or default_db(), since_ms=since_ms)
    rows = cells(runs)
    if args.json:
        sys.stdout.write(json.dumps({"runs": len(runs), "cells": rows}, indent=2) + "\n")
    else:
        sys.stdout.write(render(rows, total=len(runs)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
