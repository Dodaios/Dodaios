"""One dictation from the first sample to the recognized words.

A take records everything, and no text exists before the stop:

* **No text is shown and later corrected.** There is no live preview. What a
  recognizer returned for a stretch of the recording is either the text of
  that stretch or it is thrown away unseen.
* **It is read while the person speaks.** An engine on this computer reads
  the open piece again and again: at every pause, and at the next gap between
  two words when somebody talks on without one. From such a reading the part
  up to a break the recognizer marked itself is kept as final, once the
  reading has heard enough speech behind that break and the part holds
  enough of it (:data:`KEEP_MIN_S`). The next piece begins in the gap after
  it. The end of a sentence is the preferred break. What is behind the break
  is read again with what follows.
* **After the stop only the rest is left.** A reading the speaker added
  nothing to is the text of the last piece. Otherwise what was said since
  the last kept part is read once more, so the wait does not grow with the
  length of the dictation.
* **A paid service is asked once.** It is never sent audio whose reading may
  be thrown away. Its recordings are one request up to about half a minute
  of speech and are cut at a long pause beyond that.
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
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dodaios.dictation.speech_map import (
    SAMPLE_RATE,
    SpeechMapper,
    condense_marked,
    condensed_ranges,
    recording_offset,
)

log = logging.getLogger("dodaios.dictation.take")

_BYTES_PER_SECOND = SAMPLE_RATE * 2

#: From this much SPEECH on, an open piece is closed at the next pause.
PIECE_MIN_S = 30.0
#: The pause that closes a piece, by how much speech the piece already holds.
#: A long pause most likely ends a sentence, so a young piece waits for one;
#: an old piece takes any pause, and a piece without one is cut once it holds
#: ``PIECE_MAX_S`` of speech.
_CUT_LADDER: tuple[tuple[float, float], ...] = (
    (PIECE_MIN_S, 0.9),
    (PIECE_MIN_S * 1.5, 0.5),
    (PIECE_MIN_S * 2.5, 0.25),
)
PIECE_MAX_S = 100.0

#: A cut lies at most this far back in the pause that allowed it, so the next
#: piece starts with a little room tone and not with the whole pause.
_CUT_BACK_S = 0.5

#: A reading that ends in a pause this long may stay as its piece's text
#: when the text ends a sentence: shorter than the pause between two
#: sentences, longer than a breath inside one.
AHEAD_PAUSE_S = 0.3
#: The pause that starts a reading of the open piece, by how much speech is
#: new since the last one. With little new speech it is the moment the voice
#: has clearly stopped: somebody who lets go of the key a quarter of a second
#: after the last word then finds the text already there. Somebody who talks
#: on without stopping is read at the next short gap between two words, and
#: in the end without any: what the last word of such a reading lost does not
#: matter, because only its earlier part is ever kept.
_AHEAD_LADDER: tuple[tuple[float, float], ...] = (
    (0.6, 0.15),
    (5.0, 0.12),
    (10.0, 0.0),
)
#: Silence this long lies between two words, not inside one.
_WORD_GAP_S = 0.09
#: A reading that took longer than this came from an engine too slow to read
#: ahead with: one second, plus this share of the clip's length. Such a
#: reading is still running when the person stops, and the stop would wait
#: for it. Whisper on a free graphics card needs about 0.2 s plus 2 % of the
#: clip, and three times that on a machine whose processor is busy; on a
#: processor alone it needs half the clip's length. Simulated on real
#: dictations, reading ahead still halved the wait at three times the normal
#: reading time and made single dictations slower at six times.
_AHEAD_SLOW_BASE_S = 1.0
_AHEAD_SLOW_SHARE = 0.12
#: How long a slow engine is not read ahead with. Every dictation's last
#: reading measures it again, and a fast one lifts this at once.
_AHEAD_SLOW_FOR_S = 300.0
#: Recognizer id -> the time until which it counts as too slow to read ahead.
_slow_until: dict[str, float] = {}
#: The least speech a kept part of the recording holds. Less is read again
#: with what follows: a recognizer spells names and technical words better
#: the more of the dictation it hears around them. Measured on real
#: dictations against a stronger model, parts from 12 s on read as well as
#: the whole recording in one piece; parts from 5 or 8 s on read a little
#: worse and saved only a few more milliseconds.
KEEP_MIN_S = 12.0
#: How much speech a reading must have heard behind a place for its text up
#: to that place to be final: a little behind the end of a sentence, more
#: behind a break inside one.
_AFTER_SENTENCE_S = 0.5
_AFTER_BREAK_S = 2.0
#: The end of a sentence is the better place to cut. A break inside a
#: sentence is taken instead only when it lies this much speech further on.
_PREFER_SENTENCE_S = 6.0
#: Less speech than this after a kept piece is not read by itself. A word or
#: a breath alone is what a recognizer misreads or invents text for, so it is
#: read together with the piece before it.
_TAIL_ALONE_MIN_S = 1.0
#: Up to this much "speech" behind a reading is a click, not a word. Anything
#: more was said, however short, and the reading is not the whole text.
_NOTHING_AFTER_S = 0.07
#: How far from the time a recognizer gives for the end of a sentence the
#: gap between the two sentences may lie, and how long that gap has to be.
_SENTENCE_GAP_WITHIN_S = 0.45
_SENTENCE_GAP_MIN_S = 0.09
#: What a sentence ends with, and what may stand behind that mark.
_SENTENCE_END = (".", "!", "?", "。", "！", "？")
_CLOSING_MARKS = "\"'»“”’)]"

#: A pause between two sentences at least this long starts a new paragraph.
PARAGRAPH_PAUSE_S = 2.0
#: How far a long pause may lie outside the gap between two recognized
#: sentences and still belong to it: recognizer times are approximate.
_PAUSE_SLACK_S = 0.35

#: Less speech than this in a whole take is a key tap, not a dictation.
MIN_SPEECH_S = 0.25
#: A clip shorter than this is padded with silence: recognizers misread very
#: short clips.
_MIN_CLIP_S = 1.25

#: A piece with less speech than this is too short for a recognizer to tell
#: the language from; it is told the language recent speech was in.
SHORT_FOR_DETECTION_S = 6.0

#: A recognizer this sure of the language of a long enough clip is believed
#: for the rest of the take.
_SURE_OF_LANGUAGE = 0.8

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
    #: Readings started at a pause, and how many of them became the text.
    reads_ahead: int = 0
    reads_ahead_kept: int = 0

    def audit(self) -> tuple[str, ...]:
        """Facts about how the take was read, for the history. No content."""
        return (
            f"pieces:{self.pieces}",
            f"pieces_read_early:{self.pieces_read_early}",
            f"wait_after_stop_ms:{self.wait_after_stop_ms}",
            f"reads_ahead:{self.reads_ahead}",
            f"reads_ahead_kept:{self.reads_ahead_kept}",
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
    #: Read at a pause, before anybody knew whether the piece ends there.
    ahead: bool = False
    #: Set once such a reading has its answer, whatever the answer is.
    settled: asyncio.Event | None = None
    #: A reading made at a pause that became this piece's text.
    kept: bool = False
    #: What a reading made at a pause returned, and how its clip maps onto
    #: the recording: needed to keep its finished sentences only.
    transcript: Any = None
    ranges: tuple[tuple[int, int], ...] = ()
    #: Whether such a reading ends between two words, not inside one.
    in_gap: bool = False
    #: Whether it was looked at again once the speaker carried on.
    judged: bool = False


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


def _gap_around(spans: Sequence[tuple[int, int]], at: int) -> float:
    """Seconds of silence around sample ``at`` between two stretches of speech."""
    before = max((end for _start, end in spans if end <= at), default=None)
    after = min((start for start, _end in spans if start >= at), default=None)
    if before is None or after is None:
        return 0.0
    return (after - before) / SAMPLE_RATE


def _paragraphs_at_pauses(text: str, transcript: Any, pauses: Sequence[float]) -> str:
    """``text`` with a paragraph wherever the speaker stopped between sentences.

    ``pauses`` are times in the clip where a long pause was (see
    :func:`dodaios.dictation.speech_map.condense_marked`). A recognizer that
    reports times for its segments tells which sentence ends before such a
    pause; the next sentence then starts a paragraph. A recognizer without
    times, or times that do not line up, leave the text as it is.
    """
    if not pauses or not text:
        return text
    timed: list[tuple[float, float, str]] = []
    for segment in getattr(transcript, "segments", None) or ():
        start = _segment_field(segment, "start")
        end = _segment_field(segment, "end")
        words = segment.get("text") if isinstance(segment, dict) else getattr(segment, "text", "")
        if start is None or end is None or not str(words or "").strip():
            continue
        timed.append((start, end, str(words).strip()))
    if len(timed) < 2:
        return text
    timed.sort(key=lambda item: item[0])

    from dodaios.dictation.formatting import break_before_sentences, sentence_spans

    breaks: set[int] = set()
    sentences_so_far = 0
    for current, following in zip(timed, timed[1:], strict=False):
        sentences_so_far += max(1, len(sentence_spans(current[2])))
        if not current[2].endswith((".", "!", "?")):
            continue
        if any(
            current[1] - _PAUSE_SLACK_S <= pause <= following[0] + _PAUSE_SLACK_S
            for pause in pauses
        ):
            breaks.add(sentences_so_far)
    return break_before_sentences(text, breaks) if breaks else text


_WORD_RE = re.compile(r"\S+")


def _first_words(text: str, count: int) -> str:
    """The first ``count`` words of ``text``, its line breaks included."""
    end = 0
    for number, match in enumerate(_WORD_RE.finditer(text), start=1):
        end = match.end()
        if number == count:
            break
    return text[:end]


def _ends_sentence(text: str) -> bool:
    """Whether recognized text stops where a sentence does.

    Three dots are a recognizer's mark for a speaker who broke off, so they
    do not count.
    """
    tail = text.rstrip().rstrip(_CLOSING_MARKS).rstrip()
    if not tail or tail.endswith(("...", "…")):
        return False
    return tail.endswith(_SENTENCE_END)


def _reported_confidence(transcript: Any) -> float:
    """How sure the recognizer says it is of the language, 0.0 when unsaid."""
    try:
        return float(getattr(transcript, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):  # a figure that is not a number is no figure
        return 0.0


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
        read_ahead: bool = True,
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
        #: Seconds of speech the recording held when the open piece began.
        self._speech_before_piece = 0.0
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
        #: Whether the open piece is read at the speaker's pauses. Off for a
        #: finished recording: nobody is still speaking, so there is no wait
        #: such a reading could shorten.
        self._read_ahead = read_ahead
        #: The newest reading made at a pause, in flight or answered.
        self._ahead: _Piece | None = None
        #: Seconds of speech the recording held when that reading was cut.
        self._ahead_mark = 0.0
        self._reads_ahead = 0
        self._reads_ahead_kept = 0
        #: The language this take was heard in, once enough speech said so.
        self._take_language = ""
        #: The recognizer a piece is with right now.
        self._reading: Recognizer | None = None

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
        try:
            self._maybe_read_ahead()
        except Exception:  # noqa: BLE001 - reading ahead is a help, never a gate
            # The recording goes on and is read at the stop, as it would be
            # without any reading ahead.
            self._read_ahead = False
            log.warning("dictation: reading ahead failed and is off for this take", exc_info=True)

    def _maybe_cut(self) -> None:
        # Speech decides, not the clock: a piece of silence has nothing to
        # read, and a cut by elapsed time would fall into the middle of a
        # word spoken after a long pause.
        speech_s = self._mapper.speech_so_far_s - self._speech_before_piece
        if speech_s < PIECE_MIN_S:
            return
        total = self._mapper.total_samples
        pause = self._mapper.silence_run_s()
        needed = None
        for held, pause_needed in _CUT_LADDER:
            if speech_s >= held:
                needed = pause_needed
        cut_at: int | None = None
        if needed is not None and pause >= needed:
            ahead = self._ahead
            if ahead is not None and self._mapper.speech_so_far_s <= self._ahead_mark:
                # This pause is already being read, or was. The answer is the
                # piece, with or without a sentence end; nothing is read twice.
                if ahead.settled is not None and not ahead.settled.is_set():
                    return
                if ahead.read and not ahead.lost:
                    self._keep(ahead)
                    return
            # Inside the pause, so both pieces keep some room tone.
            cut_at = total - int(min(pause / 2, _CUT_BACK_S) * SAMPLE_RATE)
        elif speech_s >= PIECE_MAX_S:
            cut_at = total
        if cut_at is None or cut_at <= self._piece_start:
            return
        self._close_piece(cut_at, early=True)

    def _close_piece(self, end: int, *, early: bool) -> None:
        piece = _Piece(index=len(self._pieces), start=self._piece_start, end=end, early=early)
        self._pieces.append(piece)
        self._piece_start = end
        self._speech_before_piece = self._mapper.speech_so_far_s
        # A reading made at a pause belonged to the piece that just closed.
        self._ahead = None
        self._ahead_mark = self._speech_before_piece
        self._enqueue(piece)

    def _enqueue(self, piece: _Piece) -> None:
        if self._worker is None:
            self._worker = asyncio.get_running_loop().create_task(
                self._read_pieces(), name="dictation-read"
            )
        self._queue.put_nowait(piece)

    # -- reading at a pause -------------------------------------------------- #

    def _lead(self) -> Recognizer | None:
        """The recognizer the next piece goes to first."""
        for recognizer in self._recognizers:
            if recognizer.id not in self._set_aside:
                return recognizer
        return self._recognizers[0] if self._recognizers else None

    def _maybe_read_ahead(self) -> None:
        """Read the open piece up to the pause the speaker is making.

        One such reading at a time, and only when there is speech it has not
        seen. Only an engine on this computer is asked: it is idle anyway. A
        service is never sent audio whose reading may be thrown away. Its
        pieces are cut at long pauses alone, as before: cutting them earlier
        without the recognizer's own breaks cost one word in seventy on the
        recordings this was measured with.
        """
        if not self._read_ahead or self._closed or not self._recognizers_known.is_set():
            return
        ahead = self._ahead
        if ahead is not None and ahead.settled is not None and not ahead.settled.is_set():
            return
        pause = self._mapper.silence_run_s()
        speech_now = self._mapper.speech_so_far_s
        if (
            ahead is not None
            and not ahead.judged
            and ahead.read
            and not ahead.lost
            and speech_now > self._ahead_mark
        ):
            # The speaker carried on, so the pause that reading ended in is
            # over and its length is known: long enough, and the reading
            # stays as the text of everything before it.
            ahead.judged = True
            if self._keepable(ahead):
                self._keep(ahead)
        new_speech = speech_now - self._ahead_mark
        needed: float | None = None
        for held, pause_needed in _AHEAD_LADDER:
            if new_speech >= held:
                needed = pause_needed
        if needed is None or pause < needed:
            return
        lead = self._lead()
        if lead is None or not lead.on_device:
            return
        if _slow_until.get(lead.id, 0.0) > time.perf_counter():
            return
        end = self._mapper.total_samples - int(min(pause / 2, _CUT_BACK_S) * SAMPLE_RATE)
        if end <= self._piece_start:
            return
        piece = _Piece(
            index=len(self._pieces),
            start=self._piece_start,
            end=end,
            early=True,
            ahead=True,
            settled=asyncio.Event(),
            in_gap=pause >= _WORD_GAP_S,
        )
        self._ahead = piece
        self._ahead_mark = speech_now
        self._reads_ahead += 1
        self._enqueue(piece)

    def _keepable(self, piece: _Piece) -> bool:
        """Whether a reading made at a pause may stay as its piece's text."""
        return (
            piece.read
            and not piece.lost
            and piece.in_gap
            and self._mapper.pause_around(piece.end) >= AHEAD_PAUSE_S
            and self._mapper.speech_between(piece.start, piece.end) >= KEEP_MIN_S
            and _ends_sentence(piece.text)
        )

    def _keep(self, piece: _Piece) -> None:
        """Make a reading made at a pause the text of its piece."""
        piece.index = len(self._pieces)
        piece.kept = True
        piece.transcript = None
        piece.ranges = ()
        self._pieces.append(piece)
        self._piece_start = piece.end
        # Speech that came after the pause belongs to the piece that opens now.
        self._speech_before_piece = self._mapper.speech_so_far_s - self._mapper.speech_between(
            piece.end, self._mapper.total_samples
        )
        self._ahead = None
        self._ahead_mark = self._speech_before_piece
        self._reads_ahead_kept += 1

    def _ahead_settled(self, piece: _Piece) -> None:
        if piece.settled is not None:
            piece.settled.set()
        if self._closed or piece is not self._ahead:
            return  # the stop decides about it, or a cut went past it
        if self._keepable(piece):
            self._keep(piece)
        elif piece.lost:
            # Nobody read it. The next pause may try again with what follows.
            self._ahead = None
        else:
            self._keep_finished(piece)

    def _keep_finished(self, piece: _Piece) -> bool:
        """Keep the earlier part of a reading that does not end a sentence.

        The speaker paused inside a sentence, carried on before the answer
        came, or never paused at all. The text up to a break the recognizer
        marked itself is still final when the reading heard enough speech
        behind that break. The end of a sentence is preferred; a break inside
        one is taken when no sentence ended for a while. The cut is put into
        the gap between two words found in the recording itself, and the next
        piece begins there.
        """
        if not piece.read or piece.lost or piece.transcript is None or not piece.ranges:
            return False
        timed: list[tuple[float, float, str]] = []
        for segment in getattr(piece.transcript, "segments", None) or ():
            start = _segment_field(segment, "start")
            end = _segment_field(segment, "end")
            said = (
                segment.get("text") if isinstance(segment, dict) else getattr(segment, "text", "")
            )
            if start is None or end is None:
                return False
            timed.append((start, end, str(said or "")))
        if len(timed) < 2:
            return False
        words = [len(text.split()) for _start, _end, text in timed]
        if sum(words) != len(piece.text.split()):
            return False  # the text is no longer the segments' text, word for word
        ranges = list(piece.ranges)
        total = self._mapper.total_samples
        sentence: tuple[int, int] | None = None
        other: tuple[int, int] | None = None
        # At least the last segment stays: it is what is still being said.
        for keep in range(len(timed) - 1, 0, -1):
            between = (timed[keep - 1][1] + timed[keep][0]) / 2
            offset = recording_offset(ranges, between)
            if offset is None:
                continue
            cut = self._mapper.quiet_near(
                piece.start + offset,
                within_s=_SENTENCE_GAP_WITHIN_S,
                min_quiet_s=_SENTENCE_GAP_MIN_S,
            )
            if cut is None or not piece.start < cut < piece.end:
                continue
            if self._mapper.speech_between(piece.start, cut) < KEEP_MIN_S:
                break  # an earlier break holds even less
            if self._mapper.speech_between(cut, total) < _TAIL_ALONE_MIN_S:
                continue
            heard_behind = self._mapper.speech_between(cut, piece.end)
            ends = _ends_sentence("".join(text for _s, _e, text in timed[:keep]))
            if ends and heard_behind >= _AFTER_SENTENCE_S:
                sentence = (keep, cut)
                break
            if other is None and heard_behind >= _AFTER_BREAK_S:
                other = (keep, cut)
        chosen = sentence
        if other is not None and (
            sentence is None
            or self._mapper.speech_between(sentence[1], other[1]) > _PREFER_SENTENCE_S
        ):
            chosen = other
        if chosen is None:
            return False
        keep, cut = chosen
        text = _first_words(piece.text, sum(words[:keep])).rstrip()
        if not text:
            return False
        piece.end = cut
        piece.text = text
        self._keep(piece)
        return True

    async def _settle_ahead(self, total: int) -> None:
        """At the stop: keep the reading made at the last pause, or drop it.

        A reading still on its way is waited for rather than raced: an engine
        on this computer reads one clip at a time, and its answer is usually
        the whole remaining text.
        """
        ahead, self._ahead = self._ahead, None
        if ahead is None or ahead.settled is None:
            return
        await ahead.settled.wait()
        if self._cancelled or not ahead.read or ahead.lost or ahead.start != self._piece_start:
            return
        after = self._mapper.speech_between(ahead.end, total)
        if ahead.in_gap and after < _NOTHING_AFTER_S:
            # Nothing was said after it: the reading is the piece.
            ahead.end = total
            self._keep(ahead)
        elif after >= _TAIL_ALONE_MIN_S and self._keepable(ahead):
            self._keep(ahead)
        else:
            self._keep_finished(ahead)

    def _rejoin_short_tail(self, total: int) -> None:
        """Give a few last sounds back to the kept piece before them."""
        if not self._pieces:
            return
        last = self._pieces[-1]
        if not last.kept or last.end != self._piece_start:
            return
        tail = self._mapper.speech_between(self._piece_start, total)
        if _NOTHING_AFTER_S <= tail < _TAIL_ALONE_MIN_S:
            self._pieces.pop()
            self._piece_start = last.start
            self._reads_ahead_kept -= 1

    # -- recognition -------------------------------------------------------- #

    async def _read_pieces(self) -> None:
        while True:
            piece = await self._queue.get()
            if piece is None:
                return
            if self._cancelled:
                if piece.settled is not None:
                    piece.settled.set()
                continue
            try:
                await self._read_piece(piece)
            except asyncio.CancelledError:
                if piece.settled is not None:
                    piece.settled.set()
                raise
            except Exception as exc:  # noqa: BLE001 - one piece never ends the take
                piece.lost = True
                self._note_failure("unknown", f"{type(exc).__name__}: {exc}")
                log.warning("dictation piece %d could not be read", piece.index, exc_info=True)
            if piece.ahead:
                try:
                    self._ahead_settled(piece)
                except Exception:  # noqa: BLE001 - the stop reads the piece instead
                    if piece.settled is not None:
                        piece.settled.set()
                    if self._ahead is piece:
                        self._ahead = None
                    log.warning("dictation: a reading ahead could not be used", exc_info=True)

    def _language_for(self, speech_s: float) -> str:
        if self._language != "auto":
            return self._language
        if self._take_language:
            # Enough of this take was already heard to know its language.
            # Finding it out again costs the recognizer a second pass over
            # the audio on every reading.
            return self._take_language
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
        clip, long_pauses = condense_marked(raw, speech, mark_pause_s=PARAGRAPH_PAUSE_S)
        clip_s = len(clip) / _BYTES_PER_SECOND
        shortfall = int(_MIN_CLIP_S * SAMPLE_RATE) - len(clip) // 2
        if shortfall > 0:
            clip += b"\x00\x00" * shortfall
            clip_s = len(clip) / _BYTES_PER_SECOND
        language = self._language_for(speech.speech_s)
        order = [r for r in self._recognizers if r.id not in self._set_aside]
        order += [r for r in self._recognizers if r.id in self._set_aside]
        # A reading made at a pause may be thrown away, so it asks the first
        # recognizer only: the stand-in is for speech that would be lost.
        attempts = order[:1] if piece.ahead else list(order)
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
            self._reading = recognizer
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
                piece.text = _paragraphs_at_pauses(
                    spoken_text(transcript), transcript, long_pauses
                )
                piece.language = _language_tag(getattr(transcript, "language", ""))
                piece.read = True
                if recognizer.on_device:
                    if elapsed > _AHEAD_SLOW_BASE_S + _AHEAD_SLOW_SHARE * clip_s:
                        if recognizer.id not in _slow_until:
                            log.info(
                                "dictation: %s needed %.1fs for %.1fs of audio; it is not "
                                "read ahead with for now.",
                                recognizer.id,
                                elapsed,
                                clip_s,
                            )
                        _slow_until[recognizer.id] = time.perf_counter() + _AHEAD_SLOW_FOR_S
                    else:
                        _slow_until.pop(recognizer.id, None)
                if piece.ahead:
                    piece.transcript = transcript
                    piece.ranges = tuple(condensed_ranges(speech))
                self._remember(recognizer, transcript)
                if (
                    language == "auto"
                    and piece.language
                    and speech.speech_s >= SHORT_FOR_DETECTION_S
                    and _reported_confidence(transcript) >= _SURE_OF_LANGUAGE
                ):
                    self._take_language = piece.language
                log.info(
                    "dictation piece %d: %.1fs of speech read by %s in %.2fs (%d chars%s).",
                    piece.index,
                    speech.speech_s,
                    recognizer.id,
                    elapsed,
                    len(piece.text),
                    ", at a pause" if piece.ahead else "",
                )
                return
            finally:
                self._reading = None
            self._latency_s += time.perf_counter() - started
            if piece.ahead and not timed_out:
                # Nobody waits for this reading and no speech is lost with it:
                # the same audio is read again at the next pause or the stop.
                # An engine that was only still starting must stay the first
                # choice for that, so nothing is set aside or reported.
                piece.lost = True
                log.info("dictation: a reading at a pause was not made (%s).", detail)
                return
            self._note_failure(reason, detail)
            if recognizer.id not in self._set_aside:
                self._set_aside.append(recognizer.id)
            # Nobody else is left for this piece. A failure that may pass is
            # worth one more try with the first choice; a recognizer that sat
            # out its whole time limit is not asked to do so twice.
            retry = (
                not has_stand_in
                and not piece.ahead
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
                else (
                    "; trying once more."
                    if retry
                    else ("; it is read again at the stop." if piece.ahead else ".")
                ),
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
        if not self._cancelled:
            try:
                await self._settle_ahead(total)
                if not self._cancelled:
                    self._rejoin_short_tail(total)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - what is left is read now instead
                log.warning("dictation: the last reading ahead could not be used", exc_info=True)
        if total > self._piece_start and not self._cancelled:
            self._close_piece(total, early=False)
        if self._worker is not None and not self._cancelled:
            self._queue.put_nowait(None)
            await self._worker
        speech = self._mapper.finish()
        lost_s = sum(
            self._mapper.speech_between(p.start, p.end) for p in self._pieces if p.lost
        )
        text = self._joined_text()
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
            reads_ahead=self._reads_ahead,
            reads_ahead_kept=self._reads_ahead_kept,
        )

    def _joined_text(self) -> str:
        """The pieces' text in order; a long pause between two is a paragraph."""
        spans = self._mapper.finish().spans
        out = ""
        previous_end = 0
        for piece in self._pieces:
            if not piece.text:
                continue
            words = piece.text.strip()
            if out:
                out = out.rstrip()
                if words[:1].islower() and out.endswith(".") and not out.endswith(".."):
                    # The recognizer closed the piece before with a full stop
                    # and wrote this one as the rest of the sentence: the
                    # speaker only took a breath there.
                    out = out[:-1] + ","
                gap = _gap_around(spans, previous_end)
                ends_sentence = out.endswith((".", "!", "?"))
                out += "\n\n" if gap >= PARAGRAPH_PAUSE_S and ends_sentence else " "
            out += words
            previous_end = piece.end
        return out.strip()

    def cancel(self) -> None:
        """Stop reading. What was recorded stays available as :attr:`audio`."""
        self._closed = True
        self._cancelled = True
        ahead = self._ahead
        worker = self._worker
        reading = self._reading
        if worker is not None and not worker.done() and reading is not None and reading.on_device:
            # An engine on this computer cannot be interrupted: cutting its
            # call off costs the engine itself, and the next dictation waits
            # for a new one. It finishes the clip it has and reads no more.
            self._queue.put_nowait(None)
            worker = None
        elif ahead is not None and ahead.settled is not None:
            ahead.settled.set()
        for task in (worker, self._warm_task):
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
    take = Take(recognizers, language=language, language_hint=language_hint, read_ahead=False)
    # Fed in the microphone's block size so the pieces fall where they would
    # have fallen live.
    block = 3200
    for offset in range(0, len(pcm), block):
        take.feed(pcm[offset : offset + block])
        if offset % (block * 50) == 0:
            await asyncio.sleep(0)
    return await take.finish()


__all__ = [
    "AHEAD_PAUSE_S",
    "KEEP_MIN_S",
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
