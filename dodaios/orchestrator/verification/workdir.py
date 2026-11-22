"""A checkout of its own for every coding thread the lead starts.

A thread used to run in its project's folder, next to every other thread of
that project. What one run changed could then not be told from what its
neighbours changed, and the output scan had nothing it could pin on a run. With
``[rsi] worktree_per_run`` (on by default once the output scan is on) the app
makes a linked worktree on a new branch for each new thread the lead opens:
``<repo>/.worktrees/agent-<name>-<id>``, started from the remote default branch
when the repository has one, else from the checked-out commit.

Rules that keep this safe:

* **It never fails the order.** No repository, a repository that opted out, a
  project that is a sub-folder or itself a worktree, too little free disk, a
  git error: the thread opens in the project folder as before and the run is
  recorded as sharing its checkout.
* **Nothing with work in it is ever removed.** Only a worktree without an
  uncommitted or untracked file is put away, and its commits stay on their
  branch. That happens to the worktree of a deleted thread, and to the one of a
  thread nobody wrote to for :data:`REST_AFTER_MS` (sooner when the disk is
  nearly full): a worktree is some hundred megabytes, and threads live long.
* **A thread finds its folder again.** A worktree put away while its thread
  rested is made again at the same path, on the branch it was on, before the
  thread's next turn starts (:func:`restore`, called by the chat service).
  That also holds after the setting was switched off.
* **The brief follows the folder.** An absolute path into the project folder in
  the lead's brief is rewritten to the same file in the worktree, and two lines
  say where the agent is.

Putting away happens when the next worktree of that repository is made, never
on a timer. Every call here blocks on ``git``: call it off the event loop.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "BRANCH_PREFIX",
    "MIN_FREE_BYTES",
    "REST_AFTER_MS",
    "WorkDir",
    "WorkDirs",
    "away",
    "bind",
    "dirs",
    "for_new_thread",
    "localize",
    "restore",
    "set_dirs",
]

BRANCH_PREFIX: Final[str] = "agent/"
#: Below this much free space no worktree is made: a full disk stops every agent.
MIN_FREE_BYTES: Final[int] = 2 * 1024**3
#: A clean worktree is put away when its thread got no message for this long ...
REST_AFTER_MS: Final[int] = 12 * 60 * 60 * 1000
#: ... or for this long, while less than twice :data:`MIN_FREE_BYTES` is free.
REST_AFTER_TIGHT_MS: Final[int] = 60 * 60 * 1000
#: One fetch of the default branch serves every worktree made this soon after it.
_FETCH_TTL_S: Final[float] = 60.0
_FETCH_TIMEOUT_S: Final[float] = 12.0
#: A repository's worktrees are looked through at most this often.
_SWEEP_TTL_S: Final[float] = 60.0
#: A worktree made for a thread that never came to exist is removed after this long.
_UNBOUND_GRACE_MS: Final[int] = 60 * 60 * 1000
_ADD_TIMEOUT_S: Final[float] = 180.0
_SLUG = re.compile(r"[^a-z0-9]+")
#: Folders inside a project that are not the project's files: other checkouts, git's own.
_NOT_PROJECT_FILES = r"(?![/\\](?:\.worktrees|\.git|\.claude[/\\]worktrees)(?:[/\\]|\b))"


@dataclass(frozen=True, slots=True)
class WorkDir:
    """A worktree the app made for one thread."""

    folder: str
    branch: str
    base_sha: str
    repo_id: str
    #: The project folder the thread would have run in.
    project: str


def _slug(label: str) -> str:
    text = _SLUG.sub("-", (label or "").lower()).strip("-")
    return text[:32].strip("-") or "task"


def _is_main_folder(project_folder: str, root: Path) -> bool:
    """True when the project folder is the main checkout of its repository.

    The thread list places a thread by its folder, and a worktree lands in
    ``<main checkout>/.worktrees``: only then does it lie inside the project.
    """
    from dodaios.self_build.code import gitcmd

    common = gitcmd.out(["rev-parse", "--path-format=absolute", "--git-common-dir"], root)
    if not common:
        return False
    try:
        main = Path(common).parent.resolve()
        return main == root.resolve() == Path(project_folder).expanduser().resolve()
    except OSError:  # a folder that cannot be resolved is no place to make a worktree in
        return False


def localize(prompt: str, made: WorkDir) -> str:
    """The brief for a thread that runs in ``made``: its paths, and where it is.

    Absolute paths into the project folder become the same paths in the
    worktree, so a file the lead named is opened where the agent works.
    """
    text = prompt or ""
    project = made.project.rstrip("/\\")
    if project and project != made.folder.rstrip("/\\"):
        # Only as a whole folder name ("/code/notes" must not rewrite
        # "/code/notes-old"), and never a path into another checkout.
        pattern = re.compile(
            re.escape(project) + _NOT_PROJECT_FILES + r"(?=[/\\\s`'\")\]:,;]|\.(?:\s|$)|$)"
        )
        text = pattern.sub(lambda _m: made.folder, text)
    return (
        f"{text}\n\nYou work in a git worktree of your own, on the new branch "
        f"`{made.branch}`: {made.folder}\n"
        f"Other agents work in the main checkout {project} at the same time, so make your "
        "changes here."
    )


class WorkDirs:
    """Makes, records, puts away and restores the worktrees of delegated coding threads."""

    def __init__(
        self,
        store: Any,
        *,
        thread_exists: Callable[[str], bool] = lambda _sid: True,
        idle_ms: Callable[[str], int] = lambda _sid: 0,
        shared: Iterable[str] = (),
        making: bool = True,
        free_bytes: Callable[[str], int] | None = None,
        now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    ) -> None:
        self._store = store
        self._thread_exists = thread_exists
        #: How long a thread got no message; ``0`` while one of its turns runs.
        self._idle_ms = idle_ms
        self._shared = {str(repo).strip().lower() for repo in shared if str(repo).strip()}
        #: ``False``: the setting is off; worktrees made earlier are still restored.
        self._making = making
        self._free_bytes = free_bytes or (lambda folder: shutil.disk_usage(folder).free)
        self._now_ms = now_ms
        self._fetched: dict[str, float] = {}
        self._swept: dict[str, float] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- make

    def make(self, project_folder: str, label: str) -> WorkDir | None:
        """A fresh worktree for a new thread in ``project_folder``, or ``None``.

        ``None`` always means "run in the project folder as before"; the reason
        is logged.
        """
        if not self._making:
            return None
        try:
            return self._make(project_folder, label)
        except Exception as exc:  # noqa: BLE001 - a worktree is a convenience; the order goes on
            log.warning("workdir: no worktree for %s (%s)", project_folder, exc)
            return None

    def _make(self, project_folder: str, label: str) -> WorkDir | None:
        from dodaios.agentic_ide import git_ops
        from dodaios.rsi import repo_identity

        root = git_ops.repo_root(project_folder)
        if root is None:
            return None
        if not _is_main_folder(project_folder, root):
            log.info("workdir: %s is not its repository's main folder and keeps it", project_folder)
            return None
        repo = repo_identity.repo_id(root)
        if repo.lower() in self._shared:
            log.info("workdir: %s keeps its shared checkout by setting", repo)
            return None
        if self._due(self._swept, str(root), _SWEEP_TTL_S):
            self.sweep(repo, str(root))
        if self._free_bytes(str(root)) < MIN_FREE_BYTES:
            log.warning("workdir: too little free disk for a worktree of %s", repo)
            return None
        base_sha = self._base(root)
        if not base_sha:
            return None  # a repository without a commit has nothing to branch from
        branch = f"{BRANCH_PREFIX}{_slug(label)}-{uuid.uuid4().hex[:6]}"
        prepared = git_ops.prepare(root, "new_worktree", branch=branch, base=base_sha)
        made = WorkDir(
            folder=str(prepared.folder),
            branch=prepared.branch or branch,
            base_sha=base_sha,
            repo_id=repo,
            project=str(project_folder),
        )
        self._store.add_workdir(
            made.folder, repo_id=repo, root=str(root), branch=made.branch, base_sha=base_sha,
            created_ms=self._now_ms(),
        )
        log.info("workdir: %s on %s for %r", made.folder, made.branch, label)
        return made

    def _due(self, seen: dict[str, float], key: str, ttl_s: float) -> bool:
        """True, and noted, when ``key`` was not handled within ``ttl_s``."""
        now = time.monotonic()
        with self._lock:
            if now - seen.get(key, -ttl_s) < ttl_s:
                return False
            seen[key] = now
            return True

    def _base(self, root: Path) -> str:
        """The commit a new worktree starts from: the remote default branch, else ``HEAD``."""
        from dodaios.self_build.code import gitcmd
        from dodaios.self_build.code.brief import default_branch

        if gitcmd.out(["remote", "get-url", "origin"], root):
            branch = default_branch(root)
            if branch and self._due(self._fetched, str(root), _FETCH_TTL_S):
                # Best effort: offline, the last fetched state is the base.
                gitcmd.git(["fetch", "origin", branch], root, timeout=_FETCH_TIMEOUT_S)
            remote = gitcmd.out(
                ["rev-parse", "--verify", "--quiet", f"origin/{branch}^{{commit}}"], root
            )
            if remote:
                return remote
        return gitcmd.out(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], root)

    def bind(self, made: WorkDir, session_id: str) -> None:
        """Remember which thread runs in ``made``."""
        self._store.bind_workdir(made.folder, session_id)

    # ---------------------------------------------------------------- sweep

    def sweep(self, repo_id: str, repo_root: str) -> list[str]:
        """Put away the clean worktrees nobody works in. Returns their folders.

        A worktree is put away when its thread was deleted, or when its thread
        rested long enough (:data:`REST_AFTER_MS`). One with an uncommitted or
        untracked file always stays.
        """
        from dodaios.agentic_ide import git_ops
        from dodaios.self_build.code import gitcmd

        removed: list[str] = []
        now = self._now_ms()
        tight = self._free_bytes(repo_root) < 2 * MIN_FREE_BYTES
        rest_after = REST_AFTER_TIGHT_MS if tight else REST_AFTER_MS
        for row in self._store.workdirs(repo_id=repo_id):
            folder = str(row["folder"])
            session_id = str(row["session_id"] or "")
            if session_id:
                gone = not self._thread_exists(session_id)
                if not gone and self._idle_ms(session_id) < rest_after:
                    continue
            else:
                gone = True
                if now - int(row["created_ms"] or 0) < _UNBOUND_GRACE_MS:
                    continue  # its thread may still be on its way
            if not Path(folder).is_dir():
                self._store.close_workdir(folder, now)
                continue
            # What it is on now: the agent may have renamed or switched its branch.
            branch = gitcmd.out(["symbolic-ref", "--quiet", "--short", "HEAD"], folder)
            head = gitcmd.out(["rev-parse", "--verify", "--quiet", "HEAD^{commit}"], folder)
            try:
                # Refuses a worktree with uncommitted or untracked work.
                git_ops.remove_worktree(repo_root, folder)
            except git_ops.GitError as exc:
                log.info("workdir: %s kept (%s)", folder, exc)
                continue
            self._store.close_workdir(folder, now, branch=branch, head_sha=head)
            removed.append(folder)
            if gone and branch and head and head == str(row["base_sha"] or ""):
                # Nothing was committed on it: the branch holds no work.
                gitcmd.git(["branch", "-D", branch], repo_root)
        if removed:
            log.info("workdir: put away %d worktree(s) of %s", len(removed), repo_id)
        return removed

    # -------------------------------------------------------------- restore

    def restore(self, folder: str) -> bool:
        """Make a worktree that was put away again, where and as it was.

        ``True`` when the folder exists again. A folder this module never made,
        or one that is there, is left alone.
        """
        try:
            return self._restore(folder)
        except Exception:  # noqa: BLE001 - the turn then reports its missing folder itself
            log.warning("workdir: %s could not be restored", folder, exc_info=True)
            return False

    def _restore(self, folder: str) -> bool:
        from dodaios.self_build.code import gitcmd

        row = self._store.workdir(folder)
        if row is None or Path(folder).exists():
            return False
        root = Path(str(row["root"] or ""))
        if not root.is_dir():
            return False
        gitcmd.git(["worktree", "prune"], root)
        branch = str(row["branch"] or "")
        head = str(row["head_sha"] or row["base_sha"] or "")
        has_branch = bool(branch) and gitcmd.git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], root
        ).ok
        attempts: list[list[str]] = []
        if has_branch:
            attempts.append(["worktree", "add", folder, branch])
        elif branch and head:
            attempts.append(["worktree", "add", "-b", branch, folder, head])
        if head:
            # The branch is checked out elsewhere by now, or its name is taken.
            attempts.append(["worktree", "add", "--detach", folder, head])
        fresh = self._base(root)
        if fresh:
            attempts.append(["worktree", "add", "--detach", folder, fresh])
        for args in attempts:
            done = gitcmd.git(args, root, timeout=_ADD_TIMEOUT_S)
            if done.ok:
                self._store.reopen_workdir(folder)
                log.info("workdir: %s restored (%s)", folder, " ".join(args[2:-1]) or "branch")
                return True
            log.info("workdir: restoring %s: %s", folder, done.tail(300))
        return False


# ----------------------------------------------------------- process wiring

_dirs: WorkDirs | None = None


def dirs() -> WorkDirs | None:
    """The process instance, or ``None`` when the app never made a worktree."""
    return _dirs


def set_dirs(value: WorkDirs | None) -> None:
    """Replace the process instance (tests, an embedding host)."""
    global _dirs
    _dirs = value


def for_new_thread(project_folder: str, label: str) -> WorkDir | None:
    """A worktree for a thread about to be opened in ``project_folder``, or ``None``."""
    current = _dirs
    return current.make(project_folder, label) if current is not None else None


def bind(made: WorkDir | None, session_id: str) -> None:
    """Tie ``made`` to the thread that runs in it. A no-op for ``None``."""
    current = _dirs
    if current is None or made is None:
        return
    try:
        current.bind(made, session_id)
    except Exception:  # noqa: BLE001 - an unbound worktree is removed later; the thread runs
        log.warning("workdir: %s not bound to its thread", made.folder, exc_info=True)


def away(folder: str) -> bool:
    """True when ``folder`` is missing and this module may be able to restore it.

    One ``stat``: cheap enough for the chat service to ask before every turn.
    """
    return _dirs is not None and bool(folder) and not os.path.isdir(folder)


def restore(folder: str) -> bool:
    """Make the worktree at ``folder`` again when the app made it and put it away."""
    current = _dirs
    return current.restore(folder) if current is not None else False
