"""Session input stream, echo guards, speech output, playback and the barge-in monitor.

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
    import asyncio
    from collections.abc import AsyncIterator
    from typing import Any

    from dodaios.core.events import AudioOutFirst
    from dodaios.core.protocols import AudioChunk
    from dodaios.speech.echo_guard import SelfEchoGuard


class SpeakPlaybackMixin:
    """Session input stream, echo guards, speech output, playback and the barge-in monitor."""

    async def _session_input_stream(
        self, chunks: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[AudioChunk]:
        """Filter mic frames captured during/after Jarvis TTS output."""
        dropped = 0
        async for chunk in chunks:
            # Input mute (Jarvis-scoped): while muted, drop the user's audio at
            # OUR input boundary so Jarvis stops hearing them mid-session —
            # without touching the OS microphone, so every other app keeps the
            # mic. The mute flag already gated wake activation + TTS output; this
            # closes the active-session input gap ("ich rede, aber er hoert mich
            # trotzdem", 2026-06-28).  # i18n-allow
            if getattr(self, "_muted", False):
                continue
            if self._should_drop_session_input(chunk):
                dropped += 1
                continue
            if dropped:
                _pl.log.info("TTS echo guard: dropped %d mic chunk(s).", dropped)
                dropped = 0
            # Realtime sessions bypass the VAD, where mic_level.feed normally
            # lives, so feed the live loudness here — after the mute and echo
            # filters, so suppressed audio honestly shows dark bars. Same
            # normalized RMS as the VAD/PTT sites; zero-cost without overlay.
            if _pl.mic_level.has_subscribers():
                samples = _pl.pcm_bytes_to_np(chunk.pcm)
                if samples.size:
                    _pl.mic_level.feed(float(np.sqrt(np.mean(np.square(samples)))))
            yield chunk

    def _should_drop_session_input(self, chunk: AudioChunk) -> bool:
        until_ns = getattr(self, "_input_suppressed_until_ns", 0)
        if until_ns <= 0:
            return False
        chunk_ts = getattr(chunk, "timestamp_ns", 0) or time.time_ns()
        if chunk_ts < until_ns:
            return True
        self._input_suppressed_until_ns = 0
        return False

    def _suppress_session_input_after_tts(self, reason: str) -> None:
        seconds = max(0.0, float(getattr(self, "_post_tts_listen_suppression_s", 0.0)))
        if seconds <= 0.0:
            return
        until_ns = time.time_ns() + int(seconds * 1_000_000_000)
        previous = getattr(self, "_input_suppressed_until_ns", 0)
        self._input_suppressed_until_ns = max(previous, until_ns)
        _pl.log.info("TTS echo lock armed: %.1fs (%s).", seconds, reason)

    # --- Self-echo TEXT guard (BUG-084) --------------------------------- #
    # The logic lives in dodaios.speech.echo_guard.SelfEchoGuard so the
    # realtime session shares ONE implementation (BUG-089) instead of a
    # drifting copy; these thin delegates keep the pipeline's historical
    # call sites and test surface unchanged.

    def _echo_text_guard(self) -> SelfEchoGuard:
        guard = getattr(self, "_self_echo_guard", None)
        if guard is None:
            guard = _pl.SelfEchoGuard()
            self._self_echo_guard = guard
        return guard

    def _register_assistant_speech(self, text: str) -> None:
        """Remember what Jarvis is about to voice as an echo-guard reference."""

        self._echo_text_guard().register(text)

    def _touch_assistant_speech_activity(self) -> None:
        """Stamp 'assistant audio was active around now' for the echo guard."""

        self._echo_text_guard().touch()

    async def _on_audio_out_first(self, event: AudioOutFirst) -> None:
        """Mark perceived time-to-first-audio once per turn (ack or brain)."""
        tracker = self._latency_tracker
        if tracker is not None and not self._latency_first_audio_marked:
            self._latency_first_audio_marked = True
            tracker.mark(_pl.LatencyPhase.TURN_TO_FIRST_AUDIO)

    def _ensure_voice_stt_warmup(self) -> asyncio.Task[None] | None:
        """The running warm-up of a cold local voice engine, started if needed.

        ``_warmup_deferred_loaders`` only warms ``self._stt`` (the wake engine),
        and on a Vosk-wake install the utterance provider is a separate object
        nothing ever primed — its first build then landed inside the first
        spoken turn's 8 s budget (measured on an RTX 4060: 10.6 s build + 2.4 s
        first decode standalone, ~25 s inside the app, then 0.5 s per decode).
        Returns ``None`` when there is nothing to wait for, including every
        cloud provider, which has no ``warm_up``.
        """
        provider = getattr(self, "_utterance_stt", None)
        warm_up = getattr(provider, "warm_up", None)
        if not callable(warm_up) or getattr(provider, "is_warm", True) is not False:
            return None
        task = getattr(self, "_voice_stt_warmup_task", None)
        if (
            task is not None
            and not task.done()
            and getattr(self, "_voice_stt_warmup_provider", None) is provider
        ):
            return task
        if getattr(self, "_dictation_warmup_shutdown", False):
            return None

        def _log_failure(done: asyncio.Task[None]) -> None:
            if not done.cancelled() and done.exception() is not None:
                _pl.log.warning("Voice STT warm-up failed: %s", done.exception())

        task = asyncio.create_task(
            asyncio.to_thread(warm_up), name="voice-stt-warmup"
        )
        task.add_done_callback(_log_failure)
        self._voice_stt_warmup_task = task
        self._voice_stt_warmup_provider = provider
        return task

    def _speech_trace(self) -> str:
        """The turn a metered speech call belongs to, or "" between turns."""
        tracker = getattr(self, "_latency_tracker", None)
        return str(getattr(tracker, "trace_id", "") or "")

    # --- Completion timeout helpers (zero-silent-drop fallback) ------------ #

        # No TTS, no state ping-pong, no interruption.

    # --- Clarifying-question timer (Zwischenfrage; AD-OE6 for the hold) ----- #

    # --- Continuation drain timer (autonomous flush; AD-OE6 zero-silent-drop) - #

    async def _notify_voice_unavailable(self, phrase: str, *, spoken: bool) -> None:
        """Say (or, with a live capture microphone, show) why a call ended.

        ``phrase`` is the provider's refusal (dodaios.speech.provider_refusal),
        already in the call's language; empty means the generic line that no
        realtime provider is ready.
        """
        if spoken:
            await self._speak_realtime_unavailable(phrase or None)
            return
        lang = _pl._phrase_lang(self._output_language(None, ""))
        await self._publish_event(
            _pl.MessageSent(
                source_layer="speech.pipeline",
                thread_id="voice",
                role="system",
                text=phrase or _pl._REALTIME_UNAVAILABLE_PHRASE[lang],
            )
        )

    async def _speak_realtime_unavailable(self, phrase: str | None = None) -> None:
        """Speak why the realtime call could not start or went on.

        ``phrase`` replaces the generic line with the provider's actual
        refusal (dodaios.speech.provider_refusal), already in the call's
        language.
        """
        lang = _pl._phrase_lang(self._output_language(None, ""))
        phrase = phrase or _pl._REALTIME_UNAVAILABLE_PHRASE[lang]
        try:
            await self._set_turn_state(_pl.TurnTakingState.JARVIS_SPEAKING)
            await self._speak(
                phrase,
                language=lang,
                kind=_pl.SPOKEN_KIND_UNAVAILABLE,
            )
        except Exception as exc:  # noqa: BLE001 — fallback must never block recovery
            _pl.log.warning("Realtime-unavailable fallback speak failed: %s", exc)

    def _abort_playback_device(self) -> None:
        """Unblock + tear down the live output stream after a playback stall."""
        player = getattr(self, "_player", None)
        if player is None:
            return
        if hasattr(player, "abort_active"):
            player.abort_active()
        else:  # older player without the Wave-1 hook
            player.stop()

    async def _await_playback(
        self,
        play_task: asyncio.Task[Any],
        extra_tasks: set[asyncio.Task[Any]],
    ) -> set[asyncio.Task[Any]]:
        """Wait for a TTS playback task, aborting a wedged device fast.

        The dominant 60-156 s voice-hang root cause was a wedged output device:
        PortAudio's blocking ``stream.write`` got stuck in its ``to_thread``
        worker (which Python cannot cancel), so ``play_task`` never completed and
        the only escape was a 120 s ceiling. This poll loop watches the player's
        write-progress (``last_write_ns``): a mid-playback gap of
        ``_speak_playback_stall_s`` means the device is wedged → we call
        ``player.abort_active()`` (Pa_AbortStream) to unblock the write so the
        turn unwinds in ~5 s and the session re-arms. A ``_speak_playback_
        ceiling_s`` absolute backstop covers anything the progress signal misses.

        Returns the set of completed tasks, or an EMPTY set when it aborted on a
        stall/ceiling (the device has already been torn down + the event logged).
        Cross-platform: pure asyncio + PortAudio abort.
        """
        ceiling = getattr(self, "_speak_playback_ceiling_s", _pl._TTS_PLAYBACK_CEILING_S)
        stall_s = getattr(self, "_speak_playback_stall_s", _pl._TTS_PLAYBACK_STALL_S)
        watch = {play_task, *extra_tasks}
        start = time.monotonic()
        while True:
            done, _pending = await asyncio.wait(
                watch, timeout=0.25, return_when=asyncio.FIRST_COMPLETED
            )
            if done:
                return done
            player = getattr(self, "_player", None)
            last_write = getattr(player, "last_write_ns", 0) if player is not None else 0
            owner_missing = object()
            owner_task_id = (
                getattr(player, "last_write_owner_task_id", owner_missing)
                if player is not None
                else owner_missing
            )
            if owner_task_id is not owner_missing and owner_task_id != id(play_task):
                last_write = 0
            if last_write <= 0:
                # No first frame yet: the synthesize / first-frame window. A slow
                # TTS provider must NOT be misread as a device wedge — that false
                # abort (on every turn whose brain/synthesize took > stall_s) was
                # the "Jarvis listens forever / answer never heard" root cause.
                # Only a generous no-first-frame backstop applies here; it covers
                # a provider that never yields any audio at all.
                #
                # The turn is actively WORKING whenever EITHER heartbeat landed
                # AFTER this await began — in both cases the brain simply has not
                # started narrating yet, so there is legitimately nothing to play.
                # Re-arm the window from the LATER heartbeat so the ceiling bounds
                # silence since the LAST sign of life, never total work time.
                #   • ``_long_tool_last_activity`` — a computer_use step
                #     (ObservationCaptured/ActionPlanned → _on_agent_progress).
                #     Live bug 2026-06-09 ("öffne CapCut"): the CU loop was
                #     beheaded on step 4 at 20 s and the turn came back empty/mute.
                #   • ``_brain_last_progress`` — the brain's own round/token
                #     heartbeat (_mark_brain_progress, pinged on every tool-use-
                #     loop round AND every streamed token; the SAME signal the
                #     brain stall guard trusts). Live bug 2026-06-14 14:21 + 14:24
                #     (a weather question): a NON-desktop tool loop (geocode +
                #     DuckDuckGo + open-meteo, ~20 s of real work) emits no CU
                #     step, so before this the 20 s ceiling beheaded the working
                #     turn and the user heard "that took too long" + a hang-up.
                #   • ``_brain_thinking_heartbeat`` — the PRE-first-token think
                #     pulse from _run_brain_with_stall_guard. Live bug 2026-06-14
                #     16:17 (a trip-research turn): the deep brain built an
                #     18k-token cache then thought silently with no on_progress
                #     and no token, so the two heartbeats above never moved and
                #     the 20 s ceiling beheaded a working brain.
                # Strictly-greater keeps a heartbeat from BEFORE this await out of
                # the decision — per-unit re-arm, the BUG-032 stale-counter
                # lesson; the brain stall guard applies the same suspension to its
                # absolute ceiling. Once the brain finishes producing text both
                # heartbeats freeze, so a genuinely wedged TTS provider (text fed,
                # no audio) is still aborted ``ceiling`` s after the last progress.
                heartbeat = max(
                    getattr(self, "_long_tool_last_activity", 0.0),
                    getattr(self, "_brain_last_progress", 0.0),
                    getattr(self, "_brain_thinking_heartbeat", 0.0),
                )
                if heartbeat > start:
                    start = heartbeat
                if (time.monotonic() - start) >= ceiling:
                    _pl.log.warning(
                        "TTS produced no audio within %.0fs — aborting "
                        "(no first frame).", ceiling,
                    )
                    self._abort_playback_device()
                    return set()
                continue
            # Playback has started: only a genuine MID-playback gap (frames were
            # flowing, then froze) is a device wedge. An actively-progressing long
            # answer keeps last_write fresh and is never aborted — the old flat
            # total-time ceiling used to truncate any spoken turn over ~20 s.
            if _pl._playback_progress_stalled(last_write, stall_s):
                _pl.log.warning(
                    "TTS playback stalled — no audio frames for %.1fs — aborting "
                    "device + unwinding turn (device-wedge recovery).", stall_s,
                )
                self._abort_playback_device()
                return set()

    def _resolve_realtime_surface_tts(self, provider: str) -> Any | None:
        """TTS for re-rendering a realtime turn locally (mode separation).

        STRICT separation (maintainer mandate 2026-07-17): resolves ONLY the
        active realtime provider's own TTS family, keyed through the realtime
        credential slots and speaking the session voice. The pipeline ``[tts]``
        instance is never a candidate — ``None`` means "keep the turn
        text-only". Cached per provider; never raises.
        """
        key = (provider or "").strip().lower()
        if not key:
            return None
        cached = getattr(self, "_realtime_surface_tts_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            from dodaios.plugins.tts import build_realtime_surface_tts

            built = build_realtime_surface_tts(self._config, key)
        except Exception:  # noqa: BLE001 — the emergency voice must never break the turn
            built = None
        if built is not None:
            # Every readback and announcement spoken DURING a realtime call
            # goes through this voice; on a realtime-first box that is nearly
            # all of the TTS spend, and it was the one voice nobody metered.
            built = _pl.meter_tts(
                built, getattr(self, "_speech_spend", None), trace_id=self._speech_trace
            )
        self._realtime_surface_tts_cache = (key, built)
        return built

    def _emit_spoken(
        self,
        text: str,
        language: str | None,
        kind: str,
        detail: str | None = None,
        tts: Any | None = None,
    ) -> None:
        """Publish one playback-confirmed phrase to the audible transcript.

        Callers own the playback receipt and invoke this only after audio was
        accepted. Normal replies and supplemental phrases share this event.
        Publishing remains fire-and-forget so the passive recorder cannot add
        latency to the voice path. Empty text and a missing bus are no-ops.
        """
        if not text or not text.strip():
            return
        bus = getattr(self, "_bus", None)
        if bus is None:
            return
        try:
            # Which voice actually spoke: every classic-path phrase renders
            # through self._tts, whose providers record their resolved voice
            # per utterance (last_voice protocol, 2026-07-17). Read after
            # playback so a fallback takeover reports the TAKEOVER voice.
            # A caller that rendered through a DIFFERENT instance (realtime
            # surface fallback) passes it in so the label stays honest.
            if tts is None:
                tts = getattr(self, "_tts", None)
            voice = getattr(tts, "last_voice", None)
            voice_provider = getattr(tts, "last_voice_provider", None) or getattr(
                tts, "name", None
            )
            event = _pl.SpeechSpoken(
                source_layer="speech.pipeline",
                text=text,
                language=(language or "en"),
                spoken_kind=kind,
                detail=(detail or None),
                voice=voice,
                voice_provider=voice_provider if voice else None,
            )
            asyncio.create_task(bus.publish(event))  # noqa: RUF006 — fire-and-forget
        except Exception:  # noqa: BLE001 — telemetry must never break the turn
            _pl.log.debug("SpeechSpoken emit failed", exc_info=True)

    def _playback_confirmed(self, result: object) -> bool:
        """Interpret a player receipt without breaking compatible older players.

        The built-in player returns an explicit boolean. Older compatible
        players returned ``None`` after successful consumption, so only those
        non-built-in implementations retain the legacy success interpretation.
        """
        if isinstance(self._player, _pl.AudioPlayer):
            return result is True
        return result is not False

    #: Spoken readback for a Jarvis-Agent background task that finished off the
    #: chat path. de/en/es/pt so the readback follows the conversation language
    #: instead of a hardcoded German literal (forensic 2026-06-23). German
    #: strings are TTS product surface, not source artifacts (i18n-allow).
    _BG_READBACK_PHRASES: dict[str, dict[str, str]] = {
        "de": {
            "done": "Fertig.",  # i18n-allow
            "done_summ": "Fertig. {s}",  # i18n-allow
            "fail": "Das hat nicht geklappt. {e}",  # i18n-allow
            "unknown_err": "unbekannter Fehler",  # i18n-allow
        },
        "en": {
            "done": "Done.",
            "done_summ": "Done. {s}",
            "fail": "That didn't work. {e}",
            "unknown_err": "unknown error",
        },
        "es": {
            "done": "Listo.",
            "done_summ": "Listo. {s}",
            "fail": "Eso no funcionó. {e}",
            "unknown_err": "error desconocido",
        },
        "pt": {
            "done": "Feito.",
            "done_summ": "Feito. {s}",
            "fail": "Isso não funcionou. {e}",
            "unknown_err": "erro desconhecido",
        },
    }

    _BCP47: dict[str, str] = {
        "de": "de-DE", "en": "en-US", "es": "es-ES", "pt": "pt-PT", "fr": "fr-FR",
    }

    @classmethod
    def _bcp47(cls, lang: object) -> str | None:
        """Map a de/en/es/pt turn-language code to a TTS BCP-47 locale, else None.

        Single source for the whole pipeline — replaces four hand-copied maps,
        one of which (the task-ack prerender) had silently dropped ``es``, so a
        Spanish turn there got no language pin and the multilingual TTS could
        code-switch.
        """
        return cls._BCP47.get(str(lang or "").lower())

    def _output_language(self, stt_language: object, text: str) -> str:
        """Resolve THIS turn's output language for EVERY spoken/written layer.

        Honors the live ``brain.reply_language`` pin (the desktop Languages
        view) so a user-selected language reaches the ack preamble, the canned
        status / clarify / timeout phrases and the TTS voice — not only the
        deep-brain reply (forensic 2026-06-18: a German utterance mis-heard as
        English text drove the whole chain English because the pipeline
        re-derived language from text/STT alone). ``auto``/unset mirrors the
        detected input language. Single source for the whole pipeline, per
        AGENTS.md "Runtime Output Language". The live pin lives on the
        BrainManager (hot-reloaded via ``set_reply_language``); the config is
        only consulted when the brain callback does not expose the pin (tests /
        mock brains).
        """
        brain = getattr(self, "_brain", None)
        pin = getattr(brain, "reply_language", None)
        if pin is None:
            cfg = getattr(self, "_config", None)
            pin = getattr(getattr(cfg, "brain", None), "reply_language", None)
        # French is a spoken pin without a translated phrase catalog. Canned
        # phrases still fall back to English; the TTS voice follows the pin.
        if str(pin or "").strip().lower() == "fr":
            return "fr"
        # Conversation stickiness: a thin interjection ("Now") inherits the
        # running conversation language instead of flipping ack/phrases/TTS
        # (forensic 2026-06-18). The brain owns the sticky conversation language.
        # An undetectable turn falls back to English (DEFAULT_LOCALE), never
        # the UI language: the interface language says nothing about the
        # language spoken (forensic 2026-10-19).
        conv = getattr(brain, "conversation_language", "")
        return _pl.resolve_output_language(
            pin, stt_language, text, conversation_language=conv,
            default=_pl.DEFAULT_LOCALE,
        )

    async def _speak(
        self, text: str, language: str | None = None, *, kind: str = "reply"
    ) -> bool:
        """Speak text aloud — with a barge-in monitor.

        `language` = "de"/"en" (Whisper code) is mapped to "de-DE"/"en-US"
        and passed to TTS (the voice stays the same — Gemini voices are
        language-agnostic).

        ``kind`` tags what is being voiced for the Transcription log. The
        default ``"reply"`` is the ordinary brain answer; canned phrases pass
        their specific kind. Both are published only after playback succeeds.

        ``_barge_monitor`` runs on a separate mic instance in parallel with
        playback. When Silero VAD detects user speech there (threshold 0.8,
        3 consecutive frames, 400 ms grace period), player playback stops
        immediately. Return value: ``True`` when barged in.

        When muted (mascot doubleClick), we short-circuit: no synthesize
        call, no playback. We return ``False`` (no barge-in occurred) so
        callers that branch on ``barged`` behave consistently.
        """
        if getattr(self, "_muted", False):
            # INFO, not debug: a muted drop makes the whole turn inaudible
            # while the transcript claims Jarvis spoke — forensics must see
            # the audible gap without a debug build (live 2026-07-21 17:45).
            _pl.log.info(
                "_speak suppressed — voice muted (kind=%s, %d chars stay "
                "text-only)",
                kind,
                len(text),
            )
            return False
        # Double-answer guard (live complaint 2026-06-30): once a timeout /
        # "couldn't finish" notice closed THIS utterance, an ordinary brain
        # ANSWER (kind="reply", the default) must NOT also be voiced — a stalled
        # tool that timed out and then re-answered for the same content. Gate
        # ONLY the brain answer: every canned notice (timeout / clarify / ack /
        # unavailable) and every background mission readback (completion /
        # subagent / announcement) carries its own kind and is intentionally
        # exempt, so a legitimately-spawned later result still speaks. The flag
        # re-arms at the next utterance finalize. Before ``_emit_spoken`` so a
        # suppressed answer — never actually voiced — is not logged.
        if kind == "reply" and getattr(self, "_brain_timeout_spoken_this_turn", False):
            _pl.log.info(
                "Brain answer suppressed — a timeout notice already closed this "
                "turn (no double-answer)."
            )
            return False
        lang_code = self._bcp47(language)
        # Echo-guard reference (BUG-084): whatever we voice may come back
        # through the mic as speaker echo.
        self._register_assistant_speech(text)
        try:
            chunks = self._tts.synthesize(text, language_code=lang_code)
        except TypeError:
            chunks = self._tts.synthesize(text)

        play_task = asyncio.create_task(self._player.play_chunks(chunks), name="tts-play")
        barge_task = asyncio.create_task(self._barge_monitor(), name="barge-monitor")
        # Hangup is the hard kill-switch ("auflegen"): a hangup mid-phrase must
        # abort _speak at once. Without watching the event here, a stalled
        # output device — or a hangup fired during a fallback phrase
        # (_speak_brain_unavailable / _speak_brain_timeout) — keeps ``play_task``
        # pending until the no-first-frame ceiling, so ``_speak`` never returns and the
        # voice session wedges in JARVIS_SPEAKING (same root cause as
        # _brain_streaming; live bug 2026-06-01). Treat it like a barge-in.
        # getattr-fallback: test fixtures build the pipeline via ``__new__``
        # and don't set ``_hangup_event`` — a fresh never-set Event keeps the
        # behaviour identical to pre-fix (the waiter simply never fires).
        hangup_event = getattr(self, "_hangup_event", None) or asyncio.Event()
        hangup_task = asyncio.create_task(
            hangup_event.wait(), name="hangup-during-speak"
        )
        barged = False
        # A stalled output device (blocking ``stream.write``) or a stalled TTS
        # stream can wedge ``play_chunks``. The watchdog aborts a wedged device
        # in ~5 s (vs the old 120 s ceiling) so ``_speak`` always returns and the
        # voice session can never freeze with ``self._state`` stuck at ACTIVE
        # (the wake loop only re-arms in IDLE).
        try:
            done = await self._await_playback(play_task, {barge_task, hangup_task})
            if not done:
                # Watchdog already aborted the wedged device + logged the reason.
                pass
            elif hangup_task in done and not hangup_task.cancelled():
                _pl.log.info("📵 Hangup during TTS — aborting turn")
                self._player.stop()
                barged = True
            else:
                if barge_task in done and not barge_task.cancelled():
                    if barge_task.result():
                        _pl.log.info("🛑 Barge-in — stoppe TTS-Playback")
                        self._player.stop()
                        barged = True
                if (
                    barge_task in done
                    and not barge_task.cancelled()
                    and not barged
                    and not play_task.done()
                ):
                    # Barge monitor returned without barging (mic ended/error)
                    # but playback is still running — wait it out under the same
                    # device-wedge watchdog, still abortable by a hangup.
                    tail_done = await self._await_playback(play_task, {hangup_task})
                    if play_task not in tail_done:
                        if hangup_task in tail_done:
                            _pl.log.info("📵 Hangup during TTS — aborting turn")
                            barged = True
                        # else: watchdog already aborted the wedged device + logged.
                        self._player.stop()
        except Exception as exc:  # noqa: BLE001
            _pl.log.exception("Playback failure: %s", exc)
        finally:
            for t in (play_task, barge_task, hangup_task):
                if not t.done():
                    t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: S110
                    # Owned playback tasks were explicitly cancelled above.
                    pass
        if (
            play_task.done()
            and not play_task.cancelled()
            and play_task.exception() is None
            and self._playback_confirmed(play_task.result())
        ):
            self._emit_spoken(text, language, kind)
        # Echo-guard activity stamp (BUG-084) — unconditional: after a FALSE
        # barge (our own echo confirmed as "user speech") there is no post-TTS
        # suppression at all, so the text guard is the only thing standing
        # between the echo tail and a brain turn.
        self._touch_assistant_speech_activity()
        if not barged:
            self._suppress_session_input_after_tts("response")
        return barged

    async def _barge_monitor(
        self, *, grace_s: float | None = None, respect_input_suppression: bool = False
    ) -> bool:
        """Listen on a second mic instance for the user speaking over Jarvis'
        TTS output. Returns ``True`` as soon as that is confirmed.

        History: barge-in used to fire almost immediately after TTS start
        (~600 ms) and truncated the answer — speaker→mic echo (user feedback
        2026-04-22). The conservative policy (1.5 s grace, Silero 0.97, 12
        consecutive frames ≈ 380 ms) fixed headphone leakage but NOT open
        laptop speakers next to a built-in mic: there the assistant's own
        voice is loud, sustained, and perfectly speech-shaped, so Silero —
        which cannot tell whose voice it hears — confirmed a "barge" against
        the assistant itself. That false confirm truncated the audible answer
        AND (because a barge keeps the session listening with no post-TTS
        suppression) let the echo tail become the next "user" turn: the
        BUG-084 self-talk loop on the Mac test machine.

        This monitor therefore reuses the shared
        ``DesktopRealtimeBargeInDetector`` (the BUG-062 realtime fix) instead
        of a bare Silero loop, gaining its two defenses:

        - the static RMS energy pre-gate (quiet frames never reach ONNX), and
        - the BUG-084 adaptive echo floor, calibrated per answer from the
          grace-window frames — which during playback ARE our own echo.

        Every ``feed`` runs in a worker thread: the per-frame ONNX inference
        used to run synchronously on the voice event loop and starved the
        ~120 ms playback write batches on slow CPUs (BUG-062 cause #2 —
        constant stutter / multi-second pauses on the Intel-Mac test machine).
        """
        from dodaios.realtime.desktop import DesktopRealtimeBargeInDetector
        from dodaios.speech.barge_in import profile_for

        # ONE policy for both voice paths ([voice] barge_in; issue #153). The
        # caller's explicit grace stays for the thinking-interrupt monitor;
        # the default grace is the profile's.
        profile = profile_for(getattr(self, "_config", None))
        if not profile.enabled:
            # The person chose to let the assistant finish. Nothing to listen
            # for; the playback waiter continues on its own.
            return False
        detector = DesktopRealtimeBargeInDetector(
            output_active=_pl.level_tap.playback_active,
            **profile.detector_kwargs(grace_s=grace_s),
        )
        try:
            # Model load off the event loop — it shares the turn with live
            # audio playback.
            await asyncio.to_thread(detector.warmup)
        except asyncio.CancelledError:
            return False
        detector.start_output()

        try:
            async with _pl.MicrophoneCapture(
                device=self._input_device,
                max_queue_chunks=_pl.REALTIME_QUEUE_CHUNKS,
                device_priority=self._input_priority,
            ) as mic:
                async for chunk in mic.stream():
                    # Honour the global mute (orb double-click → _muted=True):
                    # while muted the user has told us to stop listening, so a
                    # barge must never fire on this second mic — mirrors
                    # _activation_allowed / _speak, which both short-circuit on
                    # _muted. Without this the thinking-interrupt monitor aborted a
                    # muted-but-still-working turn (live bug 2026-07-01).
                    if getattr(self, "_muted", False):
                        continue
                    # Echo-suppression (spec §4.2): while our own ACK/preamble
                    # audio is still within the post-TTS suppression window, skip
                    # detection so the thinking-interrupt monitor never mistakes
                    # the preamble's speaker->mic leakage for the user speaking.
                    # Pure read (no mutation) to avoid racing the session-input
                    # dropper that shares _input_suppressed_until_ns.
                    if respect_input_suppression:
                        until_ns = getattr(self, "_input_suppressed_until_ns", 0)
                        chunk_ts = getattr(chunk, "timestamp_ns", 0) or time.time_ns()
                        if until_ns > 0 and chunk_ts < until_ns:
                            continue
                    if await asyncio.to_thread(detector.feed, chunk.pcm) is not None:
                        return True
        except asyncio.CancelledError:
            return False
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("Barge-in monitor error: %s", exc)
        return False
