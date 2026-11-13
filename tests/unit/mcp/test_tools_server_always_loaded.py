"""The ask tool stays in a Claude Code seat's prompt instead of behind its tool search.

The CLI defers the tools of a large MCP server: the model sees only their names
and must search before it can call one. With only the name in sight the lead
wrote its questions into the reply (live 2026-11-13) and no question card came
up. The CLI reads ``anthropic/alwaysLoad`` from a tool's ``_meta``.
"""

from __future__ import annotations

from types import SimpleNamespace

import mcp.types as types

from dodaios.brain.tool_gateway import BrainSupervisorToolGateway
from dodaios.core import runtime_refs
from dodaios.core.protocols import ToolResult
from dodaios.mcp import dodaios_tools_server as server
from dodaios.society.ask_tool import ASK_USER_TOOL_NAME


class _Tool:
    risk_tier = "safe"
    is_action_tool = False
    schema: dict = {"type": "object", "properties": {}}
    description = "x"

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, args, ctx):
        return ToolResult(True, {})


async def _listed(session_id: str) -> dict[str, types.Tool]:
    manager = SimpleNamespace(
        _tools={name: _Tool(name) for name in ("search_web", "job_status")},
        _config=SimpleNamespace(computer_use=SimpleNamespace(enabled=True)),
    )
    ask = _Tool(ASK_USER_TOOL_NAME)
    gateway = BrainSupervisorToolGateway(
        manager, lead_session=lambda sid: sid == "lead", lead_hands=lambda sid: {ask.name: ask}
    )
    runtime_refs.set_supervisor_tool_gateway(gateway)
    token = server.CHAT_SESSION_REF.set(session_id)
    try:
        handler = server.build_server().request_handlers[types.ListToolsRequest]
        result = await handler(types.ListToolsRequest(method="tools/list"))
    finally:
        server.CHAT_SESSION_REF.reset(token)
        runtime_refs.set_supervisor_tool_gateway(None)
    return {tool.name: tool for tool in result.root.tools}


async def test_the_ask_tool_is_listed_as_always_loaded_and_nothing_else_is():
    tools = await _listed("lead")
    assert ASK_USER_TOOL_NAME in tools and "search_web" in tools
    # On the wire the mark is the tool's ``_meta``, as the CLI reads it.
    wire = tools[ASK_USER_TOOL_NAME].model_dump(by_alias=True, exclude_none=True)
    assert wire["_meta"] == {"anthropic/alwaysLoad": True}
    for name, tool in tools.items():
        if name != ASK_USER_TOOL_NAME:
            assert tool.meta is None, name


def test_the_always_loaded_set_is_the_ask_tool_alone():
    # Every name here costs its whole schema in every turn of every chat.
    assert server._ALWAYS_LOADED == frozenset({ASK_USER_TOOL_NAME})
