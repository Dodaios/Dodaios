"""OpenCodeBrain — the ACP exchange OpenMausBot's ``opencode acp`` pipeline makes.

The subprocess is faked: this file feeds the brain the JSON-RPC frames a real
OpenCode server sends and reads the frames the brain writes back. No binary,
network or temp folder in the user's data directory is touched.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from dodaios.core.protocols import BrainMessage, BrainRequest
from dodaios.plugins.brain import opencode as ocmod
from dodaios.plugins.brain.opencode import OpenCodeBrain, _config_for


def _req(text: str = "Hello") -> BrainRequest:
    return BrainRequest(messages=(BrainMessage(role="user", content=text),))


def _frame(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


def _model_option(value: str = "opencode/big-pickle") -> dict[str, Any]:
    return {
        "id": "model",
        "type": "select",
        "category": "model",
        "currentValue": "",
        "options": [{"value": value, "name": value}],
    }


def _initialize_result() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "agentInfo": {"name": "OpenCode", "version": "2.2.5"},
            "agentCapabilities": {"loadSession": True},
        },
    }


def _session_result(
    *, config_options: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "sessionId": "ses_1",
            "configOptions": config_options if config_options is not None else [_model_option()],
        },
    }


def _chunk(text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "ses_1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        },
    }


def _prompt_result(
    *,
    stop_reason: str = "end_turn",
    usage: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if error is not None:
        return {"jsonrpc": "2.0", "id": 3, "error": error}
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"stopReason": stop_reason, "usage": usage or {}},
    }


class _FakeStdin:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        for line in data.decode("utf-8").splitlines():
            if line.strip():
                self.frames.append(json.loads(line))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def methods(self) -> list[str]:
        return [str(frame.get("method") or frame.get("id")) for frame in self.frames]


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        return self._lines.pop(0) if self._lines else b""


class _FakeStderr:
    async def readline(self) -> bytes:
        return b""


class _FakeProc:
    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout([_frame(line) for line in lines])
        self.stderr = _FakeStderr()
        self.pid = 4242
        self.returncode: int | None = None
        self.killed = False

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


class _Spawned:
    """The fake process plus the argv/env the brain launched it with."""

    def __init__(self, proc: _FakeProc) -> None:
        self.proc = proc
        self.argv: tuple[Any, ...] = ()
        self.kwargs: dict[str, Any] = {}


def _install(
    monkeypatch: pytest.MonkeyPatch, lines: list[dict[str, Any]]
) -> _Spawned:
    spawned = _Spawned(_FakeProc(lines))

    async def fake_exec(*args: Any, **kwargs: Any) -> _FakeProc:
        if not spawned.argv:
            spawned.argv = args
            spawned.kwargs = kwargs
            return spawned.proc
        # Any later spawn is the Windows taskkill in ``_stop``.
        return _FakeProc([])

    monkeypatch.setattr(ocmod, "_resolve_binary", lambda: "opencode")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return spawned


@pytest.mark.asyncio
async def test_complete_streams_the_acp_answer_and_applies_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned = _install(
        monkeypatch,
        [
            _initialize_result(),
            _session_result(),
            {
                "jsonrpc": "2.0",
                "id": 10,
                "result": {"configOptions": []},
            },
            _chunk("Hello "),
            _chunk("there"),
            _prompt_result(
                usage={"inputTokens": 12, "outputTokens": 5, "cachedReadTokens": 2}
            ),
        ],
    )

    brain = OpenCodeBrain(model="opencode/big-pickle")
    deltas = [delta async for delta in brain.complete(_req())]

    text = "".join(delta.content or "" for delta in deltas)
    assert text == "Hello there"
    assert any(delta.finish_reason == "stop" for delta in deltas)
    usage = next(delta.usage for delta in deltas if delta.usage)
    assert usage == {
        "input_tokens": 12,
        "output_tokens": 5,
        "cache_hit_tokens": 2,
    }

    # The same exchange OpenMausBot makes: initialize -> session/new ->
    # set_config_option(model) -> prompt, all over one ACP process.
    assert spawned.argv[-1] == "acp"
    methods = spawned.proc.stdin.methods()
    assert methods[:3] == ["initialize", "session/new", "session/set_config_option"]
    config = spawned.proc.stdin.frames[2]
    assert config["params"] == {
        "sessionId": "ses_1",
        "configId": "model",
        "value": "opencode/big-pickle",
    }
    prompt = spawned.proc.stdin.frames[3]
    assert prompt["method"] == "session/prompt"
    assert prompt["params"]["prompt"] == [{"type": "text", "text": brain._render_prompt(_req())}]
    # A throwaway cwd, never the caller's repository.
    assert "jarvis-opencode-brain-" in str(spawned.kwargs["cwd"])
    assert spawned.proc.stdin.closed is True


@pytest.mark.asyncio
async def test_config_option_the_session_does_not_offer_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned = _install(
        monkeypatch,
        [
            _initialize_result(),
            # Live OpenCode 2.2.5 offers ``model`` and ``mode`` only; a
            # session that offers neither of the brain's picks still prompts.
            _session_result(config_options=[{"id": "mode", "type": "select"}]),
            _chunk("ok"),
            _prompt_result(),
        ],
    )

    brain = OpenCodeBrain(model="opencode/big-pickle", structured_prompts=False)
    deltas = [delta async for delta in brain.complete(_req())]

    assert "".join(delta.content or "" for delta in deltas) == "ok"
    methods = spawned.proc.stdin.methods()
    assert "session/set_config_option" not in methods
    assert methods[1:3] == ["session/new", "session/prompt"]


@pytest.mark.asyncio
async def test_a_failed_prompt_raises_instead_of_returning_an_empty_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        [
            _initialize_result(),
            _session_result(config_options=[]),
            _prompt_result(error={"code": -32000, "message": "provider exploded"}),
        ],
    )

    brain = OpenCodeBrain()
    with pytest.raises(RuntimeError, match="provider exploded"):
        async for _ in brain.complete(_req()):
            pass


@pytest.mark.asyncio
async def test_an_answer_less_turn_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        [
            _initialize_result(),
            _session_result(config_options=[]),
            _prompt_result(),
        ],
    )

    brain = OpenCodeBrain()
    with pytest.raises(RuntimeError, match="no answer"):
        async for _ in brain.complete(_req()):
            pass


def test_config_for_sends_only_slug_models_and_the_effort() -> None:
    request = BrainRequest(
        messages=(BrainMessage(role="user", content="hi"),),
        reasoning_effort="high",
    )
    assert _config_for("opencode/big-pickle", request) == {
        "model": "opencode/big-pickle",
        "effort": "high",
        "variant": "high",
    }
    # A bare alias is not an ACP model id; leave the agent on its own default.
    assert _config_for("big-pickle", request) == {
        "effort": "high",
        "variant": "high",
    }
    assert _config_for("", BrainRequest(messages=())) == {}


def test_subscription_connected_probes_the_binary_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocmod, "_probe_cache", None)
    monkeypatch.setattr(ocmod, "_resolve_binary", lambda: "opencode")
    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = b"opencode/big-pickle\nopencode/glm-5.3-flash-free\n"

    def fake_run(argv: list[str], **_: Any) -> _Result:
        calls.append(argv)
        return _Result()

    monkeypatch.setattr(ocmod.subprocess, "run", fake_run)

    assert OpenCodeBrain.subscription_connected() is True
    assert OpenCodeBrain.subscription_connected() is True
    assert calls == [["opencode", "models"]]


def test_subscription_connected_is_false_without_the_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocmod, "_probe_cache", None)
    monkeypatch.setattr(ocmod, "_resolve_binary", lambda: None)

    assert OpenCodeBrain.subscription_connected() is False


def test_subscription_connected_is_false_when_no_model_is_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocmod, "_probe_cache", None)
    monkeypatch.setattr(ocmod, "_resolve_binary", lambda: "opencode")

    class _Result:
        returncode = 0
        stdout = b""

    monkeypatch.setattr(ocmod.subprocess, "run", lambda *a, **k: _Result())

    assert OpenCodeBrain.subscription_connected() is False


@pytest.mark.asyncio
async def test_complete_raises_when_the_binary_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ocmod, "_resolve_binary", lambda: None)
    brain = OpenCodeBrain()
    with pytest.raises(RuntimeError, match="not installed"):
        async for _ in brain.complete(_req()):
            pass
