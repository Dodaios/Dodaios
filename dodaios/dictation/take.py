"""One dictation from the first sample to the recognized words.

A take records everything, and recognizes it once:

* **Nothing is recognized twice.** There is no live preview that a later pass
  corrects. Each stretch of the recording goes to a recognizer exactly once.
* **Pauses are where it is cut.** A short dictation is one request. A long one
  is cut at the speaker's own pauses into pieces of about half a minute, and
  each piece is recognized while the person is still speaking. After the stop
  only the last piece is left, so the wait does not grow with the length.
* **Silence is never sent.** A piece without speech makes no request, silence
  around the words is cut off and a long pause is shortened
  (:mod:`dodaios.dictation.speech_map`). That is what keeps a recognizer from
  inventing words for a pause.
* **One recognizer, one stand-in.** The recognizers are tried in order. One
  that fails or does not answer in time is set aside for the rest of the
  take, so a dead service costs its time limit once and not once per piece.
* **Nothing is lost quietly.** A piece no recognizer could read is counted in
  ``lost_audio_s``; the caller keeps the recording so it can be read again.

The take knows nothing about microphones, events or text fields. The caller
feeds it audio and awaits :meth:`Take.finish`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dodaios.dictation.speech_map import SAMPLE_RATE, SpeechMapper, condense

log = logging.getLogger("dodaios.dictation.take")

_BYTES_PER_SECOND = SAMPLE_RATE * 2

#: From this much audio on, an open piece is closed at the next pause.
PIECE_MIN_S = 30.0
#: The pause that closes a piece, by how long the piece already is. A long
#: pause most likely ends a sentence, so a young piece waits for one; an old
#: piece takes any pause, and a piece without one is cut at ``PIECE_MAX_S``.
_CUT_LADDER: tuple[tuple[float, float], ...] = (
    (PIECE_MIN_S, 0.9),
    (PIECE_MIN_S * 1.5, 0.5),
    (PIECE_MIN_S * 2.5, 0.25),
)
PIECE_MAX_S = 100.0

#: Less speech than this in a whole take is a key tap, not a dictation.
MIN_SPEECH_S = 0.25
#: A clip shorter than this is padded with silence: recognizers misread very
#: short clips.
_MIN_CLIP_S = 1.25

#: A piece with less speech than this is too short for a recognizer to tell
#: the language from; it is told the language recent speech was in.
SHORT_FOR_DETECTION_S = 6.0

#: Failures a second attempt can survive: a dropped connection, a service or
#: engine that was busy for a moment. A wrong key or an unusable recording is
#: not asked about twice.
_RETRY_REASONS = frozenset({"unavailable", "rate_limited", "engine_busy"})
#: The pause before that second attempt.
_RETRY_DELAY_S = 0.5

#: Recognizer segments beyond these values are text the model made up.
_NO_SPEECH_PROB = 0.6
_NO_SPEECH_LOGPROB = -1.0
_COMPRESSION_RATIO = 2.4


@dataclass(frozen=True, slots=True)
class Recognizer:
    """One engine that can read a piece, named for what really runs."""

    id: str
    provider: Any
    model: str = ""
    on_device: bool = False


@dataclass(frozen=True, slots=True)
class TakeResult:
    """What one take produced.

    ``text`` is the recognizers' text, pieces joined by a space and otherwise
    untouched. ``error`` is a reason code of
    :mod:`dodaios.speech.stt_failure` when a piece could not be read, else
    ``None``; ``error_detail`` is the technical text for the log.
    """

    text: str = ""
    language: str = ""
    duration_s: float = 0.0
    speech_s: float = 0.0
    lost_audio_s: float = 0.0
    error: str | None = None
    error_detail: str = ""
    recognizers: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    calls: int = 0
    latency_ms: int = 0
    pieces: int = 0
    pieces_read_early: int = 0
    wait_after_stop_ms: int = 0
    audio_sent_s: float = 0.0
    detector: str = ""

    def audit(self) -> tuple[str, ...]:
        """Facts about how the take was read, for the history. No content."""
        return (
            f"pieces:{self.pieces}",
            f"pieces_read_early:{self.pieces_read_early}",
            f"wait_after_stop_ms:{self.wait_after_stop_ms}",
            f"speech_ms:{round(self.speech_s * 1000)}",
            f"audio_sent_ms:{round(self.audio_sent_s * 1000)}",
            f"speech_detector:{self.detector or 'none'}",
        )


@dataclass(slots=True)
class _Piece:
    index: int
    start: int
    end: int
    early: bool
    text: str = ""
    language: str = ""
    read: bool = False
    lost: bool = False


def _time_limit_s(recognizer: Recognizer, audio_s: float, *, has_stand_in: bool) -> float:
    """How long a recognizer may take for ``audio_s`` of audio."""
    if recognizer.on_device:
        # Covers a model that still has to load and a slow processor. A local
        # engine cannot be interrupted, so cutting it off early only loses
        # the work it has done.
        return 60.0 + audio_s * 4.0
    if has_stand_in:
        return min(45.0, 6.0 + audio_s * 0.4)
    return min(120.0, 15.0 + audio_s)


def _segment_field(segment: Any, name: str) -> float | None:
    value = segment.get(name) if isinstance(segment, dict) else getattr(segment, name, None)
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):  # a figure that is not a number is no figure
        return None


def spoken_text(transcript: Any) -> str:
    """The transcript's text without the segments the model made up.

    A recognizer that reports per-segment confidence marks its own inventions:
    a segment it thinks holds no speech and is unsure of, or one that repeats
    itself. Those are left out. A transcript without such figures is taken as
    it is.
    """
    raw = str(getattr(transcript, "raw_text", "") or getattr(transcript, "text", "") or "")
    segments = getattr(transcript, "segments", None) or ()
    if not segments:
        return raw.strip()
    kept: list[str] = []
    dropped = 0
    for segment in segments:
        text = segment.get("text") if isinstance(segment, dict) else getattr(segment, "text", "")
        text = str(text or "").strip()
        if not text:
            continue
        no_speech = _segment_field(segment, "no_speech_prob")
        logprob = _segment_field(segment, "avg_logprob")
        ratio = _segment_field(segment, "compression_ratio")
        invented = (
            no_speech is not None
            and logprob is not None
            and no_speech > _NO_SPEECH_PROB
            and logprob < _NO_SPEECH_LOGPROB
        ) or (ratio is not None and ratio > _COMPRESSION_RATIO)
        if invented:
            dropped += 1
            continue
        kept.append(text)
    if not dropped:
        return raw.strip()
    log.info("dictation: left out %d recognizer segment(s) without speech.", dropped)
    return " ".join(kept).strip()


async def _transcribe(provider: Any, clip: bytes, language: str) -> Any:
    """One call to a recognizer, with the language where it takes one.

    The recognizer contract allows a bare ``transcribe_pcm(pcm)``. A provider
    without the ``language`` keyword is called without it rather than failed:
    it then detects the language itself.
    """
    try:
        return await provider.transcribe_pcm(clip, language=language)
    except TypeError as exc:  # only the signature's own refusal of the keyword
        message = str(exc)
        if "unexpected keyword argument" not in message or "language" not in message:
            raise
        return await provider.transcribe_pcm(clip)


def _language_tag(value: Any) -> str:
    """``"en-US"`` / ``"EN_us"`` -> ``"en"``; nothing usable -> ``""``."""
    tag = str(value or "").strip().lower().replace("_", "-")
    if not tag or tag in ("auto", "unknown", "und"):
        return ""
    return tag.split("-", 1)[0][:32]


class Take:
    """Record, cut at pauses, recognize each piece once."""

    def __init__(
        self,
        recognizers: Sequence[Recognizer] | None,
        *,
        language: str = "auto",
        language_hint: str = "",
    ) -> None:
        # ``None`` means "not known yet": the recording starts at once and the
        # caller hands the recognizers over with ``set_recognizers`` while it
        # runs. No piece is read before they are known.
        self._recognizers = list(recognizers or ())
        self._recognizers_known = asyncio.Event()
        if recognizers is not None:
            self._recognizers_known.set()
        self._language = (language or "auto").strip().lower() or "auto"
        self._language_hint = (language_hint or "").strip().lower()
        self._audio = bytearray()
        self._mapper = SpeechMapper()
        self._pieces: list[_Piece] = []
        self._piece_start = 0
        self._queue: asyncio.Queue[_Piece | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._set_aside: list[str] = []
        #: Recognizers that sat out their whole time limit in this take.
        self._timed_out: set[str] = set()
        #: A single byte of a sample whose other byte has not arrived yet.
        self._half_sample = b""
        self._closed = False
        self._cancelled = False
        self._calls = 0
        self._latency_s = 0.0
        self._errors: list[str] = []
        self._first_error: tuple[str, str] | None = None
        self._used: list[str] = []
        self._models: list[str] = []
        self._languages: list[str] = []
        self._audio_sent_s = 0.0

    # -- recording ---------------------------------------------------------- #

    @property
    def audio(self) -> bytes:
        """The whole recording as it came from the microphone."""
        return bytes(self._audio)

    @property
    def duration_s(self) -> float:
        return len(self._audio) / _BYTES_PER_SECOND

    @property
    def heard_speech(self) -> bool:
        return self._mapper.heard_speech

    def set_recognizers(self, recognizers: Sequence[Recognizer]) -> None:
        """Hand over the recognizers of a take that started without them."""
        self._recognizers = list(recognizers)
        self._recognizers_known.set()

    def warm(self) -> None:
        """Start loading the first recognizer's model, if it has one to load."""
        if not self._recognizers:
            return
        provider = self._recognizers[0].provider
        loader = getattr(provider, "warm_up", None)
        if not callable(loader):
            loader = getattr(provider, "_ensure_model", None)
        if not callable(loader):
            return

        async def _load() -> None:
            try:
                await asyncio.to_thread(loader)
            except Exception as exc:  # noqa: BLE001 - the first piece reports it properly
                log.debug("dictation recognizer warm-up failed: %s", exc)

        try:
            task = asyncio.get_running_loop().create_task(_load(), name="dictation-warm")
        except RuntimeError:  # no running loop: the first piece loads the model
            return
        self._warm_task = task

    _warm_task: asyncio.Task[None] | None = None

    def feed(self, pcm: bytes) -> None:
        """Add 16 kHz mono int16 audio from the microphone."""
        if self._closed or not pcm:
            return
        # Whole samples only: half a sample would shift every later offset of
        # the recording against its speech map.
        data = self._half_sample + pcm
        if len(data) % 2:
            self._half_sample = data[-1:]
            data = data[:-1]
        else:
            self._half_sample = b""
        if not data:
            return
        self._audio.extend(data)
        self._mapper.feed(data)
        self._maybe_cut()

    def _maybe_cut(self) -> None:
        total = self._mapper.total_samples
        open_s = (total - self._piece_start) / SAMPLE_RATE
        if open_s < PIECE_MIN_S:
            return
        pause = self._mapper.silence_run_s()
        needed = None
        for age, pause_needed in _CUT_LADDER:
            if open_s >= age:
                needed = pause_needed
        cut_at: int | None = None
        if needed is not None and pause >= needed:
            # In the middle of the pause, so both pieces keep some room tone.
            cut_at = total - int(pause * SAMPLE_RATE / 2)
        elif open_s >= PIECE_MAX_S:
            cut_at = total
        if cut_at is None or cut_at <= self._piece_start:
            return
        self._close_piece(cut_at, early=True)

    def _close_piece(self, end: int, *, early: bool) -> None:
        piece = _Piece(index=len(self._pieces), start=self._piece_start, end=end, early=early)
        self._pieces.append(piece)
        self._piece_start = end
        if self._worker is None:
            self._worker = asyncio.get_running_loop().create_task(
                self._read_pieces(), name="dictation-read"
            )
        self._queue.put_nowait(piece)

    # -- recognition -------------------------------------------------------- #

    async def _read_pieces(self) -> None:
        while True:
            piece = await self._queue.get()
            if piece is None:
                return
            try:
                await self._read_piece(piece)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one piece never ends the take
                piece.lost = True
                self._note_failure("unknown", f"{type(exc).__name__}: {exc}")
                log.warning("dictation piece %d could not be read", piece.index, exc_info=True)

    def _language_for(self, speech_s: float) -> str:
        if self._language != "auto":
            return self._language
        # Later pieces follow what the take has already been heard in.
        heard = next((p.language for p in reversed(self._pieces) if p.language), "")
        known = heard or self._language_hint
        if known and speech_s < SHORT_FOR_DETECTION_S:
            return known
        return "auto"

    def _note_failure(self, reason: str, detail: str) -> None:
        self._errors.append(reason)
        if self._first_error is None:
            self._first_error = (reason, detail)

    async def _read_piece(self, piece: _Piece) -> None:
        await self._recognizers_known.wait()
        raw = bytes(self._audio[piece.start * 2 : piece.end * 2])
        speech = self._mapper.map(piece.start, piece.end)
        if speech.speech_s < MIN_SPEECH_S:
            piece.read = True
            return
        clip = condense(raw, speech)
        clip_s = len(clip) / _BYTES_PER_SECOND
        shortfall = int(_MIN_CLIP_S * SAMPLE_RATE) - len(clip) // 2
        if shortfall > 0:
            clip += b"\x00\x00" * shortfall
            clip_s = len(clip) / _BYTES_PER_SECOND
        language = self._language_for(speech.speech_s)
        order = [r for r in self._recognizers if r.id not in self._set_aside]
        order += [r for r in self._recognizers if r.id in self._set_aside]
        attempts = list(order)
        retried = False
        position = 0
        while position < len(attempts):
            recognizer = attempts[position]
            has_stand_in = position < len(attempts) - 1
            position += 1
            limit = _time_limit_s(recognizer, clip_s, has_stand_in=has_stand_in)
            started = time.perf_counter()
            self._calls += 1
            timed_out = False
            try:
                transcript = await asyncio.wait_for(
                    _transcribe(recognizer.provider, clip, language), timeout=limit
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError:  # noted and logged with this piece's other failures
                timed_out = True
                self._timed_out.add(recognizer.id)
                reason = "unavailable"
                detail = (
                    f"{recognizer.id} did not answer within {limit:.0f}s "
                    f"for {clip_s:.1f}s of audio"
                )
            except Exception as exc:  # noqa: BLE001 - classified, logged, crossed
                from dodaios.speech.stt_failure import classify_stt_failure

                reason = classify_stt_failure(exc)
                detail = f"{recognizer.id}: {type(exc).__name__}: {exc}"
            else:
                elapsed = time.perf_counter() - started
                self._latency_s += elapsed
                self._audio_sent_s += clip_s
                piece.text = spoken_text(transcript)
                piece.language = _language_tag(getattr(transcript, "language", ""))
                piece.read = True
                self._remember(recognizer, transcript)
                log.info(
                    "dictation piece %d: %.1fs of speech read by %s in %.2fs (%d chars).",
                    piece.index,
                    speech.speech_s,
                    recognizer.id,
                    elapsed,
                    len(piece.text),
                )
                return
            self._latency_s += time.perf_counter() - started
            self._note_failure(reason, detail)
            if recognizer.id not in self._set_aside:
                self._set_aside.append(recognizer.id)
            # Nobody else is left for this piece. A failure that may pass is
            # worth one more try with the first choice; a recognizer that sat
            # out its whole time limit is not asked to do so twice.
            retry = (
                not has_stand_in
                and not retried
                and not timed_out
                and reason in _RETRY_REASONS
                and order[0].id not in self._timed_out
            )
            log.warning(
                "dictation piece %d: %s%s",
                piece.index,
                detail,
                "; the next recognizer takes it."
                if has_stand_in
                else ("; trying once more." if retry else "."),
            )
            if retry:
                retried = True
                attempts.append(order[0])
                await asyncio.sleep(_RETRY_DELAY_S)
        piece.lost = True

    def _remember(self, recognizer: Recognizer, transcript: Any) -> None:
        if recognizer.id not in self._used:
            self._used.append(recognizer.id)
        provider = recognizer.provider
        model = str(
            getattr(provider, "last_used_model", "")
            or recognizer.model
            or getattr(provider, "_model", "")
            or ""
        )
        if model and model not in self._models:
            self._models.append(model)
        # The transcript's own language first, then any its segments name: a
        # recognizer that follows a change of language reports it per segment.
        tags = [getattr(transcript, "language", "")]
        for segment in getattr(transcript, "segments", None) or ():
            tags.append(
                segment.get("language")
                if isinstance(segment, dict)
                else getattr(segment, "language", "")
            )
        for tag in tags:
            code = _language_tag(tag)
            if code and code not in self._languages:
                self._languages.append(code)

    # -- the end ------------------------------------------------------------ #

    async def finish(self) -> TakeResult:
        """Close the recording, read what is left, return the words."""
        stopped = time.perf_counter()
        self._closed = True
        # A take that learns its recognizers only now has none.
        self._recognizers_known.set()
        total = self._mapper.total_samples
        if total > self._piece_start and not self._cancelled:
            self._close_piece(total, early=False)
        if self._worker is not None and not self._cancelled:
            self._queue.put_nowait(None)
            await self._worker
        speech = self._mapper.finish()
        lost_s = sum(
            self._mapper.speech_between(p.start, p.end) for p in self._pieces if p.lost
        )
        text = " ".join(p.text for p in self._pieces if p.text).strip()
        error: str | None = None
        detail = ""
        if lost_s > 0 and self._first_error is not None:
            error, detail = self._first_error
        if not self._recognizers and speech.speech_s >= MIN_SPEECH_S:
            error, detail = "no_stt", "no recognizer is set up"
            lost_s = speech.speech_s
        return TakeResult(
            text=text,
            language=self._languages[0] if self._languages else "",
            duration_s=self.duration_s,
            speech_s=speech.speech_s,
            lost_audio_s=lost_s,
            error=error,
            error_detail=detail,
            recognizers=tuple(self._used),
            models=tuple(self._models),
            languages=tuple(self._languages),
            errors=tuple(dict.fromkeys(self._errors)),
            calls=self._calls,
            latency_ms=round(self._latency_s * 1000),
            pieces=len(self._pieces),
            pieces_read_early=sum(1 for p in self._pieces if p.early),
            wait_after_stop_ms=round((time.perf_counter() - stopped) * 1000),
            audio_sent_s=self._audio_sent_s,
            detector=speech.detector,
        )

    def cancel(self) -> None:
        """Stop reading. What was recorded stays available as :attr:`audio`."""
        self._closed = True
        self._cancelled = True
        for task in (self._worker, self._warm_task):
            if task is not None and not task.done():
                task.cancel()


class RecordingReader:
    """A finished recording read like a live take, behind a provider's shape.

    For the callers that hold a recording instead of a microphone (reading a
    kept recording again, a voice note from the phone): they call
    ``transcribe_pcm`` as on any recognizer and get the same cutting, silence
    handling and stand-in a dictation gets. ``recognizers`` is asked for on
    every call, so a key saved in between counts.
    """

    name = "dictation"

    def __init__(self, recognizers: Any, *, language_hint: Any = None) -> None:
        self._recognizers = recognizers
        self._language_hint = language_hint
        self.last_used_provider = ""
        self.last_used_model = ""

    async def transcribe_pcm(
        self,
        pcm_bytes: bytes,
        sample_rate: int = SAMPLE_RATE,
        language: str | None = None,
    ) -> Any:
        from dodaios.core.protocols import Transcript

        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"a dictation recording is {SAMPLE_RATE} Hz, got {sample_rate}")
        recognizers = self._recognizers() if callable(self._recognizers) else self._recognizers
        hint = self._language_hint() if callable(self._language_hint) else self._language_hint
        result = await read_recording(
            pcm_bytes,
            list(recognizers or ()),
            language=language or "auto",
            language_hint=str(hint or ""),
        )
        if not result.text and result.error:
            raise RecordingUnread(result.error, result.error_detail)
        self.last_used_provider = result.recognizers[0] if result.recognizers else ""
        self.last_used_model = result.models[0] if result.models else ""
        return Transcript(
            text=result.text,
            raw_text=result.text,
            language=result.language or "unknown",
            confidence=1.0 if result.text else 0.0,
        )


class RecordingUnread(RuntimeError):
    """No recognizer could read the recording. ``reason`` is a failure code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail or reason)
        self.reason = reason


async def read_recording(
    pcm: bytes,
    recognizers: Sequence[Recognizer],
    *,
    language: str = "auto",
    language_hint: str = "",
) -> TakeResult:
    """Read a finished recording the way a live take is read."""
    take = Take(recognizers, language=language, language_hint=language_hint)
    # Fed in the microphone's block size so the pieces fall where they would
    # have fallen live.
    block = 3200
    for offset in range(0, len(pcm), block):
        take.feed(pcm[offset : offset + block])
        if offset % (block * 50) == 0:
            await asyncio.sleep(0)
    return await take.finish()


__all__ = [
    "MIN_SPEECH_S",
    "PIECE_MAX_S",
    "PIECE_MIN_S",
    "Recognizer",
    "RecordingReader",
    "RecordingUnread",
    "Take",
    "TakeResult",
    "read_recording",
    "spoken_text",
]
