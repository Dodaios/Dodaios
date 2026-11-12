"""A server that forgets the MCP session must not leave the client broken.

Streamable HTTP servers drop a session when it idles out (the MCP SDK's default
is 30 minutes) or when the server restarts, and then answer 404 to the old
session id. The spec says the client must then start a new session with a new
InitializeRequest. Without that, every later call failed with "Session
terminated" and only an app restart brought the connector back.

These tests run a real FastMCP server over HTTP and restart it to make it
forget the session.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from dodaios.mcp import client as client_mod
from dodaios.mcp.client import MCPClient
from dodaios.mcp.registry import MCPServerSpec


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _RestartableServer:
    """One FastMCP server process stand-in that can be restarted on its port."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.calls = 0
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.calls = 0  # tool runs on this server instance only
        mcp = FastMCP("expiring")

        @mcp.tool()
        def echo(msg: str) -> str:
            """Echo the message back."""
            self.calls += 1
            return f"echoed:{msg}"

        config = uvicorn.Config(
            mcp.streamable_http_app(),
            host="127.0.0.1",
            port=self.port,
            log_level="error",
            timeout_graceful_shutdown=1,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("test MCP server did not start")
            time.sleep(0.02)

    def stop(self) -> None:
        if self._server is None or self._thread is None:
            return
        self._server.should_exit = True
        self._thread.join(timeout=10)
        self._server = None
        self._thread = None


@pytest.fixture
def server() -> Any:
    srv = _RestartableServer(_free_port())
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(autouse=True)
def _short_call_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_mod, "_CALL_TIMEOUT_S", 5.0)


def _client(port: int) -> MCPClient:
    return MCPClient(
        MCPServerSpec(
            name="expiring",
            display="Expiring",
            description="test server that forgets sessions",
            install_command=[],
            transport="http",
            url=f"http://127.0.0.1:{port}/mcp",
        )
    )


def _text(result: Any) -> str:
    return " ".join(getattr(part, "text", "") for part in result.content)


@pytest.mark.asyncio
async def test_call_after_the_server_forgot_the_session_starts_a_new_one(
    server: _RestartableServer,
) -> None:
    client = _client(server.port)
    await client.start()
    try:
        assert "echoed:one" in _text(await client.call_tool("echo", {"msg": "one"}))

        server.stop()
        server.start()  # the new server answers 404 to the old session id

        result = await client.call_tool("echo", {"msg": "two"})

        assert "echoed:two" in _text(result)
        assert client._circuit_breaker_failures == 0
        # The refused request never ran, so the new server ran the tool exactly once.
        assert server.calls == 1
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_every_later_call_works_after_the_new_session(
    server: _RestartableServer,
) -> None:
    client = _client(server.port)
    await client.start()
    try:
        await client.call_tool("echo", {"msg": "one"})
        server.stop()
        server.start()

        for n in range(3):
            assert f"echoed:{n}" in _text(await client.call_tool("echo", {"msg": str(n)}))
        assert client.is_healthy
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_a_failed_renewal_is_tried_again_on_the_next_call(
    server: _RestartableServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(server.port)
    await client.start()
    try:
        await client.call_tool("echo", {"msg": "one"})
        server.stop()
        server.start()

        real_start = MCPClient.start
        attempts = 0

        async def start_failing_once(self: MCPClient) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("server briefly unreachable")
            await real_start(self)

        monkeypatch.setattr(MCPClient, "start", start_failing_once)

        with pytest.raises(ConnectionError):
            await client.call_tool("echo", {"msg": "two"})
        assert client._circuit_breaker_failures == 1

        result = await client.call_tool("echo", {"msg": "three"})

        assert "echoed:three" in _text(result)
        assert attempts == 2
        assert client._circuit_breaker_failures == 0
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_a_tool_error_is_not_repeated(server: _RestartableServer) -> None:
    client = _client(server.port)
    await client.start()
    try:
        with pytest.raises(RuntimeError):
            await client.call_tool("no_such_tool", {})
        assert client._circuit_breaker_failures == 1
        assert server.calls == 0
    finally:
        await client.stop()
