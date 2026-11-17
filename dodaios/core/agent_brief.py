"""How Jarvis words a task it hands to another agent.

Every hand-off surface (workspace coding panes, the agent society, the live
voice backends) writes its own brief, and none of them said what that brief
should ask for. Left alone, the model read "check", "look into", "deep dive"
or "audit" as a request for a report and wrote "READ-ONLY" or "no changes"
into the brief on its own, so the agent found the problem and stopped (live
2026-10-02: "have it look at what is wrong with our plugins" became
"Autonomously perform a careful, evidence-based, READ-ONLY audit").
It also carries the core of the ``agent-brief`` builtin skill, because the
lead writes most briefs straight into a tool field. Live 2026-11-16: the
guidance sat only on ``delegate``; the lead called ``workspace-orchestrate``
directly and kept writing long German step scripts with prescribed fixes.
One rule, shared by every surface, so they cannot drift apart.

A brief also used to hold the agent back at the end. The lead wrote git
brakes of its own into it ("do not merge", "do not push", "open the PR with
the needs-human label", "work in your own worktree, change nothing in the main
folder", "no git worktree prune"), and the agent stopped short of shipping.
The maintainer (2026-11-17): he no longer reads, writes or reviews code and
trusts the agents; when the work is done the agent should check it itself and
ship it. So the default is the finished job (``SHIP_DEFAULT``), git limits come
only from the person (in the request or in their standing brief wishes,
``dodaios.core.brief_wishes``), and the limits that are not about git stay
whenever a task touches them (``REAL_LIMITS``).
"""

from __future__ import annotations

from typing import Final

#: What "done" means for a change unless the person said otherwise: the agent
#: checks its own work and ships it the way the repository lands work.
SHIP_DEFAULT: Final[str] = (
    "A change ends shipped: after its own review, with tests and CI green, the agent "
    "commits, pushes and merges it itself. Add no git limits (no push or merge, hold "
    "labels, worktree or folder rules) unless the person asked for them, in the request "
    "or in their standing brief wishes."
)

#: The limits that are not about git and hold whenever a task touches them.
REAL_LIMITS: Final[str] = (
    "Name the real limits only when a task touches them, and keep them unless the person "
    "asked for that very step: nothing posted or sent in their name, no payments, no "
    "untrusted code run with their real credentials."
)

#: Appended to every tool description / instruction that makes Jarvis write a
#: brief for another agent. Kept short: it rides in the voice tool catalog,
#: which has a byte budget (``dodaios.live.tools._CATALOG_BYTE_BUDGET``).
AGENT_BRIEF_RULE: Final[str] = (
    "The agent sees only this brief, never this chat. Lead with the "
    "outcome and why it matters, give what it cannot see (the person's words and errors "
    "verbatim, files, decisions made), a checkable done and only the limits the person set; "
    "state the goal, never a step script or a guessed fix (full guide: skill:agent-brief). "
    "It is a work order: find the cause, make the change, verify, then report back what "
    "changed and any decision the user has to make; when blocked, report that too. 'Check' "
    "or 'deep dive' include fixing; never add read-only limits unless the user explicitly "
    "asked for analysis only. " + SHIP_DEFAULT + " " + REAL_LIMITS
)

__all__ = ["AGENT_BRIEF_RULE", "REAL_LIMITS", "SHIP_DEFAULT"]
