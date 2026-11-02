#!/usr/bin/env python3
"""Run Unreal automation tests headless (``-nullrhi``) under the machine lock.

The only automation entry for agents (docs/verse/unreal/orchestration.md 5.2).

    python scripts/unreal/test.py "Verse.Combat+Verse.Contract"
    python scripts/unreal/test.py "Verse.Core+Verse.Contract" --jobs 2

A run passes only when every editor process exits 0, its ``index.json``
reports zero failed and zero not-run tests, every part of the filter matched
at least one test, and no log holds a fatal error, an ensure or a crash.
``--jobs`` (at most 4) splits the filter parts over several headless editors
inside one lock hold. Reports land in ``unreal/Verse/Saved/Automation/``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import with_lock

#: Log lines that fail a run whatever the report says.
LOG_FAILURES = (
    re.compile(r"Fatal error"),
    re.compile(r"=== Critical error: ==="),
    re.compile(r"Ensure condition failed"),
    re.compile(r"Unhandled Exception"),
    re.compile(r"appError called"),
)
PASS_STATES = {"Success", "SuccessWithWarnings"}
PROCESS_TIMEOUT_S = 60 * 60


@dataclass
class RunResult:
    filter: str
    returncode: int
    report_dir: Path
    log_path: Path
    passed: int = 0
    failed: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    log_hits: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.problems or self.failed or self.not_run or self.unmatched or self.log_hits)


def split_filter(text: str) -> list[str]:
    parts = [p.strip() for p in text.split("+")]
    parts = [p for p in parts if p]
    if not parts:
        raise common.UnrealScriptError("empty test filter")
    for part in parts:
        if not re.fullmatch(r"[A-Za-z0-9_.]+", part):
            raise common.UnrealScriptError(f"bad filter part {part!r}")
    return parts


def shard(parts: Sequence[str], jobs: int) -> list[list[str]]:
    jobs = max(1, min(jobs, common.MAX_HEADLESS_JOBS, len(parts)))
    groups: list[list[str]] = [[] for _ in range(jobs)]
    for index, part in enumerate(parts):
        groups[index % jobs].append(part)
    return groups


def command_for(engine: Path, project: Path, test_filter: str, report_dir: Path, log_path: Path,
                extra: Sequence[str] = ()) -> list[str]:
    return [
        str(common.editor_cmd(engine)),
        str(project),
        f"-ExecCmds=Automation RunTests {test_filter}; Quit",
        "-TestExit=Automation Test Queue Empty",
        "-unattended",
        "-nullrhi",
        "-nosound",
        "-nosplash",
        "-NoP4",
        "-stdout",
        "-FullStdOutLogOutput",
        f"-ReportExportPath={report_dir}",
        f"-abslog={log_path}",
        *extra,
    ]


def read_report(report_dir: Path) -> dict | None:
    index = report_dir / "index.json"
    try:
        return json.loads(index.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def scan_log(log_path: Path) -> list[str]:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if any(p.search(line) for p in LOG_FAILURES)][:20]


def evaluate(result: RunResult, parts: Sequence[str]) -> RunResult:
    if result.returncode != 0:
        result.problems.append(f"editor exited with {result.returncode}")
    report = read_report(result.report_dir)
    if report is None:
        result.problems.append(f"no readable index.json in {result.report_dir}")
        tests: list[dict] = []
    else:
        tests = list(report.get("tests") or [])
    for test in tests:
        name = test.get("fullTestPath") or test.get("testDisplayName") or "?"
        state = test.get("state", "")
        if state in PASS_STATES:
            result.passed += 1
        elif state in ("NotRun", "Skipped", "InProcess", ""):
            result.not_run.append(name)
        else:
            result.failed.append(name)
    if report is not None:
        paths = [str(t.get("fullTestPath", "")) for t in tests]
        # RunTests matches by name prefix, so a part matched when some test starts with it.
        result.unmatched = [p for p in parts if not any(x.startswith(p) for x in paths)]
    result.log_hits = scan_log(result.log_path)
    return result


def run_tests(
    test_filter: str,
    *,
    jobs: int = 1,
    worktree: Path = common.REPO_ROOT,
    rendered: bool = False,
    extra: Sequence[str] = (),
    runner: Callable[..., common.Completed] = common.run,
    lock_factory: Callable[..., with_lock.MachineLock] = with_lock.MachineLock,
    stamp: str | None = None,
    report_base: Path | None = None,
) -> list[RunResult]:
    parts = split_filter(test_filter)
    engine = common.engine_root()
    project = common.project_file(worktree)
    if not common.editor_cmd(engine).is_file():
        raise common.UnrealScriptError(f"no UnrealEditor-Cmd.exe under {engine} (run doctor.py)")
    if not project.is_file():
        raise common.UnrealScriptError(f"no project at {project}")
    groups = shard(parts, 1 if rendered else jobs)
    stamp = stamp or common.run_stamp()
    base = report_base or worktree / "unreal" / "Verse" / "Saved" / "Automation"
    planned: list[tuple[RunResult, list[str], list[str]]] = []
    for index, group in enumerate(groups):
        joined = "+".join(group)
        report_dir = base / f"{stamp}-{index}"
        report_dir.mkdir(parents=True, exist_ok=True)
        log_path = report_dir / "run.log"
        command = command_for(engine, project, joined, report_dir, log_path, extra)
        if rendered:
            command.remove("-nullrhi")
        planned.append((RunResult(joined, -1, report_dir, log_path), group, command))

    def launch(item: tuple[RunResult, list[str], list[str]]) -> RunResult:
        result, group, command = item
        common.log(f"test {result.filter}: {' '.join(command)}")
        completed = runner(command, cwd=worktree, timeout=PROCESS_TIMEOUT_S)
        result.returncode = completed.returncode
        return evaluate(result, group)

    label = f"test {test_filter} ({worktree.name})"
    with lock_factory(label, test_filter):
        with ThreadPoolExecutor(max_workers=len(planned)) as pool:
            return list(pool.map(launch, planned))


def summarize(results: Sequence[RunResult]) -> int:
    ok = all(r.ok for r in results)
    for r in results:
        common.log(
            f"{r.filter}: {r.passed} passed, {len(r.failed)} failed, {len(r.not_run)} not run"
            f"  report: {r.report_dir}"
        )
        for name in r.failed:
            common.log(f"  FAILED   {name}")
        for name in r.not_run:
            common.log(f"  NOT RUN  {name}")
        for part in r.unmatched:
            common.log(f"  NO MATCH {part} (the filter matched no test)")
        for line in r.log_hits:
            common.log(f"  LOG      {line}")
        for problem in r.problems:
            common.log(f"  PROBLEM  {problem}")
    total = sum(r.passed for r in results)
    common.log(f"{'PASS' if ok else 'FAIL'}: {total} passed")
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("filter", help='test filter, parts joined with "+"')
    parser.add_argument("--jobs", type=int, default=1,
                        help=f"headless editors in parallel (max {common.MAX_HEADLESS_JOBS})")
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    options = parser.parse_args(argv)
    if not 1 <= options.jobs <= common.MAX_HEADLESS_JOBS:
        parser.error(f"--jobs must be 1..{common.MAX_HEADLESS_JOBS}")
    try:
        results = run_tests(options.filter, jobs=options.jobs, worktree=options.worktree.resolve())
    except common.UnrealScriptError as error:
        return common.exit_with(error)
    return summarize(results)


if __name__ == "__main__":
    sys.exit(main())
