"""Every lead-visible status/list tool stays valid JSON inside both bounds.

Seeded large fixture: 60 agents with many long events, and 150 missions with
long prompts. The brain path keeps its 100 000-character maximum; the MCP path
uses the receiving CLI's limit. Neither may leave invalid JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.brain.tool_use_loop import _MAX_TOOL_RESULT_CHARS, _cap_tool_result_json
from dodaios.mcp.dodaios_tools_server import _render, mcp_max_output_chars
from dodaios.missions.manager import MissionManager
from dodaios.plugins.tool.delegate_to_agent import DelegateToAgentTool, SocietyStatusTool
from dodaios.society.runtime import SocietyRuntime
from dodaios.ui.web.missions_routes import router as missions_router
from tests.unit.plugins.tool.test_delegate_to_agent import FakeChat


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(trace_id=uuid4(), user_utterance="", config={}, memory_read=None)


def _check_both_paths(output: object) -> None:
    payload = {"success": True, "output": output}
    brain_text = _cap_tool_result_json(payload)
    assert len(brain_text) <= _MAX_TOOL_RESULT_CHARS
    json.loads(brain_text)
    mcp_text = _render(SimpleNamespace(success=True, error=None, output=output))
    assert len(mcp_text) <= mcp_max_output_chars()
    json.loads(mcp_text)


@pytest.fixture
async def big_society(tmp_path: Path):
    chat = FakeChat(tmp_path / "agent_chat.db")
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path / "data")))
    rt = SocietyRuntime(tmp_path, chat_service=lambda: chat, cfg=lambda: cfg)
    await rt.ensure_started()
    for index in range(60):
        await rt.roster.create(name=f"Agent{index}", provider="openai", model="gpt-5.2")
    delegate = DelegateToAgentTool(runtime_resolver=lambda: rt)
    for index in range(60):
        for part in range(3):
            brief = f"Job {part}: " + "long brief text " * 1_000
            await delegate.execute({"agent": f"Agent{index}", "task": brief}, _ctx())
    try:
        yield rt
    finally:
        await rt.close()


async def test_every_society_status_view_is_valid_json_inside_both_bounds(big_society):
    status = SocietyStatusTool(runtime_resolver=lambda: big_society)
    views = [
        {},
        {"board": True},
        {"mode": "agent", "agent": "Agent7", "limit": 100},
        {"mode": "events", "limit": 100},
        {"mode": "events", "agent": "Agent7", "limit": 100},
    ]
    for args in views:
        result = await status.execute(args, _ctx())
        assert result.success, (args, result.error)
        _check_both_paths(result.output)
    latest = await status.execute({"agent": "Agent3", "latest_assignment": True}, _ctx())
    assert latest.success
    _check_both_paths(latest.output)


def test_the_missions_list_with_many_long_prompts_stays_valid_json(tmp_path: Path):
    import asyncio

    manager = MissionManager(tmp_path / "missions.db")
    app = FastAPI()
    app.include_router(missions_router)
    app.state.mission_manager = manager
    asyncio.run(manager.start())
    try:
        with TestClient(app) as client:
            for index in range(150):
                client.post(
                    "/api/missions/dispatch", json={"prompt": f"M{index} " + "detail " * 800}
                )
            body = client.get("/api/missions?limit=100").json()
        assert len(body["missions"]) == 100 and body["total"] == 150 and body["next_cursor"]
        _check_both_paths({"command_id": "missions-list", "response": body})
    finally:
        asyncio.run(manager.stop())
