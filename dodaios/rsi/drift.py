"""New models and new CLI versions: epochs, a drift report, and what a new cell inherits.

Coding CLIs update themselves and models change under the same name. Every new
answering model or CLI version line (``claude-cli 2.2`` after ``2.1``) opens an
*epoch*: a new cell, compared only with itself. Two things follow:

* **Inheritance.** A cell without a policy of its own runs under the active
  policy of its nearest predecessor (same domain, model and runner, the
  closest earlier version line), until it has its own (:func:`inherited`).
* **A drift report.** Once an epoch has :data:`N_EPOCH` runs, its pass rate,
  one-shot rate and cost are compared with the last runs of the epoch before
  it, with the same lower bounds the selector uses, and one note with a
  recommendation is written: a drop is named only when it is shown, not when
  40 runs merely cannot rule it out. Nothing switches a model or a CLI by
  itself.

    python -m dodaios.rsi.drift            # the notes, newest first
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from . import selector, stats

__all__ = ["N_EPOCH", "Note", "epochs", "inherited", "notes"]

#: Runs of a new epoch before it is compared with the one before it.
N_EPOCH: Final[int] = 40
_LINE = re.compile(r"^(?P<runner>\S+)\s+(?P<line>[\d.]+)$")


def _parts(cell: str) -> tuple[str, str, str, tuple[int, ...]] | None:
    """``(domain, model, runner, version line)`` of a cell, or ``None``."""
    domain, _, rest = cell.partition("|")
    model, _, harness = rest.partition("|")
    found = _LINE.match(harness.strip())
    if not found:
        return None
    try:
        line = tuple(int(n) for n in found["line"].split("."))
    except ValueError:  # a version line that is no number has no place in the order
        return None
    return domain, model, found["runner"], line


def predecessor(cell: str, known: Iterable[str]) -> str:
    """The cell ``cell`` follows: same domain, model and runner, the closest earlier line."""
    mine = _parts(cell)
    if mine is None:
        return ""
    best: tuple[tuple[int, ...], str] | None = None
    for other in known:
        theirs = _parts(other)
        if theirs is None or theirs[:3] != mine[:3] or theirs[3] >= mine[3]:
            continue
        if best is None or theirs[3] > best[0]:
            best = (theirs[3], other)
    return best[1] if best else ""


def inherited(cell: str, active_cells: Iterable[str]) -> str:
    """The cell whose active policy a cell without one runs under; ``""`` for none."""
    return predecessor(cell, active_cells)


@dataclass(frozen=True, slots=True)
class Note:
    """What one new epoch looks like next to the one before it."""

    cell: str
    previous: str
    runs: int
    pass_diff: float
    pass_lcb: float
    one_diff: float
    cost_ratio: float
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def epochs(runs: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Judged runs by cell, oldest first; runs that changed model or CLI on the way are left out."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        metrics = selector.metrics_of(run)
        if metrics is None or metrics.mixed:
            continue
        grouped[metrics.cell].append({**run, "_metrics": metrics})
    for members in grouped.values():
        members.sort(key=lambda r: int(r.get("started_ms") or 0))
    return dict(grouped)


def _recommend(better: stats.Bound, worse: stats.Bound, cost_ratio: float) -> str:
    """``better`` bounds new minus old, ``worse`` old minus new: each claims only what it shows."""
    if better.lcb > 0:
        return "the new version passes more often; nothing to do"
    if worse.lcb > 0:
        return (
            "the new version may pass less often; compare a few of its runs by hand, and "
            "pin the earlier model or CLI version if they confirm it"
        )
    if cost_ratio > 1.25:
        return "the new version costs over a quarter more per run; worth a look"
    return "no difference shown; nothing to do"


def notes(
    runs: Iterable[dict[str, Any]], *, n: int = N_EPOCH, samples: int = stats.SAMPLES
) -> list[Note]:
    """One note per epoch with ``n`` runs that has a predecessor with ``n`` runs."""
    grouped = epochs(runs)
    out: list[Note] = []
    for cell, members in grouped.items():
        previous = predecessor(cell, (c for c, m in grouped.items() if len(m) >= n))
        if not previous or len(members) < n:
            continue
        new = [r["_metrics"] for r in members[:n]]
        old = [r["_metrics"] for r in grouped[previous][-n:]]
        new_pass = [("all", m.passed) for m in new]
        old_pass = [("all", m.passed) for m in old]
        pass_bound = stats.unpaired_lcb(new_pass, old_pass, samples=samples)
        worse = stats.unpaired_lcb(old_pass, new_pass, samples=samples)
        cost_new = sum(m.cost for m in new) / n
        cost_old = sum(m.cost for m in old) / n
        ratio = cost_new / cost_old if cost_old else 1.0
        out.append(Note(
            cell=cell, previous=previous, runs=n,
            pass_diff=pass_bound.diff, pass_lcb=pass_bound.lcb,
            one_diff=sum(m.one for m in new) / n - sum(m.one for m in old) / n,
            cost_ratio=ratio, recommendation=_recommend(pass_bound, worse, ratio),
        ))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from .report import default_db, load_runs

    parser = argparse.ArgumentParser(prog="python -m dodaios.rsi.drift", description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="path of verification.db")
    args = parser.parse_args(argv)
    found = notes(load_runs(args.db or default_db()))
    sys.stdout.write(json.dumps([n.to_dict() for n in found], indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
