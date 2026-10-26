"""What each runtime does with a Claude subscription route (``claude_cli``).

OpenClaw runs it on its bundled ``claude-cli`` backend, with no Dodaios
gateway provider at all; Hermes has no route there Dodaios installs and says
so. Neither ever gets a key or a bearer for it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.agent_runtimes.base import RuntimeLaunch, RuntimeTurn, RuntimeUnavailable
from dodaios.agent_runtimes.hermes import HermesRuntime
from dodaios.agent_runtimes.model_map import KEY_ENV_VAR, ModelRoute
from dodaios.agent_runtimes.openclaw import OpenClawRuntime

_TOKEN = "gw-" + "token"  # a fake Gateway token


def _cli_route(tmp_path: Path) -> ModelRoute:
    return ModelRoute(
        provider="claude-api",
        model="claude-fixture-5",
        base_url="",
        transport="claude_cli",
        api_key=None,
        claude_binary=str(tmp_path / "bin" / "claude"),
        claude_env=(("CLAUDE_CONFIG_DIR", str(tmp_path / "acct")),),
    )


def _turn(tmp_path: Path, **overrides) -> RuntimeTurn:
    values = {
        "agent_id": "clawd",
        "agent_name": "Clawd",
        "session_id": "society:clawd",
        "workspace": tmp_path,
        "route": _cli_route(tmp_path),
        "resume": None,
        "auto_approve": True,
        "mcp_url": "http://127.0.0.1:47820/api/control/mcp/",
        "control_key": "control-key-xyz",
    }
    values.update(overrides)
    return RuntimeTurn(**values)


def test_openclaw_runs_the_subscription_on_its_claude_cli_backend(tmp_path):
    config = OpenClawRuntime().config_for(_turn(tmp_path), port=4321, token=_TOKEN)

    defaults = config["agents"]["defaults"]
    assert defaults["model"] == {"primary": "anthropic/claude-fixture-5"}
    assert defaults["models"] == {
        "anthropic/claude-fixture-5": {"agentRuntime": {"id": "claude-cli"}},
    }
    # No provider pointing at Dodaios' gateway (or anywhere else over HTTP).
    assert "models" not in config
    text = repr(config)
    assert KEY_ENV_VAR not in text and "runtime-gateway" not in text
    # Dodaios' own MCP tools stay available, with their own approvals.
    assert "mcp" in config
    assert config["tools"]["exec"]["mode"] == "full"


def test_openclaw_without_bypass_refuses_native_tools_instead_of_hanging(tmp_path):
    ask = OpenClawRuntime().config_for(_turn(tmp_path, auto_approve=False), port=1, token=_TOKEN)
    no_shell = OpenClawRuntime().config_for(
        _turn(tmp_path, denied_native=frozenset({"shell"})), port=1, token=_TOKEN,
    )

    assert ask["tools"]["exec"]["mode"] == "deny"
    assert {"exec", "process"} <= set(no_shell["tools"]["deny"])


def test_an_api_key_route_on_openclaw_is_unchanged(tmp_path):
    from tests.unit.agent_runtimes.test_runtime_configs import _turn as api_turn

    config = OpenClawRuntime().config_for(api_turn(tmp_path), port=1, token=_TOKEN)
    assert config["models"]["providers"]
    assert config["agents"]["defaults"]["model"]["primary"].startswith("jarvis/")


def test_the_claude_cli_route_carries_only_the_account_selection(tmp_path):
    env = _cli_route(tmp_path).env()
    assert env == {"CLAUDE_CONFIG_DIR": str(tmp_path / "acct")}


def test_hermes_refuses_the_subscription_with_the_reason(tmp_path):
    runtime = HermesRuntime()

    with pytest.raises(RuntimeUnavailable, match="Hermes cannot run on the Claude subscription"):
        asyncio.run(runtime.launch(_turn(tmp_path)))
    assert asyncio.run(runtime.warm(_turn(tmp_path))) is False


def test_a_cli_turn_plans_without_a_gateway_token(tmp_path, monkeypatch):
    """The ACP runner watches gateway failures by token; the CLI route has none."""
    from dodaios.agent_chat import runner_acp
    from dodaios.agent_runtimes import gateway

    turn = _turn(tmp_path)
    released: list[str] = []

    class Runtime:
        label = "OpenClaw"

        async def launch(self, turn: RuntimeTurn) -> RuntimeLaunch:
            return RuntimeLaunch(
                argv=["openclaw", "acp"], env={}, cwd=tmp_path, acp_resume=None,
                release=lambda: released.append("slot"),
            )

    async def ready(*args):
        return None

    async def runtime_turn(*args, **kwargs):
        return turn

    async def agent(agent_id):
        return SimpleNamespace(agent_id=agent_id)

    monkeypatch.setattr(runner_acp, "driver", lambda name: Runtime())
    monkeypatch.setattr(runner_acp, "_ready", ready)
    monkeypatch.setattr(runner_acp, "_runtime_turn", runtime_turn)
    monkeypatch.setattr(runner_acp, "_agent", agent)
    gateway.reset()
    handle = SimpleNamespace(
        session=SimpleNamespace(session_id="society:clawd", permission_mode="bypass", effort=""),
        turn_id="t1",
        cancel=asyncio.Event(),
    )

    plan = asyncio.run(runner_acp.plan_runtime_turn(
        handle, "openclaw-cli", prompt="hi", cwd=tmp_path, resume=None, identity=None,
    ))

    assert not plan.provider_failure.done()
    assert gateway._FAILURES == {}
    plan.after_turn()
    assert released == ["slot"]
