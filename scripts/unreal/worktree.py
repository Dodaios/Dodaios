#!/usr/bin/env python3
"""Create or remove the worktree of one Unreal Verse sub-task.

docs/verse/unreal/orchestration.md 3.1:

    python scripts/unreal/worktree.py new wp01-2-recoil-curve
        git fetch origin
        git worktree add -b claude/verse-wp01-2-recoil-curve C:/demo/wt/<short-id> origin/main
        git config lfs.fetchexclude ""               (in the new worktree)
    python scripts/unreal/worktree.py remove <path or short-id>
        1. build.py clean in that worktree (never the shared DDC)
        2. unlink every node_modules junction or link, never delete through it
        3. git worktree remove <path>                (never --force)

Slugs are ``wp<nn>-<k>-<slug>`` for package sub-tasks (``k`` may carry a
letter, ``wp02-4a-...``) and ``int-<slug>`` for integration work. Worktree
paths stay short because Unreal paths under ``Intermediate/`` hit the Windows
path limit: ``<short-id>`` has at most 12 characters. ``DODAIOS_WORKTREE_ROOT``
overrides ``C:/demo/wt``.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import build

ROOT_ENV = "DODAIOS_WORKTREE_ROOT"
DEFAULT_ROOT = Path("C:/demo/wt")
BRANCH_PREFIX = "claude/verse-"
MAX_ID = 12
SLUG = re.compile(r"(wp(0[1-9]|1[0-9]|2[0-2])-[1-9][0-9]*[a-z]?|int)-[a-z0-9]+(-[a-z0-9]+)*")
#: Folders never walked while looking for node_modules links.
_SKIP_WALK = {".git", "node_modules", "Binaries", "Intermediate", "Saved", "DerivedDataCache",
              ".venv", "venv", "__pycache__"}
_WALK_DEPTH = 6
_WINDOWS = os.name == "nt"


def worktree_root(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get(ROOT_ENV, "").strip()
    if override:
        return Path(override)
    return DEFAULT_ROOT if os.name == "nt" else Path.home() / "wt"


def validate_slug(slug: str) -> str:
    if not SLUG.fullmatch(slug):
        raise common.UnrealScriptError(
            f"bad slug {slug!r}: use wp<nn>-<k>-<words> (nn 01-22) or int-<words>, "
            "lower case, words joined by '-'"
        )
    return slug


def short_id(slug: str, taken: Callable[[str], bool] = lambda _id: False) -> str:
    """At most 12 characters from the slug, unique under the worktree root."""
    base = slug[:MAX_ID].rstrip("-")
    if not taken(base):
        return base
    for n in range(2, 100):
        suffix = str(n)
        candidate = base[: MAX_ID - len(suffix) - 1].rstrip("-") + "-" + suffix
        if not taken(candidate):
            return candidate
    raise common.UnrealScriptError(f"no free short id for {slug!r} under the worktree root")


def _git(*args: str, cwd: Path = common.REPO_ROOT, runner=None) -> common.Completed:
    runner = runner or common.run
    return runner(["git", "-C", str(cwd), *args], capture=True)


def _check(result: common.Completed, what: str) -> common.Completed:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise common.UnrealScriptError(f"{what} failed: {detail}")
    return result


def new(
    slug: str,
    *,
    root: Path | None = None,
    wt_id: str | None = None,
    runner: Callable[..., common.Completed] | None = None,
) -> Path:
    validate_slug(slug)
    root = root or worktree_root()
    branch = BRANCH_PREFIX + slug
    if wt_id is not None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,11}", wt_id):
            raise common.UnrealScriptError(f"bad --id {wt_id!r}: 1-12 of a-z, 0-9, '-'")
        if (root / wt_id).exists():
            raise common.UnrealScriptError(f"{root / wt_id} already exists")
        chosen = wt_id
    else:
        chosen = short_id(slug, taken=lambda c: (root / c).exists())
    path = root / chosen
    _check(_git("fetch", "origin", runner=runner), "git fetch origin")
    exists = _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", runner=runner)
    if exists.returncode == 0:
        raise common.UnrealScriptError(f"branch {branch} already exists; pick another slug")
    root.mkdir(parents=True, exist_ok=True)
    _check(
        _git("worktree", "add", "-b", branch, str(path), "origin/main", runner=runner),
        "git worktree add",
    )
    _check(_git("config", "lfs.fetchexclude", "", cwd=path, runner=runner),
           "git config lfs.fetchexclude")
    common.log(f"worktree {path} on {branch} (from origin/main)")
    return path


def _is_link(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def node_modules_links(top: Path, depth: int = _WALK_DEPTH) -> Iterator[Path]:
    """Every ``node_modules`` that is a junction or symlink, without following any."""
    stack = [(top, 0)]
    while stack:
        folder, level = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if entry.name == "node_modules" and _is_link(path):
                yield path
                continue
            if level + 1 >= depth or entry.name in _SKIP_WALK or _is_link(path):
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append((path, level + 1))


def unlink_link(path: Path, runner: Callable[..., common.Completed] | None = None) -> None:
    """Remove the link itself; its target stays untouched."""
    if _WINDOWS:
        _check((runner or common.run)(["cmd", "/c", "rmdir", str(path)], capture=True),
               f"rmdir {path}")
    else:
        path.unlink()


def registered_worktrees(runner=None) -> list[Path]:
    listing = _check(_git("worktree", "list", "--porcelain", runner=runner), "git worktree list")
    return [Path(line[len("worktree "):]) for line in listing.stdout.splitlines()
            if line.startswith("worktree ")]


def resolve_target(target: str, root: Path) -> Path:
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = root / target if not candidate.exists() else candidate
    return candidate.resolve()


def remove(
    target: str,
    *,
    root: Path | None = None,
    runner: Callable[..., common.Completed] | None = None,
    cleaner: Callable[[Path], object] = build.clean,
) -> Path:
    path = resolve_target(target, root or worktree_root())
    registered = [p.resolve() for p in registered_worktrees(runner)]
    if path not in registered:
        raise common.UnrealScriptError(f"{path} is not a worktree of this repository")
    if registered and path == registered[0]:
        raise common.UnrealScriptError(f"{path} is the main checkout; it is never removed")
    cleaner(path)
    for link in node_modules_links(path):
        common.log(f"unlink {link}")
        unlink_link(link, runner)
    _check(_git("worktree", "remove", str(path), runner=runner), "git worktree remove")
    common.log(f"removed worktree {path}")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="action", required=True)
    make = commands.add_parser("new", help="create a sub-task worktree from origin/main")
    make.add_argument("slug", help="wp<nn>-<k>-<words> or int-<words>")
    make.add_argument("--id", dest="wt_id", help="short folder name (max 12 characters)")
    drop = commands.add_parser("remove", help="clean and remove a worktree")
    drop.add_argument("target", help="worktree path or short id")
    options = parser.parse_args(argv)
    try:
        if options.action == "new":
            new(options.slug, wt_id=options.wt_id)
        else:
            remove(options.target)
    except common.UnrealScriptError as error:
        return common.exit_with(error)
    return 0


if __name__ == "__main__":
    sys.exit(main())
