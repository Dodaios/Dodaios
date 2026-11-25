"""Wake pre-roll hand-off, the wake loop and parallel wake verification.

Moved out of ``pipeline.py`` without a behaviour change. Module-level names
of the pipeline are read through ``_pl`` at call time so the pipeline module
stays the one place that owns and patches them.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from dodaios.speech import pipeline as _pl

if TYPE_CHECKING:
    import asyncio
    from collections import deque
    from collections.abc import AsyncIterator
    from typing import Any

    from dodaios.audio.capture import MicrophoneCapture
    from dodaios.core.protocols import AudioChunk
    from dodaios.speech.pipeline import _ChunkSource, _SessionInputBuffer


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class WakeMixin(_HostBase):
    """Wake pre-roll hand-off, the wake loop and parallel wake verification."""

    # ------------------------------------------------------------------
    # Wake loop and capture handoff
    # ------------------------------------------------------------------

    def _begin_wake_preroll(
        self, recent: tuple[AudioChunk, ...] = ()
    ) -> None:
        """Retain audio from the first truthful wake visual onward."""
        if self._wake_preroll_active:
            return
        self._pending_session_preroll.clear()
        self._pending_session_preroll.extend(recent)
        self._wake_preroll_active = True
        self._wake_preroll_confirmed = False

    def _discard_wake_preroll(self) -> None:
        self._wake_preroll_active = False
        self._wake_preroll_confirmed = False
        self._pending_session_preroll.clear()

    def _take_wake_preroll(self) -> tuple[AudioChunk, ...]:
        chunks = (
            tuple(self._pending_session_preroll)
            if self._wake_preroll_confirmed
            else ()
        )
        self._discard_wake_preroll()
        return chunks

    async def _claim_wake_capture_for_session(
        self,
    ) -> _SessionInputBuffer | None:
        """Transfer the live wake mic to the session without closing it."""
        if self._wake_handoff_ready.is_set():
            buffer = self._wake_handoff_buffer
            self._wake_handoff_buffer = None
            self._wake_handoff_ready.clear()
            if buffer is None:
                raise RuntimeError("Wake microphone offered an empty handoff.")
            return buffer
        if self._wake_capture_released.is_set():
            # The wake task may already have passed its IDLE check and be one
            # scheduling turn away from entering the capture context. Give it
            # that turn before deciding no wake microphone exists; otherwise a
            # hotkey can open a second native stream during the pre-open race.
            await asyncio.sleep(0)
            if self._wake_capture_released.is_set():
                return None
        self._wake_stop_event.set()
        handoff_wait = asyncio.create_task(
            self._wake_handoff_ready.wait(), name="wake-handoff-ready"
        )
        release_wait = asyncio.create_task(
            self._wake_capture_released.wait(), name="wake-capture-release"
        )
        try:
            await asyncio.wait(
                {handoff_wait, release_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (handoff_wait, release_wait):
                if not task.done():
                    task.cancel()
            for task in (handoff_wait, release_wait):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._wake_stop_event.clear()
        # Prefer a concrete handoff if readiness and physical release raced in
        # the same loop tick. Otherwise the old wake stream is authoritatively
        # closed and the caller may safely open one fallback capture.
        if not self._wake_handoff_ready.is_set():
            if self._wake_capture_released.is_set():
                return None
            raise RuntimeError("Wake microphone ownership ended ambiguously.")
        buffer = self._wake_handoff_buffer
        self._wake_handoff_buffer = None
        self._wake_handoff_ready.clear()
        if buffer is None:
            raise RuntimeError("Wake microphone handoff produced no input buffer.")
        return buffer

    async def _abort_pending_wake_handoff(self) -> None:
        """Release an offered wake stream when the state loop rejects the call."""
        wake_capture_was_open = not self._wake_capture_released.is_set()
        preview_was_visible = bool(
            self._wake_preroll_active or self._wake_handoff_ready.is_set()
        )
        self._discard_wake_preroll()
        try:
            buffer = await self._claim_wake_capture_for_session()
        except Exception as exc:  # noqa: BLE001 - rejection must not kill state loop
            _pl.log.warning("Pending wake handoff could not be released: %s", exc)
            self._wake_cancel_event.set()
            self._wake_handoff_hangup_pending.clear()
            self._external_hangup_pending.clear()
            self._hangup_event.clear()
            self._explicit_hard_hangup = False
            return
        if buffer is not None:
            await buffer.close()
            await self._wake_capture_released.wait()
        try:
            if preview_was_visible or wake_capture_was_open or buffer is not None:
                # WakeWordDetected may already have put the bar into LISTENING
                # even though no VoiceSessionStarted will follow. Explicitly
                # retract that preview so UI state matches the mic lease.
                await self._publish_event(
                    _pl.WakeCandidateDetected(source_layer="speech", active=False)
                )
        finally:
            self._wake_handoff_hangup_pending.clear()
            self._external_hangup_pending.clear()
            self._hangup_event.clear()
            self._explicit_hard_hangup = False

    def _realtime_browser_audio(self, config: Any = None) -> bool:
        """Resolve browser audio with the live embedded renderer, when known."""
        from dodaios.realtime.factory import realtime_browser_audio

        renderer = None
        renderer_getter = getattr(self, "_realtime_audio_renderer", None)
        if callable(renderer_getter):
            try:
                renderer = renderer_getter()
            except Exception as exc:  # noqa: BLE001 - keep the provider default on probe failure
                _pl.log.warning(
                    "Embedded audio renderer probe failed (%s); using provider default.",
                    type(exc).__name__,
                )
        selected_config = getattr(self, "_config", None) if config is None else config
        return realtime_browser_audio(selected_config, desktop_renderer=renderer)

    @asynccontextmanager
    async def _capture_first_session_input(
        self,
    ) -> AsyncIterator[_SessionInputBuffer]:
        """Borrow the wake mic or open exactly one fallback session mic."""
        config = getattr(self, "_config", None)
        # An unpinned engine is resolved from the credentials, so the answer
        # is read off the voice loop, like the session build.
        browser_media = bool(
            await _pl._run_voice_critical_thread(lambda: self._realtime_browser_audio(config))
        )
        buffer = await self._claim_wake_capture_for_session()
        if browser_media and buffer is None:
            browser_buffer = _pl._SessionInputBuffer()
            try:
                yield browser_buffer
            finally:
                await browser_buffer.close()
            return
        if buffer is not None:
            try:
                yield buffer
            finally:
                await buffer.close()
                # ``buffer.released`` lets the wake owner begin teardown. Wait
                # for the stronger signal too so no disconnect sound or engine
                # re-arm can race the still-open native microphone.
                await self._wake_capture_released.wait()
            return

        async with _pl.MicrophoneCapture(
            device=self._input_device,
            max_queue_chunks=_pl.REALTIME_QUEUE_CHUNKS,
            device_priority=self._input_priority,
        ) as mic:
            buffer = _pl._SessionInputBuffer(capture=mic)

            async def _unmuted_capture() -> AsyncIterator[AudioChunk]:
                async for chunk in mic.stream():
                    # Filter at capture time, not only at the eventual consumer:
                    # a realtime fallback may replay retained frames after the
                    # user unmutes and must never resurrect muted audio.
                    if not getattr(self, "_muted", False):
                        yield chunk

            buffer.start(_unmuted_capture())
            try:
                yield buffer
            finally:
                await buffer.close()

    async def _release_unclaimed_wake_handoff(self) -> None:
        """Give back a wake stream that was offered but never taken.

        The wake owner parks on ``buffer.released`` once it has offered its
        stream, so a claimer that unwinds between the offer and the claim would
        strand it there — it cannot even reach its own cleanup. Closing the
        buffer here is the release signal. Safe to call when nothing is pending,
        and it never suspends for an offered handoff (that buffer has no pump
        task), so it also works from inside a task being cancelled.
        """
        buffer = getattr(self, "_wake_handoff_buffer", None)
        ready = getattr(self, "_wake_handoff_ready", None)
        if buffer is None and (ready is None or not ready.is_set()):
            return
        self._wake_handoff_buffer = None
        if ready is not None:
            ready.clear()
        if buffer is not None:
            await buffer.close()

    async def _claim_wake_capture_for_dictation(self) -> _SessionInputBuffer | None:
        """Take the wake microphone over for a dictation, or return ``None``.

        A dictation is a session start like any other: whatever already owns the
        input device hands the live stream over, so the two never run side by
        side. Without this the common case — the wake loop sitting in
        ``_run_parallel_wake``, its steady state whenever Jarvis is idle — meant
        a dictation key press opened a SECOND native input stream on the same
        device for the whole dictation (AP-24 / the BUG-014 family).

        ``None`` means "no wake stream exists"; the caller then opens exactly one
        capture of its own. A pipeline built via ``__new__`` (the unit-test
        pattern) has no wake plumbing at all and takes the same path.
        """
        if getattr(self, "_wake_handoff_ready", None) is None:
            return None
        try:
            return await self._claim_wake_capture_for_session()
        except asyncio.CancelledError:
            # A dictation cancelled INSIDE the handoff window would otherwise
            # leave the wake loop waiting forever on a stream nobody will ever
            # release: permanently deaf with an app restart as the only cure
            # (BUG-037). Give the offered stream back before unwinding.
            await self._release_unclaimed_wake_handoff()
            raise
        except Exception as exc:  # noqa: BLE001 — never a crashed dictation
            _pl.log.warning("Dictation could not take over the wake microphone: %s", exc)
            await self._release_unclaimed_wake_handoff()
        # The lease ended ambiguously. Waiting for the wake side to finish
        # closing is the only safe way to reach a fallback capture; opening one
        # now could be the second stream this whole path exists to prevent.
        try:
            await asyncio.wait_for(
                self._wake_capture_released.wait(),
                timeout=_pl._DICTATION_WAKE_RELEASE_TIMEOUT_S,
            )
        except TimeoutError:
            raise RuntimeError(
                "The wake microphone did not release in time; refusing to open "
                "a second input stream for this dictation."
            ) from None
        return None

    @asynccontextmanager
    async def _capture_dictation_input(self) -> AsyncIterator[_ChunkSource]:
        """Own exactly ONE microphone for the duration of a dictation.

        Mirrors ``_capture_first_session_input``: borrow the live wake stream
        when there is one, otherwise open a single fallback capture. On the way
        out the borrowed stream is closed and the wake owner is awaited, so the
        wake loop re-arms its own microphone as soon as the dictation's block on
        activation lifts — including on the crash path, because the release runs
        in a ``finally``.

        Either way the stream ends up bound for a BULK consumer. That mattered
        more than it looked: the borrowed path is the one that actually runs on
        any install with a wake word, and it used to inherit the wake stream's
        shallow default. So the deep queue written for dictation below was dead
        code on exactly the machines that needed it, and a stalled loop cost
        seconds of speech — measured on the maintainer's box at 7.4 s gone from
        a 15.4 s recording, with nothing anywhere saying so.
        """
        buffer = await self._claim_wake_capture_for_dictation()
        if buffer is not None:
            restore_depth: int | None = None
            capture = getattr(buffer, "capture", None)
            if capture is not None:
                try:
                    restore_depth = capture.set_queue_depth(
                        _pl._DICTATION_CAPTURE_QUEUE_CHUNKS
                    )
                except Exception:  # noqa: BLE001 — a bound is a safeguard, never a gate
                    _pl.log.debug("dictation could not deepen the capture queue", exc_info=True)
            try:
                yield buffer
            finally:
                if capture is not None and restore_depth is not None:
                    # Hand the wake detector its shallow bound back. Leaving the
                    # deep one on would trade this fix for the other failure:
                    # a wake word scored against seconds-stale audio.
                    try:
                        capture.set_queue_depth(restore_depth)
                    except Exception:  # noqa: BLE001 — teardown never fails a dictation
                        _pl.log.debug("capture queue depth not restored", exc_info=True)
                # ``close()`` sets ``released`` before it awaits anything, so
                # the wake owner is freed even if this task is being cancelled.
                await buffer.close()
                # BOUNDED. This used to wait forever, and a wake owner whose
                # teardown wedged would have held the dictation task — and
                # every "a dictation is already running" refusal — open until
                # a restart (BUG-191 family). The wake side is told, loudly,
                # and the dictation goes on to deliver what it recorded.
                try:
                    await asyncio.wait_for(
                        self._wake_capture_released.wait(),
                        timeout=_pl._DICTATION_WAKE_RELEASE_TIMEOUT_S,
                    )
                except TimeoutError:
                    _pl.log.warning(
                        "The wake microphone did not confirm its release within "
                        "%.1fs after the dictation gave the stream back — "
                        "finishing the dictation anyway.",
                        _pl._DICTATION_WAKE_RELEASE_TIMEOUT_S,
                    )
            return

        async with _pl.MicrophoneCapture(
            device=self._input_device,
            device_priority=self._input_priority,
            # A dictation is a BULK consumer: every frame is the user's words,
            # so the queue's drop-oldest policy deletes speech rather than
            # staleness. It cannot be turned off (the audio thread must never
            # block), so the defence is depth — enough slack that a slow
            # provider call cannot cost words.
            max_queue_chunks=_pl._DICTATION_CAPTURE_QUEUE_CHUNKS,
            # A key press / button started this capture, so a lost grant is
            # reported as a user-origin ``dictation`` episode.
            permission_feature="dictation",
            interactive=True,
        ) as mic:
            yield mic

    def _wake_listening_enabled(self) -> bool:
        return self._openwakeword_enabled or self._whisper_wake_enabled

    async def _wait_while_wake_disabled(self) -> None:
        """Wait on ``_wake_reload_event`` while both wake detectors are off.

        Touches no permission and opens no episode: a switched-off wake word never
        owns the microphone permission (P7). Returns at once when a detector is on.
        """
        while not self._wake_listening_enabled():
            _pl.log.warning(
                "Both wake detectors are disabled — wake is PARKED until a "
                "wake-word change re-enables one (voice still works via hotkey). "
                "Waiting on a live wake-plan reload, not sleeping forever."
            )
            try:
                await asyncio.wait_for(self._wake_reload_event.wait(), timeout=30.0)
            except TimeoutError:
                pass  # the 30 s fallback poll: no reload came, the loop re-reads the plan
            finally:
                self._wake_reload_event.clear()

    async def _wake_loop(self) -> None:
        """Listen for a wake phrase through two parallel paths while idle.

        One microphone stream fans out into two queues:
        (1) openWakeWord queue -> fast primary detector.
        (2) Whisper wake queue -> robust fallback.

        The first detector hit arms ``call_event`` and cancels both detectors.
        """
        _pl.log.info(
            "Wake-Loop gestartet (oww=%s, whisper=%s, gate=%s).",
            "on" if self._openwakeword_enabled else "off",
            "on" if self._whisper_wake_enabled else "off",
            "open" if self._activation_allowed() else "closed",
        )
        # Both detectors off: PARK, do not die. The old code did
        # ``await asyncio.Event().wait()`` on a FRESH event nobody ever sets —
        # a permanent sleep that not even a later live wake-word change could
        # re-arm (only an app restart). Wait on ``_wake_reload_event`` instead so
        # a ``set_wake_plan`` that re-enables a detector wakes the loop back up,
        # in-app. The 30 s timeout re-logs the parked state so a genuinely dead
        # listener stays visible without busy-spinning. (Mission: "no dead state
        # blocks waking"; AP-22: recovery must be reachable in-app, not a restart.)
        await self._wait_while_wake_disabled()
        gate_blocked_logged_at = 0.0
        stuck_logged_at = 0.0
        while True:
            # Re-checked on EVERY pass, not only before the loop: a user who
            # switches the wake word OFF while the loop is parked on the
            # microphone permission must send it back to the "disabled" wait,
            # or it would re-open a wake_word permission episode every park
            # interval for a feature nobody switched on (P7).
            await self._wait_while_wake_disabled()
            if not self._activation_allowed():
                now = time.time()
                if now - gate_blocked_logged_at > 30.0:
                    # Name the REAL reason. This line used to guess between two
                    # causes and the wrong guess once misled a live freeze
                    # diagnosis, so the reason comes from ONE resolver that
                    # knows every branch of the gate — including a running
                    # dictation, which is the third way to close it.
                    _pl.log.info(
                        "Wake loop is waiting — activation gate closed (%s).",
                        self._activation_block_reason() or "reason unknown",
                    )
                    gate_blocked_logged_at = now
                if self._activation_state_allows():
                    # Only the microphone permission is missing. Mute, a running
                    # dictation and mic ownership change on their own clock and
                    # keep the short poll below; a permission changes rarely and
                    # announces itself, so the loop PARKS instead of re-probing.
                    await self._park_until_microphone_allowed()
                else:
                    await asyncio.sleep(0.25)
                continue
            if self._state != _pl.PipelineState.IDLE:
                await asyncio.sleep(0.1)
                continue
            try:
                _pl.log.info(
                    "🎧 Wake-Listener aktiv — sag '%s' …",
                    getattr(self, "_wake_phrase_label", "the wake word"),
                )
                await self._run_parallel_wake()
            except _pl.MicrophoneAccessError as exc:
                # The grant is missing or was just lost: not a crash, so no
                # traceback and no 0.5 s retry churn. Park until it is granted.
                _pl.log.info("Wake listening paused: %s", exc)
                await self._park_until_microphone_allowed()
            except _pl.MicrophoneStuckError as exc:
                # The audio system stopped answering for the microphone. Not a
                # crash either: the capture has told the person, and asking
                # again every half second would only fill the log. Listening
                # resumes by itself once the audio system answers.
                now = time.time()
                if now - stuck_logged_at > _pl._WAKE_STUCK_LOG_EVERY_S:
                    _pl.log.warning("Wake listening paused: %s", exc)
                    stuck_logged_at = now
                await asyncio.sleep(_pl._WAKE_STUCK_RETRY_S)
            except Exception as exc:  # noqa: BLE001
                _pl.log.exception("Wake loop failed: %s", exc)
                await asyncio.sleep(0.5)

    async def _park_until_microphone_allowed(self) -> None:
        """Park the wake loop until the microphone is granted (never asks).

        The wake word is a background feature: it must not make macOS ask, and it
        must not poll either. So the loop opens ONE background-origin episode
        (``ensure(interactive=False)``: no request, status snapshot only), which is
        what lets the permission service watcher notice a grant given later in
        System Settings and publish ``PermissionResolved``; ``_on_permission_resolved``
        then sets ``_wake_reload_event``. ``set_wake_plan`` and the 30 s fallback
        timeout wake the loop through the same event, so a missed edge costs at most
        half a minute, never a restart. The episode is re-opened on each wake-up
        that still finds the gate closed (idempotent in the service: same episode,
        no second event), which also revives one the service expired after ten
        minutes of nobody touching it.
        """
        if not self._wake_listening_enabled():
            return  # switched off since the caller read the gate: no episode (P7)
        self._wake_parked_on_permission = True
        try:
            try:
                opened = await self._permission_service().ensure_async(
                    "microphone", feature="wake_word", interactive=False
                )
            except Exception:  # noqa: BLE001 - the park must work without the episode
                _pl.log.debug("Opening the wake-word permission episode failed.", exc_info=True)
            else:
                if opened.granted:
                    # Granted between the gate read and now: no episode was opened,
                    # so no edge will come. Let the caller re-read the gate.
                    await asyncio.sleep(0.25)
                    return
            try:
                await asyncio.wait_for(
                    self._wake_reload_event.wait(), timeout=_pl._WAKE_PERMISSION_PARK_S
                )
            except TimeoutError:
                pass  # fallback poll: the caller re-reads the gate
        finally:
            self._wake_parked_on_permission = False
            self._wake_reload_event.clear()

    def _should_show_optimistic_candidate(self) -> bool:
        """Whether an unverified OWW hit may pop the overlay bar immediately.

        The optimistic reveal exists so a genuine "Hey Jarvis" feels instant on
        the precise pretrained model, where false candidates are rare and a
        reject costs one brief bar flash. Custom ONNX and Vosk grammar stage-one
        candidates both match ordinary speech frequently, so those engines wait
        for the authoritative ``WakeWordDetected`` event after full verification.
        (vosk_kws additionally gets the PROVIDER-gated early candidate below —
        that one is mini-verified, not raw, and does not pass through here.)
        """
        if self._state != _pl.PipelineState.IDLE:
            return False
        if self._dictation_blocks_activation():
            # A dictation leaves ``_state`` at IDLE on purpose, so without this
            # clause an unverified candidate would still flash the bar out of
            # its dictation look and back, mid-recording.
            return False
        plan = getattr(self, "_wake_plan", None)
        if plan is None:
            return True
        return getattr(plan, "engine", "") == "openwakeword"

    async def _vosk_early_candidate_listener(self, active: bool) -> None:
        """Visual-only bar signal from the vosk provider's mini-verify.

        Deliberately NOT routed through ``_should_show_optimistic_candidate``:
        that helper gates the RAW pre-verify reveal (openwakeword-only, see
        revert 5fe5c4d2). The vosk provider only calls this after its
        mini-verify passed — re-score confidence + span RMS + localized sound
        confirm on the truncated ring — measured at 0/2500 room-speech windows
        shown for "hey jarvis" (calibration 2026-07-11), so the flicker class
        that forced the revert cannot recur. Retracts (active=False) always
        pass through so a shown bar can never stay stuck.
        """
        if active and self._state != _pl.PipelineState.IDLE:
            return  # a session is already running; nothing to reveal
        if active and self._dictation_blocks_activation():
            return  # a dictation owns the bar; never flash the wake look over it
        if active:
            self._begin_wake_preroll()
        else:
            self._discard_wake_preroll()
        await self._publish_event(
            _pl.WakeCandidateDetected(source_layer="speech", active=active)
        )

    async def _verify_oww_hit(self, pcm_snapshot: bytes) -> bool:
        """Second-stage gate: ask the utterance STT whether the few seconds
        leading up to an OpenWakeWord hit actually contained the configured
        wake phrase. Returns True if the phrase's matcher confirms it.

        STT-outage failure modes degrade OPEN (return True with a log line) so
        a misconfigured STT, a network blip, or a rate-limit cannot brick the
        wake — we'd rather accept the occasional false positive than have the
        user shout into a dead listener. A clear, non-matching transcript
        (genuine other speech) suppresses, preserving the bare-"Jarvis"
        BUG-009 guard. How a WORKING STT that heard no speech (empty
        transcript / silence-hallucination boilerplate) is treated depends on
        the engine: a user-trained custom_onnx hit SUPPRESSES (live forensic
        2026-07-01 — such models false-fire on breath/noise, so "no speech
        heard" is evidence of a false fire, not an STT problem), while any
        other OWW hit keeps the historical degrade-open behaviour (forensic
        2026-06-28 — short real wakes often mis-transcribe to nothing).
        """
        if not self._require_hey_prefix:
            return True
        # The STT re-verification runs for user-trained custom_onnx models
        # (live forensic 2026-07-01: a few-shot model scored breath/ambient/
        # other speech up to 1.000 — a false-positive storm; the transcript
        # matched against the phrase's own sound-folded fuzzy matcher is the
        # real discriminator). Since the product ships no pretrained model
        # (design 2026-07-07), custom_onnx plans are the only source of OWW
        # hits; vosk_kws is exempt via verify_prefix=False (its own confirm).
        plan = getattr(self, "_wake_plan", None)
        if plan is not None and not getattr(plan, "verify_prefix", True):
            return True
        # A user-trained custom_onnx model is a WEAK discriminator (live
        # forensic 2026-07-01/02: scores up to 1.000 on breath/ambient/other
        # speech, 15 fires in 25 s at the worst). Its hits get the strict
        # treatment throughout this gate.
        custom_model_hit = (
            plan is not None and getattr(plan, "engine", "") == "custom_onnx"
        )
        # Silence gate (custom only, BEFORE any STT round-trip): a hit whose
        # trailing audio is essentially silent is a breath/noise false fire by
        # definition — there is no speech an STT could confirm. Suppressing it
        # here (a) kills the "fires out of nowhere" storm at zero cost and
        # (b) stops the fire flood from hammering the verify STT into
        # 429/timeouts (live 2026-07-02: that flood-induced outage is what
        # opened the degrade-open hole and produced ghost activations).
        if custom_model_hit and pcm_snapshot:
            tail_rms = _pl.pcm_tail_rms(pcm_snapshot)
            if tail_rms < _pl.CUSTOM_WAKE_MIN_RMS:
                _pl.log.info(
                    "wake-verify: suppressed — near-silent audio "
                    "(rms %.4f < %.3f) on a custom-model hit; skipping STT",
                    tail_rms,
                    _pl.CUSTOM_WAKE_MIN_RMS,
                )
                return False
        if self._utterance_stt is None:
            _pl.log.warning(
                "require_hey_prefix=True but no utterance STT — accepting OWW hit"
            )
            return True
        # Nothing captured yet (empty ring buffer) — there is genuinely no audio
        # to confirm the wake, so reject without an STT round-trip. (Whether a
        # NON-empty buffer with no usable transcript suppresses or degrades
        # open is engine-dependent — see below.)
        if not pcm_snapshot:
            return False
        # Pass the RESOLVED wake language. Omitting it fell back to the
        # parameter default ("de"), so every custom-model wake on earth was
        # verified by telling the cloud STT the audio is German — a systematic
        # garble for an English, Spanish or any other user, on the one engine
        # AP-25 names as the endgame. Uses the same resolver the wake plan and
        # the model download use, so selection and verification always agree.
        try:
            from dodaios.speech.wake_model_fetch import resolve_wake_language

            verify_language = resolve_wake_language(self._config)
        except Exception:  # noqa: BLE001 — never let a language lookup kill a wake
            verify_language = None
        matched, text = await _pl.verify_wake_with_stt(
            self._utterance_stt,
            pcm_snapshot,
            language=verify_language,
            matcher=getattr(self, "_wake_matcher", None),
        )
        if matched:
            return True
        # For a custom-model hit, a WORKING STT that heard no wake phrase —
        # an empty transcript or a known silence-hallucination boilerplate —
        # is evidence of a false fire and must SUPPRESS. Any other OWW hit
        # keeps the documented degrade-open behaviour (historical forensic
        # 2026-06-28: false fires happened on real speech, so an empty
        # transcript there really does mean the STT failed).
        #
        # Persistent verify-STT failure (Groq 429/503/timeout after retries):
        # - non-custom hit: degrade OPEN. Candidates are rare, so an
        #   unreachable STT is a provider problem, not evidence about what the
        #   user said; accepting keeps the wake alive through an outage (AP-22).
        # - custom_onnx: FAIL CLOSED (live 2026-07-02, 3 ghost activations
        #   overnight). The fire flood of a weak model eventually hits an STT
        #   timeout, and degrade-open then activates Jarvis although nobody
        #   spoke. The session a wake opens needs that same STT to hear
        #   anything (it would be a deaf session), and hotkey/orb-click remain
        #   as in-app activation paths — honest degradation, not a bricked
        #   wake.
        if text is None:
            if custom_model_hit:
                _pl.log.info(
                    "wake-verify: suppressed — verify STT unreachable on a "
                    "custom-model hit (fail-closed: the session would be deaf "
                    "without STT; hotkey/orb-click still activate)"
                )
                return False
            _pl.log.info(
                "wake-verify: verify STT unreachable on a strong OWW hit — "
                "accepting (degrade-open; an STT outage must not brick the "
                "wake, AP-22)"
            )
            return True
        text = text.strip()
        # KNOWN STT hallucination boilerplate ("Untertitelung des ZDF, 2020",
        # "Vielen Dank."). Whisper emits these on silence/noise buffers.
        # - custom_onnx: the buffer held silence/noise → the model false-fired
        #   on breath/ambient → suppress (fail-closed).
        # - non-custom hit: forensic 2026-06-28 showed short REAL wake
        #   buffers hallucinate these for ~half of all valid wakes → accept
        #   (degrade-open), else the wake "stops working" intermittently.
        # An arbitrary non-matching transcript (genuine OTHER speech) still
        # suppresses for both, so the bare-"Jarvis" guard (BUG-009) stays.
        if text and _pl._STT_HALLUCINATION_RE.search(text) is not None:
            if custom_model_hit:
                _pl.log.info(
                    "wake-verify: suppressed — STT hallucination %r on a "
                    "custom-model hit (silence/noise false fire, fail-closed)",
                    text[:80],
                )
                return False
            _pl.log.info(
                "wake-verify: STT hallucination %r on a strong OWW hit — "
                "accepting (degrade-open, not a real rejection)",
                text[:80],
            )
            return True
        # The verify STT WORKED and produced an empty transcript.
        # - custom_onnx: no speech in the buffer → breath/noise false fire →
        #   suppress. This is the "fires out of nowhere" half of the
        #   2026-07-01 storm.
        # - non-custom hit: an empty transcription on a strong hit is far
        #   more likely a silence-mis-transcription of a short real wake than
        #   a spontaneous model fire → accept (degrade-open, forensic
        #   2026-06-28 "the wake sometimes stops working entirely").
        if not text:
            if custom_model_hit:
                _pl.log.info(
                    "wake-verify: suppressed — empty transcript on a "
                    "custom-model hit (no speech captured, fail-closed)"
                )
                return False
            _pl.log.info(
                "wake-verify: verify STT returned no transcript on a strong OWW "
                "hit — accepting (degrade-open)"
            )
            return True
        _pl.log.info(
            "wake-verify: suppressed — transcript %r has no wake prefix", text[:80]
        )
        return False

    async def _run_parallel_wake(self) -> None:
        """Fan one wake microphone into all detectors until the first hit."""
        # Detector backlogs are latency budgets, not arbitrary chunk counts.
        # Keep OWW within ~0.6 s and the slower Whisper consumer within ~1.2 s;
        # both queues drop oldest on overflow, so an overloaded host evaluates
        # recent audio instead of a wake word heard several seconds ago.
        #
        # A detector that can CATCH UP in batches (``coalesce_catchup_s``, see
        # ``_wake_catchup_budget``) may declare a deeper ``intake_backlog_s``:
        # its confirm pass blocks its own consumption for 0.4-0.9 s on a weak
        # CPU, which overflowed the 0.6 s queue at every candidate (live
        # 2026-08-19, ``oww_q=19``) and dropped frames INSIDE the audio it
        # was about to verify — the re-score then heard '' and the user had to
        # repeat. With batching it drains a deeper backlog in one or two
        # decodes, so nothing it could still use is ever dropped; a detector
        # without batching keeps the shallow budget, because for it a deeper
        # queue would only mean a later wake.
        coalesce, intake_chunks = _pl._wake_catchup_budget(self._wake)
        oww_queue: asyncio.Queue = asyncio.Queue(maxsize=intake_chunks)
        whisper_queue: asyncio.Queue = asyncio.Queue(
            maxsize=_pl.REALTIME_QUEUE_CHUNKS * 2
        )
        detector_queues = [oww_queue] if self._openwakeword_enabled else []
        if self._whisper_wake_enabled and self._whisper_wake is not None:
            detector_queues.append(whisper_queue)
        if not detector_queues:
            await asyncio.sleep(1.0)
            return

        # Rolling PCM ring buffer for post-OWW prefix verification (see
        # ``_verify_oww_hit``). 2.5 s at 16 kHz mono int16 ≈ 80 kB, well above
        # the longest natural "Hey Jarvis" plus a little headroom. We keep the
        # buffer regardless of whether prefix verification is enabled so the
        # cost is identical between modes and a runtime config flip never
        # needs to re-arm fanout.
        ring_bytes = bytearray()
        RING_MAX = 16_000 * 2 * 3  # ~3 s
        # Rolling overlap for the EXPLICIT (hotkey/PTT) handoff seed: it must
        # cover the whole press-to-claim latency — key poll (~20 ms), the
        # cross-thread call edge, one state-loop turn and the stop-event round
        # trip — or the user's first syllables land in the wake detectors
        # instead of the session.
        recent_chunks: deque[AudioChunk] = _pl.deque(
            maxlen=_pl.capture_chunks_for_duration(0.5)
        )  # ~500 ms overlap
        wake_confirmed = False
        handoff_buffer: _SessionInputBuffer | None = None

        async def _fanout(mic: MicrophoneCapture) -> None:
            source_error: BaseException | None = None
            try:
                async for chunk in mic.stream():
                    # Input mute (Jarvis-scoped): if the user mutes while a wake
                    # session is already mid-wait, stop feeding the detectors so
                    # Jarvis goes deaf immediately — without touching the OS mic.
                    # (A fresh mute while IDLE is already handled by _wake_loop's
                    # _activation_allowed() gate, which never opens the mic.)
                    muted = getattr(self, "_muted", False)
                    # A dictation is the second way this stream stops belonging
                    # to the wake word. It is the same STATE gate the activation
                    # predicate uses (never transcript content — AP-27).
                    dictating = self._dictation_blocks_activation()
                    if handoff_buffer is not None:
                        # The stream has been handed to whoever claimed it. Mute
                        # still starves a VOICE session (input-only mute), but
                        # never the dictation lane: an explicit dictation press
                        # is the user deliberately speaking into their own text
                        # field, and the lane's own fallback capture has always
                        # ignored mute. Dropping frames here would make a
                        # dictation silently record nothing whenever the wake
                        # microphone happened to be the one it took over.
                        if muted and not dictating:
                            continue
                        handoff_buffer.put(chunk)
                        continue
                    if muted or dictating:
                        # Nothing claimed the stream, so these frames would go
                        # to the wake detectors. While a dictation is running
                        # they are the user's dictated words: feeding them to a
                        # detector both risks tripping the wake word mid-
                        # dictation and shares this native engine with the
                        # dictation's own transcription (AP-24).
                        continue
                    ring_bytes.extend(chunk.pcm)
                    if len(ring_bytes) > RING_MAX:
                        del ring_bytes[: len(ring_bytes) - RING_MAX]
                    recent_chunks.append(chunk)
                    if self._wake_preroll_active:
                        self._pending_session_preroll.append(chunk)
                        _pl._feed_live_mic_level(chunk)
                    for q in detector_queues:
                        try:
                            q.put_nowait(chunk)
                        except asyncio.QueueFull:
                            # Keep detector latency bounded by dropping its oldest frame.
                            try:
                                q.get_nowait()
                                q.put_nowait(chunk)
                            except asyncio.QueueEmpty:
                                pass
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 - surface to consumers
                source_error = exc
                raise
            finally:
                if handoff_buffer is not None:
                    handoff_buffer.finish(error=source_error)

        def _activate_handoff(*, confirmed: bool) -> _SessionInputBuffer:
            nonlocal handoff_buffer
            if handoff_buffer is not None:
                return handoff_buffer
            if confirmed:
                initial = self._take_wake_preroll()
            else:
                # An explicit click/hotkey may arrive while a wake candidate is
                # still being verified. Preserve that already-visible interval;
                # otherwise seed the full rolling overlap. The user starts
                # talking AT the press, and the press precedes this claim by
                # the key-poll + call-edge + state-loop latency — seeding only
                # the last block (the old behaviour) cut the first syllables
                # off every "press and talk" capture.
                initial = (
                    tuple(self._pending_session_preroll)
                    if self._wake_preroll_active
                    else tuple(recent_chunks)
                )
                self._discard_wake_preroll()
            handoff_buffer = _pl._SessionInputBuffer(initial=initial, capture=mic)
            self._wake_handoff_buffer = handoff_buffer
            self._wake_handoff_ready.set()
            return handoff_buffer

        async def _run_oww() -> str:
            # Capability-gated catch-up: a detector that can consume variable
            # chunk sizes (vosk_kws) advertises how much backlogged audio may
            # be coalesced into one catch-up batch, so a busy CPU never leaves
            # it grinding through seconds-stale audio (the inconsistent
            # multi-second wake delay, live 2026-07-21). ``coalesce`` comes
            # from the same resolver that sized the queue above.
            async for kw in self._wake.detect(
                _pl._queue_iter(oww_queue, coalesce_max_chunks=coalesce)
            ):
                return f"oww:{kw}"
            return ""

        async def _run_whisper() -> str:
            if self._whisper_wake is None:
                await asyncio.Event().wait()  # never completes
                return ""
            async for kw in self._whisper_wake.detect(_pl._queue_iter(whisper_queue)):
                return f"whisper:{kw}"
            return ""

        # NOTE: the wake mic keeps the DEEP default queue on purpose. Its
        # detectors offload inference (openWakeWord ``to_thread``; whisper-wake
        # ``await transcribe_pcm``), so the event loop stays free and the cheap
        # ``_fanout`` drains this queue near-instantly — it never fills, so a
        # shallow depth would be inert here anyway. The wake path's real staleness
        # lever is the per-detector queues below (``oww_queue`` / ``whisper_queue``),
        # which belong to the wake layer; this change deliberately does not touch
        # them. The drop-OLDEST overflow policy (capture ``_safe_put``) still
        # applies and is safe here.
        async with _pl._wake_capture_with_release(
            _pl.MicrophoneCapture(
                device=self._input_device,
                device_priority=self._input_priority,
                # Background capture: it never makes macOS ask (the gate above
                # already required a live grant) and reports a lost grant as
                # ``wake_word``.
                permission_feature="wake_word",
                interactive=False,
            ),
            self._wake_capture_released,
        ) as mic:
            fanout_task = asyncio.create_task(_fanout(mic), name="fanout")
            oww_task = (
                asyncio.create_task(_run_oww(), name="oww-wake")
                if self._openwakeword_enabled
                else None
            )
            tasks = [fanout_task]
            if oww_task is not None:
                tasks.append(oww_task)
            if self._whisper_wake_enabled:
                whisper_task = asyncio.create_task(_run_whisper(), name="whisper-wake")
                tasks.append(whisper_task)
            else:
                whisper_task = None  # type: ignore[assignment]

            async def _detector_heartbeat() -> None:
                """Log every ten seconds while all detector tasks remain alive.

                Missing output while the watchdog is running exposes a silently
                failed task, such as a queue deadlock or swallowed exception.
                """
                def _detector_state(task: asyncio.Task[Any] | None) -> str:
                    """alive / parked / FAILED / off.

                    ``DEAD`` used to cover all of "stopped normally",
                    "cancelled" and "raised", so the log screamed DEAD for the
                    ENTIRELY NORMAL case of a detector parked while a voice
                    session owns the microphone — verified against the desktop
                    logs, where every DEAD window coincides with an active
                    session and recovers when it ends. That cost a forensic
                    detour: a healthy state that reads as a crash is worse than
                    no signal at all.
                    """
                    if task is None:
                        return "off"
                    if not task.done():
                        return "alive"
                    if task.cancelled():
                        return "parked"
                    return "FAILED" if task.exception() is not None else "parked"

                while True:
                    await asyncio.sleep(10.0)
                    # The detector's OWN counters name exactly the failure modes
                    # a recall complaint has to distinguish (candidates seen,
                    # gated on energy, suppressed by the confirm, suppressed by
                    # cooldown, fired). They were maintained and never read, so
                    # "how many of my wakes were suppressed?" needed a debugger.
                    # Read-only: nothing here may ever feed a decision.
                    try:
                        stats = getattr(self._wake, "stats", None)
                        detector_stats = stats() if callable(stats) else {}
                    except Exception:  # noqa: BLE001 — diagnostics never break the loop
                        detector_stats = {}
                    _pl.log.info(
                        "wake-detectors-heartbeat: fanout=%s oww=%s whisper=%s "
                        "oww_q=%d wsp_q=%d%s",
                        "alive" if not fanout_task.done() else "FAILED",
                        _detector_state(oww_task),
                        _detector_state(whisper_task),
                        oww_queue.qsize(),
                        whisper_queue.qsize(),
                        (
                            " " + " ".join(f"{k}={v}" for k, v in detector_stats.items())
                            if detector_stats
                            else ""
                        ),
                    )
                    # Surface a detector task that exited with an exception.
                    for t in (oww_task, whisper_task):
                        if t is None or not t.done():
                            continue
                        try:
                            t.result()
                        except asyncio.CancelledError:
                            pass
                        except Exception as exc:  # noqa: BLE001
                            _pl.log.error("Detector task %s failed: %s", t.get_name(), exc)

            heartbeat_task = asyncio.create_task(_detector_heartbeat(), name="wake-heartbeat")

            # Live-apply: a set_wake_plan() flips _wake_reload_event so we abort
            # this mic/detector session and let _wake_loop re-arm with the new
            # model/matcher — the wake word changes without an app restart.
            reload_task = asyncio.create_task(
                self._wake_reload_event.wait(), name="wake-reload"
            )
            tasks.append(reload_task)
            handoff_task = asyncio.create_task(
                self._wake_stop_event.wait(), name="wake-session-handoff"
            )
            tasks.append(handoff_task)
            cancel_task = asyncio.create_task(
                self._wake_cancel_event.wait(), name="wake-candidate-cancel"
            )
            tasks.append(cancel_task)

            async def _cancel_candidate() -> None:
                self._wake_cancel_event.clear()
                if self._wake_preroll_active:
                    await self._publish_event(
                        _pl.WakeCandidateDetected(source_layer="speech", active=False)
                    )
                self._discard_wake_preroll()

            try:
                # Wait for one detector, a live reload, or a session handoff.
                done, _pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done:
                    await _cancel_candidate()
                    return
                if fanout_task in done:
                    if not fanout_task.cancelled():
                        exc = fanout_task.exception()
                        if exc is not None:
                            _pl.log.warning("Wake microphone fanout ended: %s", exc)
                    return
                if handoff_task in done:
                    buffer = _activate_handoff(confirmed=False)
                    await buffer.released.wait()
                    return
                if reload_task in done:
                    self._wake_reload_event.clear()
                    _pl.log.info(
                        "🔁 Wake-Live-Reload — re-arming with the new wake word."
                    )
                    return  # finally cancels detectors + closes mic; loop re-enters
                for t in done:
                    if t in {reload_task, handoff_task, cancel_task}:
                        continue
                    result = t.result()
                    if result:
                        # The detector hit marks the earliest truthful visual
                        # edge. Do not seed pre-hit audio: it contains the wake
                        # phrase itself and could become a phantom user turn.
                        self._begin_wake_preroll()
                        _pl.log.info("🎙 Wake candidate from %s", result)
                        # Prefix verifier: an OWW hit is only a *candidate*
                        # until the cloud STT confirms "hey/hi/hallo + jarv"
                        # in the few seconds before the trigger. Whisper-wake
                        # already enforces the same pattern, so its hits skip
                        # the second stage. See ``_verify_oww_hit``.
                        if result.startswith("oww:"):
                            # Optimistic VISUAL reveal: pop the overlay bar NOW,
                            # before the slow STT prefix-verify below, so the bar
                            # feels instant on "Hey Jarvis". This is visual-only
                            # (WakeCandidateDetected never opens a session turn),
                            # so a rejected candidate costs a brief bar flash, not
                            # a phantom session — retracted just below on reject.
                            # Custom-model candidates never reveal optimistically
                            # (constant flicker, see the helper's docstring).
                            show_candidate = self._should_show_optimistic_candidate()
                            if show_candidate:
                                await self._publish_event(
                                    _pl.WakeCandidateDetected(
                                        source_layer="speech", active=True
                                    )
                                )
                            verify_task = asyncio.create_task(
                                self._verify_oww_hit(bytes(ring_bytes)),
                                name="wake-prefix-verify",
                            )
                            verify_done, _ = await asyncio.wait(
                                {
                                    verify_task,
                                    handoff_task,
                                    cancel_task,
                                    fanout_task,
                                },
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if cancel_task in verify_done:
                                verify_task.cancel()
                                try:
                                    await verify_task
                                except asyncio.CancelledError:
                                    pass
                                await _cancel_candidate()
                                return
                            if fanout_task in verify_done:
                                verify_task.cancel()
                                try:
                                    await verify_task
                                except asyncio.CancelledError:
                                    pass
                                await _cancel_candidate()
                                if not fanout_task.cancelled():
                                    exc = fanout_task.exception()
                                    if exc is not None:
                                        _pl.log.warning(
                                            "Wake microphone fanout ended during "
                                            "candidate verification: %s",
                                            exc,
                                        )
                                return
                            if handoff_task in verify_done:
                                verify_task.cancel()
                                try:
                                    await verify_task
                                except asyncio.CancelledError:
                                    pass
                                buffer = _activate_handoff(confirmed=False)
                                await buffer.released.wait()
                                return
                            verified = verify_task.result()
                            if not verified:
                                if show_candidate:
                                    await self._publish_event(
                                        _pl.WakeCandidateDetected(
                                            source_layer="speech", active=False
                                        )
                                    )
                                _pl.log.info(
                                    "🚫 Wake rejected: no greeting prefix in the "
                                    "last three seconds of transcript."
                                )
                                # Clear the detector's debounce cooldown: this
                                # candidate was a false positive, so a genuine
                                # "Hey Jarvis" spoken right after must NOT be
                                # swallowed for the full cooldown window.
                                note_rejected = getattr(
                                    self._wake, "note_rejected_candidate", None
                                )
                                if callable(note_rejected):
                                    note_rejected()
                                break
                        _pl.log.info("🎙 Wake confirmed by %s", result)
                        if self._state == _pl.PipelineState.IDLE:
                            # The state-loop SILENTLY drops a wake that arrives
                            # inside the post-hangup echo lock (or when the app
                            # is not activatable) — it just ``continue``s. But
                            # _emit_wake below publishes WakeWordDetected, which
                            # flips the overlay bar to its "listen" look. Emitting
                            # for a wake the loop will then drop leaves the bar
                            # stuck "listening" with no session behind it, and the
                            # user is ignored ("wake triggers, nothing happens").
                            # Mirror the loop's gate HERE, before _emit_wake, and
                            # retract the optimistic candidate instead of lying.
                            now = time.time()
                            locked = now < self._wake_lock_until
                            # The vosk provider may have shown a mini-verified
                            # early candidate for THIS wake — consume the flag
                            # either way; retract below if the wake is dropped.
                            consume = getattr(
                                self._wake, "consume_early_candidate", None
                            )
                            early_shown = consume() if callable(consume) else False
                            if locked or not self._activation_allowed():
                                if locals().get("show_candidate") or early_shown:
                                    await self._publish_event(
                                        _pl.WakeCandidateDetected(
                                            source_layer="speech", active=False
                                        )
                                    )
                                if locked:
                                    _pl.log.info(
                                        "🔒 Wake lock active; discarding detection "
                                        "for another %.1fs.",
                                        max(0.0, self._wake_lock_until - now),
                                    )
                                else:
                                    # Same resolver as every other gated site —
                                    # a hardcoded guess here named the wrong
                                    # cause during a live diagnosis.
                                    _pl.log.info(
                                        "Wake detection discarded: %s.",
                                        self._activation_block_reason()
                                        or "activation not allowed",
                                    )
                                break
                            # The UI consumes WakeWordDetected plus supervisor
                            # state to reveal its listening surface.
                            keyword = result.split(":", 1)[-1] if ":" in result else result
                            self._wake_preroll_confirmed = True
                            wake_confirmed = True
                            buffer = _activate_handoff(confirmed=True)
                            await self._emit_wake(keyword)
                            self._arm_call_event()
                            await buffer.released.wait()
                        break
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):  # noqa: S110 - teardown
                    pass
                for t in tasks:
                    if not t.done():
                        t.cancel()
                for t in tasks:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):  # noqa: S110 - teardown
                        pass
                # An exception/cancellation between offering the buffer and the
                # state loop claiming it must not leave a ready latch pointing
                # at stale audio for the next activation.
                if (
                    handoff_buffer is not None
                    and self._wake_handoff_buffer is handoff_buffer
                ):
                    self._wake_handoff_buffer = None
                    self._wake_handoff_ready.clear()
                    await handoff_buffer.close()
                self._wake_cancel_event.clear()
                self._wake_stop_event.clear()
                if not wake_confirmed:
                    self._discard_wake_preroll()
