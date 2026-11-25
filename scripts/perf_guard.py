#!/usr/bin/env python
"""One command that runs every performance, latency and budget guard.

Refactors of the biggest functions and files must keep this green. It prints a
short pass/fail table, writes a log with the full output of every guard and a
JSON file with the timings, and can record a baseline to compare against.

    python scripts/perf_guard.py --fast            # unit-level guards, no app boot (target < 5 min)
    python scripts/perf_guard.py                   # everything that can run headless
    python scripts/perf_guard.py --only dictation  # guards whose name contains the word
    python scripts/perf_guard.py --save-baseline   # remember this run's timings
    python scripts/perf_guard.py --list            # show the guards and their tier
    python scripts/perf_guard.py --real-dictation  # also run the on-device dictation replay

Where things go (``logs/`` is git-ignored, so timings stay machine-local):

* ``logs/perf_guard/last.log``    full output of every guard
* ``logs/perf_guard/last.json``   per-guard status and seconds, per-test seconds
* ``logs/perf_guard/baseline.json``  written by ``--save-baseline``; later runs
  print each guard's change against it (a guard more than 50 percent and 2 s
  slower than its baseline is flagged SLOW, it does not fail the run).

Status: PASS, FAIL, SKIP (the guard could not measure here: no build, no audio
device, no node_modules; exit code 78 or every test skipped). The exit code is
1 when any guard FAILs, otherwise 0.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET  # noqa: S405 - our own pytest output

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "logs" / "perf_guard"
DIST_INDEX = REPO / "dodaios" / "ui" / "web" / "dist" / "index.html"
FRONTEND = REPO / "dodaios" / "ui" / "web" / "frontend"
SKIP_EXIT = 78
SLOW_FACTOR = 1.5
SLOW_MIN_DELTA_S = 2.0

# Guards that are plain pytest files. "fast" ones are unit-level and need no
# app boot; "full" ones spawn processes or cold-boot the app.
PYTEST_FAST = [
    "tests/unit/core/test_socket_budget_watchdog.py",
    "tests/unit/agent_chat/test_service_startup_responsive.py",
    "tests/unit/agent_chat/test_speed.py",
    "tests/unit/society/test_conversation_responsiveness.py",
    "tests/unit/society/test_review_responsiveness.py",
    "tests/unit/realtime/test_non_blocking_heavy_turns.py",
    "tests/unit/realtime/test_live_startup_latency.py",
    "tests/unit/realtime/test_session_response_latency.py",
    "tests/unit/realtime/test_subscription_startup_latency.py",
    "tests/unit/realtime/test_factory_handshake_budget.py",
    "tests/unit/dictation/test_delivery_latency.py",
    "tests/unit/speech/test_voice_chunk_latency_budget.py",
    "tests/unit/speech/test_wake_latency.py",
    "tests/unit/speech/test_warmup_timings.py",
    "tests/unit/runs/test_list_performance.py",
]
PYTEST_FULL = [
    "tests/contract/test_socket_budget.py",
    "tests/integration/test_boot_budget.py",
    "tests/integration/test_tier1_speed.py",
]

# The cold-boot test measures the window anchor, which needs the built frontend.
PYTEST_NEEDS = {"tests/integration/test_boot_budget.py": (DIST_INDEX,)}


@dataclass
class Guard:
    name: str
    tier: str  # "fast" | "full"
    argv: list[str] = field(default_factory=list)
    cwd: Path = REPO
    timeout_s: int = 900
    # Set for guards that are one pytest file inside a shared pytest process.
    pytest_file: str | None = None
    # Files that must exist for the guard to be able to measure anything.
    needs: tuple[Path, ...] = ()


@dataclass
class Result:
    name: str
    status: str  # PASS | FAIL | SKIP
    seconds: float
    detail: str = ""
    tests: dict[str, float] = field(default_factory=dict)


def _name(path: str) -> str:
    stem = Path(path).stem.removeprefix("test_")
    return "agent_chat_speed" if stem == "speed" else stem


def _guards(real_dictation: bool) -> list[Guard]:
    py = sys.executable
    guards = [Guard(_name(f), "fast", pytest_file=f) for f in PYTEST_FAST]
    guards += [
        Guard(_name(f), "full", pytest_file=f, needs=PYTEST_NEEDS.get(f, ())) for f in PYTEST_FULL
    ]
    guards += [
        Guard(
            "dictation_replay_sim",
            "fast",
            [
                py,
                "scripts/bench/dictation_replay.py",
                "--json",
                str(OUT_DIR / "dictation_sim.json"),
            ],
            timeout_s=300,
        ),
        Guard(
            "boot_budget_cold",
            "full",
            [py, "scripts/ci/check_boot_budget.py"],
            timeout_s=900,
            needs=(DIST_INDEX,),
        ),
        Guard(
            "frontend_bundle_budget",
            "full",
            [py, "scripts/ci/check_frontend_bundle_budget.py"],
            timeout_s=120,
        ),
        Guard(
            "frontend_vitest_budgets",
            "full",
            [
                "npx",
                "--no-install",
                "vitest",
                "run",
                "src/lib/connectBudget.test.ts",
                "src/lib/pcm-worklet.startup.test.ts",
            ],
            cwd=FRONTEND,
            timeout_s=300,
        ),
    ]
    if real_dictation:
        guards.append(
            Guard(
                "dictation_replay_real",
                "full",
                [
                    py,
                    "scripts/bench/dictation_replay.py",
                    "--engine",
                    "real",
                    "--json",
                    str(OUT_DIR / "dictation_real.json"),
                ],
                timeout_s=900,
            )
        )
    return guards


def _run(argv: list[str], cwd: Path, timeout_s: int, log) -> tuple[int, float]:
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONIOENCODING="utf-8")
    started = time.perf_counter()
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            shell=(os.name == "nt" and argv[0] == "npx"),
        )
        code, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        code, out = 1, f"TIMEOUT after {timeout_s}s"
    except FileNotFoundError as exc:
        code, out = SKIP_EXIT, f"not runnable here: {exc}"
    seconds = time.perf_counter() - started
    log.write(f"\n{'=' * 78}\n$ {' '.join(argv)}\n(exit {code}, {seconds:.1f}s)\n{out}\n")
    return code, seconds


def _tail(text: str, lines: int = 3) -> str:
    kept = [ln for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(kept[-lines:])[:200]


def _run_pytest_group(guards: list[Guard], log) -> list[Result]:
    """One pytest process for many files; per-file rows come from the JUnit XML."""
    if not guards:
        return []
    # A listed guard whose file is gone is a failure of its own, never a silent pass.
    missing = [g for g in guards if not (REPO / str(g.pytest_file)).exists()]
    missing_results = [
        Result(g.name, "FAIL", 0.0, f"guard file is missing: {g.pytest_file}") for g in missing
    ]
    for r in missing_results:
        log.write(f"\n[{r.name}] {r.detail}\n")
    guards = [g for g in guards if g not in missing]
    if not guards:
        return missing_results
    xml_path = OUT_DIR / f"junit_{guards[0].tier}.xml"
    files = [g.pytest_file for g in guards]
    argv = [
        sys.executable,
        "-m",
        "pytest",
        *files,
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={xml_path}",
        "-o",
        "junit_family=xunit1",
    ]
    code, _ = _run(argv, REPO, 1800, log)
    by_file: dict[str, dict] = {
        g.pytest_file: {"tests": {}, "fail": 0, "skip": 0, "seconds": 0.0} for g in guards
    }
    if xml_path.exists():
        for case in ET.parse(xml_path).getroot().iter("testcase"):  # noqa: S314 - our own pytest output
            cls = case.get("classname", "")
            hit = next(
                (f for f in by_file if cls.startswith(f.removesuffix(".py").replace("/", "."))),
                None,
            )
            if hit is None:
                continue
            row = by_file[hit]
            secs = float(case.get("time", 0))
            row["tests"][f"{case.get('classname', '')}::{case.get('name', '')}"] = secs
            row["seconds"] += secs
            if case.find("failure") is not None or case.find("error") is not None:
                row["fail"] += 1
            elif case.find("skipped") is not None:
                row["skip"] += 1
    results = []
    for g in guards:
        row = by_file[g.pytest_file]
        n = len(row["tests"])
        if n == 0:
            status = "FAIL" if code not in (0, 5) else "SKIP"
            detail = "no tests ran (collection error?)" if status == "FAIL" else "no tests ran"
        elif row["fail"]:
            status, detail = "FAIL", f"{row['fail']} of {n} tests failed"
        elif row["skip"] == n:
            status, detail = "SKIP", f"all {n} tests skipped"
        else:
            status, detail = (
                "PASS",
                f"{n - row['skip']} tests" + (f", {row['skip']} skipped" if row["skip"] else ""),
            )
        results.append(Result(g.name, status, row["seconds"], detail, row["tests"]))
    return missing_results + results


def _run_command_guard(g: Guard, log) -> Result:
    if g.name == "frontend_vitest_budgets" and not (FRONTEND / "node_modules").exists():
        log.write(f"\n[{g.name}] skipped: no node_modules in {FRONTEND}\n")
        return Result(g.name, "SKIP", 0.0, "no node_modules (run npm ci in the frontend)")
    missing = [p for p in g.needs if not p.exists()]
    if missing:
        log.write(f"[{g.name}] skipped: missing {missing[0]}\n")
        return Result(g.name, "SKIP", 0.0, f"needs {missing[0].name} (build the frontend first)")
    code, seconds = _run(g.argv, g.cwd, g.timeout_s, log)
    if code == 0:
        return Result(g.name, "PASS", seconds)
    if code == SKIP_EXIT:
        return Result(g.name, "SKIP", seconds, "could not measure here")
    return Result(g.name, "FAIL", seconds, f"exit {code}")


def _baseline_note(result: Result, baseline: dict) -> str:
    old = baseline.get("guards", {}).get(result.name)
    if not old or result.status != "PASS":
        return ""
    before = float(old.get("seconds", 0))
    delta = result.seconds - before
    flag = ""
    if before > 0 and result.seconds > before * SLOW_FACTOR and delta > SLOW_MIN_DELTA_S:
        flag = " SLOW"
    return f"{delta:+.1f}s vs baseline{flag}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fast", action="store_true", help="unit-level guards only (no app boot)")
    ap.add_argument("--only", help="run only guards whose name contains this text")
    ap.add_argument("--list", action="store_true", help="list the guards and exit")
    ap.add_argument("--save-baseline", action="store_true", help="store this run's timings")
    ap.add_argument(
        "--real-dictation", action="store_true", help="add the on-device dictation replay"
    )
    args = ap.parse_args()

    guards = _guards(args.real_dictation)
    if args.fast:
        guards = [g for g in guards if g.tier == "fast"]
    if args.only:
        guards = [g for g in guards if args.only in g.name]
    if args.list:
        for g in guards:
            print(f"{g.tier:5s} {g.name}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = OUT_DIR / "baseline.json"
    baseline = json.loads(baseline_path.read_text("utf-8")) if baseline_path.exists() else {}
    started = time.perf_counter()
    results: list[Result] = []
    with (OUT_DIR / "last.log").open("w", encoding="utf-8") as log:
        log.write(f"perf_guard {time.strftime('%Y-%m-%d %H:%M:%S')} fast={args.fast}\n")
        for tier in ("fast", "full"):
            group = []
            for g in guards:
                if not (g.pytest_file and g.tier == tier):
                    continue
                missing = [p for p in g.needs if not p.exists()]
                if missing:
                    why = f"needs {missing[0].name} (build the frontend first)"
                    results.append(Result(g.name, "SKIP", 0.0, why))
                else:
                    group.append(g)
            if group:
                print(f"running {len(group)} pytest guard files ({tier}) ...", flush=True)
                results += _run_pytest_group(group, log)
        for g in guards:
            if g.pytest_file:
                continue
            print(f"running {g.name} ...", flush=True)
            results.append(_run_command_guard(g, log))

    width = max(len(r.name) for r in results) if results else 10
    print()
    print(f"{'guard'.ljust(width)}  status  {'sec':>7}  note")
    for r in sorted(results, key=lambda r: r.name):
        note = (r.detail + " " + _baseline_note(r, baseline)).strip()
        print(f"{r.name.ljust(width)}  {r.status:6s}  {r.seconds:7.1f}  {note}")
    counts = {s: sum(1 for r in results if r.status == s) for s in ("PASS", "FAIL", "SKIP")}
    total = time.perf_counter() - started
    print(f"\n{counts['PASS']} pass, {counts['FAIL']} fail, {counts['SKIP']} skip in {total:.0f}s")
    print(f"log: {OUT_DIR / 'last.log'}")

    payload = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fast": args.fast,
        "total_seconds": round(total, 1),
        "guards": {
            r.name: {
                "status": r.status,
                "seconds": round(r.seconds, 2),
                "detail": r.detail,
                "tests": {k: round(v, 3) for k, v in r.tests.items()},
            }
            for r in results
        },
    }
    (OUT_DIR / "last.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    if args.save_baseline:
        merged = baseline.get("guards", {})
        merged.update({k: v for k, v in payload["guards"].items() if v["status"] == "PASS"})
        baseline_path.write_text(
            json.dumps({"guards": merged, "saved": payload["when"]}, indent=1), encoding="utf-8"
        )
        print(f"baseline saved: {baseline_path}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
