#!/usr/bin/env python3
"""App-link Gauntlet: run the real Verse against the fake bridge, one scenario per parity row.

The GT rows of docs/verse/unreal/parity.md section 2, 15 and 16 are checked by running the game
(``-nullrhi``) against ``scripts/unreal/fake_bridge.py`` playing a scripted app: the scenario
sends lifecycle frames and ``expect`` steps bound every answer in time (``timeout_ms``). A case
passes when the bridge report is ``passed``, the game exits 0 (or is stopped after the scenario
finished), its log holds no fatal error, and every ``data_checks`` entry of the case holds.

    py -3 tests/unit/verse_host/gauntlet/gauntlet.py --list
    py -3 tests/unit/verse_host/gauntlet/gauntlet.py --rows A-01,A-05
    py -3 tests/unit/verse_host/gauntlet/gauntlet.py --exe C:/path/Verse.exe

Without ``--exe`` the Development editor runs the project with ``-game`` (the build that
``scripts/unreal/build.py editor`` makes). The run holds the machine lock (orchestration.md 4).
Results land in ``unreal/Verse/Saved/Gauntlet/<stamp>/`` as an Automation-style ``index.json``
with tests named ``Verse.Parity.<Letter>.<NN>``, so ``scripts/unreal/parity_report.py`` reads
them like any other result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.unreal import _common as common  # noqa: E402
from scripts.unreal import test as automation  # noqa: E402
from scripts.unreal import with_lock  # noqa: E402

HERE = Path(__file__).resolve().parent
CASES_FILE = HERE / "cases.json"
SCENARIOS_DIR = HERE / "scenarios"
FAKE_BRIDGE = REPO_ROOT / "scripts" / "unreal" / "fake_bridge.py"
TOKEN_ENV = "DODAIOS_VERSE_TOKEN"  # noqa: S105 - the variable name, not a secret
DISCOVERY_ENV = "DODAIOS_VERSE_DISCOVERY"
ROW_RE = re.compile(r"^([A-Z]{1,2})-(\d{2})$")


@dataclass(frozen=True)
class Case:
    row: str
    scenario: str
    timeout_s: int = 240
    game_args: tuple[str, ...] = ()
    data_checks: tuple[dict, ...] = ()
    note: str = ""

    @property
    def test_name(self) -> str:
        letter, number = self.row.split("-")
        return f"Verse.Parity.{letter}.{number}"


@dataclass
class CaseResult:
    case: Case
    passed: bool = False
    problems: list[str] = field(default_factory=list)
    report: dict = field(default_factory=dict)
    log_path: Path | None = None


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    cases = []
    for raw in json.loads(path.read_text(encoding="utf-8")):
        if not ROW_RE.match(raw["row"]):
            raise ValueError(f"bad row id {raw['row']!r}")
        cases.append(
            Case(
                row=raw["row"],
                scenario=raw["scenario"],
                timeout_s=raw.get("timeout_s", 240),
                game_args=tuple(raw.get("game_args", ())),
                data_checks=tuple(raw.get("data_checks", ())),
                note=raw.get("note", ""),
            )
        )
    return cases


def game_command(
    case: Case, *, exe: Path | None, project: Path, engine: Path, log_path: Path
) -> list[str]:
    """The command line of one run: a packaged Verse.exe, or the editor build with -game."""
    common_args = [
        "-nullrhi",
        "-nosound",
        "-nosplash",
        "-unattended",
        "-NoP4",
        "-windowed",
        "-ResX=1280",
        "-ResY=720",
        "-log",
        f"-abslog={log_path}",
        *case.game_args,
    ]
    if exe is not None:
        return [str(exe), *common_args]
    editor = engine / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    return [str(editor), str(project), "-game", *common_args]


def count_matching(items: Sequence[object], match: dict) -> int:
    """How many data objects hold every key/value of ``match``."""
    return sum(
        1
        for item in items
        if isinstance(item, dict) and all(item.get(k) == v for k, v in match.items())
    )


def check_data(case: Case, report: dict) -> list[str]:
    """Evaluate ``data_checks``: ``{"type", "match", "eq" | "min" | "max"}`` on received frames."""
    problems = []
    received = report.get("received_data", {})
    for check in case.data_checks:
        items = received.get(check["type"], [])
        n = count_matching(items, check.get("match", {}))
        label = f"{check['type']} {check.get('match', {})}"
        if "eq" in check and n != check["eq"]:
            problems.append(f"{label}: expected {check['eq']} frames, got {n}")
        if "min" in check and n < check["min"]:
            problems.append(f"{label}: expected at least {check['min']} frames, got {n}")
        if "max" in check and n > check["max"]:
            problems.append(f"{label}: expected at most {check['max']} frames, got {n}")
    return problems


def evaluate(case: Case, report: dict, game_code: int | None, log_hits: list[str]) -> list[str]:
    problems = []
    if not report:
        return ["the fake bridge wrote no report (the game never connected or the bridge died)"]
    if not report.get("done"):
        problems.append("the scenario did not run to its end")
    for exp in report.get("expectations", []):
        if not exp["ok"] and not exp["optional"]:
            problems.append(f"no {exp['type']} {exp['data']} in time")
    for key in ("skipped", "invalid_from_verse"):
        problems += [f"{key}: {item}" for item in report.get(key, [])]
    if report.get("hung"):
        problems.append("Verse went silent for 5 s")
    if game_code not in (0, None):
        problems.append(f"the game exited with {game_code}")
    problems += check_data(case, report)
    problems += [f"log: {line}" for line in log_hits]
    return problems


def run_case(
    case: Case,
    *,
    exe: Path | None,
    worktree: Path,
    out_dir: Path,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> CaseResult:
    """Run one case; the caller holds the machine lock."""
    result = CaseResult(case)
    scenario = SCENARIOS_DIR / case.scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = case.row.replace("-", "")
    result.log_path = out_dir / f"{stem}.log"
    report_path = out_dir / f"{stem}.report.json"
    discovery = out_dir / f"{stem}.bridge.json"
    report_path.unlink(missing_ok=True)
    token = secrets.token_hex(16)
    bridge = popen(
        [
            sys.executable,
            str(FAKE_BRIDGE),
            "--token",
            token,
            "--scenario",
            str(scenario),
            "--once",
            "--report",
            str(report_path),
            "--discovery",
            str(discovery),
        ],
        cwd=str(worktree),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    game = None
    game_code: int | None = None
    try:
        deadline = time.monotonic() + 30
        while not discovery.is_file() and time.monotonic() < deadline and bridge.poll() is None:
            time.sleep(0.1)
        if not discovery.is_file():
            result.problems.append("the fake bridge never published its discovery file")
            return result
        command = game_command(
            case,
            exe=exe,
            project=common.project_file(worktree),
            engine=common.engine_root(),
            log_path=result.log_path,
        )
        env = dict(os.environ, **{TOKEN_ENV: token, DISCOVERY_ENV: str(discovery)})
        common.log(f"gauntlet {case.row}: {' '.join(command)}")
        game = popen(command, cwd=str(worktree), env=env)
        try:
            bridge.wait(timeout=case.timeout_s)
        except subprocess.TimeoutExpired:
            result.problems.append(f"the scenario did not finish in {case.timeout_s} s")
        try:
            game.wait(timeout=30)
            game_code = game.returncode
        except subprocess.TimeoutExpired:
            result.problems.append("the game did not exit after lifecycle.quit")
    finally:
        for proc in (game, bridge):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
    try:
        result.report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result.report = {}
    result.problems += evaluate(
        case, result.report, game_code, automation.scan_log(result.log_path)
    )
    result.passed = not result.problems
    return result


def write_index(results: Sequence[CaseResult], out_dir: Path) -> Path:
    """An Automation-style index.json that parity_report.py reads."""
    tests = [
        {
            "fullTestPath": r.case.test_name,
            "testDisplayName": r.case.test_name,
            "state": "Success" if r.passed else "Fail",
            "problems": r.problems,
        }
        for r in results
    ]
    path = out_dir / "index.json"
    path.write_text(json.dumps({"tests": tests}, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", help="comma separated row ids; default every case")
    parser.add_argument("--exe", type=Path, help="a packaged Verse.exe; default the editor -game")
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    parser.add_argument("--list", action="store_true")
    options = parser.parse_args(argv)
    cases = load_cases()
    if options.rows:
        wanted = {r.strip() for r in options.rows.split(",")}
        cases = [c for c in cases if c.row in wanted]
    if options.list:
        for c in cases:
            print(f"{c.row}\t{c.scenario}\t{c.note}")
        return 0
    if not cases:
        common.log("no case selected")
        return 1
    worktree = options.worktree.resolve()
    out_dir = worktree / "unreal" / "Verse" / "Saved" / "Gauntlet" / common.run_stamp()
    results = []
    with with_lock.MachineLock(f"gauntlet ({worktree.name})", "gauntlet.py"):
        for case in cases:
            results.append(run_case(case, exe=options.exe, worktree=worktree, out_dir=out_dir))
            r = results[-1]
            common.log(f"gauntlet {case.row}: {'PASS' if r.passed else 'FAIL'}")
            for problem in r.problems:
                common.log(f"  {problem}")
    write_index(results, out_dir)
    common.log(f"results: {out_dir}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
