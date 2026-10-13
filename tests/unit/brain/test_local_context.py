"""Local servers must never shorten a prompt without anyone noticing.

Reported from testing: a 9B model never called the save tool and a larger one
only ever listed. Local servers run a small default context, and with the
system prompt plus every tool schema the start of the prompt was cut off with
no error, so the model never saw some of its tools.

The server is a fake behind ``httpx.MockTransport`` (a real httpx feature, no
``unittest.mock``).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from jarvis.brain import local_context
from jarvis.brain.local_context import (
    LOCAL_CONTEXT_MARKER,
    LocalContextError,
    certain_tokens,
    ensure_fits,
    fix_hint,
    is_overflow_refusal,
    known_window,
    known_window_for_model,
    probe_server_window,
    recommended_window,
    remember_window,
    reported_prompt_tokens,
    truncation_suspected,
)
from jarvis.core.protocols import BrainMessage, BrainRequest

ROOT = "http://fake:1234"


@pytest.fixture(autouse=True)
def _clean_registry():
    local_context.reset_registry()
    yield
    local_context.reset_registry()


def _req(chars: int, *, tools: int = 0) -> BrainRequest:
    return BrainRequest(
        messages=(BrainMessage(role="user", content="x" * chars),),
        tools=tuple({"name": f"t{i}", "description": "d" * 80} for i in range(tools)),
        system="s" * 400,
    )


def _server(routes: dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = routes.get(request.url.path)
        if payload is None:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


# ── Refusing before sending ──────────────────────────────────────────────


def test_a_request_that_fits_is_left_alone() -> None:
    ensure_fits(_req(4_000), 8_192, provider="local-openai", model="m", kind="lm-studio")


def test_an_unknown_window_never_refuses() -> None:
    ensure_fits(_req(4_000_000), 0, provider="local-openai", model="m", kind="unknown")


def test_an_oversized_request_names_the_size_and_the_setting() -> None:
    req = _req(80_000)
    with pytest.raises(LocalContextError) as err:
        ensure_fits(req, 4_096, provider="local-openai", model="qwen", kind="lm-studio")
    msg = str(err.value)
    assert LOCAL_CONTEXT_MARKER in msg.lower()
    assert "4096" in msg
    assert f"{certain_tokens(req)}" in msg
    # The remedy is concrete: which program, which setting, how large.
    assert "LM Studio" in msg and "Context Length" in msg
    assert f"{recommended_window(certain_tokens(req))}" in msg
    assert "was not sent" in msg
    assert err.value.window_tokens == 4_096


def test_the_recommendation_leaves_room_for_an_answer() -> None:
    assert recommended_window(6_000) == 8_192
    # 7,000 tokens fit 8,192 only without headroom for the reply.
    assert recommended_window(7_000) == 16_384
    assert recommended_window(10_000_000) == 262_144


@pytest.mark.parametrize(
    ("kind", "needle"),
    [
        ("ollama", "Local Models"),
        ("lm-studio", "Context Length"),
        ("llama.cpp", "--ctx-size 16384"),
        ("vllm", "--max-model-len 16384"),
        ("tgi", "--max-total-tokens 16384"),
        ("something-else", "LM Studio"),
    ],
)
def test_every_server_kind_gets_its_own_instruction(kind: str, needle: str) -> None:
    assert needle in fix_hint(kind, 10_000)


def test_server_refusals_are_recognised() -> None:
    assert is_overflow_refusal(
        "Error code: 400 - the request exceeds the available context size"
    )
    assert is_overflow_refusal("This model's maximum context length is 4096 tokens")
    assert not is_overflow_refusal("Connection refused")


# ── Judging a server that states nothing ─────────────────────────────────


def test_cached_tokens_count_towards_what_the_server_read() -> None:
    assert reported_prompt_tokens({"input_tokens": 100, "cache_hit_tokens": 900}) == 1_000
    assert reported_prompt_tokens({}) is None
    assert reported_prompt_tokens(None) is None


def test_a_prompt_read_in_full_is_not_suspected() -> None:
    req = _req(60_000)  # about 20,000 by the upper estimate
    assert not truncation_suspected(req, 15_000)


def test_a_prompt_cut_to_a_small_window_is_suspected() -> None:
    req = _req(60_000)
    assert truncation_suspected(req, 4_096)


def test_a_cache_hit_reporting_only_new_tokens_is_not_suspected() -> None:
    """Some servers report the tokens they newly evaluated. A handful of
    tokens after a cache hit is not a truncated prompt."""
    req = _req(60_000)
    assert not truncation_suspected(req, 120)


def test_small_prompts_are_never_judged() -> None:
    assert not truncation_suspected(_req(3_000), 400)


# ── Asking the server ────────────────────────────────────────────────────


async def test_lm_studio_reports_the_loaded_context() -> None:
    transport = _server(
        {
            "/v1/models": {"data": [{"id": "qwen"}]},
            "/api/v0/models": {
                "data": [
                    {
                        "id": "qwen",
                        "state": "loaded",
                        "loaded_context_length": 4_096,
                        "max_context_length": 131_072,
                    }
                ]
            },
        }
    )
    window = await probe_server_window(ROOT, "qwen", transport=transport)
    assert window is not None
    # The LOADED figure, never the maximum the model could be given.
    assert (window.tokens, window.kind) == (4_096, "lm-studio")
    assert known_window("local-openai", ROOT, "qwen") == (4_096, "server", "lm-studio")
    assert known_window_for_model("local-openai", "qwen") == 4_096


async def test_lm_studio_model_not_loaded_yet_is_unknown() -> None:
    transport = _server(
        {
            "/api/v0/models": {
                "data": [{"id": "qwen", "state": "not-loaded", "max_context_length": 131_072}]
            }
        }
    )
    assert await probe_server_window(ROOT, "qwen", transport=transport) is None


async def test_llama_cpp_reports_the_slot_context() -> None:
    transport = _server({"/props": {"default_generation_settings": {"n_ctx": 8_192}}})
    window = await probe_server_window(ROOT, "any", transport=transport)
    assert window is not None and (window.tokens, window.kind) == (8_192, "llama.cpp")


async def test_vllm_reports_max_model_len() -> None:
    transport = _server({"/v1/models": {"data": [{"id": "qwen", "max_model_len": 32_768}]}})
    window = await probe_server_window(ROOT, "qwen", transport=transport)
    assert window is not None and (window.tokens, window.kind) == (32_768, "vllm")


async def test_a_server_that_says_nothing_is_unknown_and_never_raises() -> None:
    assert await probe_server_window(ROOT, "qwen", transport=_server({})) is None

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert await probe_server_window(ROOT, "qwen", transport=httpx.MockTransport(boom)) is None


async def test_the_answer_is_cached_and_a_fresh_ask_goes_out_again() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/props":
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 4_096}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    await probe_server_window(ROOT, "m", transport=transport)
    first = len(calls)
    await probe_server_window(ROOT, "m", transport=transport)
    assert len(calls) == first
    # After a reload with a larger context the person asks again right away.
    await probe_server_window(ROOT, "m", transport=transport, fresh=True)
    assert len(calls) > first


async def test_a_silent_server_is_not_asked_on_every_request() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    # Asked while the model is demonstrably loaded: this server does not tell.
    await probe_server_window(ROOT, "m", transport=transport, fresh=True)
    asked = len(calls)
    await probe_server_window(ROOT, "m", transport=transport)
    assert len(calls) == asked


def test_the_newest_record_wins_across_server_roots() -> None:
    remember_window("local-openai", "http://a:1", "m", 4_096, source="server")
    remember_window("local-openai", "http://b:2", "m", 16_384, source="server")
    assert known_window_for_model("local-openai", "m") == 16_384
    assert known_window_for_model("ollama", "m") is None


def test_a_suspected_window_lapses_but_a_stated_one_stays(monkeypatch) -> None:
    """A window inferred from usage is a suspicion: it must not tighten the
    budget forever on the strength of one odd response."""
    remember_window("local-openai", ROOT, "guessed", 4_096, source="observed")
    remember_window("local-openai", ROOT, "stated", 4_096, source="server")
    later = local_context.time.monotonic() + local_context._OBSERVED_TTL_S + 1
    monkeypatch.setattr(local_context.time, "monotonic", lambda: later)
    assert known_window_for_model("local-openai", "guessed") is None
    assert known_window("local-openai", ROOT, "guessed") is None
    assert known_window_for_model("local-openai", "stated") == 4_096


def test_one_odd_response_changes_nothing_and_two_tighten() -> None:
    from jarvis.brain.local_context import judge_reported_prompt

    req = _req(60_000)
    assert judge_reported_prompt("local-openai", ROOT, "m", req, 4_096) == ("keep", 0)
    assert known_window("local-openai", ROOT, "m") is None
    assert judge_reported_prompt("local-openai", ROOT, "m", req, 4_096) == ("tighten", 4_096)
    assert known_window("local-openai", ROOT, "m") == (4_096, "observed", "unknown")


def test_an_honest_response_in_between_resets_the_count() -> None:
    from jarvis.brain.local_context import judge_reported_prompt

    req = _req(60_000)
    judge_reported_prompt("local-openai", ROOT, "m", req, 4_096)
    assert judge_reported_prompt("local-openai", ROOT, "m", req, 15_000) == ("keep", 0)
    assert judge_reported_prompt("local-openai", ROOT, "m", req, 4_096) == ("keep", 0)


def test_a_response_above_the_suspected_window_restores_the_budget() -> None:
    from jarvis.brain.local_context import judge_reported_prompt

    req = _req(60_000)
    judge_reported_prompt("local-openai", ROOT, "m", req, 4_096)
    judge_reported_prompt("local-openai", ROOT, "m", req, 4_096)
    assert judge_reported_prompt("local-openai", ROOT, "m", req, 12_000) == ("restore", 0)
    assert known_window("local-openai", ROOT, "m") is None


def test_a_model_that_cannot_hold_the_request_is_told_to_change_model() -> None:
    hint = fix_hint("ollama", 10_000, ceiling=8_192)
    assert "8192" in hint and "larger context window" in hint
    assert "16384" not in hint


def test_an_encoded_image_in_a_block_is_not_counted_as_text() -> None:
    """A screenshot rides in a content block as base64. Counted as prose it
    would refuse every image turn."""
    blob = "A" * 400_000
    with_image = BrainRequest(
        messages=(
            BrainMessage(
                role="user",
                content=[
                    {"type": "text", "text": "what is this"},
                    {"type": "image", "source": {"type": "base64", "data": blob}},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + blob}},
                ],
            ),
        ),
    )
    assert certain_tokens(with_image) < 50
    ensure_fits(with_image, 4_096, provider="ollama", model="m", kind="ollama")


def test_a_refusal_never_claims_a_prompt_larger_than_the_window() -> None:
    from jarvis.brain.local_context import refusal_error

    err = refusal_error(
        _req(8_000), provider="local-openai", model="qwen", kind="vllm", window_tokens=8_192
    )
    msg = str(err)
    assert LOCAL_CONTEXT_MARKER in msg.lower()
    assert "refused this request as too large" in msg
    # The next window up from the one that was too small, not the same one.
    assert "--max-model-len 16384" in msg


def test_a_brain_without_a_model_gets_no_other_models_window() -> None:
    remember_window("ollama", ROOT, "big", 65_536, source="server")
    assert known_window_for_model("ollama", "") is None


async def test_a_silent_server_is_left_alone_even_for_a_fresh_ask() -> None:
    """Four status requests before the first token of every turn would be a
    standing delay for a server that will never answer them."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    await probe_server_window(ROOT, "m", transport=transport, fresh=True)
    asked = len(calls)
    assert asked > 0
    await probe_server_window(ROOT, "m", transport=transport, fresh=True)
    assert len(calls) == asked


async def test_a_malformed_root_never_raises() -> None:
    assert await probe_server_window("not a url", "m") is None


@pytest.mark.parametrize("needed", [12_404, 18_401, 9_402, 20_429, 6_500, 65_536])
@pytest.mark.parametrize("window", [4_096, 8_192, 65_536])
@pytest.mark.parametrize("kind", ["ollama", "lm-studio", "llama.cpp", "vllm", "tgi", "unknown"])
def test_no_token_count_reads_as_an_http_status(needed: int, window: int, kind: str) -> None:
    """Classifiers across the app take a free-standing three-digit group for
    an HTTP status. Written "18,401 tokens", a too-small window was recorded as
    a rejected key, and "65,536" as an unreachable server."""
    from jarvis.brain.provider_test import ERROR, classify_provider_error

    for refused in (False, True):
        message = str(
            LocalContextError(
                provider="local-openai",
                model="qwen",
                needed_tokens=needed,
                window_tokens=window,
                how_to_fix=fix_hint(kind, needed, ceiling=None),
                refused=refused,
            )
        )
        assert classify_provider_error(message) == ERROR, message
    assert classify_provider_error(fix_hint(kind, needed, ceiling=window)) == ERROR
