"""A spent plan allowance and a run that failed inside the runtime read as what they are.

Live 2026-10-27: a ChatGPT subscription at its usage limit showed "HTTP 429
(rate limit). Try again in 30 s", and an OpenClaw turn on Ollama whose
conversation outgrew the model's context window showed a grey "Finished
without an answer".
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat.task_recovery import blocks_automatic_recovery
from dodaios.agent_runtimes import gateway, provider_errors
from dodaios.agent_runtimes.openclaw import CONTEXT_FULL_REASON, run_failure
from dodaios.live import subscription_reasoning as sr
from dodaios.live.subscription_reasoning import SubscriptionReasoningError


class ProviderStatusError(Exception):
    def __init__(self, status: int, body: Any = None, message: str = "Error") -> None:
        super().__init__(message)
        self.status_code = status
        self.body = body


@pytest.fixture(autouse=True)
def _clean_cooldowns():
    with gateway._LOCK:
        gateway._COOLDOWNS.clear()
    yield
    with gateway._LOCK:
        gateway._COOLDOWNS.clear()


# ------------------------------------------------------------ classification


def test_the_subscription_usage_limit_is_a_usage_limit_not_a_rate_limit() -> None:
    exc = sr._failure(429, {"error": {"code": "usage_limit_reached"}})
    refusal = provider_errors.gateway_refusal("openai-codex", exc)
    assert (refusal.status, refusal.code) == (429, "usage_limit")
    assert "usage limit" in refusal.message and "allowance" in refusal.message
    assert "another connected model" in refusal.message
    assert not re.search(r"\d+ s\b", refusal.message)
    assert provider_errors.is_terminal("usage_limit")


def test_a_short_subscription_rate_limit_stays_a_rate_limit() -> None:
    exc = sr._failure(429, {"error": {"code": "rate_limit_exceeded"}})
    assert "usage limit" not in str(exc)
    assert provider_errors.gateway_refusal("openai-codex", exc).code == "rate_limited"


def test_a_short_subscription_rate_limit_never_reads_like_a_stored_usage_limit() -> None:
    # The chat reads a stored "openai-codex returned HTTP 429 ..." (written before
    # the two were told apart) as a spent allowance; new rate limits are named by label.
    limited = gateway._limited("openai-codex", 30.0)
    assert limited.code == "rate_limited"
    assert not str(limited).startswith("openai-codex returned HTTP 429")
    assert str(limited).startswith("The ChatGPT subscription returned HTTP 429 (rate limit).")
    assert "30 s" in str(limited)


def test_a_daily_quota_on_a_key_is_a_usage_limit() -> None:
    body = {
        "error": {
            "message": "Quota exceeded for metric: "
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        }
    }
    refusal = provider_errors.classify("gemini", ProviderStatusError(429, body))
    assert refusal is not None and refusal.code == "usage_limit"
    assert "GenerateRequests" not in refusal.message  # never the provider's body


def test_an_ordinary_rate_limit_is_still_unclassified() -> None:
    body = {"error": {"type": "rate_limit_error", "message": "Error"}}
    assert provider_errors.classify("claude-api", ProviderStatusError(429, body)) is None


def test_the_reset_is_read_from_the_usage_limit_body() -> None:
    assert sr._failure(
        429, {"error": {"code": "usage_limit_reached", "resets_in_seconds": 5400}}
    ).retry_after == "5400"
    soon = dt.datetime.now(dt.UTC).timestamp() + 600
    reset = sr._failure(429, {"error": {"type": "usage_limit_reached", "resets_at": soon}})
    assert reset.retry_after is not None and 590 <= int(reset.retry_after) <= 600
    assert sr._failure(429, {"error": {"resets_in_seconds": True}}).retry_after is None


def test_the_message_names_the_reset_time_only_when_known() -> None:
    known = provider_errors.usage_limit_message("openai-codex", 3600)
    stamp = re.search(r"resets at (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", known)
    assert stamp is not None
    at = dt.datetime.strptime(stamp.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
    assert abs((at - dt.datetime.now(dt.UTC)).total_seconds() - 3600) < 60
    assert "resets at" not in provider_errors.usage_limit_message("openai-codex")


def test_a_usage_limit_ends_the_turn_without_an_automatic_continuation() -> None:
    assert blocks_automatic_recovery(provider_errors.usage_limit_message("openai-codex"))


# ------------------------------------------------------------ gateway cooldown


def _grant(provider: str = "openai-codex") -> gateway.Grant:
    return gateway.Grant(agent_id="agent-1", provider=provider, account_id="acct")


def test_the_gateway_reports_a_usage_limit_without_a_30_second_wait() -> None:
    exc = SubscriptionReasoningError(
        "The selected ChatGPT subscription reached a usage limit. "
        "Try again after its allowance resets.",
        code="usage_limit_reached",
        status=429,
    )
    failure = gateway._report_failure(
        _grant(), "m", gateway._subscription_failure(_grant(), exc), None
    )
    assert (failure.status, failure.code) == (429, "usage_limit")
    assert "Try again in" not in str(failure) and "30 s" not in str(failure)
    assert "resets at" not in str(failure)  # the provider named no reset time
    # The next call is refused early with the same words, not as a rate limit.
    with pytest.raises(gateway.GatewayError) as again:
        gateway.check_cooldown("openai-codex", "m", "acct")
    assert again.value.code == "usage_limit" and "Try again in" not in str(again.value)


def test_a_known_reset_is_named_and_kept_by_the_cooldown() -> None:
    exc = SubscriptionReasoningError(
        "reached a usage limit", code="usage_limit_reached", status=429, retry_after="7200"
    )
    failure = gateway._report_failure(
        _grant(), "m", gateway._subscription_failure(_grant(), exc), None
    )
    assert failure.code == "usage_limit" and "resets at" in str(failure)
    assert failure.retry_after == pytest.approx(7200, abs=1)
    with pytest.raises(gateway.GatewayError) as again:
        gateway.check_cooldown("openai-codex", "m", "acct")
    assert "resets at" in str(again.value)


def test_a_rate_limit_still_says_when_to_try_again() -> None:
    failure = gateway._report_failure(
        _grant("openai"), "m", gateway._failure("openai", ProviderStatusError(429)), None
    )
    assert failure.code == "rate_limited" and "Try again in 30 s" in str(failure)


# ------------------------------------------------------------ OpenClaw's log


def _log(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "gateway.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_START = dt.datetime.fromisoformat("2026-10-27T12:35:15+01:00").timestamp()
_OVERFLOW_RUN = [
    "2026-10-27T12:30:00.000+01:00 [agent/embedded] embedded run agent end: runId=old "
    "isError=true model=m provider=jarvis error=x rawError=An older turn's failure",
    "2026-10-27T12:35:25.546+01:00 [agent/embedded] embedded run agent end: runId=r1 "
    "isError=true model=qwen3.5:9b provider=jarvis error=Agent run failed. rawError=Context "
    "window exceeded: estimated input 184592 leaves only 1 output tokens within the "
    "65536-token context.",
    "2026-10-27T12:35:25.624+01:00 [agent/embedded] context overflow detected (attempt 1/3); "
    "attempting auto-compaction for jarvis/qwen3.5:9b",
    "2026-10-27T12:38:25.830+01:00 [agent/embedded] [context-overflow-recovery] exhausted "
    "provider overflow recovery for jarvis/qwen3.5:9b; livenessState=blocked "
    "suggestedAction=reset_or_new kind=context_overflow",
    "2026-10-27T12:38:26.319+01:00 [diagnostic] message dispatch completed: outcome=error",
]


def test_a_context_overflow_the_gateway_gave_up_on_reads_as_a_full_context(tmp_path) -> None:
    assert run_failure(_log(tmp_path, _OVERFLOW_RUN), _START) == CONTEXT_FULL_REASON


def test_only_lines_of_this_turn_count(tmp_path) -> None:
    path = _log(tmp_path, _OVERFLOW_RUN)
    assert run_failure(path, _START + 3600) == ""
    assert run_failure(tmp_path / "missing.log", _START) == ""


def test_another_failed_run_says_its_own_short_reason_without_secrets(tmp_path) -> None:
    path = _log(
        tmp_path,
        [
            "2026-10-27T12:35:25.546+01:00 [agent/embedded] embedded run agent end: runId=r1 "
            "isError=true model=m provider=jarvis error=failed rawError=Tool loop aborted "
            "with key sk-abcdef1234567890 " + "x" * 400,
        ],
    )
    reason = run_failure(path, _START)
    assert reason.startswith("OpenClaw ended the run with an error: Tool loop aborted")
    assert "sk-abcdef" not in reason and "[redacted]" in reason
    assert len(reason) < 320


def test_an_overflow_the_run_never_got_past_is_the_reason(tmp_path) -> None:
    """Only consulted for a turn that ended without an answer."""
    assert run_failure(_log(tmp_path, _OVERFLOW_RUN[:2]), _START) == CONTEXT_FULL_REASON
