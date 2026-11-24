"""Issue #828: states in which a saved GPT-Live setup could not start a call."""

from __future__ import annotations

import asyncio
import time
from array import array
from types import SimpleNamespace

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.protocols import AudioChunk
from dodaios.live import recovery, runtime, startup
from dodaios.live.session import LiveVoiceSession
from dodaios.live.state import LiveLedger
from dodaios.live.tools import LiveTools
from tests.contract.test_gpt_live import Gateway
from tests.contract.test_live_reconnection import Wire


class _WakeBuffer:
    """Thirty-one seconds of wake audio, all before the browser's first sample."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def stream(self):
        second = array("h", [0] * 16000).tobytes()
        now = time.time_ns()
        for _ in range(31):
            yield AudioChunk(pcm=second, sample_rate=16000, timestamp_ns=now - 1_000_000_000)


@pytest.mark.asyncio
async def test_wake_audio_beyond_the_buffer_no_longer_fails_the_call(monkeypatch):
    monkeypatch.setattr(startup, "_pending", {})
    source = _WakeBuffer()
    startup.offer("late-permission", source)
    # A microphone prompt answered late: the call starts without the prefix.
    assert await startup.take("late-permission", time.time() * 1000) is None
    assert source.closed


@pytest.fixture
def empty_runtime(monkeypatch):
    for name in ("_active", "_owners", "_pending_browser_starts", "_browser_call_requests"):
        monkeypatch.setattr(runtime, name, {})
    for name in ("_opening", "_watchers"):
        monkeypatch.setattr(runtime, name, set())
    monkeypatch.setattr(startup, "_pending", {})


@pytest.mark.asyncio
async def test_a_hand_over_no_window_takes_reports_a_timeout(empty_runtime):
    outcome: dict[str, str] = {}
    result = await runtime.run_browser_call(
        EventBus(), asyncio.Event(), timeout_s=0.05, outcome=outcome
    )
    assert result == "error"
    assert outcome == {"cause": "timeout"}


@pytest.mark.asyncio
async def test_a_hand_over_the_window_refused_reports_the_page(empty_runtime):
    from dodaios.core.events import BrowserVoiceRequested

    bus = EventBus()
    requests: asyncio.Queue[str] = asyncio.Queue()

    async def requested(event):
        if event.action == "start":
            requests.put_nowait(event.request_id)

    bus.subscribe(BrowserVoiceRequested, requested)
    outcome: dict[str, str] = {}
    task = asyncio.create_task(
        runtime.run_browser_call(bus, asyncio.Event(), timeout_s=45, outcome=outcome)
    )
    assert runtime.browser_startup_failed(await asyncio.wait_for(requests.get(), 1))
    assert await asyncio.wait_for(task, 1) == "error"
    assert outcome == {"cause": "page_failed"}


@pytest.mark.asyncio
async def test_a_call_that_cannot_reconnect_ends_instead_of_connecting_forever(
    tmp_path, monkeypatch
):
    import dodaios.live.session as module

    async def permit() -> None:
        return None

    monkeypatch.setattr(recovery, "connection_permit", permit)
    monkeypatch.setattr(module.random, "uniform", lambda *_args: 0)
    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(runtime, "_owners", {})

    old = Wire()
    await old.events.put(OSError("network lost"))
    messages: list[dict] = []
    ended = asyncio.Event()

    async def send(message):
        messages.append(message)
        if message.get("type") == "provider_error":
            ended.set()

    class Provider:
        name = "fake-live"
        opens = 0

        async def reattach_session(self, _previous):
            return None  # The provider no longer knows this call.

        async def open_session(self, _cfg):
            self.opens += 1
            raise OSError("still unreachable")

    provider = Provider()
    ledger = LiveLedger(tmp_path / "live.db")
    session = LiveVoiceSession(
        session_id="gone", send_json=send, send_binary=send,
        config=SimpleNamespace(brain=SimpleNamespace(reply_language="en")),
        providers=[provider],
    )
    session._connection = old
    session._ledger = ledger
    session._base_session_config = {"instructions": ""}
    session._tools = LiveTools(
        Gateway(), ledger, session.session_id, language="en", backend_model="fake"
    )
    runtime.register(session)
    session._pump_task = asyncio.create_task(session._pump())

    await asyncio.wait_for(ended.wait(), 5)
    await asyncio.wait_for(session._pump_task, 5)

    assert provider.opens == 2  # The bounded budget, not an endless loop.
    assert session.failed
    assert session not in runtime.active()
    lost = [m for m in messages if m.get("type") == "provider_error"]
    assert [m.get("message_code") for m in lost] == ["voice_connection_lost"]
