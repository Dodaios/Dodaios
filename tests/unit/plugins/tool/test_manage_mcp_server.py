"""Unknown-name errors from manage-mcp-server must be actionable.

Forensic 2026-07-13 18:33: "reconnect the GitHub MCP" failed with a bare
"no MCP server named 'github'" — GitHub was a marketplace plugin, not an
mcp.json server — and the spoken outcome gave the user nothing to correct.
"""

from __future__ import annotations

import pytest

from dodaios.plugins.tool.manage_mcp_server import ManageMcpServerTool


class _FakeMcpState:
    def __init__(self, servers: dict | None = None) -> None:
        self._servers = servers or {}

    def load_config(self) -> dict:
        return {"mcpServers": dict(self._servers)}

    def get_server_entry(self, name: str) -> dict | None:
        return self._servers.get(name)

    def remove_server(self, name: str) -> bool:
        return self._servers.pop(name, None) is not None


@pytest.mark.asyncio
async def test_toggle_unknown_name_lists_configured_servers() -> None:
    state = _FakeMcpState({"notebooklm": {"enabled": True}, "blender": {}})
    result = await ManageMcpServerTool()._toggle(
        state, "github", enabled=True, reason="test"
    )
    assert result.success is False
    assert "github" in result.error
    assert "notebooklm" in result.error
    assert "blender" in result.error
    assert "plugin" in result.error.lower()


@pytest.mark.asyncio
async def test_remove_unknown_name_lists_configured_servers() -> None:
    state = _FakeMcpState({"notebooklm": {"enabled": True}})
    result = await ManageMcpServerTool()._remove(state, "github", "test")
    assert result.success is False
    assert "notebooklm" in result.error


@pytest.mark.asyncio
async def test_unknown_name_error_survives_a_broken_state() -> None:
    class _BrokenState:
        def load_config(self):
            raise RuntimeError("boom")

        def get_server_entry(self, _name):
            return None

    result = await ManageMcpServerTool()._toggle(
        _BrokenState(), "github", enabled=True, reason="test"
    )
    assert result.success is False
    assert "github" in result.error


@pytest.mark.asyncio
async def test_toggle_enable_uses_active_clients_and_notifies_brain(monkeypatch) -> None:
    """Issue #1189: ManageMcpServerTool._toggle must query registry.active_clients()
    (not the non-existent active_names()) and publish BrainToolsChanged on live start.
    """
    from types import SimpleNamespace

    from dodaios.core import runtime_refs
    from dodaios.core.events import BrainToolsChanged

    class _ToggleState(_FakeMcpState):
        def set_enabled(self, name: str, enabled: bool) -> None:
            self._servers.setdefault(name, {})["enabled"] = enabled

    state = _ToggleState({"tradingview": {"command": "python", "enabled": False}})
    active: dict[str, object] = {}

    class _LiveRegistry:
        def load_from_mcp_json(self) -> None:
            pass

        async def start_enabled(self, names: list[str]) -> None:
            for n in names:
                active[n] = SimpleNamespace(_tools_cache=[])

        def active_clients(self) -> dict[str, object]:
            return dict(active)

    published: list[object] = []

    class _Bus:
        async def publish(self, event: object) -> None:
            published.append(event)

    monkeypatch.setattr(runtime_refs, "get_mcp_registry", lambda: _LiveRegistry())
    monkeypatch.setattr(
        runtime_refs,
        "get_web_app",
        lambda: SimpleNamespace(state=SimpleNamespace(bus=_Bus(), tool_registry={})),
    )

    result = await ManageMcpServerTool()._toggle(
        state, "tradingview", enabled=True, reason="enable tradingview"
    )
    assert result.success is True
    assert result.output["applied_live"] is True
    assert result.output["requires_restart"] is False
    assert any(isinstance(e, BrainToolsChanged) for e in published)
