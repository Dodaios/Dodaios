"""Unit tests: BrainToolsChanged is published by mcp_routes endpoints.

Validates Workstream 2 of the MCP-tools-in-brain fix: every state-changing
endpoint dispatches BrainToolsChanged so the live BrainManager reloads its
tool set without a restart.

Only the ``enable_mcp`` endpoint (already-active fast path) is exercised here
because it is the simplest to fake: no ``start_enabled`` call is needed, and
the happy-path ``_publish_brain_tools_changed`` call is unambiguous.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch  # noqa: F401 — used below

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeBus:
    """Minimal EventBus stand-in that records published events."""

    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:  # noqa: D401
        self.published.append(event)


def _make_request(name: str, bus: _FakeBus) -> SimpleNamespace:
    """Build a minimal fake FastAPI Request sufficient for enable_mcp."""
    # registry: has the spec + reports the server as already active
    fake_spec = SimpleNamespace(name=name)
    fake_client = SimpleNamespace(_tools_cache=[], is_healthy=True)

    fake_registry = SimpleNamespace(
        get_spec=lambda n: fake_spec if n == name else None,
        active_clients=lambda: {name: fake_client},
        last_error=lambda n: None,
    )

    app_state = SimpleNamespace(
        mcp_registry=fake_registry,
        tool_registry={},
        bus=bus,
        cfg=None,
    )
    return SimpleNamespace(app=SimpleNamespace(state=app_state))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_enable_mcp_publishes_brain_tools_changed() -> None:
    """enable_mcp (already-active path) must publish BrainToolsChanged."""
    # Import here so structlog / other heavy deps are never touched at
    # collection time; the module is self-contained enough to import cleanly.
    from dodaios.core.events import BrainToolsChanged
    from dodaios.ui.web import mcp_routes

    bus = _FakeBus()
    request = _make_request("test-server", bus)

    # Patch mcp_state.enable so it doesn't touch disk, and _sync_tools_for_server
    # so it doesn't call client.list_tools() (adapter import chain).
    with (
        patch.object(mcp_routes.mcp_state, "enable", return_value=None),
        patch.object(
            mcp_routes,
            "_sync_tools_for_server",
            new=AsyncMock(return_value=None),
        ),
    ):
        result = await mcp_routes.enable_mcp("test-server", request)

    assert result["ok"] is True
    assert result["enabled"] is True

    # Exactly one BrainToolsChanged must have been published.
    changed = [e for e in bus.published if isinstance(e, BrainToolsChanged)]
    assert len(changed) == 1, f"Expected 1 BrainToolsChanged, got {len(changed)}"
    assert changed[0].reason.startswith("mcp_enabled:"), (
        f"Unexpected reason: {changed[0].reason!r}"
    )
    assert "test-server" in changed[0].reason


async def test_enable_mcp_no_bus_does_not_raise() -> None:
    """_publish_brain_tools_changed must be a no-op when bus is absent."""
    from dodaios.ui.web import mcp_routes

    # No bus on app.state
    fake_spec = SimpleNamespace(name="x")
    fake_client = SimpleNamespace(_tools_cache=[], is_healthy=True)
    fake_registry = SimpleNamespace(
        get_spec=lambda n: fake_spec,
        active_clients=lambda: {"x": fake_client},
        last_error=lambda n: None,
    )
    app_state = SimpleNamespace(
        mcp_registry=fake_registry,
        tool_registry={},
        cfg=None,
        # deliberately no ``bus`` attribute
    )
    request = SimpleNamespace(app=SimpleNamespace(state=app_state))

    with (
        patch.object(mcp_routes.mcp_state, "enable", return_value=None),
        patch.object(
            mcp_routes,
            "_sync_tools_for_server",
            new=AsyncMock(return_value=None),
        ),
    ):
        # Must not raise even though bus is missing
        result = await mcp_routes.enable_mcp("x", request)

    assert result["ok"] is True


async def test_update_raw_config_starts_newly_enabled_servers_and_syncs_tools() -> None:
    """PUT /api/mcps/config/raw must start newly enabled servers and sync tools."""
    from dodaios.core.events import BrainToolsChanged
    from dodaios.ui.web import mcp_routes

    bus = _FakeBus()
    active: dict[str, object] = {}
    started: list[list[str]] = []

    async def _start_enabled(names: list[str]) -> None:
        started.append(list(names))
        for n in names:
            active[n] = SimpleNamespace(_tools_cache=[], is_healthy=True)

    fake_registry = SimpleNamespace(
        load_from_mcp_json=lambda: None,
        active_clients=lambda: dict(active),
        start_enabled=_start_enabled,
        _clients=active,
    )
    app_state = SimpleNamespace(
        mcp_registry=fake_registry,
        tool_registry={},
        bus=bus,
        cfg=None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=app_state))
    sync_mock = AsyncMock(return_value=None)

    payload = {
        "mcpServers": {
            "tradingview": {
                "command": "python",
                "args": ["server.py"],
                "transport": "stdio",
                "enabled": True,
            }
        }
    }

    with (
        patch.object(mcp_routes.mcp_state, "save_config", return_value=None),
        patch.object(mcp_routes, "_sync_tools_for_server", new=sync_mock),
    ):
        result = await mcp_routes.update_raw_config(payload, request)

    assert result == {"ok": True, "servers": 1}
    assert started == [["tradingview"]]
    sync_mock.assert_awaited_once_with(request, fake_registry, "tradingview", adding=True)
    changed = [e for e in bus.published if isinstance(e, BrainToolsChanged)]
    assert len(changed) == 1
    assert changed[0].reason == "mcp_config_raw"


async def test_delete_mcp_syncs_tools_and_publishes_brain_tools_changed() -> None:
    """DELETE /api/mcps/{name} must unregister tools and publish BrainToolsChanged."""
    from dodaios.core.events import BrainToolsChanged
    from dodaios.ui.web import mcp_routes

    bus = _FakeBus()
    stop_mock = AsyncMock(return_value=None)
    fake_client = SimpleNamespace(_tools_cache=[], is_healthy=True, stop=stop_mock)
    fake_spec = SimpleNamespace(name="tradingview", mandatory=False)
    specs = {"tradingview": fake_spec}
    clients = {"tradingview": fake_client}

    fake_registry = SimpleNamespace(
        get_spec=lambda n: specs.get(n),
        active_clients=lambda: dict(clients),
        load_from_mcp_json=lambda: None,
        _clients=clients,
        _specs=specs,
    )
    app_state = SimpleNamespace(
        mcp_registry=fake_registry,
        tool_registry={},
        bus=bus,
        cfg=None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=app_state))
    sync_mock = AsyncMock(return_value=None)

    with (
        patch.object(mcp_routes.mcp_state, "get_server_entry", return_value={"command": "python"}),
        patch.object(mcp_routes.mcp_state, "remove_server", return_value=True),
        patch.object(mcp_routes, "_sync_tools_for_server", new=sync_mock),
    ):
        result = await mcp_routes.delete_mcp("tradingview", request)

    assert result == {"ok": True, "name": "tradingview", "deleted": True}
    stop_mock.assert_awaited_once()
    sync_mock.assert_awaited_once_with(request, fake_registry, "tradingview", adding=False)
    assert "tradingview" not in specs
    changed = [e for e in bus.published if isinstance(e, BrainToolsChanged)]
    assert len(changed) == 1
    assert changed[0].reason == "mcp_deleted:tradingview"

