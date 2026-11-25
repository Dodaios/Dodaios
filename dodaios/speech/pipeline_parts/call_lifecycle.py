"""Voice session requests, engine mode and hangup.

Moved out of ``pipeline.py`` without a behaviour change. Module-level names
of the pipeline are read through ``_pl`` at call time so the pipeline module
stays the one place that owns and patches them.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from dodaios.speech import pipeline as _pl

if TYPE_CHECKING:
    from typing import Any


class CallLifecycleMixin:
    """Voice session requests, engine mode and hangup."""

    def request_voice_session(
        self, *, seed_messages: list[tuple[str, str]] | None = None
    ) -> bool:
        """``start_voice_session`` for a caller that only needs armed / not armed."""
        return not self.start_voice_session(seed_messages=seed_messages)

    def _activation_state_refusal(self) -> str:
        """Which half of ``_activation_state_allows`` said no, as a refusal code."""
        if getattr(self, "_muted", False):
            return _pl.start_refusal.MUTED
        if self._dictation_blocks_activation():
            return _pl.start_refusal.DICTATION
        return _pl.start_refusal.MICROPHONE_IN_USE

    def start_voice_session(
        self, *, seed_messages: list[tuple[str, str]] | None = None
    ) -> str:
        """Arm a wake-style voice session from outside the audio path.

        The "Speak in this conversation" button (``POST /api/chats/{kind}/
        {cid}/speak``) calls this to start a session that already remembers a
        past conversation — functionally "Hey Jarvis", but with seeded context.

        Web routes run on the pipeline loop, while the native Jarvis Bar calls
        this from its dedicated Tk thread. The final arming edge is therefore
        marshalled through the owner loop when necessary; setting an
        ``asyncio.Event`` directly from Tk can leave the selector asleep until
        unrelated I/O happens to wake it.

        Returns ``""`` when the session was armed, otherwise the one reason it
        was not, from ``dodaios.speech.start_refusal`` (a no-op: a session is
        already active or arming, voice is muted, a dictation or a browser call
        holds the microphone, or the microphone is not granted). The caller
        shows that reason; it must never guess one. The brain is seeded ONLY
        when we actually arm, so a rejected request never pollutes an unrelated
        in-flight session's history. Like PTT (an explicit user action with no
        audio-echo path), the post-hangup wake-lock is intentionally not
        consulted here.
        """
        if self._state != _pl.PipelineState.IDLE:
            _pl.log.info("request_voice_session ignored: pipeline not idle.")
            return _pl.start_refusal.BUSY
        if not self._activation_state_allows():
            _pl.log.info(
                "request_voice_session ignored: %s",
                self._activation_block_reason(explicit=True, include_permission=False)
                or "another call owns the microphone",
            )
            return self._activation_state_refusal()
        # Gesture entry: the speak button / bar click may ask macOS for the
        # microphone. A first request raises the dialog and returns False (the UI
        # says "allowed - press again"); the session is never armed retroactively.
        # A denied microphone reaches ``ensure`` too (toast, not silence).
        refusal = self._ensure_microphone("voice")
        if refusal is not None:
            _pl.log.info("request_voice_session ignored: %s", refusal)
            return _pl.start_refusal.MICROPHONE
        if seed_messages:
            brain = getattr(self, "_brain", None)
            seed = getattr(brain, "seed_history", None)
            if callable(seed):
                try:
                    seed(seed_messages)
                except Exception:  # noqa: BLE001 — seeding must never block arming
                    _pl.log.warning(
                        "request_voice_session: brain seed failed", exc_info=True
                    )
        self._last_wake_keyword = "chat_resume"
        _pl.log.info(
            "Voice session requested (wake-style, seeded=%d turns).",
            len(seed_messages or []),
        )
        self._explicit_call_pending = True
        return "" if self._arm_call_event() else _pl.start_refusal.UNAVAILABLE

    def request_voice_hangup(self) -> bool:
        """Hang up the voice channel from outside the audio path.

        The voice orb's click and ``jarvis api voice hangup`` land here — the
        same absolute-kill contract as the hangup hotkey (2026-05-20: no matter
        what is playing or queued, the voice channel goes silent now). Safe to
        call while idle; answers ``False`` instead of raising so a UI click can
        report honestly rather than 500.
        """
        try:
            self._trigger_voice_hangup()
            return True
        except Exception:  # noqa: BLE001 — a failed hangup must report, never raise
            _pl.log.warning("request_voice_hangup failed", exc_info=True)
            return False

    def _arm_call_event(self) -> bool:
        """Set the call edge on its owning asyncio loop.

        Native overlay callbacks run on a Tk thread. ``asyncio.Event.set`` may
        flip the flag from that thread without waking the loop's selector, so
        the state task resumes only after an unrelated timer or socket event.
        ``call_soon_threadsafe`` provides both the wakeup and the memory edge.
        Same-loop callers retain the direct, allocation-free path.
        """
        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if owner is not None and owner.is_running() and current is not owner:
            try:
                owner.call_soon_threadsafe(self._call_event.set)
                return True
            except RuntimeError:
                _pl.log.warning("Voice session request failed: owner loop is closed.")
                return False
        self._call_event.set()
        return True

    def voice_engine_status(self) -> dict[str, Any]:
        """Snapshot the voice call state for the UI.

        ``active_session_provider``/``model`` name what the open call really
        uses; they stay empty until its provider confirmed the session.
        """
        session_id = getattr(self, "_current_voice_session_id", None)
        return {
            "session_active": bool(session_id),
            "session_id": str(session_id or ""),
            "active_session_provider": getattr(self, "_active_realtime_provider", ""),
            "active_session_model": getattr(self, "_active_realtime_model", ""),
            "transitioning": bool(
                getattr(self, "_voice_engine_transitioning", False)
                or getattr(self, "_reopen_after_engine_change", False)
            ),
            # Why the LAST realtime start attempt failed (None once a session
            # is up): {provider, message, at}. The surfaces render it when a
            # connecting window closes without a session instead of falling
            # silently back to "idle".
            "last_start_error": getattr(self, "_last_realtime_start_error", None),
        }

    def reconnect_realtime_session(self, *, reason: str) -> bool:
        """Reconnect an active realtime call after provider/model changes."""
        if self._state == _pl.PipelineState.IDLE:
            return False
        return self._schedule_engine_reopen(reason)

    def _schedule_engine_reopen(self, reason: str) -> bool:
        if self._state == _pl.PipelineState.IDLE:
            return False
        self._reopen_after_engine_change = True
        self._engine_change_reason = str(reason or "configuration_change")
        self._voice_engine_transitioning = True
        _pl.log.info(
            "Voice engine changed during an active session; reconnecting (%s).",
            self._engine_change_reason,
        )
        self._trigger_voice_hangup()
        return True

    def _post_hangup_lock_seconds(self) -> float:
        """Wake-lock duration for the session that just ended (one-shot).

        SHORT (`_explicit_hangup_lock_s`) after a user HARD hangup — the
        JarvisBar close / hotkey / "auflegen" stopped the player, so there is no
        TTS tail to echo and the long lock would only swallow the user's very
        next "Hey <wake>". Otherwise the FULL `_post_hangup_lock_s` guards the
        speaker tail of a natural end / farewell. Consumes the hard-hangup flag
        so it applies to exactly one session end.
        """
        hard = self._explicit_hard_hangup
        self._explicit_hard_hangup = False
        return self._explicit_hangup_lock_s if hard else self._post_hangup_lock_s

    def request_hangup(self) -> None:
        """End the live voice session from outside the audio path.

        The jarvis-bar's hover-to-close cross calls this (and any future UI
        close affordance). The bar runs on a dedicated Tk thread, while the
        hangup event and its waiters belong to the pipeline's asyncio loop.
        Marshal the complete hard-stop chokepoint onto that owning loop; calling
        ``asyncio.Event.set()`` directly from Tk is unsupported and can fail to
        wake the waiter until unrelated I/O arrives. Repeated clicks during one
        teardown are idempotent. A no-op request while idle is cleared when the
        next session starts.
        """
        pending = getattr(self, "_external_hangup_pending", None)
        handoff_close = getattr(self, "_wake_handoff_hangup_pending", None)
        handoff_ready = bool(
            getattr(self, "_state", _pl.PipelineState.IDLE) is _pl.PipelineState.IDLE
            and getattr(self, "_wake_handoff_ready", None)
            and self._wake_handoff_ready.is_set()
        )
        candidate_active = bool(
            getattr(self, "_state", _pl.PipelineState.IDLE) is _pl.PipelineState.IDLE
            and getattr(self, "_wake_preroll_active", False)
        )
        if handoff_ready and handoff_close is not None:
            # Set synchronously on the caller thread. The owner-loop callback
            # can otherwise lose a race with the already-armed state task.
            handoff_close.set()
        if (
            pending is not None
            and pending.is_set()
            and not handoff_ready
            and not candidate_active
        ):
            # A second stop gesture while the first is still being honoured
            # is idempotent — unless the first one is OLD. A hangup that has
            # been "pending" for many seconds with the session still active
            # is a teardown that never finished (BUG-185: a swallowed cancel
            # left the pipeline stuck in its own finally for an afternoon).
            # That must not vanish at debug level: say it, and let the
            # request through so the chokepoint runs again.
            requested_at = float(getattr(self, "_hangup_requested_at", 0.0) or 0.0)
            age = time.monotonic() - requested_at if requested_at else 0.0
            if age < _pl._HANGUP_LATCH_STALE_S:
                _pl.log.debug("request_hangup ignored: external hangup already pending")
                return
            _pl.log.warning(
                "request_hangup: a hangup has been pending for %.1fs and the "
                "voice session is still active — the teardown did not finish; "
                "delivering the stop again (BUG-185).",
                age,
            )
        if pending is not None:
            pending.set()
        self._hangup_requested_at = time.monotonic()
        _pl.log.info("📵 request_hangup — closing the voice session")

        def _dispatch() -> None:
            try:
                if (
                    getattr(self, "_state", _pl.PipelineState.IDLE)
                    is _pl.PipelineState.IDLE
                    and getattr(self, "_wake_handoff_ready", None)
                    and self._wake_handoff_ready.is_set()
                    and handoff_close is not None
                ):
                    handoff_close.set()
                if (
                    getattr(self, "_state", _pl.PipelineState.IDLE)
                    is _pl.PipelineState.IDLE
                    and getattr(self, "_wake_preroll_active", False)
                ):
                    # The bar can be visible during wake verification before a
                    # real session exists. Its X cancels that candidate; it
                    # must not be reinterpreted as a new voice-session click.
                    cancel_event = getattr(self, "_wake_cancel_event", None)
                    if cancel_event is not None:
                        cancel_event.set()
                    if pending is not None:
                        pending.clear()
                    return
                self._trigger_voice_hangup()
            except Exception:
                # A failed dispatch must be retryable; successful requests stay
                # latched until the authoritative session teardown reaches IDLE.
                if pending is not None:
                    pending.clear()
                raise

        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if owner is not None and owner.is_running() and current is not owner:
            try:
                owner.call_soon_threadsafe(_dispatch)
                return
            except RuntimeError:
                # The loop closed between is_running() and scheduling. The
                # synchronous fallback still stops audio/CU and is harmless
                # when no asyncio waiter remains alive.
                _pl.log.debug("request_hangup: owner loop closed during dispatch")
        _dispatch()

    def is_session_active(self) -> bool:
        """Ground truth for "a live voice session is in progress right now".

        The jarvis-bar uses this to decide whether a close-X click is a real
        hang-up or a useless no-op. The bar's visual mode can get stuck in the
        active "listen" look when a wake popped it but the post-hangup wake-lock
        cooldown rejected the session — no ``VoiceSessionStarted`` is published
        and no ``IDLE`` state follows, so nothing resets the bar (freeze
        forensic 2026-06-28).

        ``_state`` becomes ACTIVE before ``VoiceSessionStarted`` is published,
        while ``_turn_state`` does not leave IDLE until every start subscriber
        returns. A slow subscriber therefore creates a real session-start window
        where checking only the turn-state misclassifies the visible X as an
        idle-body click and calls ``request_voice_session()`` instead of hanging
        up. Treat either lifecycle signal as active so the close control remains
        valid throughout startup, the live turn, and teardown. A visible wake
        candidate also counts as active for this control only: its close action
        routes to ``request_hangup()``, which retracts the pending candidate
        instead of accidentally starting a session.
        """
        return (
            getattr(self, "_state", _pl.PipelineState.IDLE) is not _pl.PipelineState.IDLE
            or
            getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
            is not _pl.TurnTakingState.IDLE
            or bool(getattr(self, "_wake_preroll_active", False))
            or bool(
                getattr(self, "_wake_handoff_ready", None)
                and self._wake_handoff_ready.is_set()
            )
        )

    def _trigger_voice_hangup(self, *, stop_player: bool = True) -> None:
        """Hard-stop the voice channel — the single hangup chokepoint.

        User intent (2026-05-20): "auflegen" is an absolute kill switch.
        No matter what Jarvis is currently saying, announcing, or queueing,
        a hangup must silence the voice channel immediately. Background
        Jarvis-Agent missions keep running (they live in their own subprocess
        + Job Object); only their *voice readback* is suppressed via the
        ``_hangup_event`` gate on the bus-driven announcement handlers.

        ``stop_player=False`` is used when the brain itself emitted the
        farewell ("Goodbye.") — we let that final utterance play.
        """
        confirmation = getattr(self, "_hangup_confirmation", None)
        if confirmation is not None:
            confirmation.reset()

        if not getattr(self, "_termination_producer", ""):
            self._termination_producer = "speech.pipeline._trigger_voice_hangup"
        if stop_player:
            try:
                self._player.stop()
            except Exception as exc:  # noqa: BLE001
                _pl.log.warning("Stopping the player during hangup failed: %s", exc)
            # Player stopped => no TTS tail => the next session end uses the
            # SHORT wake-lock so the user can re-wake immediately. A farewell
            # hangup (stop_player=False) keeps the full speaker-tail guard.
            self._explicit_hard_hangup = True
        self._hangup_event.set()
        # BUG-CU-HANGUP (2026-05-28): "auflegen" must also STOP a running
        # Computer-Use mission immediately — otherwise Jarvis keeps clicking
        # the screen in the background after the user told it to stop. This is
        # CU-scoped (cancels only the active CU token), so Jarvis-Agent
        # background missions are unaffected (their voice readback is muted via
        # the _hangup_event gate, matching the documented hangup contract).
        try:
            from dodaios.harness.computer_use_context import cancel_active_cu
            if cancel_active_cu("voice_hangup"):
                _pl.log.info("Voice-Hangup: active Computer-Use mission cancelled.")
        except Exception:  # noqa: BLE001 — hangup must never crash
            _pl.log.debug("CU cancel-on-hangup failed (non-fatal)", exc_info=True)
        # The X must also stop a CHAT turn, not only a voice turn. A chat turn
        # runs on a separate dispatcher (``desktop_app._on_user_message``) that
        # never observes ``_hangup_event`` — so before this it kept thinking
        # through every X press (live bug 2026-06-19: ~27 ignored presses). The
        # cancel is edge-triggered and loop-safe (this may run on the Tk thread).
        try:
            from dodaios.core.runtime_refs import cancel_active_chat_turn
            if cancel_active_chat_turn():
                _pl.log.info("Voice-Hangup: active chat turn cancelled.")
        except Exception:  # noqa: BLE001 — hangup must never crash
            _pl.log.debug("chat-turn cancel-on-hangup failed (non-fatal)", exc_info=True)
