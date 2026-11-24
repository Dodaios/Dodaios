"""Headless voice management uses the same persisted roster as the Agents UI.

No provider, microphone, GPU, native API or background worker is needed to
create/reconfigure/read a persistent agent. Assignment remains scheduler-owned.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from dodaios.commands.registry import get_command
from dodaios.plugins.tool.app_command import AppCommandTool
from dodaios.plugins.tool.delegate_to_agent import DelegateToAgentTool, SocietyStatusTool
from dodaios.society.runtime import SocietyRuntime
from dodaios.ui.web.society_routes import router


@pytest.fixture
async def society(tmp_path):
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False)
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    loader = AppCommandTool(transport=httpx.ASGITransport(app=app))
    commands = {tool.name: tool for tool in loader.expand()}
    try:
        yield runtime, commands
    finally:
        await runtime.close()


def context():
    return SimpleNamespace(config={"output_language": "en"}, trace_id=uuid4())


async def test_management_rejects_an_invalid_model(society):
    runtime, commands = society
    await runtime.ensure_started()
    await runtime.roster.create(name="Scout")
    model = await commands["society-switch-agent-model"].execute(
        {
            "agent_id": "scout",
            "provider": "nonexistent-provider",
        },
        context(),
    )
    assert not model.success and "422" in model.error


def test_management_is_supervisor_only_and_degrades_without_server():
    for name in (
        "society-agent-catalog",
        "society-switch-agent-model",
    ):
        command = get_command(name)
        assert command is not None and not command.worker_allowed


async def test_management_unavailable_server_returns_honest_error():
    commands = {tool.name: tool for tool in AppCommandTool(app_resolver=lambda: None).expand()}
    result = await commands["society-agent-catalog"].execute({}, context())
    assert not result.success and "server is not available" in result.error


@pytest.mark.parametrize(
    "terminal_event,expected_state",
    [
        ("MissionApproved", "done"),
        ("MissionFailed", "blocked"),
    ],
)
async def test_voice_assignment_tracks_fallback_mission_bridge(
    tmp_path, terminal_event, expected_state
):
    from dodaios.society.events import MsgType

    class FakeManager:
        async def dispatch(self, **kwargs):
            return "mission-1"

    runtime = SocietyRuntime(tmp_path, mission_manager=lambda: FakeManager())
    try:
        await runtime.ensure_started()
        await runtime.roster.create(name="Scout")
        result = await DelegateToAgentTool(runtime_resolver=lambda: runtime).execute(
            {"agent": "Scout", "task": "Compare suppliers."},
            context(),
        )
        assert result.success, result.error
        assignment_id, trace_id = result.output["assignment_id"], result.output["trace_id"]
        # Same mission trace, wrong agent/run: neither is proof for this assignment.
        await runtime.say(
            from_agent="other-agent",
            to_agent="jarvis",
            text="Unrelated result.",
            trace_id="mission:mission-1",
            msg_type=MsgType.RESULT,
            payload={"run_id": "mission-1", "status": "done"},
        )
        await runtime.say(
            from_agent="scout",
            to_agent="jarvis",
            text="Another run.",
            trace_id="mission:mission-1",
            msg_type=MsgType.RESULT,
            payload={"run_id": "mission-2", "status": "done"},
        )
        status_tool = SocietyStatusTool(runtime_resolver=lambda: runtime)
        pending = await status_tool.execute(
            {
                "assignment_id": assignment_id,
                "trace_id": trace_id,
            },
            context(),
        )
        assert pending.output["state"] == "running"
        await runtime.bridge.on_mission_envelope(
            SimpleNamespace(
                mission_id="mission-1",
                payload=SimpleNamespace(event_type=terminal_event, summary="Supplier comparison."),
            )
        )
        status = await status_tool.execute(
            {
                "assignment_id": assignment_id,
                "trace_id": trace_id,
            },
            context(),
        )
        assert status.output["state"] == expected_state
        final = status.output["events"][-1]
        assert final["trace_id"] == "mission:mission-1"
        assert final["parent_event_id"] is None
        assert final["payload"]["output"] == ["mission:mission-1"]
        assert final["payload"]["done"] == "Supplier comparison."
    finally:
        await runtime.close()
