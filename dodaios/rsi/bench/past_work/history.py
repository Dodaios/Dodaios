"""The pull requests that were merged into a repository, read from its own history.

For every merged pull request: the commit it landed as, the commit before it,
and the paths it touched with the lines changed in each. That pair of commits
is what makes past work a task: the commit before is where an agent starts,
and the merged commit holds the tests that say whether the work was done.

Reads only, from the local clone, and never a network call. A pull request is
recognised by its number in the subject, as a squash merge (``... (#12)``) or
a merge commit (``Merge pull request #12 from ...``) writes it. A pull request
that a later commit reverted is marked, because what was taken back is not a
right answer.

Two steps, because the second is the slow one. :func:`read_history` walks the
default branch once for the subjects, which takes a second. The paths and line
counts are then read only for the pull requests somebody asks about
(:meth:`History.changes`): a few hundred diffs instead of the whole history.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dodaios.rsi import domains, repo_identity

__all__ = ["History", "MergedChange", "merged_changes", "read_history"]

_RECORD: Final = "\x1e"
_FIELD: Final = "\x1f"
_SQUASHED: Final = re.compile(r"\(#(\d+)\)\s*$")
_MERGED: Final = re.compile(r"^Merge pull request #(\d+) from ")
_REVERT: Final = re.compile(r'^Revert "(.*)"')
_NUMBER: Final = re.compile(r"\(#(\d+)\)")
_LOG_TIMEOUT_S: Final = 180.0


@dataclass(frozen=True, slots=True)
class MergedChange:
    """One merged pull request as the default branch records it."""

    #: ``host/owner/name`` (:func:`dodaios.rsi.repo_identity.repo_id`).
    repo: str
    number: int
    commit: str
    #: The commit the default branch was at before this change.
    parent: str
    merged_ms: int
    subject: str
    files: tuple[str, ...]
    reverted: bool = False
    #: Lines added plus deleted per path, in the order of :attr:`files`.
    lines: tuple[int, ...] = ()

    @property
    def weights(self) -> dict[str, int]:
        """How much of the change each path holds: its lines, at least one."""
        counted = self.lines or (1,) * len(self.files)
        return {path: max(1, n) for path, n in zip(self.files, counted, strict=True)}

    @property
    def tests(self) -> tuple[str, ...]:
        return tuple(path for path in self.files if domains.domain_of(path) == "testing")

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(path for path in self.files if domains.domain_of(path) != "testing")


@dataclass(frozen=True, slots=True)
class _Head:
    commit: str
    parent: str
    merged_ms: int
    subject: str


def _git(args: list[str], folder: Path, *, timeout: float = 20.0, stdin: str | None = None) -> str:
    from dodaios.agentic_ide.git_local import run_git

    result = run_git(args, folder, timeout=timeout, stdin=stdin)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout or ""


def _default_branch(folder: Path) -> str:
    remote_head = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], folder).strip()
    return remote_head or "HEAD"


def _number(subject: str) -> int | None:
    match = _SQUASHED.search(subject) or _MERGED.match(subject)
    return int(match.group(1)) if match else None


def _touched(numstat: str) -> list[tuple[str, int]]:
    """``(path, lines added plus deleted)`` per row of ``git log --numstat``."""
    out: list[tuple[str, int]] = []
    for row in numstat.splitlines():
        added, _, rest = row.partition("\t")
        deleted, _, path = rest.partition("\t")
        if not path.strip():
            continue
        # A binary file has no line count ("-"); it still is one thing that changed.
        count = sum(int(n) for n in (added, deleted) if n.isdigit())
        out.append((path.strip(), max(1, count)))
    return out


class History:
    """The merged pull requests of one clone: all of them known, their paths read on demand."""

    def __init__(
        self, folder: Path, repo: str, heads: dict[int, _Head], reverted: frozenset[int]
    ) -> None:
        self.folder = folder
        #: ``host/owner/name`` (:func:`dodaios.rsi.repo_identity.repo_id`).
        self.repo = repo
        self._heads = heads
        self._reverted = reverted

    @property
    def numbers(self) -> frozenset[int]:
        """Every pull request number the default branch holds a merge of."""
        return frozenset(self._heads)

    def changes(self, numbers: Iterable[int] | None = None) -> dict[int, MergedChange]:
        """The merged changes of ``numbers`` (all of them for ``None``), with their paths.

        A number the default branch has no merge of is simply absent.
        """
        wanted = sorted(self._heads if numbers is None else set(numbers) & self._heads.keys())
        if not wanted:
            return {}
        out = _git(
            [
                "log",
                "--no-walk=unsorted",
                "--stdin",
                # A merge commit counts with what it brought in, against the branch before it.
                "--first-parent",
                "-m",
                # A moved file is two paths here: where it left and where it arrived.
                "--numstat",
                "--no-renames",
                f"--format={_RECORD}%H",
            ],
            self.folder,
            timeout=_LOG_TIMEOUT_S,
            stdin="\n".join(self._heads[number].commit for number in wanted) + "\n",
        )
        touched: dict[str, list[tuple[str, int]]] = {}
        for record in out.split(_RECORD):
            commit, _, rows = record.partition("\n")
            if commit.strip():
                touched[commit.strip()] = _touched(rows)
        changes: dict[int, MergedChange] = {}
        for number in wanted:
            head = self._heads[number]
            rows = touched.get(head.commit)  # type: ignore[assignment]
            if rows is None:
                continue  # git did not answer for it: unknown, not empty
            changes[number] = MergedChange(
                repo=self.repo,
                number=number,
                commit=head.commit,
                parent=head.parent,
                merged_ms=head.merged_ms,
                subject=head.subject,
                files=tuple(path for path, _ in rows),  # type: ignore[str-unpack]
                reverted=number in self._reverted,
                lines=tuple(count for _, count in rows),  # type: ignore[misc, str-unpack]
            )
        return changes


def read_history(folder: str | Path, *, branch: str = "") -> History | None:
    """The merged pull requests on the default branch of ``folder``.

    ``None`` when the folder is gone, is no repository, has no merged pull
    request, or git does not answer.
    """
    path = Path(folder).expanduser()
    if not path.is_dir():
        # A project folder that was deleted since: nothing to read, and no reason to stop.
        return None
    out = _git(
        [
            "log",
            branch or _default_branch(path),
            "--first-parent",
            f"--format=%H{_FIELD}%P{_FIELD}%ct{_FIELD}%s",
        ],
        path,
        timeout=_LOG_TIMEOUT_S,
    )
    heads: dict[int, _Head] = {}
    reverted: set[int] = set()
    for line in out.splitlines():
        fields = line.split(_FIELD)
        if len(fields) != 4:
            continue
        commit, parents, seconds, subject = fields
        undone = _REVERT.match(subject)
        if undone is not None:
            reverted.update(int(number) for number in _NUMBER.findall(undone.group(1)))
        number = _number(subject)
        parent = parents.split(" ")[0] if parents else ""
        # The log runs newest first, so the first commit that names a number is its merge.
        if number is None or not parent or number in heads:
            continue
        heads[number] = _Head(
            commit=commit,
            parent=parent,
            merged_ms=int(seconds) * 1000 if seconds.isdigit() else 0,
            subject=subject,
        )
    if not heads:
        return None
    return History(path, repo_identity.repo_id(path), heads, frozenset(reverted & heads.keys()))


def merged_changes(
    folder: str | Path, *, branch: str = "", only: Iterable[int] | None = None
) -> dict[int, MergedChange]:
    """Merged pull requests of ``folder`` by number: all, or those in ``only``.

    Empty when the folder is no repository or git does not answer.
    """
    history = read_history(folder, branch=branch)
    return {} if history is None else history.changes(only)
