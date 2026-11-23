"""The pull requests that were merged into a repository, read from its own history.

For every merged pull request: the commit it landed as, the commit before it,
and the paths it touched. That pair of commits is what makes past work a task:
the commit before is where an agent starts, and the merged commit holds the
tests that say whether the work was done.

Reads only, from the local clone: one ``git log`` over the default branch and
never a network call. A pull request is recognised by its number in the
subject, as a squash merge (``... (#12)``) or a merge commit
(``Merge pull request #12 from ...``) writes it. A pull request that a later
commit reverted is marked, because what was taken back is not a right answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from dodaios.rsi import domains, repo_identity

__all__ = ["MergedChange", "merged_changes"]

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

    @property
    def tests(self) -> tuple[str, ...]:
        return tuple(path for path in self.files if domains.domain_of(path) == "testing")

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(path for path in self.files if domains.domain_of(path) != "testing")


def _git(args: list[str], folder: Path, *, timeout: float = 20.0) -> str:
    from dodaios.agentic_ide.git_local import run_git

    result = run_git(args, folder, timeout=timeout)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout or ""


def _default_branch(folder: Path) -> str:
    remote_head = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], folder).strip()
    return remote_head or "HEAD"


def _number(subject: str) -> int | None:
    match = _SQUASHED.search(subject) or _MERGED.match(subject)
    return int(match.group(1)) if match else None


def merged_changes(folder: str | Path, *, branch: str = "") -> dict[int, MergedChange]:
    """Every merged pull request on the default branch of ``folder``, by its number.

    Empty when the folder is no repository or git does not answer.
    """
    path = Path(folder).expanduser()
    repo = repo_identity.repo_id(path)
    out = _git(
        [
            "log",
            branch or _default_branch(path),
            "--first-parent",
            "-m",
            "--name-only",
            f"--format={_RECORD}%H{_FIELD}%P{_FIELD}%ct{_FIELD}%s",
        ],
        path,
        timeout=_LOG_TIMEOUT_S,
    )
    changes: dict[int, MergedChange] = {}
    reverted: set[int] = set()
    for record in out.split(_RECORD):
        head, _, names = record.partition("\n")
        fields = head.split(_FIELD)
        if len(fields) != 4:
            continue
        commit, parents, seconds, subject = fields
        undone = _REVERT.match(subject)
        if undone is not None:
            reverted.update(int(number) for number in _NUMBER.findall(undone.group(1)))
        number = _number(subject)
        parent = parents.split(" ")[0] if parents else ""
        # The log runs newest first, so the first commit that names a number is its merge.
        if number is None or not parent or number in changes:
            continue
        changes[number] = MergedChange(
            repo=repo,
            number=number,
            commit=commit,
            parent=parent,
            merged_ms=int(seconds) * 1000 if seconds.isdigit() else 0,
            subject=subject,
            files=tuple(line.strip() for line in names.splitlines() if line.strip()),
        )
    for number in reverted & changes.keys():
        changes[number] = replace(changes[number], reverted=True)
    return changes
