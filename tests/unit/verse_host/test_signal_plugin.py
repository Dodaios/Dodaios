"""WP20.1 / WP20.6: ``signal.py`` against the real Pixel Streaming 2 plugin.

Opt-in (``DODAIOS_VERSE_PLUGIN_TEST=1``): it needs the built Verse editor and the GPU, so it
runs under the machine lock, for example::

    python scripts/unreal/with_lock.py --label wp20-plugin -- \\
        env DODAIOS_VERSE_PLUGIN_TEST=1 python -m pytest tests/unit/verse_host/test_signal_plugin.py

The test serves ``/api/verse/signal`` from a real uvicorn server, starts the game off screen with
the plugin pointed at it (30 fps, 8 Mbit/s cap, H.264, no STUN or relay), and plays the panel's
part with an aiortc peer: ticket, ``hello``, ``listStreamers``, ``subscribe``, the plugin's
offer, an answer, ICE. It checks that the plugin speaks the protocol ``signal.py`` implements,
that every candidate stays on this machine, that video arrives as H.264 within the start budget,
that the bitrate stays under the cap, and that closing the panel socket reaches the plugin
within 1 s. Metrics go to ``unreal/Verse/Saved/Harness/proof/WP20/plugin-signal.json``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.no_auto_web_auth,
    pytest.mark.skipif(
        os.environ.get("DODAIOS_VERSE_PLUGIN_TEST") != "1",
        reason="needs the built Verse editor and the GPU (DODAIOS_VERSE_PLUGIN_TEST=1)",
    ),
]

REPO = Path(__file__).resolve().parents[3]
UPROJECT = REPO / "unreal" / "Verse" / "Verse.uproject"
ENGINE = Path(os.environ.get("UE_ROOT", "C:/Program Files/Epic Games/UE_5.7"))
EDITOR = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
PROOF = REPO / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP20"
TOKEN = "wp20-plugin-test-token-" + "0" * 40
BOOT_TIMEOUT_S = 180.0
FIRST_FRAME_BUDGET_S = 1.5  # A20.1, counted from the subscribe once the streamer is up
STOP_BUDGET_S = 1.0  # A20.1
MAX_BITRATE_BPS = 8_000_000


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Server:
    def __init__(self, hub, port: int) -> None:
        import uvicorn
        from fastapi import FastAPI

        from dodaios.verse_host import signal as sig

        app = FastAPI()
        app.include_router(sig.build_router(lambda: hub))
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _engine_command(signal_url: str) -> list[str]:
    return [
        str(EDITOR),
        str(UPROJECT),
        "-game",
        "-d3d12",
        "-RenderOffScreen",
        "-windowed",
        "-ResX=960",
        "-ResY=600",
        "-unattended",
        "-nosound",
        "-nosplash",
        "-NoP4",
        "-log",
        f"-PixelStreamingConnectionURL={signal_url}",
        "-PixelStreamingWebRTCFps=30",
        "-PixelStreamingWebRTCMaxBitrate=8000000",
        "-PixelStreamingWebRTCStartBitrate=4000000",
        "-PixelStreamingEncoderCodec=H264",
        "-PixelStreamingWebRTCPortAllocatorFlags=DISABLE_STUN,DISABLE_RELAY",
        "-PixelStreamingWebRTCDisableReceiveAudio",
        "-PixelStreamingWebRTCDisableTransmitAudio",
    ]


async def _play_panel(port: int, hub, metrics: dict) -> None:
    import websockets
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.sdp import candidate_from_sdp

    from dodaios.verse_host import signal as sig

    policy = sig.LocalIcePolicy()
    url = f"ws://127.0.0.1:{port}{sig.SIGNAL_PATH}?role=player"
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    async with websockets.connect(url, max_size=sig.MAX_FRAME_BYTES) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol": sig.PROTOCOL,
                    "ticket": hub.mint_player_ticket(),
                    "w": 960,
                    "h": 600,
                    "dpr": 1.0,
                }
            )
        )
        seen: list[str] = []
        streamer_ids: list[str] = []
        while not streamer_ids:
            if time.monotonic() > deadline:
                raise AssertionError("the plugin never connected to /api/verse/signal")
            await ws.send(json.dumps({"type": "listStreamers"}))
            with contextlib.suppress(TimeoutError):
                while True:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                    seen.append(message["type"])
                    if message["type"] == "streamerList" and message["ids"]:
                        streamer_ids = message["ids"]
                        break
                    if message["type"] == "streamerList":
                        break
            if not streamer_ids:
                await asyncio.sleep(1)
        metrics["streamer_id"] = streamer_ids[0]
        metrics["streamer_up_s"] = round(BOOT_TIMEOUT_S - (deadline - time.monotonic()), 2)

        pc = RTCPeerConnection()
        first_frame = asyncio.get_running_loop().create_future()
        frames = {"n": 0}

        @pc.on("track")
        def on_track(track) -> None:
            async def pull() -> None:
                while True:
                    try:
                        await track.recv()
                    except Exception:  # noqa: BLE001 - track ended
                        return
                    frames["n"] += 1
                    if not first_frame.done():
                        first_frame.set_result(time.monotonic())

            asyncio.ensure_future(pull())

        subscribed_at = time.monotonic()
        await ws.send(json.dumps({"type": "subscribe", "streamerId": streamer_ids[0]}))
        offer_sdp = ""
        remote_candidates = 0
        while not first_frame.done():
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
            except TimeoutError:
                if time.monotonic() - subscribed_at > 20:
                    raise AssertionError(f"no video after 20 s; signalling saw {seen}") from None
                continue
            seen.append(message["type"])
            if message["type"] == "offer":
                offer_sdp = message["sdp"]
                await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type="offer"))
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                await ws.send(json.dumps({"type": "answer", "sdp": pc.localDescription.sdp}))
            elif message["type"] == "iceCandidate":
                line = message["candidate"].get("candidate", "")
                if line:
                    remote_candidates += 1
                    assert policy.allows(line, from_player=False), line
                    cand = candidate_from_sdp(line.split(":", 1)[1])
                    cand.sdpMid = message["candidate"].get("sdpMid")
                    cand.sdpMLineIndex = message["candidate"].get("sdpMLineIndex")
                    await pc.addIceCandidate(cand)
        first_at = first_frame.result()
        metrics["first_frame_after_subscribe_s"] = round(first_at - subscribed_at, 3)
        metrics["offer_has_h264"] = "H264" in offer_sdp
        metrics["offer_has_data_channel"] = "m=application" in offer_sdp
        metrics["offer_candidates_kept"] = sum(
            1 for line in offer_sdp.splitlines() if line.startswith("a=candidate:")
        )
        metrics["trickled_candidates"] = remote_candidates
        metrics["signalling_types_seen"] = sorted(set(seen))

        # Measure for 5 s.
        start_bytes = await _bytes_received(pc)
        start_frames = frames["n"]
        t0 = time.monotonic()
        await asyncio.sleep(5)
        elapsed = time.monotonic() - t0
        metrics["fps"] = round((frames["n"] - start_frames) / elapsed, 1)
        metrics["bitrate_bps"] = int((await _bytes_received(pc) - start_bytes) * 8 / elapsed)
        metrics["codec"] = _negotiated_codec(pc.localDescription.sdp)

        closed_at = time.monotonic()
        metrics["_closed_at"] = closed_at
        await ws.close()
    metrics["socket_close_s"] = round(time.monotonic() - closed_at, 3)
    await pc.close()


async def _bytes_received(pc) -> int:
    stats = await pc.getStats()
    return sum(
        getattr(s, "bytesReceived", 0) or 0
        for s in stats.values()
        if getattr(s, "type", "") == "inbound-rtp"
    )


def _negotiated_codec(answer_sdp: str) -> str:
    """The first video payload of the answer, as ``H264/90000``."""
    lines = answer_sdp.splitlines()
    video = next((line for line in lines if line.startswith("m=video")), "")
    payloads = video.split()[3:]
    for payload in payloads:
        for line in lines:
            if line.startswith(f"a=rtpmap:{payload} "):
                return line.split(" ", 1)[1]
    return ""


def test_signal_against_the_plugin():
    from dodaios.verse_host import signal as sig

    assert EDITOR.exists(), f"Unreal editor not found at {EDITOR}"
    assert os.environ.get("DODAIOS_GPU_LOCK_HELD"), "run under scripts/unreal/with_lock.py"
    port = _free_port()
    stops: list[float] = []
    hub = sig.SignalHub(lambda: TOKEN)
    original_unsubscribe = hub._unsubscribe

    async def timed_unsubscribe(peer):
        await original_unsubscribe(peer)
        stops.append(time.monotonic())

    hub._unsubscribe = timed_unsubscribe  # type: ignore[method-assign]
    signal_url = (
        f"ws://127.0.0.1:{port}{sig.SIGNAL_PATH}?role=streamer&key={sig.derive_streamer_key(TOKEN)}"
    )
    PROOF.mkdir(parents=True, exist_ok=True)
    metrics: dict = {"render": "960x600", "fps_cap": 30, "max_bitrate_bps": MAX_BITRATE_BPS}
    log_path = PROOF / "plugin-signal-engine.log"
    with _Server(hub, port), open(log_path, "wb") as log:
        engine = subprocess.Popen(_engine_command(signal_url), stdout=log, stderr=subprocess.STDOUT)
        try:
            started = time.monotonic()
            asyncio.run(_play_panel(port, hub, metrics))
            closed_at = metrics.pop("_closed_at", None)
            metrics["playerDisconnected_sent"] = bool(stops)
            if stops and closed_at is not None:
                metrics["stop_to_plugin_s"] = round(stops[-1] - closed_at, 3)
            metrics["run_s"] = round(time.monotonic() - started, 1)
        finally:
            engine.terminate()
            try:
                engine.wait(timeout=30)
            except subprocess.TimeoutExpired:
                engine.kill()
    (PROOF / "plugin-signal.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert TOKEN not in text, "launch token leaked into the engine log"
    assert metrics["offer_has_h264"], metrics
    assert metrics["offer_has_data_channel"], metrics
    assert metrics["first_frame_after_subscribe_s"] <= FIRST_FRAME_BUDGET_S, metrics
    assert metrics["bitrate_bps"] <= MAX_BITRATE_BPS * 1.1, metrics
    assert metrics["playerDisconnected_sent"], metrics
    assert metrics["socket_close_s"] <= STOP_BUDGET_S, metrics
    assert metrics.get("stop_to_plugin_s", 99) <= STOP_BUDGET_S, metrics
    assert metrics["codec"].upper().startswith("H264"), metrics
