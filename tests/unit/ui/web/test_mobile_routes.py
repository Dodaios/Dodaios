"""The phone companion over the real outer boundary: no token → 401, scoped tokens."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import send_queue
from dodaios.mobile import devices as devices_mod
from dodaios.mobile import notify as notify_mod
from dodaios.mobile import webpush as webpush_mod
from dodaios.mobile.devices import MobileDevices
from dodaios.mobile.webpush import VapidKeys
from dodaios.ui.web import mobile_routes
from dodaios.ui.web.missions_auth import issue_token, reset_tokens
from dodaios.ui.web.surface_security import COOKIE_NAME, SurfaceSecurity

pytestmark = pytest.mark.no_auto_web_auth

LEAD = "lead-session"


class _Store:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = [
            {"seq": 1, "ts_ms": 1, "kind": "user_message", "payload": {"text": "Hello"}},
            {"seq": 2, "ts_ms": 2, "kind": "assistant_text",
             "payload": {"turn_id": "t1", "text": "Hi."}},
            {"seq": 3, "ts_ms": 3, "kind": "approval_required",
             "payload": {"approval_id": "ap1", "name": "run", "summary": "do it"}},
        ]
        self.session = SimpleNamespace(session_id=LEAD, surface="jarvis", title="Lead")

    def lead_session_id(self) -> str:
        return LEAD

    def set_lead_session_id(self, value: str) -> None:
        return None

    def get_session(self, session_id: str):
        return self.session if session_id == LEAD else None

    def list_sessions(self, limit: int = 1, surface: str = ""):
        return [self.session]

    def list_events(self, session_id: str, *, after_seq: int = 0, tail: int | None = None):
        rows = [e for e in self.events if e["seq"] > after_seq]
        return rows[-tail:] if tail else rows


class _Service:
    def __init__(self) -> None:
        self.store = _Store()
        self.sent: list[str] = []
        self.approvals: list[tuple[str, str, str]] = []
        self.listeners: list[Any] = []

    def is_running(self, session_id: str) -> bool:
        return False

    def add_event_listener(self, fn) -> None:
        self.listeners.append(fn)

    def resolve_approval(self, session_id, approval_id, decision, **_kw) -> bool:
        if approval_id != "ap1":
            return False
        self.approvals.append((session_id, approval_id, decision))
        return True

    async def close_stale_approval(self, session_id, approval_id) -> bool:
        return approval_id == "stale"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    store = MobileDevices(tmp_path / "devices.json")
    devices_mod.set_devices(store)
    webpush_mod.set_vapid(VapidKeys(tmp_path / "vapid.json"))
    notify_mod.set_notifier(None)
    svc = _Service()

    async def fake_send_or_queue(service, session_id, text, attachments=None, **_kw):
        service.sent.append(text)
        return "turn-1", ""

    monkeypatch.setattr(send_queue, "send_or_queue", fake_send_or_queue)
    monkeypatch.setattr(mobile_routes, "MOBILE_INDEX", tmp_path / "m" / "index.html")
    monkeypatch.setenv("JARVIS_BIND_HOST", "0.0.0.0")  # noqa: S104 — the LAN case under test
    monkeypatch.setattr(mobile_routes, "lan_addresses", lambda: ["192.168.1.20"])

    app = FastAPI()
    app.include_router(mobile_routes.router)
    app.state.agent_chat = svc
    app.state.config = None

    @app.get("/api/private-proof")
    def private_ui():
        return {"authenticated": True}

    secured = SurfaceSecurity(app, control_key_validator=lambda value: value == "owner-key")
    desktop = TestClient(
        secured, base_url="http://127.0.0.1:47821", headers={"origin": "http://127.0.0.1:47821"}
    )
    desktop.cookies.set(COOKIE_NAME, issue_token())
    # The phone: a LAN peer, no cookie. ``client`` is what uvicorn reports.
    phone = TestClient(
        secured, base_url="http://192.168.1.20:47821", client=("192.168.1.55", 5000)
    )
    yield SimpleNamespace(desktop=desktop, phone=phone, svc=svc, store=store, tmp=tmp_path)
    devices_mod.set_devices(None)
    webpush_mod.set_vapid(None)
    notify_mod.set_notifier(None)
    reset_tokens()


def _pair(harness, name="Phone") -> tuple[str, dict]:
    code = harness.desktop.post("/api/mobile/pair/code").json()
    assert code["urls"] == [f"http://192.168.1.20:47821/m/#pair={code['code']}"]
    redeemed = harness.phone.post(
        "/api/mobile/pair/redeem", json={"code": code["code"], "name": name}
    )
    assert redeemed.status_code == 200, redeemed.text
    body = redeemed.json()
    return body["token"], body["device"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_phone_routes_refuse_without_a_token(harness) -> None:
    for path in ("/api/mobile/app/me", "/api/mobile/app/lead", "/api/mobile/app/push/key"):
        response = harness.phone.get(path)
        assert response.status_code == 401, path
    typed = harness.phone.post("/api/mobile/app/lead/messages", json={"text": "x"})
    assert typed.status_code == 401
    assert harness.phone.get("/api/mobile/app/me", headers=_auth("mdt_nope")).status_code == 401
    # A desktop-only route is closed to the phone as well (no cookie, no key).
    assert harness.phone.get("/api/mobile/devices").status_code == 401
    assert harness.phone.post("/api/mobile/pair/code").status_code == 401


def test_pairing_flow_reads_types_and_approves(harness) -> None:
    token, device = _pair(harness, "Ruby's phone")
    assert device["name"] == "Ruby's phone" and device["push"] is False
    # The code is spent.
    assert harness.phone.post(
        "/api/mobile/pair/redeem", json={"code": "WRONGCODE1", "name": "x"}
    ).status_code == 401

    me = harness.phone.get("/api/mobile/app/me", headers=_auth(token))
    assert me.status_code == 200 and me.json()["push_key"]

    lead = harness.phone.get("/api/mobile/app/lead", headers=_auth(token))
    assert lead.status_code == 200
    body = lead.json()
    assert body["session_id"] == LEAD and body["pending_approvals"] == ["ap1"]
    assert [r["kind"] for r in body["rows"]] == ["user", "assistant", "approval"]

    sent = harness.phone.post(
        "/api/mobile/app/lead/messages", json={"text": " Buy milk "}, headers=_auth(token)
    )
    assert sent.status_code == 200 and sent.json()["turn_id"] == "turn-1"
    assert harness.svc.sent == ["Buy milk"]

    approved = harness.phone.post(
        "/api/mobile/app/lead/approvals/ap1", json={"decision": "allow"}, headers=_auth(token)
    )
    assert approved.status_code == 200
    assert harness.svc.approvals == [(LEAD, "ap1", "allow")]
    assert harness.phone.post(
        "/api/mobile/app/lead/approvals/stale", json={"decision": "deny"}, headers=_auth(token)
    ).status_code == 410
    assert harness.phone.post(
        "/api/mobile/app/lead/approvals/nope", json={"decision": "deny"}, headers=_auth(token)
    ).status_code == 404
    assert harness.phone.post(
        "/api/mobile/app/lead/approvals/ap1", json={"decision": "allow_always"},
        headers=_auth(token),
    ).status_code == 422
    # The notice listener for pushes is attached once the service is used.
    assert len(harness.svc.listeners) == 1


def test_device_token_opens_nothing_but_the_phone_routes(harness) -> None:
    token, _device = _pair(harness)
    assert harness.phone.get("/api/private-proof", headers=_auth(token)).status_code == 401
    assert harness.phone.get("/api/mobile/devices", headers=_auth(token)).status_code == 401
    assert harness.phone.post("/api/mobile/pair/code", headers=_auth(token)).status_code == 401
    assert harness.phone.get("/api/mobile/status", headers=_auth(token)).status_code == 401


def test_revoke_from_the_desktop_locks_the_phone_out(harness) -> None:
    token, device = _pair(harness)
    listed = harness.desktop.get("/api/mobile/devices").json()["devices"]
    assert [d["id"] for d in listed] == [device["id"]]
    assert "digest" not in listed[0]
    renamed = harness.desktop.patch(
        f"/api/mobile/devices/{device['id']}", json={"name": "Kitchen phone"}
    )
    assert renamed.json()["name"] == "Kitchen phone"
    assert harness.desktop.delete(f"/api/mobile/devices/{device['id']}").status_code == 200
    assert harness.phone.get("/api/mobile/app/me", headers=_auth(token)).status_code == 401
    assert harness.desktop.delete(f"/api/mobile/devices/{device['id']}").status_code == 404


def test_phone_can_unpair_itself(harness) -> None:
    token, _device = _pair(harness)
    assert harness.phone.post("/api/mobile/app/unpair", headers=_auth(token)).status_code == 200
    assert harness.phone.get("/api/mobile/app/me", headers=_auth(token)).status_code == 401
    assert harness.desktop.get("/api/mobile/devices").json()["devices"] == []


def test_push_subscription_round_trip(harness) -> None:
    token, device = _pair(harness)
    key = harness.phone.get("/api/mobile/app/push/key", headers=_auth(token)).json()["key"]
    assert key
    bad = harness.phone.put(
        "/api/mobile/app/push/subscription",
        json={"endpoint": "http://plain.example/x", "keys": {"p256dh": "k" * 32, "auth": "a" * 16}},
        headers=_auth(token),
    )
    assert bad.status_code == 422
    ok = harness.phone.put(
        "/api/mobile/app/push/subscription",
        json={"endpoint": "https://push.example/x", "keys": {"p256dh": "k" * 32, "auth": "a" * 16}},
        headers=_auth(token),
    )
    assert ok.status_code == 200
    assert harness.desktop.get("/api/mobile/devices").json()["devices"][0]["push"] is True
    assert "push.example" not in harness.store.path.read_text(encoding="utf-8").replace(
        "https://push.example/x", ""
    )
    gone = harness.phone.delete("/api/mobile/app/push/subscription", headers=_auth(token))
    assert gone.status_code == 200
    assert harness.desktop.get("/api/mobile/devices").json()["devices"][0]["push"] is False
    assert harness.phone.post("/api/mobile/app/push/test", headers=_auth(token)).status_code == 409


def test_status_and_whatsapp_switch(harness, monkeypatch) -> None:
    from dodaios.channels import whatsapp

    monkeypatch.setattr(whatsapp, "_config_path", lambda: harness.tmp / "whatsapp.json")
    status = harness.desktop.get("/api/mobile/status").json()
    assert status["push_ready"] is True and status["devices"] == []
    assert status["listening"]["loopback_only"] is False
    assert status["listening"]["lan_addresses"] == ["192.168.1.20"]
    assert status["whatsapp"]["enabled"] is False and status["whatsapp"]["missing"] == "bridge"
    turned_on = harness.desktop.put("/api/mobile/whatsapp", json={"enabled": True}).json()
    assert turned_on["enabled"] is True
    assert whatsapp.load_whatsapp_config(harness.tmp / "whatsapp.json").enabled is True


def test_loopback_only_bind_offers_no_lan_links(harness, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_BIND_HOST", "127.0.0.1")
    code = harness.desktop.post("/api/mobile/pair/code").json()
    assert code["urls"] == [] and code["listening"]["loopback_only"] is True


def test_plain_http_from_a_public_address_is_refused(harness) -> None:
    code = harness.desktop.post("/api/mobile/pair/code").json()["code"]
    public = TestClient(
        harness.phone.app, base_url="http://93.184.216.34:47821", client=("93.184.216.35", 5000)
    )
    assert public.post("/api/mobile/pair/redeem", json={"code": code}).status_code == 403


def test_voice_note_without_a_recognizer_says_so(harness, monkeypatch) -> None:
    token, _device = _pair(harness)
    monkeypatch.setattr(mobile_routes, "_voice_note_stt", lambda: None)
    response = harness.phone.post(
        "/api/mobile/app/lead/voice-note", content=b"\x00" * 6400, headers=_auth(token)
    )
    assert response.status_code == 503
    short = harness.phone.post(
        "/api/mobile/app/lead/voice-note", content=b"\x00" * 10, headers=_auth(token)
    )
    assert short.status_code == 422


def test_voice_note_transcribes_and_sends(harness, monkeypatch) -> None:
    token, _device = _pair(harness)

    class _Stt:
        async def transcribe_pcm(self, pcm, language=None):
            return SimpleNamespace(text="  Remind me tomorrow ")

    monkeypatch.setattr(mobile_routes, "_voice_note_stt", lambda: _Stt())
    response = harness.phone.post(
        "/api/mobile/app/lead/voice-note", content=b"\x00" * 6400, headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json()["text"] == "Remind me tomorrow"
    assert harness.svc.sent == ["Remind me tomorrow"]


def test_mobile_page_is_served_from_the_build(harness) -> None:
    assert harness.phone.get("/m/").status_code == 404
    mobile_routes.MOBILE_INDEX.parent.mkdir(parents=True)
    mobile_routes.MOBILE_INDEX.write_text("<!doctype html><title>Phone</title>", encoding="utf-8")
    page = harness.phone.get("/m/")
    assert page.status_code == 200 and "Phone" in page.text
    assert page.headers["cache-control"].startswith("no-store")
    assert harness.phone.get("/m").status_code == 200
