"""A pause in the middle of a dictation must not cost the words after it.

The reported symptom: speak, stop to think for ten-odd seconds while still
holding the key, speak again, and everything after the pause is missing. The
chain behind it was: the pause was sent to the recognizer again and again, the
service answered ``429 Too Many Requests``, the backlog grew, and the silence
itself came back as an invented sentence ("Thank you for watching!" in the
middle of a German dictation).

What is pinned here is the shape that breaks that chain: silence is never sent
to a recognizer, a long recording goes out in bounded pieces, a refused call
gets one more try, and one piece nobody could read does not cost the others.

Every judgement about silence is made on the AUDIO, never on the text that
came back (AP-27): a content rule cannot tell an invention from a sentence.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

import dodaios.dictation.take as take_mod
import dodaios.speech.pipeline as pipeline_mod
from dodaios.core.bus import EventBus
from dodaios.core.config import DictationConfig
from dodaios.speech.pipeline import PipelineState, SpeechPipeline

pytestmark = pytest.mark.usefixtures("granted_microphone", "speech_by_loudness")

BYTES_PER_SECOND = 16_000 * 2

#: What a transcription model does with silence. Not a joke: this exact string
#: is in the maintainer's dictation history, in the middle of a German sentence.
HALLUCINATION = "Thank you for watching!"


def _word(index: int, seconds: float = 0.5) -> bytes:
    """A stretch of "speech" whose amplitude identifies it uniquely.

    Being able to tell WHICH words reached the provider is the whole point:
    "some audio was transcribed" is exactly the claim the broken version could
    also make.
    """
    amplitude = 4_000 + index * 500
    samples = int(seconds * 16_000)
    return (np.ones(samples, dtype=np.int16) * amplitude).tobytes()


def _silence(seconds: float) -> bytes:
    return np.zeros(int(seconds * 16_000), dtype=np.int16).tobytes()


class _MarkerSTT:
    """Reports which marker words a piece of audio contains.

    Mimics the real failure modes: silence comes back as a hallucinated
    sentence (never as ``""``), and the first ``fail_first`` calls are refused
    the way a rate limit refuses them.
    """

    def __init__(self, *, fail_first: int = 0) -> None:
        self.calls: list[bytes] = []
        self.silent_calls = 0
        self._fail_first = fail_first

    async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
        self.calls.append(bytes(pcm))
        if len(self.calls) <= self._fail_first:
            raise RuntimeError("429 Too Many Requests")
        samples = np.frombuffer(pcm, dtype=np.int16)
        amplitudes = {int(v) for v in np.unique(np.abs(samples)) if v}
        words = [f"w{(a - 4_000) // 500}" for a in sorted(amplitudes)]
        if not words:
            # Every real transcription model does this, and it is why silence
            # must never be uploaded in the first place.
            self.silent_calls += 1
            return SimpleNamespace(text=HALLUCINATION, language="en")
        return SimpleNamespace(text=" ".join(words), language="de")


class _ScriptedMic:
    """Yields a fixed script of chunks, then holds the stream open."""

    script: list[bytes] = []
    #: Set once the whole script was handed to the session.
    delivered: asyncio.Event | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _ScriptedMic:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def stream(self):  # type: ignore[no-untyped-def]
        for chunk in type(self).script:
            yield SimpleNamespace(pcm=chunk)
            # Let a piece be read between chunks, so the test exercises the
            # real interleaving of "audio arrives while a piece is being read"
            # instead of handing the session a finished recording.
            await asyncio.sleep(0)
        if type(self).delivered is not None:
            type(self).delivered.set()
        await asyncio.Event().wait()


def _pipeline(bus: EventBus, stt: _MarkerSTT, cfg: DictationConfig) -> SpeechPipeline:
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    pipe._bus = bus
    pipe._utterance_stt = stt
    pipe._dictation_task = None
    pipe._dictation_stop_event = asyncio.Event()
    pipe._dictation_cfg = cfg
    pipe._dictation_max_s = 30.0
    pipe._dictation_wake_block_until = 0.0
    pipe._dictation_completion_published = True
    pipe._ptt_mode = False
    pipe._state = PipelineState.IDLE
    pipe._muted = False
    pipe._input_device = "default"
    pipe._input_priority = ()
    pipe._hangup_event = asyncio.Event()
    return pipe


async def _run(
    monkeypatch,
    *,
    script: list[bytes],
    stt: _MarkerSTT,
    cfg: DictationConfig | None = None,
) -> dict[str, object]:
    """Record the whole script, release the key, return ``_finish``'s kwargs."""
    bus = EventBus()
    pipe = _pipeline(bus, stt, cfg or DictationConfig())
    _ScriptedMic.script = script
    _ScriptedMic.delivered = asyncio.Event()
    monkeypatch.setattr(pipeline_mod, "MicrophoneCapture", _ScriptedMic)
    monkeypatch.setattr(take_mod, "_RETRY_DELAY_S", 0.0)

    captured: dict[str, object] = {}

    async def _fake_finish(**kwargs: object) -> str:
        captured.update(kwargs)
        pipe._dictation_completion_published = True
        return str(kwargs.get("raw_text") or "")

    pipe._finish_dictation = _fake_finish  # type: ignore[method-assign]

    assert pipe.start_dictation(target="chat") is True
    # The key is released once the microphone has delivered everything, not
    # after a fixed sleep: a timing-based wait on a loaded machine is a flake.
    await asyncio.wait_for(_ScriptedMic.delivered.wait(), timeout=10.0)
    pipe.stop_dictation()
    await asyncio.wait_for(pipe._dictation_task, timeout=10.0)
    return captured


def _short_pieces(monkeypatch, seconds: float) -> None:
    """Cut a recording every ``seconds``, so a short test recording has pieces."""
    monkeypatch.setattr(take_mod, "PIECE_MIN_S", seconds)
    monkeypatch.setattr(take_mod, "_CUT_LADDER", ((seconds, 0.9),))
    monkeypatch.setattr(take_mod, "PIECE_MAX_S", seconds)


@pytest.mark.asyncio
async def test_words_after_a_long_pause_still_reach_the_transcript(monkeypatch) -> None:
    """The reported bug, end to end: speech, a long think-pause, more speech."""
    script = [_word(0), _word(1), _silence(12.0), _word(2), _word(3)]
    stt = _MarkerSTT()

    captured = await _run(monkeypatch, script=script, stt=stt)

    text = str(captured.get("raw_text") or "")
    for marker in ("w0", "w1", "w2", "w3"):
        assert marker in text, f"{marker} was spoken but never made it into {text!r}"


@pytest.mark.asyncio
async def test_a_pause_is_never_uploaded(monkeypatch) -> None:
    """Silence costs neither a request nor an invented sentence.

    Both halves matter: the requests are what ran into the rate limit, and the
    invented sentence is what the person found in the middle of their own text.
    """
    script = [_word(0), _silence(12.0), _word(1)]
    stt = _MarkerSTT()

    captured = await _run(monkeypatch, script=script, stt=stt)

    assert stt.silent_calls == 0, "a silent stretch was sent to the recognizer"
    assert HALLUCINATION not in str(captured.get("raw_text") or "")
    sent = sum(len(call) for call in stt.calls)
    assert sent < 4.0 * BYTES_PER_SECOND, (
        f"{sent / BYTES_PER_SECOND:.1f}s went to the recognizer for one second "
        "of speech: the pause was sent along"
    )


@pytest.mark.asyncio
async def test_a_recording_of_silence_asks_no_recognizer(monkeypatch) -> None:
    """A muted or wrong microphone makes no request, so nothing is invented."""
    stt = _MarkerSTT()

    captured = await _run(monkeypatch, script=[_silence(3.0)], stt=stt)

    assert stt.calls == []
    assert captured.get("raw_text") == ""
    assert captured.get("no_speech") is True
    assert captured.get("stt_error") is None


@pytest.mark.asyncio
async def test_a_long_recording_goes_out_in_bounded_pieces(monkeypatch) -> None:
    """No request may grow with the recording.

    One upload of a whole long recording is the shape where one failure loses
    all of it, and where the wait after the stop grows with every second
    spoken. Each piece is read once, in order.
    """
    _short_pieces(monkeypatch, 2.0)
    script = [_word(i, seconds=1.0) for i in range(12)]
    stt = _MarkerSTT()

    captured = await _run(monkeypatch, script=script, stt=stt)

    assert len(stt.calls) > 1, "the whole recording went out as one request"
    biggest = max(len(c) for c in stt.calls)
    assert biggest <= int(2.5 * BYTES_PER_SECOND), (
        f"a request reached {biggest / BYTES_PER_SECOND:.1f}s of audio"
    )
    text = str(captured.get("raw_text") or "")
    assert text.split() == [f"w{i}" for i in range(12)]


@pytest.mark.asyncio
async def test_a_refused_call_does_not_cost_the_words(monkeypatch) -> None:
    """A refusal that may pass gets one more try before the audio counts as lost.

    The refusal under test is the real one: HTTP 429. The recording is
    untouched by it, and the words arrive in full with the second call.
    """
    script = [_word(0), _word(1), _word(2)]
    stt = _MarkerSTT(fail_first=1)

    captured = await _run(monkeypatch, script=script, stt=stt)

    text = str(captured.get("raw_text") or "")
    for marker in ("w0", "w1", "w2"):
        assert marker in text, f"{marker} was lost to the refused call: {text!r}"
    assert captured.get("lost_audio_s") == 0
    assert captured.get("stt_error") is None


@pytest.mark.asyncio
async def test_one_dead_piece_does_not_cost_the_others(monkeypatch) -> None:
    """The point of reading in pieces.

    A piece whose every attempt fails is a real loss, but a bounded one, and
    it is reported: the lost seconds and the reason reach the delivery step,
    which keeps the recording so it can be read again.
    """

    class _OneBadPiece(_MarkerSTT):
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None):
            samples = np.frombuffer(pcm, dtype=np.int16)
            if 4_000 in {int(v) for v in np.unique(np.abs(samples))}:
                self.calls.append(bytes(pcm))
                raise RuntimeError("429 Too Many Requests")
            return await super().transcribe_pcm(pcm, language)

    _short_pieces(monkeypatch, 1.0)
    script = [_word(i, seconds=1.0) for i in range(4)]
    stt = _OneBadPiece()

    captured = await _run(monkeypatch, script=script, stt=stt)

    text = str(captured.get("raw_text") or "")
    assert "w0" not in text, "the failing piece was expected to be lost"
    for marker in ("w1", "w2", "w3"):
        assert marker in text, (
            f"{marker} was taken down by an unrelated failing piece: {text!r}"
        )
    assert float(captured.get("lost_audio_s") or 0.0) > 0.5
    assert captured.get("stt_error") == "rate_limited"
    assert captured.get("audio"), "the recording must be kept for another reading"


@pytest.mark.asyncio
async def test_a_recording_that_ends_early_is_reported(monkeypatch) -> None:
    """A truncated transcript must never be presented as the whole thing.

    The handoff buffer a dictation borrows from the wake loop raises once its
    replay window is exceeded. That killed the drain task, and the failure was
    swallowed with the teardown's cancellations — so the user got a transcript
    that stopped halfway with nothing anywhere saying why.
    """

    class _DyingMic(_ScriptedMic):
        async def stream(self):  # type: ignore[no-untyped-def]
            yield SimpleNamespace(pcm=_word(0))
            raise RuntimeError("Voice input exceeded the 30-second replay window")

    stt = _MarkerSTT()
    bus = EventBus()
    pipe = _pipeline(bus, stt, DictationConfig())
    monkeypatch.setattr(pipeline_mod, "MicrophoneCapture", _DyingMic)

    captured: dict[str, object] = {}

    async def _fake_finish(**kwargs: object) -> str:
        captured.update(kwargs)
        pipe._dictation_completion_published = True
        return str(kwargs.get("raw_text") or "")

    pipe._finish_dictation = _fake_finish  # type: ignore[method-assign]

    assert pipe.start_dictation(target="chat") is True
    await asyncio.wait_for(pipe._dictation_task, timeout=10.0)

    # The reason CODE, not the exception text: this value ends up under the
    # user's own words in the history, where a stack-trace fragment explains
    # nothing. The exception itself goes to the log.
    assert str(captured.get("stt_error") or "") == "recording_interrupted", (
        "the recording died and the dictation reported nothing about it"
    )
