"""How many benchmark tasks the person's past coding work gives.

    python -m dodaios.rsi.bench.past_work --repo . [--repo ../other] [--json]

Prints counts only: no request text leaves the records through this command.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dodaios.rsi.bench.model import Domain, Split
from dodaios.rsi.bench.past_work.intake import read_changes
from dodaios.rsi.bench.past_work.sessions import read_sessions
from dodaios.rsi.bench.past_work.tasks import LeftOut, Mined, logged_briefs, mine

_WHY = {
    LeftOut.NO_REQUEST: "opened without the person asking for anything in words",
    LeftOut.CONVERSATION: "too much was said before it to call one thing the request",
    LeftOut.AMBIGUOUS: "several things said since the previous pull request",
    LeftOut.NOT_MERGED: "not merged on the default branch of a given repository",
    LeftOut.REVERTED: "merged and taken back",
    LeftOut.EMPTY: "merged without changing a file",
    LeftOut.CREDENTIAL: "the person's words hold credential-shaped text",
    LeftOut.DUPLICATE: "another session already accounts for it",
}


def summary(mined: Mined) -> dict[str, object]:
    per_split: Counter[tuple[str, str]] = Counter(
        (task.domain.value, task.split.value) for task in mined.tasks
    )
    domains = sorted({task.domain.value for task in mined.tasks})
    return {
        "sessions": mined.sessions,
        "opened": mined.opened,
        "pieces_of_work": len({task.group for task in mined.tasks}),
        "tasks": {
            domain: {split.value: per_split[(domain, split.value)] for split in Split}
            for domain in domains
        },
        "left_out": dict(mined.left_out),
    }


def render(report: dict[str, object]) -> str:
    lines = [
        "Tasks from past coding work (read from the coding CLIs' own records)",
        f"sessions that opened a pull request: {report['sessions']}",
        f"pull requests they opened:           {report['opened']}",
        f"pieces of work that became tasks:    {report['pieces_of_work']}",
        "",
        f"{'domain':<10}" + "".join(f"{split.value:>10}" for split in Split) + f"{'all':>8}",
    ]
    tasks = report["tasks"]
    assert isinstance(tasks, dict)
    for domain in (Domain.BRIEF.value, Domain.CODING.value):
        row = tasks.get(domain, {})
        counts = [int(row.get(split.value, 0)) for split in Split]
        lines.append(f"{domain:<10}" + "".join(f"{n:>10}" for n in counts) + f"{sum(counts):>8}")
    left = report["left_out"]
    assert isinstance(left, dict)
    if left:
        lines += ["", "left out:"]
        lines += [f"  {count:>5}  {_WHY[LeftOut(reason)]}" for reason, count in left.items()]
    return "\n".join(lines)


def _store(folders: list[str], *, as_json: bool) -> int:
    from dodaios.core import config as core_config
    from dodaios.rsi.bench.past_work.intake import take_in
    from dodaios.rsi.bench.store import DB_NAME, BenchStore

    store = BenchStore(Path(core_config.DATA_DIR) / DB_NAME)
    try:
        if store.readonly:
            sys.stdout.write("the store was written by a newer app: nothing stored\n")
            return 1
        taken = take_in(store, folders, composed=logged_briefs())
    finally:
        store.close()
    report = {
        "new": taken.new,
        "in_use": dict(taken.in_use),
        "retired": taken.retired,
        "left_out": dict(taken.left_out),
    }
    if as_json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
        return 0
    in_use = ", ".join(f"{count} {domain}" for domain, count in taken.in_use.items())
    sys.stdout.write(
        f"stored {taken.new} new tasks from past coding work; in use: {in_use};"
        f" retired: {taken.retired}\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dodaios.rsi.bench.past_work")
    parser.add_argument("--repo", action="append", default=[], help="a local clone (repeatable)")
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    parser.add_argument(
        "--store", action="store_true", help="put the tasks into the benchmark's store"
    )
    args = parser.parse_args(argv)
    if args.store:
        return _store(args.repo or ["."], as_json=args.json)
    sessions = list(read_sessions())
    changes = read_changes(sessions, args.repo or ["."])
    report = summary(mine(sessions, changes, composed=logged_briefs()))
    sys.stdout.write((json.dumps(report, indent=2) if args.json else render(report)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
