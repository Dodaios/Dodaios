"""Read a recorded voice note (a phone chat's voice message) as text.

A voice message from Telegram arrives as an encoded file (OGG/Opus), not as
the live microphone stream the voice pipeline listens to. This module decodes
it to the 16 kHz mono PCM every recognizer takes and reads it with the same
recognizer a dictation uses (local first), so a voice message is understood
exactly like the owner's spoken words at the desk.

Import-light: PyAV and the recognizer are reached only when a note arrives.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "MAX_NOTE_SECONDS",
    "VoiceNoteError",
    "VoiceNoteUnavailable",
    "decode_to_pcm16k",
    "transcribe_voice_note",
]

#: Sample rate every recognizer takes.
SAMPLE_RATE: Final[int] = 16_000
#: The longest note that is read; a longer one is cut here.
MAX_NOTE_SECONDS: Final[int] = 600
#: Under this much audio (0.1 s) there is nothing to read.
_MIN_PCM_BYTES: Final[int] = 3_200


class VoiceNoteError(RuntimeError):
    """The note could not be decoded or read."""


class VoiceNoteUnavailable(VoiceNoteError):
    """No speech-to-text recognizer is running on this computer."""


def decode_to_pcm16k(data: bytes, *, max_seconds: int = MAX_NOTE_SECONDS) -> bytes:
    """Any audio file PyAV can open as 16 kHz mono int16 PCM (cut at ``max_seconds``)."""
    try:
        import av
    except ImportError as exc:  # pragma: no cover - av is a base dependency where notes run
        raise VoiceNoteError("No audio decoder is installed.") from exc

    limit = max_seconds * SAMPLE_RATE * 2
    out = bytearray()
    try:
        with av.open(io.BytesIO(data)) as container:
            if not container.streams.audio:
                raise VoiceNoteError("The file has no sound.")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                for chunk in resampler.resample(frame):
                    out += chunk.to_ndarray().tobytes()
                if len(out) >= limit:
                    break
            else:
                for chunk in resampler.resample(None):
                    out += chunk.to_ndarray().tobytes()
    except VoiceNoteError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decoder failure is one answer for the chat
        reason = type(exc).__name__
        raise VoiceNoteError(f"The voice note could not be decoded ({reason}).") from exc
    return bytes(out[:limit])


def _recognizer() -> Any:
    """The dictation's recognizer (local first), else the voice one; ``None`` without voice."""
    try:
        from dodaios.core.runtime_refs import get_speech_pipeline

        pipeline = get_speech_pipeline()
    except Exception:  # noqa: BLE001 - a headless host has no speech pipeline
        return None
    if pipeline is None:
        return None
    builder = getattr(pipeline, "_dictation_stt", None)
    if callable(builder):
        try:
            instance = builder()
        except Exception as exc:  # noqa: BLE001 - fall through to the voice recognizer
            log.debug("voice note: dictation recognizer unavailable: %s", exc)
        else:
            if instance is not None:
                return instance
    return getattr(pipeline, "_utterance_stt", None)


async def transcribe_voice_note(
    data: bytes, *, language: str | None = None, stt: Any = None
) -> str:
    """The words spoken in ``data`` ("" when nothing was heard).

    Raises :class:`VoiceNoteUnavailable` when no recognizer runs here and
    :class:`VoiceNoteError` when the note cannot be decoded or read.
    """
    recognizer = stt if stt is not None else _recognizer()
    if recognizer is None or not callable(getattr(recognizer, "transcribe_pcm", None)):
        raise VoiceNoteUnavailable("No speech-to-text recognizer is running.")
    pcm = await asyncio.to_thread(decode_to_pcm16k, data)
    if len(pcm) < _MIN_PCM_BYTES:
        return ""
    try:
        try:
            transcript = await recognizer.transcribe_pcm(pcm, language=language or None)
        except TypeError:  # a recognizer from before the keyword: the bare call is the contract
            transcript = await recognizer.transcribe_pcm(pcm)
    except Exception as exc:  # noqa: BLE001 - the chat gets one honest line
        raise VoiceNoteError(f"The voice note could not be read ({type(exc).__name__}).") from exc
    return str(getattr(transcript, "text", transcript) or "").strip()
