"""A repository's local state, read fast enough to poll.

The IDE's Git tab asks for the same repository every few seconds, from every
open pane. Reading it costs a handful of ``git`` processes, and the expensive
part — every branch with how far it is ahead of / behind its upstream and the
default branch — only changes when a ref moves. So this module splits the read
in two:

* **Branches** are read once and reused until the repository's refs change.
  The check is a walk over the ref files' timestamps (no process), so an
  unchanged repository costs a few milliseconds instead of half a second.
* **The checkout** (uncommitted changes, ahead/behind of the current branch) is
  one ``git status`` per read, shared by callers that ask within a second.

A cold read runs its git commands side by side. Nothing here raises: a folder
that is not a repository, or a machine without git, answers ``None``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS

_GIT_TIMEOUT_S = 8.0
#: A status answer this young is shared instead of read again (N panes, one repository).
STATUS_SHARE_S = 1.0
#: Branches are re-read at least this often even when no ref file changed.
BRANCHES_MAX_AGE_S = 30.0
#: Where a repository's paths are remembered before git is asked again.
_PATHS_TTL_S = 60.0
#: Default-branch names tried when ``origin/HEAD`` does not say.
_DEFAULT_CANDIDATES = ("main", "master", "trunk", "develop")


class Job:
    """One call on a daemon thread, so a cold read runs its git commands side by side.

    Daemon threads on purpose: a hung git must never keep the app from exiting.
    """

    def __init__(self, target: Callable[..., Any], *args: Any) -> None:
        self._value: Any = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._work, args=(target, args), name="git-local", daemon=True
        )
        self._thread.start()

    def _work(self, target: Callable[..., Any], args: tuple[Any, ...]) -> None:
        try:
            self._value = target(*args)
        except BaseException as exc:  # re-raised in the caller by result()
            self._error = exc

    def result(self) -> Any:
        self._thread.join()
        if self._error is not None:
            raise self._error
        return self._value


# ------------------------------------------------------------------ plumbing


def run_git(
    args: list[str], cwd: Path, *, timeout: float = _GIT_TIMEOUT_S, stdin: str | None = None
):
    """One git call that never prompts; None when git is missing or hangs."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Reading must never take the index lock away from the person's own git.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", "-c", "core.quotePath=false", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
            input=stdin,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
    except FileNotFoundError:  # git not installed: callers report it as unavailable
        return None
    except subprocess.TimeoutExpired:
        logger.info("Git: `git {}` did not answer in time in {}", args[0] if args else "", cwd)
        return None


def git_out(args: list[str], cwd: Path) -> str | None:
    result = run_git(args, cwd)
    if result is None or result.returncode != 0:
        return None
    return result.stdout


# ------------------------------------------------------------------ model


@dataclass(slots=True)
class LocalBranch:
    name: str
    head: str = ""
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    #: The upstream is configured but no longer exists on the remote.
    upstream_gone: bool = False
    committed_at: int = 0
    #: The folder this branch is checked out in ("" when it is nowhere).
    worktree: str = ""
    #: Commits it has that the default branch lacks / lacks that it has; None when unknown.
    base_ahead: int | None = None
    base_behind: int | None = None
    #: Targets whose history already contains all of its commits.
    merged_into: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Checkout:
    """The folder's own state: what is uncommitted and how it stands to its remote."""

    branch: str = ""
    detached: bool = False
    #: No commit yet (a fresh ``git init``).
    unborn: bool = False
    head: str = ""
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    #: Files with any uncommitted change; one both staged and edited counts once.
    files: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    conflicted: int = 0
    #: ``merge`` | ``rebase`` | ``cherry-pick`` | ``revert`` | ``bisect`` while one is unfinished.
    operation: str = ""
    stashes: int = 0
    #: Epoch seconds of the last ``git fetch`` (0 when never).
    last_fetch: int = 0
    has_remote: bool = False


@dataclass(slots=True)
class LocalState:
    root: Path
    checkout: Checkout
    default_branch: str = ""
    #: What ``base_ahead`` / ``base_behind`` compare with (``origin/main``), "" when unknown.
    base_ref: str = ""
    branches: list[LocalBranch] = field(default_factory=list)
    #: Remote-tracking branch (``origin/main``) → the commit it points at.
    remote_heads: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class RepoPaths:
    root: Path
    #: This checkout's git directory (``.git``, or ``.git/worktrees/<name>``).
    git_dir: Path
    #: The directory every worktree of the repository shares.
    common_dir: Path


# ------------------------------------------------------------------ locating

_paths_guard = threading.Lock()
_paths: dict[str, tuple[float, RepoPaths]] = {}


def locate(folder: str | Path) -> RepoPaths | None:
    """The repository ``folder`` is in; None when it is not one (or git is missing)."""
    path = Path(folder).expanduser()
    if not path.is_dir() or shutil.which("git") is None:
        return None
    key = os.path.normcase(str(path))
    now = time.monotonic()
    with _paths_guard:
        hit = _paths.get(key)
    if hit and now - hit[0] < _PATHS_TTL_S and hit[1].git_dir.is_dir():
        return hit[1]
    text = git_out(["rev-parse", "--show-toplevel", "--git-dir", "--git-common-dir"], path)
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 3:
        with _paths_guard:
            _paths.pop(key, None)
        return None

    def absolute(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (path / candidate)

    found = RepoPaths(
        root=Path(lines[0]), git_dir=absolute(lines[1]), common_dir=absolute(lines[2])
    )
    with _paths_guard:
        _paths[key] = (now, found)
    return found


# ------------------------------------------------------------------ fingerprint


def _stamp(path: Path) -> tuple[int, int]:
    try:
        info = path.stat()
    except OSError:  # the file does not exist (no packed refs yet, no fetch yet)
        return (0, 0)
    return (info.st_mtime_ns, info.st_size)


def _walk(folder: Path, into: list[tuple[str, int, int]]) -> None:
    try:
        entries = sorted(os.scandir(folder), key=lambda entry: entry.name)
    except OSError:  # no such directory (a repository without remotes): nothing to add
        return
    for entry in entries:
        try:
            info = entry.stat()
            is_dir = entry.is_dir()
        except OSError:  # deleted between the listing and the stat: the next read sees it gone
            continue
        into.append((entry.path, info.st_mtime_ns, info.st_size))
        if is_dir:
            _walk(Path(entry.path), into)


def refs_fingerprint(paths: RepoPaths) -> tuple:
    """Changes whenever a branch, a remote-tracking ref, HEAD or a worktree does.

    Git moves a ref by renaming a lock file over it, so both the file's and its
    directory's timestamp change; packed and reftable storage change their own
    files. Reading timestamps costs no process.
    """
    marks: list[tuple[str, int, int]] = []
    for name in ("HEAD", "packed-refs", "config"):
        marks.append((name, *_stamp(paths.common_dir / name)))
    if paths.git_dir != paths.common_dir:
        marks.append(("worktree-HEAD", *_stamp(paths.git_dir / "HEAD")))
    _walk(paths.common_dir / "refs" / "heads", marks)
    _walk(paths.common_dir / "refs" / "remotes", marks)
    _walk(paths.common_dir / "reftable", marks)
    try:
        trees = sorted(os.scandir(paths.common_dir / "worktrees"), key=lambda entry: entry.name)
    except OSError:  # no linked worktrees
        trees = []
    for tree in trees:
        marks.append((tree.name, *_stamp(Path(tree.path) / "HEAD")))
    return tuple(marks)


# ------------------------------------------------------------------ branches

# None until the first read; False on a git older than 2.41 (no ``ahead-behind`` atom).
_ahead_behind_ok: bool | None = None


def _parse_track(text: str) -> tuple[int, int, bool]:
    ahead = behind = 0
    gone = False
    for part in text.split(","):
        word, _, count = part.strip().partition(" ")
        if word == "ahead" and count.isdigit():
            ahead = int(count)
        elif word == "behind" and count.isdigit():
            behind = int(count)
        elif word == "gone":
            gone = True
    return ahead, behind, gone


def _read_heads(root: Path) -> list[LocalBranch]:
    text = git_out(
        [
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)%09%(objectname)%09%(upstream:short)%09"
            "%(upstream:track,nobracket)%09%(committerdate:unix)%09%(worktreepath)",
            "refs/heads",
        ],
        root,
    )
    rows: list[LocalBranch] = []
    for line in (text or "").splitlines():
        name, oid, upstream, track, stamp, tree = ([*line.split("\t"), "", "", "", "", ""])[:6]
        if not name:
            continue
        ahead, behind, gone = _parse_track(track)
        rows.append(
            LocalBranch(
                name=name,
                head=oid,
                upstream=upstream,
                ahead=ahead,
                behind=behind,
                upstream_gone=gone,
                committed_at=int(stamp) if stamp.isdigit() else 0,
                worktree=str(Path(tree)) if tree else "",
            )
        )
    return rows


def _read_remote_heads(root: Path) -> dict[str, str]:
    text = git_out(
        ["for-each-ref", "--format=%(refname:short)%09%(objectname)", "refs/remotes"], root
    )
    heads: dict[str, str] = {}
    for line in (text or "").splitlines():
        name, _, oid = line.partition("\t")
        if name and oid and not name.endswith("/HEAD"):
            heads[name] = oid.strip()
    return heads


def _read_origin_default(root: Path) -> str:
    text = git_out(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], root)
    return text.strip().split("/", 1)[-1] if text and text.strip() else ""


def _pair(text: str) -> tuple[int, int] | None:
    ahead, _, behind = text.strip().partition(" ")
    return (int(ahead), int(behind)) if ahead.isdigit() and behind.isdigit() else None


def _read_ahead_behind(
    root: Path, refs: list[str]
) -> dict[str, list[tuple[int, int] | None]] | None:
    """Branch → (ahead, behind) against each of ``refs``, in one history walk.

    None on a git without the ``ahead-behind`` atom; the caller then falls back
    to one ``--merged`` listing and reports no counts.
    """
    global _ahead_behind_ok
    if not refs or _ahead_behind_ok is False:
        return None
    atoms = "%09".join(f"%(ahead-behind:{ref})" for ref in refs)
    result = run_git(["for-each-ref", f"--format=%(refname:short)%09{atoms}", "refs/heads"], root)
    if result is None:
        return None
    if result.returncode != 0:
        if "unknown field name" in (result.stderr or ""):
            _ahead_behind_ok = False
        return None
    _ahead_behind_ok = True
    counts: dict[str, list[tuple[int, int] | None]] = {}
    for line in result.stdout.splitlines():
        name, *cells = line.split("\t")
        if name:
            counts[name] = [_pair(cell) for cell in cells]
    return counts


def merged_into(root: Path, target_ref: str) -> dict[str, str]:
    """Branch name → tip, for every branch whose commits ``target_ref`` already has."""
    text = git_out(
        [
            "for-each-ref",
            f"--merged={target_ref}",
            "--format=%(refname:short)%09%(objectname)",
            "refs/heads",
        ],
        root,
    )
    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        name, _, oid = line.partition("\t")
        if name:
            found[name] = oid.strip()
    return found


@dataclass(slots=True)
class _Branches:
    fingerprint: tuple
    taken_at: float
    default_branch: str
    base_ref: str
    rows: list[LocalBranch]
    remote_heads: dict[str, str]


def _read_branches(paths: RepoPaths, current: str, fingerprint: tuple) -> _Branches:
    root = paths.root
    default = _read_origin_default(root)
    heads_job = Job(_read_heads, root)
    remotes_job = Job(_read_remote_heads, root)
    # Counted while the branch list is still being read; the guess holds
    # whenever the default branch exists both here and on the remote.
    guess = [f"refs/heads/{default}", f"refs/remotes/origin/{default}"] if default else []
    counts_job = Job(_read_ahead_behind, root, guess) if guess else None
    rows, remote_heads = heads_job.result(), remotes_job.result()
    names = {row.name: row for row in rows}
    if not default:
        default = next((name for name in _DEFAULT_CANDIDATES if name in names), current)

    # The default branch as this computer has it, and as the remote does: a
    # branch whose commits are in either is merged.
    targets: list[str] = []
    if default and default in names:
        targets.append(f"refs/heads/{default}")
    if default and f"origin/{default}" in remote_heads:
        targets.append(f"refs/remotes/origin/{default}")
    base_ref = ""
    if targets:
        base_ref = f"origin/{default}" if targets[-1].startswith("refs/remotes/") else default
    tips = [
        names[default].head if ref.startswith("refs/heads/") else remote_heads[f"origin/{default}"]
        for ref in targets
    ]

    counts = counts_job.result() if counts_job is not None else None
    if targets != guess:
        counts = _read_ahead_behind(root, targets)
    if counts is not None:
        for row in rows:
            cells = counts.get(row.name) or []
            pairs = [cell for cell in cells if cell is not None]
            if pairs:
                row.base_ahead, row.base_behind = pairs[-1]
            if row.name == default:
                continue
            # Tip equal to the target's: created from it, no work of its own — not "merged".
            if any(
                cell is not None and cell[0] == 0 and row.head != tips[index]
                for index, cell in enumerate(cells[: len(tips)])
            ):
                row.merged_into = [default]
    else:
        for index, ref in enumerate(targets):
            for name, oid in merged_into(root, ref).items():
                row = names.get(name)
                if (
                    row is not None
                    and name != default
                    and oid != tips[index]
                    and not row.merged_into
                ):
                    row.merged_into = [default]
    return _Branches(
        fingerprint=fingerprint,
        taken_at=time.monotonic(),
        default_branch=default,
        base_ref=base_ref,
        rows=rows,
        remote_heads=remote_heads,
    )


# ------------------------------------------------------------------ checkout


def _parse_status(text: str, checkout: Checkout) -> None:
    """Fill ``checkout`` from ``git status --porcelain=v2 --branch``."""
    for line in text.splitlines():
        if line.startswith("# branch.oid "):
            oid = line[len("# branch.oid ") :].strip()
            checkout.unborn = oid == "(initial)"
            checkout.head = "" if checkout.unborn else oid[:12]
        elif line.startswith("# branch.head "):
            head = line[len("# branch.head ") :].strip()
            checkout.detached = head == "(detached)"
            checkout.branch = "" if checkout.detached else head
        elif line.startswith("# branch.upstream "):
            checkout.upstream = line[len("# branch.upstream ") :].strip()
        elif line.startswith("# branch.ab "):
            ahead, _, behind = line[len("# branch.ab ") :].strip().partition(" ")
            if ahead[1:].isdigit() and behind[1:].isdigit():
                checkout.ahead, checkout.behind = int(ahead[1:]), int(behind[1:])
        elif line.startswith(("1 ", "2 ")):
            xy = line[2:4]
            checkout.files += 1
            if xy[:1] != ".":
                checkout.staged += 1
            if xy[1:2] != ".":
                checkout.unstaged += 1
        elif line.startswith("u "):
            checkout.files += 1
            checkout.conflicted += 1
        elif line.startswith("? "):
            checkout.files += 1
            checkout.untracked += 1


def _operation(git_dir: Path) -> str:
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        return "rebase"
    for marker, name in (
        ("MERGE_HEAD", "merge"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("REVERT_HEAD", "revert"),
        ("BISECT_LOG", "bisect"),
    ):
        if (git_dir / marker).exists():
            return name
    return ""


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            return sum(1 for _ in handle)
    except OSError:  # no stash was ever made
        return 0


def _has_remote(common_dir: Path) -> bool:
    try:
        return "[remote " in (common_dir / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:  # unreadable config: offer nothing that needs a remote
        return False


def _read_checkout(paths: RepoPaths) -> Checkout:
    checkout = Checkout()
    text = git_out(["status", "--porcelain=v2", "--branch", "--untracked-files=normal"], paths.root)
    if text is not None:
        _parse_status(text, checkout)
    checkout.operation = _operation(paths.git_dir)
    checkout.stashes = _count_lines(paths.common_dir / "logs" / "refs" / "stash")
    checkout.last_fetch = _stamp(paths.common_dir / "FETCH_HEAD")[0] // 1_000_000_000
    checkout.has_remote = _has_remote(paths.common_dir)
    return checkout


# ------------------------------------------------------------------ cache


@dataclass(slots=True)
class _Entry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    branches: _Branches | None = None
    checkout: Checkout | None = None
    checkout_at: float = 0.0


_guard = threading.Lock()
_entries: dict[str, _Entry] = {}


def forget(folder: str | Path | None = None) -> None:
    """Drop what is remembered (about one folder's repository, or everything)."""
    with _guard:
        if folder is None:
            _entries.clear()
        else:
            _entries.pop(os.path.normcase(str(Path(folder).expanduser())), None)
    if folder is None:
        with _paths_guard:
            _paths.clear()


def read(folder: str | Path, *, fresh: bool = False) -> LocalState | None:
    """The repository ``folder`` is in; None when there is none to read.

    ``fresh`` re-reads everything now (after an action changed the repository).
    The branch rows are copies: callers may annotate them.
    """
    paths = locate(folder)
    if paths is None:
        return None
    key = os.path.normcase(str(paths.root))
    with _guard:
        entry = _entries.setdefault(key, _Entry())
    # One read per repository at a time; a second caller waits and reuses it.
    with entry.lock:
        now = time.monotonic()
        checkout_job = None
        if fresh or entry.checkout is None or now - entry.checkout_at >= STATUS_SHARE_S:
            checkout_job = Job(_read_checkout, paths)
        fingerprint = refs_fingerprint(paths)
        branches = entry.branches
        stale = (
            fresh
            or branches is None
            or branches.fingerprint != fingerprint
            or now - branches.taken_at >= BRANCHES_MAX_AGE_S
        )
        if checkout_job is not None:
            entry.checkout = checkout_job.result()
            entry.checkout_at = time.monotonic()
        checkout = entry.checkout
        assert checkout is not None
        if stale:
            branches = _read_branches(paths, checkout.branch, fingerprint)
            entry.branches = branches
        assert branches is not None
        return LocalState(
            root=paths.root,
            checkout=checkout,
            default_branch=branches.default_branch or checkout.branch,
            base_ref=branches.base_ref,
            branches=[
                LocalBranch(
                    name=row.name,
                    head=row.head,
                    upstream=row.upstream,
                    ahead=row.ahead,
                    behind=row.behind,
                    upstream_gone=row.upstream_gone,
                    committed_at=row.committed_at,
                    worktree=row.worktree,
                    base_ahead=row.base_ahead,
                    base_behind=row.base_behind,
                    merged_into=list(row.merged_into),
                )
                for row in branches.rows
            ],
            remote_heads=branches.remote_heads,
        )


def missing_commits(root: Path, oids: list[str]) -> set[str]:
    """The commits of ``oids`` this computer does not have (so: not fetched yet)."""
    wanted = [oid for oid in dict.fromkeys(oids) if oid]
    if not wanted:
        return set()
    result = run_git(["cat-file", "--batch-check"], root, stdin="\n".join(wanted) + "\n")
    if result is None or result.returncode != 0:
        return set()
    missing: set[str] = set()
    for oid, line in zip(wanted, result.stdout.splitlines(), strict=False):
        if line.rstrip().endswith(" missing"):
            missing.add(oid)
    return missing
