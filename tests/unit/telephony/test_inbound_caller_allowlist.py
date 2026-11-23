"""Only the owner's listed numbers reach the assistant by phone.

Anyone can dial a phone number. An inbound call used to get a full assistant
session, with its tools, whoever was calling; the chat channels have had an
owner allowlist for a long time, the telephone had none. The signed webhook
now hangs up on every caller that is not on ``allowed_callers`` before a
session or a call secret exists. An empty list takes no inbound call. Calls
the app places itself are unaffected.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dodaios.ui.web.telephony_routes as routes
from dodaios.core.config import JarvisConfig, TwilioConfig
from dodaios.telephony.security import caller_allowed, normalize_caller
from dodaios.telephony.status import TelephonyManager
from dodaios.ui.web.telephony_routes import router as telephony_router

_OWNER = "+4915112345678"
_STRANGER = "+15005550006"
_URL = "https://jarvis.example.com/api/telephony/voice"
_AUTH_TOKEN = "supersecrettoken"  # noqa: S105 - test signing secret


@pytest.fixture
def cfg() -> JarvisConfig:
    config = JarvisConfig()
    config.integrations.twilio = TwilioConfig(
        enabled=True,
        account_sid="AC0123456789abcdef0123456789abcdef",
        phone_number="+49301234567",
        allowed_callers=[_OWNER],
        public_base_url="https://jarvis.example.com",
    )
    return config


@pytest.fixture
def app(cfg: JarvisConfig, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    application = FastAPI()
    application.include_router(telephony_router)
    application.state.config = cfg
    application.state.telephony_manager = TelephonyManager()
    application.state.bus = None
    monkeypatch.setattr(routes, "get_secret", lambda *a, **k: _AUTH_TOKEN)
    return application


def _signed_call(app: FastAPI, params: dict[str, str], query: str = ""):
    from twilio.request_validator import RequestValidator

    url = f"{_URL}?{query}" if query else _URL
    signature = RequestValidator(_AUTH_TOKEN).compute_signature(url, params)
    path = f"/api/telephony/voice?{query}" if query else "/api/telephony/voice"
    with TestClient(app) as client:
        return client.post(path, data=params, headers={"X-Twilio-Signature": signature})


@pytest.mark.parametrize("caller", [_STRANGER, "anonymous", "", "client:someone", "+491511234567"])
def test_a_caller_not_on_the_list_is_hung_up_on(app: FastAPI, caller: str) -> None:
    params = {"CallSid": "CA-stranger", "From": caller, "To": "+49301234567"}
    params["Direction"] = "inbound"

    response = _signed_call(app, params)

    assert response.status_code == 200
    assert "<Hangup" in response.text
    assert "<Connect>" not in response.text
    assert "<Stream" not in response.text
    assert app.state.telephony_manager.peek_pending("CA-stranger") is None


def test_the_owner_gets_a_session(app: FastAPI) -> None:
    params = {"CallSid": "CA-owner", "From": _OWNER, "To": "+49301234567", "Direction": "inbound"}

    response = _signed_call(app, params)

    assert response.status_code == 200
    assert "<Connect>" in response.text
    assert app.state.telephony_manager.peek_pending("CA-owner") is not None


def test_an_empty_list_takes_no_inbound_call(app: FastAPI, cfg: JarvisConfig) -> None:
    cfg.integrations.twilio.allowed_callers = []
    params = {"CallSid": "CA-nobody", "From": _OWNER, "To": "+49301234567", "Direction": "inbound"}

    response = _signed_call(app, params)

    assert "<Hangup" in response.text
    assert "<Connect>" not in response.text
    assert app.state.telephony_manager.peek_pending("CA-nobody") is None


def test_a_call_the_app_placed_needs_no_list_entry(app: FastAPI, cfg: JarvisConfig) -> None:
    cfg.integrations.twilio.allowed_callers = []
    params = {
        "CallSid": "CA-out",
        "From": "+49301234567",
        "To": _STRANGER,
        "Direction": "outbound-api",
    }

    response = _signed_call(app, params, query="opening=Hello")

    assert "<Connect>" in response.text
    assert app.state.telephony_manager.peek_pending("CA-out") is not None


def test_an_unsigned_request_cannot_claim_to_be_outbound(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/telephony/voice?opening=Hello",
            data={"CallSid": "CA-forged", "From": _STRANGER, "Direction": "outbound-api"},
            headers={"X-Twilio-Signature": "garbage"},
        )

    assert response.status_code == 403
    assert "<Connect>" not in response.text


def test_the_list_is_saved_normalised_and_read_back(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: dict[str, object] = {}
    monkeypatch.setattr(
        "dodaios.core.config_writer.set_telephony_config", lambda values: written.update(values)
    )
    with TestClient(app) as client:
        saved = client.post(
            "/api/telephony/config",
            json={"allowed_callers": ["+49 151 1234-5678", "0049 151 12345678", "+14155550100"]},
        )
        refused = client.post("/api/telephony/config", json={"allowed_callers": ["not a number"]})
        read = client.get("/api/telephony/config")

    assert saved.status_code == 200
    assert written["allowed_callers"] == [_OWNER, "+14155550100"]
    assert refused.status_code == 422
    assert "allowed_callers" in read.json()


def test_numbers_are_compared_in_one_form() -> None:
    assert normalize_caller("+49 (151) 1234-5678") == _OWNER
    assert normalize_caller("0049 151 12345678") == _OWNER
    assert normalize_caller("anonymous") == ""
    assert normalize_caller("sip:owner@example.com") == ""
    assert normalize_caller(None) == ""
    assert caller_allowed(_OWNER, ["+49 151 12345678"])
    assert not caller_allowed(_OWNER, [])
    assert not caller_allowed("", [""])
    assert not caller_allowed("anonymous", ["anonymous"])
