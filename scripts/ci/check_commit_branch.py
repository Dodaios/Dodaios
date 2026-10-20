#!/usr/bin/env python3
"""Refuse a local commit on ``main``.

Local ``main`` is a mirror of ``origin/main``: it moves only by fast-forward
(``git pull --ff-only``). Work is committed on a feature branch and reaches
``main`` through its pull request and the merge queue. A commit made on local
``main`` exists on one machine only, and because the queue squash-merges, the
two histories stop sharing commits: within days local ``main`` is both ahead of
and behind the remote, and every later landing has to untangle that first.

This gate fails when ``HEAD`` is the ``main`` branch. A detached ``HEAD`` and
every other branch pass. CI runners are left alone: the workflows that write to
``main`` do it through their own reviewed path.

Used from ``.githooks/pre-commit``.

stdlib-only.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

PROTECTED_BRANCHES = frozenset({"main"})

# Exit codes: 0 = commit allowed, 1 = commit on a protected branch.
EXIT_OK = 0
EXIT_PROTECTED = 1


def _current_branch() -> str | None:
    """Return the checked-out branch, or None on a detached HEAD or outside git."""
    proc = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on the success path.",
    )
    args = parser.parse_args(argv)

    if os.environ.get("GITHUB_ACTIONS") == "true":
        return EXIT_OK

    branch = _current_branch()
    if branch not in PROTECTED_BRANCHES:
        if not args.quiet:
            print(f"check_commit_branch: commits are allowed on {branch or 'a detached HEAD'}.")
        return EXIT_OK

    sys.stderr.write(
        f"check_commit_branch: '{branch}' mirrors origin/{branch} and takes no local commits.\n"
        "Put the change on a feature branch in a worktree of your own:\n"
        f"  git worktree add -b <agent>/<topic> <path> origin/{branch}\n"
        "Your uncommitted edits stay where they are; carry your own paths over with\n"
        "  git diff HEAD -- <paths> | git -C <path> apply --3way\n"
        "and land the branch with: python scripts/agent_land.py\n"
        "In a clone nobody else uses, `git switch -c <topic>` does the same in place.\n"
    )
    return EXIT_PROTECTED


if __name__ == "__main__":
    raise SystemExit(main())
