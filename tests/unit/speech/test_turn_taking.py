"""Turn-state plumbing that the realtime call and the notices still use."""

from __future__ import annotations

import asyncio

import pytest

from dodaios.core.protocols import AudioChunk
from dodaios.speech.pipeline import SpeechPipeline, TurnTakingState


class FakeTTS:
    async def synthesize(
        self,
        text: str,
        language_code: str | None = None,
    ):
        if False:  # pragma: no cover
            yield AudioChunk(pcm=b"", sample_rate=24_000, timestamp_ns=0)


class SlowPlayer:
    def __init__(self) -> None:
        self.completed = False
        self.cancelled = False
        self.stop_calls = 0

    async def play_chunks(self, _chunks) -> None:
        try:
            await asyncio.sleep(0.05)
            self.completed = True
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    def stop(self) -> None:
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_speak_does_not_cancel_playback_when_barge_monitor_returns_false() -> None:
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    player = SlowPlayer()
    pipe._tts = FakeTTS()
    pipe._player = player
    pipe._post_tts_listen_suppression_s = 0.0
    pipe._input_suppressed_until_ns = 0

    async def _barge_monitor() -> bool:
        return False

    pipe._barge_monitor = _barge_monitor  # type: ignore[method-assign]

    barged = await pipe._speak("Hallo Ruben.", language="de")

    assert barged is False
    assert player.completed is True
    assert player.cancelled is False
    assert player.stop_calls == 0


@pytest.mark.asyncio
async def test_turn_state_mapping_preserves_ui_supervisor_states() -> None:
    assert SpeechPipeline._supervisor_state_for_turn(TurnTakingState.IDLE) == "IDLE"
    assert SpeechPipeline._supervisor_state_for_turn(TurnTakingState.LISTENING) == "LISTENING"
    assert SpeechPipeline._supervisor_state_for_turn(TurnTakingState.USER_SPEAKING) == "LISTENING"
    assert (
        SpeechPipeline._supervisor_state_for_turn(
            TurnTakingState.WAITING_FOR_FINAL_TRANSCRIPT
        )
        == "LISTENING"
    )
    assert SpeechPipeline._supervisor_state_for_turn(TurnTakingState.PROCESSING) == "THINKING"
    assert (
        SpeechPipeline._supervisor_state_for_turn(TurnTakingState.JARVIS_SPEAKING)
        == "SPEAKING"
    )


def test_turn_taking_state_values_are_stable() -> None:
    # The supervisor and the UI key on these strings: never renumber/rename.
    assert TurnTakingState.IDLE.value == "IDLE"
    assert TurnTakingState.LISTENING.value == "LISTENING"
    assert TurnTakingState.USER_SPEAKING.value == "USER_SPEAKING"
    assert TurnTakingState.WAITING_FOR_FINAL_TRANSCRIPT.value == "WAITING_FOR_FINAL_TRANSCRIPT"
    assert TurnTakingState.PROCESSING.value == "PROCESSING"
    assert TurnTakingState.JARVIS_SPEAKING.value == "JARVIS_SPEAKING"
