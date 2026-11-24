"""Pin the hang-up-during-TTS abort contract of ``_speak``.

Live bug 2026-06-01 ("Jarvis shows SPEAKING the whole time even though it is
not speaking"): playback that never finishes kept ``await asyncio.wait({
play_task, barge_task})`` waiting forever, because it did not watch the hangup
event. The user pressed hangup repeatedly with no effect and the voice state
stayed wedged on SPEAKING.

``_speak`` still voices every spoken notice and announcement outside a call
(the "voice unavailable" notice included), so it must stop the player and
return the instant the user hangs up.

The fakes record causality, not wall-clock timing, so the assertions are
deterministic without any real audio device or network.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.protocols import AudioChunk
from dodaios.speech.pipeline import SpeechPipeline


@dataclass
class _SingleSentenceTTS:
    name: str = "single-sentence-tts"
    supports_streaming: bool = True

    async def synthesize(
        self, text: str, voice: str | None = None,
        language_code: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        yield AudioChunk(
            pcm=text.encode("utf-8"),
            sample_rate=24_000,
            timestamp_ns=0,
            channels=1,
        )


@dataclass
class _NeverEndingPlayer:
    """Player fake that begins playback and then blocks forever, so
    ``play_task`` never completes on its own."""

    consumed: list[str] = field(default_factory=list)
    stop_calls: int = 0
    play_started: asyncio.Event = field(default_factory=asyncio.Event)
    _first_seen: bool = False

    async def play_chunks(self, chunks: AsyncIterator[AudioChunk]) -> None:
        async for chunk in chunks:
            self.consumed.append(chunk.pcm.decode("utf-8"))
            if not self._first_seen:
                self._first_seen = True
                self.play_started.set()
                await asyncio.sleep(3600)  # held until the turn is cancelled

    def stop(self) -> None:
        self.stop_calls += 1


def _make_pipeline(tts, player) -> SpeechPipeline:
    bus = EventBus()
    pipeline = SpeechPipeline(tts=tts, bus=bus, enable_whisper_wake=False)
    pipeline._player = player  # type: ignore[assignment]
    pipeline._latency_tracker = None

    async def _never_barge(**_kwargs) -> bool:
        await asyncio.sleep(3600)
        return False

    pipeline._barge_monitor = _never_barge  # type: ignore[assignment]
    return pipeline


@pytest.mark.asyncio
async def test_hangup_during_speak_aborts_the_playback() -> None:
    """``_speak`` must abort on hangup: every spoken notice goes through it.
    Pre-fix this hangs until the 120 s ceiling."""
    tts = _SingleSentenceTTS()
    player = _NeverEndingPlayer()
    pipeline = _make_pipeline(tts, player)

    turn = asyncio.create_task(pipeline._speak("Ein langer Satz.", language="de"))

    assert await asyncio.wait_for(_event(player.play_started), timeout=2.0)
    pipeline._hangup_event.set()

    barged = await asyncio.wait_for(turn, timeout=2.0)

    assert player.stop_calls >= 1, "hangup must silence the player"
    assert barged is True, "an aborted turn must not suppress session input"


async def _event(evt: asyncio.Event) -> bool:
    await evt.wait()
    return True
