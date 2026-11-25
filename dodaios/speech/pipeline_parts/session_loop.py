"""State loop, earcons and active sessions.

Moved out of ``pipeline.py`` without a behaviour change. Module-level names
of the pipeline are read through ``_pl`` at call time so the pipeline module
stays the one place that owns and patches them.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from dodaios.speech import pipeline as _pl

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncIterator

    from dodaios.core.protocols import AudioChunk
    from dodaios.speech.pipeline import _SessionInputBuffer


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class SessionLoopMixin(_HostBase):
    """State loop, earcons and active sessions."""

    # ------------------------------------------------------------------
    # State-Loop
    # ------------------------------------------------------------------

    async def _state_loop(self) -> None:
        while True:
            await self._call_event.wait()
            self._call_event.clear()
            now = time.time()
            # Consume the explicit-edge marker for THIS call before any gate
            # decides.
            explicit_call = bool(getattr(self, "_explicit_call_pending", False))
            self._explicit_call_pending = False
            allowed = (
                self._gesture_activation_allowed()
                if explicit_call
                else self._activation_allowed()
            )
            if not allowed:
                # Resolved, never guessed: this backstop closes for a mute and
                # for a running dictation too, and a log line that names the
                # window instead is exactly what misled an earlier diagnosis.
                # A deliberate press (``explicit_call``) is judged by the
                # user-gesture predicate, a wake word by the background one.
                _pl.log.info(
                    "Voice call ignored: %s.",
                    self._activation_block_reason(explicit=explicit_call)
                    or "activation not allowed",
                )
                await self._abort_pending_wake_handoff()
                continue
            if now < self._wake_lock_until and not explicit_call:
                # The speaker-echo lock gates only WAKE-WORD calls: the tail of
                # Jarvis' own TTS can re-trigger the wake word, but it cannot
                # press a key. Dropping explicit presses here made a quick
                # follow-up ("press and talk") record nothing until the lock
                # expired — the opening words of the capture were missing.
                remaining = self._wake_lock_until - now
                _pl.log.info("Wake lock active; ignoring call for %.1fs.", remaining)
                await self._abort_pending_wake_handoff()
                continue
            # Preserve a close accepted after the confirmed wake offered its
            # microphone but before this loop entered ACTIVE. Clearing it here
            # would reopen the visibly closed bar and submit the buffered words.
            handoff_offered = bool(
                self._wake_handoff_buffer is not None
                or self._wake_handoff_ready.is_set()
            )
            handoff_close_latch = getattr(
                self, "_wake_handoff_hangup_pending", None
            )
            preserve_handoff_close = bool(
                handoff_offered
                and handoff_close_latch is not None
                and handoff_close_latch.is_set()
            )
            if handoff_close_latch is not None:
                handoff_close_latch.clear()
            if not preserve_handoff_close:
                self._external_hangup_pending.clear()
                self._hangup_event.clear()
                self._hangup_confirmation = _pl.HangupConfirmation()
                # Forget a hard-hangup flag left by a no-op while truly idle.
                # A close after handoff is real and retains the short wake lock.
                self._explicit_hard_hangup = False
            self._state = _pl.PipelineState.ACTIVE
            self._voice_start_monotonic = (
                time.monotonic() if explicit_call
                else getattr(self, "_wake_detected_monotonic", None) or time.monotonic()
            )
            self._wake_detected_monotonic = None
            self._listening_cue_started = False
            self._listening_cue_task: asyncio.Task[None] | None = None
            session_id = str(_pl.uuid4())
            self._termination_producer = ""
            self._termination_detail = {}
            self._idle_deadline_monotonic = None
            self._last_user_activity_monotonic = None
            self._last_answer_floor_monotonic = None
            self._previous_turn_state = None
            self._current_voice_session_id = session_id
            self._restore_agent_replies()
            self._active_realtime_provider = ""
            self._active_realtime_model = ""
            self._voice_engine_transitioning = True
            session_started_at = time.time()
            wake_keyword = self._last_wake_keyword or "hotkey"
            self._last_wake_keyword = ""
            hangup_reason = _pl.HANGUP_ERROR
            try:
                # Reuse the already-open wake microphone when available. The
                # handoff never owns two native streams at once and retains all
                # frames heard after the visible wake candidate.
                async with self._capture_first_session_input() as input_buffer:
                    # This event is the UI's authoritative "being listened to
                    # now" signal. Capture is already armed before any
                    # subscriber can reveal the listening bar.
                    await self._publish_event(
                        _pl.VoiceSessionStarted(
                            source_layer="speech.pipeline",
                            session_id=session_id,
                            wake_keyword=wake_keyword,
                            language=_pl.DEFAULT_LOCALE,
                        )
                    )
                    # A close accepted while a slow start subscriber runs must
                    # release the borrowed capture without entering a provider.
                    if (
                        self._hangup_event.is_set()
                        or self._external_hangup_pending.is_set()
                    ):
                        hangup_reason = _pl.HANGUP_HOTKEY
                        self._termination_producer = "speech.pipeline._state_loop.startup_hangup"
                        _pl.log.info("Voice session cancelled during startup.")
                    else:
                        _pl.log.info("Voice session accepted.")
                        await self._set_turn_state(_pl.TurnTakingState.LISTENING)
                        # The selected engine confirms readiness with a brief
                        # non-speech cue. Never play the legacy spoken ACK or
                        # pause capture: the opening words are already buffered.
                        hangup_reason = await self._active_session(
                            input_buffer=input_buffer
                        )
            except asyncio.CancelledError:
                hangup_reason = _pl.HANGUP_SHUTDOWN
                self._termination_producer = "speech.pipeline._state_loop.cancelled"
                raise
            except Exception as exc:  # noqa: BLE001
                self._termination_producer = "speech.pipeline._state_loop.error"
                _pl.log.exception("Voice session failed: %s", exc)
            finally:
                cue = getattr(self, "_listening_cue_task", None)
                if cue is not None:
                    await _pl.cancel_and_reap(
                        cue,
                        budget_s=_pl._SESSION_TASK_REAP_BUDGET_S,
                        heartbeat_s=_pl._SESSION_TASK_REAP_HEARTBEAT_S,
                    )
                    self._listening_cue_task = None
                termination = self._termination_snapshot(hangup_reason)
                reopen_after_engine_change = bool(
                    getattr(self, "_reopen_after_engine_change", False)
                )
                engine_change_reason = str(
                    getattr(self, "_engine_change_reason", "")
                )
                self._reopen_after_engine_change = False
                self._engine_change_reason = ""
                self._current_voice_session_id = None
                self._active_realtime_provider = ""
                self._active_realtime_model = ""
                self._voice_engine_transitioning = False
                # PTT is one-shot per hold — disarm before the next session so a
                # stale flag can never reroute a later wake-word session into
                # the raw-recording path.
                # Hanging up ends a coding-agent brief that is still being
                # written, the same way it does on the realtime engine (see
                # ``RealtimeVoiceSession._abandon_spoken_workspace_briefs``):
                # composing takes 10-30 s, and a pane typed into after the user
                # stopped waiting is work they no longer asked for. Idempotent —
                # a realtime call that already dropped its briefs leaves none
                # here. Skipped on an engine reconnect: that session re-arms and
                # the order the user gave is still live.
                if not reopen_after_engine_change:
                    try:
                        from dodaios.agentic_ide.fanout import cancel_spoken_deliveries

                        cancel_spoken_deliveries(
                            reason=f"the call ended ({hangup_reason or 'unknown'})"
                        )
                    except Exception:  # noqa: BLE001 — teardown must never crash
                        _pl.log.debug("Workspace brief teardown failed", exc_info=True)
                # Whatever was spoken after the last utterance (the goodbye, a
                # late announcement) is settled BEFORE the session closes, or
                # the recorder has no open session to file it under.
                spend = getattr(self, "_speech_spend", None)
                if spend is not None:
                    spend.flush()
                await self._publish_event(
                    _pl.VoiceSessionEnded(
                        source_layer=termination["producer"],
                        session_id=session_id,
                        hangup_reason=hangup_reason,
                        duration_s=max(0.0, time.time() - session_started_at),
                        detail=json.dumps(termination, ensure_ascii=True),
                    )
                )
                self._state = _pl.PipelineState.IDLE
                # Return the supervisor to IDLE and hide the active surface.
                await self._set_turn_state(_pl.TurnTakingState.IDLE)
                self._external_hangup_pending.clear()
                if reopen_after_engine_change and self._activation_allowed():
                    # An internal engine reconnect has no response tail to
                    # protect against. Re-arm immediately with the latest
                    # config; a disconnect earcon would leak into the new mic.
                    self._explicit_hard_hangup = False
                    self._wake_lock_until = 0.0
                    self._last_wake_keyword = "engine_switch"
                    self._call_event.set()
                    _pl.log.info(
                        "Voice session re-armed after engine change (%s).",
                        engine_change_reason or "configuration_change",
                    )
                else:
                    # Normal disconnect earcon followed by speaker-echo lock.
                    # Skipped when the dictation lane is what ended this session:
                    # the user's microphone is open a few milliseconds later (or
                    # already is), and a tone played into it is speaker echo the
                    # transcription then has to eat.
                    if not self._dictation_blocks_activation():
                        await self._play_earcon(_pl.DISCONNECT_PCM)
                    lock_s = self._post_hangup_lock_seconds()
                    self._wake_lock_until = time.time() + lock_s
                    _pl.log.info(
                        "Voice session ended; returning to idle (wake lock %.1fs).",
                        lock_s,
                    )

    def _earcons_enabled(self) -> bool:
        """Whether synthesized UI earcons may play.

        Read fresh from the shared config object so the Settings → Behavior
        "Sound effects" master switch applies live (no restart). Defensive
        default ``True`` — a missing field must never silence tones.
        """
        ui = getattr(getattr(self, "_config", None), "ui", None)
        return bool(getattr(ui, "sound_effects", True))

    async def _play_earcon(
        self, pcm: bytes, *, sample_rate: int = _pl.CHIME_SAMPLE_RATE
    ) -> None:
        """Play a synthesized earcon unless the global "Sound effects" switch
        is off. Never raises — an earcon failure must not crash a turn (AD-OE6).
        Does NOT gate the spoken TTS voice, which is not an earcon.
        """
        if not self._earcons_enabled():
            return
        try:
            await self._player.play_pcm(pcm, sample_rate=sample_rate)
        except Exception as exc:  # noqa: BLE001
            _pl.log.debug("Earcon playback skipped (%s).", exc)

    def _start_listening_cue(self) -> None:
        """Confirm native capture once, without blocking or suppressing input."""
        if getattr(self, "_listening_cue_started", False):
            return
        self._listening_cue_started = True
        if (
            not self._earcons_enabled()
            or self.is_speaker_muted
            or getattr(self, "_muted", False)
            or self._hangup_event.is_set()
            # Read defensively: a pipeline assembled without __init__ (the realtime
            # handshake test doubles) has no external-hangup flag yet.
            or (pending := getattr(self, "_external_hangup_pending", None)) is not None
            and pending.is_set()
        ):
            return
        self._listening_cue_task = asyncio.create_task(
            self._play_earcon(_pl.CHIME_PCM), name="voice-listening-cue"
        )

    @asynccontextmanager
    async def _session_input_source(
        self,
        input_buffer: _SessionInputBuffer | None,
        *,
        discard_suppressed: bool = False,
    ) -> AsyncIterator[AsyncIterator[AudioChunk]]:
        """Yield a pre-opened session stream or own a fallback capture."""
        if input_buffer is not None:
            discard_before = (
                lambda: int(getattr(self, "_input_suppressed_until_ns", 0))
            ) if discard_suppressed else None
            yield input_buffer.stream(discard_before_ns=discard_before)
            return
        async with _pl.MicrophoneCapture(
            device=self._input_device,
            max_queue_chunks=_pl.REALTIME_QUEUE_CHUNKS,
            device_priority=self._input_priority,
        ) as mic:
            yield mic.stream()

    async def _active_session(
        self, *, input_buffer: _SessionInputBuffer | None = None
    ) -> str:
        self._last_answer_floor_monotonic = None
        self._voice_engine_transitioning = True
        return await self._active_realtime_session(input_buffer=input_buffer)

    async def _active_realtime_session(
        self, *, input_buffer: _SessionInputBuffer | None = None
    ) -> str:
        """Run one desktop duplex session; returns its hangup reason.

        Imports stay lazy so the optional realtime stack never enters the boot
        critical path. The session owns provider-family fallback and resampling;
        this adapter owns only the local microphone, speaker, and lifecycle.
        Desktop starts half-duplex because PortAudio has no portable acoustic
        echo cancellation. The browser surface provides full duplex with Web
        Audio echo cancellation.
        """
        from dodaios.speech.realtime_session_runner import RealtimeSessionRunner

        return await RealtimeSessionRunner(self, input_buffer).run()
