"""Issue #828: states in which a saved GPT-Live setup could not start a call."""

from __future__ import annotations

import asyncio
import time
import tomllib
from array import array
from types import SimpleNamespace

import pytest

from dodaios.core import config_writer
from dodaios.core.bus import EventBus
from dodaios.core.protocols import AudioChunk
from dodaios.live import recovery, runtime, startup
from dodaios.live.config import LiveConfig
from dodaios.live.session import LiveVoiceSession
from dodaios.live.state import LiveLedger
from dodaios.live.tools import LiveTools
from tests.contract.test_gpt_live import Gateway
from tests.contract.test_live_reconnection import Wire

_CLASSIC_PROFILE = (
    '[brain.realtime]\nprovider = ""\n'
    '[voice]\nmode = "pipeline"\nprofile = "codex-subscription-voice"\n'
)


@pytest.fixture
def quiet_baseline(monkeypatch):
    monkeypatch.setattr(config_writer, "_update_config_soll_section", lambda *a: None)  # i18n-allow


def test_saving_gpt_live_retires_a_leftover_classic_voice_profile(tmp_path, quiet_baseline):
    path = tmp_path / "jarvis.toml"
    path.write_text(_CLASSIC_PROFILE, encoding="utf-8")

    profile = LiveConfig(
        configured=True,
        auth_mode="chatgpt_subscription",
        subscription_backend_model="chosen-model",
    )
    config_writer.set_live_profile(profile.model_dump(), path=path)

    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["voice"] == {"mode": "realtime", "profile": ""}
    assert saved["brain"]["realtime"]["provider"] == "openai-live-subscription"


def _blocked_config(tmp_path, *, mode="realtime", provider="openai-live", configured=True):
    path = tmp_path / "jarvis.toml"
    live = LiveConfig(configured=configured, backend_model="chosen-model").model_dump()
    lines = [f'[brain.realtime]\nprovider = "{provider}"\n']
    lines.append(f'[voice]\nmode = "{mode}"\nprofile = "codex-subscription-voice"\n')
    lines.append("[live]\n")
    for key, value in live.items():
        rendered = str(value).lower() if isinstance(value, bool) else f'"{value}"'
        lines.append(f"{key} = {rendered}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_boot_repairs_a_gpt_live_setup_that_a_classic_profile_blocks(tmp_path):
    path = _blocked_config(tmp_path)
    assert config_writer.retire_voice_profile_under_live(path=path) is True
    saved = tomllib.loads(path.read_text(encoding="utf-8"))
    assert saved["voice"] == {"mode": "realtime", "profile": ""}
    assert saved["live"]["backend_model"] == "chosen-model"
    # Repaired once; a second boot has nothing left to change.
    assert config_writer.retire_voice_profile_under_live(path=path) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "pipeline"},  # the classic profile is the selected engine
        {"provider": "gemini-live"},  # another realtime provider owns the choice
        {"configured": False},  # GPT-Live was never saved
    ],
)
def test_boot_repair_leaves_every_other_voice_selection_alone(tmp_path, changes):
    path = _blocked_config(tmp_path, **changes)
    before = path.read_text(encoding="utf-8")
    assert config_writer.retire_voice_profile_under_live(path=path) is False
    assert path.read_text(encoding="utf-8") == before


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
