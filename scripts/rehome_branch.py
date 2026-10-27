#!/usr/bin/env python3
"""Move a branch made before the 2026-10-27 history rewrite onto the new main.

On 2026-10-27 the repository history was rewritten once (git filter-repo) to
drop the old frontend bundles, films and Blender files; every commit SHA
changed. A local branch cut before that still sits on the old history, so
``git rebase origin/main`` would try to replay thousands of commits.

This replays only the branch's own commits:

    python scripts/rehome_branch.py            # the checked-out branch
    python scripts/rehome_branch.py --dry-run  # show what it would do

It needs the rewrite's commit map (old SHA -> new SHA), which the rewrite
left in this clone's git directory, and ``refs/backup/pre-rewrite-main``
(old main). A clone made after the rewrite needs neither and never runs this.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

OLD_MAIN = "refs/backup/pre-rewrite-main"
MAP_NAME = "history-rewrite-2026-10-27.commit-map"


def git(*args: str, check: bool = True) -> str:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if check and out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def load_map(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        old, _, new = line.partition(" ")
        if old and new:
            mapping[old] = new
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    map_file = common / MAP_NAME
    if not map_file.is_file() or not git("rev-parse", "--verify", "-q", OLD_MAIN, check=False):
        print("No rewrite data in this clone: a clone made after the rewrite needs nothing.")
        return 0
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if git("merge-base", "HEAD", "origin/main", check=False):
        print(f"{branch} already shares history with origin/main; nothing to do.")
        return 0
    old_base = git("merge-base", "HEAD", OLD_MAIN, check=False)
    if not old_base:
        raise SystemExit(f"{branch} shares no history with old main either; rebase it by hand.")
    new_base = load_map(map_file).get(old_base, "")
    if not new_base or set(new_base) == {"0"}:
        raise SystemExit(f"old base {old_base[:12]} has no rewritten twin; rebase by hand.")
    own = git("rev-list", "--count", f"{old_base}..HEAD")
    print(f"{branch}: {own} own commit(s), old base {old_base[:12]} -> new base {new_base[:12]}")
    if args.dry_run:
        return 0
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Commit or set aside your changes first (the rebase needs a clean tree).")
    done = subprocess.run(["git", "rebase", "--onto", new_base, old_base], check=False)
    if done.returncode != 0:
        print("Resolve the conflicts, then `git rebase --continue`.")
        return done.returncode
    print(f"Done. {branch} now builds on the rewritten history; land it as usual.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
