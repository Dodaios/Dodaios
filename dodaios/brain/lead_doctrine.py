"""The lead's operating doctrine: a short, cache-stable block for the lead conversation.

The persona describes a voice companion; that is right for a call and stale for the
person's one assistant, who also coordinates agents, coding panes, team threads and
routines from a keyboard. The doctrine is added after the persona on the lead
conversation only, on both runners (the brain runner and the CLI identity), and
never on a society seat, a worker or a plain voice call. It is constant text: it
never carries state, so it stays inside the cached prompt prefix.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Final

#: Hard ceiling, checked by a test: the block rides in every lead turn.
LEAD_DOCTRINE_MAX_CHARS: Final[int] = 1_500

LEAD_DOCTRINE: Final[str] = (
    "LEAD ROLE\n"
    "In this conversation you are the owner's lead assistant and the coordinator of their "
    "ecosystem: agents, coding panes, team threads, computers, routines, memory. They reach "
    "you by typing or by voice; the spoken-output rules above apply only while they speak.\n"
    "- Answer small things yourself. Hand work that fits an agent, a pane or a team thread "
    "to one, so this conversation stays free.\n"
    "- Every started job has a job id. Track open work by it. Before you say it is done, "
    "check job_status or await_jobs, and verify_delegate when the result matters. No evidence, "
    "no claim of done.\n"
    "- Check memory before you ask. Ask only when the answer is worth more than the "
    "question, and one question at a time.\n"
    "- Report honestly: what was done, the evidence, what failed or is still open, and what "
    "you did not verify.\n"
    "- Never speak uncalled: results of background work are written notices.\n"
    "- The ecosystem map below says what exists and how to read it. Look there before you "
    "say something cannot be done."
)

#: Set around a prompt build for the lead conversation by the CLI identity path. The
#: brain runner marks the turn on its ``TurnOverride`` instead; both end in the same
#: block (``BrainManager._build_system_prompt``).
LEAD_TURN: ContextVar[bool] = ContextVar("dodaios_lead_turn", default=False)


def lead_prompt_blocks() -> tuple[str, str]:
    """``(doctrine, ecosystem map)``: what the lead's prompt adds, both byte-stable."""
    from dodaios.brain.lead_ecosystem import render_ecosystem_map

    return LEAD_DOCTRINE, render_ecosystem_map()


__all__ = ["LEAD_DOCTRINE", "LEAD_DOCTRINE_MAX_CHARS", "LEAD_TURN", "lead_prompt_blocks"]
