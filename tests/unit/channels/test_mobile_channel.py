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


async def _paired(store: DeviceStore, client: httpx.AsyncClient) -> dict[str, str]:
    paired = await client.post(
        "/api/m/pair", json={"code": store.issue_code(300), "device_name": "Pixel"}
    )
    return {"Authorization": f"Bearer {paired.json()['token']}"}


async def test_api_history_and_tasks(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path)
    async with _client(_app(store)) as client:
        assert (await client.get("/api/m/tasks")).status_code == 401
        auth = await _paired(store, client)
        await client.post("/api/m/message", json={"text": "hi"}, headers=auth)
        items = (await client.get("/api/m/history", headers=auth)).json()["items"]
        assert [(i["role"], i["text"]) for i in items] == [("user", "hi"), ("jarvis", "echo:hi")]

        task = (
            await client.post("/api/m/tasks", json={"text": " Milch  holen "}, headers=auth)
        ).json()
        assert task["text"] == "Milch holen" and task["done"] is False
        done = await client.post(f"/api/m/tasks/{task['id']}", json={"done": True}, headers=auth)
        assert done.json()["done"] is True
        assert (
            await client.post("/api/m/tasks/nope", json={"done": True}, headers=auth)
        ).status_code == 404
        assert (await client.delete(f"/api/m/tasks/{task['id']}", headers=auth)).json() == {
            "ok": True
        }
        assert (await client.get("/api/m/tasks", headers=auth)).json() == {"items": []}


async def test_api_files_round_trip(tmp_path: Path) -> None:
    store = DeviceStore(tmp_path)
    async with _client(_app(store)) as client:
        auth = await _paired(store, client)
        up = await client.post(
            "/api/m/files", params={"name": "../../evil.txt"}, content=b"abc", headers=auth
        )
        assert up.json() == {"name": "evil.txt", "size": 3}
        device_id = auth["Authorization"].split()[1].split(".")[0]
        to_phone = tmp_path / "devices" / device_id / "to_phone"
        to_phone.mkdir(parents=True, exist_ok=True)
        (to_phone / "plan.pdf").write_bytes(b"pdf")

        listed = (await client.get("/api/m/files", headers=auth)).json()["items"]
        assert {(f["dir"], f["name"]) for f in listed} == {
            ("from_phone", "evil.txt"),
            ("to_phone", "plan.pdf"),
        }
        got = await client.get("/api/m/files/to_phone/plan.pdf", headers=auth)
        assert got.content == b"pdf"
        assert (
            await client.get("/api/m/files/to_phone/..%2Fhistory.jsonl", headers=auth)
        ).status_code == 404
        assert (await client.get("/api/m/files/etc/plan.pdf", headers=auth)).status_code == 404
        assert not (tmp_path / "evil.txt").exists()


async def test_inbox_receives_channel_messages(tmp_path: Path) -> None:
    from jarvis.channels.base import ChannelMessage

    cfg = MobileGatewayConfig(data_dir=str(tmp_path))
    channel = MobileChannel(EventBus(), cfg)
    result = channel.store.pair(channel.store.issue_code(300), "p")
    assert result is not None
    sid = device_session_id(result.device_id)
    await channel.send_message(ChannelMessage(session_id=sid, kind="text", content="Erinnerung"))
    await channel.send_message(ChannelMessage(session_id=sid, kind="text", content="Zweite"))
    auth = {"Authorization": f"Bearer {result.device_id}.{result.token}"}
    async with _client(_app(channel.store)) as client:
        items = (await client.get("/api/m/inbox", headers=auth)).json()["items"]
        assert [(i["id"], i["text"]) for i in items] == [(1, "Erinnerung"), (2, "Zweite")]
        later = (await client.get("/api/m/inbox", params={"after": 1}, headers=auth)).json()
        assert [i["text"] for i in later["items"]] == ["Zweite"]


def _missions_db(path: Path) -> Path:
    import sqlite3

    db = path / "missions.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE missions (id TEXT PRIMARY KEY, prompt TEXT, state TEXT, "
            "created_ms INTEGER, updated_ms INTEGER, cost_usd REAL)"
        )
        conn.executemany(
            "INSERT INTO missions VALUES (?, ?, ?, ?, ?, ?)",
            [("a", "Old  job", "APPROVED", 1, 10, 0.5), ("b", "New job", "RUNNING", 2, 20, 0.0)],
        )
    return db


def test_project_reader_lists_newest_first_and_never_writes(tmp_path: Path) -> None:
    from jarvis.mobile_gateway.projects import ProjectReader

    db = _missions_db(tmp_path)
    before = db.read_bytes()
    items = ProjectReader(db).missions()
    assert [(i["id"], i["title"], i["active"]) for i in items] == [
        ("b", "New job", True),
        ("a", "Old job", False),
    ]
    assert db.read_bytes() == before
    assert ProjectReader(tmp_path / "missing.db").missions() == []


async def test_api_projects(tmp_path: Path) -> None:
    from jarvis.mobile_gateway.projects import ProjectReader

    store = DeviceStore(tmp_path)
    app = create_app(
        store=store,
        limiter=RateLimiter(1000),
        send_message=_echo,
        max_message_chars=50,
        projects=ProjectReader(_missions_db(tmp_path)),
    )
    async with _client(app) as client:
        assert (await client.get("/api/m/projects")).status_code == 401
        auth = await _paired(store, client)
        body = (await client.get("/api/m/projects", headers=auth)).json()
        assert body["active"] == 1 and len(body["items"]) == 2


class _FakeVoice:
    """Stands in for the PC's /ws/audio: answers each frame and records it."""

    def __init__(self) -> None:
        self.received: list[str | bytes] = []
        self._out: asyncio.Queue[str | bytes | None] = asyncio.Queue()

    async def __aenter__(self) -> _FakeVoice:
        await self._out.put(json.dumps({"type": "audio_ready"}))
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def send(self, message: str | bytes) -> None:
        self.received.append(message)
        if isinstance(message, bytes):
            await self._out.put(b"\x01\x00" * 4)

    def __aiter__(self) -> _FakeVoice:
        return self

    async def __anext__(self) -> str | bytes:
        item = await self._out.get()
        if item is None:
            raise StopAsyncIteration
        return item


def test_api_call_relays_audio_both_ways(tmp_path: Path) -> None:
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    store = DeviceStore(tmp_path)
    fake = _FakeVoice()
    app = create_app(
        store=store,
        limiter=RateLimiter(1000),
        send_message=_echo,
        max_message_chars=50,
        voice=lambda: fake,
    )
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/m/call"):
            pass
        token = client.post(
            "/api/m/pair", json={"code": store.issue_code(300), "device_name": "Pixel"}
        ).json()["token"]
        with client.websocket_connect(
            "/api/m/call", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            assert json.loads(ws.receive_text()) == {"type": "audio_ready"}
            ws.send_text(json.dumps({"type": "audio_start", "sample_rate": 16000}))
            ws.send_bytes(b"\x00\x00" * 160)
            assert ws.receive_bytes() == b"\x01\x00" * 4
    assert fake.received[0] == json.dumps({"type": "audio_start", "sample_rate": 16000})
    assert fake.received[1] == b"\x00\x00" * 160


def test_api_call_without_voice_closes(tmp_path: Path) -> None:
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    store = DeviceStore(tmp_path)
    with TestClient(_app(store)) as client:
        token = client.post(
            "/api/m/pair", json={"code": store.issue_code(300), "device_name": "Pixel"}
        ).json()["token"]
        with (
            client.websocket_connect(
                "/api/m/call", headers={"Authorization": f"Bearer {token}"}
            ) as ws,
            pytest.raises(WebSocketDisconnect) as closed,
        ):
            ws.receive_text()
        assert closed.value.code == 1011


def test_ring_board_delivers_waits_and_expires() -> None:
    from jarvis.mobile_gateway.ring import RingBoard

    async def scenario() -> None:
        board = RingBoard()
        assert await board.wait("d1", 0.01) is None
        waiter = asyncio.create_task(board.wait("d1", 5.0))
        await asyncio.sleep(0)
        board.ring("d1", "Frage?")
        got = await waiter
        assert got is not None and got.text == "Frage?"
        assert board.take("d1") is None
        stale = RingBoard(ttl_s=-1.0)
        stale.ring("d1", "alt")
        assert stale.take("d1") is None

    asyncio.run(scenario())


def test_api_ring_returns_pending_ring(tmp_path: Path) -> None:
    from jarvis.mobile_gateway.ring import RingBoard

    async def scenario() -> None:
        store = DeviceStore(tmp_path)
        board = RingBoard()
        app = create_app(
            store=store,
            limiter=RateLimiter(1000),
            send_message=_echo,
            max_message_chars=50,
            rings=board,
        )
        async with _client(app) as client:
            assert (await client.get("/api/m/ring")).status_code == 401
            paired = await client.post(
                "/api/m/pair", json={"code": store.issue_code(300), "device_name": "Pixel"}
            )
            auth = {"Authorization": f"Bearer {paired.json()['token']}"}
            assert (await client.get("/api/m/ring?wait=0", headers=auth)).json() == {"ring": None}
            board.ring(store.devices()[0].device_id, "Jarvis fragt")
            ring = (await client.get("/api/m/ring?wait=0", headers=auth)).json()["ring"]
            assert ring["text"] == "Jarvis fragt"

    asyncio.run(scenario())


def test_approval_request_rings_paired_phones(tmp_path: Path) -> None:
    from jarvis.core.events import ActionApprovalRequired

    async def scenario() -> None:
        channel = MobileChannel(EventBus(), MobileGatewayConfig(data_dir=str(tmp_path)))
        pairing = channel.store.pair(channel.store.issue_code(300), "Pixel")
        assert pairing is not None
        await channel._on_bus_event(ActionApprovalRequired(tool_name="send_mail"))
        ring = channel.rings.take(pairing.device_id)
        assert ring is not None and "send_mail" in ring.text

    asyncio.run(scenario())
