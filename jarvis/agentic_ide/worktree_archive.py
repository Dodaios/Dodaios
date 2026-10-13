"""Put a linked worktree away without losing what was in it, and bring it back.

Removing a worktree with uncommitted work discards that work. Archiving saves
it first: every tracked change and every untracked file that is not ignored is
written into one snapshot commit, kept under a ref of its own, and only then is
the checkout removed. The branch and its commits stay where they are.
Restoring recreates the checkout at its old path and puts the saved files back
as uncommitted changes.

Ignored files (build output, virtual environments, ``.env``) are not part of a
snapshot; they are not part of the repository either.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from . import git_ops
from .git_ops import GitError, Prepared

#: Snapshots live outside ``refs/heads`` so they never show up as branches.
ARCHIVE_REF_PREFIX = "refs/dodaios/archived-worktrees/"
_SUBJECT_MARK = "archived-worktree "
# The snapshot is made by the app, also on a machine with no git identity set.
_SNAPSHOT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Dodaios",
    "GIT_AUTHOR_EMAIL": "worktree-archive@dodaios.invalid",
    "GIT_COMMITTER_NAME": "Dodaios",
    "GIT_COMMITTER_EMAIL": "worktree-archive@dodaios.invalid",
}


@dataclass(slots=True)
class ArchivedWorktree:
    """One worktree that was put away and can be restored."""

    name: str
    branch: str
    path: str
    #: The commit the worktree was on when it was archived.
    head: str
    archived_at: int
    #: Whether the snapshot holds work that was never committed.
    uncommitted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _git(args: list[str], cwd: Path, *, what: str = "", env: dict[str, str] | None = None) -> str:
    """Run git like :func:`git_ops._ok`, optionally with extra environment."""
    return git_ops._ok(args, cwd, what=what, extra_env=env)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.") or "worktree"


def _main_root(folder: str | Path) -> tuple[Path, git_ops.RepoInfo]:
    path = git_ops._folder(folder)
    info = git_ops.inspect(path)
    if not info.is_repo:
        raise GitError(f"{path.name} is not a git repository.", code="not_repo")
    return Path(info.main_root or info.root), info


def _find_tree(info: git_ops.RepoInfo, worktree: str) -> git_ops.Worktree:
    """The linked worktree named by its path, its folder name or its branch."""
    wanted = str(worktree or "").strip()
    if not wanted:
        raise GitError("Name the worktree by its branch or its folder.", code="invalid")
    linked = [tree for tree in info.worktrees if not tree.main]
    for tree in linked:
        if git_ops._same_path(tree.path, wanted):
            return tree
    branch = git_ops.normalize_branch(wanted)
    matches = [
        tree for tree in linked
        if tree.branch == branch or Path(tree.path).name.casefold() == wanted.casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if any(tree.main and (tree.branch == branch or git_ops._same_path(tree.path, wanted))
           for tree in info.worktrees):
        raise GitError("The main checkout cannot be archived.", code="invalid")
    names = ", ".join(tree.branch or Path(tree.path).name for tree in linked) or "none"
    raise GitError(
        f"No linked worktree is called {wanted}. Linked worktrees: {names}.", code="not_found"
    )


def archive(folder: str | Path, worktree: str, *, open_folders: list[str]) -> ArchivedWorktree:
    """Save everything in a linked worktree to a snapshot, then remove the checkout."""
    main_root, info = _main_root(folder)
    tree = _find_tree(info, worktree)
    tree_path = Path(tree.path)
    if git_ops.worktree_in_use(tree_path, open_folders):
        raise GitError(
            "A workspace or agent is still open in this worktree. Close it first.", code="in_use"
        )
    if not tree_path.is_dir():
        raise GitError(
            f"The folder {tree_path} is gone; there is nothing to save.", code="prunable"
        )
    if tree.locked:
        raise GitError("This worktree is locked and stays where it is.", code="locked")
    head = _git(["rev-parse", "HEAD"], tree_path, what="read the worktree").strip()
    head_tree = _git(["rev-parse", "HEAD^{tree}"], tree_path).strip()
    with tempfile.TemporaryDirectory(prefix="worktree-archive-") as scratch:
        # A private index: the worktree's own staging area is left untouched.
        index = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        _git(["read-tree", "HEAD"], tree_path, env=index, what="snapshot the worktree")
        _git(["add", "--all"], tree_path, env=index, what="snapshot the worktree")
        saved_tree = _git(["write-tree"], tree_path, env=index).strip()
    stamp = int(time.time())
    label = tree.branch or tree_path.name
    entry = ArchivedWorktree(
        name=f"{_slug(label)}-{stamp}",
        branch=tree.branch,
        path=str(tree_path),
        head=head,
        archived_at=stamp,
        uncommitted=saved_tree != head_tree,
    )
    subject = _SUBJECT_MARK + json.dumps(
        {"branch": entry.branch, "path": entry.path}, ensure_ascii=True
    )
    commit = _git(
        ["commit-tree", saved_tree, "-p", head, "-m", subject],
        main_root, env=_SNAPSHOT_IDENTITY, what="save the snapshot",
    ).strip()
    # The listing reads the time from the snapshot itself; report the same one.
    written = _git(["show", "-s", "--format=%ct", commit], main_root).strip()
    entry.archived_at = int(written) if written.isdigit() else stamp
    ref = ARCHIVE_REF_PREFIX + entry.name
    _git(["update-ref", ref, commit], main_root, what="save the snapshot")
    try:
        _git(["worktree", "remove", "--force", str(tree_path)], main_root,
             what="remove the worktree")
    except GitError as exc:
        # The work is saved either way; say so, and keep the snapshot.
        raise GitError(
            f"{exc} The snapshot {entry.name} was saved and the worktree is still there.",
            code="not_removed",
        ) from exc
    logger.info("Agentic IDE git: archived worktree {} as {}", tree_path, entry.name)
    return entry


def archived(folder: str | Path) -> list[ArchivedWorktree]:
    """Every archived worktree of ``folder``'s repository, newest first."""
    main_root, _info = _main_root(folder)
    listing = git_ops._run(
        [
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname)%09%(parent)%09%(committerdate:unix)%09%(tree)%09%(contents:subject)",
            ARCHIVE_REF_PREFIX,
        ],
        main_root,
    )
    if listing.returncode != 0:
        return []
    entries: list[ArchivedWorktree] = []
    for line in listing.stdout.splitlines():
        ref, parent, stamp, saved_tree, subject = ([*line.split("\t", 4), "", "", "", ""])[:5]
        if not ref.startswith(ARCHIVE_REF_PREFIX) or not subject.startswith(_SUBJECT_MARK):
            continue
        try:
            meta = json.loads(subject[len(_SUBJECT_MARK):])
        except ValueError:  # a ref someone else put here: not one of ours
            continue
        head = parent.split(" ")[0]
        head_tree = git_ops._run(["rev-parse", f"{head}^{{tree}}"], main_root)
        entries.append(
            ArchivedWorktree(
                name=ref[len(ARCHIVE_REF_PREFIX):],
                branch=str(meta.get("branch") or ""),
                path=str(meta.get("path") or ""),
                head=head,
                archived_at=int(stamp) if stamp.isdigit() else 0,
                uncommitted=head_tree.returncode != 0 or head_tree.stdout.strip() != saved_tree,
            )
        )
    return entries


def _find_archived(entries: list[ArchivedWorktree], name: str) -> ArchivedWorktree:
    wanted = str(name or "").strip()
    if not wanted:
        raise GitError("Name the archived worktree by its name or branch.", code="invalid")
    exact = [entry for entry in entries if entry.name == wanted]
    branch = git_ops.normalize_branch(wanted)
    matches = exact or [
        entry for entry in entries
        if entry.branch == branch or Path(entry.path).name.casefold() == wanted.casefold()
    ]
    if not matches:
        known = ", ".join(entry.name for entry in entries) or "none"
        raise GitError(
            f"No archived worktree is called {wanted}. Archived: {known}.", code="not_found"
        )
    # The same branch may have been archived more than once: the newest wins.
    return matches[0]


def restore(folder: str | Path, name: str) -> Prepared:
    """Recreate an archived worktree at its old path with its saved files."""
    main_root, info = _main_root(folder)
    entry = _find_archived(archived(main_root), name)
    target = Path(entry.path)
    if target.exists():
        raise GitError(
            f"The folder {target} exists again; move it away before restoring.", code="exists"
        )
    ref = ARCHIVE_REF_PREFIX + entry.name
    branch = next((b for b in info.branches if entry.branch and b.name == entry.branch), None)
    tip = (
        git_ops._run(["rev-parse", f"refs/heads/{entry.branch}"], main_root).stdout.strip()
        if branch else ""
    )
    # The saved files belong on top of the commit they were made on. A branch
    # that moved on, is open elsewhere or is gone gets a detached checkout there.
    on_branch = bool(branch) and not branch.worktree and tip == entry.head
    if git_ops._inside(target, main_root / git_ops.WORKTREE_DIR):
        git_ops._exclude_worktree_dir(main_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    add = ["worktree", "add", str(target), entry.branch] if on_branch else [
        "worktree", "add", "--detach", str(target), entry.head,
    ]
    _git(add, main_root, what="recreate the worktree")
    if entry.uncommitted:
        # Working files only: the saved changes come back uncommitted, as they
        # were, and files that had been untracked are untracked again.
        _git(["restore", f"--source={ref}", "--worktree", "--", "."], target,
             what="put the saved files back")
    _git(["update-ref", "-d", ref], main_root, what="clear the snapshot")
    logger.info("Agentic IDE git: restored worktree {} from {}", target, entry.name)
    if on_branch:
        message = f"Restored {entry.branch} to {target}."
    elif entry.branch:
        message = (
            f"Restored to {target} at the commit it was archived on, not on {entry.branch}: "
            "that branch moved on, is open elsewhere or no longer exists."
        )
    else:
        message = f"Restored to {target} at the commit it was archived on."
    return Prepared(
        folder=str(target), branch=entry.branch if on_branch else "", created=True,
        message=message,
    )


__all__ = ["ARCHIVE_REF_PREFIX", "ArchivedWorktree", "archive", "archived", "restore"]
