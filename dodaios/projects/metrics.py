"""The long-horizon measure: multi-session project completion rate and median duration.

A project counts as multi-session when evidence moved on two or more calendar days or
two or more chat sessions touched it (the lead is one endless conversation, so days
carry most of the signal). Among those:

* completion rate = completed / (completed + abandoned + stalled), where stalled is an
  open project with no progress for its stall window, so a project nobody finished and
  nobody closed counts against the score instead of vanishing;
* median duration = median days from creation to completion, over completed projects.

Read-only and model-free: it is a component of the agent score (``dodaios.evals.agent_score``).
"""

from __future__ import annotations

import statistics
from typing import Any

from .models import DAY_MS, Project, now_ms
from .store import ProjectStore


def is_multi_session(project: Project) -> bool:
    return len(project.days) >= 2 or len(project.sessions) >= 2


def project_metrics(store: ProjectStore, *, now: int | None = None) -> dict[str, Any]:
    now = now_ms() if now is None else now
    projects = [p for p in store.list(limit=100_000) if is_multi_session(p)]
    completed = [p for p in projects if p.status == "complete"]
    abandoned = [p for p in projects if p.status == "abandoned"]
    open_ = [p for p in projects if not p.is_closed]
    stalled = [p for p in open_ if now - p.last_progress_ms >= p.stall_days * DAY_MS]
    decided = len(completed) + len(abandoned) + len(stalled)
    durations = [(p.closed_ms - p.created_ms) / DAY_MS for p in completed if p.closed_ms]
    return {
        "multi_session_projects": len(projects),
        "completed": len(completed),
        "abandoned": len(abandoned),
        "open": len(open_) - len(stalled),
        "stalled": len(stalled),
        "completion_rate": (len(completed) / decided) if decided else None,
        "median_days_to_complete": statistics.median(durations) if durations else None,
    }
