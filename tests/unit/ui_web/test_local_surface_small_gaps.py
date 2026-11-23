"""Smaller gaps of the local surfaces, each closed by one rule.

* The stock API documentation pages load their script from a public CDN and
  ran in the app's own origin, where a script may call every route. They are
  no longer served outside development mode.
* The loopback OAuth listener ended the waiting sign-in when ANY request
  with a wrong ``state`` arrived, so a page in the browser could cancel a
  sign-in. A wrong state is now refused and the flow keeps waiting.
* Files that carry a token (the standalone Conductor token, the terminal and
  turn hosts' state files) were written first and restricted afterwards.
  They are now created owner-only.
* A read-only agent token could add agents and open rooms.
"""
from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig

# --------------------------------------------------------------- docs pages


def _app(*, dev_mode: bool):
    from dodaios.ui.web.server import WebServer

    cfg = JarvisConfig()
    cfg.ui.dev_mode = dev_mode
    return WebServer(cfg, bus=EventBus()).app


def test_no_cdn_backed_docs_page_outside_development() -> None:
    app = _app(dev_mode=False)
    client = TestClient(app)

    assert app.docs_url is None
    assert app.redoc_url is None
    for path in ("/api/_swagger", "/redoc", "/docs", "/docs/oauth2-redirect"):
        body = client.get(path).text
        assert "cdn.jsdelivr.net" not in body, path
        assert "swagger-ui" not in body, path
    assert client.get("/api/openapi.json").status_code == 200


def test_swagger_stays_available_in_development() -> None:
    app = _app(dev_mode=True)

    assert app.docs_url == "/api/_swagger"
    assert app.redoc_url is None


# ------------------------------------------------------------ OAuth callback


def test_wrong_state_does_not_end_the_waiting_sign_in() -> None:
    from dodaios.marketplace.oauth_callback_server import OAuthCallbackServer

    async def scenario() -> tuple[int, int, str]:
        server = OAuthCallbackServer(expected_state="expected-state", timeout_seconds=5.0)
        await server.start()
        try:
            waiting = asyncio.create_task(server.await_callback())
            async with httpx.AsyncClient() as client:
                wrong = await client.get(
                    server.redirect_uri, params={"state": "someone-else", "code": "x"}
                )
                missing = await client.get(server.redirect_uri)
                await asyncio.sleep(0.05)
                assert not waiting.done(), "a foreign request must not end the flow"
                right = await client.get(
                    server.redirect_uri, params={"state": "expected-state", "code": "the-code"}
                )
            result = await waiting
            assert missing.status_code == 400
            return wrong.status_code, right.status_code, result.code
        finally:
            await server.stop()

    wrong_status, right_status, code = asyncio.run(scenario())

    assert wrong_status == 400
    assert right_status == 200
    assert code == "the-code"


# ------------------------------------------------------- owner-only files


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, int]]:
    """Every ``os.open`` call as ``(path, flags, mode)``."""
    calls: list[tuple[str, int, int]] = []
    real = os.open

    def spy(path, flags, mode=0o777, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        calls.append((str(path), flags, mode))
        return real(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    return calls


def _assert_created_private(calls: list[tuple[str, int, int]], final: Path) -> None:
    created = [c for c in calls if Path(c[0]).parent == final.parent and c[1] & os.O_CREAT]
    assert created, "the file must be created through os.open with an explicit mode"
    for _path, flags, mode in created:
        assert flags & os.O_EXCL, "never write into a file someone else prepared"
        assert mode == 0o600
    assert final.is_file()
    assert not list(final.parent.glob("*.tmp"))
    if sys.platform != "win32":
        assert stat.S_IMODE(final.stat().st_mode) == 0o600


def test_conductor_token_file_is_created_private(
    tmp_path: Path, opened: list[tuple[str, int, int]]
) -> None:
    from conductor.api.security import write_token_file

    target = tmp_path / "conductor-home" / "api-token"

    write_token_file("first-token", target)
    write_token_file("second-token", target)

    assert target.read_text(encoding="utf-8") == "second-token\n"
    _assert_created_private(opened, target)


@pytest.mark.parametrize(
    "module_name", ["dodaios.terminal.pty_host", "dodaios.agent_chat.turn_host"]
)
def test_host_state_file_is_created_private(
    tmp_path: Path, opened: list[tuple[str, int, int]], module_name: str
) -> None:
    import importlib
    import json

    module = importlib.import_module(module_name)
    target = tmp_path / "host" / "state.json"

    module._write_state(target, {"port": 1, "token": "first"})
    module._write_state(target, {"port": 2, "token": "second"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"port": 2, "token": "second"}
    _assert_created_private(opened, target)


# ------------------------------------------------------------ agent tokens


@pytest.mark.parametrize("tool_name", ["agent_create", "room_open"])
def test_a_read_token_cannot_change_the_roster_or_open_rooms(tool_name: str) -> None:
    from dodaios.mcp.agents import tokens, tools

    tool = tools.get(tool_name)
    assert tool is not None

    assert not tokens.allows("read", tool.name, dangerous=tool.dangerous)
    assert tokens.allows("work", tool.name, dangerous=tool.dangerous)
    assert tokens.allows("full", tool.name, dangerous=tool.dangerous)


def test_a_read_token_still_reads() -> None:
    from dodaios.mcp.agents import tokens, tools

    writes = {"agent_create", "room_open"}
    listing = [t for t in tools.TOOLS if not t.dangerous and t.name not in writes]

    assert listing, "read-only tools must remain"
    assert all(tokens.allows("read", t.name, dangerous=t.dangerous) for t in listing)
