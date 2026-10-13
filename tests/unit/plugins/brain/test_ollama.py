"""Keyless local Ollama brain: endpoint normalization, discovery, honest errors.

The provider must work with ZERO credentials (§3): the SDK client gets a
dummy key, the server root comes from config override → OLLAMA_HOST → the
localhost default, and every failure surfaces an honest, actionable English
message instead of a fake model id that would 404.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from jarvis.core.config import BrainConfig, BrainProviderConfig, JarvisConfig
from jarvis.plugins.brain.ollama import (
    DEFAULT_SERVER_ROOT,
    RECOMMENDED_PULL,
    RECOMMENDED_VISION_PULL,
    OllamaBrain,
    default_server_root,
    normalize_server_root,
)
from tests.fakes.provider_config import install_provider_config


class _FakeOpenAI:
    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        _FakeOpenAI.last_kwargs = kwargs


@pytest.fixture(autouse=True)
def _forget_context_windows():
    """Sized and verified windows live per process; no test may inherit one."""
    from jarvis.brain import local_context
    from jarvis.plugins.brain import ollama as plugin

    plugin.reset_context_memo()
    local_context.reset_registry()
    yield
    plugin.reset_context_memo()
    local_context.reset_registry()


def _no_override(monkeypatch) -> None:
    install_provider_config(monkeypatch, JarvisConfig())
    monkeypatch.delenv("OLLAMA_HOST", raising=False)


def _override(url: str, monkeypatch) -> None:
    conf = JarvisConfig(brain=BrainConfig(providers={"ollama": BrainProviderConfig(base_url=url)}))
    install_provider_config(monkeypatch, conf)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)


# ── Server-root normalization ────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://localhost:11434/", "http://localhost:11434"),
        # A pasted OpenAI-compat suffix must not double up to /v1/v1.
        ("http://localhost:11434/v1", "http://localhost:11434"),
        ("http://localhost:11434/api", "http://localhost:11434"),
        # Bare host:port (the OLLAMA_HOST shape) gains a scheme.
        ("127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("mybox:11434", "http://mybox:11434"),
        # 0.0.0.0 is a server BIND address — as a client target it fails on
        # Windows, so it maps to localhost.
        ("0.0.0.0:11434", "http://localhost:11434"),
        ("https://gpu.lan:11434/", "https://gpu.lan:11434"),
        ("", DEFAULT_SERVER_ROOT),
        ("   ", DEFAULT_SERVER_ROOT),
    ],
)
def test_normalize_server_root(raw: str, expected: str) -> None:
    assert normalize_server_root(raw) == expected


def test_default_server_root_honors_ollama_host(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:12345")
    assert default_server_root() == "http://localhost:12345"


def test_default_server_root_without_env(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert default_server_root() == DEFAULT_SERVER_ROOT


# ── Client construction (keyless) ────────────────────────────────────────
def test_client_defaults_to_localhost_v1_with_dummy_key(monkeypatch) -> None:
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _no_override(monkeypatch)
    OllamaBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == "http://localhost:11434/v1"
    # Keyless: the SDK insists on a non-empty key, Ollama ignores it.
    assert _FakeOpenAI.last_kwargs["api_key"] == "ollama"
    assert _FakeOpenAI.last_kwargs["max_retries"] == 0


def test_client_uses_config_override_root(monkeypatch) -> None:
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _override("http://gpu.lan:11434", monkeypatch)
    OllamaBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == "http://gpu.lan:11434/v1"


def test_client_normalizes_pasted_v1_override(monkeypatch) -> None:
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _override("http://gpu.lan:11434/v1/", monkeypatch)
    OllamaBrain()._ensure_client()
    assert _FakeOpenAI.last_kwargs["base_url"] == "http://gpu.lan:11434/v1"


def test_client_timeout_fast_connect_wide_read(monkeypatch) -> None:
    """A dead local server must fail fast so the chain crosses families,
    while a slow CPU-bound generation may stream for minutes."""
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _no_override(monkeypatch)
    OllamaBrain()._ensure_client()
    timeout = _FakeOpenAI.last_kwargs["timeout"]
    assert timeout.connect <= 2.0
    assert timeout.read >= 120.0


# ── Model discovery via native /api/tags ─────────────────────────────────
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
    # /api/show capability map: model name -> capabilities list. Models absent
    # from the map answer with a chat-capable default.
    show_caps: dict[str, list[str]] = {}

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        _FakeAsyncClient.last_url = url
        if _FakeAsyncClient.fail:
            raise httpx.ConnectError("connection refused")
        return _FakeResponse(_FakeAsyncClient.payload)

    async def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        assert url.endswith("/api/show")
        name = str((json or {}).get("model") or "")
        caps = _FakeAsyncClient.show_caps.get(name, ["completion", "tools"])
        return _FakeResponse({"capabilities": caps})


@pytest.fixture()
def fake_tags(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.fail = False
    _FakeAsyncClient.payload = {}
    _FakeAsyncClient.last_url = None
    _FakeAsyncClient.show_caps = {}
    return _FakeAsyncClient


async def test_configured_model_skips_discovery(monkeypatch, fake_tags) -> None:
    _no_override(monkeypatch)
    brain = OllamaBrain(model="qwen3.5:9b")
    assert await brain._resolve_model() == "qwen3.5:9b"
    assert fake_tags.last_url is None  # no HTTP call


async def test_discovery_uses_smallest_downloaded_model(monkeypatch, fake_tags) -> None:
    """Live incident 2026-07-25: the first-installed pick loaded a 30B model
    (45 GB at its 256k default context) on a 32 GB box and froze the desktop.
    The silent default is the SMALLEST download; the user's pick wins."""
    _no_override(monkeypatch)
    fake_tags.payload = {
        "models": [
            {"name": "qwen3-coder:30b", "size": 18_000_000_000},
            {"name": "qwen2.5:7b", "size": 4_700_000_000},
            {"name": "deepseek-r1:14b", "size": 9_000_000_000},
        ]
    }
    brain = OllamaBrain()
    assert await brain._resolve_model() == "qwen2.5:7b"
    assert fake_tags.last_url == "http://localhost:11434/api/tags"
    # Cached: a second resolve must not depend on the server again.
    fake_tags.fail = True
    assert await brain._resolve_model() == "qwen2.5:7b"


async def test_discovery_never_picks_a_cloud_reference(monkeypatch, fake_tags) -> None:
    """``:cloud`` tags are ollama.com-proxied references, not local weights —
    the LOCAL brain must never default onto a path that leaves the machine."""
    _no_override(monkeypatch)
    fake_tags.payload = {
        "models": [
            {"name": "kimi-k2.5:cloud", "size": 1},
            {"name": "remote-thing", "size": 2, "remote": True},
            {"name": "qwen2.5:7b", "size": 4_700_000_000},
        ]
    }
    assert await OllamaBrain()._resolve_model() == "qwen2.5:7b"


async def test_discovery_skips_embedding_only_downloads(monkeypatch, fake_tags) -> None:
    """Live incident 2026-07-25 #2: the smallest download was bge-m3, an
    embedding-only model that 400s on chat. The default gates on the DECLARED
    /api/show capability (never the name, AP-21) and takes the next-smallest
    chat-capable download."""
    _no_override(monkeypatch)
    fake_tags.payload = {
        "models": [
            {"name": "bge-m3:latest", "size": 1_200_000_000},
            {"name": "qwen2.5:7b", "size": 4_700_000_000},
        ]
    }
    fake_tags.show_caps = {"bge-m3:latest": ["embedding"]}
    assert await OllamaBrain()._resolve_model() == "qwen2.5:7b"


async def test_tool_turns_require_a_tools_capable_download(monkeypatch, fake_tags) -> None:
    """Live incident 2026-07-25 #3: the smallest chat-capable download had no
    ``tools`` capability and 400ed on the first tool turn. A tool-bearing
    request gates on the declared ``tools`` capability; plain chat may still
    run the smaller model."""
    _no_override(monkeypatch)
    fake_tags.payload = {
        "models": [
            {"name": "deepseek-llm:latest", "size": 1_000},
            {"name": "qwen2.5:7b", "size": 2_000},
        ]
    }
    fake_tags.show_caps = {"deepseek-llm:latest": ["completion"]}
    brain = OllamaBrain()
    assert await brain._resolve_model() == "deepseek-llm:latest"
    assert await brain._resolve_model(need_tools=True) == "qwen2.5:7b"


async def test_embedding_only_server_gives_honest_error(monkeypatch, fake_tags) -> None:
    _no_override(monkeypatch)
    fake_tags.payload = {"models": [{"name": "bge-m3:latest", "size": 1}]}
    fake_tags.show_caps = {"bge-m3:latest": ["embedding"]}
    with pytest.raises(RuntimeError) as err:
        await OllamaBrain()._resolve_model()
    msg = str(err.value)
    assert "supports chat" in msg
    assert f"ollama pull {RECOMMENDED_PULL}" in msg


async def test_cloud_only_server_gives_honest_pull_hint(monkeypatch, fake_tags) -> None:
    _no_override(monkeypatch)
    fake_tags.payload = {"models": [{"name": "kimi-k2.5:cloud", "size": 1}]}
    with pytest.raises(RuntimeError) as err:
        await OllamaBrain()._resolve_model()
    msg = str(err.value)
    assert f"ollama pull {RECOMMENDED_PULL}" in msg
    assert "cloud references do not count" in msg


async def test_empty_server_gives_honest_pull_hint(monkeypatch, fake_tags) -> None:
    _no_override(monkeypatch)
    fake_tags.payload = {"models": []}
    with pytest.raises(RuntimeError) as err:
        await OllamaBrain()._resolve_model()
    assert f"ollama pull {RECOMMENDED_PULL}" in str(err.value)


async def test_unreachable_server_gives_honest_error(monkeypatch, fake_tags) -> None:
    _no_override(monkeypatch)
    fake_tags.fail = True
    with pytest.raises(RuntimeError) as err:
        await OllamaBrain()._resolve_model()
    msg = str(err.value)
    assert "not reachable" in msg
    assert "http://localhost:11434" in msg


# ── Vision: a MODEL property, never a server property ────────────────────
@pytest.fixture()
def catalog(monkeypatch):
    """Stub the cached model catalog the synchronous vision probe reads."""
    import jarvis.brain.model_catalog as mc

    state = {"caps": {}, "has_data": False, "vision_pick": None}

    monkeypatch.setattr(
        mc,
        "model_capabilities",
        lambda provider, model: state["caps"].get(model, {"vision": None, "tools": None}),
    )
    monkeypatch.setattr(mc, "provider_has_modality_data", lambda provider: state["has_data"])
    monkeypatch.setattr(mc, "pick_vision_model", lambda provider: state["vision_pick"])
    return state


def test_pinned_model_without_vision_declares_itself_blind(catalog) -> None:
    """The whole point: a text-only pull must not advertise sight, or
    ``resolve_vision_brain`` hands it a screenshot and it answers about the
    words around a picture it never saw."""
    catalog["caps"] = {"qwen3.5:9b": {"vision": False, "tools": True}}
    assert OllamaBrain(model="qwen3.5:9b").supports_vision is False


def test_pinned_multimodal_model_declares_sight(catalog) -> None:
    catalog["caps"] = {"qwen3-vl:8b": {"vision": True, "tools": True}}
    assert OllamaBrain(model="qwen3-vl:8b").supports_vision is True


def test_unknown_capability_stays_capable(catalog) -> None:
    """Fail-open on unknown: an uncached model keeps the pre-existing answer,
    and the image path then negotiates a real vision model."""
    assert OllamaBrain(model="something-uncached").supports_vision is True


def test_server_without_any_vision_download_is_blind(catalog) -> None:
    """No pinned model + a catalog that HAS the data and lists no multimodal
    download = an informed no, so the vision chain crosses to a provider that
    can actually see (AP-22)."""
    catalog["has_data"] = True
    catalog["vision_pick"] = None
    assert OllamaBrain().supports_vision is False


def test_server_with_a_vision_download_is_sighted(catalog) -> None:
    catalog["has_data"] = True
    catalog["vision_pick"] = "qwen3-vl:8b"
    assert OllamaBrain().supports_vision is True


def test_no_catalog_data_stays_capable(catalog) -> None:
    catalog["has_data"] = False
    assert OllamaBrain().supports_vision is True


async def test_image_turn_picks_a_vision_capable_download(monkeypatch, fake_tags) -> None:
    """An image turn skips the smaller text-only download and takes the
    multimodal one — while plain chat still runs the small model."""
    _no_override(monkeypatch)
    fake_tags.payload = {
        "models": [
            {"name": "qwen3.5:4b", "size": 1_000},
            {"name": "qwen3-vl:8b", "size": 5_000},
        ]
    }
    fake_tags.show_caps = {
        "qwen3.5:4b": ["completion", "tools"],
        "qwen3-vl:8b": ["completion", "tools", "vision"],
    }
    brain = OllamaBrain()
    assert await brain._resolve_model() == "qwen3.5:4b"
    assert await brain._resolve_model(need_vision=True) == "qwen3-vl:8b"


async def test_image_turn_without_a_vision_download_errors_honestly(monkeypatch, fake_tags) -> None:
    _no_override(monkeypatch)
    fake_tags.payload = {"models": [{"name": "qwen3.5:4b", "size": 1_000}]}
    fake_tags.show_caps = {"qwen3.5:4b": ["completion", "tools"]}
    brain = OllamaBrain()
    with pytest.raises(RuntimeError) as err:
        await brain._resolve_model(need_vision=True)
    assert f"ollama pull {RECOMMENDED_VISION_PULL}" in str(err.value)
    # Auto-discovery may see a new download on the next turn. This failed
    # attempt must not permanently disable the retained provider instance.
    assert brain.supports_vision is True


async def test_unprobeable_model_is_never_used_for_an_image_turn(monkeypatch, fake_tags) -> None:
    """Vision is the ONE requirement that fails CLOSED: a model whose
    ``/api/show`` probe does not answer may back a chat turn, never an image
    turn — a blind answer is indistinguishable from a sighted one."""
    _no_override(monkeypatch)
    fake_tags.payload = {"models": [{"name": "mystery:latest", "size": 1_000}]}

    async def _show_unavailable(self, url: str, json: dict[str, Any] | None = None) -> None:
        raise httpx.ConnectError("show unavailable")

    monkeypatch.setattr(fake_tags, "post", _show_unavailable)
    brain = OllamaBrain()
    assert await brain._resolve_model() == "mystery:latest"
    with pytest.raises(RuntimeError):
        await brain._resolve_model(need_vision=True)


async def test_complete_refuses_an_image_on_a_pinned_blind_model(
    monkeypatch, fake_tags, catalog
) -> None:
    """A pinned model is the user's own choice, so it is not silently swapped —
    but the turn errors instead of describing a screenshot it cannot see."""
    import openai

    from jarvis.core.protocols import BrainMessage, BrainRequest, ImageBlock

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    _no_override(monkeypatch)
    catalog["caps"] = {"qwen3.5:9b": {"vision": False, "tools": True}}
    fake_tags.show_caps = {"qwen3.5:9b": ["completion", "tools"]}
    req = BrainRequest(
        messages=(
            BrainMessage(
                role="user",
                content="What is on my screen?",
                images=(ImageBlock(mime="image/png", data_b64="aGk="),),
            ),
        )
    )
    brain = OllamaBrain(model="qwen3.5:9b")
    with pytest.raises(RuntimeError) as err:
        async for _ in brain.complete(req):
            pass
    msg = str(err.value)
    assert "cannot see images" in msg
    assert RECOMMENDED_VISION_PULL in msg


# ── Protocol surface ─────────────────────────────────────────────────────
def test_capability_flags_and_cost(catalog) -> None:
    brain = OllamaBrain(model="x")
    assert brain.supports_tools is True
    assert brain.can_call_tools() is True
    # Unknown capability → capable (the image path does the real gating).
    assert brain.supports_vision is True
    # Local inference bills nothing — the cost meter must see 0.
    req_like = type("R", (), {"messages": (), "max_tokens": 100})()
    assert brain.estimate_cost(req_like) == 0.0


def test_tags_payload_shape_matches_documented_api() -> None:
    """Pin the parsed shape: /api/tags returns {"models": [{"name": ...}]}.

    If Ollama ever changes this, the discovery test data here must be updated
    together with ``_resolve_model`` — this test documents the contract.
    """
    payload = json.loads('{"models": [{"name": "qwen3.5:9b", "size": 1}]}')
    names = [m.get("name") for m in payload["models"]]
    assert names == ["qwen3.5:9b"]


# ── Per-model options (profile alias, warm ping, request overrides) ──────
#: What the stubbed sizing answers in the ``wired`` tests.
AUTOMATIC = 16_384


class _FakeStreamer:
    """Records what ``complete`` hands to the shared streamer."""

    calls: list[tuple[str, Any]] = []

    @classmethod
    async def stream(cls, client: Any, model: str, req: Any, **kwargs: Any):
        cls.calls.append((model, req))
        from jarvis.core.protocols import BrainDelta

        yield BrainDelta(content="ok", finish_reason="stop")


class _FakeProfiles:
    """Stands in for ``ollama_profiles.ensure_profile`` / ``warm``."""

    ensured: list[tuple[str, str, Any]] = []
    warmed: list[tuple[str, str, Any]] = []
    fail: bool = False

    @classmethod
    async def ensure_profile(cls, root: str, base: str, opts: Any, **kwargs: Any) -> str:
        if cls.fail:
            raise RuntimeError("server said no")
        cls.ensured.append((root, base, opts))
        return f"{base.replace(':', '-')}-jarvis-deadbeef"

    @classmethod
    async def warm(cls, root: str, model: str, keep_alive: Any, **kwargs: Any) -> bool:
        cls.warmed.append((root, model, keep_alive))
        return True


@pytest.fixture()
def wired(monkeypatch):
    import openai

    from jarvis.brain import ollama_profiles
    from jarvis.plugins.brain import ollama as plugin

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(plugin, "stream_complete", _FakeStreamer.stream)
    monkeypatch.setattr(ollama_profiles, "ensure_profile", _FakeProfiles.ensure_profile)
    monkeypatch.setattr(ollama_profiles, "warm", _FakeProfiles.warm)

    async def _sized(self: OllamaBrain, model: str) -> int:
        return AUTOMATIC

    async def _unreported(self: OllamaBrain, *args: Any) -> None:
        return None

    # The sizing and the /api/ps check have their own tests below; here they
    # must not reach a real server on the machine running the suite.
    monkeypatch.setattr(OllamaBrain, "_automatic_context", _sized)
    monkeypatch.setattr(OllamaBrain, "_verify_running_context", _unreported)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    _FakeStreamer.calls = []
    _FakeProfiles.ensured = []
    _FakeProfiles.warmed = []
    _FakeProfiles.fail = False
    return _FakeProfiles


def _config_with_options(monkeypatch, models: dict[str, dict[str, Any]]) -> None:
    conf = JarvisConfig(brain=BrainConfig(providers={"ollama": BrainProviderConfig(models=models)}))
    install_provider_config(monkeypatch, conf)


def _req(**kwargs: Any):
    from jarvis.core.protocols import BrainMessage, BrainRequest

    return BrainRequest(messages=(BrainMessage(role="user", content="hi"),), **kwargs)


async def _run(brain: OllamaBrain, req: Any) -> None:
    async for _ in brain.complete(req):
        pass


async def test_no_options_still_get_an_explicit_context(monkeypatch, wired) -> None:
    """Without a setting the server default applies, which is small and
    shortens a longer prompt without an error. So a window is always sent."""
    _config_with_options(monkeypatch, {})
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    model, req = _FakeStreamer.calls[0]
    assert model == "qwen3.5-9b-jarvis-deadbeef"
    assert [(b, o.num_ctx) for _, b, o in wired.ensured] == [("qwen3.5:9b", AUTOMATIC)]
    assert req.temperature == 0.7 and req.reasoning_effort is None
    assert wired.warmed == []
    assert brain.context_window == AUTOMATIC


def test_a_fresh_brain_budgets_for_the_floor_not_the_class_figure(monkeypatch) -> None:
    """Tools are fitted before the first call. Until the window is sized the
    budget is the floor every automatic window starts from, so the first turn
    can never be planned larger than what the server is then asked to run."""
    from jarvis.brain.ollama_profiles import AUTOMATIC_CONTEXT_FLOOR

    _config_with_options(monkeypatch, {})
    assert OllamaBrain(model="qwen3.5:9b").context_window == AUTOMATIC_CONTEXT_FLOOR
    assert OllamaBrain().context_window == AUTOMATIC_CONTEXT_FLOOR


async def test_bakeable_options_stream_through_the_profile_alias(monkeypatch, wired) -> None:
    _config_with_options(
        monkeypatch,
        {"qwen3.5:9b": {"num_ctx": 16384, "num_gpu": -1, "keep_alive": "30m", "think": False}},
    )
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    model, req = _FakeStreamer.calls[0]
    assert model == "qwen3.5-9b-jarvis-deadbeef"
    assert [(b, o.num_ctx) for _, b, o in wired.ensured] == [("qwen3.5:9b", 16384)]
    # The warm ping targets the alias (that is what the turn will load).
    assert wired.warmed == [(DEFAULT_SERVER_ROOT, "qwen3.5-9b-jarvis-deadbeef", "30m")]
    assert brain.context_window == 16384
    assert req.reasoning_effort == "none"


async def test_request_only_options_ride_the_request(monkeypatch, wired) -> None:
    _config_with_options(monkeypatch, {"qwen3.5:9b": {"temperature": 0.1, "num_predict": 300}})
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    model, req = _FakeStreamer.calls[0]
    # The only baked knob is the automatic context; the knobs set on the
    # model card still ride the request.
    assert model == "qwen3.5-9b-jarvis-deadbeef"
    assert [o.num_ctx for _, _, o in wired.ensured] == [AUTOMATIC]
    assert wired.warmed == []
    assert req.temperature == 0.1 and req.max_tokens == 300


async def test_a_caller_that_chose_its_own_knob_keeps_it(monkeypatch, wired) -> None:
    """A deterministic tool step's temperature=0 / reasoning "none" wins over the profile."""
    _config_with_options(monkeypatch, {"qwen3.5:9b": {"temperature": 0.9, "think": "high"}})
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req(temperature=0.0, reasoning_effort="none"))
    _, req = _FakeStreamer.calls[0]
    assert req.temperature == 0.0 and req.reasoning_effort == "none"


async def test_profile_failure_degrades_to_the_base_model(monkeypatch, wired) -> None:
    _config_with_options(monkeypatch, {"qwen3.5:9b": {"num_ctx": 8192}})
    wired.fail = True
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    model, _ = _FakeStreamer.calls[0]
    assert model == "qwen3.5:9b"
    call = await brain._prepare_call("qwen3.5:9b", _req())
    # The plan stands, but nothing confirms the server runs it.
    assert (call.planned, call.confirmed) == (8192, False)


async def test_a_request_the_prepared_window_cannot_hold_is_never_sent(monkeypatch, wired) -> None:
    from jarvis.brain.local_context import LocalContextError

    _config_with_options(monkeypatch, {"qwen3.5:9b": {"num_ctx": 4096}})
    brain = OllamaBrain(model="qwen3.5:9b")
    with pytest.raises(LocalContextError) as err:
        await _run(brain, _req(system="s" * 80_000))
    assert _FakeStreamer.calls == []
    msg = str(err.value)
    assert "4096" in msg and "Local Models" in msg and "Tune" in msg


# ── Automatic sizing and the check against what the server runs ──────────
class _RoutedClient:
    """A fake ``httpx.AsyncClient`` that answers by path."""

    tags: dict[str, Any] | None = {}
    show: dict[str, Any] = {}
    ps: dict[str, Any] | None = {}
    seen: list[str] = []

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _RoutedClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str) -> _FakeResponse:
        _RoutedClient.seen.append(url)
        if url.endswith("/api/ps"):
            if _RoutedClient.ps is None:
                raise httpx.ConnectError("connection refused")
            return _FakeResponse(_RoutedClient.ps)
        if _RoutedClient.tags is None:
            raise httpx.ConnectError("connection refused")
        return _FakeResponse(_RoutedClient.tags)

    async def post(self, url: str, json: dict[str, Any] | None = None) -> _FakeResponse:
        return _FakeResponse(_RoutedClient.show)


@pytest.fixture()
def routed(monkeypatch):
    import openai

    from jarvis.brain import ollama_profiles, ollama_pull
    from jarvis.plugins.brain import ollama as plugin

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    monkeypatch.setattr(httpx, "AsyncClient", _RoutedClient)
    monkeypatch.setattr(plugin, "stream_complete", _FakeStreamer.stream)
    monkeypatch.setattr(ollama_profiles, "ensure_profile", _FakeProfiles.ensure_profile)
    monkeypatch.setattr(ollama_profiles, "warm", _FakeProfiles.warm)
    monkeypatch.setattr(ollama_pull, "accelerator_gb", lambda: (0.0, "none"))
    monkeypatch.setattr(ollama_pull, "total_memory_gb", lambda: 16.0)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    _config_with_options(monkeypatch, {})
    _FakeStreamer.calls = []
    _FakeProfiles.ensured = []
    _FakeProfiles.warmed = []
    _FakeProfiles.fail = False
    _RoutedClient.tags = {"models": [{"name": "qwen3.5:9b", "size": 6 * 1024**3}]}
    _RoutedClient.show = {
        "capabilities": ["completion", "tools"],
        "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 262_144},
    }
    _RoutedClient.ps = {"models": []}
    _RoutedClient.seen = []
    return _RoutedClient


async def test_sixteen_gb_of_ram_gets_the_floor_not_the_server_default(routed) -> None:
    """6 GB of weights on a 16 GB machine without a readable accelerator:
    8k is what fits comfortably, but the prompt of this app does not fit 8k."""
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    assert [o.num_ctx for _, _, o in _FakeProfiles.ensured] == [16_384]
    assert brain.context_window == 16_384


async def test_a_large_card_gets_the_ceiling_not_the_native_window(routed, monkeypatch) -> None:
    from jarvis.brain import ollama_pull

    monkeypatch.setattr(ollama_pull, "accelerator_gb", lambda: (24.0, "nvidia"))
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    # The whole cache is allocated up front: 262k is never the default.
    assert [o.num_ctx for _, _, o in _FakeProfiles.ensured] == [32_768]


async def test_a_small_native_window_caps_the_automatic_one(routed) -> None:
    routed.show = {
        "capabilities": ["completion", "tools"],
        "model_info": {"general.architecture": "old", "old.context_length": 8_192},
    }
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    assert [o.num_ctx for _, _, o in _FakeProfiles.ensured] == [8_192]


async def test_the_window_is_sized_once_per_model(routed) -> None:
    """A changed num_ctx makes Ollama reload the weights."""
    await _run(OllamaBrain(model="qwen3.5:9b"), _req())
    tag_calls = sum(1 for url in routed.seen if url.endswith("/api/tags"))
    await _run(OllamaBrain(model="qwen3.5:9b"), _req())
    assert sum(1 for url in routed.seen if url.endswith("/api/tags")) == tag_calls


async def test_a_server_that_runs_a_smaller_window_is_believed(routed) -> None:
    """The profile could not be created, so the base model loads with the
    server default. /api/ps says which, and that becomes the budget."""
    _FakeProfiles.fail = True
    routed.ps = {"models": [{"name": "qwen3.5:9b", "context_length": 4_096}]}
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    assert _FakeStreamer.calls[0][0] == "qwen3.5:9b"
    assert brain.context_window == 4_096
    # The next brain for this model plans with the real figure straight away.
    assert OllamaBrain(model="qwen3.5:9b").context_window == 4_096


async def test_a_prompt_the_server_cut_short_never_becomes_an_answer(routed) -> None:
    from jarvis.brain.local_context import LocalContextError

    _FakeProfiles.fail = True
    routed.ps = {"models": [{"name": "qwen3.5:9b", "context_length": 4_096}]}
    brain = OllamaBrain(model="qwen3.5:9b")
    handed_on: list[Any] = []
    with pytest.raises(LocalContextError) as err:
        async for delta in brain.complete(_req(system="s" * 80_000)):
            handed_on.append(delta)
    # Refused before the first token reached the caller.
    assert handed_on == []
    assert err.value.truncated is True
    assert "cut this request short" in str(err.value)


async def test_an_unanswered_check_leaves_the_plan_standing(routed) -> None:
    routed.ps = None
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    assert brain.context_window == 16_384


async def test_a_server_refusal_names_the_setting(routed, monkeypatch) -> None:
    from jarvis.brain.local_context import LocalContextError
    from jarvis.plugins.brain import ollama as plugin

    async def refusing(client: Any, model: str, req: Any, **kwargs: Any):
        raise RuntimeError("Error code: 400 - the request exceeds the available context size")
        yield  # pragma: no cover

    monkeypatch.setattr(plugin, "stream_complete", refusing)
    with pytest.raises(LocalContextError) as err:
        await _run(OllamaBrain(model="qwen3.5:9b"), _req())
    assert "Local Models" in str(err.value)


async def test_discovered_model_is_tuned_like_a_pinned_one(monkeypatch, wired, fake_tags) -> None:
    _config_with_options(monkeypatch, {"qwen3.5:4b": {"num_ctx": 4096}})
    fake_tags.payload = {"models": [{"name": "qwen3.5:4b", "size": 1_000}]}
    brain = OllamaBrain()
    await _run(brain, _req())
    model, _ = _FakeStreamer.calls[0]
    assert model == "qwen3.5-4b-jarvis-deadbeef"


async def test_the_smaller_window_is_enforced_on_every_later_turn(routed) -> None:
    """The first turn learned that the server runs 4,096. A later, larger
    request must be held to that too, not only the turn that asked."""
    from jarvis.brain.local_context import LocalContextError

    _FakeProfiles.fail = True
    routed.ps = {"models": [{"name": "qwen3.5:9b", "context_length": 4_096}]}
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    assert len(_FakeStreamer.calls) == 1
    with pytest.raises(LocalContextError) as err:
        await _run(brain, _req(system="s" * 80_000))
    # Refused before sending this time: the window is already known.
    assert len(_FakeStreamer.calls) == 1
    assert "was not sent" in str(err.value)
    assert brain.context_window == 4_096


async def test_a_model_that_declares_a_larger_window_is_not_shrunk(routed) -> None:
    """A Modelfile that sets num_ctx 65536 works today. The automatic window
    must not put a smaller one in front of it."""
    routed.show = {
        "capabilities": ["completion", "tools"],
        "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 262_144},
        "parameters": "temperature 0.6\nnum_ctx                        65536\nstop <|im_end|>",
    }
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    assert _FakeProfiles.ensured == []
    assert _FakeStreamer.calls[0][0] == "qwen3.5:9b"
    assert brain.context_window == 65_536


async def test_a_model_that_declares_a_tiny_window_still_gets_the_floor(routed) -> None:
    routed.show = {
        "capabilities": ["completion", "tools"],
        "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 262_144},
        "parameters": "num_ctx 2048",
    }
    await _run(OllamaBrain(model="qwen3.5:9b"), _req())
    assert [o.num_ctx for _, _, o in _FakeProfiles.ensured] == [16_384]


async def test_a_server_still_starting_does_not_fix_the_size_for_good(routed, monkeypatch) -> None:
    from jarvis.brain import ollama_pull

    monkeypatch.setattr(ollama_pull, "accelerator_gb", lambda: (24.0, "nvidia"))
    routed.tags = None  # /api/tags does not answer yet
    brain = OllamaBrain(model="qwen3.5:9b")
    assert await brain._automatic_context("qwen3.5:9b") == 16_384
    routed.tags = {"models": [{"name": "qwen3.5:9b", "size": 6 * 1024**3}]}
    assert await brain._automatic_context("qwen3.5:9b") == 32_768


async def test_a_remote_server_is_not_sized_from_this_machine(routed, monkeypatch) -> None:
    from jarvis.brain import ollama_pull

    monkeypatch.setattr(ollama_pull, "accelerator_gb", lambda: (24.0, "nvidia"))
    _override("http://otherbox:11434", monkeypatch)
    brain = OllamaBrain(model="qwen3.5:9b")
    # 24 GB here says nothing about the machine that holds the weights.
    assert await brain._automatic_context("qwen3.5:9b") == 16_384


async def test_a_refused_profile_is_not_requested_again_on_every_turn(routed, monkeypatch) -> None:
    from jarvis.brain import ollama_profiles

    attempts: list[str] = []

    async def refusing(root: str, base: str, opts: Any, **kwargs: Any) -> str:
        attempts.append(base)
        raise RuntimeError("server said no")

    monkeypatch.setattr(ollama_profiles, "ensure_profile", refusing)
    brain = OllamaBrain(model="qwen3.5:9b")
    await _run(brain, _req())
    await _run(brain, _req())
    assert attempts == ["qwen3.5:9b"]
    assert [m for m, _ in _FakeStreamer.calls] == ["qwen3.5:9b", "qwen3.5:9b"]


async def test_the_window_is_settled_before_the_first_turn_is_budgeted(routed, monkeypatch) -> None:
    from jarvis.brain import ollama_pull

    monkeypatch.setattr(ollama_pull, "accelerator_gb", lambda: (24.0, "nvidia"))
    brain = OllamaBrain(model="qwen3.5:9b")
    assert brain.context_window == 16_384
    await brain.prepare_context_window()
    assert brain.context_window == 32_768
    assert _FakeStreamer.calls == []
    # The next brain for this model starts from the sized window.
    assert OllamaBrain(model="qwen3.5:9b").context_window == 32_768


async def test_concurrent_calls_do_not_share_their_plan(routed) -> None:
    """One brain serves several calls. What a call was prepared with is
    returned to it, never parked on the instance for the next one to overwrite."""
    brain = OllamaBrain(model="qwen3.5:9b")
    first = await brain._prepare_call("qwen3.5:9b", _req())
    brain.set_context_window(65_536)
    second = await brain._prepare_call("qwen3.5:9b", _req())
    assert (first.planned, second.planned) == (16_384, 65_536)
