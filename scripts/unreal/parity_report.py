#!/usr/bin/env python3
"""Run the ``Verse.Parity.*`` tests and write the parity report, one line per row.

The finish line of docs/verse/unreal/parity.md section 1: the deletion pull
request (section 21) is allowed only when this prints ``N/N green``.

    python scripts/unreal/parity_report.py                 # run Verse.Parity, then report
    python scripts/unreal/parity_report.py --no-run        # newest Saved/Automation run
    python scripts/unreal/parity_report.py --index DIR     # one index.json folder (repeatable)
    python scripts/unreal/parity_report.py --junit FILE    # pytest results (BT, ST rows)
    python scripts/unreal/parity_report.py --list-rows     # print the rows and exit

Matching is by id: the test ``Verse.Parity.D.07`` (or ``Verse.Parity.Duel.D07``,
``Verse.Parity.D_07.Case2``) belongs to row ``D-07``. A pytest case belongs to a
row when its name carries the row id after ``parity`` (``test_parity_d_07_...``).
A row is

* ``green``   when at least one test matched and every matched test passed,
* ``red``     when any matched test failed or did not run,
* ``missing`` when no test matched; the report lists it, it is never skipped.

Output: ``report.json`` and ``report.md`` next to each other (default
``unreal/Verse/Saved/Parity``). Exit code 0 only when every row is green.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common

PARITY_FILE = common.REPO_ROOT / "docs" / "verse" / "unreal" / "parity.md"
DEFAULT_OUT = common.PROJECT_DIR / "Saved" / "Parity"
FILTER = "Verse.Parity"
PASS_STATES = {"Success", "SuccessWithWarnings"}
KINDS = ("AT", "GT", "BT", "VT", "SS", "ST")

SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.*)$")
ROW_RE = re.compile(r"^\|\s*([A-Z]{1,2})-(\d{2})\s*\|(.*)\|\s*$")
# Test names: Verse.Parity.<anything>.<Letter>[._-]?<two digits>[.<case>]
UNREAL_ID_RE = re.compile(r"(?:^|\.)([A-Z]{1,2})[._-]?(\d{2})(?=$|[._])")
PYTEST_ID_RE = re.compile(r"parity[_.\-]([a-z]{1,2})[_.\-]?(\d{2})(?=$|[_.\-])", re.IGNORECASE)


@dataclass(frozen=True)
class Row:
    id: str
    section: int
    feature: str
    kinds: tuple[str, ...]


@dataclass
class Outcome:
    name: str
    passed: bool
    source: str


@dataclass
class RowStatus:
    row: Row
    status: str = "missing"
    tests: list[Outcome] = field(default_factory=list)


def parse_rows(text: str) -> list[Row]:
    """Rows of sections 2-19 (the tables of the checklist), in file order."""
    rows: list[Row] = []
    section = 0
    for line in text.splitlines():
        heading = SECTION_RE.match(line)
        if heading:
            section = int(heading.group(1))
            continue
        if not 2 <= section <= 19:
            continue
        match = ROW_RE.match(line)
        if not match:
            continue
        cells = [c.strip() for c in match.group(3).split("|")]
        check = cells[-1] if cells else ""
        kinds = tuple(k for k in KINDS if re.search(rf"`{k}`", check))
        rows.append(
            Row(f"{match.group(1)}-{match.group(2)}", section, cells[0] if cells else "", kinds)
        )
    return rows


def unreal_row_id(full_test_path: str) -> str | None:
    """``Verse.Parity.D.07`` -> ``D-07``; None for names outside Verse.Parity."""
    prefix = FILTER + "."
    if not full_test_path.startswith(prefix):
        return None
    match = UNREAL_ID_RE.search(full_test_path[len(prefix) - 1 :])
    return f"{match.group(1)}-{match.group(2)}" if match else None


def pytest_row_id(name: str) -> str | None:
    match = PYTEST_ID_RE.search(name)
    return f"{match.group(1).upper()}-{match.group(2)}" if match else None


def read_index(directory: Path) -> list[Outcome]:
    try:
        report = json.loads((directory / "index.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    outcomes = []
    for test in report.get("tests") or []:
        name = str(test.get("fullTestPath") or test.get("testDisplayName") or "")
        outcomes.append(Outcome(name, test.get("state", "") in PASS_STATES, str(directory)))
    return outcomes


def read_junit(path: Path) -> list[Outcome]:
    try:
        root = ET.parse(path).getroot()  # noqa: S314 - our own pytest output
    except (OSError, ET.ParseError):
        return []
    outcomes = []
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '')}.{case.get('name', '')}"
        bad = any(case.find(tag) is not None for tag in ("failure", "error"))
        skipped = case.find("skipped") is not None
        outcomes.append(Outcome(name, not bad and not skipped, str(path)))
    return outcomes


def newest_index_dir(base: Path) -> Path | None:
    candidates = [p.parent for p in base.glob("*/index.json")] if base.is_dir() else []
    return max(candidates, key=lambda p: (p / "index.json").stat().st_mtime, default=None)


def build_report(
    rows: Sequence[Row], unreal: Iterable[Outcome], pytests: Iterable[Outcome]
) -> list[RowStatus]:
    by_id = {row.id: RowStatus(row) for row in rows}
    for outcome in unreal:
        row_id = unreal_row_id(outcome.name)
        if row_id in by_id:
            by_id[row_id].tests.append(outcome)
    for outcome in pytests:
        row_id = pytest_row_id(outcome.name)
        if row_id in by_id:
            by_id[row_id].tests.append(outcome)
    for entry in by_id.values():
        if entry.tests:
            entry.status = "green" if all(t.passed for t in entry.tests) else "red"
    return list(by_id.values())


def summary_line(statuses: Sequence[RowStatus]) -> str:
    green = sum(1 for s in statuses if s.status == "green")
    return f"{green}/{len(statuses)} green"


def to_json(statuses: Sequence[RowStatus], when: datetime | None = None) -> dict:
    counts = {k: sum(1 for s in statuses if s.status == k) for k in ("green", "red", "missing")}
    return {
        "generated": (when or datetime.now(UTC)).isoformat(timespec="seconds"),
        "summary": summary_line(statuses),
        "total": len(statuses),
        **counts,
        "rows": [
            {
                "id": s.row.id,
                "section": s.row.section,
                "feature": s.row.feature,
                "kinds": list(s.row.kinds),
                "status": s.status,
                "tests": [{"name": t.name, "passed": t.passed} for t in s.tests],
            }
            for s in statuses
        ],
    }


def to_markdown(statuses: Sequence[RowStatus]) -> str:
    lines = [f"# Verse parity report: {summary_line(statuses)}", ""]
    for key in ("red", "missing"):
        group = [s for s in statuses if s.status == key]
        lines.append(f"## {key.capitalize()} ({len(group)})")
        lines.append("")
        lines.extend(
            f"- {s.row.id} [{'/'.join(s.row.kinds) or '-'}] {s.row.feature}" for s in group
        )
        lines.append("")
    lines.append("## All rows")
    lines.append("")
    lines.append("| Row | Status | Kinds | Tests |")
    lines.append("|---|---|---|---|")
    for s in statuses:
        lines.append(
            f"| {s.row.id} | {s.status} | {' '.join(s.row.kinds) or '-'} | {len(s.tests)} |"
        )
    return "\n".join(lines) + "\n"


def write_report(statuses: Sequence[RowStatus], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    json_path.write_text(json.dumps(to_json(statuses), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(statuses), encoding="utf-8")
    return json_path, md_path


def run_parity_tests(worktree: Path, runner: Callable | None = None) -> list[Outcome]:
    """Run ``Verse.Parity`` through scripts/unreal/test.py (machine lock, nullrhi)."""
    from scripts.unreal import test as automation

    results = automation.run_tests(
        FILTER, worktree=worktree, **({"runner": runner} if runner else {})
    )
    outcomes: list[Outcome] = []
    for result in results:
        outcomes.extend(read_index(result.report_dir))
    return outcomes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-run", action="store_true", help="do not run Unreal; read the newest saved run"
    )
    parser.add_argument(
        "--index", type=Path, action="append", default=[], help="an Automation report folder"
    )
    parser.add_argument(
        "--junit", type=Path, action="append", default=[], help="a pytest junit xml file"
    )
    parser.add_argument("--parity-file", type=Path, default=PARITY_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    parser.add_argument("--list-rows", action="store_true")
    options = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")

    rows = parse_rows(options.parity_file.read_text(encoding="utf-8"))
    if options.list_rows:
        for row in rows:
            print(f"{row.id}\t{'/'.join(row.kinds)}\t{row.feature}")
        return 0

    unreal: list[Outcome] = []
    try:
        if options.index:
            for directory in options.index:
                unreal.extend(read_index(directory))
        elif options.no_run:
            newest = newest_index_dir(
                options.worktree / "unreal" / "Verse" / "Saved" / "Automation"
            )
            if newest:
                unreal.extend(read_index(newest))
        else:
            unreal.extend(run_parity_tests(options.worktree.resolve()))
        if not options.index:
            # The newest app-link Gauntlet run (tests/unit/verse_host/gauntlet) reports GT rows.
            saved = options.worktree / "unreal" / "Verse" / "Saved"
            gauntlet = newest_index_dir(saved / "Gauntlet")
            if gauntlet:
                unreal.extend(read_index(gauntlet))
    except common.UnrealScriptError as error:
        return common.exit_with(error)
    pytests = [o for path in options.junit for o in read_junit(path)]

    statuses = build_report(rows, unreal, pytests)
    json_path, md_path = write_report(statuses, options.out)
    for s in statuses:
        if s.status != "green":
            common.log(f"{s.status.upper():8} {s.row.id}  {s.row.feature}")
    common.log(f"report: {json_path} and {md_path}")
    print(summary_line(statuses))
    return 0 if all(s.status == "green" for s in statuses) else 1


if __name__ == "__main__":
    sys.exit(main())
