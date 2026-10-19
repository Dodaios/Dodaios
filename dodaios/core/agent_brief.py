"""How Jarvis words a task it hands to another agent.

Every hand-off surface (workspace coding panes, the agent society, the live
voice backends) writes its own brief, and none of them said what that brief
should ask for. Left alone, the model read "check", "look into", "deep dive"
or "audit" as a request for a report and wrote "READ-ONLY" or "no changes"
into the brief on its own, so the agent found the problem and stopped (live
2026-10-02: "have it look at what is wrong with our plugins" became
"Autonomously perform a careful, evidence-based, READ-ONLY audit").
One rule, shared by every surface, so they cannot drift apart.
"""

from __future__ import annotations

from typing import Final

#: Appended to every tool description / instruction that makes Jarvis write a
#: brief for another agent. Kept short: it rides in the voice tool catalog,
#: which has a byte budget (``dodaios.live.tools._CATALOG_BYTE_BUDGET``).
AGENT_BRIEF_RULE: Final[str] = (
    "Brief another agent with a work order: find the cause, make the change, verify, then "
    "report back what changed and any decision the user has to make; when blocked, report "
    "that too. 'Check' or 'deep dive' include fixing; never add read-only limits unless the "
    "user explicitly asked for analysis only."
)

__all__ = ["AGENT_BRIEF_RULE"]
