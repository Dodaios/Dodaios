"""One board for everything running: call tasks, coding agents, missions, the team."""

from __future__ import annotations

import pytest

from dodaios.core.protocols import SupervisorToolDescriptor, ToolResult
from dodaios.live.state import LiveLedger
from dodaios.live.tools import LiveTools
from tests.fakes.fake_native_voice import FakeToolGateway

_AGENTS = {
    "status": "ok",
    "counts": {"busy": 1, "needs_input": 1},
    "needs_you": ["Alex (Installer)"],
    "workspaces": [{"workspace": "Installer", "git": {"branch": "main"}, "agents": []}],
    "note": "explains the words",
}
_MISSIONS = {
    "command_id": "missions-list",
    "summary": "List missions",
    "response": {
        "missions": [
            {"id": "m-1", "prompt": "Build the report", "state": "RUNNING", "cost_usd": 0.0},
        ],
        "total": 1,
    },
}
_TEAM = {"agents": [{"agent": "Scout", "state": "working", "task": "Find a VPS"}]}


def _tool(name: str) -> SupervisorToolDescriptor:
    return SupervisorToolDescriptor(name, f"{name}.", {"type": "object"}, "safe")


@pytest.fixture
def board(tmp_path):
    def build(*names: str):
        gateway = FakeToolGateway(tuple(_tool(name) for name in names))
        gateway.results = {
            "workspace-orchestrate": ToolResult(True, _AGENTS),
            "missions-list": ToolResult(True, _MISSIONS),
            "society_status": ToolResult(True, _TEAM),
        }
        ledger = LiveLedger(tmp_path / f"live-{len(ledgers)}.sqlite3")
        ledgers.append(ledger)
        return LiveTools(gateway, ledger, "call", language="en", backend_model=""), gateway

    ledgers: list[LiveLedger] = []
    yield build
    for ledger in ledgers:
        ledger.close()


@pytest.mark.asyncio
async def test_one_call_shows_every_kind_of_running_work(board):
    tools, gateway = board("workspace-orchestrate", "missions-list", "society_status")
    listed = await tools.execute("c1", "task_status", {}, tools.revision)
    assert listed["success"] is True and listed["tasks"] == []
    assert listed["coding_agents"]["counts"] == {"busy": 1, "needs_input": 1}
    assert "note" not in listed["coding_agents"]
    assert listed["missions"] == [
        {"mission_id": "m-1", "state": "RUNNING", "request": "Build the report"}
    ]
    assert listed["team"] == _TEAM["agents"]
    assert listed["needs_you"] == ["Alex (Installer)"]
    assert sorted(gateway.calls) == [
        ("missions-list", {"active": True, "limit": 20}),
        ("society_status", {"board": True}),
        ("workspace-orchestrate", {"action": "status"}),
    ]


@pytest.mark.asyncio
async def test_a_source_the_install_does_not_have_is_left_out(board):
    tools, gateway = board("workspace-orchestrate")
    listed = await tools.execute("c1", "task_status", {}, tools.revision)
    assert "coding_agents" in listed
    assert "missions" not in listed and "team" not in listed
    assert [name for name, _ in gateway.calls] == ["workspace-orchestrate"]


@pytest.mark.asyncio
async def test_a_failing_source_says_so_and_the_rest_still_answers(board):
    tools, gateway = board("workspace-orchestrate", "missions-list", "society_status")
    gateway.results["missions-list"] = ToolResult(False, None, error="HTTP 503: not started")
    gateway.results["society_status"] = ToolResult(True, "Your agents: Scout.")  # another shape

    async def explode(name, arguments, request):
        if name == "workspace-orchestrate":
            raise RuntimeError("registry gone")
        return await original(name, arguments, request)

    original, gateway.execute = gateway.execute, explode
    listed = await tools.execute("c1", "task_status", {}, tools.revision)
    assert listed["success"] is True
    assert listed["coding_agents"] == {"unavailable": "This part could not be read."}
    assert listed["missions"] == {"unavailable": "HTTP 503: not started"}
    assert listed["team"] == {"unavailable": "Your agents: Scout."}
    assert listed["needs_you"] == []


@pytest.mark.asyncio
async def test_scope_call_reads_nothing_outside_this_call(board):
    tools, gateway = board("workspace-orchestrate", "missions-list", "society_status")
    listed = await tools.execute("c1", "task_status", {"scope": "call"}, tools.revision)
    assert listed == {"success": True, "tasks": [], "needs_you": []}
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_the_board_is_a_read_and_is_declared_with_its_scope(board):
    tools, _gateway = board("workspace-orchestrate")
    assert tools._reads_only("task_status", {}) is True
    assert tools._reads_only("task_status", {"scope": "call"}) is True
    assert tools._reads_only("task_status", {"cancel": "task-1"}) is False
    declared = next(d for d in tools.declarations() if d["name"] == "task_status")
    assert declared["parameters"]["properties"]["scope"]["enum"] == ["all", "call"]
    assert "coding agent" in declared["description"]
