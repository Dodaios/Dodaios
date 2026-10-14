"""Team threads: several coding agents carry one task together, as peers.

One prompt goes to a team of thread sessions on different models. Trusted
Python (``engine.TeamThreads``) owns the order of work: every member plans
alone, the members challenge each other's plans, they agree on one master
plan, one of them builds it and the others review until they approve. In the
planner-and-builder mode one member owns a living plan, one builds it step by
step and the others review every step. Models only write the contributions;
none of them can start another's turn.

``docs/agentic-ide-team-threads.md`` describes the feature,
``docs/adr/0042-team-threads-trusted-coordinator.md`` the design.
"""

from __future__ import annotations

from .engine import Limits, SeatPick, TeamError, TeamThreads
from .store import MODES, PHASES, ROLES, STATES, TeamThreadStore

__all__ = [
    "MODES",
    "PHASES",
    "ROLES",
    "STATES",
    "Limits",
    "SeatPick",
    "TeamError",
    "TeamThreadStore",
    "TeamThreads",
]
