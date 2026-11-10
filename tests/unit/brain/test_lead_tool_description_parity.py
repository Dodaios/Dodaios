"""A tool description must not send the lead to a tool the lead does not have.

Live repro: ``delegate_to_agent`` said coding panes "go through
workspace-orchestrate", but that tool existed only for the voice seat; the typed
lead fell back to the ambient-pane prompt tool the code itself calls unsafe.

The invariant is PARITY with the lead's own catalog (the typed brain seat and
the CLI seats over MCP see the same set): every tool name a description names,
bare or quoted, exists in it. A name that is only a word in a schema (an
argument, an enum value) is not a tool name.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.brain.tool_gateway import BrainSupervisorToolGateway

REPO = Path(__file__).resolve().parents[3]
_NAME = re.compile(r"(?<![\w-])[a-z][a-z0-9]*(?:[-_][a-z0-9]+)+(?![\w-])")
_QUOTED = re.compile(r"""[`'"]([a-z][a-z0-9]*(?:[-_][a-z0-9]+)+)[`'"]""")
# Tools of other surfaces that exist, so naming them from the lead is wrong.
_OTHER_SURFACE_TOOLS = frozenset(
    {
        "task_status",
        "take_appshot",
        "update_soul",
        "product_help",
        "remember",
        "show_on_screen",
        "ask_agent",
        "end_call",
        "today_brief",
        "agentic-ide-prompt",
        "agentic-ide-fanout",
    }
)
# Hyphenated words that are not tool names (product areas, file names, states).
_NOT_TOOLS = frozenset({"needs_input", "needs_attention", "while_busy", "request_id"})


def _key(name: str) -> str:
    return name.replace("_", "-")


def _entry_point_names() -> set[str]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["project"]["entry-points"]["jarvis.tool"])


@pytest.fixture(scope="module")
def lead_catalog() -> dict[str, Any]:
    from dodaios.agent_chat.folder_tools import folder_tools
    from dodaios.brain.factory import _load_tools_for_tier
    from dodaios.brain.workspace_tool import WorkspaceOrchestrationTool
    from dodaios.core.bus import EventBus
    from dodaios.core.config import JarvisConfig

    tools = _load_tools_for_tier(
        "router",
        bus=EventBus(),
        executor=None,
        harness_manager=None,
        user_profile=None,
        people=None,
        config=JarvisConfig(),
    )
    tools.update(folder_tools(REPO, stance="ask"))
    gateway = BrainSupervisorToolGateway(
        SimpleNamespace(_tools=tools),
        workspace_tool=WorkspaceOrchestrationTool(SimpleNamespace(run=None)),
    )
    return gateway.lead_tools()


def test_the_lead_has_addressed_pane_coding_and_the_board_but_not_ambient_prompts(lead_catalog):
    assert {"workspace-orchestrate", "workspace-git", "work_board"} <= set(lead_catalog)
    assert "agentic-ide-prompt" not in lead_catalog
    assert "agentic-ide-fanout" not in lead_catalog
    assert "agentic-ide-status" in lead_catalog  # a read the lead still uses


def _texts(tool: Any) -> list[tuple[str, str]]:
    found = [(f"{tool.name} description", str(getattr(tool, "description", "") or ""))]
    schema = getattr(tool, "schema", None)
    if isinstance(schema, dict):
        for prop, spec in (schema.get("properties") or {}).items():
            if isinstance(spec, dict) and spec.get("description"):
                found.append((f"{tool.name}.{prop}", str(spec["description"])))
    return found


def test_every_tool_named_in_a_lead_visible_description_is_in_the_lead_catalog(lead_catalog):
    from dodaios.commands.registry import get_registry

    catalog = {_key(name) for name in lead_catalog}
    known_elsewhere = {
        _key(name)
        for name in (
            *_entry_point_names(),
            *(command.id for command in get_registry()),
            *_OTHER_SURFACE_TOOLS,
        )
    }
    vocabulary: set[str] = set(_NOT_TOOLS)
    for tool in lead_catalog.values():
        schema = getattr(tool, "schema", None)
        if isinstance(schema, dict):
            vocabulary.update(_schema_words(schema))
    problems: list[str] = []
    for tool in lead_catalog.values():
        for where, text in _texts(tool):
            for token in set(_NAME.findall(text)) | set(_QUOTED.findall(text)):
                if _key(token) in catalog or token in vocabulary:
                    continue
                if _key(token) in known_elsewhere:
                    problems.append(f"{where}: names '{token}', which the lead does not have")
    assert not problems, "\n".join(sorted(problems))


def _schema_words(schema: Any) -> set[str]:
    words: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                words.update(value)
            if key == "enum" and isinstance(value, list):
                words.update(str(item) for item in value)
            words |= _schema_words(value)
    elif isinstance(schema, list):
        for item in schema:
            words |= _schema_words(item)
    return words
