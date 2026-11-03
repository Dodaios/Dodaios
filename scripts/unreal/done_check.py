#!/usr/bin/env python3
"""Unreal lane status for the repo done gate (architecture.md 8.3, docs/agent-done-gate.md).

A change that touches ``unreal/**``, ``art/verse/**``, ``docs/verse/unreal/**``,
``scripts/unreal/**`` or an ``unreal-*`` workflow is done only when the Unreal
lanes that cover it are green on the commit, and a visible change has a harness
screenshot of its own work package, taken after the commit, under
``Saved/Harness/proof/<WP>/<sub-task>/``. The work package comes from ``--wp``,
the PR body's ``Work-Package:`` line or the branch name (``claude/verse-wp10-...``).
This script says
which lanes the change needs, asks GitHub for their latest run on the commit, and
answers ``DONE``, ``NOT DONE`` (exit 1) or ``n/a`` (no Unreal path, exit 0).
``scripts/agent_done_gate.py`` calls it (the hook line belongs to the
integration owner).

    python scripts/unreal/done_check.py                       # HEAD against origin/main
    python scripts/unreal/done_check.py --commit <sha> --base origin/main --json
    python scripts/unreal/done_check.py --wp WP12
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNREAL_PREFIXES = (
    "unreal/",
    "art/verse/",
    "docs/verse/unreal/",
    "scripts/unreal/",
    ".github/workflows/unreal-",
)
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


def _quiet(command: Sequence[str]) -> str:
    try:
        return _run(command)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


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


WP_PATTERN = re.compile(r"\bWP(\d{1,2})\b", re.I)


def work_package(explicit: str | None, branch: str = "", pr_body: str = "") -> str | None:
    """``WPnn`` from ``--wp``, the PR body's ``Work-Package:`` line, or the branch name."""
    if explicit:
        match = WP_PATTERN.search(explicit)
        return f"WP{int(match.group(1)):02d}" if match else explicit
    for line in pr_body.splitlines():
        if line.lower().startswith("work-package:"):
            match = WP_PATTERN.search(line)
            if match:
                return f"WP{int(match.group(1)):02d}"
    match = re.search(r"verse-wp(\d{1,2})", branch, re.I)
    return f"WP{int(match.group(1)):02d}" if match else None


def has_screenshot(worktree: Path, wp: str | None, since: float) -> bool:
    """A PNG under ``proof/<WP>/<sub-task>/`` written after ``since`` (the commit time)."""
    if not wp:
        return False
    proof = worktree / "unreal" / "Verse" / "Saved" / "Harness" / "proof"
    for folder in (proof / wp, proof / wp.replace("WP0", "WP")):
        if not folder.is_dir():
            continue
        for png in folder.glob("*/**/*.png"):
            try:
                if png.stat().st_mtime >= since:
                    return True
            except OSError:
                continue
    return False


def evaluate(
    paths: Sequence[str],
    commit: str,
    worktree: Path,
    run: Runner = _run,
    *,
    wp: str | None = None,
    since: float = 0.0,
) -> dict:
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
    if visible and not has_screenshot(worktree, wp, since):
        problems.append(
            f"visible change without a harness screenshot of {wp or 'its work package'} "
            "taken after the commit (scripts/unreal/capture.py shots --wp <WP> --subtask <n>)"
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
    parser.add_argument("--wp", help="Work package (WP10); default from the PR or the branch.")
    args = parser.parse_args(argv)
    try:
        commit = _run(["git", "rev-parse", args.commit]).strip()
        paths = changed(args.base, commit)
    except subprocess.CalledProcessError as exc:
        print(f"done_check: git failed: {exc}", file=sys.stderr)
        return 2
    since = float(_run(["git", "show", "-s", "--format=%ct", commit]).strip() or 0)
    wp = args.wp
    if not wp:
        branch = _quiet(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        body = _quiet(["gh", "pr", "view", "--json", "body", "--jq", ".body"])
        wp = work_package(None, branch, body)
    result = evaluate(paths, commit, args.worktree, wp=wp, since=since)
    result["workPackage"] = wp
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
