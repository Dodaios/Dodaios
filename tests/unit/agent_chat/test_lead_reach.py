"""``/api/agent-chat/lead/channels``: where the person reaches the assistant outside the app."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import reach
from dodaios.ui.web.agent_chat_routes import router


class _Manager:
    def __init__(self, started: list[str], bot_username: str = "") -> None:
        self._started = started
        self._channel = SimpleNamespace(bot_username=bot_username)

    def started(self) -> list[str]:
        return self._started

    def get(self, name: str) -> Any:
        assert name == "telegram"
        return self._channel


class _Tokens:
    def __init__(self, tokens: Any) -> None:
        self._tokens = tokens

    def load(self, plugin_id: str) -> Any:
        assert plugin_id == "slack"
        if isinstance(self._tokens, Exception):
            raise self._tokens
        return self._tokens


def _grant(**fields: Any) -> SimpleNamespace:
    return SimpleNamespace(**{"access": "xoxp-1", "needs_reauth": False, "extra": {}, **fields})


def test_telegram_is_connected_only_while_its_channel_runs() -> None:
    off = {"id": "telegram", "kind": "chat", "connected": False, "handle": "", "url": ""}
    assert reach.telegram_row(None) == off
    assert reach.telegram_row(_Manager(["discord"], "nova_bot")) == off

    row = reach.telegram_row(_Manager(["telegram"], "nova_bot"))
    assert row == {
        "id": "telegram",
        "kind": "chat",
        "connected": True,
        "handle": "@nova_bot",
        "url": "https://t.me/nova_bot",
    }


def test_telegram_counts_as_connected_only_once_the_bot_has_a_name() -> None:
    # A channel that is switched off is "started" for the manager and never
    # learns its bot's name; a name that is no Telegram name is not trusted.
    for name in ("", "a b", "https://evil.example/x"):
        row = reach.telegram_row(_Manager(["telegram"], name))
        assert (row["connected"], row["handle"], row["url"]) == (False, "", "")


def test_a_manager_that_raises_reads_as_not_connected() -> None:
    class _Broken:
        def started(self) -> list[str]:
            raise RuntimeError("mid-start")

    assert reach.telegram_row(_Broken())["connected"] is False


def test_slack_names_the_workspace_of_a_healthy_grant() -> None:
    row = reach.slack_row(_Tokens(_grant(extra={"team_id": "T024BE7LD", "team_name": "Acme"})))
    assert row == {
        "id": "slack",
        "kind": "tool",
        "connected": True,
        "handle": "Acme",
        "url": "https://app.slack.com/client/T024BE7LD",
    }
    # An id that is no workspace id never becomes part of an address.
    odd = reach.slack_row(_Tokens(_grant(extra={"team_id": "../x", "team_name": "Acme"})))
    assert (odd["connected"], odd["url"]) == (True, "")


@pytest.mark.parametrize(
    "tokens",
    [None, _grant(access=""), _grant(needs_reauth=True), RuntimeError("corrupted token blob")],
)
def test_slack_without_a_usable_grant_is_not_connected(tokens: Any) -> None:
    row = reach.slack_row(_Tokens(tokens))
    assert (row["connected"], row["handle"], row["url"]) == (False, "", "")


def test_the_route_lists_slack_then_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reach, "slack_row", lambda store=None: {"id": "slack", "connected": False})
    app = FastAPI()
    app.include_router(router)
    app.state.channel_manager = _Manager(["telegram"], "nova_bot")
    with TestClient(app) as client:
        rows = client.get("/api/agent-chat/lead/channels").json()["channels"]
    assert [row["id"] for row in rows] == ["slack", "telegram"]
    assert rows[1]["url"] == "https://t.me/nova_bot"
