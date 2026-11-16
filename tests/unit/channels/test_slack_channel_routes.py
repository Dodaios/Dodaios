"""The Slack setup routes: check both keys, store them, know the owner, start live.

The routes talk to the stand-in for Slack over the network; the Credential
Manager, the config file and the live reload are replaced, so nothing on the
computer running the tests changes.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dodaios.core.config_writer as writer
import dodaios.marketplace.channel_runtime as runtime
import dodaios.ui.web.slack_channel_routes as routes
from dodaios.core.config import IntegrationsConfig, SlackChannelConfig
from tests.fakes.slack_standin import FAKE_APP_TOKEN, FAKE_BOT_TOKEN, FAKE_USER_TOKEN, SlackStandIn


@pytest.fixture
def standin():
    """The stand-in on its own loop in a thread (TestClient runs its own loop)."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    holder: dict[str, Any] = {}

    def run() -> None:
        asyncio.set_event_loop(loop)
        try:
            holder["s"] = SlackStandIn()
            loop.run_until_complete(holder["s"].start())
        except BaseException as exc:  # handed to the test thread below
            holder["error"] = exc
            ready.set()
            return
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(30), "the Slack stand-in did not start within 30 s"
    if "error" in holder:
        raise holder["error"]
    yield holder["s"]
    asyncio.run_coroutine_threadsafe(holder["s"].stop(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, standin: SlackStandIn) -> dict[str, Any]:
    state: dict[str, Any] = {
        "secrets": {},
        "config": SlackChannelConfig(api_base_url=standin.api_base),
        "applied": [],
        "user_grant": None,
    }

    def load_config() -> Any:
        return SimpleNamespace(integrations=IntegrationsConfig(slack=state["config"]))

    def set_slack_channel(**fields: Any) -> None:
        state["config"] = state["config"].model_copy(
            update={k: v for k, v in fields.items() if v is not None and k != "path"}
        )

    async def apply(app_state: Any, name: str) -> bool:
        state["applied"].append(name)
        return True

    monkeypatch.setattr(routes, "load_config", load_config)
    monkeypatch.setattr(
        routes, "set_secret", lambda k, v: state["secrets"].__setitem__(k, v) or True
    )
    monkeypatch.setattr(routes, "delete_secret", lambda k: state["secrets"].pop(k, None) or True)
    monkeypatch.setattr(routes, "get_secret", lambda k, env_fallback=None: state["secrets"].get(k))
    monkeypatch.setattr(writer, "set_slack_channel", set_slack_channel)
    monkeypatch.setattr(runtime, "apply_channel_live", apply)

    class _Store:
        def load(self, plugin_id: str) -> Any:
            return state["user_grant"]

    import dodaios.marketplace.token_store as token_store

    monkeypatch.setattr(token_store, "TokenStore", _Store)
    return state


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_the_state_offers_the_manifest_link_before_anything_is_set_up(env: dict[str, Any]) -> None:
    with _client() as client:
        state = client.get("/api/channels/slack").json()
    assert state["enabled"] is False and state["keys_saved"] is False
    assert state["create_app_url"].startswith("https://api.slack.com/apps?new_app=1&manifest_json=")
    assert state["manifest"]["settings"]["socket_mode_enabled"] is True


def test_a_connect_checks_stores_and_starts_and_pairs_by_the_first_message(
    env: dict[str, Any],
) -> None:
    with _client() as client:
        res = client.post(
            "/api/channels/slack/connect",
            json={"bot_token": f" {FAKE_BOT_TOKEN} ", "app_token": FAKE_APP_TOKEN},
        )
    assert res.status_code == 200, res.text
    assert env["secrets"] == {"slack_bot_token": FAKE_BOT_TOKEN, "slack_app_token": FAKE_APP_TOKEN}
    cfg = env["config"]
    assert cfg.enabled is True and cfg.team_id == "T0STANDIN1"
    assert cfg.allowed_user_ids == [] and cfg.pair_on_first_dm is True
    assert env["applied"] == ["slack"]
    body = res.json()
    assert body["owner_from_sign_in"] is False and body["live_applied"] is True


def test_the_own_slack_sign_in_in_the_same_workspace_names_the_owner(env: dict[str, Any]) -> None:
    env["user_grant"] = SimpleNamespace(access=FAKE_USER_TOKEN, needs_reauth=False, extra={})
    with _client() as client:
        res = client.post(
            "/api/channels/slack/connect",
            json={"bot_token": FAKE_BOT_TOKEN, "app_token": FAKE_APP_TOKEN},
        )
    assert res.status_code == 200, res.text
    assert env["config"].allowed_user_ids == ["U0OWNER001"]
    assert env["config"].pair_on_first_dm is False
    assert res.json()["owner_from_sign_in"] is True


def test_a_refused_key_stores_nothing_and_says_which(
    env: dict[str, Any], standin: SlackStandIn
) -> None:
    standin.app_revoked = True
    with _client() as client:
        res = client.post(
            "/api/channels/slack/connect",
            json={"bot_token": FAKE_BOT_TOKEN, "app_token": FAKE_APP_TOKEN},
        )
        shape = client.post(
            "/api/channels/slack/connect", json={"bot_token": "xoxp-1", "app_token": FAKE_APP_TOKEN}
        )
    assert res.status_code == 400 and res.json()["detail"]["code"] == "app_token_rejected"
    assert shape.status_code == 400 and shape.json()["detail"]["code"] == "bot_token_shape"
    assert env["secrets"] == {} and env["config"].enabled is False and env["applied"] == []
    assert FAKE_APP_TOKEN not in res.text and FAKE_BOT_TOKEN not in res.text


def test_slack_unreachable_is_a_passing_failure(env: dict[str, Any], standin: SlackStandIn) -> None:
    standin.go_offline()
    try:
        with _client() as client:
            res = client.post(
                "/api/channels/slack/connect",
                json={"bot_token": FAKE_BOT_TOKEN, "app_token": FAKE_APP_TOKEN},
            )
    finally:
        standin.go_online()
    assert res.status_code == 502 and res.json()["detail"]["code"] == "slack_unreachable"


def test_a_connect_to_another_workspace_drops_the_old_owner(env: dict[str, Any]) -> None:
    env["config"] = env["config"].model_copy(
        update={"team_id": "T0ELSEWHERE", "allowed_user_ids": ["U0OLDOWNER"]}
    )
    with _client() as client:
        client.post(
            "/api/channels/slack/connect",
            json={"bot_token": FAKE_BOT_TOKEN, "app_token": FAKE_APP_TOKEN},
        )
    assert env["config"].allowed_user_ids == [] and env["config"].pair_on_first_dm is True


def test_pair_again_and_disconnect(env: dict[str, Any]) -> None:
    env["secrets"].update({"slack_bot_token": FAKE_BOT_TOKEN, "slack_app_token": FAKE_APP_TOKEN})
    env["config"] = env["config"].model_copy(
        update={"enabled": True, "allowed_user_ids": ["U0OWNER001"], "pair_on_first_dm": False}
    )
    with _client() as client:
        client.post("/api/channels/slack/pairing")
        assert env["config"].allowed_user_ids == [] and env["config"].pair_on_first_dm is True
        state = client.post("/api/channels/slack/disconnect").json()
    assert env["secrets"] == {} and env["config"].enabled is False
    assert state["keys_saved"] is False
    assert env["applied"] == ["slack", "slack"]
