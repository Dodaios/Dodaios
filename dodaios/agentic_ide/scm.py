"""Source control for the Git tab: the working tree, the index and the history.

The Git tab works on the repository of the open workspace the way a person
works in a terminal: read what changed (staged, unstaged, untracked, in
conflict), move files in and out of the index, throw changes away, commit,
stash, switch and create branches and tags, and read the commit graph.

Every call runs the ``git`` CLI at the repository root with prompts switched
off and a timeout, so a credential prompt or a hook that waits never hangs the
app. Reads never take the index lock (``GIT_OPTIONAL_LOCKS=0``): agents run
their own git in the same checkout. Failures are :class:`GitError` with a
sentence for the person and a ``code`` the UI can branch on.

Paths in and out of this module are repository-relative POSIX paths; the route
layer only ever hands in the folder of an open workspace.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from loguru import logger

from dodaios.agentic_ide.git_ops import GitError
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

_READ_TIMEOUT_S = 15.0
_WRITE_TIMEOUT_S = 60.0
# A commit runs the repository's hooks; a push or fetch talks to a server.
_COMMIT_TIMEOUT_S = 300.0
_NETWORK_TIMEOUT_S = 180.0
#: Most files one status answer lists (the rest is reported as ``truncated``).
MAX_STATUS_FILES = 10_000
#: Most commits one graph page returns.
MAX_GRAPH_PAGE = 200
#: Largest file text a commit diff returns per side.
MAX_DIFF_TEXT_BYTES = 2 * 1024 * 1024
#: A commit id, a ref name or ``stash@{n}``: what the UI may name as a revision.
_REVISION = re.compile(r"^(?!-)[A-Za-z0-9._/@{}^~+-]{1,250}$")
_HASH = re.compile(r"^[0-9a-f]{4,64}$")
_UNIT = "\x1f"
_RECORD = "\x1e"

GraphScope = Literal["auto", "all", "current"]


# ------------------------------------------------------------------ plumbing


def _run(
    args: list[str],
    root: Path,
    *,
    timeout: float = _READ_TIMEOUT_S,
    stdin: str | None = None,
    read: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Never block on a credential or editor prompt nobody can see.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_EDITOR"] = "true"
    env["GIT_SEQUENCE_EDITOR"] = "true"
    env["GCM_INTERACTIVE"] = "never"
    if read:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", "-c", "core.quotePath=false", "-c", "color.ui=false", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
            input=stdin if stdin is not None else "",
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
    except FileNotFoundError as exc:
        raise GitError("Git is not installed.", code="missing") from exc
    except subprocess.TimeoutExpired as exc:
        logger.info("Source control: `git {}` did not answer in time in {}", args[0], root)
        raise GitError("Git did not answer in time.", code="timeout") from exc


def _reason(result: subprocess.CompletedProcess[str]) -> str:
    lines = [
        line.strip()
        for line in (result.stderr or result.stdout or "").splitlines()
        if line.strip() and not line.strip().startswith("hint:")
    ]
    return lines[-1] if lines else f"git exited with {result.returncode}"


def _ok(
    args: list[str],
    root: Path,
    *,
    what: str,
    timeout: float = _WRITE_TIMEOUT_S,
    stdin: str | None = None,
    code: str = "failed",
) -> str:
    result = _run(args, root, timeout=timeout, stdin=stdin)
    if result.returncode != 0:
        raise GitError(f"Git could not {what}: {_reason(result)}", code=code)
    return result.stdout


def _read(args: list[str], root: Path, *, timeout: float = _READ_TIMEOUT_S) -> str | None:
    result = _run(args, root, timeout=timeout, read=True)
    return result.stdout if result.returncode == 0 else None


def repository_root(folder: str | Path) -> Path:
    """The top of the repository ``folder`` is in; raises when it is in none."""
    path = Path(folder).expanduser()
    if not path.is_dir():
        raise GitError(f"There is no folder called {path}.", code="no_folder")
    result = _run(["rev-parse", "--show-toplevel"], path, read=True)
    if result.returncode != 0:
        raise GitError(f"{path.name} is not a git repository.", code="not_repo")
    return Path(result.stdout.strip())


def _prefix(folder: Path, root: Path) -> str:
    """The workspace folder's path inside the repository, with a trailing slash."""
    result = _run(["rev-parse", "--show-prefix"], folder, read=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _clean_paths(paths: list[str]) -> list[str]:
    """Repository-relative paths, refusing anything that would leave the repository."""
    cleaned: list[str] = []
    for raw in paths:
        value = (raw or "").strip().replace("\\", "/")
        posix = PurePosixPath(value)
        if (
            not value
            or posix.is_absolute()
            or ".." in posix.parts
            or re.match(r"^[A-Za-z]:", value)
        ):
            raise GitError(f"{raw!r} is not a path inside the repository.", code="invalid")
        cleaned.append(posix.as_posix())
    if not cleaned:
        raise GitError("No files were named.", code="invalid")
    return cleaned


def _pathspec(paths: list[str]) -> str:
    """Paths for ``--pathspec-from-file=-``: NUL separated, matched literally."""
    return "\0".join(paths) + "\0"


_LITERAL = ["--literal-pathspecs"]


def _revision(value: str) -> str:
    value = (value or "").strip()
    if not _REVISION.match(value) or ".." in value:
        raise GitError(f"{value!r} is not a branch, tag or commit.", code="invalid")
    return value


def _branch_name(root: Path, name: str) -> str:
    value = (name or "").strip()
    if not value or value.startswith("-"):
        raise GitError("The branch needs a name.", code="invalid")
    if _run(["check-ref-format", "--branch", value], root, read=True).returncode != 0:
        raise GitError(f"{value!r} is not a valid branch name.", code="invalid")
    return value


def _has_head(root: Path) -> bool:
    return _run(["rev-parse", "--verify", "--quiet", "HEAD"], root, read=True).returncode == 0


# ------------------------------------------------------------------ status


@dataclass(slots=True)
class ScmFile:
    """One changed path in one group of the Source Control list."""

    #: Repository-relative path.
    path: str
    #: The status letter shown beside the file: M A D R C T U I or ``!``.
    letter: str
    #: ``index_modified`` ``modified`` ``untracked`` ``both_modified`` …
    status: str
    #: Where a rename or copy came from.
    original: str = ""


@dataclass(slots=True)
class ScmStatus:
    available: bool
    reason: str = ""
    root: str = ""
    #: The workspace folder's path inside the repository ("" or ``sub/``).
    prefix: str = ""
    branch: str = ""
    head: str = ""
    detached: bool = False
    unborn: bool = False
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    #: ``merge`` | ``rebase`` | ``cherry-pick`` | ``revert`` | ``bisect`` | ""
    operation: str = ""
    remotes: list[str] = field(default_factory=list)
    stashes: int = 0
    merge: list[ScmFile] = field(default_factory=list)
    staged: list[ScmFile] = field(default_factory=list)
    changes: list[ScmFile] = field(default_factory=list)
    truncated: bool = False
    #: The last commit's message, for an amend.
    head_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_INDEX_STATUS = {
    "M": ("M", "index_modified"),
    "T": ("T", "index_type_changed"),
    "A": ("A", "index_added"),
    "D": ("D", "index_deleted"),
    "R": ("R", "index_renamed"),
    "C": ("C", "index_copied"),
}
_TREE_STATUS = {
    "M": ("M", "modified"),
    "T": ("T", "type_changed"),
    "D": ("D", "deleted"),
    "A": ("A", "intent_to_add"),
    "R": ("R", "intent_to_rename"),
}
_CONFLICT_STATUS = {
    "DD": "both_deleted",
    "AU": "added_by_us",
    "UD": "deleted_by_them",
    "UA": "added_by_them",
    "DU": "deleted_by_us",
    "AA": "both_added",
    "UU": "both_modified",
}


def _operation(root: Path) -> str:
    git_dir = _read(["rev-parse", "--git-dir"], root)
    if not git_dir:
        return ""
    path = Path(git_dir.strip())
    if not path.is_absolute():
        path = root / path
    if (path / "rebase-merge").exists() or (path / "rebase-apply").exists():
        return "rebase"
    if (path / "MERGE_HEAD").exists():
        return "merge"
    if (path / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    if (path / "REVERT_HEAD").exists():
        return "revert"
    if (path / "BISECT_LOG").exists():
        return "bisect"
    return ""


def parse_status(text: str, status: ScmStatus) -> None:
    """Fill ``status`` from ``git status --porcelain=v2 -z --branch`` output."""
    records = text.split("\0")
    index = 0
    count = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if record.startswith("# "):
            key, _, value = record[2:].partition(" ")
            if key == "branch.oid":
                status.unborn = value == "(initial)"
                status.head = "" if status.unborn else value
            elif key == "branch.head":
                status.detached = value == "(detached)"
                status.branch = "" if status.detached else value
            elif key == "branch.upstream":
                status.upstream = value
            elif key == "branch.ab":
                parts = value.split()
                if len(parts) == 2:
                    status.ahead = int(parts[0].lstrip("+") or 0)
                    status.behind = int(parts[1].lstrip("-") or 0)
            continue
        if count >= MAX_STATUS_FILES:
            status.truncated = True
            if record[:1] == "2":
                index += 1
            continue
        kind = record[:1]
        if kind == "?":
            status.changes.append(ScmFile(path=record[2:], letter="U", status="untracked"))
            count += 1
        elif kind == "!":
            continue
        elif kind == "u":
            fields = record.split(" ", 10)
            xy, path = fields[1], fields[10]
            status.merge.append(
                ScmFile(path=path, letter="!", status=_CONFLICT_STATUS.get(xy, "both_modified"))
            )
            count += 1
        elif kind in {"1", "2"}:
            limit = 8 if kind == "1" else 9
            fields = record.split(" ", limit)
            xy, path = fields[1], fields[limit]
            original = ""
            if kind == "2":
                original = records[index] if index < len(records) else ""
                index += 1
            x, y = xy[0], xy[1]
            if x in _INDEX_STATUS:
                letter, word = _INDEX_STATUS[x]
                status.staged.append(
                    ScmFile(
                        path=path,
                        letter=letter,
                        status=word,
                        original=original if x in {"R", "C"} else "",
                    )
                )
                count += 1
            if y in _TREE_STATUS:
                letter, word = _TREE_STATUS[y]
                status.changes.append(
                    ScmFile(
                        path=path,
                        letter=letter,
                        status=word,
                        original=original if x not in {"R", "C"} and y == "R" else "",
                    )
                )
                count += 1


def read_status(folder: str | Path) -> ScmStatus:
    """The Source Control list of the repository ``folder`` is in."""
    path = Path(folder).expanduser()
    try:
        root = repository_root(path)
    except GitError as exc:  # not a repository: the Git tab shows the reason instead
        return ScmStatus(available=False, reason=str(exc))
    status = ScmStatus(available=True, root=str(root), prefix=_prefix(path, root))
    result = _run(
        ["status", "--porcelain=v2", "-z", "--branch", "--untracked-files=all", "--find-renames"],
        root,
        read=True,
        timeout=30.0,
    )
    if result.returncode != 0:
        return ScmStatus(
            available=False, reason=f"Git could not read the status: {_reason(result)}"
        )
    parse_status(result.stdout, status)
    status.operation = _operation(root)
    remotes = _read(["remote"], root)
    status.remotes = [line.strip() for line in (remotes or "").splitlines() if line.strip()]
    stashes = _read(["stash", "list", "--format=%gd"], root)
    status.stashes = len([line for line in (stashes or "").splitlines() if line.strip()])
    if not status.unborn:
        status.head_message = (_read(["log", "-1", "--format=%B"], root) or "").strip()
    return status


# ------------------------------------------------------------------ index


def stage(folder: str | Path, paths: list[str]) -> None:
    """Add the named files to the index; a deleted file is staged as deleted."""
    root = repository_root(folder)
    cleaned = _clean_paths(paths)
    _ok(
        [*_LITERAL, "add", "--all", "--pathspec-from-file=-", "--pathspec-file-nul"],
        root,
        what="stage the changes",
        stdin=_pathspec(cleaned),
    )


def stage_all(folder: str | Path, *, tracked_only: bool = False) -> None:
    root = repository_root(folder)
    _ok(["add", "--update" if tracked_only else "--all"], root, what="stage the changes")


def unstage(folder: str | Path, paths: list[str]) -> None:
    """Take the named files out of the index; the working tree keeps them."""
    root = repository_root(folder)
    cleaned = _clean_paths(paths)
    if _has_head(root):
        args = ["restore", "--staged", "--pathspec-from-file=-", "--pathspec-file-nul"]
    else:
        # Nothing committed yet: there is no HEAD to restore from.
        args = ["rm", "--cached", "-r", "--quiet", "--pathspec-from-file=-", "--pathspec-file-nul"]
    _ok([*_LITERAL, *args], root, what="unstage the changes", stdin=_pathspec(cleaned))


def unstage_all(folder: str | Path) -> None:
    root = repository_root(folder)
    if _has_head(root):
        _ok(["reset", "--quiet"], root, what="unstage the changes")
    else:
        _ok(["rm", "--cached", "-r", "--quiet", "."], root, what="unstage the changes")


def _trash(target: Path) -> bool:
    """Move an untracked file to the system trash; False when there is none."""
    from .system_trash import move_to_trash

    try:
        return move_to_trash(target)
    except OSError as exc:
        logger.info("Source control: the trash refused {}: {}", target.name, exc)
        return False


def _remove_untracked(root: Path, rel: str) -> None:
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise GitError(f"{rel} is outside the repository.", code="invalid") from exc
    if not (target.exists() or target.is_symlink()):
        return
    if _trash(target):
        return
    if target.is_dir() and not target.is_symlink():
        raise GitError(f"{rel} is a folder; delete it in the Folder tab.", code="invalid")
    target.unlink()


def discard(folder: str | Path, paths: list[str]) -> None:
    """Throw away the working-tree changes of the named files.

    A tracked file goes back to its staged (or committed) content; an untracked
    one goes to the system trash (deleted for good where there is no trash).
    A file that only exists in the index stays staged.
    """
    root = repository_root(folder)
    cleaned = _clean_paths(paths)
    listed = _run(
        [*_LITERAL, "ls-files", "-z", "--cached", "--", *cleaned], root, read=True
    ).stdout.split("\0")
    tracked = {entry for entry in listed if entry}
    restore = [path for path in cleaned if path in tracked]
    untracked = [path for path in cleaned if path not in tracked]
    if restore:
        _ok(
            [*_LITERAL, "restore", "--worktree", "--pathspec-from-file=-", "--pathspec-file-nul"],
            root,
            what="discard the changes",
            stdin=_pathspec(restore),
        )
    for rel in untracked:
        _remove_untracked(root, rel)


def discard_all(folder: str | Path, *, untracked: bool) -> None:
    """Discard every working-tree change; ``untracked`` also removes new files."""
    root = repository_root(folder)
    if _run(["ls-files", "--cached", "-z"], root, read=True).stdout:
        _ok(["restore", "--worktree", "."], root, what="discard the changes")
    if untracked:
        listed = _read(["ls-files", "-z", "--others", "--exclude-standard"], root) or ""
        for rel in [entry for entry in listed.split("\0") if entry]:
            _remove_untracked(root, rel)


def ignore(folder: str | Path, paths: list[str]) -> str:
    """Append the named files to the repository's ``.gitignore``; returns its path."""
    root = repository_root(folder)
    cleaned = _clean_paths(paths)
    target = root / ".gitignore"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    known = {line.strip() for line in existing.splitlines()}
    lines = [f"/{path}" for path in cleaned if f"/{path}" not in known and path not in known]
    if lines:
        joiner = "" if not existing or existing.endswith("\n") else "\n"
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(joiner + "\n".join(lines) + "\n")
    return ".gitignore"


# ------------------------------------------------------------------ commit


def commit(
    folder: str | Path,
    message: str,
    *,
    amend: bool = False,
    all_changes: bool = False,
    include_untracked: bool = True,
    signoff: bool = False,
    no_verify: bool = False,
    allow_empty: bool = False,
) -> str:
    """Commit the index (or every change, with ``all_changes``). Returns the short id."""
    root = repository_root(folder)
    text = (message or "").strip()
    if not text and not amend:
        raise GitError("The commit needs a message.", code="invalid")
    if all_changes:
        _ok(["add", "--all" if include_untracked else "--update"], root, what="stage the changes")
    nothing = _run(["diff", "--cached", "--quiet"], root).returncode == 0 and _has_head(root)
    if nothing and not amend and not allow_empty:
        raise GitError("There are no staged changes to commit.", code="clean")
    args = ["commit", "--cleanup=strip"]
    if amend:
        args.append("--amend")
    if signoff:
        args.append("--signoff")
    if no_verify:
        args.append("--no-verify")
    if allow_empty:
        args.append("--allow-empty")
    stdin: str | None = None
    if text:
        args.extend(["-F", "-"])
        stdin = text + "\n"
    else:
        args.append("--no-edit")
    _ok(args, root, what="commit", timeout=_COMMIT_TIMEOUT_S, stdin=stdin)
    return _ok(["rev-parse", "--short", "HEAD"], root, what="read the new commit").strip()


def undo_last_commit(folder: str | Path) -> str:
    """Undo the last commit and keep its changes staged; returns its message."""
    root = repository_root(folder)
    if not _has_head(root):
        raise GitError("There is no commit to undo.", code="invalid")
    message = (_read(["log", "-1", "--format=%B"], root) or "").strip()
    if _run(["rev-parse", "--verify", "--quiet", "HEAD~1"], root, read=True).returncode == 0:
        _ok(["reset", "--soft", "HEAD~1"], root, what="undo the last commit")
    else:
        # The first commit has no parent: drop the branch ref, keep the index.
        _ok(["update-ref", "-d", "HEAD"], root, what="undo the last commit")
    return message


def continue_operation(folder: str | Path) -> None:
    """Finish a merge, rebase, cherry-pick or revert once every conflict is staged."""
    root = repository_root(folder)
    operation = _operation(root)
    if not operation or operation == "bisect":
        raise GitError("Nothing is in progress.", code="invalid")
    if operation == "merge":
        _ok(["commit", "--no-edit"], root, what="finish the merge", timeout=_COMMIT_TIMEOUT_S)
        return
    _ok(
        [operation, "--continue"], root, what=f"continue the {operation}", timeout=_COMMIT_TIMEOUT_S
    )


def abort_operation(folder: str | Path) -> None:
    root = repository_root(folder)
    operation = _operation(root)
    if not operation:
        raise GitError("Nothing is in progress.", code="invalid")
    if operation == "bisect":
        _ok(["bisect", "reset"], root, what="end the bisect")
        return
    _ok([operation, "--abort"], root, what=f"abort the {operation}")


# ------------------------------------------------------------------ remotes


def _current_branch(root: Path) -> str:
    return (_read(["symbolic-ref", "--quiet", "--short", "HEAD"], root) or "").strip()


def _upstream(root: Path) -> str:
    return (
        _read(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root) or ""
    ).strip()


def _remotes(root: Path) -> list[str]:
    return [line.strip() for line in (_read(["remote"], root) or "").splitlines() if line.strip()]


def fetch(
    folder: str | Path, *, remote: str = "", prune: bool = False, all_remotes: bool = False
) -> None:
    root = repository_root(folder)
    args = ["fetch"]
    if prune:
        args.append("--prune")
    if all_remotes or not remote:
        args.append("--all")
    else:
        args.append(_remote_name(root, remote))
    _ok(args, root, what="fetch", timeout=_NETWORK_TIMEOUT_S, code="network")


def pull(folder: str | Path, *, rebase: bool = False, remote: str = "", branch: str = "") -> None:
    """Pull into the current branch: fast-forward or merge, or ``rebase``.

    A pull that conflicts leaves the merge or rebase in progress; the conflicts
    then show under Merge Changes, the same as in a terminal.
    """
    root = repository_root(folder)
    if not _current_branch(root):
        raise GitError("Check out a branch before pulling.", code="detached")
    args = ["pull", "--rebase" if rebase else "--no-rebase"]
    if remote:
        args.append(_remote_name(root, remote))
        if branch:
            args.append(_revision(branch))
    elif not _upstream(root):
        raise GitError(
            "This branch has no upstream to pull from. Publish it first.", code="no_upstream"
        )
    _ok(args, root, what="pull", timeout=_NETWORK_TIMEOUT_S, code="network")


def push(
    folder: str | Path,
    *,
    remote: str = "",
    force: bool = False,
    tags: bool = False,
) -> str:
    """Push the current branch; the first push (or ``remote``) sets the upstream."""
    root = repository_root(folder)
    branch = _current_branch(root)
    if not branch:
        raise GitError("Check out a branch before pushing.", code="detached")
    remotes = _remotes(root)
    if not remotes:
        raise GitError("This repository has no remote to push to.", code="no_remote")
    upstream = _upstream(root)
    args = ["push"]
    if force:
        args.append("--force-with-lease")
    if tags:
        args.append("--follow-tags")
    if upstream and not remote:
        _ok(args, root, what="push", timeout=_NETWORK_TIMEOUT_S, code="network")
        return upstream
    target = (
        _remote_name(root, remote) if remote else ("origin" if "origin" in remotes else remotes[0])
    )
    _ok(
        [*args, "--set-upstream", target, branch],
        root,
        what="push",
        timeout=_NETWORK_TIMEOUT_S,
        code="network",
    )
    return f"{target}/{branch}"


def push_tags(folder: str | Path, *, remote: str = "") -> None:
    root = repository_root(folder)
    remotes = _remotes(root)
    if not remotes:
        raise GitError("This repository has no remote to push to.", code="no_remote")
    target = (
        _remote_name(root, remote) if remote else ("origin" if "origin" in remotes else remotes[0])
    )
    _ok(
        ["push", target, "--tags"],
        root,
        what="push the tags",
        timeout=_NETWORK_TIMEOUT_S,
        code="network",
    )


def sync(folder: str | Path, *, rebase: bool = False) -> None:
    """Pull, then push: what the Sync Changes button does."""
    pull(folder, rebase=rebase)
    push(folder)


def _remote_name(root: Path, remote: str) -> str:
    name = (remote or "").strip()
    if name not in _remotes(root):
        raise GitError(f"There is no remote called {name!r}.", code="not_found")
    return name


def add_remote(folder: str | Path, name: str, url: str) -> None:
    root = repository_root(folder)
    value = (name or "").strip()
    address = (url or "").strip()
    if not re.match(r"^[A-Za-z0-9._-]{1,100}$", value):
        raise GitError(
            "The remote needs a name of letters, digits, dots or dashes.", code="invalid"
        )
    if not address or address.startswith("-"):
        raise GitError("The remote needs a URL.", code="invalid")
    _ok(["remote", "add", value, address], root, what="add the remote")


def remove_remote(folder: str | Path, name: str) -> None:
    root = repository_root(folder)
    _ok(["remote", "remove", _remote_name(root, name)], root, what="remove the remote")


# ------------------------------------------------------------------ refs


@dataclass(slots=True)
class Ref:
    #: ``head`` | ``remote`` | ``tag``
    kind: str
    name: str
    commit: str
    date: int
    subject: str
    upstream: str = ""


def list_refs(folder: str | Path) -> dict[str, Any]:
    """Every local branch, remote branch and tag, newest first."""
    root = repository_root(folder)
    text = _read(
        [
            "for-each-ref",
            "--sort=-committerdate",
            f"--format=%(refname){_UNIT}%(objectname:short){_UNIT}%(committerdate:unix)"
            f"{_UNIT}%(contents:subject){_UNIT}%(upstream:short)",
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        ],
        root,
    )
    refs: list[Ref] = []
    for line in (text or "").splitlines():
        parts = line.split(_UNIT)
        if len(parts) < 5:
            continue
        full, commit_id, date, subject, upstream = parts[:5]
        if full.startswith("refs/heads/"):
            kind, name = "head", full[len("refs/heads/") :]
        elif full.startswith("refs/remotes/"):
            kind, name = "remote", full[len("refs/remotes/") :]
            if name.endswith("/HEAD"):
                continue
        elif full.startswith("refs/tags/"):
            kind, name = "tag", full[len("refs/tags/") :]
        else:
            continue
        refs.append(
            Ref(
                kind=kind,
                name=name,
                commit=commit_id,
                date=int(date or 0),
                subject=subject,
                upstream=upstream,
            )
        )
    return {"current": _current_branch(root), "refs": [asdict(ref) for ref in refs]}


def checkout(folder: str | Path, ref: str, *, detached: bool = False) -> str:
    """Switch to a local branch, a remote branch (tracked locally) or a tag/commit."""
    root = repository_root(folder)
    target = _revision(ref)
    local = _run(["show-ref", "--verify", "--quiet", f"refs/heads/{target}"], root, read=True)
    if not detached and local.returncode == 0:
        _ok(["switch", target], root, what=f"switch to {target}")
        return target
    remote = _run(["show-ref", "--verify", "--quiet", f"refs/remotes/{target}"], root, read=True)
    if not detached and remote.returncode == 0:
        name = target.split("/", 1)[1] if "/" in target else target
        exists = _run(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], root, read=True)
        if exists.returncode == 0:
            _ok(["switch", name], root, what=f"switch to {name}")
        else:
            _ok(["switch", "--track", target], root, what=f"check out {target}")
        return name
    _ok(["switch", "--detach", target], root, what=f"check out {target}")
    return target


def create_branch(folder: str | Path, name: str, *, start: str = "", switch: bool = True) -> str:
    root = repository_root(folder)
    branch = _branch_name(root, name)
    base = [_revision(start)] if start else []
    if switch:
        _ok(["switch", "-c", branch, *base], root, what="create the branch")
    else:
        _ok(["branch", branch, *base], root, what="create the branch")
    return branch


def rename_branch(folder: str | Path, name: str, *, old: str = "") -> str:
    root = repository_root(folder)
    branch = _branch_name(root, name)
    args = ["branch", "-m"] + ([_revision(old)] if old else []) + [branch]
    _ok(args, root, what="rename the branch")
    return branch


def delete_branch(folder: str | Path, name: str, *, force: bool = False) -> None:
    root = repository_root(folder)
    branch = _revision(name)
    if branch == _current_branch(root):
        raise GitError("The branch you are on cannot be deleted.", code="current")
    result = _run(["branch", "-D" if force else "-d", branch], root)
    if result.returncode != 0:
        if not force and "not fully merged" in (result.stderr or ""):
            raise GitError(f"{branch} has commits that are on no other branch.", code="unmerged")
        raise GitError(f"Git could not delete the branch: {_reason(result)}")


def merge(folder: str | Path, ref: str) -> str:
    """Merge ``ref`` into the current branch; a conflict leaves the merge open."""
    root = repository_root(folder)
    result = _run(["merge", "--no-edit", _revision(ref)], root, timeout=_COMMIT_TIMEOUT_S)
    if result.returncode != 0:
        if _operation(root) == "merge":
            return "conflict"
        raise GitError(f"Git could not merge: {_reason(result)}")
    return "merged"


def rebase(folder: str | Path, ref: str) -> str:
    """Rebase the current branch onto ``ref``; a conflict leaves the rebase open."""
    root = repository_root(folder)
    result = _run(["rebase", _revision(ref)], root, timeout=_COMMIT_TIMEOUT_S)
    if result.returncode != 0:
        if _operation(root) == "rebase":
            return "conflict"
        raise GitError(f"Git could not rebase: {_reason(result)}")
    return "rebased"


def create_tag(folder: str | Path, name: str, *, message: str = "", ref: str = "") -> None:
    root = repository_root(folder)
    tag = (name or "").strip()
    if (
        not tag
        or tag.startswith("-")
        or _run(["check-ref-format", f"refs/tags/{tag}"], root, read=True).returncode
    ):
        raise GitError(f"{tag!r} is not a valid tag name.", code="invalid")
    args = ["tag"]
    stdin = None
    if message.strip():
        args += ["-a", "-F", "-"]
        stdin = message.strip() + "\n"
    args.append(tag)
    if ref:
        args.append(_revision(ref))
    _ok(args, root, what="create the tag", stdin=stdin)


def delete_tag(folder: str | Path, name: str) -> None:
    root = repository_root(folder)
    _ok(["tag", "-d", _revision(name)], root, what="delete the tag")


def cherry_pick(folder: str | Path, commit_id: str) -> str:
    root = repository_root(folder)
    result = _run(["cherry-pick", _revision(commit_id)], root, timeout=_COMMIT_TIMEOUT_S)
    if result.returncode != 0:
        if _operation(root) == "cherry-pick":
            return "conflict"
        raise GitError(f"Git could not cherry-pick: {_reason(result)}")
    return "picked"


def revert(folder: str | Path, commit_id: str) -> str:
    root = repository_root(folder)
    result = _run(["revert", "--no-edit", _revision(commit_id)], root, timeout=_COMMIT_TIMEOUT_S)
    if result.returncode != 0:
        if _operation(root) == "revert":
            return "conflict"
        raise GitError(f"Git could not revert: {_reason(result)}")
    return "reverted"


# ------------------------------------------------------------------ stash


def list_stashes(folder: str | Path) -> list[dict[str, Any]]:
    root = repository_root(folder)
    text = _read(["stash", "list", f"--format=%gd{_UNIT}%gs{_UNIT}%ct"], root) or ""
    stashes = []
    for line in text.splitlines():
        parts = line.split(_UNIT)
        if len(parts) == 3:
            stashes.append({"ref": parts[0], "message": parts[1], "date": int(parts[2] or 0)})
    return stashes


def _stash_ref(value: str) -> str:
    if not re.match(r"^stash@\{\d{1,5}\}$", value or ""):
        raise GitError(f"{value!r} is not a stash.", code="invalid")
    return value


def stash(
    folder: str | Path, *, message: str = "", include_untracked: bool = False, staged: bool = False
) -> None:
    root = repository_root(folder)
    args = ["stash", "push"]
    if include_untracked:
        args.append("--include-untracked")
    if staged:
        args.append("--staged")
    if message.strip():
        args += ["-m", message.strip()]
    result = _run(args, root, timeout=_WRITE_TIMEOUT_S)
    if result.returncode != 0:
        raise GitError(f"Git could not stash: {_reason(result)}")
    if "No local changes to save" in (result.stdout + result.stderr):
        raise GitError("There are no local changes to stash.", code="clean")


def stash_apply(folder: str | Path, ref: str = "", *, pop: bool = False) -> None:
    root = repository_root(folder)
    args = ["stash", "pop" if pop else "apply", "--index"]
    if ref:
        args.append(_stash_ref(ref))
    result = _run(args, root, timeout=_WRITE_TIMEOUT_S)
    if result.returncode == 0:
        return
    # --index fails when the staged part no longer applies; apply the content alone.
    retry = [part for part in args if part != "--index"]
    _ok(retry, root, what="apply the stash")


def stash_drop(folder: str | Path, ref: str = "", *, everything: bool = False) -> None:
    root = repository_root(folder)
    if everything:
        _ok(["stash", "clear"], root, what="drop the stashes")
        return
    _ok(["stash", "drop", *([_stash_ref(ref)] if ref else [])], root, what="drop the stash")


# ------------------------------------------------------------------ history


@dataclass(slots=True)
class GraphCommit:
    id: str
    parents: list[str]
    author: str
    email: str
    date: int
    refs: list[str]
    subject: str


def _parse_log(text: str) -> list[GraphCommit]:
    commits: list[GraphCommit] = []
    for record in text.split(_RECORD):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_UNIT)
        if len(parts) < 7:
            continue
        commit_id, parents, author, email, date, refs, subject = parts[:7]
        commits.append(
            GraphCommit(
                id=commit_id,
                parents=parents.split(),
                author=author,
                email=email,
                date=int(date or 0),
                refs=[ref.strip() for ref in refs.split(",") if ref.strip()],
                subject=subject,
            )
        )
    return commits


_LOG_FORMAT = f"--format=%H{_UNIT}%P{_UNIT}%an{_UNIT}%ae{_UNIT}%at{_UNIT}%D{_UNIT}%s{_RECORD}"


def graph(
    folder: str | Path, *, scope: GraphScope = "auto", skip: int = 0, limit: int = 50
) -> dict[str, Any]:
    """One page of the commit graph, newest first in topological order.

    ``auto`` shows the current branch with its upstream, ``current`` only the
    branch, ``all`` every branch, remote branch and tag.
    """
    root = repository_root(folder)
    if not _has_head(root):
        return {
            "commits": [],
            "more": False,
            "head": "",
            "incoming": [],
            "outgoing": [],
            "upstream": "",
        }
    size = max(1, min(int(limit), MAX_GRAPH_PAGE))
    upstream = _upstream(root)
    if scope == "all":
        revs = ["--branches", "--remotes", "--tags", "HEAD"]
    elif scope == "current" or not upstream:
        revs = ["HEAD"]
    else:
        revs = ["HEAD", upstream]
    text = _read(
        [
            "log",
            "--topo-order",
            "--decorate=full",
            _LOG_FORMAT,
            f"--skip={max(0, int(skip))}",
            f"-n{size + 1}",
            *revs,
            "--",
        ],
        root,
        timeout=30.0,
    )
    commits = _parse_log(text or "")
    head = (_read(["rev-parse", "HEAD"], root) or "").strip()
    incoming: list[str] = []
    outgoing: list[str] = []
    if upstream:
        incoming = (_read(["rev-list", "--max-count=500", f"HEAD..{upstream}"], root) or "").split()
        outgoing = (_read(["rev-list", "--max-count=500", f"{upstream}..HEAD"], root) or "").split()
    return {
        "commits": [asdict(entry) for entry in commits[:size]],
        "more": len(commits) > size,
        "head": head,
        "upstream": upstream,
        "incoming": incoming,
        "outgoing": outgoing,
    }


_NAME_STATUS = {"M": "M", "A": "A", "D": "D", "R": "R", "C": "C", "T": "T", "U": "!"}


def commit_details(folder: str | Path, commit_id: str) -> dict[str, Any]:
    """A commit's full message and the files it changed against its first parent."""
    root = repository_root(folder)
    rev = _revision(commit_id)
    meta = _read(
        [
            "show",
            "-s",
            f"--format=%H{_UNIT}%P{_UNIT}%an{_UNIT}%ae{_UNIT}%at{_UNIT}%cn{_UNIT}%ct{_UNIT}%B",
            rev,
        ],
        root,
    )
    if meta is None:
        raise GitError(f"There is no commit {commit_id!r}.", code="not_found")
    parts = meta.split(_UNIT, 7)
    full, parents = parts[0], parts[1].split()
    if parents:
        args = ["diff-tree", "-r", "-z", "-M", "--name-status", parents[0], full]
    else:
        args = ["diff-tree", "--no-commit-id", "-r", "-z", "-M", "--name-status", "--root", full]
    listed = (_read(args, root) or "").split("\0")
    files: list[dict[str, str]] = []
    index = 0
    while index < len(listed):
        code = listed[index]
        index += 1
        if not code:
            continue
        letter = _NAME_STATUS.get(code[0], code[0])
        if letter in {"R", "C"}:
            original, path = listed[index], listed[index + 1]
            index += 2
        else:
            original, path = "", listed[index]
            index += 1
        files.append({"path": path, "letter": letter, "original": original})
    stat = _read(
        ["diff", "--shortstat", parents[0], full]
        if parents
        else ["show", "--shortstat", "--format=", full],
        root,
    )
    return {
        "id": full,
        "parents": parents,
        "author": parts[2],
        "email": parts[3],
        "date": int(parts[4] or 0),
        "committer": parts[5],
        "committer_date": int(parts[6] or 0),
        "message": parts[7].strip() if len(parts) > 7 else "",
        "files": files,
        "stat": (stat or "").strip(),
    }


def _blob_text(root: Path, rev: str, path: str) -> tuple[str | None, bool]:
    """A file's text at ``rev`` (None when it does not exist there) and whether it is binary."""
    if not rev:
        return None, False
    size = _read(["cat-file", "-s", f"{rev}:{path}"], root)
    if size is None:
        return None, False
    if int(size.strip() or 0) > MAX_DIFF_TEXT_BYTES:
        return "", True
    result = _run(["show", f"{rev}:{path}"], root, read=True)
    if result.returncode != 0:
        return None, False
    text = result.stdout
    if "\0" in text:
        return "", True
    return text.removeprefix("﻿"), False


def commit_file_diff(
    folder: str | Path, commit_id: str, path: str, *, original: str = ""
) -> dict[str, Any]:
    """The two sides of one file in a commit: its first parent's text and the commit's."""
    root = repository_root(folder)
    rev = _revision(commit_id)
    (rel,) = _clean_paths([path])
    before_path = _clean_paths([original])[0] if original else rel
    parents = (_read(["rev-list", "--parents", "-n1", rev], root) or "").split()[1:]
    before, binary_before = _blob_text(root, parents[0] if parents else "", before_path)
    after, binary_after = _blob_text(root, rev, rel)
    return {
        "path": rel,
        "original_path": before_path,
        "before": before,
        "after": after,
        "binary": binary_before or binary_after,
    }


def session_file_diff(folder: str | Path, path: str, base: str) -> dict[str, Any]:
    """One file an agent session changed: its text at ``base`` and on disk now.

    ``path`` is relative to the session's folder (the workspace, or the pane's
    own worktree); ``base`` is the commit before the session's first change.
    """
    from dodaios.agentic_ide import git_changes

    root = Path(folder).expanduser()
    try:
        rel = git_changes.normalize_workspace_path(root, path)
        before = git_changes.head_text(root, rel, base)
    except ValueError as exc:
        raise GitError(str(exc), code="invalid") from exc
    target = root / rel
    after: str | None = None
    binary = False
    if target.is_file():
        if target.stat().st_size > MAX_DIFF_TEXT_BYTES:
            binary = True
        else:
            data = target.read_bytes()
            if b"\0" in data:
                binary = True
            else:
                after = data.decode("utf-8", errors="replace").removeprefix("\ufeff")
    if before is not None and "\0" in before:
        binary = True
    return {"path": rel, "before": before, "after": after, "binary": binary}
