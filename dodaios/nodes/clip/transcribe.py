"""Speech to timed words, on this computer.

Captions, silence-aware cuts and "cut where she says X" all need to know
which word is said when. The recognizer is the same local engine the app's
own dictation uses (faster-whisper, :mod:`dodaios.plugins.stt.fwhisper`),
asked for word timestamps: on a GPU the large turbo model (fast and good in
every language the app speaks), on a CPU the small ``base`` model so a minute
of speech does not take minutes. Nothing leaves the machine.

The model is loaded on first use, kept for a few minutes for the next
request (a clip is usually captioned piece by piece) and then released, so an
idle app does not hold a gigabyte of GPU memory for a feature not in use.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Final

from dodaios.nodes.clip.media import read_audio

log = logging.getLogger(__name__)

GPU_MODEL: Final[str] = "large-v3-turbo"
CPU_MODEL: Final[str] = "base"
#: Seconds an unused model is kept loaded.
KEEP_S: Final[float] = 300.0
_RATE: Final[int] = 16_000

_lock = threading.Lock()
_model: Any = None
_release: threading.Timer | None = None


class TranscribeError(RuntimeError):
    """Speech could not be recognized; the message is for the person."""


def _gpu_usable() -> bool:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:  # noqa: BLE001 — no CUDA build or no driver: the CPU it is
        return False


def _load() -> Any:
    """The recognizer, built once (GPU first, the CPU when that fails)."""
    try:
        from dodaios.plugins.stt import fwhisper
    except ImportError as exc:  # the speech extra is not installed
        raise TranscribeError("Speech recognition is not installed on this computer.") from exc
    if _gpu_usable():
        try:
            fwhisper.ensure_cuda_libraries_findable()
            return fwhisper._new_whisper_model(GPU_MODEL, "cuda", "float16")
        except Exception as exc:  # noqa: BLE001 — a GPU that will not load: fall back
            log.warning("clip transcribe: GPU model failed (%s); using the CPU", exc)
    try:
        return fwhisper._new_whisper_model(CPU_MODEL, "cpu", "int8")
    except ImportError as exc:
        raise TranscribeError("Speech recognition is not installed on this computer.") from exc


def _drop() -> None:
    global _model, _release
    with _lock:
        _model = None
        _release = None
    log.info("clip transcribe: recognizer released after %.0f s unused", KEEP_S)


def _recognizer() -> Any:
    """The loaded recognizer; call with ``_lock`` held."""
    global _model, _release
    if _release is not None:
        _release.cancel()
        _release = None
    if _model is None:
        _model = _load()
    return _model


def transcribe_samples(samples: Any, language: str | None = None) -> dict[str, Any]:
    """Words of 16 kHz mono ``samples``, timed from their first sample."""
    global _release
    mono = samples[0] if getattr(samples, "ndim", 1) == 2 else samples
    if mono.shape[0] < _RATE // 4:
        return {"language": language or "", "text": "", "words": []}
    with _lock:
        model = _recognizer()
        try:
            segments, info = model.transcribe(
                mono,
                language=(language or None),
                word_timestamps=True,
                vad_filter=True,
                beam_size=5,
                condition_on_previous_text=False,
            )
            words: list[dict[str, Any]] = []
            for segment in segments:
                for word in segment.words or []:
                    text = str(word.word or "").strip()
                    if text:
                        words.append(
                            {
                                "w": text,
                                "s": round(float(word.start), 3),
                                "e": round(float(word.end), 3),
                            }
                        )
        finally:
            _release = threading.Timer(KEEP_S, _drop)
            _release.daemon = True
            _release.start()
    return {
        "language": str(getattr(info, "language", "") or language or ""),
        "text": " ".join(word["w"] for word in words),
        "words": words,
    }


#: The language heard in a file, by its path, size and change time.
_heard: dict[tuple[str, int, float], str] = {}
#: How much of a file the language is judged on.
_DETECT_S: Final[float] = 30.0


def spoken_language(path: Path) -> str | None:
    """The language spoken in ``path``, judged once on its first half minute.

    A piece of a cut is often only a few seconds long, and on so little speech
    the recognizer guesses the language wrong (an English sentence of three
    seconds came back as German words). So the language is judged on the file
    the piece comes from and kept per file; ``None`` when nothing could be
    judged, which leaves the guess to the recognizer again.
    """
    try:
        stat = path.stat()
    except OSError:  # a file gone or unreadable: the recognizer guesses per piece
        return None
    key = (str(path), stat.st_size, stat.st_mtime)
    if key in _heard:
        return _heard[key] or None
    samples = read_audio(path, 0.0, _DETECT_S, rate=_RATE, channels=1)
    mono = samples[0] if getattr(samples, "ndim", 1) == 2 else samples
    found = ""
    if mono.shape[0] >= _RATE:
        with _lock:
            model = _recognizer()
            try:
                language, probability, _ = model.detect_language(mono)
                if probability >= 0.5:
                    found = str(language)
            except Exception as exc:  # noqa: BLE001 — an older engine without it: guess per piece
                log.debug("clip transcribe: language not judged: %s", exc)
    _heard[key] = found
    return found or None


def transcribe_file(
    path: Path, start: float = 0.0, end: float | None = None, language: str | None = None
) -> dict[str, Any]:
    """The words said in ``path`` between ``start`` and ``end``, in source seconds.

    Returns ``{"language", "text", "words": [{"w", "s", "e"}]}``. Raises
    :class:`TranscribeError` when no recognizer can be loaded.
    """
    samples = read_audio(Path(path), start, end, rate=_RATE, channels=1)
    found = transcribe_samples(samples, language or spoken_language(Path(path)))
    for word in found["words"]:
        word["s"] = round(word["s"] + start, 3)
        word["e"] = round(word["e"] + start, 3)
    return found


__all__ = ["TranscribeError", "transcribe_file", "transcribe_samples"]
