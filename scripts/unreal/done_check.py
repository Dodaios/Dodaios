#!/usr/bin/env python3
"""Unreal lane status for the repo done gate (architecture.md 8.3, docs/agent-done-gate.md).

A change that touches ``unreal/**``, ``art/verse/**`` or ``docs/verse/unreal/**``
is done only when the Unreal lanes that cover it are green on the commit, and a
visible change has a harness screenshot in its evidence folder. This script says
which lanes the change needs, asks GitHub for their latest run on the commit, and
answers ``DONE``, ``NOT DONE`` (exit 1) or ``n/a`` (no Unreal path, exit 0).
``scripts/agent_done_gate.py`` calls it (the hook line belongs to the
integration owner).

    python scripts/unreal/done_check.py                       # HEAD against origin/main
    python scripts/unreal/done_check.py --commit <sha> --base origin/main --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNREAL_PREFIXES = ("unreal/", "art/verse/", "docs/verse/unreal/")
#: Paths whose change needs a compile and the automation tests.
BUILD_PREFIXES = (
    "unreal/Verse/Source/",
    "unreal/Verse/Config/",
    "unreal/Verse/Content/",
    "unreal/Verse/Verse.uproject",
    "unreal/Verse/Plugins/",
)
#: Paths whose change is visible and needs a screenshot of the running build.
VISIBLE_PREFIXES = ("unreal/Verse/Content/", "art/verse/", "unreal/Verse/Art/")
LANES = {"static": "unreal-static.yml", "build": "unreal-build.yml"}
GREEN = {"success"}

Runner = Callable[[Sequence[str]], str]


def _run(command: Sequence[str]) -> str:
    proc = subprocess.run(
        list(command),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,  # noqa: S603
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return proc.stdout


def changed(base: str, commit: str, run: Runner = _run) -> list[str]:
    out = run(["git", "diff", "--name-only", f"{base}...{commit}"])
    return [p for p in out.splitlines() if p]


def needed_lanes(paths: Sequence[str]) -> list[str]:
    unreal = [p for p in paths if p.startswith(UNREAL_PREFIXES)]
    if not unreal:
        return []
    lanes = ["static"]
    if any(p.startswith(BUILD_PREFIXES) for p in unreal):
        lanes.append("build")
    return lanes


def is_visible(paths: Sequence[str]) -> bool:
    return any(p.startswith(VISIBLE_PREFIXES) for p in paths)


def lane_status(workflow: str, commit: str, run: Runner = _run) -> dict:
    try:
        out = run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--commit",
                commit,
                "--limit",
                "5",
                "--json",
                "status,conclusion,url,event,headSha,createdAt",
            ]
        )
        runs = json.loads(out or "[]")
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as exc:
        return {"workflow": workflow, "state": "unknown", "detail": f"gh failed: {exc}"}
    if not runs:
        return {"workflow": workflow, "state": "missing", "detail": "no run on this commit"}
    latest = max(runs, key=lambda r: r.get("createdAt", ""))
    if latest.get("status") != "completed":
        return {"workflow": workflow, "state": "running", "detail": latest.get("url", "")}
    state = "green" if latest.get("conclusion") in GREEN else "red"
    return {
        "workflow": workflow,
        "state": state,
        "detail": latest.get("url", ""),
        "conclusion": latest.get("conclusion"),
    }


def has_screenshot(worktree: Path) -> bool:
    proof = worktree / "unreal" / "Verse" / "Saved" / "Harness" / "proof"
    return proof.exists() and any(proof.rglob("*.png"))


def evaluate(paths: Sequence[str], commit: str, worktree: Path, run: Runner = _run) -> dict:
    lanes = needed_lanes(paths)
    if not lanes:
        return {"verdict": "n/a", "lanes": [], "detail": "no Unreal path changed"}
    statuses = [lane_status(LANES[lane], commit, run) for lane in lanes]
    problems = [
        f"{s['workflow']}: {s['state']} {s.get('detail', '')}".strip()
        for s in statuses
        if s["state"] != "green"
    ]
    visible = is_visible(paths)
    if visible and not has_screenshot(worktree):
        problems.append(
            "visible change without a harness screenshot (scripts/unreal/capture.py shots)"
        )
    return {
        "verdict": "NOT DONE" if problems else "DONE",
        "lanes": statuses,
        "visible": visible,
        "problems": problems,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--worktree", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        commit = _run(["git", "rev-parse", args.commit]).strip()
        paths = changed(args.base, commit)
    except subprocess.CalledProcessError as exc:
        print(f"done_check: git failed: {exc}", file=sys.stderr)
        return 2
    result = evaluate(paths, commit, args.worktree)
    result["commit"] = commit
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for lane in result["lanes"]:
            print(f"done_check: {lane['workflow']}: {lane['state']} {lane.get('detail', '')}")
        for problem in result.get("problems", []):
            print(f"done_check: {problem}")
        print(f"done_check: {result['verdict']}")
    return 1 if result["verdict"] == "NOT DONE" else 0


if __name__ == "__main__":
    sys.exit(main())
