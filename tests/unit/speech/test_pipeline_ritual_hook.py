"""The pipeline's hook for rituals: a ritual's phrase is answered without a model turn."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator

import pytest

from dodaios.core.bus import EventBus
from dodaios.rituals import said as ritual_said
from dodaios.speech.pipeline import SpeechPipeline


class FakeTTS:
    """Minimal TTS fake: keeps pipeline init from crashing."""

    name = "fake-tts"
    supports_streaming = False

    async def synthesize(  # type: ignore[no-untyped-def]
        self, text: str, language_code=None
    ) -> AsyncIterator[bytes]:  # pragma: no cover - not called in these tests
        if False:
            yield b""


class FakeBrain:
    """A brain that only keeps its history, like the one the spoken brief seeds."""

    def __init__(self) -> None:
        self._history: list[tuple[str, str]] = [("user", "earlier"), ("assistant", "answer")]
        self.called = False

    async def __call__(self, text: str) -> str:  # pragma: no cover - must not be reached
        self.called = True
        return "ok"

    def seed_history(self, turns: list[tuple[str, str]]) -> None:
        self._history = list(turns)


@pytest.fixture
def pipeline():
    brain = FakeBrain()
    built = SpeechPipeline(
        tts=FakeTTS(), bus=EventBus(), brain_callback=brain, enable_whisper_wake=False
    )
    spoken: list[tuple[str, str | None, str]] = []

    async def fake_speak(text: str, language: str | None = None, *, kind: str = "reply") -> bool:
        spoken.append((text, language, kind))
        return False

    built._speak = fake_speak  # type: ignore[method-assign]
    built._brain = brain
    return built, brain, spoken


async def test_a_rituals_phrase_is_said_and_no_model_turn_follows(
    pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, brain, spoken = pipeline
    asked: list[tuple[str, str | None]] = []

    async def answer(text: str, *, language: str | None = None, **_: object) -> str | None:
        asked.append((text, language))
        return "Good morning. One thing today."

    monkeypatch.setattr(ritual_said, "spoken_answer", answer)
    assert await built._maybe_ritual("Hey Nova, good morning", "en") is True
    assert asked == [("Hey Nova, good morning", "en")]
    assert spoken == [("Good morning. One thing today.", "en", "reply")]
    assert brain.called is False
    # A follow-up finds what was said in the brain's history.
    assert brain._history[-2:] == [
        ("user", "Hey Nova, good morning"),
        ("assistant", "Good morning. One thing today."),
    ]
    assert brain._history[0] == ("user", "earlier")


async def test_an_ordinary_sentence_goes_on_to_the_brain(
    pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, brain, spoken = pipeline

    async def nothing(text: str, **_: object) -> str | None:
        return None

    monkeypatch.setattr(ritual_said, "spoken_answer", nothing)
    assert await built._maybe_ritual("What is the weather like?", "en") is False
    assert spoken == [] and len(brain._history) == 2


def test_the_hook_sits_after_the_joined_sentence_and_before_the_brain() -> None:
    """A sentence that only begins with the phrase must be joined first; and the
    brain, the privacy phrases and the skills come after a ritual."""
    source = inspect.getsource(SpeechPipeline._handle_utterance_turn)
    ritual = source.index("self._maybe_ritual(text, lang)")
    assert source.index("self._continuation_buffer.process(") < ritual
    assert source.index("self._mic_says_user_resumed()") < ritual
    assert ritual < source.index("self._match_privacy_phrase(text)")
    assert ritual < source.index("self._try_skill_direct_trigger(text, lang)")
