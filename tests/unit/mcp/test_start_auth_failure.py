"""A remote MCP server refusing the connect must fail as an ordinary exception.

AnyIO cancels the connect when the HTTP transport task fails. If that cancellation
reaches the caller, no ``except Exception`` contains it and
``PluginToolRegistry.bootstrap`` ends at the first refusing plugin, so every later
plugin stays without tools.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.marketplace.catalog import PluginCatalog
from dodaios.marketplace.catalog_data import load_catalog
from dodaios.marketplace.plugin_registry import PluginToolRegistry
from dodaios.marketplace.token_store import InMemoryBackend, Tokens, TokenStore
from dodaios.mcp.client import MCPClient
from tests.fakes.fake_plugin_http import RotatingPluginHandler


class _Refuse(BaseHTTPRequestHandler):
    def _refuse(self) -> None:
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET = do_DELETE = _refuse

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def refusing_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Refuse)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/mcp"
    server.shutdown()


class _ReachableClient:
    is_healthy = True

    def __init__(self, spec: Any, **_kwargs: Any) -> None:
        self.spec = spec

    async def start(self) -> None:
        pass

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "ping", "inputSchema": {}}]

    async def stop(self) -> None:
        pass


@pytest.mark.asyncio
async def test_refused_connect_raises_ordinary_exception(refusing_url: str) -> None:
    spec = SimpleNamespace(
        name="refusing",
        transport="http",
        url=refusing_url,
        headers={},
        install_command=None,
        env={},
    )
    with pytest.raises(Exception) as caught:  # noqa: PT011,B017 - the point is that it is an Exception
        await asyncio.wait_for(MCPClient(spec).start(), timeout=15)
    assert "401" in repr(getattr(caught.value, "exceptions", caught.value))


@pytest.mark.asyncio
async def test_bootstrap_continues_after_a_refusing_plugin(refusing_url: str) -> None:
    catalog = load_catalog()
    notion = catalog.by_id("notion")
    refusing = notion.model_copy(update={"mcp_server": {**notion.mcp_server, "url": refusing_url}})
    reachable = catalog.by_id("linear")
    store = TokenStore(InMemoryBackend())
    store.save(refusing.id, Tokens(access="old-access", refresh="old-refresh"))
    store.save(reachable.id, Tokens(access="good-access", refresh="good-refresh"))

    def client_factory(spec: Any, **kwargs: Any) -> Any:
        return MCPClient(spec, **kwargs) if spec.name == refusing.id else _ReachableClient(spec)

    registry = PluginToolRegistry(
        catalog=PluginCatalog(version=1, schema_version="1", plugins=[refusing, reachable]),
        token_store=store,
        client_factory=client_factory,
        refresh_handler_builder=lambda _: RotatingPluginHandler(),
    )
    try:
        await asyncio.wait_for(registry.bootstrap(), timeout=40)
        assert registry.is_bootstrapped()
        assert registry.live_tool_count(reachable.id) == 1
    finally:
        await registry.stop()
