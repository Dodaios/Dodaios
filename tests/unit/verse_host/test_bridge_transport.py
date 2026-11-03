"""17.2 / A17.2 and A17.3 (link half): the route over a real loopback socket.

Wrong token closes 4401 within 100 ms; no ``hello`` in 5 s closes 4400; a
non-loopback peer gets 4403; a second client replaces the first (4409); an
oversized frame closes 1009; the dead link is declared at 5 s within 0.5 s.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from dodaios.ui.web import verse_routes
from dodaios.verse_host import protocol as P
from tests.unit.verse_host._support import TOKEN, hello, make_host


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def server(tmp_path: Path):
    host, backend = make_host(tmp_path)
    app = FastAPI()
    app.include_router(verse_routes.router)
    app.state.verse_host = host
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    srv = uvicorn.Server(config)
    task = asyncio.ensure_future(srv.serve())
    for _ in range(100):
        if srv.started:
            break
        await asyncio.sleep(0.02)
    yield host, f"ws://127.0.0.1:{port}{P.PATH}"
    srv.should_exit = True
    await asyncio.wait_for(task, 10)


async def _close_code(ws) -> int:
    try:
        while True:
            await asyncio.wait_for(ws.recv(), 10)
    except ConnectionClosed as exc:
        return exc.rcvd.code if exc.rcvd else 1006


async def test_wrong_token_closes_4401_within_100ms(server) -> None:
    _host, url = server
    async with ws_connect(url) as ws:
        started = time.perf_counter()
        await ws.send(json.dumps(hello(token="x" * 43)))
        code = await _close_code(ws)
        elapsed = time.perf_counter() - started
    assert code == 4401
    assert elapsed < 0.1, elapsed


async def test_hello_timeout_is_5s_and_closes_4400(server, monkeypatch) -> None:
    assert P.HELLO_TIMEOUT_S == 5.0
    _host, url = server
    async with ws_connect(url) as ws:
        started = time.perf_counter()
        code = await _close_code(ws)
        elapsed = time.perf_counter() - started
    assert code == 4400
    assert 4.9 <= elapsed <= 5.6, elapsed


async def test_malformed_and_unsupported_hello(server) -> None:
    _host, url = server
    async with ws_connect(url) as ws:
        await ws.send("not json")
        assert await _close_code(ws) == 4400
    async with ws_connect(url) as ws:
        await ws.send(json.dumps(hello(protocols=["verse.bridge/9"])))
        try:
            await asyncio.wait_for(ws.recv(), 5)
        except ConnectionClosed as exc:
            assert exc.rcvd.code == 4426
            assert "verse.bridge/1" in exc.rcvd.reason


async def test_second_client_replaces_first(server) -> None:
    host, url = server
    async with ws_connect(url) as first:
        await first.send(json.dumps(hello()))
        welcome = json.loads(await first.recv())
        assert welcome["type"] == "welcome" and welcome["seq"] == 1
        async with ws_connect(url) as second:
            await second.send(json.dumps(hello()))
            assert json.loads(await second.recv())["type"] == "welcome"
            assert await _close_code(first) == 4409
            await second.send(json.dumps({"type": "ping", "ts": 1.0, "data": {}}))
            pong = json.loads(await second.recv())
            assert pong["type"] == "pong" and pong["seq"] == 2


async def test_oversized_frame_closes_1009(server) -> None:
    _host, url = server
    async with ws_connect(url, max_size=None) as ws:
        await ws.send(json.dumps(hello()))
        await ws.recv()
        await ws.send("x" * (P.MAX_FRAME_BYTES + 10))
        assert await _close_code(ws) == 1009


async def test_dead_link_declared_at_5s(server) -> None:
    host, url = server
    declared: list[float] = []

    async def on_hung(_session) -> None:
        declared.append(time.perf_counter())

    host.hub.on_hung = on_hung
    async with ws_connect(url) as ws:
        await ws.send(json.dumps(hello()))
        await ws.recv()
        last = time.perf_counter()
        for _ in range(3):
            await ws.send(json.dumps({"type": "ping", "ts": 1.0, "data": {}}))
            await ws.recv()
            last = time.perf_counter()
            await asyncio.sleep(1.0)
        assert declared == []
        await asyncio.sleep(5.8 - (time.perf_counter() - last))
    assert declared, "no dead link declared"
    assert 5.0 <= declared[0] - last <= 5.5, declared[0] - last


async def test_non_loopback_peer_gets_4403(tmp_path: Path) -> None:
    from tests.unit.verse_host._support import MemoryTransport

    host, _ = make_host(tmp_path)
    for peer in ("192.168.1.20", "10.0.0.5", "testclient", None):
        t = MemoryTransport()
        t.push(hello(token=TOKEN))
        code = await host.hub.serve(t, peer)
        assert code == 4403 and t.closed_with[0] == 4403
        assert t.sent == []
    for peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        assert verse_routes_is_loopback(peer)


def verse_routes_is_loopback(peer: str) -> bool:
    from dodaios.verse_host.bridge import is_loopback

    return is_loopback(peer)


async def test_signal_route_closes_1013_until_wp20(server) -> None:
    _host, url = server
    async with ws_connect(url.replace("/bridge", "/signal")) as ws:
        assert await _close_code(ws) == 1013


def test_outbox_merges_two_queued_deltas_of_one_pane() -> None:
    from dodaios.verse_host.bridge import Outbox, _Out

    box = Outbox()

    def delta(rows: list[tuple[int, str]], cursor: list[int]) -> _Out:
        data = {
            "pane_id": "ws_91:T1",
            "kind": "delta",
            "cols": 80,
            "rows": 24,
            "cursor": cursor,
            "style": "styled",
            "rows_changed": [
                {"row": r, "runs": [{"col": 0, "text": t}] if t else []} for r, t in rows
            ],
        }
        return _Out("screens.frame", data, key="screens:ws_91:T1", delta=True, ref=1, feed=True)

    box.put(delta([(1, "a"), (2, "old")], [1, 1]))
    box.put(delta([(2, "new"), (5, "")], [5, 0]))
    assert len(box) == 1
    data = box._items[0].data
    assert [r["row"] for r in data["rows_changed"]] == [1, 2, 5]
    assert data["rows_changed"][1]["runs"][0]["text"] == "new"
    assert data["rows_changed"][2]["runs"] == []  # a cleared row survives the merge
    assert data["cursor"] == [5, 0]
