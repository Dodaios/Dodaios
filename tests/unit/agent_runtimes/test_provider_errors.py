"""Provider refusals a retry cannot fix reach Hermes / OpenClaw as what they are.

Measured live 2026-10-07: an empty OpenAI balance answers 429, OpenRouter 402,
and a stopped local server times out. All of them used to read as "rate limited, try again in 30 s".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from dodaios.agent_runtimes import gateway, provider_errors
from dodaios.agent_runtimes.provider_errors import classify


class ProviderStatusError(Exception):
    """The shape the openai / anthropic SDKs raise: a status and a parsed body."""

    def __init__(self, status: int, body: Any = None, message: str = "Error") -> None:
        super().__init__(message)
        self.status_code = status
        self.body = body


class APITimeoutError(Exception):
    """Named like the SDKs' transport error; the name is the signal."""


def test_an_empty_openai_balance_is_billing_not_a_rate_limit() -> None:
    exc = ProviderStatusError(
        429,
        {"error": {"message": "You have no credits remaining.", "code": "insufficient_quota"}},
    )
    refusal = classify("openai", exc)
    assert refusal is not None
    assert (refusal.status, refusal.code) == (402, "billing")
    assert "OpenAI" in refusal.message
    assert "no credits remaining" not in refusal.message  # never the provider's body


def test_payment_required_is_billing() -> None:
    refusal = classify("openrouter", ProviderStatusError(402, {"error": {"code": 402}}))
    assert refusal is not None and refusal.status == 402


def test_a_zero_quota_is_billing() -> None:
    body = {"error": {"message": "Quota exceeded for metric: x, limit: 0, model: m"}}
    refusal = classify("gemini", ProviderStatusError(429, body))
    assert refusal is not None and refusal.code == "billing"


def test_an_ordinary_rate_limit_stays_unclassified() -> None:
    body = {"error": {"type": "rate_limit_error", "message": "Error"}}
    assert classify("claude-api", ProviderStatusError(429, body)) is None
    assert classify("openai", ProviderStatusError(500)) is None


class ConnectTimeout(Exception):
    """httpx's connect timeout: nothing accepted the connection."""


class ReadTimeout(Exception):
    """httpx's read timeout: the server was reached and went quiet."""


def _timeout(cause: Exception) -> APITimeoutError:
    """An SDK timeout wrapping the transport error, as openai/anthropic raise it."""
    try:
        raise APITimeoutError("Request timed out.") from cause
    except APITimeoutError as exc:
        return exc


def test_a_stopped_local_server_is_unreachable() -> None:
    # Windows refuses a closed localhost port only after the connect timeout.
    refusal = classify("local-openai", _timeout(ConnectTimeout("connect timed out")))
    assert refusal is not None
    assert (refusal.status, refusal.code) == (503, "provider_unreachable")


def test_a_wrapped_transport_error_is_found_in_the_chain() -> None:
    try:
        try:
            raise ConnectTimeout("timed out")
        except ConnectTimeout as inner:
            raise RuntimeError("stream failed") from inner
    except RuntimeError as outer:
        refusal = classify("ollama", outer)
    assert refusal is not None and refusal.code == "provider_unreachable"


def test_a_model_that_took_too_long_is_a_timeout_not_unreachable() -> None:
    refusal = classify("openai", _timeout(ReadTimeout("read timed out")), "gpt-5.5")
    assert refusal is not None
    assert (refusal.status, refusal.code) == (504, "timeout")
    assert "took too long" in refusal.message and "start it" not in refusal.message


_OVERFLOWS = [
    # OpenAI / OpenRouter
    ProviderStatusError(
        400,
        {"error": {"code": "context_length_exceeded", "type": "invalid_request_error"}},
        "This model's maximum context length is 400000 tokens.",
    ),
    # Anthropic
    ProviderStatusError(
        400,
        {"type": "error", "error": {"type": "invalid_request_error"}},
        "prompt is too long: 210000 tokens > 200000 maximum",
    ),
    # vLLM / local servers
    ProviderStatusError(400, None, "max_tokens is too large: this exceeds max_model_len"),
    # A stream error event without a status
    RuntimeError("Responses API stream failed: Your input exceeds the context window"),
]


@pytest.mark.parametrize("exc", _OVERFLOWS)
def test_a_context_overflow_tells_the_runtime_to_compress(exc: Exception) -> None:
    refusal = provider_errors.gateway_refusal("openai", exc, "gpt-5.5")
    assert (refusal.status, refusal.code) == (400, "context_length_exceeded")
    # Hermes and OpenClaw both match these words to compress and resend.
    assert "context length exceeded" in refusal.message.lower()
    assert not provider_errors.is_terminal(refusal.code)


def test_a_gemini_overflow_is_found_on_the_genai_error_shape() -> None:
    class ClientError(Exception):  # google-genai: ``code`` int, ``status`` name
        def __init__(self) -> None:
            super().__init__("400 INVALID_ARGUMENT. The input token count (1200000) exceeds "
                             "the maximum number of tokens allowed (1048576).")
            self.code = 400
            self.status = "INVALID_ARGUMENT"
            self.details = {"error": {"code": 400, "status": "INVALID_ARGUMENT"}}

    refusal = provider_errors.gateway_refusal("gemini", ClientError())
    assert refusal.code == "context_length_exceeded"


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (ProviderStatusError(404, {"error": {"code": "model_not_found"}}, "no such model"),
         404, "model_not_found"),
        (ProviderStatusError(400, None, "registry.ollama.ai/library/gemma:2b does not support "
                             "tools"), 400, "tools_unsupported"),
        (ProviderStatusError(400, {"error": {"code": "invalid_function_parameters"}},
                             "Invalid schema for function 'x'"), 400, "invalid_tool_schema"),
        (ProviderStatusError(400, None, "messages.3: unexpected role"), 400, "invalid_request"),
        (ProviderStatusError(529, None, "Overloaded"), 503, "provider_overloaded"),
        (ProviderStatusError(500, None, "boom"), 502, "provider_error"),
        (ProviderStatusError(401, None, "invalid x-api-key"), 401, "provider_auth"),
    ],
)
def test_every_provider_failure_gets_an_actionable_status(exc, status, code) -> None:
    refusal = provider_errors.gateway_refusal("ollama", exc, "gemma:2b")
    assert (refusal.status, refusal.code) == (status, code)
    assert "must never" not in refusal.message


def test_only_unrecoverable_failures_end_the_turn() -> None:
    terminal = {"billing", "provider_auth", "model_not_found", "invalid_tool_schema",
                "tools_unsupported", "rate_limited"}
    recoverable = {"context_length_exceeded", "timeout", "provider_overloaded",
                   "provider_error", "invalid_request", "provider_unreachable"}
    assert all(provider_errors.is_terminal(code) for code in terminal)
    assert not any(provider_errors.is_terminal(code) for code in recoverable)


def test_the_log_line_is_bounded_and_masks_credentials() -> None:
    exc = ProviderStatusError(
        401, {"error": {"code": "invalid_api_key"}},
        "Incorrect API key provided: sk-proj-abcdefghijklmnop. Bearer abcdefghijklmnopqrst "
        + "x" * 900,
    )
    line = provider_errors.describe(exc)
    assert "sk-proj-abcdefghijklmnop" not in line and "abcdefghijklmnopqrst" not in line
    assert "status=401" in line and "invalid_api_key" in line
    assert len(line) < 520


def test_the_gateway_reports_the_refusal_not_a_rate_limit() -> None:
    failure = gateway._failure(
        "openai", ProviderStatusError(429, {"error": {"code": "insufficient_quota"}})
    )
    assert (failure.status, failure.code) == (402, "billing")


async def test_a_non_streaming_subscription_answer_keeps_its_output(monkeypatch) -> None:
    """ChatGPT's backend streams the items and completes with an empty output."""
    item = {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}

    class Subscription:
        async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"type": "response.output_item.done", "item": item}
            yield {"type": "response.completed", "response": {"id": "r1", "output": []}}

    gateway.reset()
    monkeypatch.setattr(gateway, "_client", lambda account_id: Subscription())
    try:
        answer = await gateway.complete_response(
            gateway.Grant("agent-1", "openai-codex"),
            {"model": "gpt-5.6-sol", "input": [], "instructions": "", "tools": []},
        )
    finally:
        gateway.reset()
    assert answer["output"] == [item]


def test_a_system_message_moves_into_the_instructions() -> None:
    """ChatGPT's backend refuses system input items (OpenClaw sends one)."""
    args = gateway.request_args(
        {
            "model": "gpt-6.1-sol",
            "instructions": "",
            "input": [
                {"type": "message", "role": "system", "content": "You are Lumen."},
                {"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": "Hi"},
                ]},
            ],
        }
    )
    assert args["instructions"] == "You are Lumen."
    assert [item["role"] for item in args["input"]] == ["user"]


def test_floating_point_dust_never_adds_a_second_to_the_wait() -> None:
    """Windows CI said "Try again in 31 s" for a 30 s cooldown (30.000000001)."""
    assert gateway.whole_seconds(30.000000001) == 30
    assert gateway.whole_seconds(30.4) == 31
    assert gateway.whole_seconds(-1.0) == 0
