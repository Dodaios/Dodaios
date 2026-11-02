#!/usr/bin/env python3
"""Prove that a test run left the checkout as it found it.

A test run must never rewrite a tracked file (``scripts/config-soll.json`` was  # i18n-allow: filename
flipped to another brain provider by a config-writer test) or leave a new file
behind (the parallel runner wrote ``report.xml`` into the working directory).

The guard compares two snapshots of ``git status``. A snapshot maps every path
that is modified or untracked to its status, size and modification time, so a
path that turns dirty, appears, or is rewritten again while already dirty all
count as a change. Paths that were dirty before the run and stay untouched do
not, so a developer's own edits never fail it.

Used by:

* ``tests/conftest.py``: a pytest session that rewrites a tracked file fails.
  Untracked files are not judged there, because sibling processes of the
  parallel runner create short-lived probe files of their own.
* ``scripts/ci/run_tests_parallel.py``: the whole run, after every process has
  ended, must leave no new or changed path outside its own outputs.
* CI (``.github/workflows/ci.yml``): ``snapshot`` before the shard,
  ``check`` after it.

Commands::

    python scripts/ci/checkout_guard.py snapshot --out before.json
    python scripts/ci/checkout_guard.py check --snapshot before.json --ignore out/
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

Snapshot = dict[str, str]


def snapshot(root: Path | None = None, *, untracked: bool = True) -> Snapshot | None:
    """Return ``{path: "status:size:mtime"}`` for every dirty path, or None.

    None means the state cannot be read (no git, not a checkout); callers then
    skip the check instead of failing on it.
    """
    root = REPO_ROOT if root is None else root
    try:
        proc = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-c",
                "core.quotepath=off",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=" + ("all" if untracked else "no"),
            ],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    entries = proc.stdout.decode("utf-8", errors="replace").split("\0")
    state: Snapshot = {}
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            index += 1  # the rename/copy source follows as its own field
        state[path] = f"{status}:{_stamp(root / path)}"
    return state


def _stamp(path: Path) -> str:
    try:
        info = path.stat()
    except OSError:
        return "-"
    if path.is_dir():
        return "dir"
    return f"{info.st_size}:{info.st_mtime_ns}"


def changes(before: Snapshot, after: Snapshot, ignore: Iterable[str] = ()) -> list[str]:
    """Paths whose state differs between the snapshots, minus ``ignore``.

    An ``ignore`` entry ending in ``/`` covers a whole directory; any other
    entry is one path. A path that was dirty before and is clean afterwards
    counts too: the run reverted somebody's edit.
    """
    prefixes = tuple(_norm(item) for item in ignore if item)
    found = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        if any(path == p.rstrip("/") or (p.endswith("/") and path.startswith(p)) for p in prefixes):
            continue
        found.append(path)
    return found


def _norm(item: str) -> str:
    text = item.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def describe(paths: list[str], limit: int = 20) -> str:
    lines = [f"  {path}" for path in paths[:limit]]
    if len(paths) > limit:
        lines.append(f"  ... and {len(paths) - limit} more")
    return "\n".join(lines)


def relative_ignores(paths: Iterable[Path], root: Path | None = None) -> list[str]:
    """Repo-relative forms of output paths that live inside the checkout."""
    root = REPO_ROOT if root is None else root
    found = []
    for path in paths:
        try:
            found.append(path.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            continue  # outside the checkout: git never sees it
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="Record the checkout's dirty paths.")
    snap.add_argument("--out", type=Path, required=True)
    check = sub.add_parser("check", help="Fail when the checkout changed since the snapshot.")
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--ignore", action="append", default=[], help="Path or dir/ to skip.")
    args = parser.parse_args(argv)

    current = snapshot()
    if current is None:
        print("checkout_guard: git status is unavailable; nothing checked.")
        return 0
    if args.command == "snapshot":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"checkout_guard: {len(current)} dirty path(s) recorded.")
        return 0
    before = json.loads(args.snapshot.read_text(encoding="utf-8"))
    changed = changes(before, current, args.ignore)
    if not changed:
        print("checkout_guard: the checkout is as the snapshot found it.")
        return 0
    print(
        "::error title=Tests changed the checkout::The test run modified tracked files or "
        "left new files in the checkout. Point the writer at a temp path:"
    )
    print(describe(changed, limit=50))
    return 1


if __name__ == "__main__":
    sys.exit(main())
