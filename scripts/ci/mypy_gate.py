#!/usr/bin/env python3
"""The mypy gate: blocking packages stay clean, every other package may only shrink.

``python -m mypy dodaios/`` (configuration in ``pyproject.toml``, ``[tool.mypy]``)
runs once and its errors are grouped by package:

* A package in ``BLOCKING`` must report zero errors. One error fails the gate.
* Every other package is a backlog. ``mypy-baseline.json`` holds its error count.
  The gate fails when a package gets more errors than its baseline, or when a
  package that the baseline does not list gets any error. A count that shrank
  is only a note: run ``--update`` and commit the tighter baseline.

A package is the first folder below ``dodaios/`` (``dodaios.core``); modules that
sit directly in ``dodaios/`` count as ``dodaios``. Folders next to ``dodaios/``
that mypy follows into (``ui``, ``conductor``) are keyed by their own name.

Usage::

    python scripts/ci/mypy_gate.py            # run mypy and check
    python scripts/ci/mypy_gate.py --update   # rewrite the baseline (may only shrink)
    python scripts/ci/mypy_gate.py --table    # print the per-package table
    python scripts/ci/mypy_gate.py --from-file out.txt   # use a saved mypy output
    python scripts/ci/mypy_gate.py --base <sha>          # judge only touched packages
    python scripts/ci/mypy_gate.py --all                 # judge every package

With a diff base (``--base`` or ``$RATCHET_BASE``) only the packages that contain a
file changed since the base (``git diff --name-only <base> HEAD``) are judged: main
moves while a pull request waits in the merge queue, so a whole-repo comparison is
stale by merge time. A change to the mypy setup itself (``pyproject.toml``, this
script, the baseline, ``uv.lock``) judges every package. Without a base, or with
``--all``, every package is judged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent / "mypy-baseline.json"

# Packages that report no mypy error today. Add a package here once it is clean
# (a package missing from both this list and the baseline is held to zero too).
BLOCKING: tuple[str, ...] = (
    "dodaios",
    "dodaios._legacy_alias",
    "dodaios.agents",
    "dodaios.app_actions",
    "dodaios.artifacts",
    "dodaios.assets",
    "dodaios.audio",
    "dodaios.autostart",
    "dodaios.board",
    "dodaios.briefs",
    "dodaios.browser_voice",
    "dodaios.channels",
    "dodaios.cli",
    "dodaios.cli_ctl",
    "dodaios.clis",
    "dodaios.commands",
    "dodaios.computers",
    "dodaios.contacts",
    "dodaios.control",
    "dodaios.core",
    "dodaios.costs",
    "dodaios.credential_broker",
    "dodaios.diagnostics",
    "dodaios.dictation",
    "dodaios.docs",
    "dodaios.documents",
    "dodaios.dodaiosx",
    "dodaios.evals",
    "dodaios.friends",
    "dodaios.google_cli",
    "dodaios.hardware",
    "dodaios.harness",
    "dodaios.i18n",
    "dodaios.lead_triggers",
    "dodaios.learners",
    "dodaios.life_admin",
    "dodaios.local_models",
    "dodaios.memory",
    "dodaios.mobile",
    "dodaios.overlay",
    "dodaios.platform",
    "dodaios.pointer",
    "dodaios.preview",
    "dodaios.projects",
    "dodaios.rituals",
    "dodaios.rsi",
    "dodaios.runs",
    "dodaios.safety",
    "dodaios.screen_context",
    "dodaios.self_build",
    "dodaios.self_change",
    "dodaios.sessions",
    "dodaios.setup",
    "dodaios.standing_tasks",
    "dodaios.state",
    "dodaios.tasks",
    "dodaios.telemetry",
    "dodaios.telephony",
    "dodaios.terminal",
    "dodaios.tools",
    "dodaios.trigger",
    "dodaios.trust",
    "dodaios.vision",
    "dodaios.visuals",
    "dodaios.voice",
    "dodaios.workflows",
    "dodaios.workspace",
)

_ERROR = re.compile(r"^(?P<path>[^\s:][^:]*\.pyi?):\d+(?::\d+)?: error: ")


def package_of(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    if parts[0] == "dodaios":
        return f"dodaios.{parts[1]}" if len(parts) > 2 else "dodaios"
    return parts[0]


def count_errors(output: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in output.splitlines():
        match = _ERROR.match(line)
        if match:
            counts[package_of(match.group("path"))] += 1
    return counts


_FULL_CHECK_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "scripts/ci/mypy_gate.py",
        "scripts/ci/mypy-baseline.json",
    }
)


def touched_packages(base: str) -> set[str] | None:
    """Packages with a changed file since ``base``; ``None`` means judge everything."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", base, "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"note: git diff against {base!r} failed; judging every package.")
        return None
    packages: set[str] = set()
    for name in proc.stdout.split():
        if name in _FULL_CHECK_FILES:
            return None
        if name.endswith((".py", ".pyi")):
            packages.add(package_of(name))
    return packages


def judge(
    counts: Counter[str],
    baseline: dict[str, int],
    touched: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(failures, notes)``; ``touched`` limits the judgement to those packages."""
    failures: list[str] = []
    notes: list[str] = []
    for package in BLOCKING:
        if touched is not None and package not in touched:
            continue
        if counts.get(package):
            failures.append(
                f"{package} is a blocking package and reports {counts[package]} mypy error(s)."
            )
    for package, number in sorted(counts.items()):
        if package in BLOCKING or (touched is not None and package not in touched):
            continue
        allowed = baseline.get(package, 0)
        if number > allowed:
            failures.append(f"{package}: {number} mypy errors, baseline allows {allowed}.")
    for package, allowed in sorted(baseline.items()):
        if counts.get(package, 0) < allowed:
            notes.append(f"{package}: {counts.get(package, 0)} (baseline {allowed}).")
    return failures, notes


def run_mypy() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "dodaios/", "--no-error-summary", "--show-error-codes"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"mypy crashed (exit {proc.returncode}).")
    return proc.stdout


def load_baseline() -> dict[str, int]:
    if not BASELINE.exists():
        return {}
    return {k: int(v) for k, v in json.loads(BASELINE.read_text(encoding="utf-8")).items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    parser.add_argument("--table", action="store_true", help="print the per-package table")
    parser.add_argument("--from-file", help="read saved mypy output instead of running mypy")
    parser.add_argument("--all", action="store_true", help="judge every package")
    parser.add_argument(
        "--base",
        default=os.environ.get("RATCHET_BASE", ""),
        help="diff base: judge only packages with a file changed since it "
        "(default: $RATCHET_BASE; without one every package is judged)",
    )
    args = parser.parse_args()

    output = Path(args.from_file).read_text(encoding="utf-8") if args.from_file else run_mypy()
    counts = count_errors(output)
    baseline = load_baseline()

    if args.table:
        for package, number in sorted(counts.items(), key=lambda item: (item[1], item[0])):
            print(f"{number:5d}  {package}")
        print(f"{sum(counts.values()):5d}  total")
        return 0

    touched = None if (args.all or args.update or not args.base) else touched_packages(args.base)
    failures, notes = judge(counts, baseline, touched)

    if args.update:
        fresh = {p: n for p, n in counts.items() if p not in BLOCKING}
        grown = [p for p, n in fresh.items() if n > baseline.get(p, 0)] if baseline else []
        if grown:
            print("Refusing to raise the baseline for: " + ", ".join(sorted(grown)))
            return 1
        BASELINE.write_text(
            json.dumps(dict(sorted(fresh.items())), indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {BASELINE.relative_to(REPO)} ({sum(fresh.values())} errors).")
        return 0

    for note in notes:
        print(f"note: {note} Run --update to tighten the baseline.")
    if failures:
        print("mypy gate failed:")
        for failure in failures:
            print(f"  {failure}")
        print("Fix the errors (see `python -m mypy dodaios/`); the baseline may only shrink.")
        return 1
    scope = "every package" if touched is None else f"{len(touched)} touched package(s)"
    print(
        f"mypy gate ok ({scope} judged): {len(BLOCKING)} blocking packages clean, "
        f"{sum(counts.values())} backlog errors within the baseline."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
