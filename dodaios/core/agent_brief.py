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
"""

from __future__ import annotations

from typing import Final

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
    "asked for analysis only."
)

__all__ = ["AGENT_BRIEF_RULE"]
