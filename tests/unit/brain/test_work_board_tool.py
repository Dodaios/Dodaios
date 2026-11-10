"""``work_board``: what runs and who needs the person, summary-first."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from dodaios.brain.tool_gateway import BrainSupervisorToolGateway
from dodaios.brain.work_board_tool import WorkBoardTool
from dodaios.core.protocols import SupervisorToolRequest, ToolResult

_AGENTS = {
    "status": "ok",
    "counts": {"busy": 1, "needs_input": 1, "idle": 3},
    "needs_you": ["Alex (Installer)"],
    "workspaces": [
        {
            "workspace": "Installer",
            "git": {"branch": "feat/x", "ahead": 2},
            "agents": [
                {"name": "Alex", "state": "needs_input"},
                {"name": "Bo", "state": "busy", "job": "refactor"},
                {"name": "Cy", "state": "idle"},
                {"name": "Di", "state": "empty"},
            ],
        }
    ],
}
_MISSIONS = {
    "response": {
        "missions": [
            {"id": "m-1", "prompt": "Build the report " + "x" * 900, "state": "RUNNING"},
            {"id": "m-2", "prompt": "Wait", "state": "WAITING_CAPACITY"},
        ],
        "total": 2,
    }
}
_TASKS = {"response": {"tasks": [{"id": "t-1", "title": "Daily brief", "state": "running"}]}}
_TEAM = {
    "agents": [
        {"agent": "Scout", "state": "working", "task": "Find a VPS"},
        {"agent": "Archivist", "state": "idle"},
    ]
}


class _Fake:
    def __init__(self, name: str, output=None, *, fail: bool = False, boom: bool = False) -> None:
        self.name = name
        self._output, self._fail, self._boom = output, fail, boom
        self.calls: list[dict] = []

    async def execute(self, args, ctx):
        self.calls.append(args)
        if self._boom:
            raise RuntimeError("down")
        if self._fail:
            return ToolResult(False, None, error="HTTP 503: not started")
        return ToolResult(True, self._output)


def _ctx():
    return SimpleNamespace(trace_id=uuid4(), user_utterance="", config={}, memory_read=None)


def _tools(**overrides):
    tools = {
        "workspace-orchestrate": _Fake("workspace-orchestrate", _AGENTS),
        "missions-list": _Fake("missions-list", _MISSIONS),
        "tasks-list": _Fake("tasks-list", _TASKS),
        "society_status": _Fake("society_status", _TEAM),
    }
    tools.update(overrides)
    return tools


async def test_the_board_puts_needs_you_first_and_reads_every_source():
    tools = _tools()
    result = await WorkBoardTool(lambda: tools).execute({}, _ctx())
    board = result.output
    assert next(iter(board)) == "needs_you"
    assert board["needs_you"] == [
        "Alex (Installer)",
        "mission m-2: waiting for subscription capacity",
    ]
    assert tools["society_status"].calls == [{"board": True}]
    assert tools["missions-list"].calls == [{"active": True, "limit": 20}]
    assert board["tasks"] == [{"task_id": "t-1", "title": "Daily brief", "state": "running"}]


async def test_summary_first_drops_idle_agents_and_clips_long_requests():
    tools = _tools()
    board = (await WorkBoardTool(lambda: tools).execute({}, _ctx())).output
    (workspace,) = board["coding_agents"]["workspaces"]
    assert [a["name"] for a in workspace["agents"]] == ["Alex", "Bo"]
    assert workspace["idle_agents"] == 2 and workspace["git"]["branch"] == "feat/x"
    assert len(board["missions"][0]["request"]) <= 200
    assert board["team"] == {
        "working": [{"agent": "Scout", "state": "working", "task": "Find a VPS"}],
        "idle": 1,
    }
    full = (await WorkBoardTool(lambda: tools).execute({"detail": True}, _ctx())).output
    assert len(full["coding_agents"]["workspaces"][0]["agents"]) == 4
    assert len(full["team"]) == 2


async def test_a_failing_or_missing_source_leaves_only_its_own_section_out():
    tools = _tools(**{"missions-list": _Fake("missions-list", fail=True)})
    del tools["society_status"]
    tools["tasks-list"] = _Fake("tasks-list", boom=True)
    board = (await WorkBoardTool(lambda: tools).execute({}, _ctx())).output
    assert "503" in board["missions"]["unavailable"]
    assert board["tasks"] == {"unavailable": "This part could not be read."}
    assert "team" not in board and board["needs_you"] == ["Alex (Installer)"]


def test_the_lead_has_the_board_and_addressed_pane_tools_on_every_seat():
    manager = SimpleNamespace(
        _tools={
            "agentic-ide-prompt": _Fake("agentic-ide-prompt"),
            "agentic-ide-fanout": _Fake("agentic-ide-fanout"),
            "agentic-ide-status": _Fake("agentic-ide-status"),
            "missions-list": _Fake("missions-list"),
        }
    )
    workspace = SimpleNamespace(name="workspace-orchestrate", gateway=object())
    gateway = BrainSupervisorToolGateway(
        manager, workspace_tool=workspace, lead_session=lambda sid: sid == "lead"
    )
    lead = gateway.lead_tools()
    assert {"workspace-orchestrate", "workspace-git", "work_board"} <= set(lead)
    assert "agentic-ide-prompt" not in lead and "agentic-ide-fanout" not in lead
    assert "agentic-ide-status" in lead
    # Other surfaces keep the ambient-pane tools.
    assert "agentic-ide-prompt" in gateway._live_tools()
    assert gateway.is_lead_session("lead") and not gateway.is_lead_session("society:x")


async def test_a_lead_session_catalog_and_execution_use_the_lead_set():
    class _Executor:
        def __init__(self) -> None:
            self.tool = None

        async def execute(self, tool, args, **_):
            self.tool = tool
            return ToolResult(True, {"ok": True})

    executor = _Executor()
    manager = SimpleNamespace(
        _tools={"agentic-ide-prompt": _Fake("agentic-ide-prompt")}, _tool_executor=executor
    )
    gateway = BrainSupervisorToolGateway(
        manager,
        workspace_tool=SimpleNamespace(name="workspace-orchestrate", gateway=object()),
        lead_session=lambda sid: sid == "lead",
    )
    names = {d.name for d in await gateway.session_catalog("lead")}
    assert "work_board" in names and "agentic-ide-prompt" not in names
    other = {d.name for d in await gateway.session_catalog("society:x")}
    assert "work_board" not in other and "agentic-ide-prompt" in other

    request = SupervisorToolRequest(
        trace_id=uuid4(),
        origin="agent-chat",
        user_utterance="",
        config_snapshot={"approval_ref": "agent-chat:lead"},
    )
    await gateway.execute("work_board", {}, request)
    assert isinstance(executor.tool, WorkBoardTool)
