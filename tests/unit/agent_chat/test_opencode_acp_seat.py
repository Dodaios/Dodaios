"""The ``opencode acp`` seat: what the planner spawns, and the exchange it makes.

The turn is the ACP pipeline OpenMausBot drives for OpenCode — ``initialize`` ->
``session/new`` (or ``session/load``) -> ``session/set_config_option`` for the
picked model -> ``session/prompt``. The transport and the process belong to the
CLI runner, so this file feeds ``AcpTurn`` the frames an agent sends and reads
the frames it writes back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import runner_cli as rc
from dodaios.agent_runtimes.acp import AcpTurn


class _IO:
    """The runner's side of an ACP turn, recorded instead of written."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    async def write(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def ask(self, call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        return "allow"


def _model_option(value: str = "opencode/big-pickle") -> dict[str, Any]:
    return {
        "id": "model",
        "type": "select",
        "category": "model",
        "currentValue": "",
        "options": [{"value": value, "name": value}],
    }


@pytest.fixture(name="seat")
def seat_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """``plan_opencode_acp`` with the binary found, as ``opencode`` is installed."""

    monkeypatch.setattr(rc, "_which", lambda *names: "opencode")

    def plan(**overrides: Any) -> Any:
        kwargs: dict[str, Any] = {
            "prompt": "hello",
            "cwd": tmp_path,
            "model": "opencode/big-pickle",
            "effort": "",
            "permission_mode": "default",
            "resume": None,
        }
        kwargs.update(overrides)
        return rc.plan_opencode_acp(**kwargs)

    return plan


def test_the_seat_spawns_the_acp_server_not_a_run(seat: Any) -> None:
    plan = seat()

    assert plan.argv[-1] == "acp"
    assert plan.shape == "acp"
    # The turn writes its own requests on stdin; the pump closes it, never
    # feeding it a prompt as text.
    assert plan.keep_stdin is True
    assert plan.stdin_text is None
    assert isinstance(plan.acp, AcpTurn)
    assert plan.acp.config["model"] == "opencode/big-pickle"


def test_the_chat_mode_decides_how_permission_requests_are_answered(seat: Any) -> None:
    asking = seat(permission_mode="default")
    assert asking.acp.auto_allow is False
    assert asking.acp.auto_deny is False

    full = seat(permission_mode="auto")
    assert full.acp.auto_allow is True

    planning = seat(permission_mode="plan")
    assert planning.acp.auto_deny is True


def test_the_seat_offers_the_harness_tools_once_the_server_is_ready(
    seat: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.agent_chat import dodaios_harness

    monkeypatch.setattr(dodaios_harness, "endpoint", lambda: "http://127.0.0.1:1/api/mcp")
    monkeypatch.setattr(dodaios_harness, "control_key", lambda: "key")

    server = seat().acp.mcp_servers[0]
    assert server.url == "http://127.0.0.1:1/api/mcp"
    assert server.headers["Authorization"] == "Bearer key"


def test_an_unbound_server_hands_over_no_tools(seat: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.agent_chat import dodaios_harness

    monkeypatch.setattr(dodaios_harness, "endpoint", lambda: None)
    assert seat().acp.mcp_servers == []


async def test_the_model_is_a_config_option_and_the_prompt_waits_for_it(
    tmp_path: Path,
) -> None:
    io = _IO()
    turn = AcpTurn(
        turn_id="t1",
        cwd=str(tmp_path),
        prompt_text="hello",
        config={"model": "opencode/big-pickle"},
    )

    await turn.on_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "agentInfo": {"name": "OpenCode", "version": "2"},
                "agentCapabilities": {"loadSession": True},
            },
        },
        io,
    )
    assert io.frames[-1]["method"] == "session/new"
    assert turn.can_load is True

    await turn.on_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"sessionId": "ses_1", "configOptions": [_model_option()]},
        },
        io,
    )
    assert io.frames[-1]["method"] == "session/set_config_option"
    assert io.frames[-1]["params"] == {
        "sessionId": "ses_1",
        "configId": "model",
        "value": "opencode/big-pickle",
    }

    await turn.on_message({"jsonrpc": "2.0", "id": 10, "result": {"configOptions": []}}, io)
    assert io.frames[-1]["method"] == "session/prompt"
    assert io.frames[-1]["params"]["sessionId"] == "ses_1"
    assert io.frames[-1]["params"]["prompt"] == [{"type": "text", "text": "hello"}]
    assert turn.vendor_session == "ses_1"

    await turn.on_message(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "ses_1",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "world"},
                },
            },
        },
        io,
    )
    await turn.on_message(
        {"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}}, io
    )
    assert turn.prompt_answered is True
    assert turn.saw_result is True
    assert turn.result_text == "world"


async def test_an_option_the_session_does_not_offer_is_skipped(tmp_path: Path) -> None:
    io = _IO()
    turn = AcpTurn(
        turn_id="t1",
        cwd=str(tmp_path),
        prompt_text="hello",
        config={"model": "opencode/gone", "variant": "high"},
    )

    await turn.on_message(
        {"jsonrpc": "2.0", "id": 1, "result": {"agentCapabilities": {"loadSession": True}}},
        io,
    )
    await turn.on_message(
        {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "ses_1", "configOptions": []}},
        io,
    )

    # Nothing to set: the prompt goes out at once rather than the turn failing.
    assert io.frames[-1]["method"] == "session/prompt"
