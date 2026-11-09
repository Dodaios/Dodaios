"""Issue #828: a GPT-Live start failure tells the person what to fix.

The browser route used to send only the generic "could not start" text when
the subscription session failed and usage-billed fallback was disabled. A
classified :class:`SubscriptionLiveError` (plan not offered, reconnect needed,
allowance exhausted) now reaches the surface with its static message, while
raw provider text still never does.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import dodaios.browser_voice.route as route_mod
from dodaios.browser_voice.route import (
    _USAGE_FALLBACK_DISABLED_DETAIL,
    _USAGE_FALLBACK_DISABLED_NOTE,
    _fallback_disabled_detail,
    browser_voice_ws,
)
from dodaios.plugins.realtime.openai_subscription_live import (
    SubscriptionLiveError,
    static_failure_message,
)
from dodaios.ui.web.missions_auth import register_token, revoke_token
from tests.unit.browser_voice.test_route import (
    _VALID_TOKEN,
    _FakeWS,
    _RecSession,
    _state,
)


@pytest.fixture(autouse=True)
def _registered_browser_token():
    register_token(_VALID_TOKEN)
    try:
        yield
    finally:
        revoke_token(_VALID_TOKEN)


def _provider_errors(ws: _FakeWS) -> list[str]:
    return [m.get("error") for m in ws.sent_json if m.get("type") == "provider_error"]


async def _run_failing_start(monkeypatch, error: BaseException) -> _FakeWS:
    classic = _RecSession()

    class _SubscriptionOnlyRealtime(_RecSession):
        is_realtime = True
        allow_classic_fallback = False

        async def handle_control(self, _msg: dict) -> None:
            raise error

    state = _state(classic)
    state.config.voice = SimpleNamespace(mode="realtime")
    monkeypatch.setattr(
        route_mod, "_build_browser_session", lambda **_kwargs: _SubscriptionOnlyRealtime()
    )
    ws = _FakeWS(
        [{"type": "websocket.receive", "text": '{"type":"audio_start","sample_rate":48000}'}],
        state=state,
    )
    await browser_voice_ws(ws)
    assert classic.controls == []
    assert ws.closed == (1011, "automatic API fallback disabled")
    return ws


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "plan", "expected_start"),
    [
        ("voice_not_offered", "free", "The selected ChatGPT account (Free plan) is not offered"),
        ("authentication_required", "", "Reconnect your ChatGPT subscription"),
        ("quota_exhausted", "", "The ChatGPT subscription voice allowance is exhausted."),
    ],
)
async def test_classified_subscription_failure_reaches_the_surface(
    monkeypatch, code, plan, expected_start
) -> None:
    ws = await _run_failing_start(monkeypatch, SubscriptionLiveError(code, plan=plan))

    errors = _provider_errors(ws)
    assert len(errors) == 1
    assert errors[0].startswith(expected_start)
    assert errors[0].endswith(_USAGE_FALLBACK_DISABLED_NOTE)
    assert errors[0] != _USAGE_FALLBACK_DISABLED_DETAIL


@pytest.mark.asyncio
async def test_wrapped_subscription_failure_is_still_classified(monkeypatch) -> None:
    try:
        try:
            raise SubscriptionLiveError("quota_exhausted")
        except SubscriptionLiveError as inner:
            raise RuntimeError("transport wrapper") from inner
    except RuntimeError as wrapped:
        ws = await _run_failing_start(monkeypatch, wrapped)

    assert _provider_errors(ws) == [
        "The ChatGPT subscription voice allowance is exhausted. "
        + _USAGE_FALLBACK_DISABLED_NOTE
    ]


@pytest.mark.asyncio
async def test_raw_provider_text_is_never_forwarded(monkeypatch) -> None:
    raw = 'HTTP 500 {"error": {"message": "secret internal detail sk-abc"}}'
    ws = await _run_failing_start(monkeypatch, RuntimeError(raw))

    assert _provider_errors(ws) == [_USAGE_FALLBACK_DISABLED_DETAIL]
    assert all("secret" not in str(m) for m in ws.sent_json)


def test_recorded_failure_strings_only_pass_when_static() -> None:
    message = str(SubscriptionLiveError("voice_not_offered", plan="go"))
    assert static_failure_message(message) == message
    assert _fallback_disabled_detail(message) == f"{message} {_USAGE_FALLBACK_DISABLED_NOTE}"
    assert static_failure_message("provider stream ended mid-turn") is None
    assert static_failure_message(message + " extra provider detail") is None
    assert _fallback_disabled_detail("stream ended") == _USAGE_FALLBACK_DISABLED_DETAIL
    assert _fallback_disabled_detail(None) == _USAGE_FALLBACK_DISABLED_DETAIL


@pytest.mark.asyncio
async def test_login_and_timeout_failures_are_named(monkeypatch) -> None:
    from dodaios.live.start_failure import TIMED_OUT
    from dodaios.live.subscription_auth import SubscriptionAuthError

    expired = "The ChatGPT login expired. Sign in again in Agent accounts."
    ws = await _run_failing_start(monkeypatch, SubscriptionAuthError(expired))
    assert _provider_errors(ws) == [f"{expired} {_USAGE_FALLBACK_DISABLED_NOTE}"]

    ws = await _run_failing_start(monkeypatch, TimeoutError())
    assert _provider_errors(ws) == [f"{TIMED_OUT} {_USAGE_FALLBACK_DISABLED_NOTE}"]


@pytest.mark.asyncio
async def test_api_key_refusal_shows_its_authored_sentence_only(monkeypatch) -> None:
    from dodaios.core.protocols import VoiceStartError

    error = VoiceStartError(
        "OpenAI Live session creation failed (HTTP 429, no_credits).",
        user_message="The OpenAI API account has no credit left.",
        code="no_credits",
    )
    ws = await _run_failing_start(monkeypatch, error)
    assert _provider_errors(ws) == [
        f"The OpenAI API account has no credit left. {_USAGE_FALLBACK_DISABLED_NOTE}"
    ]
    assert all("HTTP 429" not in str(m) for m in ws.sent_json)


def test_a_recorded_failure_code_resolves_to_its_sentence() -> None:
    assert _fallback_disabled_detail("voice_not_offered").startswith(
        "The selected ChatGPT account is not offered subscription voice."
    )


@pytest.mark.asyncio
async def test_an_engine_that_cannot_be_built_says_what_to_do(monkeypatch) -> None:
    state = _state(_RecSession())
    state.config.voice = SimpleNamespace(mode="realtime")
    monkeypatch.setattr(route_mod, "_build_browser_session", lambda **_kwargs: None)
    monkeypatch.setattr(route_mod, "_automatic_usage_fallback_allowed", lambda _cfg: False)
    ws = _FakeWS([], state=state)
    await browser_voice_ws(ws)
    assert ws.closed == (1011, "realtime access unavailable")
    assert _provider_errors(ws) == [route_mod._SELECTED_VOICE_NOT_READY_DETAIL]
