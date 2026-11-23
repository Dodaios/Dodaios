"""Run the seed suite and print what it measures: ``python -m dodaios.rsi.bench``.

    python -m dodaios.rsi.bench                       # the assistant as it ships
    python -m dodaios.rsi.bench --set recall.turn_limit=3 --set recall.relative_floor=0.5

Reads nothing from an installation and writes nothing: the suite builds the
invented person's memory in RAM. With ``--set`` it also prints the paired
comparison against the shipped defaults, per split.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any

from dodaios.rsi import overlay as overlays
from dodaios.rsi import params
from dodaios.rsi.sequential import interval_of

from . import run, seedsuite
from .model import Split, Task
from .recall import RecallWorld


def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a number or true/false: {text!r}") from exc


def _overrides(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in pairs:
        name, _, raw = item.partition("=")
        param = params.INDEX.by_name(name.strip())
        out[param.name] = param.coerce(_value(raw.strip()))
    return out


def _table(rows: list[tuple[str, ...]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
                     for row in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dodaios.rsi.bench", description=__doc__)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="a parameter value to compare with the shipped default")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = parser.parse_args(argv)
    candidate = _overrides(args.set)

    world = seedsuite.build_world()
    worlds = {seedsuite.SEED_WORLD: RecallWorld(world.vault, world.ids)}
    tasks = seedsuite.recall_tasks()
    by_split: dict[Split, list[Task]] = defaultdict(list)
    for task in tasks:
        by_split[task.split].append(task)

    report: dict[str, Any] = {"suite": "seed", "domain": "recall", "tasks": len(tasks),
                              "set": candidate, "splits": {}}
    rows = [("split", "tasks", "score", "tokens/task")]
    if candidate:
        rows = [("split", "tasks", "shipped", "with --set", "difference", "low", "high",
                 "tokens/task")]
    for split in Split:
        chosen = run.shuffled(by_split[split], f"cli:{split.value}")
        base = run.measure(chosen, overlays.FACTORY, worlds)
        n = len(base)
        mean = sum(r.score for r in base) / n if n else 0.0
        tokens = sum(r.tokens for r in base) / n if n else 0.0
        entry: dict[str, Any] = {"tasks": n, "score": round(mean, 4), "tokens": round(tokens, 1)}
        if candidate:
            other = run.measure(chosen, overlays.Overlay(label="cli", params=candidate), worlds)
            paired = run.pair(base, other)
            found = interval_of(paired.differences)
            entry.update(candidate=round(paired.candidate_mean, 4), diff=round(found.mean, 4),
                         low=round(found.low, 4), high=round(found.high, 4),
                         candidate_tokens=round(paired.candidate_tokens, 1))
            rows.append((split.value, str(n), f"{mean:.3f}", f"{paired.candidate_mean:.3f}",
                         f"{found.mean:+.3f}", f"{found.low:+.3f}", f"{found.high:+.3f}",
                         f"{tokens:.0f} -> {paired.candidate_tokens:.0f}"))
        else:
            rows.append((split.value, str(n), f"{mean:.3f}", f"{tokens:.0f}"))
        report["splits"][split.value] = entry
    world.close()

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Seed suite, recall: {len(tasks)} tasks. A score is the share of messages for "
              "which the model got the memory it needed (or nothing, when it needed none).")
        print(_table(rows))
        if candidate:
            print("low/high: bounds of the mean difference per task that stay valid at every "
                  "look (5 % per side).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
