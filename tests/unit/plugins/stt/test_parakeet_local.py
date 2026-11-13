"""Guards for the on-device Parakeet recognizer.

No model and no engine are loaded here: a stand-in ``sherpa_onnx`` module
records how the provider builds and feeds its recognizer. What is pinned:

* the model is built on first use and only once, also when a warm-up and the
  first dictation ask for it at the same moment;
* a missing engine or missing model files is one plain error that names what
  is missing, not a native crash;
* the audio reaches the recognizer in the range it expects, with silence
  around it so the first and the last word survive;
* the declarations other parts of the app decide by: the provider name, that
  it runs on the device, and which languages it can read.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dodaios.plugins.stt.parakeet_local import (
    MODEL_ID,
    ParakeetLocalSTT,
    supports_language,
)

_MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")


class _FakeStream:
    """Records what the provider hands the recognizer."""

    def __init__(self) -> None:
        self.result = types.SimpleNamespace(text="")
        self.waveforms: list[tuple[int, np.ndarray]] = []

    def accept_waveform(self, sample_rate: int, samples: np.ndarray) -> None:
        self.waveforms.append((sample_rate, np.array(samples, copy=True)))


class _FakeRecognizer:
    def __init__(self, text: str) -> None:
        self._text = text
        self.streams: list[_FakeStream] = []
        self.decoded: list[_FakeStream] = []

    def create_stream(self) -> _FakeStream:
        stream = _FakeStream()
        self.streams.append(stream)
        return stream

    def decode_stream(self, stream: _FakeStream) -> None:
        self.decoded.append(stream)
        stream.result.text = self._text


class _FakeEngine(types.ModuleType):
    """A ``sherpa_onnx`` stand-in that counts the recognizers it builds."""

    def __init__(self, text: str = " Hello there. ", build_s: float = 0.0) -> None:
        super().__init__("sherpa_onnx")
        self.built: list[dict[str, Any]] = []
        self.recognizers: list[_FakeRecognizer] = []
        engine = self

        class OfflineRecognizer:
            @classmethod
            def from_transducer(cls, **kwargs: Any) -> _FakeRecognizer:
                engine.built.append(kwargs)
                # A real model takes seconds to load; the pause leaves room
                # for a second caller to arrive while the first is loading.
                time.sleep(build_s)
                recognizer = _FakeRecognizer(text)
                engine.recognizers.append(recognizer)
                return recognizer

        self.OfflineRecognizer = OfflineRecognizer

    @property
    def last_stream(self) -> _FakeStream:
        return self.recognizers[-1].streams[-1]


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    """A model folder that holds every file the recognizer asks for."""
    for name in _MODEL_FILES:
        (tmp_path / name).touch()
    return tmp_path


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> _FakeEngine:
    fake = _FakeEngine()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    return fake


def _pcm(seconds: float = 0.5, level: int = 1000) -> bytes:
    """Audio without a single zero sample, so added silence can be told apart."""
    return np.full(int(16_000 * seconds), level, dtype=np.int16).tobytes()


# --------------------------------------------------------------------------
# Building the model
# --------------------------------------------------------------------------


def test_the_model_is_built_on_first_use_and_only_once(
    engine: _FakeEngine, model_dir: Path
) -> None:
    """Starting the app must not load half a gigabyte; the first dictation does."""
    provider = ParakeetLocalSTT(model_dir=model_dir)
    assert engine.built == []

    asyncio.run(provider.transcribe_pcm(_pcm()))
    asyncio.run(provider.transcribe_pcm(_pcm()))
    provider._ensure_model()

    assert len(engine.built) == 1
    assert len(engine.recognizers[0].decoded) == 2


def test_the_model_is_built_from_the_files_of_its_folder(
    engine: _FakeEngine, model_dir: Path
) -> None:
    provider = ParakeetLocalSTT(model_dir=model_dir, num_threads=3)

    provider._ensure_model()

    arguments = engine.built[0]
    assert arguments["tokens"] == str(model_dir / "tokens.txt")
    assert arguments["encoder"] == str(model_dir / "encoder.int8.onnx")
    assert arguments["decoder"] == str(model_dir / "decoder.int8.onnx")
    assert arguments["joiner"] == str(model_dir / "joiner.int8.onnx")
    assert arguments["num_threads"] == 3


def test_two_threads_asking_at_once_build_one_model(
    monkeypatch: pytest.MonkeyPatch, model_dir: Path
) -> None:
    """A warm-up and the first decode can both find the model missing; a
    second build would hold the model in memory twice."""
    slow_engine = _FakeEngine(build_s=0.05)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", slow_engine)
    provider = ParakeetLocalSTT(model_dir=model_dir)
    together = threading.Barrier(2)
    failures: list[BaseException] = []

    def _ask() -> None:
        try:
            together.wait(timeout=5)
            provider._ensure_model()
        except BaseException as exc:  # noqa: BLE001 - reported by the assert below
            failures.append(exc)

    threads = [threading.Thread(target=_ask) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert failures == []
    assert len(slow_engine.built) == 1
    assert provider._recognizer is slow_engine.recognizers[0]


def test_aclose_drops_the_model_and_the_next_call_builds_it_again(
    engine: _FakeEngine, model_dir: Path
) -> None:
    """A provider that was switched away from must free the model's memory."""
    provider = ParakeetLocalSTT(model_dir=model_dir)
    asyncio.run(provider.transcribe_pcm(_pcm()))

    asyncio.run(provider.aclose())
    assert provider._recognizer is None
    result = asyncio.run(provider.transcribe_pcm(_pcm()))

    assert len(engine.built) == 2
    assert result.text == "Hello there."


# --------------------------------------------------------------------------
# What is missing is said plainly
# --------------------------------------------------------------------------


def test_missing_model_files_raise_one_error_that_names_them(
    engine: _FakeEngine, tmp_path: Path
) -> None:
    (tmp_path / "encoder.int8.onnx").touch()
    (tmp_path / "decoder.int8.onnx").touch()
    provider = ParakeetLocalSTT(model_dir=tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(provider.transcribe_pcm(_pcm()))

    message = str(excinfo.value)
    assert "joiner.int8.onnx" in message
    assert "tokens.txt" in message
    assert "encoder.int8.onnx" not in message
    assert "model files" in message
    assert engine.built == []


def test_a_missing_engine_raises_one_error_that_names_it(
    monkeypatch: pytest.MonkeyPatch, model_dir: Path
) -> None:
    """A base install has no sherpa-onnx; the person must learn that, not see
    an import trace."""
    # ``None`` in ``sys.modules`` makes the import fail as on a base install.
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)
    provider = ParakeetLocalSTT(model_dir=model_dir)

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(provider.transcribe_pcm(_pcm()))

    message = str(excinfo.value)
    assert "sherpa-onnx" in message
    assert "not installed" in message
    assert isinstance(excinfo.value.__cause__, ImportError)


def test_a_failed_build_is_tried_again_on_the_next_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The files can arrive while the app runs; no restart may be needed."""
    fake = _FakeEngine()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    provider = ParakeetLocalSTT(model_dir=tmp_path)
    with pytest.raises(RuntimeError):
        provider._ensure_model()

    for name in _MODEL_FILES:
        (tmp_path / name).touch()
    result = asyncio.run(provider.transcribe_pcm(_pcm()))

    assert result.text == "Hello there."
    assert len(fake.built) == 1


# --------------------------------------------------------------------------
# What the recognizer is given
# --------------------------------------------------------------------------


def test_the_decode_gets_float_samples_with_silence_around_them(
    engine: _FakeEngine, model_dir: Path
) -> None:
    """Without room in front the model drops the first word, without room
    behind it can cut the last syllable."""
    provider = ParakeetLocalSTT(model_dir=model_dir)
    pcm = _pcm(0.5, level=1000)

    asyncio.run(provider.transcribe_pcm(pcm))

    recognizer = engine.recognizers[0]
    assert len(recognizer.streams) == 1
    assert recognizer.decoded == recognizer.streams
    (rate, samples), = engine.last_stream.waveforms
    assert rate == 16_000
    assert samples.dtype == np.float32
    spoken = np.flatnonzero(samples)
    lead = samples[: spoken[0]]
    tail = samples[spoken[-1] + 1 :]
    assert lead.size > 0
    assert tail.size > 0
    assert spoken.size == 8_000
    np.testing.assert_allclose(samples[spoken[0] : spoken[-1] + 1], 1000 / 32768.0, rtol=1e-6)


@pytest.mark.parametrize("level", [32767, -32768])
def test_full_scale_audio_stays_within_minus_one_and_one(
    engine: _FakeEngine, model_dir: Path, level: int
) -> None:
    provider = ParakeetLocalSTT(model_dir=model_dir)

    asyncio.run(provider.transcribe_pcm(_pcm(0.2, level=level)))

    _, samples = engine.last_stream.waveforms[0]
    assert float(np.max(np.abs(samples))) <= 1.0
    assert float(np.max(np.abs(samples))) > 0.99


def test_the_transcript_carries_the_recognizers_words(
    engine: _FakeEngine, model_dir: Path
) -> None:
    """The model finds the language itself, so a caller that names one is
    answered like any other."""
    provider = ParakeetLocalSTT(model_dir=model_dir)

    result = asyncio.run(provider.transcribe_pcm(_pcm(), 16_000, language="de"))

    assert result.text == "Hello there."
    assert result.raw_text == "Hello there."
    assert result.confidence == 1.0
    assert provider.last_used_model == MODEL_ID


def test_empty_input_makes_no_decode_call(engine: _FakeEngine, model_dir: Path) -> None:
    """Nothing to read is an empty answer, and no reason to load the model."""
    provider = ParakeetLocalSTT(model_dir=model_dir)

    result = asyncio.run(provider.transcribe_pcm(b""))

    assert result.text == ""
    assert result.confidence == 0.0
    assert engine.built == []
    assert engine.recognizers == []


def test_a_recognizer_that_heard_nothing_gives_an_empty_transcript(
    monkeypatch: pytest.MonkeyPatch, model_dir: Path
) -> None:
    silent_engine = _FakeEngine(text="  ")
    monkeypatch.setitem(sys.modules, "sherpa_onnx", silent_engine)
    provider = ParakeetLocalSTT(model_dir=model_dir)

    result = asyncio.run(provider.transcribe_pcm(_pcm()))

    assert result.text == ""
    assert result.raw_text == ""
    assert result.confidence == 0.0


# --------------------------------------------------------------------------
# Declarations
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["de", "de-DE", "EN", "en_US", " fr ", "uk"])
def test_supports_language_accepts_the_languages_of_the_model(language: str) -> None:
    assert supports_language(language) is True


@pytest.mark.parametrize("language", ["zh", "ja", "zh-CN", "", None, "auto"])
def test_supports_language_rejects_everything_else(language: str | None) -> None:
    """Speech in such a language has to go to another engine."""
    assert supports_language(language) is False


def test_declares_its_name_and_that_it_runs_on_the_device() -> None:
    """The name selects the provider; the flag tells the rest of the app that
    nothing this recognizer hears leaves the machine."""
    assert ParakeetLocalSTT.name == "parakeet-local"
    assert ParakeetLocalSTT.runs_on_device is True


def test_construction_loads_no_model(engine: _FakeEngine, model_dir: Path) -> None:
    provider = ParakeetLocalSTT(model_dir=model_dir, language="de")

    assert provider._recognizer is None
    assert engine.built == []
