"""Named agents are no longer part of the product (2026-11-11).

The person works with ONE agent, Dodaios (the society's lead), and with the
coding agents of the Agentic IDE. The Agents page is gone, but agents a person
made before that still sat on the roster as active: the lead's prompt named
them as "the team you lead" on every turn, tasks were routed to them, and their
notices opened the hidden Agents page.

This runs once per start of the runtime and archives every agent except the
lead. Archiving keeps the agent's record, chats and memory (nothing is
deleted) and switches its routines off, the same as the person archiving it
by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .events import AgentState

log = logging.getLogger(__name__)

__all__ = ["Retirement", "retire_named_agents"]


@dataclass
class Retirement:
    """What one pass archived: the agents' names and how many routines it switched off."""

    names: list[str] = field(default_factory=list)
    routines: int = 0

    def __bool__(self) -> bool:
        return bool(self.names)


async def retire_named_agents(runtime: Any) -> Retirement:
    """Archive every non-lead agent that is not archived yet; report what changed.

    Never raises: an agent that cannot be archived stays as it is and the
    start goes on. The caller tells the person (``lead.post_agents_retired``):
    switching routines off silently is how a standing job stops without a word.
    """
    try:
        agents = runtime.roster.snapshot()
    except Exception:  # noqa: BLE001 - housekeeping, never a start blocker
        log.warning("society: roster unavailable, named agents not retired", exc_info=True)
        return Retirement()
    result = Retirement()
    retired = result.names
    for agent in agents:
        if agent.agent_id == runtime.lead_id or agent.state is AgentState.ARCHIVED:
            continue
        try:
            await runtime.roster.archive(agent.agent_id)
        except Exception:  # noqa: BLE001 - one agent must not stop the others
            log.warning("society: agent %s not archived", agent.agent_id, exc_info=True)
            continue
        retired.append(agent.name)
        result.routines += await _switch_off_routines(runtime, agent.agent_id)
    if retired:
        log.info("society: named agents retired (archived): %s", ", ".join(retired))
    return result


async def _switch_off_routines(runtime: Any, agent_id: str) -> int:
    try:
        task_store, scheduler = runtime.task_services()
    except Exception:  # noqa: BLE001 - routines of archived agents are skipped anyway
        return 0
    if task_store is None:
        return 0
    from .routines import retire_agent_routines

    try:
        return int(await retire_agent_routines(task_store, scheduler, agent_id))
    except Exception:  # noqa: BLE001 - the task runner skips an archived owner's routines
        log.warning("society: routines of %s not switched off", agent_id, exc_info=True)
        return 0
