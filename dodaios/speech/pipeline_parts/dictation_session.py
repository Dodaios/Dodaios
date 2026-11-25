"""One dictation session, its finish step and insertion.

Moved out of ``pipeline.py`` without a behaviour change. Module-level names
of the pipeline are read through ``_pl`` at call time so the pipeline module
stays the one place that owns and patches them.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import numpy as np

from dodaios.speech import pipeline as _pl

if TYPE_CHECKING:
    from typing import Any


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class DictationSessionMixin(_HostBase):
    """One dictation session, its finish step and insertion."""

    async def _dictation_session(self) -> None:
        """Record one dictation, recognize it once, deliver the text.

        The microphone is taken over (or opened when nothing else holds it)
        and everything it hears goes into one take
        (:mod:`dodaios.dictation.take`). No text exists while the person
        speaks: the take cuts a long recording at the speaker's own pauses and
        reads each piece once, in the background, so after the stop only the
        last piece is left to read. Then the text is formatted, delivered and
        recorded by ``_finish_dictation``.

        The stop event, the recording cap, a hangup and the end of the input
        stream each end the recording; a hangup or the bar's discard delivers
        nothing. The brain, TTS and the turn state machine are not involved,
        and the whole session is fail-open so a dictation error never breaks a
        later voice turn. Exactly one ``DictationCompleted`` ends it.
        """
        from dodaios.dictation.audio_preprocessing import (
            AudioQualityAccumulator,
            assess_desktop_audio_preprocessing,
        )
        from dodaios.dictation.take import MIN_SPEECH_S, Take, TakeResult

        # ``getattr`` defaults keep pipelines built via ``__new__`` working.
        cfg = getattr(self, "_dictation_cfg", None)
        target = getattr(self, "_dictation_target", "chat")
        pinned_language = (
            str(getattr(cfg, "language", "auto") or "auto").strip().lower() or "auto"
        )
        # The take starts without its recognizers, so nothing stands between
        # the key press and the open microphone. Which engines read it is
        # found out beside the recording, off the event loop: after a saved
        # key or on the first press that means building providers and asking
        # the hardware, and a first word must not be lost to that.
        take = Take(
            None,
            language=pinned_language,
            language_hint=self._recent_dictation_language(),
        )

        async def _find_recognizers() -> None:
            recognizers: tuple[Any, ...] = ()
            try:
                resolution = await asyncio.to_thread(self._dictation_resolution)
                recognizers = tuple(resolution.recognizers)
            except Exception as exc:  # noqa: BLE001 — reported as "nothing to read with"
                _pl.log.warning("Dictation recognizers could not be resolved: %s", exc)
            take.set_recognizers(recognizers)
            # The engine starts loading while the person speaks, not with the
            # first piece to read.
            take.warm()

        recognizers_task = asyncio.create_task(
            _find_recognizers(), name="dictation-recognizers"
        )
        handle = getattr(self, "_dictation_parakeet_rest", None)
        if handle is not None:
            handle.cancel()
            self._dictation_parakeet_rest = None

        audio_cfg = getattr(getattr(self, "_config", None), "audio", None)
        audio_preprocessing = assess_desktop_audio_preprocessing(
            echo_cancellation_requested=bool(
                getattr(audio_cfg, "echo_cancellation", True)
            ),
        )
        audio_quality = AudioQualityAccumulator()
        capture_reported_dropouts = 0
        capture_restart_count = 0
        capture_overflows = 0
        started_at = time.monotonic()
        hung_up = False
        # Set when the RECORDING ended before the person did.
        capture_error: str | None = None
        # True once delivery was entered, so the crash handler below never
        # delivers a second time.
        finished = False
        try:
            # ONE microphone owner at a time: this takes the live wake stream
            # over when there is one and opens its own capture otherwise
            # (AP-24). The wake side gets its stream back on exit.
            async with self._capture_dictation_input() as source:
                # PortAudio's overflow counter is cumulative for the stream;
                # what this dictation lost is the difference from here.
                overflow_base = _pl._capture_counter(source, "overflow_count")

                async def _drain() -> None:
                    async for chunk in source.stream():
                        audio_quality.add_chunk(
                            chunk.pcm,
                            sample_rate_hz=int(
                                getattr(chunk, "sample_rate", 16_000) or 16_000
                            ),
                            timestamp_ns=int(getattr(chunk, "timestamp_ns", 0) or 0),
                        )
                        take.feed(chunk.pcm)
                        # The live loudness moves the bar's and the composer's
                        # waveform; zero cost when nobody is subscribed.
                        if _pl.mic_level.has_subscribers():
                            samples = _pl.pcm_bytes_to_np(chunk.pcm)
                            if samples.size:
                                _pl.mic_level.feed(
                                    float(np.sqrt(np.mean(np.square(samples))))
                                )

                drain_task = asyncio.create_task(_drain(), name="dictation-drain")
                stop_task = asyncio.create_task(self._dictation_stop_event.wait())
                # Beside a live call the hangup event is the CALL's: hanging up
                # the conversation must not throw away what is being dictated.
                hangup_event = (
                    asyncio.Event()
                    if getattr(self, "_dictation_beside_call", False)
                    else self._hangup_event
                )
                hangup_task = asyncio.create_task(hangup_event.wait())
                # A recording the HOLD key started is owed a release edge; the
                # watchdog sets the stop event when the key is physically up
                # and that edge never came (BUG-191).
                hold_task = (
                    asyncio.create_task(
                        self._watch_dictation_hold_key(), name="dictation-hold-watch"
                    )
                    if getattr(self, "_dictation_started_by", "") == "hold_key"
                    else None
                )
                try:
                    done, _pending = await asyncio.wait(
                        {stop_task, hangup_task, drain_task},
                        # ``None`` waits as long as it takes, which is what a
                        # cap of 0 means.
                        timeout=self._dictation_max_s or None,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    hung_up = hangup_task in done or hangup_event.is_set()
                    if getattr(self, "_dictation_discard_requested", False):
                        # The bar's close-X: nothing read, nothing delivered.
                        hung_up = True
                    if stop_task in done:
                        ended_by = "discard" if hung_up else "stop"
                    elif hangup_task in done:
                        ended_by = "hangup"
                    elif drain_task in done:
                        ended_by = "input ended"
                    else:
                        ended_by = f"the {self._dictation_max_s:.0f}s recording cap"
                    _pl.log.info(
                        "dictation recording ended by %s after %.1fs (via=%s).",
                        ended_by,
                        time.monotonic() - started_at,
                        getattr(self, "_dictation_started_by", "") or "unknown",
                    )
                    if drain_task in done and not drain_task.cancelled():
                        drain_exc = drain_task.exception()
                        if drain_exc is not None:
                            # The microphone went away. What was recorded is
                            # still read; the outcome says the recording was
                            # cut short instead of presenting it as whole.
                            capture_error = "recording_interrupted"
                            _pl.log.warning(
                                "dictation recording ended early — %s: %s",
                                capture_error,
                                f"{type(drain_exc).__name__}: {drain_exc}".strip(),
                            )
                        else:
                            _pl.log.info(
                                "dictation input stream ended; reading what was "
                                "recorded."
                            )
                    capture_overflows = max(
                        0, _pl._capture_counter(source, "overflow_count") - overflow_base
                    )
                    capture_reported_dropouts = (
                        int(getattr(source, "dropped_frames", 0) or 0) + capture_overflows
                    )
                    capture_restart_count = int(getattr(source, "restart_count", 0) or 0)
                finally:
                    side_tasks = [drain_task, stop_task, hangup_task]
                    if hold_task is not None:
                        side_tasks.append(hold_task)
                    for t in side_tasks:
                        t.cancel()
                    for t in side_tasks:
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                            # Cancelled above; a drain error was read already.
                            pass

            # The microphone is closed on every end path. Now is the moment to
            # say "no longer listening, still working". A hangup skips it:
            # nothing is read and ``DictationCompleted`` follows at once.
            if hung_up:
                take.cancel()
                result = TakeResult(duration_s=take.duration_s)
            else:
                await self._publish_dictation_event(
                    _pl.DictationTranscribing(source_layer="speech.dictation")
                )
                await recognizers_task
                result = await take.finish()

            wall_clock_s = max(0.0, time.monotonic() - started_at)
            quality_metrics = audio_quality.snapshot(
                reported_dropouts=capture_reported_dropouts
            )
            finished = True
            final_text = await self._finish_dictation(
                raw_text=result.text,
                language=result.language,
                # The length of the recording, from the audio itself: the
                # statistics divide the word count by it.
                duration_s=result.duration_s,
                target=target,
                hung_up=hung_up,
                # A recording that ended early outranks a recognition error:
                # it explains a short text every later layer would otherwise
                # present as complete.
                stt_error=capture_error or result.error,
                lost_audio_s=result.lost_audio_s,
                dropped_audio_s=quality_metrics.dropout_duration_ms / 1000.0,
                no_speech=not hung_up and result.speech_s < MIN_SPEECH_S,
                audio=take.audio,
                stt_providers=result.recognizers,
                stt_models=result.models,
                detected_languages=result.languages,
                stt_latency_ms=result.latency_ms,
                stt_calls=result.calls,
                stt_errors=result.errors,
                stt_audit=(
                    *result.audit(),
                    f"capture_overflows:{capture_overflows}",
                    f"capture_restarts:{capture_restart_count}",
                    *audio_preprocessing.audit(),
                ),
                audio_sample_rate_hz=quality_metrics.sample_rate_hz,
                audio_rms=quality_metrics.rms,
                audio_clipping_ratio=quality_metrics.clipping_ratio,
                audio_dropouts=quality_metrics.dropout_count,
                audio_dropout_ms=quality_metrics.dropout_duration_ms,
            )
            _pl.log.info(
                "🎙️ dictation ended (%d chars, %.1fs recorded, %.1fs of speech, "
                "%.1fs elapsed, text %.2fs after the stop, target=%s, read by %s "
                "in %d piece(s), %d of %d reading(s) ahead kept%s%s%s).",
                len(final_text),
                result.duration_s,
                result.speech_s,
                wall_clock_s,
                result.wait_after_stop_ms / 1000.0,
                target,
                ", ".join(result.recognizers) or "nothing",
                result.pieces,
                result.reads_ahead_kept,
                result.reads_ahead,
                ", hung up" if hung_up else "",
                f", capture: {capture_error}" if capture_error else "",
                (
                    f", LOST {result.lost_audio_s:.1f}s of speech "
                    f"({result.error}: {result.error_detail or 'no detail'})"
                    if result.lost_audio_s
                    else (
                        f", {len(result.errors)} failed call(s) covered by the stand-in"
                        if result.errors
                        else ""
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001 — dictation must never break voice
            _pl.log.warning("dictation session crashed (non-fatal)", exc_info=True)
            if finished:
                # Delivery published its own final text; entering it again
                # would publish twice.
                return
            # Before delivery: the failure goes THROUGH the normal finish, so
            # it is published, recorded as ``failed`` and keeps its recording.
            try:
                quality_metrics = audio_quality.snapshot(
                    reported_dropouts=capture_reported_dropouts
                )
                await self._finish_dictation(
                    raw_text="",
                    language="",
                    duration_s=take.duration_s,
                    target=target,
                    hung_up=False,
                    stt_error=_pl.classify_stt_failure(exc),
                    audio=take.audio,
                    audio_sample_rate_hz=quality_metrics.sample_rate_hz,
                    audio_rms=quality_metrics.rms,
                    audio_clipping_ratio=quality_metrics.clipping_ratio,
                    audio_dropouts=quality_metrics.dropout_count,
                    audio_dropout_ms=quality_metrics.dropout_duration_ms,
                )
            except Exception:  # noqa: BLE001 — the fallback must not raise either
                _pl.log.debug("dictation failure record failed", exc_info=True)
                try:
                    await self._publish_event(
                        _pl.DictationTranscript(
                            source_layer="speech.dictation", text="", is_final=True
                        )
                    )
                except Exception:  # noqa: BLE001, S110
                    # The primary failure is already logged; this event is optional.
                    pass
        finally:
            # Nothing of this recording keeps reading after the session, and
            # the Parakeet model is released once nobody has dictated for a
            # while.
            take.cancel()
            if not recognizers_task.done():
                recognizers_task.cancel()
            try:
                self._rest_dictation_parakeet()
            except Exception:  # noqa: BLE001 — a release is tidying, never a gate
                _pl.log.debug("Parakeet idle release not scheduled", exc_info=True)
            # Terminal-event guarantee. Surfaces open on ``DictationStarted``
            # and close on ``DictationCompleted``. A cancellation skips the
            # handler above and a crash inside delivery can end before its own
            # completion; both land here. Scheduled rather than awaited,
            # because awaiting inside a cancelled task is not reliable.
            if not getattr(self, "_dictation_completion_published", True):
                self._dictation_completion_published = True
                quality_metrics = audio_quality.snapshot(
                    reported_dropouts=capture_reported_dropouts
                )
                self._publish_event_soon(
                    _pl.DictationCompleted(
                        source_layer="speech.dictation",
                        outcome="cancelled",
                        # A hold key's early start taken back by a shortcut
                        # is not news: nobody dictated, so nothing is said.
                        detail=(
                            ""
                            if getattr(self, "_dictation_leave_no_trace", False)
                            else "The dictation ended before it produced text."
                        ),
                        duration_s=take.duration_s,
                        audio_sample_rate_hz=quality_metrics.sample_rate_hz,
                        audio_rms=quality_metrics.rms,
                        audio_clipping_ratio=quality_metrics.clipping_ratio,
                        audio_dropouts=quality_metrics.dropout_count,
                        audio_dropout_ms=quality_metrics.dropout_duration_ms,
                    )
                )

    #: How much audio a CLOUD reading needs before it is allowed to steer later
    #: dictations. Under this, the provider is guessing from too little context
    #: — which is the defect this anchor exists to route around, so accepting a
    #: short reading here would let the guess teach itself.
    _LANGUAGE_ANCHOR_MIN_S = 6.0

    #: How many readings the anchor remembers. Small enough to follow a speaker
    #: who switches language within a few dictations, large enough that one
    #: mis-detected clip cannot flip it on its own.
    _LANGUAGE_ANCHOR_HISTORY = 5

    def _remember_dictation_language(self, language: str, *, on_device: bool) -> None:
        """Record one reading of what this user dictates in. Never raises.

        The anchor behind ``_recent_dictation_language``. An ``on_device``
        reading is trusted outright — a local decoder cannot have translated the
        audio, so its answer is about the SOUND. A cloud reading is a claim
        about a transcript that may itself be a translation, so the caller only
        offers one when there was enough audio to make the claim worth
        something, and it still only ever gets a vote rather than the decision.
        """
        code = str(language or "").strip().lower()
        if not code or code in ("auto", "unknown", "und"):
            return
        readings = getattr(self, "_dictation_language_readings", None)
        if readings is None:
            from collections import deque

            readings = deque(maxlen=self._LANGUAGE_ANCHOR_HISTORY)
            self._dictation_language_readings = readings
        # An on-device reading is worth the whole window, because it is the one
        # signal a translation cannot fake: one of them outvotes a run of cloud
        # guesses instead of waiting its turn behind them.
        readings.extend([code] * (readings.maxlen if on_device else 1))

    def _prime_dictation_language_anchor(self) -> None:
        """Seed the anchor from the stored history, once per process.

        Without this the anchor is empty after every app start, so the first
        short dictation of a session is back to asking two seconds of audio
        which language it is — the exact case this exists to avoid. The history
        already holds the answer: what this person dictated in yesterday is a
        better opening guess than nothing at all.

        Cheap enough to do inline (measured: ~1.6 ms for a 147 KB history) and
        it happens on the first dictation, never at boot (AP-26). Failure is a
        no-op: an unreadable history costs an opening guess, never a dictation.
        """
        if getattr(self, "_dictation_anchor_primed", False):
            return
        self._dictation_anchor_primed = True
        try:
            from dodaios.dictation.history import DictationHistory

            entries = DictationHistory().list_all(include_discarded=True)
            recent = [
                entry
                for entry in entries
                if float(getattr(entry, "duration_s", 0.0) or 0.0)
                >= self._LANGUAGE_ANCHOR_MIN_S
            ][: self._LANGUAGE_ANCHOR_HISTORY]
            # Oldest first, so the newest readings are the ones the bounded
            # window keeps — a person who switched language last week must not
            # be anchored to the language they used before that.
            for entry in reversed(recent):
                self._remember_dictation_language(
                    str(getattr(entry, "language", "") or ""), on_device=False
                )
        except Exception:  # noqa: BLE001 — an opening guess is never worth a failure
            _pl.log.debug("dictation language anchor priming failed", exc_info=True)

    def _recent_dictation_language(self) -> str:
        """The language recent dictations agree on, or ``""`` when unclear.

        Read at the START of a dictation, where it becomes the session language
        a short recording could never establish for itself. A MAJORITY rather
        than the last reading, so a single mis-detected clip cannot redirect the
        next one; ties resolve to ``""``, which simply restores auto-detect.
        """
        self._prime_dictation_language_anchor()
        readings = getattr(self, "_dictation_language_readings", None)
        if not readings:
            return ""
        from collections import Counter

        counts = Counter(readings).most_common()
        if len(counts) > 1 and counts[0][1] == counts[1][1]:
            return ""
        return counts[0][0]

    async def _publish_dictation_event(self, event: Any) -> bool:
        """Deliver to healthy observers in order without waiting on a dead UI.

        The bus fans out concurrently, so an unrelated stalled observer cannot
        delay a healthy recipient. The bounded await still joins cancellation;
        no publication task is left behind to reorder a later dictation.
        """
        try:
            await asyncio.wait_for(
                self._publish_event(event), timeout=_pl._DICTATION_EVENT_TIMEOUT_S
            )
        except TimeoutError:
            _pl.log.warning(
                "Dictation event %s exceeded %.1fs; abandoning stalled observers.",
                type(event).__name__,
                _pl._DICTATION_EVENT_TIMEOUT_S,
            )
            return False
        return True

    async def _tell_silent_microphone(self, input_name: str) -> None:
        """Publish which microphone a dictation heard nothing from (never raises).

        The window turns it into the notice that names the input and opens the
        microphone picker; the bar keeps showing the dictation's own sentence.
        """
        try:
            await self._publish_event(
                _pl.MicrophoneTrouble(
                    source_layer="speech.pipeline",
                    reason="silent",
                    device=input_name,
                    feature="dictation",
                    automatic=getattr(self, "_input_device", None) == "auto-headset",
                )
            )
        except Exception:  # noqa: BLE001 - a notice must never cost the dictation its result
            _pl.log.debug("The silent-microphone notice could not be published.", exc_info=True)

    async def _finish_dictation(
        self,
        *,
        raw_text: str,
        language: str,
        duration_s: float,
        target: str,
        hung_up: bool,
        stt_error: str | None = None,
        lost_audio_s: float = 0.0,
        dropped_audio_s: float = 0.0,
        audio: bytes | None = None,
        stt_providers: tuple[str, ...] = (),
        stt_models: tuple[str, ...] = (),
        detected_languages: tuple[str, ...] = (),
        stt_latency_ms: int = 0,
        stt_calls: int = 0,
        stt_errors: tuple[str, ...] = (),
        stt_audit: tuple[str, ...] = (),
        audio_sample_rate_hz: int = 0,
        audio_rms: float = 0.0,
        audio_clipping_ratio: float = 0.0,
        audio_dropouts: int = 0,
        audio_dropout_ms: int = 0,
        no_speech: bool = False,
    ) -> str:
        """Format, deliver and record one finished dictation. Returns the text.

        ``no_speech`` says the recording held no speech at all (a tap on the
        key, a muted or wrong microphone). No recognizer was asked then, and
        the outcome names the microphone as the thing to check.

        Split out of ``_dictation_session`` so the delivery half is testable
        without a microphone. Every step degrades on its own: a failed cleanup
        falls back to the raw transcript, a failed insertion falls back to "it
        is on your clipboard", and a failed history write costs nothing but the
        history entry.

        ``stt_error`` is the transcription failure, if there was one. It is what
        makes ``failed`` distinguishable from ``empty``, so it is carried into
        the completion event and the history row rather than logged and dropped.
        It is normalised to a reason code HERE rather than trusted from the
        caller: this method is the one place the value is persisted and
        published, and a raw provider string reaching it is exactly how a Python
        exception class and a vendor URL ended up rendered under a user's own
        dictated words. A backstop at the store beats a rule every future caller
        has to remember.

        ``lost_audio_s`` is how many seconds of the recording were attempted
        and never read — see the ``partial`` entry in
        ``dodaios.dictation.outcomes``. It is a SEPARATE argument from
        ``stt_error`` on purpose, and the distinction is the whole of the fix:
        an error says something went wrong, this says something was lost, and
        only the second one is a reason to stop calling the dictation a success
        and to keep its audio. Defaults to zero so every existing caller (and
        the crash path below) keeps today's behaviour exactly.

        ``dropped_audio_s`` is the OTHER way to end up missing words, and it is
        kept apart from ``lost_audio_s`` because the two owe the user different
        sentences. Lost audio was recorded and never read — a retry could still
        read it, which is what Restore offers. Dropped audio was never recorded:
        the capture queue overflowed while the loop was busy and those frames
        are gone, so promising Restore would point at a button that cannot help.
        Both degrade the outcome to ``partial``; only the first one promises
        anything.

        ``audio`` is the session's raw PCM; it is written to a local sidecar
        only when the dictation left the user missing words AND they allow it
        (``[dictation].keep_failed_audio``), which is what a later Restore
        transcribes again.
        """
        finish_started = time.perf_counter()
        stt_error = _pl.normalize_stt_failure(stt_error)
        cleaned = raw_text
        removed_words = 0
        cleanup_reason = ""
        cfg = getattr(self, "_dictation_cfg", None)

        # A user-pinned ``[dictation].language`` outranks whatever the provider
        # reported. Without this the cleanup rules see the provider's guess —
        # and a provider that answers "unknown" leaves every dictation with
        # reason="no_rules", i.e. no cleanup at all despite an explicit pin.
        pinned = str(getattr(cfg, "language", "auto") or "auto").strip().lower()
        # Which language the cleanup rules — and the polish pass — run in. The
        # decision itself lives in ``resolve_dictation_language`` at module
        # level, because the Restore route re-transcribes the same audio and has
        # to reach the same answer. A hangup transcribed nothing, so there is no
        # text to resolve from and the reported tag stands.
        effective_language = _pl.resolve_dictation_language(
            pinned=pinned,
            reported=language,
            text="" if hung_up else raw_text,
        )

        # Teach the anchor what this user dictates in, so the NEXT recording —
        # which may be two seconds of "carry on" — is not left asking a clip too
        # short to answer. Only a long recording votes: a short one is exactly
        # the case the provider gets wrong, and letting it vote would let the
        # guess confirm itself. The reading is the resolved language, so a user
        # pin outranks everything here as it does everywhere else.
        if not hung_up and duration_s >= self._LANGUAGE_ANCHOR_MIN_S:
            try:
                self._remember_dictation_language(
                    effective_language, on_device=False
                )
            except Exception:  # noqa: BLE001 — an anchor is a hint, never a gate
                _pl.log.debug("dictation language anchor update failed", exc_info=True)

        if raw_text and not hung_up:
            # The rules that turn the recognizer's text into the dictation:
            # pause marks out, spoken paragraph and line commands in,
            # hesitation sounds out, punctuation repaired. No model call.
            try:
                from dodaios.dictation.formatting import format_dictation

                formatted = format_dictation(
                    raw_text,
                    language=effective_language,
                    fillers=bool(getattr(cfg, "remove_fillers", True)),
                    paragraphs=bool(getattr(cfg, "auto_paragraphs", True)),
                    max_removed_fraction=float(
                        getattr(cfg, "filler_max_removed_fraction", 0.25)
                    ),
                )
                cleaned = formatted.text
                removed_words = formatted.removed_words
                cleanup_reason = formatted.filler_reason
            except Exception:  # noqa: BLE001 — never lose the text to a formatting bug
                _pl.log.warning("dictation formatting failed; using the recognized text",
                            exc_info=True)
                cleaned = raw_text

        # Two kinds of text must never reach a document, and both used to.
        #
        # (a) Whisper's silence boilerplate. Every Whisper-family model answers a
        #     near-silent microphone with the same handful of subtitle credits
        #     and video outros — 12 of the first 26 rows of the live history are
        #     "Thank you." or "Thank you for watching!", none of them spoken. The
        #     repo has owned the marker list for months and the voice lane
        #     filters on it in four places; the dictation lane never did.
        # (b) A transcript with no WORDS in it. A bare "." was pasted into a live
        #     document (history row 2026-07-28T18:10:30) and the clipboard was
        #     then restored over it, so the user was left holding a stray full
        #     stop and no way back to what they had copied.
        #
        # Blanking the text HERE, rather than only skipping the insertion, is
        # deliberate: the final transcript published below also feeds the chat
        # composer and the bar, and a dictation that reports "empty" while its
        # text already sits in the composer is the same defect in a different
        # window. ``raw_text`` is untouched, so the history row still shows what
        # the provider returned and a later Restore can transcribe the audio
        # again. Fail-open like every other step here: a broken gate costs the
        # gate, never the user's words.
        rejected_detail = ""
        if no_speech and not stt_error:
            rejected_detail = (
                "No speech was heard, so nothing was inserted. Check that the "
                "right microphone is selected and not muted."
            )
            if audio_sample_rate_hz > 0 and audio_rms == 0.0 and duration_s >= 0.5:
                # Exact zeros are not a quiet room: the input carries nothing.
                # Say WHICH input: "the microphone" is whichever one the
                # automatic choice landed on, and the person cannot see that.
                silent_input = _pl.last_input_name()
                named = f"The microphone '{silent_input}'" if silent_input else "The microphone"
                rejected_detail = (
                    f"{named} delivered no signal at all, so nothing was "
                    "inserted. Choose another microphone in Settings, or check "
                    "that this one is not muted."
                )
                await self._tell_silent_microphone(silent_input)
        if raw_text.strip() and not cleaned.strip() and not hung_up and not rejected_detail:
            # The rules left nothing: the recognizer returned marks, no words.
            rejected_detail = (
                "The dictation produced punctuation but no words, so "
                "nothing was inserted."
            )
        if cleaned.strip() and not hung_up:
            try:
                from dodaios.dictation.cleanup import count_words

                if count_words(cleaned) == 0:
                    rejected_detail = (
                        "The dictation produced punctuation but no words, so "
                        "nothing was inserted."
                    )
                elif _pl._is_silence_hallucination(cleaned, duration_s):
                    rejected_detail = (
                        "The audio was too quiet to resolve, so nothing was "
                        "inserted."
                    )
                if rejected_detail:
                    _pl.log.info(
                        "dictation delivery refused (%.1fs of audio, %r): %s",
                        duration_s,
                        cleaned[:80],
                        rejected_detail,
                    )
                    cleaned = ""
            except Exception:  # noqa: BLE001 — a broken guard never eats the text
                _pl.log.debug("dictation delivery gate failed", exc_info=True)
                rejected_detail = ""

        # The generative polish pass — the second read-over that turns a
        # transcript into written prose (punctuation, sentence structure, the
        # capitalisation our own ~8 s segment boundaries destroy). No regex can
        # do this, which is why the deterministic cleanup above closes only half
        # the gap.
        #
        # It sits HERE, after the delivery gates and before the publish, for two
        # reasons. After the gates, so we never spend a model call polishing
        # boilerplate we are about to throw away. Before the publish, so the
        # chat composer, the Jarvis Bar and the insertion all see the SAME
        # string — a polished paste next to an unpolished composer is the kind
        # of divergence nobody can explain afterwards. ``raw_text`` is untouched
        # and still reaches the history, so the user can always recover the
        # words they actually said.
        #
        # Fail-open twice over: ``polish_transcript`` itself never raises and
        # returns the raw text on every non-``applied`` status, and this block
        # additionally catches anything the import or the call surfaces. The
        # import is INSIDE the function (AP-26) exactly like ``clean_transcript``
        # above — nothing about the polish pass may reach the boot path.
        # The same pass also delivers the dictation in a fixed language when
        # ``[dictation].translate`` is on — one model call does both, so a
        # translation costs the same single round trip a polish does.
        polish_status = ""
        polish_provider = ""
        polish_latency_ms = 0
        if cleaned.strip() and not hung_up:
            try:
                from dodaios.dictation.polish import (
                    polish_enabled,
                    polish_transcript,
                    resolve_translate_target,
                )

                # Resolved HERE and not inside the pass so both callers of the
                # pass — this one and the Restore route — reach the same answer
                # from the same function, exactly like ``effective_language``
                # above. It reads the CONFIG only, deliberately NOT
                # ``effective_language``: deciding per dictation whether to
                # translate, based on a recognizer tag that is documented to be
                # wrong, is what made the delivered language alternate between
                # two with nothing the user touched explaining it.
                translate_to = resolve_translate_target(cfg)

                # Prompt Mode outranks both passes: the whole dictation is
                # rewritten into a brief for a coding agent, so neither the
                # wording pass nor the translator has anything left to do.
                # When it cannot deliver (no writer, timeout, an answer that
                # is not a prompt) the dictation falls through to the passes
                # below exactly as if the switch were off.
                from dodaios.dictation.prompt_mode import (
                    STATUS_PROMPTED,
                    compose_prompt,
                    prompt_mode_enabled,
                )

                prompted = False
                if prompt_mode_enabled(cfg):
                    result = await compose_prompt(
                        cleaned,
                        cfg=cfg,
                        protected_terms=self._dictation_protected_terms(),
                        language=effective_language,
                    )
                    prompted = result.status == STATUS_PROMPTED
                    _pl.log.info(
                        "dictation prompt mode: %s (%s, %d ms%s).",
                        result.status,
                        result.provider or "no writer",
                        result.latency_ms,
                        f", {result.reason}" if result.reason else "",
                    )
                    if prompted:
                        cleaned = result.text
                        polish_status = result.status
                        polish_provider = result.provider
                        polish_latency_ms = result.latency_ms

                if prompted:
                    pass  # delivered above; the passes below are superseded
                elif polish_enabled(cfg) or translate_to:
                    result = await polish_transcript(
                        cleaned,
                        language=effective_language,
                        cfg=cfg,
                        protected_terms=self._dictation_protected_terms(),
                        style=str(getattr(cfg, "polish_style", "neutral") or "neutral"),
                        translate_to=translate_to,
                    )
                    cleaned = result.text
                    polish_status = result.status
                    polish_provider = result.provider
                    polish_latency_ms = result.latency_ms
                    _pl.log.info(
                        "dictation %s: %s (%s, %d ms%s).",
                        f"translation to {translate_to}" if translate_to else "polish",
                        polish_status,
                        polish_provider or "no provider",
                        polish_latency_ms,
                        f", {result.reason}" if result.reason else "",
                    )
                else:
                    polish_status = "off"
            except Exception:  # noqa: BLE001 — never lose the text to the polish pass
                _pl.log.warning(
                    "dictation polish failed; using the unpolished transcript",
                    exc_info=True,
                )
                polish_status = "provider_error"

        # Resolve ``auto`` now: the foreground window at DELIVERY time is the
        # one the user means, not the one that happened to be in front when
        # recording started.
        #
        # Resolved BEFORE the publish below because the answer RIDES on that
        # event. The UI sees a final transcript on both routes, so without it
        # there is no way to tell "this belongs in the app" from "this is
        # already being pasted into another program" — and a UI that guessed
        # would write a dictation meant for a foreign window into whatever
        # Jarvis field last had focus.
        resolved_target = target
        if target not in ("insert", "chat"):
            try:
                from dodaios.dictation.insert import resolve_target

                resolved_target = resolve_target(target)
            except Exception:  # noqa: BLE001 — an unreadable foreground is not fatal
                _pl.log.debug("dictation target resolution failed", exc_info=True)
                resolved_target = "insert"

        formatting_ms = round((time.perf_counter() - finish_started) * 1000.0)
        notification_ms = 0
        insertion_ms = 0
        final_notification_status = "complete"
        insert_result = None

        async def notify_final() -> None:
            nonlocal notification_ms, final_notification_status
            started = time.perf_counter()
            try:
                complete = await self._publish_dictation_event(
                    _pl.DictationTranscript(
                        source_layer="speech.dictation",
                        text=cleaned,
                        is_final=True,
                        target=resolved_target,
                    )
                )
                if not complete:
                    final_notification_status = "observer_timeout"
            except Exception:
                final_notification_status = "failed"
                _pl.log.warning("dictation final publish failed", exc_info=True)
            finally:
                notification_ms = round((time.perf_counter() - started) * 1000.0)

        async def insert_external() -> None:
            nonlocal insert_result, insertion_ms
            started = time.perf_counter()
            try:
                insert_result = await asyncio.to_thread(self._insert_dictation, cleaned)
            except Exception:
                _pl.log.warning("dictation insertion failed", exc_info=True)
            finally:
                insertion_ms = round((time.perf_counter() - started) * 1000.0)

        # Healthy UI clients receive the final text even if OS insertion fails.
        # An external paste starts alongside notification: its destination must
        # not drift while an unrelated UI observer is holding up the bus.
        try:
            if resolved_target == "insert" and cleaned.strip() and not hung_up:
                await asyncio.gather(notify_final(), insert_external())
            else:
                await notify_final()
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("dictation final delivery failed: %s", exc)

        outcome_name = "chat"
        detail = ""
        method = ""
        if hung_up:
            outcome_name = "cancelled"
        elif not cleaned.strip():
            # Nothing to deliver. WHY there is nothing is the whole point of
            # this branch: a provider error is a "failed" the user can act on
            # (fix the key, switch provider), silence is just an "empty".
            outcome_name = "failed" if stt_error else "empty"
            if stt_error:
                # ``detail`` is the sentence surfaces without a locale of their
                # own show verbatim (the Jarvis Bar, the CLI) — and until now a
                # failed dictation left it empty, so the bar said nothing at all
                # about why the words never arrived. The localized half is the
                # reason CODE on ``error``, which the UI translates.
                detail = _pl.stt_failure_message(stt_error)
                # Every provider failed and the words exist only as audio now.
                # That audio is kept for exactly this case (``failed`` is a
                # recoverable outcome), so the notice says where to get the
                # words back — the 2026-10-20 lost dictation told the user only
                # that the service "could not be reached". Promised only when
                # the sidecar will really be written: history on, the user's
                # keep switch on, and audio captured.
                if (
                    audio
                    and bool(getattr(cfg, "history_enabled", True))
                    and bool(getattr(cfg, "keep_failed_audio", True))
                ):
                    detail += (
                        " The audio was kept — use Restore in the dictation "
                        "history to try again."
                    )
            elif rejected_detail:
                # Nothing arrived because what arrived was not speech. Saying so
                # is the difference between "your microphone heard nothing" and
                # an unexplained empty result after the user clearly spoke.
                detail = rejected_detail
        elif resolved_target == "insert":
            if insert_result is None:
                outcome_name = "failed"
                detail = "The text could not be inserted."
                if bool(getattr(cfg, "history_enabled", True)):
                    detail += " It is available in dictation history."
            else:
                outcome_name = insert_result.status
                detail = insert_result.detail
                method = insert_result.method

        # A dictation that delivered SOME words and permanently lost others is
        # not a success, whichever way the surviving fragment was delivered.
        # This is the maintainer's original complaint: 37.7 s of speech, a 429
        # from the provider, three words in the field, outcome ``inserted`` —
        # and because a success is not recoverable, the audio was deleted and
        # the history offered no Restore. Unrecoverable by construction.
        #
        # It is keyed on the LOSS, never on ``stt_error``: a failure on the last
        # probe tick whose tail then fell under the minimum segment size leaves
        # a stale error on a complete transcript, and degrading that would be
        # the same lie told backwards. ``hung_up`` still wins — the user
        # cancelled, and every unread second after that is their decision, not a
        # fault. An empty result stays ``failed``/``empty``: there is no
        # "partial" of nothing.
        if lost_audio_s > 0 and not hung_up and cleaned.strip():
            outcome_name = "partial"
            # Only promise Restore when the recording is actually being kept.
            # ``[dictation].keep_failed_audio`` is the user's switch, and a
            # message pointing at a button that will not be there is a worse
            # answer than the plain statement of what was lost.
            lost_note = (
                f"About {lost_audio_s:.1f}s of the recording could not be "
                "transcribed, so words are missing."
            )
            if bool(getattr(cfg, "keep_failed_audio", True)):
                lost_note += (
                    " The audio was kept — use Restore in the dictation "
                    "history to try again."
                )
            why = _pl.stt_failure_message(stt_error) if stt_error else ""
            # ``detail`` is the sentence locale-less surfaces (the Jarvis Bar,
            # the CLI) show verbatim, so the delivery detail is kept rather than
            # replaced: "words are missing" and "it went to the clipboard" are
            # both true and the user needs both. The localized half stays the
            # reason CODE on ``error``, which the UI translates.
            detail = " ".join(part for part in (lost_note, why, detail) if part)
            _pl.log.warning(
                "dictation degraded to partial: %.1fs of audio never "
                "transcribed (%s); the recording is kept for Restore.",
                lost_audio_s,
                stt_error or "unknown",
            )

        # The other hole, and the one nothing used to mention: frames the
        # CAPTURE dropped. When the event loop stalls longer than the mic
        # queue holds, ``_safe_put`` deletes the oldest frame per arrival and
        # that speech never becomes audio anyone can read — measured across 797
        # live dictations at 56 % of them losing something and one losing 7.4 s
        # out of 15.4 s, every one of them delivered as a clean success.
        #
        # Said FIRST when both holes are present: this is the unrecoverable
        # one. It also deliberately does not mention Restore — the audio it
        # would re-read is the audio that was never recorded.
        if (
            dropped_audio_s >= _pl._DICTATION_DROPPED_AUDIO_NOTICE_S
            and not hung_up
            and cleaned.strip()
        ):
            outcome_name = "partial"
            detail = " ".join(
                part
                for part in (
                    f"About {dropped_audio_s:.1f}s of audio was lost while "
                    "recording, so words are missing.",
                    detail,
                )
                if part
            )
            _pl.log.warning(
                "dictation degraded to partial: %.1fs of audio never reached "
                "the recording (capture queue overflow) — not recoverable.",
                dropped_audio_s,
            )

        delivery_audit = (
            *stt_audit,
            f"formatting_wait_ms:{formatting_ms}",
            f"final_notification_wait_ms:{notification_ms}",
            f"insertion_wait_ms:{insertion_ms}",
            f"finish_wait_ms:{round((time.perf_counter() - finish_started) * 1000.0)}",
            f"final_notification:{final_notification_status}",
        )

        # Mark the turn closed BEFORE the publish attempt: this flag answers
        # "does the teardown still owe a terminal event", and a publish that
        # raised is not a reason to fire a second, contradictory completion.
        self._dictation_completion_published = True
        try:
            await self._publish_dictation_event(
                _pl.DictationCompleted(
                    source_layer="speech.dictation",
                    text=cleaned,
                    raw_text=raw_text,
                    outcome=outcome_name,
                    detail=detail,
                    method=method,
                    language=effective_language,
                    duration_s=duration_s,
                    removed_words=removed_words,
                    error=stt_error,
                    polish_status=polish_status,
                    polish_provider=polish_provider,
                    polish_latency_ms=polish_latency_ms,
                    stt_providers=stt_providers,
                    stt_models=stt_models,
                    detected_languages=detected_languages,
                    stt_latency_ms=max(0, int(stt_latency_ms)),
                    stt_calls=max(0, int(stt_calls)),
                    stt_errors=stt_errors,
                    stt_audit=delivery_audit,
                    audio_sample_rate_hz=max(0, int(audio_sample_rate_hz)),
                    audio_rms=max(0.0, float(audio_rms)),
                    audio_clipping_ratio=max(0.0, float(audio_clipping_ratio)),
                    audio_dropouts=max(0, int(audio_dropouts)),
                    audio_dropout_ms=max(0, int(audio_dropout_ms)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            _pl.log.debug("dictation completion publish failed: %s", exc)

        await self._record_dictation(
            raw_text=raw_text,
            cleaned=cleaned,
            language=effective_language,
            duration_s=duration_s,
            outcome_name=outcome_name,
            method=method,
            removed_words=removed_words,
            cleanup_reason=cleanup_reason,
            stt_error=stt_error,
            audio=audio,
            polish_status=polish_status,
            polish_provider=polish_provider,
            polish_latency_ms=polish_latency_ms,
            stt_providers=stt_providers,
            stt_models=stt_models,
            detected_languages=detected_languages,
            stt_latency_ms=max(0, int(stt_latency_ms)),
            stt_calls=max(0, int(stt_calls)),
            stt_errors=stt_errors,
            stt_audit=delivery_audit,
            audio_sample_rate_hz=max(0, int(audio_sample_rate_hz)),
            audio_rms=max(0.0, float(audio_rms)),
            audio_clipping_ratio=max(0.0, float(audio_clipping_ratio)),
            audio_dropouts=max(0, int(audio_dropouts)),
            audio_dropout_ms=max(0, int(audio_dropout_ms)),
        )
        return cleaned

    async def _record_dictation(
        self,
        *,
        raw_text: str,
        cleaned: str,
        language: str,
        duration_s: float,
        outcome_name: str,
        method: str,
        removed_words: int,
        cleanup_reason: str,
        stt_error: str | None,
        audio: bytes | None,
        polish_status: str = "",
        polish_provider: str = "",
        polish_latency_ms: int = 0,
        stt_providers: tuple[str, ...] = (),
        stt_models: tuple[str, ...] = (),
        detected_languages: tuple[str, ...] = (),
        stt_latency_ms: int = 0,
        stt_calls: int = 0,
        stt_errors: tuple[str, ...] = (),
        stt_audit: tuple[str, ...] = (),
        audio_sample_rate_hz: int = 0,
        audio_rms: float = 0.0,
        audio_clipping_ratio: float = 0.0,
        audio_dropouts: int = 0,
        audio_dropout_ms: int = 0,
    ) -> None:
        """Write the history row and, when warranted, the audio sidecar.

        Split out of ``_finish_dictation`` because it is the only part that
        touches the disk: the caller has already published everything the UI
        needs, so nothing in here is allowed to change what the user sees. All
        of it is best-effort — a failed history write costs the history entry
        and nothing else.

        The ``polish_*`` values are offered to the store and dropped when it
        does not want them yet — see the ``TypeError`` branch below. A history
        row is worth more than the three fields describing how it was formatted.
        """
        from dodaios.dictation.outcomes import is_recoverable

        cfg = getattr(self, "_dictation_cfg", None)
        # A dictation that produced nothing is recorded too when its outcome
        # says the user LOST something (partial / failed / cancelled / empty):
        # that row is the only place a later Restore can start from.
        if not (raw_text or is_recoverable(outcome_name)):
            return
        if getattr(self, "_dictation_leave_no_trace", False) and outcome_name == "cancelled":
            # The early start of a hold key that turned out to be a shortcut
            # (``_on_dictate_abandon``): nobody dictated, nothing was lost.
            return
        if not getattr(cfg, "history_enabled", True):
            return

        entry = None
        history = None
        try:
            from dodaios.dictation.history import DictationHistory

            history = DictationHistory()
            fields: dict[str, Any] = dict(
                raw_text=raw_text,
                text=cleaned,
                language=language,
                duration_s=duration_s,
                outcome=outcome_name,
                method=method,
                removed_words=removed_words,
                cleanup_reason=cleanup_reason,
                error=stt_error,
                max_entries=int(getattr(cfg, "history_max_entries", 200)),
                retention_days=int(getattr(cfg, "history_retention_days", 30)),
            )
            extra = {
                "polish_status": polish_status,
                "polish_provider": polish_provider,
                "polish_latency_ms": polish_latency_ms,
                "stt_providers": stt_providers,
                "stt_models": stt_models,
                "detected_languages": detected_languages,
                "stt_latency_ms": max(0, int(stt_latency_ms)),
                "stt_calls": max(0, int(stt_calls)),
                "stt_errors": stt_errors,
                "stt_audit": stt_audit,
                "audio_sample_rate_hz": max(0, int(audio_sample_rate_hz)),
                "audio_rms": max(0.0, float(audio_rms)),
                "audio_clipping_ratio": max(0.0, float(audio_clipping_ratio)),
                "audio_dropouts": max(0, int(audio_dropouts)),
                "audio_dropout_ms": max(0, int(audio_dropout_ms)),
            }
            try:
                entry = await asyncio.to_thread(history.add, **fields, **extra)
            except TypeError:
                # The store predates these fields. Writing the row WITHOUT them
                # is the right degradation: the user's words are the payload,
                # and "how it was formatted" is metadata about the payload. The
                # alternative — letting the TypeError fall into the handler
                # below — silently drops the whole dictation from the history,
                # which is a far worse answer to a version skew.
                _pl.log.debug(
                    "dictation history does not carry the polish fields yet; "
                    "storing the row without them."
                )
                entry = await asyncio.to_thread(history.add, **fields)
        except Exception:  # noqa: BLE001 — history is never worth a failure
            _pl.log.debug("dictation history write failed", exc_info=True)
            return

        # Audio is the most sensitive thing this application ever stores, so it
        # is written on exactly one path: the user allowed it AND the dictation
        # left them missing words (``RECOVERABLE_OUTCOMES``). Never on a plain
        # success — but ``partial`` is in that set precisely because the words
        # it did deliver are not the ones it lost.
        if (
            entry is None
            or history is None
            or not audio
            or not bool(getattr(cfg, "keep_failed_audio", True))
            or not is_recoverable(outcome_name)
        ):
            return
        try:
            from dodaios.dictation.audio import prune_audio, save_dictation_audio

            path = await asyncio.to_thread(
                save_dictation_audio, entry.id, audio, directory=history.audio_dir
            )
            if path is not None:
                await asyncio.to_thread(
                    history.update, entry.id, audio_path=str(path)
                )
            # Retention runs after the write, off the delivery path: the
            # transcript is already in front of the user by now.
            await asyncio.to_thread(
                prune_audio,
                max_files=int(getattr(cfg, "audio_max_files", 20)),
                retention_days=int(getattr(cfg, "audio_retention_days", 7)),
                directory=history.audio_dir,
            )
        except Exception:  # noqa: BLE001 — a lost recovery option, not a lost dictation
            _pl.log.debug("dictation audio sidecar failed", exc_info=True)

    def _insert_dictation(self, text: str):
        """Blocking insertion, run off the event loop. Never raises.

        ``insert_text`` sleeps around the paste chord and talks to the OS
        clipboard, so it must not run on the pipeline's loop — a 250 ms block
        there is a stutter in the voice path.
        """
        from dodaios.dictation.insert import InsertResult, insert_text

        cfg = getattr(self, "_dictation_cfg", None)
        try:
            return insert_text(
                text,
                method=str(getattr(cfg, "insert_method", "clipboard")),
                paste_chord=str(getattr(cfg, "paste_chord", "auto")),
                delay_ms=int(getattr(cfg, "paste_delay_ms", 120)),
                delay_after_ms=int(getattr(cfg, "paste_delay_after_ms", 120)),
                restore_clipboard=bool(getattr(cfg, "restore_clipboard", True)),
            )
        except Exception as exc:  # noqa: BLE001 — degrade to an honest report
            _pl.log.warning("dictation insertion failed: %s", exc, exc_info=True)
            return InsertResult(
                status="unavailable",
                detail=(
                    "The text could not be inserted here. It is kept in the "
                    "dictation history."
                ),
                clipboard_holds_text=False,
            )
