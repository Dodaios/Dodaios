"""The deterministic checks on what a coding run left behind.

When a run's turn has ended, the gate looks at the run's *work area*: a
checkout the run had to itself, with a known starting commit. It takes a
snapshot of that folder as it is now (tracked and untracked files, through a
throwaway index, so nothing in the folder changes), diffs it against the
start, and puts the diff through the cheat scan and the scope check.

A run has a work area when

* its thread runs in a linked worktree (the folder is the run's alone), or
* the thread runs in the shared project folder but everything the session
  changed lies in ONE linked worktree of that repository, which it made itself,
  or
* the thread runs in a shared checkout and a snapshot of it was taken when the
  run was bound (``start_tree``). Then the run's change is the difference
  between that snapshot and one taken now, limited to the files the run's own
  tool calls wrote where it reported any, so what the person or others changed
  meanwhile in other files is not the run's.

In a shared checkout a run is ``unattributed`` only when another run was open
in the same checkout during its turn and the two touched a common file: then
the difference holds the other run's edits too. A run without any of these
work areas is ``unattributed`` as well.

Reads only, calls no model and runs none of the project's commands.
"""

from __future__ import annotations

import logging
import os
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
    "shared_area",
    "work_area",
    "written_paths",
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
#: Changed paths a step keeps (for the review's triggers).
_PATHS_KEPT: Final[int] = 200
_GENERATED = (
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock",
    "go.sum",
)


@dataclass(frozen=True, slots=True)
class WorkArea:
    """The checkout a run had to itself and the commit it started from."""

    folder: str
    base: str
    #: ``thread_worktree`` (the thread's own folder), ``session_worktree``
    #: (a worktree the session made) or ``shared_snapshot`` (a shared checkout,
    #: from the snapshot taken when the run was bound).
    how: str
    #: For a shared checkout: the files that are the run's (``None``: all).
    paths: tuple[str, ...] | None = None


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
            "paths": self.files[:_PATHS_KEPT],
            "limited": self.area is not None and self.area.paths is not None,
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


def _limited(args: list[str], paths: tuple[str, ...] | None) -> list[str]:
    """``args`` for git, limited to ``paths`` (a literal pathspec) when given."""
    if paths is None:
        return args
    return [*args, "--", *(f":(literal){path}" for path in paths)]


def _numstat(
    folder: str, base: str, tree: str, paths: tuple[str, ...] | None = None
) -> tuple[list[str], int, int]:
    files: list[str] = []
    added = deleted = 0
    if paths is not None and not paths:
        return files, added, deleted
    args = _limited(["diff", "--numstat", "-M", base, tree], paths)
    for line in _git(folder, *args).splitlines():
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


def diff_of(detail: dict[str, Any]) -> str:
    """The diff an output scan read, from what its step kept; ``""`` when gone."""
    folder = str(detail.get("folder") or "")
    base, tree = str(detail.get("base") or ""), str(detail.get("tree_id") or "")
    if not (folder and base and tree) or not Path(folder).is_dir():
        return ""
    paths = tuple(detail.get("paths") or ()) if detail.get("limited") else None
    if paths is not None and not paths:
        return ""
    return _git(folder, *_limited(["diff", "-M", base, tree], paths))


# ------------------------------------------------------------ shared checkout


def _norm(path: str) -> str:
    return os.path.normcase(path.replace("\\", "/")).replace("\\", "/")


def _relative(paths: Iterable[str], cwd: str, top: str) -> set[str]:
    """``paths`` (absolute, or relative to ``cwd``) as paths inside ``top``, normalised."""
    out: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        full = Path(raw) if Path(raw).is_absolute() else Path(cwd) / raw
        try:
            rel = os.path.relpath(os.path.normpath(str(full)), os.path.normpath(top))
        except ValueError:  # another drive: not in this checkout
            continue
        if rel.startswith(".."):
            continue
        out.add(_norm(rel))
    return out


def written_paths(events: Iterable[dict[str, Any]], since_ms: int = 0) -> list[str]:
    """Files a thread's own tool calls wrote or edited from ``since_ms`` on."""
    from dodaios.society.coding_threads import _WRITING_TOOLS

    out: list[str] = []
    for event in events:
        if event.get("kind") != "tool_call" or int(event.get("ts_ms") or 0) < since_ms:
            continue
        payload = event.get("payload") or {}
        if str(payload.get("name") or "").lower() not in _WRITING_TOOLS:
            continue
        args = payload.get("input") or {}
        path = str(args.get("file_path") or args.get("path") or "")
        if path and path not in out:
            out.append(path)
    return out


def shared_area(
    run: dict[str, Any],
    reported: Iterable[str],
    tree: str,
    neighbours: dict[str, Iterable[str]] | None = None,
) -> tuple[WorkArea | None, str]:
    """The run's own part of a shared checkout, or ``(None, why not)``.

    ``reported`` are the files the run's tool calls wrote (empty: it named
    none, so the whole difference counts), ``tree`` the snapshot taken now,
    ``neighbours`` the files each other run open in the checkout meanwhile
    touched.
    """
    cwd = str(run.get("workdir") or "")
    start = str(run.get("start_tree") or "")
    top = _toplevel(cwd) if cwd and start else ""
    if not top:
        return None, "the run had no checkout of its own, so nothing can be pinned on it"
    own = _relative(reported, cwd, top)
    changed: list[str] = []
    for line in _git(top, "diff", "--name-status", "-M", start, tree).splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        names = parts[1:]
        if not own or any(_norm(name) in own for name in names):
            changed.extend(name for name in names if name not in changed)
    for other, touched in (neighbours or {}).items():
        theirs = _relative(touched, cwd, top)
        common = sorted(theirs & ({_norm(name) for name in changed} | own))
        if common:
            shown = ", ".join(common[:3])
            return None, (
                f"another run ({other}) worked in the same checkout at the same time and "
                f"touched the same files ({shown}), so the change cannot be pinned on this run"
            )
    return WorkArea(folder=top, base=start, how="shared_snapshot", paths=tuple(changed)), ""


def check_run(
    run: dict[str, Any],
    events: Iterable[dict[str, Any]] = (),
    *,
    snapshot: Callable[[str], str | None] | None = None,
    reported: Iterable[str] = (),
    neighbours: dict[str, Iterable[str]] | None = None,
) -> GateResult:
    """Run the deterministic checks on what ``run`` left in its work area.

    ``reported`` and ``neighbours`` matter only for a run in a shared checkout
    (see :func:`shared_area`).
    """
    events = list(events)
    area = work_area(run, events)
    if snapshot is None:
        from dodaios.agent_chat.team.workspace import GitWorkspace

        snapshot = GitWorkspace().snapshot
    if area is None:
        folder = str(run.get("workdir") or "")
        if not run.get("start_tree") or not folder:
            return GateResult(
                UNATTRIBUTED,
                reason="the run had no checkout of its own, so nothing can be pinned on it",
            )
        tree = snapshot(folder) or ""
        if not tree:
            return GateResult(UNREADABLE, reason="the checkout could not be read")
        area, why = shared_area(run, reported, tree, neighbours)
        if area is None:
            return GateResult(UNATTRIBUTED, reason=why)
    else:
        tree = snapshot(area.folder) or ""
    if not tree:
        return GateResult(UNREADABLE, area=area, reason="the work area could not be read")
    files, added, deleted = _numstat(area.folder, area.base, tree, area.paths)
    patch = (
        _git(area.folder, *_limited(["diff", "-M", area.base, tree], area.paths))
        if area.paths is None or area.paths else ""
    )
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
    if area.paths is None:
        committed = bool(head_tree) and head_tree == tree
    elif not area.paths:
        committed = bool(head_tree)
    else:
        # In a shared checkout only the run's own files have to be in the commit.
        committed = bool(head_tree) and not _git(
            area.folder, *_limited(["diff", "--name-only", head_tree, tree], area.paths)
        )
    return GateResult(
        status, area=area, tree_id=tree, files=files, added=added, deleted=deleted,
        findings=found, truncated=truncated,
        head_sha=_git(area.folder, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"),
        committed=committed,
    )
