"""Probe STT selection, vision toggles, permission and activation gates, mute.

Moved out of ``pipeline.py`` without a behaviour change. Module-level names
of the pipeline are read through ``_pl`` at call time so the pipeline module
stays the one place that owns and patches them.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from dodaios.speech import pipeline as _pl

if TYPE_CHECKING:
    from typing import Any

    from dodaios.core.events import (
        DictationPromptModePauseToggleRequested,
        PermissionResolved,
        VoiceMuteToggleRequested,
    )


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class VadActivationMixin(_HostBase):
    """Probe STT selection, vision toggles, permission and activation gates, mute."""

    def _select_probe_stt(self, utterance: Any) -> Any:
        """Use a separate wake engine or a concurrency-safe final provider."""
        wake = getattr(self, "_stt", None)
        candidate = wake if wake is not None else utterance
        if candidate is utterance and not getattr(
            candidate, "supports_concurrent_transcription", True
        ):
            # Cancelling an async preview does not stop its native worker.
            # A local final decode must never compete with that same engine.
            return None
        from dodaios.speech.stt_dictionary import wrap_stt_with_dictionary

        return wrap_stt_with_dictionary(candidate)

    def _vision_cfg(self) -> Any:
        """Liefert RouterVisionConfig oder None (tolerant zu fehlender Config)."""
        cfg = self._config
        if cfg is None:
            return None
        return getattr(getattr(getattr(cfg, "brain", None), "router", None), "vision", None)

    def _maybe_toggle_vision_on_state(self, new_state: str) -> None:
        """Pausiert/resumed den VisionContextProvider anhand Pipeline-State.

        No-op wenn kein Provider injected oder pause_on_idle=False.
        """
        if self._vision_provider is None:
            return
        vcfg = self._vision_cfg()
        pause_on_idle = getattr(vcfg, "pause_on_idle", True) if vcfg is not None else True
        if not pause_on_idle:
            return
        if new_state == "IDLE":
            try:
                self._vision_provider.pause()
            except Exception as exc:  # noqa: BLE001
                _pl.log.warning("Vision-pause() bei IDLE fehlgeschlagen: %s", exc)
        elif new_state in ("LISTENING", "THINKING", "SPEAKING"):
            try:
                self._vision_provider.resume()
            except Exception as exc:  # noqa: BLE001
                _pl.log.warning("Vision-resume() bei %s fehlgeschlagen: %s", new_state, exc)

    def _background_capture_allowed(self) -> bool:
        """Silent gate for BACKGROUND capture (wake word, barge-in): a live grant only.

        Never asks the OS and never opens the device. An undecided microphone is
        closed here because nothing the user did is waiting on it: the wake loop
        parks and a gesture elsewhere asks. Does not apply Jarvis mute.
        """
        gate = getattr(self, "_activation_gate", None)
        if gate is None:
            return True
        try:
            return bool(gate())
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("Voice capture permission gate failed closed: %s", exc)
            return False

    def _user_capture_allowed(self) -> bool:
        """Silent gate for USER-started capture (push-to-talk, voice session, dictation).

        True unless the microphone is denied, restricted or unavailable: an
        undecided microphone is usable because the gesture itself asks (see
        ``_ensure_microphone``). Never asks and never opens the device.
        """
        gate = getattr(self, "_user_activation_gate", None)
        if gate is None:
            return True
        try:
            return bool(gate())
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("Voice user-capture permission gate failed closed: %s", exc)
            return False

    def _permission_service(self) -> Any:
        """The injected ``PermissionGate``, else the process service (resolved per call)."""
        gate = getattr(self, "_permission_gate", None)
        if gate is not None:
            return gate
        from dodaios.platform.permission_service import get_permission_service

        return get_permission_service()

    def _ensure_microphone(self, feature: str) -> str | None:
        """THE ask of a voice gesture: ``ensure(MICROPHONE, wait_s=0)``.

        Returns ``None`` when the microphone is granted (or this is not a TCC
        platform), else a finished English sentence saying why not. ``wait_s=0``
        is the loop-safe form: a first press may make macOS show its dialog and
        returns PENDING at once, so the press that raised the dialog is NOT
        started retroactively (the UI says "allowed - press again"). The service
        publishes the ``PermissionNeeded`` episode itself, a denial included.
        Never raises; a failed read refuses.
        """
        try:
            result = self._permission_service().ensure(
                "microphone", feature=feature, interactive=True, wait_s=0.0
            )
        except Exception:  # noqa: BLE001 - an unreadable permission must not start the capture
            _pl.log.warning(
                "The microphone permission check for %s failed.", feature, exc_info=True
            )
            return _pl._MICROPHONE_REFUSED_SENTENCE
        if result.granted:
            return None
        return str(result.user_detail or "") or _pl._MICROPHONE_REFUSED_SENTENCE

    async def _on_permission_resolved(self, event: PermissionResolved) -> None:
        """A microphone grant wakes a wake loop that is parked on the permission.

        Runs on the loop (bus dispatch), so setting the asyncio event is safe. A
        resolution while the loop is not parked changes nothing: a wake capture
        that is already running must not be torn down by a dictation's grant.
        """
        if not event.granted or "microphone" not in event.permissions:
            return
        if getattr(self, "_wake_parked_on_permission", False):
            self._wake_reload_event.set()

    def _dictation_blocks_activation(self) -> bool:
        """True while a running dictation must keep the wake word silent.

        The maintainer's contract: a dictation turn owns the microphone, so the
        words being dictated must never trip the wake word (and two native input
        streams must never race for the same device — BUG-014 / AP-24).

        This is a STATE gate, not the content gate AP-27 forbids: it asks
        whether an application task is alive, with zero reference to audio or to
        any transcript, exactly like the three gates it sits beside
        (``_wake_lock_until``, mute, ``_state != IDLE``). It changes WHEN wake is
        listened to, never HOW a candidate is judged.

        Two independent things must BOTH hold for wake to stay blocked:

        1. A dictation task is alive — either the recording itself
           (``_dictation_task``) or the handover that is ending a voice
           conversation to get the microphone for one
           (``_dictation_handover_task``). Derived from ``task.done()``, never a
           bare bool somebody has to remember to clear — a crashed, cancelled or
           returned task is ``done()``, so the block lifts by itself.
        2. The watchdog deadline has not passed. ``_dictation_wake_block_until``
           is a timestamp set at start, mirroring ``_wake_lock_until``. A task
           that somehow hangs forever therefore still cannot deafen the wake
           word beyond it.

        The handover half matters as much as the recording half: ending the
        conversation returns the pipeline to IDLE with the wake loop free to
        re-arm, and a wake word firing in that gap would take the microphone
        straight back from the user who just pressed the dictation key.

        All defaults fail OPEN (no task → False, missing deadline → 0.0 →
        False), because the failure this guards against is BUG-037: permanently
        deaf with no visible cause and only a restart to fix.
        """
        task = getattr(self, "_dictation_task", None)
        if task is None or task.done():
            task = getattr(self, "_dictation_handover_task", None)
        if task is None or task.done():
            return False
        return time.time() < float(getattr(self, "_dictation_wake_block_until", 0.0))

    def _activation_state_allows(self) -> bool:
        """The non-permission half of the gate: mute, a running dictation, mic ownership.

        Split out so a gesture entry point can refuse for these reasons BEFORE it
        asks the OS for anything (a muted press must not raise a macOS dialog), and
        so the wake loop can tell "waiting on the permission" from "waiting on the
        state" and park only for the first.
        """
        if getattr(self, "_muted", False):
            return False
        if self._dictation_blocks_activation():
            return False
        from dodaios.live.runtime import owns_microphone

        return not owns_microphone(
            except_session_id=getattr(self, "_current_voice_session_id", None)
        )

    def _activation_block_reason(
        self, *, explicit: bool = False, include_permission: bool = True
    ) -> str:
        """The honest English reason ``_activation_allowed`` is saying no.

        One source for every log line that reports the closed gate. It exists
        because those lines used to hardcode two guesses ("muted" /
        "window not visible?"), and the wrong guess once misled a live freeze
        diagnosis. Returns an empty string when the gate is open. ``explicit``
        selects the user-gesture permission predicate, as in ``_activation_allowed``.
        ``include_permission=False`` names only the state half (a gesture entry
        point that refused on the state alone and must not report the microphone).
        """
        if getattr(self, "_muted", False):
            return "voice is muted"
        if self._dictation_blocks_activation():
            return "a dictation is running"
        if not include_permission:
            return ""
        permitted = self._user_capture_allowed() if explicit else self._background_capture_allowed()
        if not permitted:
            return (
                "microphone access is not granted"
                if not explicit
                else "microphone access is denied or unavailable"
            )
        return ""

    def _activation_allowed(self) -> bool:
        """True when external UI/lifecycle state permits BACKGROUND voice activation.

        While muted (mascot doubleClick → ``_muted=True``) we always
        return False so the wake-loop ignores every detection. The loop
        keeps spinning; unmuting is one bool flip away.

        A running dictation closes the same gate (``_dictation_blocks_activation``)
        — one edit reaches all three wake gates (loop entry, pre-emit, state
        loop) plus the push-to-talk and ``request_voice_session`` entry points,
        because the state half of this predicate is shared with all of them
        (``_activation_state_allows``).

        The permission half is ``_background_capture_allowed``: a live microphone
        GRANT. A deliberate user action (the call key, push-to-talk, the speak
        button) uses ``_gesture_activation_allowed`` instead, which only needs the
        microphone not to be refused, because the gesture is what asks the OS.
        Neither ever asks from here.

        ``getattr`` defaults to False for pipelines constructed via
        ``__new__`` (used by privacy/vision unit tests that bypass
        ``__init__``) — those instances are never muted by definition.

        NB: ``dictation_available`` / ``start_dictation`` deliberately do NOT
        consult this predicate. Routing them through here would make a
        dictation forbid its own successor.
        """
        return self._activation_state_allows() and self._background_capture_allowed()

    def _gesture_activation_allowed(self) -> bool:
        """``_activation_allowed`` for a deliberate user action (key, button, bar click).

        Same state half (mute, a running dictation, mic ownership); the permission
        half is ``_user_capture_allowed``: true unless the microphone is denied,
        restricted or unavailable. The wake word is NOT such an action and never
        passes through here.
        """
        return self._activation_state_allows() and self._user_capture_allowed()

    @property
    def is_muted(self) -> bool:
        """Snapshot of the global voice mute flag.

        Public so tests and the REST surface can read the live value
        without going through the bus.
        """
        return self._muted

    async def toggle_mute(self, source: str = "") -> bool:
        """Flip the microphone mute for the assistant and return the new value.

        The REST twin of publishing ``VoiceMuteToggleRequested``: the same
        handler flips it and broadcasts ``VoiceMuteChanged``, so a running
        call (``live/session.py``) and every other mirror follow.
        """
        from dodaios.core.events import VoiceMuteToggleRequested

        await self._on_mute_toggle_requested(VoiceMuteToggleRequested(source=source))
        return self._muted

    async def _on_mute_toggle_requested(
        self, event: VoiceMuteToggleRequested
    ) -> None:
        """Flip the mute flag and broadcast the authoritative state.

        Idempotent toggle: callers do not have to know the current state.
        We log the change at INFO so the live log carries an audit trail.
        """
        new_value = not self._muted
        self._muted = new_value
        _pl.log.info(
            "🔇 Voice mute %s (source=%s)",
            "ENABLED" if new_value else "disabled",
            event.source or "unknown",
        )
        # Mute is INPUT-ONLY (maintainer intent 2026-06-29: "mute my mic FOR
        # Jarvis, do NOT mute Jarvis — other things keep working"). We deliberately
        # do NOT call self._player.stop() here: that ran Pa_AbortStream
        # (stream.abort) mid-TTS-write, which (a) contradicted the input-only
        # intent and (b) wedged the shared WASAPI device — the next wake-mic then
        # opened "successfully" but delivered only dead/silent frames (no
        # rolling-whisper, no 3 s Mic-Stall fire), so "Hey <wake>" silently
        # stopped working after a mute-during-speech + hangup. Jarvis finishes the
        # current sentence; new _speak() calls are still suppressed while muted,
        # and the user's input frames are dropped at our boundary — the OS mic is
        # untouched. Forensic: data/jarvis_desktop.log 2026-06-29 14:09–14:12.
        if self._bus is None:
            return
        try:
            await self._bus.publish(
                _pl.VoiceMuteChanged(muted=new_value, source=event.source)
            )
        except Exception:  # noqa: BLE001
            _pl.log.exception("VoiceMuteChanged publish failed")

    async def _on_prompt_mode_pause_toggle_requested(
        self, event: DictationPromptModePauseToggleRequested
    ) -> None:
        """Pause or resume Prompt Mode and broadcast the new state.

        Idempotent like the mute toggle: the caller does not know the current
        state. Deliberately NOT a settings write — the value in jarvis.toml is
        left alone, so the settings card keeps showing the switch on and one
        more click on the bar brings the rewriting back.
        """
        from dodaios.dictation.prompt_mode_switch import toggle_prompt_mode_pause

        await toggle_prompt_mode_pause(
            cfg=getattr(self, "_dictation_cfg", None),
            bus=self._bus,
            source=event.source or "unknown",
        )
