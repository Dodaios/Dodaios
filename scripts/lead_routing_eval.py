"""Lead routing eval: does the typed lead pick the right first tool?

Offline replay (default, free, what CI runs through pytest):

    python scripts/lead_routing_eval.py
    python scripts/lead_routing_eval.py --replay path/to/recording.json

Live run (opt-in, BILLS the chosen seat, never in CI):

    DODAIOS_LEAD_ROUTING_LIVE=1 python scripts/lead_routing_eval.py --live --seat <provider>

See docs/lead-routing-evals.md.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

if sys.platform == "win32":
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from tests.eval.lead_routing import (  # noqa: E402
    Report,
    build_lead_catalog,
    format_table,
    load_cases,
    load_recordings,
    score_cases,
    validate_cases,
)
from tests.eval.lead_routing.cases import FIXTURE_DIR  # noqa: E402
from tests.eval.lead_routing.validate import catalog_problems, reference_payload  # noqa: E402

RECORDED_DIR = FIXTURE_DIR / "recorded"
RESULTS_DIR = REPO / "eval-results"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--replay", nargs="*", type=Path, metavar="FILE",
                   help="recording files to score (default: every file in recorded/)")
    p.add_argument("--category", action="append", help="only this category (repeatable)")
    p.add_argument("--write-reference", action="store_true",
                   help="regenerate recorded/reference.json from the expectations")
    p.add_argument("--live", action="store_true", help="run against a real seat (bills it)")
    p.add_argument("--seat", action="append", default=[],
                   help="provider id of the seat to run live (repeatable); never chosen for you")
    p.add_argument("--model", help="model id for the live seat")
    p.add_argument("--allow-api-key", action="store_true",
                   help="allow a per-token API key even while a subscription is connected")
    p.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--limit", type=int, help="run only the first N cases (cheap smoke run)")
    p.add_argument("--save-recording", action="store_true",
                   help="also store the live answers so they can be replayed offline")
    p.add_argument("--failures", action="store_true", help="print every failed case")
    return p


def _select(cases, args):  # noqa: ANN001
    if args.category:
        cases = [c for c in cases if c.category in set(args.category)]
    return cases[: args.limit] if args.limit else cases


def _print_failures(report: Report) -> None:
    for result in report.failures():
        print(f"  [{report.seat}] {result.case.id}: {result.status}: {result.detail}")


def _write_report(reports: list[Report], extra: dict) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"lead-routing-{stamp}.json"
    payload = {"generated": stamp, **extra, "seats": [r.to_json() for r in reports]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _replay(cases, catalog, args) -> list[Report]:  # noqa: ANN001
    files = args.replay if args.replay else sorted(RECORDED_DIR.glob("*.json"))
    reports = []
    for path in files:
        seat, recordings = load_recordings(path)
        reports.append(score_cases(cases, recordings, catalog, seat))
    return reports


def _confirmed(cases, catalog, args) -> tuple[list, str]:  # noqa: ANN001
    """Print the billing notice per seat and get the owner's go-ahead. Returns (cases, refusal)."""
    from tests.eval.lead_routing import live
    from tests.eval.lead_routing.scoring import missing_requirements

    runnable = [
        c for c in cases if live.offerable(c, catalog) and not missing_requirements(c, catalog)
    ]
    per_call = live.estimate_tokens_per_call(catalog)
    for seat in args.seat:
        gate = live.live_gate(
            seat, allow_api_key=args.allow_api_key,
            case_count=len(runnable), tokens_per_call=per_call,
        )
        print(f"\n{'=' * 78}\n{gate.notice}\n{'=' * 78}")
        if not gate.allowed:
            reasons = "\n".join(f"  - {r}" for r in gate.reasons)
            return runnable, f"Refusing to start:\n{reasons}"
        if args.yes:
            continue
        if not sys.stdin.isatty():
            return runnable, "Refusing to start: not interactive and --yes was not given."
        if input(f"Type the seat name ({seat}) to start: ").strip() != seat:
            return runnable, "Not confirmed; nothing was run."
    return runnable, ""


async def _live(cases, runnable, catalog, args) -> list[Report]:  # noqa: ANN001
    from tests.eval.lead_routing import live

    reports: list[Report] = []
    for seat in args.seat:
        brain = live.build_brain(seat, args.model)
        done = 0

        def progress(case, rec) -> None:  # noqa: ANN001
            nonlocal done
            done += 1
            print(f"  {done:3d}/{len(runnable)} {case.id:46s} -> {rec.tool or 'no tool'}",
                  flush=True)

        recordings = await live.run_live(
            runnable, catalog, brain, concurrency=args.concurrency, progress=progress
        )
        label = f"{seat}/{args.model}" if args.model else seat
        reports.append(score_cases(cases, recordings, catalog, label))
        if args.save_recording:
            RESULTS_DIR.mkdir(exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            out = RESULTS_DIR / f"lead-routing-{seat}-{stamp}.recording.json"
            payload = {"seat": label, "responses": {k: v.to_json() for k, v in recordings.items()}}
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"recording stored: {out}")
    return reports


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = load_cases()
    problems = validate_cases(cases)
    if problems:
        print("The golden set is malformed:\n  " + "\n  ".join(problems))
        return 2
    if args.write_reference:
        RECORDED_DIR.mkdir(parents=True, exist_ok=True)
        path = RECORDED_DIR / "reference.json"
        path.write_text(json.dumps(reference_payload(cases), indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(f"wrote {path} ({len(cases)} cases)")
        return 0
    if args.live and not args.seat:
        print("--live needs an explicit --seat <provider>; no seat is ever chosen for you.")
        return 2
    cases = _select(cases, args)
    catalog = build_lead_catalog()
    drift = catalog_problems(cases, catalog)
    if drift:
        print("Catalog drift (the golden set names something the lead no longer has):")
        print("  " + "\n  ".join(drift))
    if args.live:
        runnable, refusal = _confirmed(cases, catalog, args)
        if refusal:
            print(refusal)
            return 2
        reports, extra = asyncio.run(_live(cases, runnable, catalog, args)), {"mode": "live"}
    else:
        reports, extra = _replay(cases, catalog, args), {"mode": "replay"}
    if not reports:
        return 2
    print("\n" + format_table(reports))
    for report in reports:
        summary = report.summary()
        print(f"\n{report.seat}: {summary['passed']}/{summary['cases']} passed, "
              f"{summary['skipped']} skipped (tools not in the catalog yet)")
        if args.failures or args.live:
            _print_failures(report)
    if args.live:
        print(f"\nreport: {_write_report(reports, extra)}")
    failed = any(r.failures() for r in reports)
    return 1 if (failed and not args.live) or drift else 0


if __name__ == "__main__":
    sys.exit(main())
