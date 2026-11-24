"""``[trigger] session_idle_timeout_s``: the configured idle window.

User mandate 2026-06-30: a call stays active until a MANUAL hangup when the
idle timeout is disabled. Any value <= 0 disables it; the pipeline keeps a
sane positive window internally and records the effective value (0 when
disabled) in the call's termination snapshot.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.protocols import AudioChunk
from dodaios.speech.pipeline import SpeechPipeline


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


def _pipeline(idle_timeout_s: float) -> SpeechPipeline:
    return SpeechPipeline(
        tts=FakeTTS(),
        bus=EventBus(),
        enable_whisper_wake=False,
        idle_timeout_s=idle_timeout_s,
    )


# ---------------------------------------------------------------------------
# Config schema default + constructor flag
# ---------------------------------------------------------------------------


def test_trigger_config_session_idle_timeout_default() -> None:
    # Downloaders keep the safe 30 s auto-hangup; only an explicit 0 disables it.
    from dodaios.core.config import TriggerConfig

    assert TriggerConfig().session_idle_timeout_s == 30.0


@pytest.mark.parametrize(
    "value,enabled",
    [(30.0, True), (0.0, False), (-1.0, False)],
)
def test_idle_hangup_enabled_flag(value: float, enabled: bool) -> None:
    pipe = _pipeline(value)
    assert pipe._idle_hangup_enabled is enabled
