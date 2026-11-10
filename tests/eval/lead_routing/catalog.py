"""The tool catalog the typed lead sees, built from the real code.

Nothing here calls a model. The catalog is what the lead's tool gateway offers
the lead's chat: the shared router-tier tools plus the folder tools, and, once
the gateway exposes a dedicated lead set (``lead_tools``), exactly that set.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]

#: Tools the lead's chat gets per session (they need a live runtime, so they are
#: known by name only). A live run cannot offer them to a model.
SESSION_TOOL_NAMES: frozenset[str] = frozenset({"society_browser"})


#: Virtual tool loaders whose output depends on the machine, not on the code.
MACHINE_DEPENDENT_LOADERS: frozenset[str] = frozenset({"cli-tools", "plugin-tools", "mcp-tools"})


@dataclass(slots=True)
class LeadCatalog:
    """Tool name -> tool object, plus the names that exist without a schema."""

    tools: dict[str, Any] = field(default_factory=dict)
    session_names: frozenset[str] = SESSION_TOOL_NAMES

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self.tools) | self.session_names

    def has(self, name: str) -> bool:
        return name in self.names

    def risk_tier(self, name: str) -> str:
        return str(getattr(self.tools.get(name), "risk_tier", "") or "")

    def is_action_tool(self, name: str) -> bool:
        return bool(getattr(self.tools.get(name), "is_action_tool", False))

    def offered(self) -> list[dict[str, Any]]:
        """Provider-format tool schemas (``name`` / ``description`` / ``input_schema``)."""
        out: list[dict[str, Any]] = []
        for name, tool in sorted(self.tools.items()):
            schema = getattr(tool, "schema", None)
            out.append(
                {
                    "name": name,
                    "description": str(getattr(tool, "description", "") or ""),
                    "input_schema": schema
                    if isinstance(schema, dict)
                    else {"type": "object", "properties": {}},
                }
            )
        return out


def build_lead_catalog() -> LeadCatalog:
    """Build the lead's catalog from the real tool loader. Slow (a second or two)."""
    from dodaios.agent_chat.folder_tools import folder_tools
    from dodaios.brain import factory
    from dodaios.brain.factory import _load_tools_for_tier
    from dodaios.core.bus import EventBus
    from dodaios.core.config import JarvisConfig

    # The virtual loaders expand to whatever THIS machine has installed or connected
    # (command-line tools, plugins, MCP servers). They are left out so the catalog,
    # and with it every verdict, is the same on every machine and in CI.
    hermetic = frozenset(factory.ROUTER_TOOLS) - MACHINE_DEPENDENT_LOADERS
    with patch.object(factory, "ROUTER_TOOLS", hermetic):
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
    try:
        from dodaios.brain.tool_gateway import BrainSupervisorToolGateway

        gateway = BrainSupervisorToolGateway(SimpleNamespace(_tools=tools))
        if hasattr(gateway, "lead_tools"):
            tools = _lead_set(gateway, tools)
    except Exception:  # noqa: BLE001 - fall back to the shared set, never fail the eval
        log.warning("lead_tools unavailable; using the shared tool set", exc_info=True)
    return LeadCatalog(tools=dict(tools))


def _lead_set(gateway: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    """The gateway's own lead set, when it exposes one (a later change adds it)."""
    try:
        from dodaios.brain.workspace_tool import WorkspaceOrchestrationTool

        gateway._workspace_tool = WorkspaceOrchestrationTool(SimpleNamespace(run=None))
    except Exception:  # noqa: BLE001
        log.debug("workspace tool not constructible offline", exc_info=True)
    lead = gateway.lead_tools()
    return dict(lead) if isinstance(lead, dict) and lead else fallback
