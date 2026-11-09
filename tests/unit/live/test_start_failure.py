"""A failed voice start names its cause; provider text never reaches the person."""

from __future__ import annotations

import pytest

from dodaios.core.protocols import VoiceStartError
from dodaios.live.start_failure import TIMED_OUT, start_failure_reason
from dodaios.live.subscription_auth import SubscriptionAuthError
from dodaios.plugins.realtime.openai_live import _start_refusal
from dodaios.plugins.realtime.openai_subscription_live import (
    SubscriptionLiveError,
    static_failure_message,
)


def test_a_login_problem_keeps_its_own_sentence():
    error = SubscriptionAuthError("The ChatGPT login expired. Sign in again in Agent accounts.")
    assert start_failure_reason(error) == str(error)


def test_a_wrapped_cause_is_still_found():
    try:
        try:
            raise SubscriptionLiveError("quota_exhausted")
        except SubscriptionLiveError as inner:
            raise RuntimeError("wrapper with private detail") from inner
    except RuntimeError as outer:
        reason = start_failure_reason(outer)
    assert reason == "The ChatGPT subscription voice allowance is exhausted."


def test_a_person_facing_start_error_shows_only_its_authored_sentence():
    error = VoiceStartError(
        "OpenAI Live session creation failed (HTTP 429, no_credits).",
        user_message="The OpenAI API account has no credit left.",
        code="no_credits",
    )
    assert start_failure_reason(error) == "The OpenAI API account has no credit left."


def test_a_timeout_is_named():
    assert start_failure_reason(TimeoutError()) == TIMED_OUT


def test_the_bare_code_a_session_recorded_resolves_to_its_sentence():
    assert start_failure_reason("voice_not_offered") == static_failure_message(
        SubscriptionLiveError("voice_not_offered")
    )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("upstream said: private provider body"),
        ValueError("https://internal.example/path?token=abc"),
        "some provider sentence",
        "provider_error",
        None,
    ],
)
def test_unknown_failures_return_nothing_so_no_provider_text_leaks(error):
    assert start_failure_reason(error) is None


@pytest.mark.parametrize(
    ("status", "cause", "code"),
    [
        (401, "bad_key", "bad_key"),
        (403, "bad_key", "access_denied"),
        (403, "no_credits", "no_credits"),
        (429, "no_credits", "no_credits"),
        (429, "rate_limited", "rate_limited"),
        (404, "model_unavailable", "model_unavailable"),
        (404, "error", "model_unavailable"),
        (400, "error", "invalid_configuration"),
        (503, "unreachable", "unreachable"),
    ],
)
def test_an_api_key_refusal_is_classified_from_status_and_cause(status, cause, code):
    refused, sentence = _start_refusal(status, cause)
    assert refused == code
    assert sentence
    assert "HTTP" not in sentence


def test_an_unclassified_refusal_has_no_sentence():
    assert _start_refusal(418, "error") == ("unavailable", "")
