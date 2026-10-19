"""The agent done gate's last verdict for each pane, read from its own record.

``scripts/agent_done_gate.py`` runs from each coding CLI's Stop hook and
decides whether the agent may stop yet. On every check it writes the session's
last verdict to ``<git common dir>/agent-done-gate/sessions/<session>.json``
under ``"last"``::

    {"verdict", "reason", "next", "pr", "branch", "cwd", "at"}

This module only reads those files. It never asks GitHub and never runs the
gate: the header shows what the gate itself last said.

A pane is matched to its record by (:func:`board`):

1. its agent session id, when the app knows it (Claude Code, Codex, Kimi,
   OpenCode, ... through ``agent_sessions``): that session's file and no
   other, however old;
2. otherwise by folder or branch: the newest record, at most
   :data:`FALLBACK_MAX_AGE_S` old, whose ``cwd`` is the pane's folder or whose
   ``branch`` is the pane's branch. Records of sessions another pane of the
   workspace is known to own are never borrowed.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dodaios.agentic_ide import git_overview

#: The gate's folder inside the git common dir (``STATE_DIR`` in the gate).
STATE_DIR = "agent-done-gate"
#: The verdicts a header shows. NONE and HOLD stay quiet: nothing to land, or
#: a person asked for the branch to stay local.
SHOWN = frozenset({"DONE", "WAIT", "FIX", "STUCK"})
#: A record matched only by folder or branch is ignored once it is this old.
FALLBACK_MAX_AGE_S = 6 * 3600
#: How long a folder's git common dir and branch are reused before asking git again.
REPO_TTL_S = 30.0
#: Long reasons are cut; the tooltip has room for a sentence or two, not a log.
MAX_TEXT = 600


@dataclass(frozen=True, slots=True)
class PaneGateRecord:
    """What is known about one pane: its name, its folder, its session, its branch."""

    pane: str
    folder: str
    session_id: str = ""
    #: The worktree branch Jarvis created for the pane, when it did.
    branch: str = ""


@dataclass(frozen=True, slots=True)
class GateVerdict:
    verdict: str
    reason: str
    next: str
    pr: int | None
    branch: str
    at: str
    #: ``session``: the pane's own session wrote it; ``folder``: matched by
    #: folder or branch, so it may be a neighbouring session's word.
    matched: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RepoInfo:
    common_dir: Path | None
    branch: str = ""


Locate = Callable[[str], RepoInfo]


def safe_name(session: str) -> str:
    """The file name the gate gives a session id (``_safe`` in the gate)."""
    return re.sub(r"[^\w.-]", "_", session)[:120]


def _norm(folder: str) -> str:
    if not folder:
        return ""
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(folder)))
    except (OSError, ValueError):  # an unreadable path matches no record; the label stays empty
        return ""


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:  # a record without a valid time is not shown, by design
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.timestamp()


def _text(value: Any) -> str:
    return value.strip()[:MAX_TEXT] if isinstance(value, str) else ""


def parse_last(data: Any) -> dict[str, Any] | None:
    """The ``last`` record of a session file, cleaned, or None if it is not one."""
    if not isinstance(data, dict):
        return None
    last = data.get("last")
    if not isinstance(last, dict):
        return None
    verdict = _text(last.get("verdict")).upper()
    at = _text(last.get("at"))
    if not verdict or _timestamp(at) is None:
        return None
    pr = last.get("pr")
    return {
        "verdict": verdict,
        "reason": _text(last.get("reason")),
        "next": _text(last.get("next")),
        "pr": pr if isinstance(pr, int) and not isinstance(pr, bool) and pr > 0 else None,
        "branch": _text(last.get("branch")),
        "cwd": _text(last.get("cwd")),
        "at": at,
    }


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return parse_last(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):  # the gate may be mid-write or absent; next poll reads it
        return None


def _verdict(last: dict[str, Any], matched: str) -> GateVerdict | None:
    if last["verdict"] not in SHOWN:
        return None
    return GateVerdict(
        verdict=last["verdict"],
        reason=last["reason"],
        next=last["next"],
        pr=last["pr"],
        branch=last["branch"],
        at=last["at"],
        matched=matched,
    )


# ------------------------------------------------------------------ git


_repos: dict[str, tuple[float, RepoInfo]] = {}
_repos_lock = threading.Lock()


def locate(folder: str) -> RepoInfo:
    """The git common dir and checked-out branch of ``folder``, briefly cached."""
    key = _norm(folder)
    now = time.monotonic()
    with _repos_lock:
        hit = _repos.get(key)
        if hit and now - hit[0] < REPO_TTL_S:
            return hit[1]
    out = (
        git_overview._out(
            ["rev-parse", "--path-format=absolute", "--git-common-dir", "--abbrev-ref", "HEAD"],
            Path(folder),
        )
        if key and Path(folder).is_dir()
        else None
    )
    lines = (out or "").splitlines()
    info = RepoInfo(
        common_dir=Path(lines[0].strip()) if lines and lines[0].strip() else None,
        branch=lines[1].strip() if len(lines) > 1 and lines[1].strip() != "HEAD" else "",
    )
    with _repos_lock:
        _repos[key] = (now, info)
    return info


def forget_repos() -> None:
    """Drop the cached git answers; tests only."""
    with _repos_lock:
        _repos.clear()


# ------------------------------------------------------------------ board


def _recent(sessions: Path, now: float) -> list[tuple[str, dict[str, Any]]]:
    """Every (file stem, record) in ``sessions`` written within the fallback window."""
    found: list[tuple[str, dict[str, Any]]] = []
    try:
        entries = list(os.scandir(sessions))
    except OSError:  # no sessions folder means the gate never ran in this repository
        return found
    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        try:
            if now - entry.stat().st_mtime > FALLBACK_MAX_AGE_S:
                continue
        except OSError:  # a file deleted between listing and stat is simply gone
            continue
        last = _read(Path(entry.path))
        stamp = _timestamp(last["at"]) if last else None
        if last and stamp is not None and now - stamp <= FALLBACK_MAX_AGE_S:
            found.append((entry.name[: -len(".json")], last))
    return found


def board(
    records: Iterable[PaneGateRecord],
    *,
    now: float | None = None,
    find_repo: Locate | None = None,
) -> dict[str, dict[str, Any] | None]:
    """The gate's last shown verdict per pane name (None when there is none to show)."""
    now = time.time() if now is None else now
    find_repo = find_repo or locate
    records = list(records)
    owned = {safe_name(r.session_id) for r in records if r.session_id}
    recent: dict[Path, list[tuple[str, dict[str, Any]]]] = {}
    answer: dict[str, dict[str, Any] | None] = {}
    for record in records:
        repo = find_repo(record.folder)
        if repo.common_dir is None:
            answer[record.pane] = None
            continue
        sessions = repo.common_dir / STATE_DIR / "sessions"
        if record.session_id:
            last = _read(sessions / f"{safe_name(record.session_id)}.json")
            shown = _verdict(last, "session") if last else None
            answer[record.pane] = shown.to_dict() if shown else None
            continue
        if sessions not in recent:
            recent[sessions] = _recent(sessions, now)
        folder = _norm(record.folder)
        branches = {b for b in (record.branch, repo.branch) if b}
        best: dict[str, Any] | None = None
        best_at = float("-inf")
        for stem, last in recent[sessions]:
            if stem in owned:
                continue
            if not ((folder and _norm(last["cwd"]) == folder) or last["branch"] in branches):
                continue
            stamp = _timestamp(last["at"]) or 0.0
            if stamp > best_at:
                best, best_at = last, stamp
        shown = _verdict(best, "folder") if best else None
        answer[record.pane] = shown.to_dict() if shown else None
    return answer
