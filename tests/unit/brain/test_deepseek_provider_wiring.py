"""DeepSeek uses its own credentials and completes a non-thinking tool turn."""

import json
from pathlib import Path
from typing import Any

import httpx
import keyring.core
import openai
import pytest

from dodaios.agent_chat.catalog import offers
from dodaios.agent_chat.effort import effort_levels
from dodaios.agent_chat.runner_api import supports_api_runner
from dodaios.brain.model_catalog import ModelCatalog
from dodaios.brain.provider_registry import BrainProviderRegistry
from dodaios.core import config as cfg
from dodaios.core.config import JarvisConfig
from dodaios.core.protocols import BrainMessage, BrainRequest
from dodaios.ui.web.agent_chat_routes import _catalog_rows
from dodaios.ui.web.provider_spec import get_spec
from tests.fakes.fake_keyring_backend import FakeKeyringBackend
from tests.fakes.provider_config import install_provider_config


@pytest.fixture
def deepseek_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install_provider_config(monkeypatch, JarvisConfig())
    monkeypatch.setattr(keyring.core, "_keyring_backend", FakeKeyringBackend())
    monkeypatch.setattr(cfg, "_KEYRING_BACKEND_READY", True)
    monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")


async def test_deepseek_streams_a_tool_call_and_accepts_its_result(
    monkeypatch: pytest.MonkeyPatch,
    deepseek_credentials: None,
) -> None:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer test-deepseek-key"
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["model"] == "deepseek-v4-pro"
        assert payload["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in payload
        if len(requests) == 1:
            delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ]
            }
            finish = "tool_calls"
        else:
            assert payload["messages"][-2]["tool_calls"][0]["id"] == "call_1"
            assert payload["messages"][-1] == {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "42",
            }
            delta = {"content": "The answer is 42."}
            finish = "stop"
        chunk = {
            "id": "test-completion",
            "created": 0,
            "model": "deepseek-v4-pro",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    sdk = openai.AsyncOpenAI
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: sdk(http_client=http, **kw))
        registry = BrainProviderRegistry()
        assert "deepseek" in registry.available(), registry.failed()
        brain = registry.instantiate("deepseek", model="deepseek-v4-pro")
        user = BrainMessage(role="user", content="Look up the answer.")
        tools = (
            {
                "name": "lookup",
                "description": "Look up the answer",
                "input_schema": {"type": "object", "properties": {}},
            },
        )
        first = BrainRequest(messages=(user,), tools=tools, reasoning_effort="high")
        deltas = [delta async for delta in brain.complete(first)]
        calls = [delta.tool_call for delta in deltas if delta.tool_call]
        assert calls == [{"id": "call_1", "name": "lookup", "input": {}}]
        assistant = BrainMessage(role="assistant", content=[{"type": "tool_use", **calls[0]}])
        result = BrainMessage(role="tool", content="42", tool_call_id="call_1")
        second = BrainRequest(messages=(user, assistant, result), tools=tools)
        answer = "".join([delta.content or "" async for delta in brain.complete(second)])
        assert answer == "The answer is 42."

        monkeypatch.delenv("DEEPSEEK_API_KEY")
        cfg._mark_secret_changed("deepseek_api_key")
        with pytest.raises(RuntimeError, match="No DeepSeek API key"):
            _ = [delta async for delta in brain.complete(second)]
        assert len(requests) == 2


async def test_deepseek_lists_official_models_with_its_key(
    tmp_path: Path,
    deepseek_credentials: None,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.deepseek.com/models"
        assert request.headers["authorization"] == "Bearer test-deepseek-key"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "deepseek-flash",
                        "object": "model",
                        "owned_by": "deepseek",
                        "input_modalities": ["text", "image"],
                    },
                ],
            },
        )

    catalog = ModelCatalog(
        cache_path=tmp_path / "catalog.json",
        http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = await catalog.list_models("deepseek")
    assert result.source == "live"
    assert [model.id for model in result.models] == ["deepseek-flash"]
    assert result.models[0].input_modalities == ("text",)


def test_deepseek_chat_catalog_reports_shared_key_presence(deepseek_credentials: None) -> None:
    row = next(row for row in _catalog_rows("jarvis", {}) if row["id"] == "deepseek")
    assert row["api_key_set"] is True
    assert row["default_model"] == "deepseek-flash"


def test_deepseek_settings_offer_an_api_chat_seat() -> None:
    spec = get_spec("deepseek")
    assert spec is not None and spec.brain_switchable
    assert spec.auth_mode == "api_key"
    assert spec.secret_keys == ("deepseek_api_key",)
    assert offers("society", "deepseek")
    assert supports_api_runner("deepseek")
    assert effort_levels("deepseek") == ("",)
