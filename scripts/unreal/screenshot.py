#!/usr/bin/env python3
"""Run a ``Verse.Visual.*`` suite on the GPU under the machine lock.

The only screenshot entry for agents (docs/verse/unreal/orchestration.md 5.3).

    python scripts/unreal/screenshot.py --suite Verse.Visual.Hangar

One rendered process at a time (orchestration.md 4). The game window opens
off the person's monitors, so nothing appears on their desktop and their
desktop is never captured. The automation framework compares each shot with
the ground truth in ``unreal/Verse/Tests/GroundTruth/Win64/``; reports and
shots land in ``unreal/Verse/Saved/Harness/proof/<branch>/<run>/`` and are
never committed. Pass rules are the ones of ``test.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import test as automation

SUITE_PREFIX = "Verse.Visual."
#: Far outside any monitor layout, so the window never covers the person's work.
OFFSCREEN = ("-WinX=-32000", "-WinY=-32000")


def render_args(width: int = 1920, height: int = 1080) -> list[str]:
    return [
        "-game",
        "-d3d12",
        "-windowed",
        f"-ResX={width}",
        f"-ResY={height}",
        *OFFSCREEN,
        "-benchmark",
        "-fps=30",
    ]


def proof_dir(worktree: Path) -> Path:
    branch = common.safe_name(common.current_branch(worktree))
    return worktree / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / branch


def capture(
    suite: str, *, worktree: Path = common.REPO_ROOT, **kwargs
) -> list[automation.RunResult]:
    if not suite.startswith(SUITE_PREFIX):
        raise common.UnrealScriptError(
            f"visual suites are named {SUITE_PREFIX}<Suite>, got {suite!r}"
        )
    return automation.run_tests(
        suite,
        worktree=worktree,
        rendered=True,
        extra=render_args(),
        report_base=proof_dir(worktree),
        **kwargs,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", required=True, help="for example Verse.Visual.Hangar")
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    options = parser.parse_args(argv)
    try:
        results = capture(options.suite, worktree=options.worktree.resolve())
    except common.UnrealScriptError as error:
        return common.exit_with(error)
    return automation.summarize(results)


if __name__ == "__main__":
    sys.exit(main())
