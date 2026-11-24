"""The moment Jarvis stops speaking is stamped as the answer floor.

Forensic 2026-06-27 08:49: a slow answer was hung up on seconds after it
landed, and nothing recorded when the floor went back to the user. The turn
state stamps that moment (SPEAKING -> LISTENING) and the call's termination
snapshot reports it, so a hangup right after an answer can be told apart from
a hangup during one.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.protocols import AudioChunk
from dodaios.speech.pipeline import SpeechPipeline, TurnTakingState


@dataclass
class FakeTTS:
    name: str = "fake-tts"
    supports_streaming: bool = True
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    async def synthesize(
        self, text: str, voice: str | None = None,
        language_code: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        self.calls.append((text, language_code))
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]


def _pipeline() -> SpeechPipeline:
    return SpeechPipeline(tts=FakeTTS(), bus=EventBus(), enable_whisper_wake=False)


@pytest.mark.asyncio
async def test_speaking_to_listening_stamps_answer_floor() -> None:
    pipe = _pipeline()
    pipe._last_answer_floor_monotonic = None
    await pipe._set_turn_state(TurnTakingState.JARVIS_SPEAKING)
    await pipe._set_turn_state(TurnTakingState.LISTENING)
    assert pipe._last_answer_floor_monotonic is not None


@pytest.mark.asyncio
async def test_other_transitions_do_not_stamp_answer_floor() -> None:
    # Going to LISTENING from a non-speaking state (e.g. session start) is not a
    # finished answer — no fresh-window grace owed.
    pipe = _pipeline()
    pipe._last_answer_floor_monotonic = None
    await pipe._set_turn_state(TurnTakingState.IDLE)
    await pipe._set_turn_state(TurnTakingState.LISTENING)
    assert pipe._last_answer_floor_monotonic is None
