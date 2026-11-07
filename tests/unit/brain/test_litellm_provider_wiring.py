"""LiteLLM is a hosted-by-you OpenAI-compatible gateway, wired like OpenRouter.

The difference from OpenRouter is the host: there is no public LiteLLM URL,
so the card stores a server URL (default http://localhost:4000/v1) and the
catalog is whatever that proxy lists.
"""
from __future__ import annotations

from typing import Any

import pytest

import dodaios.core.config as cfg
from dodaios.brain.manager import PROVIDER_ALIASES, TIER_DEFAULTS_BY_PROVIDER
from dodaios.brain.model_catalog import CATALOG_PROVIDERS, ModelCatalog, _ENDPOINTS
from dodaios.brain.provider_registry import BrainProviderRegistry
from dodaios.core.config import BrainConfig, BrainProviderConfig, JarvisConfig
from dodaios.missions.init import _API_AGENT_SLUGS
from dodaios.missions.worker_runtime.provider_map import env_vars_for, to_worker_slug
from dodaios.missions.workers.api_agent_worker import _BRAIN_BY_PROVIDER, supports_api_agent_worker
from dodaios.core.protocols import BrainMessage, BrainRequest
from dodaios.plugins.brain.litellm import (
    BASE_URL,
    LiteLLMBrain,
    context_tokens_from_model_info,
    first_chat_model,
    fit_reply_cap,
    openai_client_base,
    openai_server_root,
)
from dodaios.ui.web.provider_spec import get_spec
from tests.fakes.provider_config import install_provider_config


def test_litellm_is_a_registered_brain_plugin() -> None:
    reg = BrainProviderRegistry()
    assert "litellm" in reg.available()
    assert "litellm" not in reg.failed()
    brain = reg.instantiate("litellm")
    assert brain.name == "litellm"
    assert brain.can_call_tools() is True


def test_litellm_credential_slot_resolves() -> None:
    assert cfg.PROVIDER_SECRET_CANDIDATES["litellm"][0] == (
        "litellm_api_key",
        "LITELLM_API_KEY",
    )


def test_litellm_provider_spec_has_a_host_field() -> None:
    spec = get_spec("litellm")
    ref = get_spec("openrouter")
    assert spec is not None and ref is not None
    assert spec.tier == ref.tier == "brain"
    assert spec.auth_mode == ref.auth_mode == "api_key"
    assert spec.secret_keys == ("litellm_api_key",)
    assert spec.brain_switchable is True
    assert spec.supports_base_url is True
    assert spec.default_base_url == BASE_URL


async def test_litellm_catalog_uses_the_saved_host(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    assert "litellm" in CATALOG_PROVIDERS
    ep = _ENDPOINTS["litellm"]
    assert ep.auth == "bearer"
    assert ep.vendor_base + ep.path == "http://localhost:4000/v1/models"

    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": [{"id": "my-alias"}]}

    class _Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def get(self, url: str, headers=None, params=None) -> _Response:
            self.calls.append(url)
            return _Response()

    client = _Client()
    install_provider_config(
        monkeypatch,
        JarvisConfig(
            brain=BrainConfig(
                providers={"litellm": BrainProviderConfig(base_url="https://llm.example/v1")}
            )
        ),
    )
    monkeypatch.setattr(cfg, "get_provider_secret", lambda pid: "sk-proxy")
    catalog = ModelCatalog(cache_path=tmp_path / "cache.json", http_client_factory=lambda: client)
    result = await catalog.list_models("litellm")
    assert result.source == "live"
    assert [m.id for m in result.models] == ["my-alias"]
    assert client.calls == ["https://llm.example/v1/models"]


async def test_litellm_catalog_adds_v1_when_the_host_omits_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class _Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": [{"id": "my-alias"}]}

    class _Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def get(self, url: str, headers=None, params=None) -> _Response:
            self.calls.append(url)
            return _Response()

    client = _Client()
    install_provider_config(
        monkeypatch,
        JarvisConfig(
            brain=BrainConfig(
                providers={"litellm": BrainProviderConfig(base_url="https://llm.example")}
            )
        ),
    )
    monkeypatch.setattr(cfg, "get_provider_secret", lambda pid: "sk-proxy")
    catalog = ModelCatalog(cache_path=tmp_path / "cache.json", http_client_factory=lambda: client)
    await catalog.list_models("litellm")
    assert client.calls == ["https://llm.example/v1/models"]


def test_litellm_client_uses_default_host_and_saved_host(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    class _FakeOpenAI:
        last_kwargs: dict[str, Any] = {}

        def __init__(self, **kwargs: Any) -> None:
            type(self).last_kwargs = kwargs

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    install_provider_config(monkeypatch, JarvisConfig())
    monkeypatch.setattr(cfg, "get_provider_secret", lambda pid: "sk-proxy")
    LiteLLMBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == BASE_URL
    assert _FakeOpenAI.last_kwargs["api_key"] == "sk-proxy"


def test_litellm_client_uses_the_saved_host(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    class _FakeOpenAI:
        last_kwargs: dict[str, Any] = {}

        def __init__(self, **kwargs: Any) -> None:
            type(self).last_kwargs = kwargs

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    install_provider_config(
        monkeypatch,
        JarvisConfig(
            brain=BrainConfig(
                providers={"litellm": BrainProviderConfig(base_url="https://llm.example/v1")}
            )
        ),
    )
    monkeypatch.setattr(cfg, "get_provider_secret", lambda pid: "sk-proxy")
    LiteLLMBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == "https://llm.example/v1"


def test_litellm_client_adds_v1_when_the_host_omits_it(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    class _FakeOpenAI:
        last_kwargs: dict[str, Any] = {}

        def __init__(self, **kwargs: Any) -> None:
            type(self).last_kwargs = kwargs

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    install_provider_config(
        monkeypatch,
        JarvisConfig(
            brain=BrainConfig(
                providers={"litellm": BrainProviderConfig(base_url="https://llm.example")}
            )
        ),
    )
    monkeypatch.setattr(cfg, "get_provider_secret", lambda pid: "sk-proxy")
    LiteLLMBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == "https://llm.example/v1"
    assert openai_client_base("https://llm.example/v1") == "https://llm.example/v1"


def test_litellm_tier_default_is_discovered_not_invented() -> None:
    assert TIER_DEFAULTS_BY_PROVIDER["router"]["litellm"] == ""
    assert TIER_DEFAULTS_BY_PROVIDER["deep"]["litellm"] == ""
    assert PROVIDER_ALIASES["litellm"] == "litellm"


def test_litellm_reply_cap_fits_the_learned_window() -> None:
    req = BrainRequest(
        messages=(BrainMessage(role="user", content="hello " * 300),),
        max_tokens=32_768,
    )
    capped = fit_reply_cap(req, 8192)
    assert capped.max_tokens < 8192
    assert capped.max_tokens < req.max_tokens


def test_litellm_unknown_model_cannot_see(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dodaios.brain.model_catalog.model_capabilities",
        lambda provider, model: {"vision": None, "tools": None},
    )
    monkeypatch.setattr(
        "dodaios.brain.model_catalog.model_context_length",
        lambda provider, model: None,
    )
    assert LiteLLMBrain(model="local-llama").supports_vision is False
    monkeypatch.setattr(
        "dodaios.brain.model_catalog.model_capabilities",
        lambda provider, model: {"vision": True, "tools": True},
    )
    assert LiteLLMBrain(model="gpt-4o").supports_vision is True


async def test_litellm_complete_caps_the_reply_and_drops_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brain = LiteLLMBrain(model="local-llama")
    brain.context_window = 8192
    brain.supports_vision = False
    seen: dict[str, object] = {}

    async def _model(_client: object) -> str:
        return "local-llama"

    async def _stream(_client: object, model: str, req: BrainRequest, **kwargs: object):
        seen["model"] = model
        seen["max_tokens"] = req.max_tokens
        seen["vision"] = kwargs.get("supports_vision")
        if False:
            yield None

    monkeypatch.setattr(brain, "_ensure_client", lambda: object())
    monkeypatch.setattr(brain, "_resolve_model", _model)
    monkeypatch.setattr("dodaios.plugins.brain.litellm.stream_complete", _stream)
    req = BrainRequest(messages=(BrainMessage(role="user", content="hi"),), max_tokens=32_768)
    async for _delta in brain.complete(req):
        pass
    assert seen["vision"] is False
    assert seen["max_tokens"] != 32_768
    assert int(seen["max_tokens"]) <= 8192


def test_litellm_discovery_skips_a_non_chat_model() -> None:
    assert first_chat_model(["text-embedding-3-small", "my-alias"]) == "my-alias"
    assert first_chat_model(["text-embedding-3-small"]) == ""
    assert openai_server_root("https://llm.example/v1/") == "https://llm.example"


def test_litellm_model_info_window_is_the_input_limit() -> None:
    payload = {
        "data": [
            {
                "model_name": "local-llama",
                "model_info": {"max_input_tokens": 8192, "max_output_tokens": 1024},
            }
        ]
    }
    assert context_tokens_from_model_info(payload, "local-llama") == 8192
    assert context_tokens_from_model_info(payload, "other") is None


async def test_litellm_prepare_context_window_uses_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.brain.local_context import ServerWindow

    brain = LiteLLMBrain(model="local-llama")

    def _client() -> object:
        return type("C", (), {"base_url": "http://localhost:4000/v1"})()

    monkeypatch.setattr(brain, "_ensure_client", _client)

    async def _probe(root: str, model: str, **kwargs: object) -> ServerWindow:
        assert root == "http://localhost:4000"
        assert model == "local-llama"
        assert kwargs["provider"] == "litellm"
        return ServerWindow(8192, "litellm")

    monkeypatch.setattr("dodaios.brain.local_context.probe_server_window", _probe)
    await brain.prepare_context_window()
    assert brain.context_window == 8192


def test_litellm_is_an_agent_provider() -> None:
    from dodaios.agent_chat.catalog import offers
    from dodaios.agent_chat.runner_api import supports_api_runner

    assert offers("society", "litellm")
    assert supports_api_runner("litellm")


def test_litellm_runs_as_in_process_api_agent() -> None:
    assert "litellm" in _API_AGENT_SLUGS
    assert supports_api_agent_worker("litellm") is True
    assert "litellm" in _BRAIN_BY_PROVIDER
    assert to_worker_slug("litellm") == "litellm"
    assert "LITELLM_API_KEY" in env_vars_for("litellm")
