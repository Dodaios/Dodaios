"""Local model preload: the model loads while the person types, not after send."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx

from dodaios.brain import ollama_profiles
from dodaios.ui.web import agent_chat_routes


def _recording_transport(calls: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"path": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(200, json={"done": True})

    return httpx.MockTransport(handler)


def test_load_now_asks_every_time() -> None:
    # The server unloads an idle model, so a preload is never memoized.
    calls: list[dict[str, Any]] = []
    transport = _recording_transport(calls)
    for _ in range(2):
        assert asyncio.run(
            ollama_profiles.load_now("http://x", "m", "30m", transport=transport)
        )
    assert [c["path"] for c in calls] == ["/api/generate", "/api/generate"]
    assert calls[0]["body"] == {"model": "m", "stream": False, "keep_alive": "30m"}


def test_load_now_keeps_server_default_without_keep_alive() -> None:
    calls: list[dict[str, Any]] = []
    asyncio.run(
        ollama_profiles.load_now("http://x", "m", None, transport=_recording_transport(calls))
    )
    assert "keep_alive" not in calls[0]["body"]


def test_load_now_never_raises() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert not asyncio.run(
        ollama_profiles.load_now("http://x", "m", None, transport=httpx.MockTransport(broken))
    )


def test_preload_is_a_noop_for_brains_without_preload(monkeypatch) -> None:
    hosted = SimpleNamespace()
    manager = SimpleNamespace(_get_brain=lambda provider, model: hosted)
    monkeypatch.setattr("dodaios.agent_chat.runner_brain.brain_manager", lambda: manager)
    monkeypatch.setattr("dodaios.agent_chat.runner_brain._default_model", lambda b, p: None)
    assert agent_chat_routes._preload_provider_model("openai", "") is False


def test_preload_starts_a_local_load(monkeypatch) -> None:
    loaded: list[bool] = []

    async def preload() -> bool:
        loaded.append(True)
        return True

    local = SimpleNamespace(preload=preload)
    manager = SimpleNamespace(_get_brain=lambda provider, model: local)
    monkeypatch.setattr("dodaios.agent_chat.runner_brain.brain_manager", lambda: manager)
    monkeypatch.setattr("dodaios.agent_chat.runner_brain._default_model", lambda b, p: "m")

    async def run() -> bool:
        started = agent_chat_routes._preload_provider_model("ollama", "")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return started

    assert asyncio.run(run()) is True
    assert loaded == [True]
