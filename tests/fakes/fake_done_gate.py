"""Agent done gate state on disk, and a git locator that never runs git.

``FakeRepoLocator`` stands in for ``done_gate_status.locate``: each folder maps
to the git common dir and branch a test chose, and every question is counted.
``write_session`` writes a session file the way ``scripts/agent_done_gate.py``
does, so the reader is tested against the gate's real file shape.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dodaios.agentic_ide.done_gate_status import STATE_DIR, RepoInfo, safe_name


@dataclass
class FakeRepoLocator:
    repos: dict[str, RepoInfo] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    def add(self, folder: str | Path, common_dir: Path | None, branch: str = "") -> None:
        self.repos[os.path.normcase(os.path.abspath(str(folder)))] = RepoInfo(common_dir, branch)

    def __call__(self, folder: str) -> RepoInfo:
        self.asked.append(folder)
        return self.repos.get(os.path.normcase(os.path.abspath(folder)), RepoInfo(None))


def iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds")


def write_session(
    common_dir: Path,
    session: str,
    *,
    verdict: str,
    at: float,
    reason: str = "",
    next_step: str = "",
    pr: int | None = None,
    branch: str = "",
    cwd: str | Path = "",
    mtime: float | None = None,
) -> Path:
    """One ``sessions/<session>.json`` with a ``last`` record, as the gate writes it."""
    path = common_dir / STATE_DIR / "sessions" / f"{safe_name(session)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "branches": [branch] if branch else [],
        "last": {
            "verdict": verdict,
            "reason": reason,
            "next": next_step,
            "pr": pr,
            "branch": branch,
            "cwd": str(cwd),
            "at": iso(at),
        },
    }
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path
