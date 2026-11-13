"""One dictation from the key press to the delivered text.

The session records, reads the recording once after the stop and delivers the
text. These tests drive it with a scripted microphone and a fake recognizer
and pin what every surface relies on: the events and their order, that no
text exists before the stop, what a recording without speech becomes, and
that the rules for pauses and spoken layout commands reach the delivered text
while the recognizer's own words stay available as the raw text.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import dodaios.speech.pipeline as pipeline_mod
from dodaios.core.config import DictationConfig
from dodaios.core.events import (
    DictationCompleted,
    DictationTranscribing,
    DictationTranscript,
)
from dodaios.speech.pipeline import SpeechPipeline

pytestmark = pytest.mark.usefixtures("speech_by_loudness")

RATE = 16_000


def _loud(seconds: float) -> bytes:
    return (np.ones(int(seconds * RATE), dtype=np.int16) * 6_000).tobytes()


def _silent(seconds: float) -> bytes:
    return np.zeros(int(seconds * RATE), dtype=np.int16).tobytes()


class _Recognizer:
    """Answers every clip with one fixed text and counts its calls."""

    name = "test-recognizer"

    def __init__(self, text: str, language: str = "de") -> None:
        self.text = text
        self.language = language
        self.calls = 0

    async def transcribe_pcm(self, pcm: bytes, language: str | None = None) -> Any:
        self.calls += 1
        return SimpleNamespace(text=self.text, language=self.language)


class _Mic:
    """Delivers a recording in one-second chunks, then stays open."""

    def __init__(self, pcm: bytes, delivered: asyncio.Event) -> None:
        self._pcm = pcm
        self._delivered = delivered

    async def __aenter__(self) -> _Mic:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def stream(self):  # noqa: ANN201 - async generator of chunks
        step = RATE * 2
        for offset in range(0, len(self._pcm), step):
            yield SimpleNamespace(pcm=self._pcm[offset : offset + step])
            await asyncio.sleep(0)
        self._delivered.set()
        await asyncio.Event().wait()


def _pipeline(recognizer: _Recognizer, cfg: DictationConfig | None = None):
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    pipe._utterance_stt = recognizer
    pipe._dictation_cfg = cfg or DictationConfig(history_enabled=False, polish=False)
    pipe._dictation_target = "chat"
    pipe._dictation_max_s = 30.0
    pipe._dictation_completion_published = False
    pipe._dictation_anchor_primed = True
    pipe._input_device = None
    pipe._input_priority = None
    pipe._dictation_stop_event = asyncio.Event()
    pipe._hangup_event = asyncio.Event()
    events: list[object] = []

    async def _publish(event: object) -> None:
        events.append(event)

    pipe._publish_event = _publish  # type: ignore[assignment]
    pipe._publish_event_soon = events.append  # type: ignore[assignment]
    return pipe, events


async def _dictate(
    monkeypatch: pytest.MonkeyPatch,
    pipe: SpeechPipeline,
    recording: bytes,
    *,
    discard: bool = False,
) -> None:
    delivered = asyncio.Event()
    monkeypatch.setattr(
        pipeline_mod, "MicrophoneCapture", lambda **_kw: _Mic(recording, delivered)
    )
    task = asyncio.create_task(pipe._dictation_session())
    await asyncio.wait_for(delivered.wait(), timeout=10.0)
    if discard:
        pipe._dictation_discard_requested = True
    pipe._dictation_stop_event.set()
    await asyncio.wait_for(task, timeout=10.0)


async def test_one_dictation_is_transcribing_then_one_text_then_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recognizer = _Recognizer("Das ist ein Test.")  # i18n-allow: German fixture
    pipe, events = _pipeline(recognizer)

    await _dictate(monkeypatch, pipe, _loud(2.0))

    kinds = [type(event).__name__ for event in events]
    assert kinds == ["DictationTranscribing", "DictationTranscript", "DictationCompleted"]
    transcript = next(e for e in events if isinstance(e, DictationTranscript))
    assert transcript.is_final is True
    assert transcript.text == "Das ist ein Test."  # i18n-allow: German fixture
    assert transcript.target == "chat"
    completed = next(e for e in events if isinstance(e, DictationCompleted))
    assert completed.outcome == "chat"
    assert completed.stt_providers == ("test-recognizer",)
    assert completed.stt_calls == 1
    assert recognizer.calls == 1


async def test_no_text_exists_while_the_microphone_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no interim transcript: the recognizer is not asked before the
    stop for a short recording, and nothing is published that a surface could
    mistake for text."""
    recognizer = _Recognizer("words")
    pipe, events = _pipeline(recognizer)
    delivered = asyncio.Event()
    monkeypatch.setattr(
        pipeline_mod, "MicrophoneCapture", lambda **_kw: _Mic(_loud(3.0), delivered)
    )

    task = asyncio.create_task(pipe._dictation_session())
    await asyncio.wait_for(delivered.wait(), timeout=10.0)
    for _ in range(20):
        await asyncio.sleep(0)

    assert recognizer.calls == 0
    assert events == []

    pipe._dictation_stop_event.set()
    await asyncio.wait_for(task, timeout=10.0)
    assert [type(e).__name__ for e in events][0] == "DictationTranscribing"


async def test_a_recording_without_speech_is_empty_and_names_the_microphone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recognizer = _Recognizer("Thank you.")
    pipe, events = _pipeline(recognizer)

    await _dictate(monkeypatch, pipe, _silent(3.0))

    assert recognizer.calls == 0, "silence was sent to the recognizer"
    completed = next(e for e in events if isinstance(e, DictationCompleted))
    assert completed.outcome == "empty"
    assert completed.text == ""
    assert completed.error is None
    assert "microphone" in completed.detail
    transcript = next(e for e in events if isinstance(e, DictationTranscript))
    assert transcript.text == ""


async def test_a_discarded_dictation_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recognizer = _Recognizer("never delivered")
    pipe, events = _pipeline(recognizer)

    await _dictate(monkeypatch, pipe, _loud(2.0), discard=True)

    assert recognizer.calls == 0
    assert not any(isinstance(e, DictationTranscribing) for e in events)
    completed = next(e for e in events if isinstance(e, DictationCompleted))
    assert completed.outcome == "cancelled"
    assert completed.text == ""


async def test_spoken_layout_and_pause_marks_are_formatted_and_the_raw_text_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heard = (
        "Erster Punkt... den wir besprechen. Neuer Absatz. "  # i18n-allow: German fixture
        "Zweiter Punkt, neue Zeile, dritter Punkt."  # i18n-allow: German fixture
    )
    recognizer = _Recognizer(heard)
    pipe, events = _pipeline(recognizer)

    await _dictate(monkeypatch, pipe, _loud(4.0))

    completed = next(e for e in events if isinstance(e, DictationCompleted))
    assert completed.text == (
        "Erster Punkt den wir besprechen.\n\n"  # i18n-allow: German fixture
        "Zweiter Punkt\nDritter Punkt."  # i18n-allow: German fixture
    )
    assert "..." not in completed.text
    assert completed.raw_text == heard


async def test_a_recording_of_exact_zeros_says_the_microphone_delivered_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact zeros are not a quiet room. The notice then points at the input
    device instead of at a voice that was too soft."""
    recognizer = _Recognizer("never asked")
    pipe, events = _pipeline(recognizer)

    await _dictate(monkeypatch, pipe, _silent(2.0))

    completed = next(e for e in events if isinstance(e, DictationCompleted))
    assert completed.outcome == "empty"
    assert completed.audio_rms == 0.0
    assert "no signal at all" in completed.detail
    assert "input device" in completed.detail
