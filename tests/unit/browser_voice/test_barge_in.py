"""Barge-in and sentence continuation on the browser Pipeline voice path.

BC-250 recette 2026-10-28: the person could not interrupt Jarvis. The browser
streams the microphone while the reply plays, but no client ever sent the
``barge_in`` control frame, and an utterance that ended while a turn was
running was dropped without a trace, so the end of a sentence cut by a pause
was lost as well. The session now decides from the audio itself.
"""
from __future__ import annotations

import asyncio

import pytest

from dodaios.browser_voice.session import is_stop_request, looks_like_echo
from tests.fakes.fake_telephony_stack import FakeBrain, FakeSTT
from tests.unit.browser_voice.test_session import _make_session, _pcm16_frame, _Sink, _SlowTTS


async def _say(session, frames: int = 8) -> None:
    """One utterance through the endpointer: speech then trailing silence."""
    session._endpointer.silence_ms = 100
    session._endpointer.min_speech_ms = 60
    for _ in range(frames):
        await session.handle_audio_frame(_pcm16_frame(15000))
    for _ in range(10):
        await session.handle_audio_frame(_pcm16_frame(0))


async def _until(predicate, steps: int = 300) -> None:
    for _ in range(steps):
        if predicate():
            return
        await asyncio.sleep(0.01)


class _HeldBrain(FakeBrain):
    """Thinks until released, so a second utterance lands mid-turn."""

    def __init__(self, response: str = "Voici la réponse.") -> None:  # i18n-allow
        super().__init__(response)
        self.release = asyncio.Event()

    async def generate_stream(self, user_text: str, **_kw):
        self.prompts.append(user_text)
        await self.release.wait()
        yield self._response


# --- pure helpers -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["stop", "Stop !", "arrête", "Arrête-toi.", "tais-toi", "chut", "non, stop",  # i18n-allow
     "attends", "ok stop", "halt", "hör auf", "shut up"],  # i18n-allow: speech input
)
def test_bare_stop_requests(text: str) -> None:
    assert is_stop_request(text)


@pytest.mark.parametrize(
    "text",
    ["raconte-moi autre chose", "stop la musique et lance la radio", "non",  # i18n-allow
     "", "attends, je voulais te demander la météo de demain à Lyon"],  # i18n-allow
)
def test_requests_that_say_more_than_stop(text: str) -> None:
    assert not is_stop_request(text)


def test_echo_is_the_reply_heard_back() -> None:
    reply = "Il était une fois un petit phare solitaire qui racontait des blagues."  # i18n-allow
    assert looks_like_echo("un petit phare solitaire", reply)  # i18n-allow
    assert not looks_like_echo("raconte-moi autre chose", reply)  # i18n-allow
    assert not looks_like_echo("stop", "stop the stopwatch")  # a stop is never echo


# --- the session --------------------------------------------------------------


async def test_speaking_over_the_reply_interrupts_it_and_answers_the_new_request():
    sink = _Sink()
    brain = FakeBrain("Il était une fois un petit phare solitaire.")  # i18n-allow
    stt = FakeSTT(["raconte-moi une histoire", "parle-moi plutôt de la météo"])  # i18n-allow
    session = _make_session(sink, stt=stt, brain=brain, tts=_SlowTTS(chunks=200))
    await _say(session)
    await _until(lambda: session._speaking)
    assert session._speaking

    await _say(session)
    await _until(lambda: len(brain.prompts) >= 2)

    assert sink.json_of("tts_cancel"), "the browser must flush the reply it is playing"
    assert brain.prompts == ["raconte-moi une histoire", "parle-moi plutôt de la météo"]  # i18n-allow
    await session.end()


async def test_a_bare_stop_silences_without_a_new_turn():
    sink = _Sink()
    brain = FakeBrain("Il était une fois un petit phare solitaire.")  # i18n-allow
    session = _make_session(
        sink, stt=FakeSTT(["raconte-moi une histoire", "arrête"]), brain=brain,  # i18n-allow
        tts=_SlowTTS(chunks=200),
    )
    await _say(session)
    await _until(lambda: session._speaking)
    await _say(session)
    await _until(lambda: bool(sink.json_of("tts_cancel")))
    await _until(lambda: not session._processing)

    assert sink.json_of("tts_cancel")
    assert brain.prompts == ["raconte-moi une histoire"]  # i18n-allow: "stop" never reaches the brain
    await session.end()


async def test_own_voice_echo_does_not_interrupt():
    sink = _Sink()
    reply = "Il était une fois un petit phare solitaire."  # i18n-allow
    brain = FakeBrain(reply)
    session = _make_session(
        sink, stt=FakeSTT(["raconte-moi une histoire", "un petit phare solitaire"]),  # i18n-allow
        brain=brain, tts=_SlowTTS(chunks=200),
    )
    await _say(session)
    await _until(lambda: session._speaking)
    await _say(session)
    await _until(lambda: len(session._stt.calls) >= 2)
    await asyncio.sleep(0.05)

    assert not sink.json_of("tts_cancel")
    assert brain.prompts == ["raconte-moi une histoire"]  # i18n-allow
    await session.end()


async def test_rest_of_a_sentence_cut_by_a_pause_is_transcribed_with_it():
    sink = _Sink()
    brain = _HeldBrain()
    stt = FakeSTT(["Salut, il est", "Salut, il est quelle heure ?"])  # i18n-allow
    session = _make_session(sink, stt=stt, brain=brain)
    await _say(session, frames=8)
    await _until(lambda: len(brain.prompts) == 1)
    await _say(session, frames=6)
    await _until(lambda: len(stt.calls) >= 2)
    await _until(lambda: len(brain.prompts) >= 2)
    brain.release.set()
    await _until(lambda: session.turns >= 1 and not session._processing)

    first_len, second_len = stt.calls[0][0], stt.calls[1][0]
    assert second_len > first_len, "the second STT pass hears both pieces"
    assert brain.prompts[-1] == "Salut, il est quelle heure ?"  # i18n-allow
    assert session.turns == 1, "the cut-off half never gets its own answer"
    await session.end()


async def test_talk_after_the_reply_started_is_queued_not_dropped():
    sink = _Sink()
    brain = FakeBrain("Réponse.")  # i18n-allow
    stt = FakeSTT(["première question", "deuxième question"])  # i18n-allow
    session = _make_session(sink, stt=stt, brain=brain, tts=_SlowTTS(chunks=3))
    await _say(session)
    await _until(lambda: session._reply_started)
    session._processing = True  # still finishing this turn's bookkeeping
    session._playback_until = 0.0
    session._speaking = False
    await session._handle_overlap(b"\x00\x01" * 1600)
    assert session._queued, "kept for after the turn"
    session._processing = False
    await session.end()


# --- the record ---------------------------------------------------------------


class _Bus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


async def test_a_french_session_is_recorded_as_french():
    from dodaios.core.events import VoiceSessionStarted, VoiceTurnCompleted

    sink, bus = _Sink(), _Bus()
    session = _make_session(
        sink, stt=FakeSTT(["il est quelle heure ?"]), brain=FakeBrain("Il est midi."),  # i18n-allow
        language_code="fr-FR", bus=bus,
    )
    await _say(session)
    await _until(lambda: any(isinstance(e, VoiceTurnCompleted) for e in bus.events))
    started = next(e for e in bus.events if isinstance(e, VoiceSessionStarted))
    done = next(e for e in bus.events if isinstance(e, VoiceTurnCompleted))
    assert started.language == "fr"
    assert (done.user_lang, done.jarvis_lang) == ("fr", "fr")
    assert session._lang_short() == "en"  # the scrubber keeps its own locale set
    await session.end()


# --- the session's own brain ----------------------------------------------------


class _ClosableBrain(FakeBrain):
    def __init__(self) -> None:
        super().__init__("ok")
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


async def test_ending_a_session_releases_the_brain_built_for_it():
    brain = _ClosableBrain()
    session = _make_session(_Sink(), brain=brain, owns_brain=True)
    await session.end(reason="client_stop")
    await session.end(reason="ws_closed")
    assert brain.closed == 1


async def test_a_shared_brain_is_left_alone():
    brain = _ClosableBrain()
    session = _make_session(_Sink(), brain=brain)
    await session.end(reason="client_stop")
    assert brain.closed == 0
