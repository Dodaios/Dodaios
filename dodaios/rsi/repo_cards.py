"""Gather what the repository index says, without making the lead's turn wait.

Two kinds of fact go into the index (:mod:`repo_index`):

* **Slow facts** need ``git`` or GitHub: which repository a folder belongs to
  (so a worktree counts for its repository), whether a main checkout has
  uncommitted changes or conflicts, and the open pull requests with their
  checks (one GitHub call for all repositories, at most once a minute, only
  while a repository on GitHub is in play). They are read by a background
  refresh, started when a coding thread's turn ends or the index is first
  asked for, and kept in memory. Nothing is polled.
* **Fast facts** are in the app's own memory or one indexed query: which
  coding threads are working, which wait for the person, and which
  repositories this conversation handed work to last. They are read when the
  index is rendered.

So rendering never starts a ``git`` process and never touches the network. The
price is that a slow fact can be one refresh behind.

The board keeps a revision that rises only when the rendered content changes,
and remembers per conversation what it last sent, so a CLI seat is handed the
index only when it differs from what its conversation already holds.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final

from . import repo_identity
from .repo_index import RepoState, body_digest, in_play, render

log = logging.getLogger(__name__)

__all__ = ["RepoBoard", "board", "cli_note", "install", "set_board", "turn_context_note"]

#: Repositories this conversation handed work to that stay "in play".
RECENT_REPOS: Final[int] = 5
#: A conversation is handed the unchanged index again after this many turns,
#: so it is still there once older turns were compacted away.
RESEND_EVERY: Final[int] = 20
#: Two refreshes are at least this far apart.
MIN_REFRESH_GAP_S: Final[float] = 3.0
#: GitHub is asked about open pull requests at most this often.
PULL_REQUESTS_TTL_S: Final[float] = 60.0
_THREAD_SURFACE: Final[str] = "agent"
_SESSIONS_READ: Final[int] = 200
_JOBS_READ: Final[int] = 40

Project = tuple[str, str]  # (name, folder)


def _list_projects() -> list[Project]:
    from dodaios.agentic_ide import library

    return [(project.name, str(project.path)) for project in library.list_projects()]


def _git_state(folder: str) -> tuple[bool, bool]:
    """``(dirty, conflict)`` of a checkout; both ``False`` when it cannot be read."""
    from dodaios.agentic_ide import git_ops

    state = git_ops.brief(folder) or {}
    return bool(state.get("changed_files")), bool(state.get("conflicted"))


#: ``(prs, failing, running, in conflict)`` of one repository's open pull requests.
PullRequestCounts = tuple[int, int, int, bool]


def _pull_requests() -> dict[str, PullRequestCounts] | None:
    """The person's open pull requests per repository id; ``None`` when GitHub says nothing."""
    from dodaios.agentic_ide import github_link

    cred = github_link.credential()
    if cred is None:
        return None
    try:
        _login, mine, _review = github_link.open_pull_requests(cred)
    except github_link.GitHubError as exc:
        log.info("repo board: no pull requests read (%s)", exc)
        return None
    counts: dict[str, list[Any]] = {}
    for row in mine:
        repo = f"github.com/{row.repo.lower()}"
        entry = counts.setdefault(repo, [0, 0, 0, False])
        entry[0] += 1
        entry[1] += row.checks == "failing"
        entry[2] += row.checks == "running"
        entry[3] = entry[3] or row.conflicts
    return {repo: (n, failing, running, conflict) for repo, (n, failing, running, conflict)
            in counts.items()}


def _recent_jobs(owner_session: str) -> list[Any]:
    from dodaios.orchestrator import jobs

    return jobs.get_ledger().recent(owner_session=owner_session, limit=_JOBS_READ)


class RepoBoard:
    """The slow facts of every known repository, and the index rendered from them."""

    def __init__(
        self,
        service: Any,
        *,
        projects: Callable[[], list[Project]] = _list_projects,
        repo_of: Callable[[str], str] = repo_identity.repo_id,
        git_state: Callable[[str], tuple[bool, bool]] = _git_state,
        recent_jobs: Callable[[str], list[Any]] = _recent_jobs,
        pull_requests: Callable[[], dict[str, PullRequestCounts] | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service = service
        self._projects = projects
        self._repo_of = repo_of
        self._git_state = git_state
        self._recent_jobs = recent_jobs
        # Looked up when called, so a test can stand in for GitHub.
        self._pull_requests = pull_requests or (lambda: _pull_requests())
        self._clock = clock
        self._prs: dict[str, PullRequestCounts] = {}
        self._prs_at: float | None = None
        self._lock = threading.Lock()
        #: folder -> repository id, for project folders and thread folders seen so far.
        self._repo_by_folder: dict[str, str] = {}
        self._name: dict[str, str] = {}
        self._main: dict[str, str] = {}
        self._flags: dict[str, tuple[bool, bool]] = {}
        #: Thread folders no project folder contains; resolved by the next refresh.
        self._unresolved: set[str] = set()
        self._watch_flags: set[str] = set()
        self._refreshed_at: float | None = None
        self._refreshing = False
        self._rev = 0
        self._digest = ""
        self._sent: dict[str, tuple[str, int]] = {}

    # --------------------------------------------------------- slow facts

    def on_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Chat-service listener: a finished turn may have changed a checkout. Inline."""
        if event.get("kind") == "turn_finished":
            self.request_refresh()

    def request_refresh(self) -> bool:
        """Start a background refresh unless one runs or one just ran."""
        with self._lock:
            if self._refreshing:
                return False
            last = self._refreshed_at
            if last is not None and self._clock() - last < MIN_REFRESH_GAP_S:
                return False
            self._refreshing = True
        threading.Thread(target=self._refresh_guarded, name="repo-board", daemon=True).start()
        return True

    def _refresh_guarded(self) -> None:
        try:
            self.refresh()
        except Exception:  # noqa: BLE001 - the index is a convenience; the last good facts stay
            log.warning("repo board: refresh failed", exc_info=True)
        finally:
            with self._lock:
                self._refreshing = False

    def refresh(self) -> None:
        """Read the slow facts again. Blocking (``git``): call it off the event loop."""
        known = self._projects()
        with self._lock:
            unresolved = sorted(self._unresolved)
            watch = set(self._watch_flags)
        repo_by_folder: dict[str, str] = {}
        name: dict[str, str] = {}
        main: dict[str, str] = {}
        for project_name, folder in known:
            repo = self._repo_of(folder)
            if not repo:
                continue
            repo_by_folder[_norm(folder)] = repo
            # The first project of a repository names it; a worktree added
            # later as a project of its own does not rename it.
            name.setdefault(repo, project_name)
            main.setdefault(repo, folder)
        for folder in unresolved:
            repo = self._repo_of(folder)
            if repo:
                repo_by_folder[_norm(folder)] = repo
                name.setdefault(repo, Path(folder).name)
                main.setdefault(repo, folder)
        flags = {repo: self._git_state(main[repo]) for repo in sorted(watch) if repo in main}
        prs = self._read_pull_requests(watch)
        with self._lock:
            self._repo_by_folder = repo_by_folder
            self._name = name
            self._main = main
            self._flags = flags
            if prs is not None:
                self._prs = prs
            self._unresolved.difference_update(unresolved)
            self._refreshed_at = self._clock()

    def _read_pull_requests(self, watch: set[str]) -> dict[str, PullRequestCounts] | None:
        """Open pull requests per repository, when one in play is on GitHub and it is time."""
        if not any(repo.split("/", 1)[0] == "github.com" for repo in watch):
            return None  # no repository in play is on GitHub
        with self._lock:
            last = self._prs_at
        if last is not None and self._clock() - last < PULL_REQUESTS_TTL_S:
            return None
        found = self._pull_requests()
        with self._lock:
            self._prs_at = self._clock()
        return found

    # --------------------------------------------------------- fast facts

    def _repo_for(self, folder: str) -> str:
        """The repository of a thread's folder, from what is already known."""
        wanted = _norm(folder)
        best, found = "", ""
        with self._lock:
            for known, repo in self._repo_by_folder.items():
                if (wanted == known or wanted.startswith(known + "/")) and len(known) > len(best):
                    best, found = known, repo
            if not found and wanted:
                self._unresolved.add(folder)
        return found

    def _thread_counts(self) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
        """``(busy, waits, folder_of_session)`` over the coding threads."""
        busy: dict[str, int] = {}
        waits: dict[str, int] = {}
        folders: dict[str, str] = {}
        service = self._service
        for session in service.store.list_sessions(limit=_SESSIONS_READ, surface=_THREAD_SURFACE):
            sid = session.session_id
            folders[sid] = str(session.cwd or "")
            waiting = bool(service.pending_questions(sid) or service.pending_approvals(sid))
            working = bool(service.is_running(sid))
            if not (waiting or working):
                continue
            repo = self._repo_for(folders[sid])
            if not repo:
                continue
            if waiting:
                waits[repo] = waits.get(repo, 0) + 1
            else:
                busy[repo] = busy.get(repo, 0) + 1
        return busy, waits, folders

    def _recent(self, owner_session: str, folders: dict[str, str]) -> list[str]:
        if not owner_session:
            return []
        seen: list[str] = []
        for job in self._recent_jobs(owner_session):
            target = str(getattr(job, "target", "") or "")
            if not target.startswith("thread:"):
                continue
            repo = self._repo_for(folders.get(target.removeprefix("thread:"), ""))
            if repo and repo not in seen:
                seen.append(repo)
            if len(seen) >= RECENT_REPOS:
                break
        return seen

    def states(self, *, message: str = "", owner_session: str = "") -> tuple[list[RepoState], int]:
        """``(one state per known repository, how many there are)``. No ``git``."""
        busy, waits, folders = self._thread_counts()
        recent = set(self._recent(owner_session, folders))
        with self._lock:
            names = dict(self._name)
            flags = dict(self._flags)
            prs = dict(self._prs)
        named = _named(message, names.values())
        states = [
            RepoState(
                name=label,
                busy=busy.get(repo, 0),
                waits=waits.get(repo, 0),
                prs=prs.get(repo, (0, 0, 0, False))[0],
                prs_failing=prs.get(repo, (0, 0, 0, False))[1],
                prs_running=prs.get(repo, (0, 0, 0, False))[2],
                dirty=flags.get(repo, (False, False))[0],
                conflict=flags.get(repo, (False, False))[1] or prs.get(repo, (0, 0, 0, False))[3],
                named=label in named,
                recent=repo in recent,
            )
            for repo, label in names.items()
        ]
        # Flags are read only for repositories that are in play; the set for the
        # next refresh is the one in play now.
        wanted = {
            repo for repo, label in names.items() if any(s.name == label for s in in_play(states))
        }
        with self._lock:
            changed = wanted != self._watch_flags
            self._watch_flags = wanted
            first = self._refreshed_at is None
        if changed or first:
            self.request_refresh()
        return states, len(names)

    # ------------------------------------------------------------ the text

    def text(self, *, message: str = "", owner_session: str = "") -> str:
        """The index as it stands, or ``""`` when no repository is in play."""
        states, total = self.states(message=message, owner_session=owner_session)
        digest = body_digest(states, total=total)
        with self._lock:
            if digest != self._digest:
                self._digest = digest
                self._rev += 1
            rev = self._rev
        return render(states, total=total, rev=rev)

    def note_for(self, session_id: str, *, message: str = "") -> str:
        """The index for a conversation that keeps what it was sent.

        Returns ``""`` while the conversation already holds this revision, and
        the text again every :data:`RESEND_EVERY` turns.
        """
        text = self.text(message=message, owner_session=session_id)
        with self._lock:
            digest = self._digest
            last, turns = self._sent.get(session_id, ("", 0))
            if not text:
                self._sent[session_id] = ("", 0)
                return ""
            if digest == last and turns + 1 < RESEND_EVERY:
                self._sent[session_id] = (last, turns + 1)
                return ""
            self._sent[session_id] = (digest, 0)
        return text

    def forget(self, session_id: str) -> None:
        """The conversation lost its history (a fresh start, a compaction): send again."""
        with self._lock:
            self._sent.pop(session_id, None)


def _norm(folder: str) -> str:
    return str(folder or "").replace("\\", "/").rstrip("/")


def _named(message: str, names: Iterable[str]) -> set[str]:
    """The repository names a message mentions as whole words."""
    text = message or ""
    if not text:
        return set()
    found: set[str] = set()
    for name in names:
        if len(name) < 3:
            continue
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.IGNORECASE):
            found.add(name)
    return found


# ----------------------------------------------------------- process wiring

_board: RepoBoard | None = None


def board() -> RepoBoard | None:
    """The process board, or ``None`` while the repository index is off."""
    return _board


def set_board(value: RepoBoard | None) -> None:
    """Replace the process board (tests, an embedding host)."""
    global _board
    _board = value


def cli_note(session_id: str, message: str = "") -> str:
    """The index for a lead turn on a CLI seat, or ``""`` (off, unchanged, nothing in play)."""
    current = _board
    if current is None:
        return ""
    try:
        return current.note_for(session_id, message=message)
    except Exception:  # noqa: BLE001 - the index must never fail a lead turn
        log.warning("repo board: no index for this turn", exc_info=True)
        return ""


def turn_context_note() -> str:
    """The index for a lead turn on the app's own brain, or ``""``."""
    current = _board
    if current is None:
        return ""
    try:
        return current.text()
    except Exception:  # noqa: BLE001 - the index must never fail a lead turn
        log.warning("repo board: no index for this turn", exc_info=True)
        return ""


def install(service: Any, config: Any) -> RepoBoard | None:
    """Start the repository index for ``service`` when ``[rsi] repo_index`` is set."""
    section = getattr(config, "rsi", None)
    if section is None or not getattr(section, "repo_index", False):
        return None
    try:
        made = RepoBoard(service)
        service.add_event_listener(made.on_event)
    except Exception:  # noqa: BLE001 - a board that cannot start leaves the chat as it was
        log.warning("repo board: not started", exc_info=True)
        return None
    set_board(made)
    log.info("repo board: the lead gets a repository index with its messages")
    return made
