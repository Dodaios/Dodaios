"""WP20.1: the backend Pixel Streaming 2 signalling (``dodaios/verse_host/signal.py``)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dodaios.verse_host import signal as sig

# A bare FastAPI app: the app-session boundary is not under test here.
pytestmark = pytest.mark.no_auto_web_auth

TOKEN = "t" * 64
LOOPBACK = ("127.0.0.1", 50123)
LAN_IP = "192.168.7.20"
ENGINE_SIGNALLING = Path(
    "C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Media/PixelStreaming2/Source/"
    "PixelStreaming2Servers/Private/SignallingServer.cpp"
)

OFFER_SDP = "\r\n".join(
    [
        "v=0",
        "o=- 1 2 IN IP4 127.0.0.1",
        "m=video 9 UDP/TLS/RTP/SAVPF 96",
        "a=candidate:1 1 udp 2122260223 127.0.0.1 50000 typ host generation 0",
        f"a=candidate:2 1 udp 2122194687 {LAN_IP} 50001 typ host generation 0",
        "a=candidate:3 1 udp 1686052607 203.0.113.9 50002 typ srflx raddr 0.0.0.0 rport 0",
        "a=candidate:4 1 udp 41885439 198.51.100.4 3478 typ relay raddr 0.0.0.0 rport 0",
        "a=candidate:5 1 udp 2122129151 10.99.0.4 50003 typ host generation 0",
        "",
    ]
)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, kind: str, data: dict) -> None:
        self.calls.append((kind, data))


def make_client(hub_box: dict, peer=LOOPBACK) -> TestClient:
    app = FastAPI()
    app.include_router(sig.build_router(lambda: hub_box.get("hub")))
    return TestClient(app, client=peer)


@pytest.fixture
def setup():
    panel = Recorder()
    hub = sig.SignalHub(
        lambda: TOKEN,
        on_panel=panel,
        ice_policy=sig.LocalIcePolicy(["127.0.0.1", "::1", LAN_IP]),
        hello_timeout=0.5,
    )
    box = {"hub": hub}
    return hub, panel, make_client(box), box


def streamer_url(key: str | None = None) -> str:
    return f"{sig.SIGNAL_PATH}?role=streamer&key={key or sig.derive_streamer_key(TOKEN)}"


def player_url() -> str:
    return f"{sig.SIGNAL_PATH}?role=player"


def recv(ws) -> dict:
    return json.loads(ws.receive_text())


def ticket(client: TestClient) -> str:
    res = client.post(sig.TICKET_PATH)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["path"] == sig.SIGNAL_PATH and body["protocol"] == sig.PROTOCOL
    return body["ticket"]


def hello(client: TestClient, **geometry) -> dict:
    data = {"w": 480, "h": 320, "dpr": 1.5}
    data.update(geometry)
    return {"type": "hello", "protocol": sig.PROTOCOL, "ticket": ticket(client), **data}


def ice(line: str) -> dict:
    return {"candidate": line, "sdpMid": "0", "sdpMLineIndex": 0}


def close_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as info:
        ws.receive_text()
    return info.value.code


def open_streamer(client: TestClient):
    """Connect like the plugin does: read ``config`` and ``identify``, answer ``endpointId``."""
    ws = client.websocket_connect(streamer_url())
    s = ws.__enter__()
    config = recv(s)
    assert config == {"type": "config", "peerConnectionOptions": {"iceServers": []}}
    assert recv(s) == {"type": "identify"}
    s.send_text(json.dumps({"type": "endpointId", "id": "Verse"}))
    return ws, s


def open_player(client: TestClient, **geometry):
    ws = client.websocket_connect(player_url())
    p = ws.__enter__()
    p.send_text(json.dumps(hello(client, **geometry)))
    assert recv(p) == {"type": "config", "peerConnectionOptions": {"iceServers": []}}
    state = recv(p)
    assert state["type"] == "verse.streamState"
    return ws, p


# -- token and peer rules ------------------------------------------------------


def test_streamer_key_is_derived_and_not_the_token():
    key = sig.derive_streamer_key(TOKEN)
    assert key != TOKEN and TOKEN not in key and len(key) == 64
    assert key == sig.derive_streamer_key(TOKEN)
    assert key != sig.derive_streamer_key("u" * 64)


def test_wrong_streamer_key_closes_4401(setup):
    _, _, client, _ = setup
    with client.websocket_connect(streamer_url("0" * 64)) as ws:
        assert close_code(ws) == sig.CLOSE_TOKEN


def test_missing_streamer_key_closes_4400(setup):
    _, _, client, _ = setup
    with client.websocket_connect(f"{sig.SIGNAL_PATH}?role=streamer") as ws:
        assert close_code(ws) == sig.CLOSE_BAD_HELLO


def test_unknown_role_closes_4400(setup):
    _, _, client, _ = setup
    with client.websocket_connect(f"{sig.SIGNAL_PATH}?role=viewer") as ws:
        assert close_code(ws) == sig.CLOSE_BAD_HELLO


def test_non_loopback_peer_closes_4403():
    hub = sig.SignalHub(lambda: TOKEN, ice_policy=sig.LocalIcePolicy([]))
    client = make_client({"hub": hub}, peer=("192.168.7.30", 50000))
    with client.websocket_connect(streamer_url()) as ws:
        assert close_code(ws) == sig.CLOSE_PEER
    assert client.post(sig.TICKET_PATH).status_code == 403


def test_no_launch_closes_1013_and_ticket_is_503():
    client = make_client({})
    with client.websocket_connect(streamer_url()) as ws:
        assert close_code(ws) == sig.CLOSE_TRY_AGAIN
    assert client.post(sig.TICKET_PATH).status_code == 503


def test_launch_without_token_closes_1013():
    hub = sig.SignalHub(lambda: None, ice_policy=sig.LocalIcePolicy([]))
    client = make_client({"hub": hub})
    with client.websocket_connect(streamer_url()) as ws:
        assert close_code(ws) == sig.CLOSE_TRY_AGAIN


def test_player_without_hello_closes_4400(setup):
    _, _, client, _ = setup
    with client.websocket_connect(player_url()) as ws:
        assert close_code(ws) == sig.CLOSE_BAD_HELLO


def test_player_other_first_frame_closes_4400(setup):
    _, _, client, _ = setup
    with client.websocket_connect(player_url()) as ws:
        ws.send_text(json.dumps({"type": "listStreamers"}))
        assert close_code(ws) == sig.CLOSE_BAD_HELLO


def test_player_wrong_protocol_closes_4426(setup):
    _, _, client, _ = setup
    with client.websocket_connect(player_url()) as ws:
        frame = hello(client)
        frame["protocol"] = "verse.signal/9"
        ws.send_text(json.dumps(frame))
        assert close_code(ws) == sig.CLOSE_PROTOCOL


def test_player_bad_ticket_closes_4401(setup):
    _, _, client, _ = setup
    with client.websocket_connect(player_url()) as ws:
        frame = hello(client)
        frame["ticket"] = "forged"
        ws.send_text(json.dumps(frame))
        assert close_code(ws) == sig.CLOSE_TOKEN


def test_ticket_is_single_use(setup):
    _, _, client, _ = setup
    frame = hello(client)
    with client.websocket_connect(player_url()) as ws:
        ws.send_text(json.dumps(frame))
        assert recv(ws)["type"] == "config"
    with client.websocket_connect(player_url()) as ws:
        ws.send_text(json.dumps(frame))
        assert close_code(ws) == sig.CLOSE_TOKEN


def test_ticket_expires():
    now = [100.0]
    hub = sig.SignalHub(lambda: TOKEN, ice_policy=sig.LocalIcePolicy([]), clock=lambda: now[0])
    client = make_client({"hub": hub})
    frame = hello(client)
    now[0] += sig.TICKET_TTL_S + 1
    with client.websocket_connect(player_url()) as ws:
        ws.send_text(json.dumps(frame))
        assert close_code(ws) == sig.CLOSE_TOKEN


def test_player_hello_needs_panel_size(setup):
    _, _, client, _ = setup
    with client.websocket_connect(player_url()) as ws:
        ws.send_text(json.dumps(hello(client, w=0)))
        assert close_code(ws) == sig.CLOSE_BAD_HELLO


def test_oversized_frame_closes_1009(setup):
    _, _, client, _ = setup
    ws_cm, s = open_streamer(client)
    s.send_text(json.dumps({"type": "ping", "pad": "x" * (sig.MAX_FRAME_BYTES + 1)}))
    assert close_code(s) == sig.CLOSE_TOO_BIG
    ws_cm.__exit__(None, None, None)


def test_second_streamer_replaces_first(setup):
    hub, _, client, _ = setup
    first_cm, first = open_streamer(client)
    second_cm, _second = open_streamer(client)
    assert close_code(first) == sig.CLOSE_REPLACED
    assert hub.streamer_connected
    second_cm.__exit__(None, None, None)
    first_cm.__exit__(None, None, None)


def test_second_player_replaces_first(setup):
    hub, _, client, _ = setup
    first_cm, first = open_player(client)
    second_cm, _second = open_player(client)
    assert close_code(first) == sig.CLOSE_REPLACED
    assert hub.player_connected
    second_cm.__exit__(None, None, None)
    first_cm.__exit__(None, None, None)


# -- the reference protocol (the plugin's streamer and the frontend's player) ---


def test_full_session_follows_the_reference_protocol(setup):
    hub, panel, client, _ = setup
    s_cm, s = open_streamer(client)
    p_cm, p = open_player(client)
    assert panel.calls[-1] == (
        "panel.visibility",
        {"visible": True, "w": 480, "h": 320, "dpr": 1.5},
    )

    p.send_text(json.dumps({"type": "listStreamers"}))
    assert recv(p) == {"type": "streamerList", "ids": ["Verse"]}
    p.send_text(json.dumps({"type": "subscribe", "streamerId": "Verse"}))
    connected = recv(s)
    assert connected == {
        "type": "playerConnected",
        "playerId": "1",
        "dataChannel": True,
        "sfu": False,
        "sendOffer": True,
    }

    s.send_text(json.dumps({"type": "offer", "playerId": "1", "sdp": OFFER_SDP}))
    offer = recv(p)
    assert offer["type"] == "offer" and "playerId" not in offer
    assert "127.0.0.1 50000 typ host" in offer["sdp"]
    assert f"{LAN_IP} 50001 typ host" in offer["sdp"]
    for dropped in ("typ srflx", "typ relay", "10.99.0.4"):
        assert dropped not in offer["sdp"]
    assert offer["sdp"].endswith("\r\n")

    p.send_text(json.dumps({"type": "answer", "sdp": "v=0\r\n"}))
    assert recv(s) == {"type": "answer", "sdp": "v=0\r\n", "playerId": "1"}

    good = ice("candidate:7 1 udp 2122260223 abcd-ef.local 61000 typ host")
    bad = ice("candidate:8 1 udp 1686052607 203.0.113.9 61001 typ srflx raddr 0.0.0.0 rport 0")
    p.send_text(json.dumps({"type": "iceCandidate", "candidate": bad}))
    p.send_text(json.dumps({"type": "iceCandidate", "candidate": good}))
    assert recv(s) == {"type": "iceCandidate", "candidate": good, "playerId": "1"}

    relay = ice("candidate:9 1 udp 1 198.51.100.4 3478 typ relay raddr 0.0.0.0 rport 0")
    s.send_text(json.dumps({"type": "iceCandidate", "playerId": "1", "candidate": relay}))
    loop_c = ice("candidate:10 1 udp 2122260223 127.0.0.1 50010 typ host")
    s.send_text(json.dumps({"type": "iceCandidate", "playerId": "1", "candidate": loop_c}))
    assert recv(p) == {"type": "iceCandidate", "candidate": loop_c}

    p.send_text(json.dumps({"type": "ping", "time": 1}))
    assert recv(p)["type"] == "pong"
    s.send_text(json.dumps({"type": "ping", "time": 1}))
    assert recv(s)["type"] == "pong"

    p.send_text(json.dumps({"type": "panel.resize", "w": 560, "h": 360, "dpr": 2.0}))
    p.send_text(json.dumps({"type": "panel.resize", "w": 560, "h": 360, "dpr": 2.0}))
    p.send_text(json.dumps({"type": "ping", "time": 2}))
    assert recv(p)["type"] == "pong"  # ordering barrier
    assert panel.calls.count(("panel.resize", {"w": 560, "h": 360, "dpr": 2.0})) == 1

    p_cm.__exit__(None, None, None)
    assert recv(s) == {"type": "playerDisconnected", "playerId": "1"}
    assert panel.calls[-1] == ("panel.visibility", {"visible": False, "w": 0, "h": 0, "dpr": 2.0})
    assert not hub.player_connected
    s_cm.__exit__(None, None, None)


def test_player_before_streamer_is_connected_on_endpoint_id(setup):
    _, _, client, _ = setup
    p_cm, p = open_player(client)
    p.send_text(json.dumps({"type": "listStreamers"}))
    assert recv(p) == {"type": "streamerList", "ids": []}
    s_cm, s = open_streamer(client)
    assert recv(s)["type"] == "playerConnected"
    p_cm.__exit__(None, None, None)
    s_cm.__exit__(None, None, None)


def test_streamer_disconnect_player_closes_it(setup):
    _, _, client, _ = setup
    s_cm, s = open_streamer(client)
    p_cm, p = open_player(client)
    p.send_text(json.dumps({"type": "subscribe", "streamerId": "Verse"}))
    assert recv(s)["type"] == "playerConnected"
    s.send_text(json.dumps({"type": "disconnectPlayer", "playerId": "1", "reason": "x"}))
    assert close_code(p) == 1000
    p_cm.__exit__(None, None, None)
    s_cm.__exit__(None, None, None)


def test_unlisted_types_never_cross(setup):
    _, _, client, _ = setup
    s_cm, s = open_streamer(client)
    p_cm, p = open_player(client)
    p.send_text(json.dumps({"type": "subscribe", "streamerId": "Verse"}))
    assert recv(s)["type"] == "playerConnected"
    p.send_text(json.dumps({"type": "stats", "data": {"x": 1}}))
    p.send_text(json.dumps({"type": "dataChannelRequest"}))
    s.send_text(json.dumps({"type": "playerCount", "count": 9, "playerId": "1"}))
    s.send_text(json.dumps({"type": "offer", "playerId": "2", "sdp": "v=0\r\n"}))  # unknown player
    p.send_text(json.dumps({"type": "ping", "time": 3}))
    assert recv(p)["type"] == "pong"
    s.send_text(json.dumps({"type": "ping", "time": 3}))
    assert recv(s)["type"] == "pong"
    p_cm.__exit__(None, None, None)
    s_cm.__exit__(None, None, None)


def test_stream_state_reaches_the_player(setup):
    hub, _, client, _ = setup
    p_cm, p = open_player(client)
    # Run on the socket's own event loop, as the verse host's bridge would.
    p.portal.call(hub.publish_stream_state, {"state": "stopped", "error": "full_view_open"})
    assert recv(p) == {"type": "verse.streamState", "state": "stopped", "error": "full_view_open"}
    p.portal.call(hub.publish_stream_state, {"state": "bogus"})
    assert recv(p) == {"type": "verse.streamState", "state": "failed"}
    p_cm.__exit__(None, None, None)


# -- ICE policy ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "from_player", "ok"),
    [
        ("candidate:1 1 udp 1 127.0.0.1 5000 typ host", False, True),
        ("a=candidate:1 1 udp 1 ::1 5000 typ host", False, True),
        (f"candidate:1 1 tcp 1 {LAN_IP} 9 typ host tcptype active", False, True),
        ("candidate:1 1 udp 1 10.1.1.1 5000 typ host", False, False),
        ("candidate:1 1 udp 1 abc.local 5000 typ host", True, True),
        ("candidate:1 1 udp 1 abc.local 5000 typ host", False, False),
        ("candidate:1 1 udp 1 127.0.0.1 5000 typ srflx raddr 0.0.0.0 rport 0", False, False),
        ("candidate:1 1 udp 1 127.0.0.1 5000 typ relay", True, False),
        ("candidate:1 1 udp 1 127.0.0.1 5000 typ prflx", True, False),
        ("candidate:1 1 sctp 1 127.0.0.1 5000 typ host", False, False),
        ("candidate:1 1 udp 1 127.0.0.1 0 typ host", False, False),
        ("candidate:garbage", False, False),
        ("", False, False),
    ],
)
def test_ice_policy(line, from_player, ok):
    policy = sig.LocalIcePolicy(["127.0.0.1", "::1", LAN_IP])
    assert policy.allows(line, from_player=from_player) is ok


def test_machine_addresses_always_hold_loopback():
    found = sig.machine_addresses()
    assert {"127.0.0.1", "::1"} <= found


def test_loopback_host_check():
    assert sig.is_loopback_host("127.0.0.1")
    assert sig.is_loopback_host("127.8.9.1")
    assert sig.is_loopback_host("::1")
    assert sig.is_loopback_host("::ffff:127.0.0.1")
    assert sig.is_loopback_host("localhost")
    assert not sig.is_loopback_host("192.168.1.2")
    assert not sig.is_loopback_host("testclient")
    assert not sig.is_loopback_host(None)


# -- contract with the engine's own signalling server -----------------------------


def _engine_handlers() -> tuple[set[str], set[str]]:
    text = ENGINE_SIGNALLING.read_text(encoding="utf-8", errors="replace")
    streamer = set(re.findall(r'StreamerMessageHandlers\.Add\("([A-Za-z]+)"\)', text))
    player = set(re.findall(r'PlayerMessageHandlers\.Add\("([A-Za-z]+)"\)', text))
    return streamer, player


@pytest.mark.skipif(not ENGINE_SIGNALLING.exists(), reason="Unreal Engine 5.7 not installed")
def test_handles_every_message_the_engine_reference_server_handles():
    """Protocol drift guard (risk RK9): the plugin's own server is the reference."""
    streamer, player = _engine_handlers()
    assert streamer, "engine source changed shape"
    source = Path(sig.__file__).read_text(encoding="utf-8")
    for kind in streamer | (player - {"stats"}):
        assert f'"{kind}"' in source, f"engine message {kind} not handled"
    text = ENGINE_SIGNALLING.read_text(encoding="utf-8", errors="replace")
    for field_name in ("playerId", "dataChannel", "sfu", "sendOffer", "streamerId", "iceServers"):
        assert f'"{field_name}"' in text or f'TEXT("{field_name}")' in text
        assert f'"{field_name}"' in source


# -- lifecycle and timing (WP20.6) ------------------------------------------------


def test_hidden_panel_reaches_streamer_and_bridge_within_one_second(setup):
    """A20.1, backend half: the panel socket closing stops the stream path at once."""
    import time

    _, panel, client, _ = setup
    s_cm, s = open_streamer(client)
    p_cm, p = open_player(client)
    p.send_text(json.dumps({"type": "subscribe", "streamerId": "Verse"}))
    assert recv(s)["type"] == "playerConnected"
    started = time.perf_counter()
    p_cm.__exit__(None, None, None)
    assert recv(s) == {"type": "playerDisconnected", "playerId": "1"}
    elapsed = time.perf_counter() - started
    assert panel.calls[-1][0] == "panel.visibility" and panel.calls[-1][1]["visible"] is False
    assert elapsed < 1.0, elapsed
    s_cm.__exit__(None, None, None)


def test_full_view_round_trip_resubscribes(setup):
    """WP20.5: stopped (full view) ends the peer; the next start subscribes again."""
    hub, _, client, _ = setup
    s_cm, s = open_streamer(client)
    p_cm, p = open_player(client)
    p.send_text(json.dumps({"type": "subscribe", "streamerId": "Verse"}))
    assert recv(s)["type"] == "playerConnected"
    p.portal.call(hub.publish_stream_state, {"state": "stopped", "error": "full_view_open"})
    assert recv(p) == {"type": "verse.streamState", "state": "stopped", "error": "full_view_open"}
    p.portal.call(hub.publish_stream_state, {"state": "starting"})
    assert recv(p) == {"type": "verse.streamState", "state": "starting"}
    p.send_text(json.dumps({"type": "subscribe", "streamerId": ""}))
    assert recv(s)["type"] == "playerConnected"
    p_cm.__exit__(None, None, None)
    s_cm.__exit__(None, None, None)


def test_no_token_or_key_in_logs(setup, caplog):
    """The streamer key and tickets never reach a log line (A17.5 spirit for the signal path)."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lines.append, level="DEBUG")
    try:
        hub, _, client, _ = setup
        s_cm, s = open_streamer(client)
        p_cm, p = open_player(client)
        p.send_text(json.dumps({"type": "bogus"}))
        s.send_text(json.dumps({"type": "bogus"}))
        p.send_text(json.dumps({"type": "ping", "time": 1}))
        assert recv(p)["type"] == "pong"
        p_cm.__exit__(None, None, None)
        s_cm.__exit__(None, None, None)
    finally:
        logger.remove(sink)
    text = "\n".join(lines)
    assert TOKEN not in text
    assert sig.derive_streamer_key(TOKEN) not in text
