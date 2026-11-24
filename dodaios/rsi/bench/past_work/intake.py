"""Put the tasks from past coding work into the benchmark's store.

Mining reads the coding CLIs' records, and a CLI deletes a record after some
weeks. So the tasks are stored when they are found, and a stored task stays
when its record is gone: the request and the merged change are all it needs.

A stored task is retired only for a reason the repository gives: its pull
request was reverted, or its commit is no longer on the default branch. Never
because mining did not find it again.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dodaios.rsi.bench.model import Domain, Source
from dodaios.rsi.bench.past_work.history import MergedChange, _git, read_history
from dodaios.rsi.bench.past_work.sessions import PastSession, read_sessions
from dodaios.rsi.bench.past_work.tasks import mine
from dodaios.rsi.bench.store import BenchStore

__all__ = ["Taken", "read_changes", "session_folders", "take_in"]

_DOMAINS = (Domain.BRIEF, Domain.CODING)


@dataclass(frozen=True, slots=True)
class Taken:
    """What one intake did to the store."""

    #: Tasks the store did not have before.
    new: int = 0
    #: Tasks from past work in use after the intake, per domain.
    in_use: Mapping[str, int] = field(default_factory=dict)
    #: Tasks taken out of use because their pull request no longer stands.
    retired: int = 0
    #: Opened pull requests that became no task, by reason.
    left_out: Mapping[str, int] = field(default_factory=dict)
    #: The clones that were read, one per repository (a brief replay works on them).
    folders: tuple[str, ...] = ()


def _pull(group: str) -> tuple[str, int]:
    """The repository and number a task's group names (``host/owner/name#12``)."""
    repo, _, number = group.rpartition("#")
    return repo, int(number) if number.isdigit() else 0


def session_folders(sessions: Iterable[PastSession]) -> list[Path]:
    """One folder per repository, among the folders the sessions that opened a pull request ran in.

    A session's folder is often a worktree, and many worktrees share one
    repository: its history is read once. A folder that is gone or is no
    repository is left out.
    """
    seen: set[str] = set()
    out: list[Path] = []
    for raw in sorted({session.cwd for session in sessions if session.opened and session.cwd}):
        folder = Path(raw)
        if not folder.is_dir():
            continue
        common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], folder).strip()
        key = os.path.normcase(os.path.normpath(common)) if common else ""
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(folder)
    return out


def read_changes(
    sessions: Iterable[PastSession],
    folders: Iterable[str | Path],
    *,
    also: Iterable[tuple[str, int]] = (),
) -> dict[str, dict[int, MergedChange]]:
    """The merged changes of the pull requests the sessions opened, per repository.

    Read from the clones in ``folders``; ``also`` names further pull requests to
    look up. A repository that was read is in the answer even when none of the
    pull requests asked about is merged there; a folder that is no repository
    is not.
    """
    wanted: dict[str, set[int]] = {}
    for session in sessions:
        for pull in session.opened:
            wanted.setdefault(pull.repo, set()).add(pull.number)
    for repo, number in also:
        wanted.setdefault(repo, set()).add(number)
    changes: dict[str, dict[int, MergedChange]] = {}
    for folder in folders:
        history = read_history(folder)
        if history is not None:
            changes[history.repo] = history.changes(wanted.get(history.repo, ()))
    return changes


def _stands(group: str, changes: Mapping[str, Mapping[int, MergedChange]]) -> bool | None:
    """Whether a task's pull request still stands; ``None`` when its repository was not read."""
    repo, number = _pull(group)
    merged = changes.get(repo)
    if merged is None or not number:
        return None
    change = merged.get(number)
    return change is not None and not change.reverted


def take_in(
    store: BenchStore,
    folders: Iterable[str | Path] | None = None,
    *,
    homes: dict[str, Path] | None = None,
    composed: Callable[[str], bool] | None = None,
) -> Taken:
    """Mine the records for the clones in ``folders`` and bring the store up to date.

    Without ``folders`` the repositories are the ones the recorded sessions
    themselves ran in (:func:`session_folders`). ``homes`` and ``composed`` are
    passed on to :func:`.sessions.read_sessions` and :func:`.tasks.mine`. A
    folder that is no repository contributes nothing.
    """
    sessions = list(read_sessions(homes))
    folders = list(session_folders(sessions) if folders is None else folders)
    stored = [task for domain in _DOMAINS for task in store.tasks(domain, source=Source.MINED)]
    # A stored task's pull request is asked about too: its record may be long gone.
    changes = read_changes(sessions, folders, also=(_pull(task.group) for task in stored))
    mined = mine(sessions, changes, composed=composed)
    new = store.put_tasks(mined.tasks)
    gone = [task.id for task in stored if _stands(task.group, changes) is False]
    if gone:
        store.retire(gone)
    return Taken(
        new=new,
        in_use={domain.value: len(store.tasks(domain, source=Source.MINED)) for domain in _DOMAINS},
        retired=len(gone),
        left_out=dict(mined.left_out),
        folders=tuple(str(folder) for folder in folders),
    )
