"""One lead on every seat: the brain seat, the CLI seat's MCP catalog and voice agree.

The only differences are the ones ``dodaios.brain.lead_manifest`` names.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dodaios.agent_chat import surface_kits
from dodaios.agent_chat import tools as folder
from dodaios.brain.lead_manifest import LEAD_MANIFEST, LEAD_SPAWN_TOOLS
from dodaios.brain.tool_gateway import BrainSupervisorToolGateway
from dodaios.core import runtime_refs
from dodaios.core.protocols import ToolResult
from dodaios.mcp import dodaios_tools_server as server


class _Tool:
    risk_tier = "safe"
    is_action_tool = False
    schema: dict = {"type": "object", "properties": {}}
    description = "x"

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, args, ctx):
        return ToolResult(True, {})


#: A live registry the way the app has it: the shared tools, the ambient-pane
#: prompt tools, the spawn vehicle, the team relay and a screen primitive.
_LIVE = (
    "spawn-worker",
    "delegate-to-agent",
    "message_agent",
    "society_status",
    "missions-list",
    "job_status",
    "await_jobs",
    "run_shell",
    "search_web",
    "agentic-ide-prompt",
    "agentic-ide-fanout",
    "agentic-ide-status",
    "computer_use",
    "click",
)


def _gateway(live=_LIVE):
    manager = SimpleNamespace(
        _tools={name: _Tool(name) for name in live},
        _config=SimpleNamespace(computer_use=SimpleNamespace(enabled=True)),
    )
    workspace = _Tool("workspace-orchestrate")
    workspace.gateway = object()
    connect = _Tool("society_request_connect")
    ask = _Tool("society_ask_user")
    takeover = _Tool("request_browser_takeover")
    secret = _Tool("society_request_credential")
    login = _Tool("society_request_login")
    return BrainSupervisorToolGateway(
        manager,
        workspace_tool=workspace,
        lead_session=lambda sid: sid == "lead",
        lead_hands=lambda sid: {
            connect.name: connect, ask.name: ask, takeover.name: takeover, secret.name: secret,
            login.name: login,
        },
    )


async def _wire_names(gateway, session_id: str) -> set[str]:
    runtime_refs.set_supervisor_tool_gateway(gateway)
    token = server.CHAT_SESSION_REF.set(session_id)
    try:
        return set((await server._session_wire_catalog()).keys())
    finally:
        server.CHAT_SESSION_REF.reset(token)
        runtime_refs.set_supervisor_tool_gateway(None)


def _brain_seat_names(gateway, monkeypatch) -> set[str]:
    """The tools the brain seat's turn has: the kit's hands and the manager's, filtered."""
    connect = _Tool("society_request_connect")
    monkeypatch.setattr(
        "dodaios.society.connect_tool.lead_connect_tools", lambda session: {connect.name: connect}
    )
    ask = _Tool("society_ask_user")
    monkeypatch.setattr(
        "dodaios.society.ask_tool.lead_ask_tools", lambda session: {ask.name: ask}
    )
    takeover = _Tool("request_browser_takeover")
    monkeypatch.setattr(
        "dodaios.society.browser.takeover_tool.lead_takeover_tools",
        lambda session=None: {takeover.name: takeover},
    )
    secret = _Tool("society_request_credential")
    monkeypatch.setattr(
        "dodaios.society.credential_tool.lead_credential_tools",
        lambda session: {secret.name: secret},
    )
    login = _Tool("society_request_login")
    monkeypatch.setattr(
        "dodaios.society.login_tool.lead_login_tools", lambda session: {login.name: login}
    )
    monkeypatch.setattr("dodaios.society.browser.tool.lead_browser_tools", lambda session=None: {})
    runtime_refs.set_supervisor_tool_gateway(gateway)
    try:
        kit_hands = surface_kits._jarvis_tools(None, None, SimpleNamespace(session_id="lead"))
    finally:
        runtime_refs.set_supervisor_tool_gateway(None)
    select = surface_kits._jarvis_filter(None)
    return set(select({**gateway._live_tools(), **kit_hands}))


async def test_the_lead_is_the_same_on_the_brain_seat_the_cli_seat_and_voice(monkeypatch):
    gateway = _gateway()
    cli = await _wire_names(gateway, "lead")
    brain = _brain_seat_names(gateway, monkeypatch) - LEAD_MANIFEST.brain_seat_only
    voice = {d.name for d in gateway.voice_catalog()}
    live = set(gateway._live_tools())

    assert cli == brain
    assert cli == set(LEAD_MANIFEST.expected_lead_from_voice(voice, live))
    # What the person was promised: delegation, the board, the team, addressed panes.
    assert {
        "spawn-worker",
        "job_status",
        "await_jobs",
        "work_board",
        "ask_agent",
        "product_help",
        "workspace-orchestrate",
        "workspace-git",
        "society_request_connect",
        "request_browser_takeover",
        # A question that belongs to the person opens the question card.
        "society_ask_user",
        # A secret the person gives goes into the vault through the secure field.
        "society_request_credential",
        # A website login, also one a team agent's routine needs, through the login card.
        "society_request_login",
        # Multi-day work and what the lead looks after with no end date.
        "project",
        "standing_task",
    } <= cli
    assert "standing_task" not in voice  # a call hands that to the chat

async def test_the_older_spawn_vehicles_are_not_offered_to_the_lead_over_mcp():
    gateway = _gateway((*_LIVE, "multi-spawn", "dispatch-to-harness", "dispatch-with-review"))
    names = await _wire_names(gateway, "lead")
    assert "spawn-worker" in names
    assert not {"multi-spawn", "dispatch-to-harness", "dispatch-with-review"} & names


async def test_only_the_lead_keeps_its_spawn_tools_over_mcp():
    gateway = _gateway()
    assert LEAD_SPAWN_TOOLS & await _wire_names(gateway, "lead")
    for session_id in ("society:scout", "agent-thread-1"):
        names = await _wire_names(gateway, session_id)
        assert not LEAD_SPAWN_TOOLS & names, session_id


async def test_a_worker_call_to_a_spawn_tool_is_still_refused(monkeypatch):
    gateway = _gateway()
    runtime_refs.set_supervisor_tool_gateway(gateway)
    try:
        assert server._withheld_for("society:scout") >= LEAD_SPAWN_TOOLS
        assert server._withheld_for("task-1") >= LEAD_SPAWN_TOOLS
        assert not server._withheld_for("lead") & LEAD_SPAWN_TOOLS
        assert "multi-spawn" in server._withheld_for("lead")
    finally:
        runtime_refs.set_supervisor_tool_gateway(None)


def test_the_voice_only_list_names_real_voice_tools_and_none_leak_to_the_lead():
    gateway = _gateway()
    voice = {d.name for d in gateway.voice_catalog()}
    lead = set(gateway.lead_tools())
    for name in LEAD_MANIFEST.voice_only:
        assert name in voice or name == "computer", name
        assert name not in lead


def test_the_folder_tool_exception_is_exactly_the_folder_tool_names():
    assert LEAD_MANIFEST.brain_seat_only == {str(spec["name"]) for spec in folder.TOOL_SPECS}


@pytest.mark.parametrize("name", ["ask_agent", "product_help"])
def test_the_typed_lead_has_the_voice_helpers_too(name):
    assert name in _gateway().lead_tools()
