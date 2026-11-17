"""Named agents are retired: a start archives every agent except the lead."""

from __future__ import annotations

from pathlib import Path

from dodaios.society.events import AgentState
from dodaios.society.lead_card import lead_card_section, society_agent_names
from dodaios.society.retirement import retire_named_agents
from dodaios.society.runtime import SocietyRuntime


async def _runtime(data_dir: Path) -> SocietyRuntime:
    runtime = SocietyRuntime(data_dir, seed_starter_team=False)
    await runtime.ensure_started()
    return runtime


async def test_a_start_archives_every_agent_but_the_lead(tmp_path: Path) -> None:
    first = await _runtime(tmp_path)
    try:
        await first.roster.create(name="Scout", focus=["core:search-web"])
        await first.roster.create(name="Builder", focus=["cli:gh"])
        assert set(society_agent_names()) == {"Scout", "Builder"}
    finally:
        await first.close()

    again = await _runtime(tmp_path)
    try:
        for agent_id in ("scout", "builder"):
            agent = await again.roster.get(agent_id)
            assert agent is not None and agent.state is AgentState.ARCHIVED
        lead = await again.roster.get(again.lead_id)
        assert lead is not None and lead.state is not AgentState.ARCHIVED
        # Nothing left for the lead to talk about as "its team".
        assert society_agent_names() == ()
        assert lead_card_section(lead_name="George") == ""
    finally:
        await again.close()


async def test_retiring_twice_archives_nothing_new(tmp_path: Path) -> None:
    runtime = await _runtime(tmp_path)
    try:
        await runtime.roster.create(name="Scout", focus=[])
        assert await retire_named_agents(runtime) == ["Scout"]
        await runtime.roster.refresh()
        assert await retire_named_agents(runtime) == []
    finally:
        await runtime.close()
