"""The instant acknowledgment on the announcement path (2026-08-17).

An announcement from ``brain.instant_ack`` is one first-sign-of-life line per
user request, so the announcement path exempts it from the anti-loop cap on
spoken preambles; every other emitter stays capped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.events import AnnouncementRequested
from dodaios.core.protocols import AudioChunk
from dodaios.speech.pipeline import SpeechPipeline, TurnTakingState
from tests.fakes.voice_session import open_classic_voice_session


@dataclass
class FakeTTS:
    calls: list[tuple[str, str | None]] = field(default_factory=list)
    name: str = "fake-tts"
    supports_streaming: bool = True

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        language_code: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        self.calls.append((text, language_code))
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]


@dataclass
class FakePlayer:
    plays: int = 0

    async def play_chunks(
        self,
        chunks: AsyncIterator[AudioChunk],
        *,
        should_play=None,
    ) -> None:
        if should_play is not None and not should_play():
            async for _ in chunks:
                pass
            return
        self.plays += 1
        async for _ in chunks:
            pass

    def stop(self) -> None:
        return None


def _make_pipeline(
    tts: FakeTTS,
    bus: EventBus,
    player: FakePlayer,
    *,
    instant_ack: bool = True,
) -> SpeechPipeline:
    pipeline = SpeechPipeline(tts=tts, bus=bus, enable_whisper_wake=False)
    pipeline._player = player  # type: ignore[assignment]
    pipeline._config = SimpleNamespace(  # type: ignore[attr-defined]
        ack_brain=SimpleNamespace(
            suppress_preamble_after_interrupt_ms=5000,
            grounded_ack_commit_grace_ms=0,
            preamble_dedup_window_s=180,
            preamble_rate_limit_per_min=3,
            instant_ack=instant_ack,
        )
    )
    pipeline._brain = SimpleNamespace(_readback_composer=None)  # type: ignore[attr-defined]
    pipeline._turn_state = TurnTakingState.PROCESSING
    pipeline._brain_first_frame_played = False
    return open_classic_voice_session(pipeline)


@pytest.mark.asyncio
async def test_instant_ack_is_exempt_from_the_anti_loop_cap() -> None:
    """Four heavy commands in a minute -> four first-signs-of-life. The cap
    still applies to every other emitter."""
    bus = EventBus()
    tts = FakeTTS()
    player = FakePlayer()
    _make_pipeline(tts, bus, player)

    for i in range(5):
        await bus.publish(
            AnnouncementRequested(
                text=f"Instant line number {i}.",
                language="en",
                priority="normal",
                kind="preamble",
                source_layer="brain.instant_ack",
            )
        )
    assert player.plays == 5

    for i in range(5):
        await bus.publish(
            AnnouncementRequested(
                text=f"Other line number {i}.",
                language="en",
                priority="normal",
                kind="preamble",
                source_layer="brain.other",
            )
        )
    assert player.plays == 8, "the anti-loop cap must still bind other emitters"
