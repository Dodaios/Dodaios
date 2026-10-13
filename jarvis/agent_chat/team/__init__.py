"""Team threads: several coding agents carry one task together, as peers.

One prompt goes to a team of thread sessions on different models. Trusted
Python (``engine.TeamThreads``) owns the order of work: every member plans
alone, the members challenge each other's plans, they agree on one master
plan, one of them builds it and the others review until they approve. Models
only write the contributions; none of them can start another's turn.

``docs/agentic-ide-team-threads.md`` describes the feature,
``docs/adr/0042-team-threads-trusted-coordinator.md`` the design.
"""

from __future__ import annotations

from .engine import Limits, SeatPick, TeamError, TeamThreads
from .store import PHASES, STATES, TeamThreadStore

__all__ = [
    "PHASES",
    "STATES",
    "Limits",
    "SeatPick",
    "TeamError",
    "TeamThreadStore",
    "TeamThreads",
]
