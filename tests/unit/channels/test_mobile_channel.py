"""Mobile gateway: pairing, device keys, rate limit, and the chat round trip."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
from pathlib import Path

import httpx
import pytest

from jarvis.channels.mobile import MobileChannel, device_session_id
from jarvis.core.bus import EventBus
from jarvis.core.config import IntegrationsConfig, MobileGatewayConfig
from jarvis.core.events import ResponseGenerated
from jarvis.mobile_gateway.__main__ import pairing_payload
from jarvis.mobile_gateway.app import create_app
from jarvis.mobile_gateway.devices import MAX_FAILED_PAIRINGS, DeviceStore
from jarvis.mobile_gateway.ratelimit import RateLimiter
from jarvis.mobile_gateway.tls import ensure_certificate, fingerprint


def _client(app: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _echo(text: str, _device: object) -> str:
    return f"echo:{text}"


def _app(store: DeviceStore, *, per_minute: int = 1000, send=_echo):  # noqa: ANN001, ANN202
    return create_app(
        store=store,
        limiter=RateLimiter(per_minute),
        send_message=send,
        max_message_chars=50,
    )


def test_config_is_off_by_default() -> None:
    cfg = IntegrationsConfig().mobile
    assert cfg.enabled is False
    assert cfg.port == 8443


def test_store_keeps_only_hashes(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path)
    code = store.issue_code(300)
    result = store.pair(code, "Pixel")
    assert result is not None
    raw = (tmp_path / "devices.json").read_text(encoding="utf-8")
    assert code not in raw
    assert result.token not in raw


def test_code_is_single_use_and_expires(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path)
    code = store.issue_code(300)
    assert store.pair(code.lower(), "a") is not None
    assert store.pair(code, "b") is None
    expired = store.issue_code(-1)
    assert store.pair(expired, "c") is None


def test_wrong_codes_burn_pending_codes(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path)
    code = store.issue_code(300)
    for _ in range(MAX_FAILED_PAIRINGS):
        assert store.pair("WRONGWRO", "x") is None
    assert store.pair(code, "x") is None


def test_revoked_device_is_rejected(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path)
    result = store.pair(store.issue_code(300), "Pixel")
    assert result is not None
    credential = f"{result.device_id}.{result.token}"
    assert store.authenticate(credential) is not None
    assert store.authenticate(f"{result.device_id}.wrong") is None
    assert store.revoke(result.device_id)
    assert store.authenticate(credential) is None


def test_rate_limiter_window() -> None:
    limiter = RateLimiter(2)
    assert limiter.allow("a", now=0.0)
    assert limiter.allow("a", now=1.0)
    assert not limiter.allow("a", now=2.0)
    assert limiter.allow("b", now=2.0)
    assert limiter.allow("a", now=61.0)


async def test_api_pair_status_message(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path)
    async with _client(_app(store)) as client:
        assert (await client.get("/api/m/health")).json()["ok"] is True
        assert (await client.get("/api/m/status")).status_code == 401
        bad = await client.post("/api/m/pair", json={"code": "NOPE", "device_name": "p"})
        assert bad.status_code == 403

        paired = await client.post(
            "/api/m/pair", json={"code": store.issue_code(300), "device_name": "Pixel"}
        )
        assert paired.status_code == 200
        auth = {"Authorization": f"Bearer {paired.json()['token']}"}

        status = await client.get("/api/m/status", headers=auth)
        assert status.status_code == 200
        assert status.json()["device"] == "Pixel"

        reply = await client.post("/api/m/message", json={"text": " hi "}, headers=auth)
        assert reply.json() == {"reply": "echo:hi"}
        too_long = await client.post("/api/m/message", json={"text": "x" * 51}, headers=auth)
        assert too_long.status_code == 413

        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/api/m/../../api/settings")).status_code == 404


async def test_api_no_reply_is_504(tmp_path: Path) -> None:
    async def silent(_text: str, _device: object) -> None:
        return None

    store = DeviceStore(tmp_path)
    result = store.pair(store.issue_code(300), "p")
    assert result is not None
    auth = {"Authorization": f"Bearer {result.device_id}.{result.token}"}
    async with _client(_app(store, send=silent)) as client:
        resp = await client.post("/api/m/message", json={"text": "hi"}, headers=auth)
    assert resp.status_code == 504


async def test_api_rate_limit(tmp_path: Path) -> None:
    async with _client(_app(DeviceStore(tmp_path), per_minute=2)) as client:
        codes = [(await client.get("/api/m/health")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_certificate_is_stable(tmp_path: Path) -> None:
    cert, key = ensure_certificate(tmp_path)
    first = fingerprint(cert)
    assert ensure_certificate(tmp_path) == (cert, key)
    assert fingerprint(cert) == first
    assert len(first) == 64


def test_pairing_payload_shape() -> None:
    payload = json.loads(pairing_payload("2a02::1", 8443, "ab" * 32, "ABCDEFGH"))
    assert payload == {"v": 1, "h": "2a02::1", "p": 8443, "f": "ab" * 32, "c": "ABCDEFGH"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_channel_round_trip_over_tls(tmp_path: Path) -> None:
    bus = EventBus()
    cfg = MobileGatewayConfig(
        enabled=True, host="127.0.0.1", port=_free_port(), data_dir=str(tmp_path)
    )
    channel = MobileChannel(bus, cfg)
    await channel.start()
    try:
        cert = tmp_path / "gateway-cert.pem"
        ctx = ssl.create_default_context(cafile=str(cert))
        ctx.check_hostname = False
        base = f"https://127.0.0.1:{cfg.port}"

        async def answer() -> None:
            async for msg in channel.messages():
                assert msg.session_id == device_session_id(msg.metadata["channel_session_id"])
                await bus.publish(
                    ResponseGenerated(trace_id=msg.trace_id, text=f"re:{msg.content}")
                )
                return

        responder = asyncio.create_task(answer())
        async with httpx.AsyncClient(verify=ctx, base_url=base) as client:
            for _ in range(50):
                try:
                    await client.get("/api/m/health")
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.05)
            code = channel.store.issue_code(300)
            token = (await client.post("/api/m/pair", json={"code": code})).json()["token"]
            reply = await client.post(
                "/api/m/message",
                json={"text": "ping"},
                headers={"Authorization": f"Bearer {token}"},
            )
        await responder
        assert reply.json() == {"reply": "re:ping"}
        log_text = (tmp_path / "access.log").read_text(encoding="utf-8")
        assert "/api/m/message 200" in log_text
        assert token.split(".", 1)[1] not in log_text
    finally:
        await channel.stop()


async def test_channel_port_in_use_fails_start(tmp_path: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        cfg = MobileGatewayConfig(enabled=True, host="127.0.0.1", port=port, data_dir=str(tmp_path))
        channel = MobileChannel(EventBus(), cfg)
        with pytest.raises(Exception, match="cannot listen"):
            await channel.start()


async def test_disabled_channel_opens_nothing(tmp_path: Path) -> None:
    channel = MobileChannel(EventBus(), MobileGatewayConfig(data_dir=str(tmp_path)))
    await channel.start()
    await channel.stop()
    assert not (tmp_path / "gateway-cert.pem").exists()
