"""Generic local OpenAI-compatible brain: required base URL, optional key.

The card covers HuggingFace transformers serve, llama.cpp llama-server,
LM Studio, and vLLM with ONE adapter. Unlike the cloud brains there is no
vendor default endpoint — a missing base URL must raise an honest,
example-bearing English error, never guess a port. The key is optional and
only forwarded when the user stored one.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

import jarvis.core.config as cfg
from jarvis.core.config import BrainConfig, BrainProviderConfig, JarvisConfig
from jarvis.plugins.brain.local_openai import LocalOpenAIBrain
from tests.fakes.provider_config import install_provider_config


class _FakeOpenAI:
    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        _FakeOpenAI.last_kwargs = kwargs


def _with_base_url(url: str | None, monkeypatch, stored_key: str | None = None) -> None:
    providers = {}
    if url is not None:
        providers["local-openai"] = BrainProviderConfig(base_url=url)
    conf = JarvisConfig(brain=BrainConfig(providers=providers))
    install_provider_config(monkeypatch, conf)
    monkeypatch.setattr(
        cfg,
        "get_secret",
        lambda key, env=None: stored_key if key == "local_openai_api_key" else None,
    )


# ── Base URL is REQUIRED ─────────────────────────────────────────────────
def test_missing_base_url_gives_honest_examples(monkeypatch) -> None:
    _with_base_url(None, monkeypatch)
    with pytest.raises(RuntimeError) as err:
        LocalOpenAIBrain()._resolve_root()
    msg = str(err.value)
    # The error must teach the fix: the config key and real example ports.
    assert "local-openai" in msg
    assert "http://localhost:8000" in msg  # transformers serve / vLLM
    assert "http://localhost:8080" in msg  # llama.cpp llama-server
    assert "http://localhost:1234" in msg  # LM Studio


def test_client_appends_v1_to_root(monkeypatch) -> None:
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _with_base_url("http://localhost:8000", monkeypatch)
    LocalOpenAIBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == "http://localhost:8000/v1"
    # No stored key → placeholder the server ignores.
    assert _FakeOpenAI.last_kwargs["api_key"] == "local"


def test_client_normalizes_pasted_v1(monkeypatch) -> None:
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _with_base_url("http://localhost:1234/v1/", monkeypatch)
    LocalOpenAIBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == "http://localhost:1234/v1"


def test_optional_key_is_forwarded_when_stored(monkeypatch) -> None:
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _with_base_url("http://localhost:8000", monkeypatch, stored_key="sk-local-test")
    LocalOpenAIBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["api_key"] == "sk-local-test"


def test_client_timeout_fast_connect_wide_read(monkeypatch) -> None:
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _with_base_url("http://localhost:8000", monkeypatch)
    LocalOpenAIBrain()._ensure_client()
    timeout = _FakeOpenAI.last_kwargs["timeout"]
    assert timeout.connect <= 2.0
    assert timeout.read >= 120.0


# ── Model discovery via /v1/models ───────────────────────────────────────
class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    payload: dict[str, Any] = {}
    fail: bool = False
    last_url: str | None = None
    last_headers: dict[str, str] | None = None

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _FakeResponse:
        _FakeAsyncClient.last_url = url
        _FakeAsyncClient.last_headers = headers
        if _FakeAsyncClient.fail:
            raise httpx.ConnectError("connection refused")
        return _FakeResponse(_FakeAsyncClient.payload)


@pytest.fixture()
def fake_models(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.fail = False
    _FakeAsyncClient.payload = {}
    _FakeAsyncClient.last_url = None
    _FakeAsyncClient.last_headers = None
    return _FakeAsyncClient


async def test_discovery_uses_first_served_model(monkeypatch, fake_models) -> None:
    _with_base_url("http://localhost:8000", monkeypatch)
    fake_models.payload = {"data": [{"id": "Qwen/Qwen3.5-9B"}, {"id": "other"}]}
    brain = LocalOpenAIBrain()
    assert await brain._resolve_model() == "Qwen/Qwen3.5-9B"
    assert fake_models.last_url == "http://localhost:8000/v1/models"


async def test_discovery_sends_bearer_when_key_stored(monkeypatch, fake_models) -> None:
    _with_base_url("http://localhost:8000", monkeypatch, stored_key="sk-local-test")
    fake_models.payload = {"data": [{"id": "m"}]}
    await LocalOpenAIBrain()._resolve_model()
    assert fake_models.last_headers == {"Authorization": "Bearer sk-local-test"}


async def test_empty_model_list_gives_honest_error(monkeypatch, fake_models) -> None:
    _with_base_url("http://localhost:8000", monkeypatch)
    fake_models.payload = {"data": []}
    with pytest.raises(RuntimeError) as err:
        await LocalOpenAIBrain()._resolve_model()
    assert "/v1/models is empty" in str(err.value)


async def test_unreachable_server_gives_honest_error(monkeypatch, fake_models) -> None:
    _with_base_url("http://localhost:8000", monkeypatch)
    fake_models.fail = True
    with pytest.raises(RuntimeError) as err:
        await LocalOpenAIBrain()._resolve_model()
    msg = str(err.value)
    assert "not reachable" in msg
    assert "http://localhost:8000" in msg


# ── Vision: blind unless the server itself says otherwise ────────────────
def test_vision_stays_blind_when_the_server_declares_nothing(monkeypatch) -> None:
    """The common case: an OpenAI-compatible server publishes no modality
    fields, so the honest answer is "cannot see" — a confident description of a
    picture nobody looked at is the failure worth being conservative about."""
    import jarvis.brain.model_catalog as mc

    monkeypatch.setattr(
        mc, "model_capabilities", lambda provider, model: {"vision": None, "tools": None}
    )
    assert LocalOpenAIBrain(model="Qwen/Qwen3.5-9B").supports_vision is False


def test_vision_believes_a_server_that_declares_image_input(monkeypatch) -> None:
    """Some servers DO publish ``architecture.input_modalities``; a user who
    runs a multimodal model there should not have to move to another card."""
    import jarvis.brain.model_catalog as mc

    monkeypatch.setattr(
        mc, "model_capabilities", lambda provider, model: {"vision": True, "tools": True}
    )
    assert LocalOpenAIBrain(model="Qwen/Qwen3-VL-8B").supports_vision is True


# ── Protocol surface ─────────────────────────────────────────────────────
def test_capability_flags_and_cost() -> None:
    brain = LocalOpenAIBrain(model="x")
    assert brain.supports_tools is True
    assert brain.can_call_tools() is True
    # Deliberately False without evidence: whether an arbitrary local server
    # accepts image content is unknowable — the shared streamer then DROPS
    # images with a warning instead of letting a text-only server reject the
    # whole turn.
    assert brain.supports_vision is False
    req_like = type("R", (), {"messages": (), "max_tokens": 100})()
    assert brain.estimate_cost(req_like) == 0.0


def test_wizard_whitelists_the_optional_secret() -> None:
    """Saving the optional key from the app requires the wizard slot to exist
    (ALLOWED_SECRET_KEYS is derived from it)."""
    from jarvis.setup.wizard import SECRETS

    spec = next(s for s in SECRETS if s.key == "local_openai_api_key")
    assert spec.env_fallback == "LOCAL_OPENAI_API_KEY"
    # App-only: local servers usually need no key — it must not lengthen
    # first-run onboarding.
    assert spec.prompt is False


# ── Context window: ask the server, refuse what cannot fit ───────────────
class _Stream:
    """Stands in for the shared streamer; records whether it was reached."""

    calls: list[str] = []
    usage: dict[str, int] | None = None
    error: Exception | None = None

    @classmethod
    async def stream(cls, client: Any, model: str, req: Any, **kwargs: Any):
        from jarvis.core.protocols import BrainDelta

        cls.calls.append(model)
        if cls.error is not None:
            raise cls.error
        yield BrainDelta(content="ok", finish_reason="stop")
        if cls.usage is not None:
            yield BrainDelta(usage=cls.usage)


@pytest.fixture()
def served(monkeypatch):
    """A brain wired to a fake stream and a server whose window the test sets."""
    import openai

    from jarvis.brain import local_context
    from jarvis.plugins.brain import local_openai as plugin

    local_context.reset_registry()
    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(plugin, "stream_complete", _Stream.stream)
    _with_base_url("http://localhost:1234", monkeypatch)
    _Stream.calls = []
    _Stream.usage = None
    _Stream.error = None
    state: dict[str, Any] = {"before": None, "after": None, "asked": []}

    async def probe(root: str, model: str, *, headers=None, transport=None, fresh=False):
        state["asked"].append(fresh)
        window = state["after"] if fresh else state["before"]
        if window is not None:
            local_context.remember_window(
                "local-openai", root, model, window.tokens, source="server", kind=window.kind
            )
        return window

    monkeypatch.setattr(local_context, "probe_server_window", probe)
    yield state
    local_context.reset_registry()


def _request(chars: int = 20):
    from jarvis.core.protocols import BrainMessage, BrainRequest

    return BrainRequest(messages=(BrainMessage(role="user", content="x" * chars),))


async def _drain(brain: LocalOpenAIBrain, req: Any) -> list[Any]:
    return [delta async for delta in brain.complete(req)]


async def test_the_servers_own_window_becomes_the_budget(served) -> None:
    from jarvis.brain.local_context import ServerWindow

    served["before"] = ServerWindow(8_192, "llama.cpp")
    brain = LocalOpenAIBrain(model="qwen")
    assert brain.context_window == LocalOpenAIBrain.context_window
    await _drain(brain, _request())
    assert brain.context_window == 8_192
    # A brain built for the next turn budgets its tools for the real window.
    assert LocalOpenAIBrain(model="qwen").context_window == 8_192


async def test_a_request_the_loaded_window_cannot_hold_is_never_sent(served) -> None:
    from jarvis.brain.local_context import LocalContextError, ServerWindow

    served["before"] = ServerWindow(4_096, "lm-studio")
    with pytest.raises(LocalContextError) as err:
        await _drain(LocalOpenAIBrain(model="qwen"), _request(80_000))
    assert _Stream.calls == []
    msg = str(err.value)
    assert "4096" in msg and "LM Studio" in msg and "Context Length" in msg


async def test_a_model_loaded_by_the_request_is_checked_before_the_answer(served) -> None:
    """LM Studio loads on demand: before the request the window is unknown,
    after the first token the server states it. A prompt it cut short must not
    reach the caller as an answer."""
    from jarvis.brain.local_context import LocalContextError, ServerWindow

    served["after"] = ServerWindow(4_096, "lm-studio")
    handed_on: list[Any] = []
    with pytest.raises(LocalContextError):
        async for delta in LocalOpenAIBrain(model="qwen").complete(_request(80_000)):
            handed_on.append(delta)
    assert handed_on == []
    assert served["asked"] == [False, True]


async def test_a_server_refusal_names_the_setting(served) -> None:
    from jarvis.brain.local_context import LocalContextError

    _Stream.error = RuntimeError(
        "Error code: 400 - the request exceeds the available context size"
    )
    with pytest.raises(LocalContextError) as err:
        await _drain(LocalOpenAIBrain(model="qwen"), _request(80_000))
    assert "--ctx-size" in str(err.value) and "Context Length" in str(err.value)


async def test_other_server_errors_pass_through_unchanged(served) -> None:
    _Stream.error = RuntimeError("Error code: 500 - model crashed")
    with pytest.raises(RuntimeError) as err:
        await _drain(LocalOpenAIBrain(model="qwen"), _request())
    assert "model crashed" in str(err.value)


async def test_a_silent_server_that_read_far_less_tightens_the_next_budget(served) -> None:
    """No way to ask and no refusal: the only evidence is how many prompt
    tokens the server says it read. That is a suspicion, so the turn is not
    failed; the next one is planned for what the server demonstrably holds."""
    _Stream.usage = {"input_tokens": 4_096, "output_tokens": 5}
    brain = LocalOpenAIBrain(model="qwen")
    deltas = await _drain(brain, _request(80_000))
    assert deltas[0].content == "ok"
    # One odd response changes nothing.
    assert brain.context_window == LocalOpenAIBrain.context_window
    await _drain(brain, _request(80_000))
    assert brain.context_window == 4_096
    assert LocalOpenAIBrain(model="qwen").context_window == 4_096


async def test_a_later_full_read_clears_the_suspicion(served) -> None:
    _Stream.usage = {"input_tokens": 4_096, "output_tokens": 5}
    brain = LocalOpenAIBrain(model="qwen")
    await _drain(brain, _request(80_000))
    await _drain(brain, _request(80_000))
    assert brain.context_window == 4_096
    # The server now reports more than the suspected window, so it was wrong.
    _Stream.usage = {"input_tokens": 12_000, "output_tokens": 5}
    await _drain(brain, _request(40_000))
    assert brain.context_window == LocalOpenAIBrain.context_window
    assert LocalOpenAIBrain(model="qwen").context_window == LocalOpenAIBrain.context_window


async def test_the_window_is_settled_before_the_first_turn_is_budgeted(served) -> None:
    """Tools are fitted before complete(). A brain that only learned its
    window there would have its first turn refused whole, not trimmed."""
    from jarvis.brain.local_context import ServerWindow

    served["before"] = ServerWindow(8_192, "llama.cpp")
    brain = LocalOpenAIBrain(model="qwen")
    await brain.prepare_context_window()
    assert brain.context_window == 8_192
    assert _Stream.calls == []


async def test_a_refusal_does_not_claim_a_prompt_larger_than_the_window(served) -> None:
    """vLLM counts prompt plus reply. The sentence must not say the prompt
    needs less than the window and then call the window too small."""
    from jarvis.brain.local_context import LocalContextError, ServerWindow

    served["before"] = ServerWindow(8_192, "vllm")
    _Stream.error = RuntimeError("This model's maximum context length is 8192 tokens")
    with pytest.raises(LocalContextError) as err:
        await _drain(LocalOpenAIBrain(model="qwen"), _request(8_000))
    msg = str(err.value)
    assert err.value.refused is True
    assert "refused this request as too large" in msg
    assert "--max-model-len 16384" in msg
