"""The deterministic checks on what a coding run left behind.

When a run's turn has ended, the gate looks at the run's *work area*: a
checkout the run had to itself, with a known starting commit. It takes a
snapshot of that folder as it is now (tracked and untracked files, through a
throwaway index, so nothing in the folder changes), diffs it against the
start, and puts the diff through the cheat scan and the scope check.

A run has a work area when

* its thread runs in a linked worktree (the folder is the run's alone), or
* the thread runs in the shared project folder but everything the session
  changed lies in ONE linked worktree of that repository, which it made itself.

A run without one is ``unattributed``: in a shared checkout the difference to
the start holds other runs' edits too, and edits made through a shell show up
in no tool record, so nothing found there could be pinned on this run.

Reads only, calls no model and runs none of the project's commands.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from . import cheat_scan, scope
from .cheat_scan import AMBIGUOUS, VIOLATION, Finding

log = logging.getLogger(__name__)

__all__ = [
    "CLEAN",
    "FINDINGS",
    "STATUSES",
    "UNATTRIBUTED",
    "UNREADABLE",
    "VIOLATIONS",
    "GateResult",
    "WorkArea",
    "check_run",
    "work_area",
]

#: Nothing found.
CLEAN: Final[str] = "clean"
#: Only findings someone has to look at.
FINDINGS: Final[str] = "findings"
#: At least one finding that shows a weakening or an off-limits change on its face.
VIOLATIONS: Final[str] = "violations"
#: The run had no work area of its own: nothing can be pinned on it.
UNATTRIBUTED: Final[str] = "unattributed"
#: The work area could not be read (no git, the folder is gone).
UNREADABLE: Final[str] = "unreadable"
STATUSES: Final[tuple[str, ...]] = (CLEAN, FINDINGS, VIOLATIONS, UNATTRIBUTED, UNREADABLE)

#: A larger patch is scanned up to here and reported as cut.
_PATCH_MAX: Final[int] = 4_000_000
_FINDINGS_KEPT: Final[int] = 60
_GENERATED = (
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock",
    "go.sum",
)


@dataclass(frozen=True, slots=True)
class WorkArea:
    """The checkout a run had to itself and the commit it started from."""

    folder: str
    base: str
    #: ``thread_worktree`` (the thread's own folder) or ``session_worktree``
    #: (a worktree the session made).
    how: str


@dataclass(slots=True)
class GateResult:
    status: str
    area: WorkArea | None = None
    tree_id: str = ""
    files: list[str] = field(default_factory=list)
    added: int = 0
    deleted: int = 0
    findings: list[Finding] = field(default_factory=list)
    truncated: bool = False
    reason: str = ""
    #: The commit the work area was on when it was read.
    head_sha: str = ""
    #: The work area held nothing beyond that commit: no uncommitted or untracked file.
    committed: bool = False

    @property
    def churn(self) -> int:
        """Lines added plus lines deleted, without lockfiles."""
        return self.added + self.deleted

    def to_detail(self) -> dict[str, Any]:
        """What a step row keeps: counts in full, findings capped."""
        return {
            "status": self.status,
            "reason": self.reason,
            "work_area": self.area.how if self.area else "",
            "folder": self.area.folder if self.area else "",
            "base": self.area.base if self.area else "",
            "tree_id": self.tree_id,
            "head_sha": self.head_sha,
            "committed": self.committed,
            "files": len(self.files),
            "added": self.added,
            "deleted": self.deleted,
            "truncated": self.truncated,
            "violations": sum(1 for f in self.findings if f.severity == VIOLATION),
            "ambiguous": sum(1 for f in self.findings if f.severity == AMBIGUOUS),
            "findings": [f.to_dict() for f in self.findings[:_FINDINGS_KEPT]],
        }


# ---------------------------------------------------------------------- git


def _git(folder: str, *args: str) -> str:
    from dodaios.agentic_ide.git_local import git_out

    try:
        return (git_out(list(args), Path(folder)) or "").strip()
    except Exception:  # noqa: BLE001 - an unreadable folder has no git facts
        log.debug("gates: git %s failed in %s", args[:1], folder, exc_info=True)
        return ""


def _toplevel(folder: str) -> str:
    return _git(folder, "rev-parse", "--path-format=absolute", "--show-toplevel")


def _common_dir(folder: str) -> str:
    return _git(folder, "rev-parse", "--path-format=absolute", "--git-common-dir")


def _is_linked(folder: str) -> bool:
    git_dir = _git(folder, "rev-parse", "--path-format=absolute", "--git-dir")
    common = _common_dir(folder)
    return bool(git_dir and common and git_dir != common)


def _fork_point(folder: str, fallback: str) -> str:
    """Where a session-made worktree left the line it came from."""
    for ref in ("origin/HEAD", fallback):
        if not ref:
            continue
        base = _git(folder, "merge-base", "HEAD", ref)
        if base:
            return base
    return ""


# ---------------------------------------------------------------- work area


def work_area(
    run: dict[str, Any],
    events: Iterable[dict[str, Any]] = (),
    *,
    worked: Callable[..., list[tuple[str, float]]] | None = None,
) -> WorkArea | None:
    """The work area of ``run``, or ``None`` when it shared its checkout.

    ``events`` are the thread's own events; only those from the run's start on
    count as the run's work.
    """
    folder = str(run.get("workdir") or "")
    own = _toplevel(folder) if folder else ""
    if not own:
        return None
    base = str(run.get("base_sha") or "")
    # A thread that started in a linked worktree has that one, unless ...
    given = WorkArea(folder=own, base=base, how="thread_worktree") if (
        run.get("isolated") and base
    ) else None
    if worked is None:
        from dodaios.agentic_ide.session_branches import worked_folders as worked
    started_s = float(run.get("started_ms") or 0) / 1000
    touched = {
        top
        for written, _at in worked(list(events), folder, not_before=started_s)
        if (top := _toplevel(written))
    }
    if given is not None and (not touched or own in touched):
        return given
    if len(touched) != 1:
        return given  # nothing written, or writes in more than one checkout
    (only,) = touched
    if not _is_linked(only) or _common_dir(only) != _common_dir(folder):
        return given  # it wrote into the shared checkout, or into another repository
    # ... it made a worktree of its own and did all its work there.
    fork = _fork_point(only, base)
    return WorkArea(folder=only, base=fork, how="session_worktree") if fork else given


# --------------------------------------------------------------------- gate


def _numstat(folder: str, base: str, tree: str) -> tuple[list[str], int, int]:
    files: list[str] = []
    added = deleted = 0
    for line in _git(folder, "diff", "--numstat", "-M", base, tree).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path = parts[2]
        files.append(path)
        if Path(path).name in _GENERATED:
            continue
        if parts[0].isdigit():
            added += int(parts[0])
        if parts[1].isdigit():
            deleted += int(parts[1])
    return files, added, deleted


def _reader(folder: str) -> Callable[[str], str | None]:
    root = Path(folder)

    def read(path: str) -> str | None:
        target = root / path
        try:
            if not target.is_file() or target.stat().st_size > 1_000_000:
                return None
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError:  # an unreadable file gives the scan nothing more to go on
            return None

    return read


def check_run(
    run: dict[str, Any],
    events: Iterable[dict[str, Any]] = (),
    *,
    snapshot: Callable[[str], str | None] | None = None,
) -> GateResult:
    """Run the deterministic checks on what ``run`` left in its work area."""
    area = work_area(run, events)
    if area is None:
        return GateResult(
            UNATTRIBUTED,
            reason="the run had no checkout of its own, so nothing can be pinned on it",
        )
    if snapshot is None:
        from dodaios.agent_chat.team.workspace import GitWorkspace

        snapshot = GitWorkspace().snapshot
    tree = snapshot(area.folder) or ""
    if not tree:
        return GateResult(UNREADABLE, area=area, reason="the work area could not be read")
    files, added, deleted = _numstat(area.folder, area.base, tree)
    patch = _git(area.folder, "diff", "-M", area.base, tree)
    truncated = len(patch) > _PATCH_MAX
    own_repo = (Path(area.folder) / "dodaios" / "self_change" / "surfaces.py").is_file()
    found = [
        *scope.check(files, own_repo=own_repo),
        *cheat_scan.scan(patch[:_PATCH_MAX], read_new=_reader(area.folder)),
    ]
    if any(f.severity == VIOLATION for f in found):
        status = VIOLATIONS
    elif found:
        status = FINDINGS
    else:
        status = CLEAN
    head_tree = _git(area.folder, "rev-parse", "--verify", "--quiet", "HEAD^{tree}")
    return GateResult(
        status, area=area, tree_id=tree, files=files, added=added, deleted=deleted,
        findings=found, truncated=truncated,
        head_sha=_git(area.folder, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"),
        committed=bool(head_tree) and head_tree == tree,
    )
