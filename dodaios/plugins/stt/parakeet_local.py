"""On-device speech-to-text: NVIDIA Parakeet TDT 0.6B v3 through sherpa-onnx.

The fast local recognizer. It reads a whole clip in one pass on the CPU, at
tens of times real time on an ordinary laptop, and writes punctuation and
capitals itself. It needs no key, no graphics card and no network, and its
int8 model is a download of about 490 MB.

It covers 25 European languages (:data:`SUPPORTED_LANGUAGES`) and finds the
language by itself; it cannot be told one. Speech in any other language
belongs to the Whisper engine, which :func:`supports_language` lets a caller
decide before it picks this one.

Structural provider (duck-typed against ``STTProvider``). Engine and model are
optional and absent on a base install, so every heavy import is lazy and a
missing piece is one plain error.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import numpy as np

from dodaios.audio.capture import pcm_bytes_to_np
from dodaios.core.protocols import AudioChunk, Transcript

log = logging.getLogger(__name__)

#: Directory name of the model bundle under ``data/models/``.
MODEL_ID = "parakeet-tdt-0.6b-v3-int8"

_MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")

#: The languages the v3 model was trained on (ISO 639-1).
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {
        "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
        "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru",
        "uk",
    }
)

#: Silence around the clip. The model drops a word that starts on the very
#: first sample and can cut the last syllable without room behind it.
_LEAD_SILENCE_S = 0.3
_TAIL_SILENCE_S = 0.4

_INT16_FULL_SCALE = 32768.0
_MIN_THREADS = 2
_MAX_THREADS = 4


def _default_threads() -> int:
    """Half the logical processors, between two and four.

    More threads did not decode faster on an eight-core laptop, and a
    dictation must leave the rest of the machine responsive.
    """
    return max(_MIN_THREADS, min(_MAX_THREADS, (os.cpu_count() or _MIN_THREADS) // 2))


def supports_language(language: str | None) -> bool:
    """Whether the model can read ``language`` (a code such as ``de-DE``)."""
    code = str(language or "").strip().lower().replace("_", "-").split("-", 1)[0]
    return code in SUPPORTED_LANGUAGES


#: How long the last token of a sentence is taken to last, for its end time.
_TOKEN_S = 0.08


def _sentence_segments(
    tokens: Any, timestamps: Any, *, offset_s: float
) -> tuple[dict[str, Any], ...]:
    """The decoded sentences with their times in the clip, from token times.

    The model reports the start of every token. A sentence ends at a token
    that ends in ``.``, ``?`` or ``!``. Times are given relative to the clip
    the caller passed, so the silence added in front is taken off again.
    Anything that does not line up yields no segments, never a wrong one.
    """
    try:
        pairs = list(zip(list(tokens), [float(t) for t in timestamps], strict=True))
    except (TypeError, ValueError):  # no or mismatched times: no segments
        return ()
    segments: list[dict[str, Any]] = []
    words: list[str] = []
    start: float | None = None
    last = 0.0
    for token, at in pairs:
        piece = str(token)
        if start is None:
            start = at
        words.append(piece)
        last = at
        if piece.rstrip().endswith((".", "?", "!")):
            segments.append(
                {
                    "start": max(0.0, start - offset_s),
                    "end": max(0.0, last + _TOKEN_S - offset_s),
                    "text": "".join(words).strip(),
                }
            )
            words, start = [], None
    if words and start is not None:
        segments.append(
            {
                "start": max(0.0, start - offset_s),
                "end": max(0.0, last + _TOKEN_S - offset_s),
                "text": "".join(words).strip(),
            }
        )
    return tuple(segment for segment in segments if segment["text"])


class ParakeetLocalSTT:
    """Local one-pass speech-to-text via sherpa-onnx (keyless, on-device)."""

    name = "parakeet-local"
    #: Nothing this recognizer hears leaves the machine.
    runs_on_device = True
    supports_streaming = False

    def __init__(
        self,
        *,
        language: str | None = None,
        model_dir: str | Path | None = None,
        num_threads: int | None = None,
        provider: str = "cpu",
    ) -> None:
        # Kept for the transcript's language tag only: the model detects.
        self._language = (language or "").strip() or None
        self._model_dir = Path(model_dir) if model_dir else None
        self._num_threads = max(1, int(num_threads or _default_threads()))
        self._provider = provider or "cpu"
        self._recognizer: Any | None = None
        # One decode at a time: the recognizer is one shared native object.
        self._decode_lock = asyncio.Lock()
        # A warm-up and the first decode can ask for the model at once, from
        # two threads; it is loaded once.
        self._load_lock = threading.Lock()

    @property
    def last_used_model(self) -> str:
        return MODEL_ID

    def _resolve_model_files(self) -> dict[str, Path]:
        if self._model_dir is not None:
            return {name: self._model_dir / name for name in _MODEL_FILES}
        from dodaios.speech.sherpa_models import model_paths

        return model_paths(MODEL_ID)

    def _ensure_model(self) -> None:
        """Build the recognizer on first use; one plain error if it cannot."""
        if self._recognizer is not None:
            return
        with self._load_lock:
            if self._recognizer is None:
                self._recognizer = self._load()

    def _load(self) -> Any:
        try:
            import sherpa_onnx  # noqa: PLC0415 - optional engine, lazy on purpose
        except ImportError as exc:
            raise RuntimeError(
                "The local speech runtime (sherpa-onnx) is not installed, so "
                "Parakeet cannot transcribe. Install it from the API-Keys view, "
                "or switch voice input to a provider you have a key for."
            ) from exc

        files = self._resolve_model_files()
        missing = [name for name, path in files.items() if not path.is_file()]
        if missing or not files:
            raise RuntimeError(
                "The Parakeet model files are not on this machine yet "
                f"(missing: {', '.join(sorted(missing)) or 'all'}). Download "
                "them from the API-Keys view."
            )
        log.info(
            "Loading local Parakeet model (%s, %d threads) from %s",
            self._provider,
            self._num_threads,
            files["tokens.txt"].parent,
        )
        return sherpa_onnx.OfflineRecognizer.from_transducer(
            tokens=str(files["tokens.txt"]),
            encoder=str(files["encoder.int8.onnx"]),
            decoder=str(files["decoder.int8.onnx"]),
            joiner=str(files["joiner.int8.onnx"]),
            num_threads=self._num_threads,
            provider=self._provider,
            model_type="nemo_transducer",
        )

    async def transcribe(self, audio: AsyncIterator[AudioChunk]) -> Transcript:
        """Collect the whole utterance, then decode it in one pass."""
        pieces: list[np.ndarray] = []
        sample_rate = 16_000
        async for chunk in audio:
            pieces.append(pcm_bytes_to_np(chunk.pcm))
            sample_rate = chunk.sample_rate
        if not pieces:
            return Transcript(text="", language="unknown", confidence=0.0)
        return await self._decode(np.concatenate(pieces), sample_rate)

    async def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16_000,
        language: str | None = None,  # noqa: ARG002 - the model detects the language
    ) -> Transcript:
        """Direct path: int16 PCM bytes -> transcript."""
        return await self._decode(pcm_bytes_to_np(pcm_bytes), sample_rate)

    async def stream_transcribe(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[Transcript]:
        """One final transcript, matching ``supports_streaming = False``."""
        yield await self.transcribe(audio)

    async def _decode(self, samples: np.ndarray, sample_rate: int) -> Transcript:
        if samples.size == 0:
            return Transcript(text="", language="unknown", confidence=0.0)
        async with self._decode_lock:
            return await asyncio.to_thread(self._decode_blocking, samples, sample_rate)

    def _decode_blocking(self, samples: np.ndarray, sample_rate: int) -> Transcript:
        self._ensure_model()
        recognizer = self._recognizer
        assert recognizer is not None  # _ensure_model raises otherwise

        audio = np.asarray(samples, dtype=np.float32)
        # ``pcm_bytes_to_np`` may hand back int16-scaled values; the feature
        # extractor expects [-1, 1].
        if audio.size and float(np.max(np.abs(audio))) > 1.0:
            audio = audio / _INT16_FULL_SCALE
        lead = np.zeros(int(sample_rate * _LEAD_SILENCE_S), dtype=np.float32)
        tail = np.zeros(int(sample_rate * _TAIL_SILENCE_S), dtype=np.float32)
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, np.concatenate([lead, audio, tail]))
        recognizer.decode_stream(stream)
        result = stream.result
        raw = str(getattr(result, "text", "") or "").strip()

        from dodaios.plugins.stt.transcript_filter import clean_stt_text

        language = self._language or "auto"
        return Transcript(
            text=clean_stt_text(raw, language=self._language),
            raw_text=raw,
            language=language,
            # The transducer reports no calibrated probability for a clip.
            confidence=1.0 if raw else 0.0,
            segments=_sentence_segments(
                getattr(result, "tokens", None) or (),
                getattr(result, "timestamps", None) or (),
                offset_s=_LEAD_SILENCE_S,
            ),
        )

    async def aclose(self) -> None:
        """Release the recognizer so a provider switched away frees its memory."""
        self._recognizer = None


__all__ = ["MODEL_ID", "SUPPORTED_LANGUAGES", "ParakeetLocalSTT", "supports_language"]
