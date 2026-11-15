"""Guards for the on-device Piper voice.

The properties worth pinning are the ones a cloud TTS gets for free and a local
one does not: a Piper voice speaks exactly ONE language, so choosing the right
file per turn IS the feature. Getting it wrong does not raise — it answers a
German sentence in an English accent, which no test would notice unless it
asks for this explicitly.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dodaios.plugins.tts import piper_local
from dodaios.plugins.tts.piper_local import PiperLocalTTS


class _FakeAudio:
    def __init__(self, seconds: float = 0.5, sample_rate: int = 22_050) -> None:
        self.samples = np.linspace(-0.5, 0.5, int(sample_rate * seconds), dtype=np.float32)
        self.sample_rate = sample_rate


class _FakeEngine:
    """Records what was spoken, so the test can assert WHICH voice ran."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.spoken: list[str] = []

    def generate(
        self,
        text: str,
        speaker_id: int | object,
        speed: float | None = None,
        *,
        callback=None,
    ) -> _FakeAudio:
        self.spoken.append(text)
        return _FakeAudio()


@pytest.fixture
def all_voices_installed(monkeypatch: pytest.MonkeyPatch) -> dict[str, _FakeEngine]:
    """Pretend every catalogued voice is downloaded, with fake engines."""
    engines: dict[str, _FakeEngine] = {}

    monkeypatch.setattr(
        "dodaios.speech.local_models.bundle_present",
        lambda model_id, **kw: True,
    )

    def _build(self: PiperLocalTTS, model_id: str) -> _FakeEngine:
        engine = _FakeEngine(model_id)
        engines[model_id] = engine
        return engine

    monkeypatch.setattr(PiperLocalTTS, "_build_engine", _build)
    return engines


async def _speak(tts: PiperLocalTTS, text: str, language_code: str | None) -> bytes:
    pcm = b""
    async for chunk in tts.synthesize(text, language_code=language_code):
        pcm += chunk.pcm
    return pcm


def test_each_language_gets_its_own_voice(all_voices_installed) -> None:
    """The core of a local TTS: one voice per language, picked per turn."""
    tts = PiperLocalTTS()

    asyncio.run(_speak(tts, "Guten Morgen", "de-DE"))
    german = tts.last_voice
    asyncio.run(_speak(tts, "Good morning", "en-US"))
    english = tts.last_voice
    asyncio.run(_speak(tts, "Buenos dias", "es-ES"))
    spanish = tts.last_voice

    assert german is not None and "de_DE" in german
    assert english is not None and "en_US" in english
    assert spanish is not None and "es_ES" in spanish


def test_the_speaker_profile_survives_a_language_switch(all_voices_installed) -> None:
    """Switching language must not switch WHO is speaking (BUG-086's shape)."""
    from dodaios.speech.local_models import SHERPA_BUNDLES

    tts = PiperLocalTTS(gender="feminine")

    asyncio.run(_speak(tts, "Guten Morgen", "de-DE"))
    german = tts.last_voice
    asyncio.run(_speak(tts, "Good morning", "en-US"))
    english = tts.last_voice

    assert SHERPA_BUNDLES[german].gender == "feminine"
    assert SHERPA_BUNDLES[english].gender == "feminine"


def test_an_explicit_voice_request_wins(all_voices_installed) -> None:
    tts = PiperLocalTTS()

    asyncio.run(
        tts.synthesize(
            "Hello", voice="vits-piper-en_US-amy-medium", language_code="de-DE"
        ).__anext__()
    )

    assert tts.last_voice == "vits-piper-en_US-amy-medium"


def test_an_unsupported_language_still_speaks(all_voices_installed) -> None:
    """Better an accent than silence — but the log has to say what happened."""
    tts = PiperLocalTTS()

    pcm = asyncio.run(_speak(tts, "Bonjour", "fr-FR"))

    assert pcm, "a language with no local voice must not produce silence"
    assert tts.last_voice is not None


def test_no_downloaded_voice_raises_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silence is the worst possible failure for a voice — say why instead."""
    monkeypatch.setattr(
        "dodaios.speech.local_models.bundle_present", lambda model_id, **kw: False
    )
    tts = PiperLocalTTS()

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(_speak(tts, "Hallo", "de-DE"))

    assert "API-Keys view" in str(excinfo.value)


def test_only_downloaded_voices_are_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Listing a voice that is not on disk would let the user pick silence."""
    present = {"vits-piper-de_DE-thorsten-medium"}
    monkeypatch.setattr(
        "dodaios.speech.local_models.bundle_present",
        lambda model_id, **kw: model_id in present,
    )
    tts = PiperLocalTTS()

    assert tts.list_voices() == ["vits-piper-de_DE-thorsten-medium"]
    assert tts.list_voices("en-US") == []


def test_audio_is_int16_in_range(all_voices_installed) -> None:
    """The pipeline plays int16; an unclipped float would wrap into loud noise."""
    tts = PiperLocalTTS()

    pcm = asyncio.run(_speak(tts, "Hallo", "de-DE"))
    samples = np.frombuffer(pcm, dtype=np.int16)

    assert samples.size > 0
    assert samples.max() <= 32767
    assert samples.min() >= -32768


def test_empty_text_speaks_nothing_without_loading_a_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(self: PiperLocalTTS, model_id: str) -> Any:
        raise AssertionError("empty text must not load a voice")

    monkeypatch.setattr(PiperLocalTTS, "_build_engine", _explode)
    tts = PiperLocalTTS()

    assert asyncio.run(_speak(tts, "   ", "de-DE")) == b""


def test_declares_that_it_runs_on_device() -> None:
    assert PiperLocalTTS.runs_on_device is True


def test_callback_capable_engine_yields_incremental_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StreamingEngine:
        sample_rate = 22_050

        def generate(self, _text, _speaker, _speed=None, *, callback):
            callback(np.full(100, 0.1, dtype=np.float32), 0.5)
            callback(np.full(100, 0.2, dtype=np.float32), 1.0)
            return _FakeAudio(seconds=0.0)

    monkeypatch.setattr(
        "dodaios.speech.local_models.bundle_present",
        lambda _model_id, **_kwargs: True,
    )
    monkeypatch.setattr(
        PiperLocalTTS,
        "_build_engine",
        lambda _self, _model_id: StreamingEngine(),
    )
    tts = PiperLocalTTS()

    async def collect() -> list[bytes]:
        return [
            chunk.pcm
            async for chunk in tts.synthesize("Hello", language_code="en-US")
        ]

    chunks = asyncio.run(collect())

    assert PiperLocalTTS.supports_streaming is True
    assert len(chunks) == 2
    assert all(chunks)


def test_voices_cover_every_supported_reply_language() -> None:
    """The catalog must not leave a supported language mute.

    ``[brain].reply_language`` offers de/en/es/pt, and the resolver can land on any
    of them per turn. A missing voice there is not a gap in a nice-to-have — it
    is the assistant going silent mid-conversation.
    """
    from dodaios.speech.local_models import PIPER_DEFAULT_VOICES, SHERPA_BUNDLES

    languages = {SHERPA_BUNDLES[v].language for v in PIPER_DEFAULT_VOICES}

    assert {"de", "en", "es", "pt"} <= languages


def test_default_voices_share_one_speaker_profile() -> None:
    """All three defaults must be the same kind of speaker, per the test above."""
    from dodaios.speech.local_models import PIPER_DEFAULT_VOICES, SHERPA_BUNDLES

    genders = {SHERPA_BUNDLES[v].gender for v in PIPER_DEFAULT_VOICES}

    assert len(genders) == 1


def test_module_exposes_the_expected_provider_surface() -> None:
    """Structural TTSProvider conformance — no inheritance, so assert it."""
    for attribute in ("synthesize", "list_voices", "name", "supports_streaming"):
        assert hasattr(piper_local.PiperLocalTTS, attribute)


_CANCELLED_STREAM_SCRIPT = textwrap.dedent(
    """
    import asyncio
    import sys
    import time

    import numpy as np

    import dodaios.speech.local_models as local_models
    from dodaios.plugins.tts import piper_local
    from dodaios.plugins.tts.piper_local import PiperLocalTTS


    class _Audio:
        samples = np.zeros(0, dtype=np.float32)
        sample_rate = 22_050


    class SlowEngine:
        # Like a native engine: a chunk every 0.3 s until the callback cancels.
        sample_rate = 22_050

        def generate(self, _text, _speaker, _speed=None, *, callback=None):
            for _ in range(50):
                if callback(np.full(2205, 0.1, dtype=np.float32), 0.0) == 0:
                    break
                time.sleep(0.3)
            return _Audio()


    # Legacy engine path: no sherpa-onnx or eSpeak NG needed on the test host.
    piper_local.package_version = lambda _name: "1.12.0"
    local_models.bundle_present = lambda *_args, **_kwargs: True
    PiperLocalTTS._build_engine = lambda _self, _model_id: SlowEngine()


    async def main():
        tts = PiperLocalTTS()

        async def consume():
            async for _chunk in tts.synthesize("Hello there", language_code="en-US"):
                pass

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.15)  # first chunk read; the reader now waits for the next
        task.cancel()  # barge-in or voice-session teardown
        await asyncio.gather(task, return_exceptions=True)


    asyncio.run(main())
    print("EXITED", flush=True)
    """
)


def test_a_cancelled_stream_does_not_keep_the_process_alive() -> None:
    """A barge-in mid-sentence must not leave a reader thread blocked forever.

    asyncio.run() joins the default executor on exit, so one orphaned
    ``chunks.get()`` kept the service alive until systemd sent SIGKILL.
    """
    repo_root = Path(__file__).resolve().parents[4]
    try:
        result = subprocess.run(
            [sys.executable, "-c", _CANCELLED_STREAM_SCRIPT],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the process did not exit: a Piper reader thread is still blocked")
    assert result.returncode == 0, result.stderr[-2000:]
    assert "EXITED" in result.stdout


# -- the runtime's version and a runtime without package metadata -----------
# Issue #1698: the desktop installers freeze sherpa-onnx into the app without
# its dist-info folder. The voice asked importlib.metadata for the version and
# failed with "No package metadata was found for sherpa-onnx", although the
# runtime itself was there and the card said "ready".


def _no_package_metadata(name: str) -> str:
    from importlib.metadata import PackageNotFoundError

    raise PackageNotFoundError(name)


def _runtime_module(**attributes: Any) -> Any:
    import types

    module = types.ModuleType("sherpa_onnx")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


@pytest.mark.parametrize(
    ("version", "major"),
    [("1.13.8", 1), ("2.0.1", 2), ("v1.12.40", 1), ("10.0.0", 10)],
)
def test_the_version_comes_from_the_module_when_there_is_no_package_metadata(
    monkeypatch: pytest.MonkeyPatch, version: str, major: int
) -> None:
    monkeypatch.setattr(piper_local, "package_version", _no_package_metadata)

    assert piper_local._sherpa_major_version(_runtime_module(__version__=version)) == major


def test_the_loaded_module_wins_over_stale_package_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The code that runs is the module; metadata can belong to another copy."""
    monkeypatch.setattr(piper_local, "package_version", lambda _name: "2.0.1")

    assert piper_local._sherpa_major_version(_runtime_module(__version__="1.13.8")) == 1


def test_package_metadata_answers_when_the_module_is_not_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "sherpa_onnx", raising=False)
    monkeypatch.setattr(piper_local, "package_version", lambda _name: "2.0.1")

    assert piper_local._sherpa_major_version() == 2


def test_a_runtime_that_says_no_version_is_taken_as_the_pinned_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(piper_local, "package_version", _no_package_metadata)

    assert piper_local._sherpa_major_version(_runtime_module()) == 1


def _frozen_style_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Any]:
    """A working sherpa-onnx 1.x stand-in with no package metadata, plus one voice."""
    built: list[Any] = []

    class _Config:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _OfflineTts:
        sample_rate = 22_050

        def __init__(self, config: Any) -> None:
            built.append(config)

        def generate(self, _text, _speaker, _speed=None, *, callback=None):
            callback(np.full(220, 0.25, dtype=np.float32), 1.0)
            return _FakeAudio(seconds=0.0)

    module = _runtime_module(
        __version__="1.13.8",
        OfflineTts=_OfflineTts,
        OfflineTtsConfig=_Config,
        OfflineTtsModelConfig=_Config,
        OfflineTtsVitsModelConfig=_Config,
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    monkeypatch.setattr(piper_local, "package_version", _no_package_metadata)
    monkeypatch.setattr("dodaios.speech.local_models._LOAD_FAILURES", {})

    voice = tmp_path / "voice"
    (voice / "espeak-ng-data").mkdir(parents=True)
    for name in ("voice.onnx", "tokens.txt"):
        (voice / name).write_bytes(b"x")
    monkeypatch.setattr(
        "dodaios.speech.sherpa_models.model_paths",
        lambda _model_id, **_kw: {
            "voice.onnx": voice / "voice.onnx",
            "tokens.txt": voice / "tokens.txt",
            "espeak-ng-data": voice / "espeak-ng-data",
        },
    )
    monkeypatch.setattr(
        "dodaios.speech.local_models.bundle_present", lambda _model_id, **_kw: True
    )
    return built


def test_the_voice_speaks_when_the_runtime_has_no_package_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole path of the Test button: load the voice, then speak."""
    built = _frozen_style_runtime(monkeypatch, tmp_path)

    pcm = asyncio.run(_speak(PiperLocalTTS(), "Hello there", "en-US"))

    assert len(built) == 1
    assert len(pcm) == 440  # 220 samples as int16


def test_a_runtime_that_cannot_load_stops_the_card_from_saying_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The first failed use is remembered: the card then tells the truth."""
    from dodaios.speech import local_models

    _frozen_style_runtime(monkeypatch, tmp_path)
    # What an interrupted uninstall leaves: a module with nothing in it.
    monkeypatch.setitem(sys.modules, "sherpa_onnx", _runtime_module())
    monkeypatch.setattr(
        local_models.importlib.util, "find_spec", lambda _name: sys.modules["os"].__spec__
    )
    assert local_models.local_status("piper-local").ready is True

    with pytest.raises(RuntimeError, match="cannot be loaded"):
        asyncio.run(_speak(PiperLocalTTS(), "Hello there", "en-US"))

    status = local_models.local_status("piper-local")
    assert status.ready is False
    assert "could not be loaded" in status.detail
