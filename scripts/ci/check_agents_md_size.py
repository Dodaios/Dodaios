#!/usr/bin/env python3
"""Keep the agent rulebook short enough to be read and followed.

Every line of ``AGENTS.md`` is loaded into every agent session. Research on
context files (arXiv 2602.11988) found that long ones raise agent cost by about
a fifth and help little: only what the agent cannot discover from the code
helps. So the root file is a routing map with a hard cap, and a rule that
needs more room lives in a doc or in a small per-folder ``AGENTS.md``.

Fails when the root ``AGENTS.md`` is longer than 150 lines or 12,000
characters, or when any other tracked ``AGENTS.md`` is longer than 60 lines.

stdlib-only; reads the git index, so it works in linked worktrees.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT_MAX_LINES = 150
ROOT_MAX_CHARS = 12_000
FOLDER_MAX_LINES = 60
# Independent side-projects that co-live in this repo and keep their own rulebook.
SIDE_PROJECTS = ("skillbook/",)


def _repo_root() -> Path | None:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(proc.stdout.strip()) if proc.returncode == 0 else None


def _tracked(repo: Path) -> list[str] | None:
    proc = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def problems(repo: Path, tracked: list[str]) -> list[str]:
    found: list[str] = []
    for rel in tracked:
        if PurePosixPath(rel).name != "AGENTS.md" or rel.startswith(SIDE_PROJECTS):
            continue
        path = repo / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = len(text.splitlines())
        if rel == "AGENTS.md":
            if lines > ROOT_MAX_LINES:
                found.append(f"{rel}: {lines} lines, limit {ROOT_MAX_LINES}")
            if len(text) > ROOT_MAX_CHARS:
                found.append(f"{rel}: {len(text)} characters, limit {ROOT_MAX_CHARS}")
        elif lines > FOLDER_MAX_LINES:
            found.append(f"{rel}: {lines} lines, limit {FOLDER_MAX_LINES}")
    return found


def main(argv: list[str] | None = None) -> int:
    repo = _repo_root()
    tracked = _tracked(repo) if repo is not None else None
    if repo is None or tracked is None:
        sys.stderr.write("check_agents_md_size: not inside a git repo (or git missing).\n")
        return 3
    found = problems(repo, tracked)
    if found:
        sys.stderr.write("check_agents_md_size: the agent rulebook grew too long:\n")
        for line in found:
            sys.stderr.write(f"  {line}\n")
        sys.stderr.write("Move detail into a doc and link it; keep only what an agent cannot find.\n")
        return 1
    if "--quiet" not in (argv if argv is not None else sys.argv[1:]):
        print("check_agents_md_size: AGENTS.md files are within their size caps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
