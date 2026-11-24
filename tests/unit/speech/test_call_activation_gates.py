"""How the state loop accepts or discards a call request.

A call opens from the wake word or from a deliberate press (the call key, the
speak button). The post-hangup wake lock exists so Jarvis' own speaker tail
cannot re-trigger the wake word; a deliberate press has no echo path and must
pass it. A closed user capture gate discards every call; a closed background
gate discards only a wake-word call. The session itself is stubbed: no audio
hardware is touched.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from dodaios.sessions.constants import HANGUP_TURN_COMPLETE
from dodaios.speech.pipeline import PipelineState, SpeechPipeline

pytestmark = pytest.mark.usefixtures("granted_microphone")


class FakeTTS:
    name = "fake-tts"
    supports_streaming = False

    async def synthesize(  # type: ignore[no-untyped-def]
        self, text: str, language_code=None
    ) -> AsyncIterator[bytes]:  # pragma: no cover
        if False:
            yield b""


def _make_pipeline() -> SpeechPipeline:
    pipe = SpeechPipeline(tts=FakeTTS(), bus=None, enable_whisper_wake=False)
    pipe._state = PipelineState.IDLE
    pipe._activation_allowed = lambda: True  # type: ignore[method-assign]
    return pipe


def _silence_side_effects(pipe: SpeechPipeline) -> None:
    async def _noop_state(state):  # noqa: ANN001
        return None

    async def _noop_event(evt):  # noqa: ANN001
        return None

    pipe._set_turn_state = _noop_state  # type: ignore[method-assign]
    pipe._publish_event = _noop_event  # type: ignore[method-assign]


# ----------------------------------------------------------------------
# State-loop integration
# ----------------------------------------------------------------------

async def _pump_state_loop_once(pipe: SpeechPipeline) -> None:
    """Run the state loop just long enough to consume one call event, then
    cancel (the loop re-blocks on the next ``_call_event.wait()``)."""
    task = asyncio.create_task(pipe._state_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_wake_lock_discards_wake_word_call():
    """A WAKE-WORD call landing inside the post-hangup wake-lock is dropped:
    the lock exists precisely so Jarvis' own speaker tail cannot re-trigger
    the wake word. No explicit edge → the lock applies."""
    pipe = _make_pipeline()
    pipe._wake_lock_until = time.time() + 100.0  # lock wide open
    pipe._call_event.set()
    ran = {"session": False}

    async def fake_active_session(*, input_buffer=None):  # noqa: ANN001
        ran["session"] = True
        return HANGUP_TURN_COMPLETE

    pipe._active_session = fake_active_session  # type: ignore[method-assign]

    await _pump_state_loop_once(pipe)

    assert ran["session"] is False
    assert pipe._state == PipelineState.IDLE


def _accepting_session_stub(pipe: SpeechPipeline) -> dict[str, bool]:
    """Stub the capture + session so the state loop can ACCEPT a call without
    real audio hardware; returns the record of whether the session ran."""
    _silence_side_effects(pipe)
    pipe._player = _RecordingPlayer()  # type: ignore[assignment]
    ran = {"session": False}

    @asynccontextmanager
    async def fake_capture():
        yield None

    async def fake_active_session(*, input_buffer=None):  # noqa: ANN001
        ran["session"] = True
        return HANGUP_TURN_COMPLETE

    pipe._capture_first_session_input = fake_capture  # type: ignore[method-assign]
    pipe._active_session = fake_active_session  # type: ignore[method-assign]
    return ran


async def test_call_hotkey_bypasses_post_hangup_wake_lock():
    """A deliberate press has no speaker-echo path: what the ``_hotkey_loop``
    arms (explicit marker + call event) must survive the wake lock."""
    pipe = _make_pipeline()
    ran = _accepting_session_stub(pipe)
    pipe._wake_lock_until = time.time() + 100.0
    pipe._explicit_call_pending = True  # what _hotkey_loop sets on "call"
    pipe._call_event.set()

    await _pump_state_loop_once(pipe)

    assert ran["session"] is True, "explicit CALL press must open a session"
    assert pipe._explicit_call_pending is False, "marker is one-shot"
    assert pipe._state == PipelineState.IDLE


async def test_closed_user_capture_gate_discards_an_explicit_call():
    pipe = _make_pipeline()
    ran = _accepting_session_stub(pipe)
    pipe._user_activation_gate = lambda: False
    pipe._explicit_call_pending = True
    pipe._call_event.set()

    await _pump_state_loop_once(pipe)

    assert ran["session"] is False
    assert pipe._state == PipelineState.IDLE


async def test_closed_background_gate_discards_a_wake_call_but_not_an_explicit_one():
    """The wake word needs a live grant; a deliberate press needs only a not-refused mic."""
    wake = _make_pipeline()
    del wake._activation_allowed  # the real predicate, not the harness stub
    wake._activation_gate = lambda: False
    wake._call_event.set()
    ran = _accepting_session_stub(wake)
    await _pump_state_loop_once(wake)
    assert ran["session"] is False

    explicit = _make_pipeline()
    del explicit._activation_allowed
    explicit._activation_gate = lambda: False
    explicit._explicit_call_pending = True
    explicit._call_event.set()
    ran = _accepting_session_stub(explicit)
    await _pump_state_loop_once(explicit)
    assert ran["session"] is True


class _RecordingPlayer:
    def __init__(self) -> None:
        self.plays: list[int] = []

    async def play_pcm(self, pcm, sample_rate=None):  # noqa: ANN001
        self.plays.append(sample_rate or 0)
