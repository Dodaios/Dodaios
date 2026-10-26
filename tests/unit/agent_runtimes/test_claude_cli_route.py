"""An agent on the Claude subscription runs through the official Claude CLI only.

Anthropic bills a Claude login sent to its HTTP API by a third-party app as
Extra Usage, so the subscription seat never gets a gateway route, a bearer,
or an API key in its place. The CLI is a fake process (``fake_claude_cli``)
that answers ``claude auth status --json`` for the account directory it is
started with, and fails any model call.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios import claude_auth
from dodaios.agent_chat.catalog import API_KEY_ACCOUNT, SUBSCRIPTION_ACCOUNT
from dodaios.agent_runtimes import gateway, model_map
from dodaios.core import config
from tests.fakes import fake_claude_cli

_KEY = "sk-ant-api03-" + "fixture"


@pytest.fixture
def claude(monkeypatch, tmp_path):
    """Claude only, no API key, the fake CLI installed; returns the default
    account's directory (the app's own ``CLAUDE_CONFIG_DIR``)."""
    monkeypatch.setattr(model_map, "_ENDPOINTS", {"claude-api": model_map._ENDPOINTS["claude-api"]})
    secrets: dict[str, str | None] = {"key": None}
    monkeypatch.setattr(config, "get_jarvis_agent_secret", lambda provider: None)
    monkeypatch.setattr(
        config, "resolve_provider_endpoint", lambda *args, **kwargs: SimpleNamespace(
            credential=secrets["key"], base_url="https://api.anthropic.com", via_proxy=False,
        ),
    )
    launcher = fake_claude_cli.install(tmp_path / "bin")
    monkeypatch.setattr(
        claude_auth.ClaudeAuthService, "_resolve_binary", lambda self: str(launcher)
    )
    claude_auth.clear_version_cache()
    default = tmp_path / "claude-default"
    default.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(default))
    monkeypatch.setattr(gateway, "base_url", lambda: "http://127.0.0.1:1/api/runtime-gateway/v1")
    gateway.reset()
    yield SimpleNamespace(default=default, launcher=launcher, secrets=secrets)
    gateway.reset()
    claude_auth.clear_version_cache()


def test_a_subscription_seat_routes_to_the_cli_never_the_gateway(claude):
    fake_claude_cli.sign_in(claude.default, fake_claude_cli.SUBSCRIPTION)

    route = model_map.route_for(None, "claude-api", "claude-fixture", agent_id="a1")

    assert route.transport == "claude_cli"
    assert route.api_key is None and route.base_url == ""
    assert route.claude_binary == str(claude.launcher)
    # Only the account selection reaches the runtime: no key, no bearer.
    env = route.env()
    assert env["CLAUDE_CONFIG_DIR"] == str(claude.default)
    assert model_map.KEY_ENV_VAR not in env
    assert not any("KEY" in name or "TOKEN" in name for name in env)
    # No gateway token was minted, so nothing can be answered over HTTP.
    assert gateway._GRANTS == {}
    # The CLI was only asked whether it is signed in.
    assert fake_claude_cli.calls(claude.default) == [["auth", "status", "--json"]]


def test_pinned_subscription_wins_over_a_saved_key(claude):
    claude.secrets["key"] = _KEY
    fake_claude_cli.sign_in(claude.default, fake_claude_cli.SUBSCRIPTION)

    assert model_map.route_for(None, "claude-api", "m", account_id=SUBSCRIPTION_ACCOUNT).transport \
        == "claude_cli"
    unpinned = model_map.route_for(None, "claude-api", "m", agent_id="a1")
    assert unpinned.transport == "chat_completions" and unpinned.api_key != _KEY
    pinned_key = model_map.route_for(None, "claude-api", "m", account_id=API_KEY_ACCOUNT)
    assert pinned_key.transport == "chat_completions"


@pytest.mark.parametrize("state", [fake_claude_cli.LOGGED_OUT, fake_claude_cli.API_KEY])
def test_a_cli_not_signed_in_to_a_plan_is_an_honest_error_never_a_key(claude, state):
    claude.secrets["key"] = _KEY  # a key exists, and must not stand in
    fake_claude_cli.sign_in(claude.default, state)

    with pytest.raises(model_map.RouteUnavailable, match="not signed in to a Claude plan") as exc:
        model_map.route_for(None, "claude-api", "m", account_id=SUBSCRIPTION_ACCOUNT)
    assert "No API key was used" in str(exc.value)
    assert gateway._GRANTS == {}


def test_a_missing_cli_is_an_honest_error(claude, monkeypatch):
    monkeypatch.setattr(claude_auth.ClaudeAuthService, "_resolve_binary", lambda self: None)

    with pytest.raises(model_map.RouteUnavailable, match="Claude Code is not installed"):
        model_map.route_for(None, "claude-api", "m", account_id=SUBSCRIPTION_ACCOUNT)
    assert model_map.usable_providers(None) == []
    assert model_map.access_choices() == {}


def test_a_named_claude_account_is_probed_and_passed_to_the_runtime(claude):
    from dodaios import agent_accounts

    work = agent_accounts.create_account("claude", "Work")
    fake_claude_cli.sign_in(work.config_dir, fake_claude_cli.SUBSCRIPTION)
    # The default account is signed out: only the named one may answer.
    fake_claude_cli.sign_in(claude.default, fake_claude_cli.LOGGED_OUT)

    route = model_map.route_for(None, "claude-api", "m", account_id=work.id)

    assert route.env()["CLAUDE_CONFIG_DIR"] == str(work.config_dir)
    assert fake_claude_cli.calls(work.config_dir) == [["auth", "status", "--json"]]
    assert fake_claude_cli.calls(claude.default) == []


def test_pickers_offer_the_subscription_only_when_the_cli_is_signed_in(claude):
    fake_claude_cli.sign_in(claude.default, fake_claude_cli.SUBSCRIPTION)
    assert model_map.usable_providers(None) == ["claude-api"]
    assert model_map.access_choices() == {"claude-api": ["subscription"]}

    claude_auth.clear_version_cache()  # forgets the cached auth status too
    fake_claude_cli.sign_in(claude.default, fake_claude_cli.LOGGED_OUT)
    claude.secrets["key"] = _KEY
    assert model_map.access_choices() == {"claude-api": ["api"]}


def test_prepare_route_keeps_the_cli_route_out_of_the_gateway(claude):
    fake_claude_cli.sign_in(claude.default, fake_claude_cli.SUBSCRIPTION)

    route = asyncio.run(model_map.prepare_route(None, "claude-api", "m", agent_id="a1"))

    assert route.transport == "claude_cli" and route.api_key is None
    assert gateway._GRANTS == {}


def test_the_gateway_refuses_a_subscription_seat_instead_of_calling_http(claude, monkeypatch):
    """A token minted while the agent ran on its key, then the key was removed:
    the gateway must not answer it on the Claude login (or anything else)."""
    claude.secrets["key"] = _KEY
    token = gateway.grant_token("a1", "claude-api", "")
    claude.secrets["key"] = None
    built: list[str] = []
    monkeypatch.setattr(gateway, "_new_brain", lambda provider, model: built.append(provider))
    from dodaios.core.protocols import BrainRequest

    grant = gateway.verify(token)
    assert grant is not None

    async def drain() -> None:
        async for _delta in gateway._deltas(grant, "m", BrainRequest(messages=[])):
            pass

    with pytest.raises(gateway.GatewayError) as exc:
        asyncio.run(drain())
    assert exc.value.code == "claude_cli_only" and exc.value.status == 409
    assert built == []


def test_claude_login_never_reads_a_credential_file(claude, monkeypatch):
    """The subscription check asks the CLI; it never opens the login itself."""
    import dodaios.claude_credentials as credentials

    def forbidden(*args, **kwargs):
        pytest.fail("the Claude login must not be read by Dodaios")

    monkeypatch.setattr(credentials, "freshest_claude_oauth", forbidden)
    fake_claude_cli.sign_in(claude.default, fake_claude_cli.SUBSCRIPTION)

    model_map.claude_login(SUBSCRIPTION_ACCOUNT)


def test_the_fake_cli_launcher_is_a_real_process(tmp_path):
    """Guard for the fake itself: it answers only ``auth status``."""
    import subprocess

    launcher = fake_claude_cli.install(tmp_path / "bin")
    account = tmp_path / "acct"
    fake_claude_cli.sign_in(account, fake_claude_cli.SUBSCRIPTION)
    env = {**__import__("os").environ, "CLAUDE_CONFIG_DIR": str(account)}
    status = subprocess.run(
        [str(launcher), "auth", "status", "--json"], capture_output=True, text=True, env=env,
        check=False,
    )
    model = subprocess.run(
        [str(launcher), "-p", "hi"], capture_output=True, text=True, env=env, check=False,
    )
    assert '"loggedIn": true' in status.stdout
    assert model.returncode == 3
    assert Path(account / "fake-calls.log").is_file()
