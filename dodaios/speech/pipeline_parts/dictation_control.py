"""Dictation start/stop, microphone hand-over and recognizer resolution.

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
    import asyncio
    from typing import Any


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class DictationControlMixin(_HostBase):
    """Dictation start/stop, microphone hand-over and recognizer resolution."""

    # ------------------------------------------------------------------
    # Chat mic-dictation (transcribe-only → chat input, never the brain)
    # ------------------------------------------------------------------

    def dictation_available(self) -> bool:
        """True if the server can run mic-dictation (a mic + an STT exist).

        Lets the UI hide the mic button on a headless host with no capture
        device (cloud-first: a missing capability is a clean no-op, AD-OE6).

        The microphone PERMISSION is deliberately not a term here: the button
        must be visible on a fresh Mac, where the first press is what asks.
        ``start_dictation`` refuses honestly when the permission is missing.
        """
        return self._utterance_stt is not None and self._input_device != "none"

    def dictation_engine_status(self) -> dict[str, Any]:
        """Which recognizer reads the next dictation, for the UI. Never raises.

        ``provider`` / ``model`` name the engine that answers the next press
        and ``local`` says whether it runs on this computer; ``fallback`` is
        the stand-in behind it. ``detail`` is one sentence for the person
        when recognition is not where the settings suggest: no key saved, or
        a slow on-device model in use while a faster one could be downloaded.
        """
        try:
            return dict(self._dictation_resolution().status())
        except Exception as exc:  # noqa: BLE001 — a status probe never breaks the view
            _pl.log.debug("dictation engine status unavailable (%s)", exc)
            return {
                "local": False,
                "provider": "",
                "model": "",
                "fallback": "",
                "detail": "",
            }

    def start_dictation(self, *, target: str = "chat", source: str = "api") -> bool:
        """Begin a transcribe-only dictation session (idempotent-safe).

        ``source`` names the door the request came through — ``hold_key``,
        ``toggle_key``, ``ws``, ``rest`` or the default ``api`` — purely so the
        start line in the log says so and the hold-key watchdog knows whether a
        release edge is owed (BUG-191: a recording that never ended could not
        be traced to its trigger, because the log never said which one it was).

        ``target`` decides where the finished transcript goes:

        * ``"chat"`` — publish the transcript only. This is the chat composer's
          mic button: the text lands in the app's own input box.
        * ``"insert"`` — additionally paste it into the focused text field of
          whatever application is in front. This is dictation mode proper.

        Returns ``False`` when it cannot start — no microphone, no STT, or a
        dictation already running. A live voice conversation is NOT one of
        those cases any more: see the handover below.

        **The dictation key wins.** Pressing it is a deliberate, explicit user
        action; a conversation left open in the background is not. On this
        machine's configuration a session never ends by itself (idle auto-hangup
        is off by maintainer mandate and the hangup key is unbound), so a single
        wake word at any point in the day used to make EVERY later dictation
        press refuse — silently — until the app was restarted. So a press now
        hangs the conversation up through the ordinary hangup chokepoint (the
        same one the bar's close-X uses), waits for the microphone to actually
        come back, and then records. This is the maintainer's own kill-switch
        doctrine: an explicit stop gesture beats whatever Jarvis is in the
        middle of, INCLUDING a half-spoken answer, and the answer is cut off the
        clean way — the player stops, the session unwinds through its normal
        teardown, and a bounded wait means a wedged teardown refuses honestly
        instead of hanging or deafening the key forever.

        **Every refusal is announced**, not just logged: each one publishes a
        ``DictationRefused`` carrying a stable reason token and a finished
        English sentence. Before that, a refused shortcut produced a
        ``log.info`` in a file the desktop app cannot display, so
        the key simply did nothing and the user had no way to learn why. The
        boolean return is unchanged, so every existing caller (hotkey edge, WS
        handler, REST route) keeps working; ``True`` from the handover path
        means "accepted", and its failure arrives as ``DictationRefused``.

        This NEVER routes to the brain: it spawns ``_dictation_session`` which
        only publishes ``DictationStarted`` / ``DictationTranscript`` /
        ``DictationTranscribing`` / ``DictationCompleted`` events.
        """
        if self._utterance_stt is None:
            self._refuse_dictation(
                "no_stt",
                "No speech-to-text provider is configured, so there is nothing "
                "to transcribe with. Add a provider key in Settings.",
            )
            return False
        if self.dictation_active():
            self._refuse_dictation(
                "already_running",
                "A dictation is already recording.",
            )
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._refuse_dictation(
                "pipeline_not_running",
                "The voice pipeline is not running, so dictation cannot start.",
            )
            return False
        # The press is the gesture that may ask macOS for the microphone. A first
        # press of an undecided microphone raises the OS dialog and refuses THIS
        # press ("microphone_unavailable" + the PermissionNeeded episode the
        # service publishes); nothing starts retroactively once it is answered, the
        # UI says "allowed - press again". The refusal sentence comes from the
        # permission layer's fixed templates, never from exception text.
        refusal = self._ensure_microphone("dictation")
        if refusal is None and not self._user_capture_allowed():
            refusal = _pl._MICROPHONE_REFUSED_SENTENCE
        if refusal is not None:
            self._refuse_dictation("microphone_unavailable", refusal)
            return False
        if self._live_call_owns_microphone():
            # A live call keeps running: its input is held, not hung up.
            return self._commit_dictation(
                loop, target=target, source=source, beside_call=True
            )
        if self._voice_session_holds_microphone():
            return self._begin_dictation_handover(loop, target=target, source=source)
        return self._commit_dictation(loop, target=target, source=source)

    def _live_call_owns_microphone(self) -> bool:
        """True while a live realtime call captures the microphone in the WebView.

        Such a call owns its own capture (getUserMedia, with the browser's echo
        cancellation), so a dictation does not have to take the device away
        from it. Instead the dictation records through its own capture and the
        call's input is HELD until the text is delivered (``VoiceInputHeld``):
        the conversation stays open and the dictated words never become a turn.
        """
        try:
            from dodaios.live.runtime import owns_microphone
        except Exception:  # noqa: BLE001 — no live stack means no live call
            _pl.log.debug("live call registry unavailable", exc_info=True)
            return False
        return owns_microphone()

    @property
    def is_voice_input_held(self) -> bool:
        """Whether a dictation currently holds a live call's input back.

        Read by a call that starts DURING such a dictation, so it adopts the
        hold instead of hearing the dictated words.
        """
        return bool(getattr(self, "_voice_input_held", False))

    def _set_voice_input_held(self, held: bool) -> None:
        """Hold or release a live call's input and tell the call. Never raises."""
        if bool(getattr(self, "_voice_input_held", False)) == held:
            return
        self._voice_input_held = held
        _pl.log.info(
            "Live call input %s for the dictation.",
            "held" if held else "released",
        )
        self._publish_event_soon(_pl.VoiceInputHeld(held=held, reason="dictation"))

    def _on_beside_call_dictation_done(self, _task: asyncio.Task[None]) -> None:
        """Give the call its voice back once the dictation has fully ended.

        A done-callback rather than a ``finally``: it runs for every end of the
        task, including one cancelled before its first step, so the call can
        never be left deaf. The task ends only after the text was delivered,
        which is the moment the user may talk to the call again.
        """
        try:
            self._dictation_beside_call = False
            self._set_voice_input_held(False)
        except Exception:  # noqa: BLE001 — a release must never become a crash
            _pl.log.warning("Releasing the live call input failed", exc_info=True)

    def _voice_session_holds_microphone(self) -> bool:
        """True while the VOICE lane owns the one input device.

        The dictation lane must then not open a stream of its own (AP-24 /
        the BUG-014 family). ``getattr`` defaults keep pipelines built via
        ``__new__`` working.
        """
        return getattr(self, "_state", _pl.PipelineState.IDLE) is not _pl.PipelineState.IDLE

    def _begin_dictation_handover(
        self, loop: asyncio.AbstractEventLoop, *, target: str, source: str = "api"
    ) -> bool:
        """Take the microphone from a live voice conversation, then dictate.

        Returns ``True`` when the press is ACCEPTED: the conversation has been
        told to hang up and the dictation starts a moment later, once the device
        has actually been released. That ordering is the whole point, because
        two native input streams on one device is the AP-24 class of bug.
        ``False`` means the hangup itself could not even be requested, which is
        refused out loud like any other dead end.

        The wake gate is closed here rather than at the commit point: ending the
        conversation returns the pipeline to IDLE with the wake loop free to
        re-arm, and a wake word firing inside that gap would take the microphone
        straight back from the user who just pressed the key. The deadline
        covers only the handover — ``_commit_dictation`` re-arms it for the
        recording — so a handover that dies without running its own teardown
        still cannot deafen wake for more than this window (BUG-037).
        """
        self._dictation_wake_block_until = (
            time.time() + _pl._DICTATION_HANDOVER_TIMEOUT_S + 1.0
        )
        try:
            # Hang up SYNCHRONOUSLY, on the press itself — never from inside the
            # waiting task. A task cancelled before its first step (a
            # press-and-release a few milliseconds apart, which is a normal
            # human gesture) never executes a single line of its body, so a
            # hangup scheduled in there would simply not happen and the key
            # would be back to doing nothing at all.
            #
            # This is the ordinary hangup entry point — the same one the bar's
            # close-X calls. It stops the player immediately, cancels a running
            # Computer-Use mission and a live chat turn, and lets the session
            # unwind through its own teardown. Deliberately NOT a second
            # teardown of our own: one chokepoint, one contract.
            self.request_hangup()
        except Exception as exc:  # noqa: BLE001 — an honest refusal, not a crash
            _pl.log.warning("Dictation handover could not hang up the session: %s", exc)
            self._refuse_dictation(
                "handover_failed",
                "The running voice conversation could not be ended, so the "
                "dictation did not start. Close the voice bar and press the "
                "key again.",
            )
            return False
        task = loop.create_task(
            self._dictate_when_the_microphone_is_free(loop, target=target, source=source),
            name="dictation-handover",
        )
        # The terminal guarantee lives in a done-callback, not in the
        # coroutine's own ``except``, for the same never-started reason.
        task.add_done_callback(self._on_handover_settled)
        self._dictation_handover_task = task
        _pl.log.info(
            "Dictation key pressed during a live voice session — hung up, "
            "waiting for the microphone."
        )
        return True

    async def _dictate_when_the_microphone_is_free(
        self, loop: asyncio.AbstractEventLoop, *, target: str, source: str = "api"
    ) -> None:
        """Wait for the hung-up session to release the device, then dictate.

        The hangup has already been requested (see ``_begin_dictation_handover``);
        this is only the wait, and it is BOUNDED. The pipeline reaches IDLE after
        its capture context has exited, so waiting for that state is what keeps
        the dictation from opening a second native stream on the same device
        (AP-24). Nothing here can leave the wake gate closed — the gate is
        derived from this task being alive, so it reopens the moment this
        returns, raises or is cancelled (BUG-037).
        """
        try:
            deadline = loop.time() + _pl._DICTATION_HANDOVER_TIMEOUT_S
            while self._voice_session_holds_microphone():
                if loop.time() >= deadline:
                    _pl.log.warning(
                        "Dictation handover timed out after %.1fs — the voice "
                        "session still holds the microphone.",
                        _pl._DICTATION_HANDOVER_TIMEOUT_S,
                    )
                    self._refuse_dictation(
                        "handover_failed",
                        "The voice conversation did not give the microphone back "
                        "in time, so the dictation did not start. Try the key "
                        "again in a moment.",
                    )
                    return
                await asyncio.sleep(_pl._DICTATION_HANDOVER_POLL_S)
            self._commit_dictation(loop, target=target, source=source)
        finally:
            # Not the terminal guarantee — a task cancelled before its first
            # step never runs this. ``_on_handover_settled`` is what always
            # runs; this only releases the handle as early as possible.
            self._dictation_handover_task = None

    def _on_handover_settled(self, task: asyncio.Task[None]) -> None:
        """Terminal guarantee for the handover: it commits, or it explains.

        Runs for EVERY end of the handover task, including one cancelled before
        it ever started — the fastest press-and-release, and the case a plain
        ``except asyncio.CancelledError`` inside the coroutine silently misses.
        Never raises: a callback that throws here would surface as a stray
        "exception in callback" and take the explanation with it (AP-18).
        """
        try:
            if getattr(self, "_dictation_handover_task", None) is task:
                self._dictation_handover_task = None
            if task.cancelled():
                # The key was let go (or a toggle stopped it) while the
                # conversation was still shutting down. Starting the recording
                # now would leave a dictation nobody is holding a key for,
                # running to the duration cap — so say what happened instead.
                # The hangup itself already went through, which is exactly why
                # pressing again works — USUALLY. The sentence checks rather
                # than assumes: a session whose teardown is wedged still holds
                # the device at this moment (BUG-185), and "the microphone is
                # free now" was exactly the lie the user read ten times in a
                # row while nothing they pressed could work.
                if self._voice_session_holds_microphone():
                    detail = (
                        "The voice conversation is still shutting down, so "
                        "nothing was recorded. Hold the key a little longer, "
                        "or press it again once the voice bar has closed."
                    )
                else:
                    detail = (
                        "The voice conversation was still shutting down when "
                        "the dictation key was released, so nothing was "
                        "recorded. The microphone is free now — press the key "
                        "again."
                    )
                self._refuse_dictation("handover_failed", detail)
                return
            error = task.exception()
            if error is not None:
                _pl.log.warning("Dictation handover failed: %s", error, exc_info=error)
                self._refuse_dictation(
                    "handover_failed",
                    "Handing the microphone over from the voice conversation "
                    "failed, so the dictation did not start. Try the key again.",
                )
        except Exception:  # noqa: BLE001 — a refusal must never become a crash
            _pl.log.debug("Dictation handover callback failed", exc_info=True)

    def _commit_dictation(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        target: str,
        source: str = "api",
        beside_call: bool = False,
    ) -> bool:
        """Arm the wake block, announce the turn and spawn the recording task.

        The commit point shared by the direct start and the handover, so both
        arrive in the dictation lane through exactly one door. Always returns
        ``True``; every reason not to be here is checked by ``start_dictation``.

        ``beside_call`` means a live call keeps running next to this dictation:
        its input is held until the task ends, and the call's hangup event is
        left alone — it belongs to the call, not to this recording.
        """
        self._dictation_started_by = str(source or "api")
        self._dictation_discard_requested = False
        self._dictation_leave_no_trace = False
        self._dictation_beside_call = beside_call
        # A fresh dictation session must NOT inherit a stale hangup. ``_hangup_event``
        # is set by every "auflegen" and is otherwise only cleared when the next
        # VOICE session is accepted (``_run_session``). The dictation lane shares
        # that event in its ``asyncio.wait`` gate, so a leftover hangup from an
        # earlier voice call would finalize this session on its first tick — the
        # mic appears to "stop the instant you click it". Clear it here, mirroring
        # the voice-path ``self._hangup_event.clear()`` at session accept. Beside
        # a live call the event is the CALL's: clearing it could swallow a
        # hangup the user just asked for, and the lane does not wait on it.
        hangup = getattr(self, "_hangup_event", None)
        if hangup is not None and not beside_call:
            hangup.clear()
        if beside_call:
            # Held BEFORE the recording task exists, so the call stops hearing
            # the user as early as possible.
            self._set_voice_input_held(True)
        # Stored RAW ("auto" / "insert" / "chat"). ``auto`` is resolved when the
        # recording ENDS, not here: the window that matters is the one in front
        # when the text is delivered. Clicking "Start dictating" in the app and
        # then switching to the target application is a normal flow, and
        # resolving at start would have sent that text to the chat box.
        self._dictation_target = target if target in ("insert", "chat") else "auto"
        self._dictation_stop_event = asyncio.Event()
        # Watchdog deadline for the wake-word block (see
        # ``_dictation_blocks_activation``). It is a TIMESTAMP, copying the
        # ``_wake_lock_until`` pattern, so a dictation task that somehow never
        # terminates still cannot leave the wake word deaf forever — the worst
        # case is bounded instead of needing an app restart (BUG-037). The
        # allowance on top of the recording cap covers the closing
        # transcription, which runs after the microphone is already released.
        # A 0 recording ceiling means "speak as long as you like", and this
        # deadline must NOT inherit that. Unbounded here would re-open BUG-037:
        # a dictation task that somehow never terminates would leave the wake
        # word deaf until the app is restarted. So an unlimited recording still
        # gets a bounded — generously bounded — wake block. The two are allowed
        # to disagree: the worst case of this one expiring early is a wake word
        # that answers during a very long dictation, which is recoverable in a
        # second; the worst case of it never expiring needs a restart.
        block_s = getattr(self, "_dictation_max_s", _pl._DICTATION_DEFAULT_MAX_S)
        if not block_s:
            block_s = _pl._DICTATION_UNBOUNDED_WAKE_BLOCK_S
        self._dictation_wake_block_until = time.time() + float(block_s) + 60.0
        # Reset BEFORE the task exists: the teardown guarantee below reads this
        # to decide whether a terminal event still has to be published.
        self._dictation_completion_published = False
        # Announce the turn BEFORE the first audio frame. Queued ahead of the
        # session task on purpose: nothing has opened the microphone yet when
        # this method returns, so a UI surface can show "listening" at key-down
        # speed instead of waiting for the first partial transcript — which
        # costs a partial interval plus an STT round-trip, and for a short press
        # never arrives at all.
        self._publish_event_soon(
            _pl.DictationStarted(
                source_layer="speech.dictation", target=self._dictation_target
            )
        )
        self._dictation_task = loop.create_task(
            self._dictation_session(), name="dictation"
        )
        if beside_call:
            self._dictation_task.add_done_callback(self._on_beside_call_dictation_done)
        _pl.log.info(
            "🎙️ dictation started (transcribe-only, target=%s, via=%s%s).",
            self._dictation_target,
            self._dictation_started_by,
            ", beside a live call" if beside_call else "",
        )
        return True

    def _refuse_dictation(self, reason: str, detail: str) -> None:
        """Log AND announce a refused dictation start.

        ``reason`` must come from ``DICTATION_REFUSAL_REASONS`` — the single
        vocabulary for this value, checked here so a new branch that forgets to
        extend it is caught in the log instead of reaching a UI that has never
        heard of the token (AP-4 / BUG-008).
        """
        if reason not in _pl.DICTATION_REFUSAL_REASONS:
            _pl.log.warning(
                "Unknown dictation refusal reason %r — add it to "
                "DICTATION_REFUSAL_REASONS.",
                reason,
            )
        _pl.log.info("start_dictation refused (%s): %s", reason, detail)
        self._publish_event_soon(
            _pl.DictationRefused(
                source_layer="speech.dictation", reason=reason, detail=detail
            )
        )

    def dictation_active(self) -> bool:
        """Is the dictation lane engaged right now? (REST/UI status, cheap.)

        True for the recording AND for the handover that is clearing a voice
        conversation out of the way for one. Both count, because both mean the
        key has been pressed and the lane is owed exactly one outcome — a second
        start in that window is the ``already_running`` no-op, not a race for
        the microphone.
        """
        for name in ("_dictation_task", "_dictation_handover_task"):
            task = getattr(self, name, None)
            if task is not None and not task.done():
                return True
        return False

    def stop_dictation(self) -> bool:
        """Signal the active dictation session to finish (best-effort).

        A handover still in flight is CANCELLED rather than stopped: the
        recording it was about to start has not begun, and letting it start now
        would leave a dictation nobody is holding a key for, running to the
        duration cap. The cancellation publishes its own refusal, so a hold
        gesture released mid-handover still tells the user what happened.
        """
        handover = getattr(self, "_dictation_handover_task", None)
        if handover is not None and not handover.done():
            handover.cancel()
            # Belt and braces: should a recording ALSO be alive (a handover
            # that already committed but has not cleared its handle yet), the
            # stop must reach it too — returning here used to leave the
            # recording running with the stop swallowed (BUG-191).
            task = getattr(self, "_dictation_task", None)
            if task is not None and not task.done():
                self._dictation_stop_event.set()
            return True
        if self._dictation_task is None or self._dictation_task.done():
            return False
        self._dictation_stop_event.set()
        return True

    def request_dictation_stop(self, *, discard: bool = False) -> bool:
        """End a running dictation from OUTSIDE the pipeline's loop — the bar's X.

        The dictation counterpart of ``request_hangup``: the Jarvis Bar runs on
        its own Tk thread (or in a child process, on macOS), while the stop
        event and its waiter belong to the pipeline's asyncio loop, so the
        request is marshalled onto that loop. ``discard=True`` is what the
        close-X means — make it go away, deliver nothing — and matches what the
        same X does to a voice session; the default finishes and delivers, like
        the key. Returns whether a dictation was there to stop, so a caller can
        tell "stopped" from "nothing was running".

        Until BUG-191 the bar drew its X in the dictation modes and resolved
        every click on it to nothing, on the theory that another way to stop
        always existed. With a lost release edge there was none.
        """
        active = self.dictation_active()
        if not active:
            _pl.log.debug("request_dictation_stop: no dictation is running.")
            return False
        _pl.log.info(
            "📵 request_dictation_stop — %s the running dictation (via=%s).",
            "discarding" if discard else "finishing",
            getattr(self, "_dictation_started_by", "") or "unknown",
        )

        def _dispatch() -> None:
            try:
                if discard:
                    self._dictation_discard_requested = True
                self._dictate_key_down = False
                self.stop_dictation()
                if discard:
                    # The stop event only ends capture. After release the lane
                    # may be waiting on model startup, STT or formatting, so an
                    # explicit discard must cancel that work as well. The task's
                    # completion handler closes the UI and releases the wake gate.
                    task = getattr(self, "_dictation_task", None)
                    if task is not None and not task.done():
                        # Let a just-created session enter its cleanup scope
                        # before cancellation; repeated X clicks must not cancel
                        # the cleanup itself.
                        def _cancel() -> None:
                            if not task.done() and not task.cancelling():
                                task.cancel()

                        if current is not None or (
                            owner is not None and owner.is_running()
                        ):
                            asyncio.get_running_loop().call_soon(_cancel)
                        else:
                            _cancel()
            except Exception:  # noqa: BLE001 — a stop gesture must never crash
                _pl.log.exception("request_dictation_stop dispatch failed")

        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if owner is not None and owner.is_running() and current is not owner:
            try:
                owner.call_soon_threadsafe(_dispatch)
                return True
            except RuntimeError:
                _pl.log.debug("request_dictation_stop: owner loop closed during dispatch")
        _dispatch()
        return True

    async def _watch_dictation_hold_key(self) -> None:
        """Finish a HOLD recording whose key is physically up — the lost release.

        Runs beside the recording only for a dictation the hold key started.
        Every ``_DICTATE_HOLD_WATCH_POLL_S`` it asks the live trigger whether
        the dictation chord is down. ``None`` means this backend cannot tell
        (no listener, no package, Wayland): the watchdog stands down at once
        and the lane keeps working from edges alone — it never invents a
        release. ``False`` for ``_DICTATE_HOLD_LOST_RELEASE_S`` straight means
        the key-up happened and its edge never arrived; the recording is then
        ended through the same stop event a real release sets, so what was
        said is delivered exactly as if the edge had come (BUG-191).
        """
        trigger = getattr(self, "_hotkey_trigger", None)
        probe = getattr(trigger, "chord_is_down", None)
        if trigger is None or not callable(probe):
            return
        up_since: float | None = None
        while True:
            answer = probe("dictate")
            if answer is None:
                _pl.log.debug(
                    "hold-key watchdog: this hotkey backend cannot report key "
                    "state — the recording relies on the release edge alone."
                )
                return
            now = time.monotonic()
            if answer:
                up_since = None
            elif up_since is None:
                up_since = now
            elif now - up_since >= _pl._DICTATE_HOLD_LOST_RELEASE_S:
                _pl.log.warning(
                    "The dictation hold key has been physically up for %.1fs and "
                    "no release edge arrived — finishing the recording as the "
                    "release would have (the key-up edge was lost).",
                    now - up_since,
                )
                self._dictate_key_down = False
                self._dictation_stop_event.set()
                return
            await asyncio.sleep(_pl._DICTATE_HOLD_WATCH_POLL_S)

    def _dictation_expected_language(self) -> str:
        """The language the next dictation is expected in: a code, or ``auto``.

        The dictation language when one is chosen; otherwise the language
        recent dictations were in. It decides which on-device model can read
        the recording, and what a clip too short to detect from is told.
        """
        cfg = getattr(self, "_dictation_cfg", None)
        pinned = str(getattr(cfg, "language", "auto") or "auto").strip().lower() or "auto"
        if pinned != "auto":
            return pinned
        try:
            return self._recent_dictation_language() or "auto"
        except Exception:  # noqa: BLE001 — a hint, never a gate
            _pl.log.debug("recent dictation language unavailable", exc_info=True)
            return "auto"

    def _dictation_resolution(self) -> Any:
        """The recognizers for the next dictation, resolved when something changed.

        Kept between dictations and resolved again when a speech key was saved
        or removed, an on-device model appeared, or the expected language
        changed (``_reset_dictation_stt`` drops it on a settings change). So a
        key pasted in the settings counts from the next press on, without a
        restart. The rules are in :mod:`dodaios.dictation.recognizers`.
        """
        # One resolution at a time: a dictation resolves in a worker thread
        # while the status route may ask on the event loop.
        with _pl._DICTATION_RESOLUTION_LOCK:
            return self._resolve_dictation_recognizers()

    def _resolve_dictation_recognizers(self) -> Any:
        """The body of ``_dictation_resolution``, under its lock."""
        from dodaios.dictation.recognizers import (
            Resolution,
            credential_signature,
            parakeet_ready,
            resolve_recognizers,
        )
        from dodaios.dictation.take import Recognizer

        config = getattr(self, "_config", None)
        stt_cfg = getattr(config, "stt", None) if config is not None else None
        if stt_cfg is None:
            # A pipeline without a configuration reads with its voice provider.
            voice = getattr(self, "_utterance_stt", None)
            if voice is None:
                return Resolution()
            return Resolution(
                recognizers=(
                    Recognizer(
                        id=str(getattr(voice, "name", "") or type(voice).__name__),
                        provider=voice,
                        on_device=bool(getattr(voice, "runs_on_device", False)),
                    ),
                )
            )

        dictation_cfg = getattr(self, "_dictation_cfg", None)
        language = self._dictation_expected_language()
        has_parakeet = parakeet_ready()
        signature = (credential_signature(stt_cfg), language, has_parakeet)
        cached = getattr(self, "_dictation_resolution_cache", None)
        if cached is not None and cached[0] == signature:
            return cached[1]

        from dodaios.plugins.stt import (
            _stt_family_has_key,
            available_stt_provider_names,
            build_named_stt_provider,
            build_stt_from_config,
            provider_runs_on_device,
        )

        configured = str(getattr(stt_cfg, "provider", "") or "").strip()
        own_prompt = str(getattr(dictation_cfg, "bias_prompt", "") or "").strip()

        def _build(name: str) -> Any | None:
            # No vocabulary in the decoder prompt: a recognizer recites a
            # primed word list over pauses. The vocabulary corrects the
            # finished text instead (see ``_wrap``).
            try:
                patched = stt_cfg.model_copy(
                    update={"provider": name, "bias_prompt": own_prompt}
                )
                return build_stt_from_config(patched, dictionary_bias=False)
            except Exception as exc:  # noqa: BLE001 — one engine less, not no dictation
                _pl.log.warning("Dictation recognizer %s could not be built: %s", name, exc)
                return None

        def _cloud(name: str) -> Any | None:
            instance = _build(name)
            # A provider without a usable key is built as the local floor;
            # that is not the cloud provider asked for.
            built_as = str(getattr(instance, "name", "") or "")
            if instance is None or (built_as and provider_runs_on_device(built_as)):
                return None
            return instance

        def _keyed_cloud_names() -> list[str]:
            names = [n for n in available_stt_provider_names() if not provider_runs_on_device(n)]
            if (
                configured
                and configured not in names
                and not provider_runs_on_device(configured)
                and _stt_family_has_key(configured)
            ):
                names.insert(0, configured)
            return names

        def _whisper_in_process() -> Any | None:
            try:
                return build_named_stt_provider(
                    "faster-whisper", stt_cfg, dictionary_bias=False
                )
            except Exception as exc:  # noqa: BLE001
                _pl.log.debug("in-process Whisper unavailable for dictation: %s", exc)
                return None

        def _wrap(provider: Any) -> Any:
            try:
                from dodaios.speech.stt_dictionary import wrap_stt_with_dictionary

                provider = wrap_stt_with_dictionary(provider)
            except Exception as exc:  # noqa: BLE001 — corrections are not load-bearing
                _pl.log.warning("STT dictionary wrapper unavailable for dictation: %s", exc)
            return _pl.meter_stt(
                provider, getattr(self, "_speech_spend", None), trace_id=self._speech_trace
            )

        worker = self._dictation_local_final(dictation_cfg)
        has_accelerator = False
        if worker is not None:
            from dodaios.dictation.local_final import _no_accelerator_answers

            has_accelerator = not _no_accelerator_answers()
            # Without a graphics card the worker reads on the CPU: slow, but
            # the only Whisper there is on such a host.
            worker._allow_cpu = not has_accelerator

        try:
            faster_whisper_here = "faster-whisper" in available_stt_provider_names()
        except Exception:  # noqa: BLE001
            faster_whisper_here = False

        resolution = resolve_recognizers(
            stt_cfg,
            language=language,
            cloud=_cloud,
            keyed_cloud_names=_keyed_cloud_names,
            runs_on_device=provider_runs_on_device,
            whisper_worker=worker,
            whisper_has_accelerator=has_accelerator,
            parakeet=self._dictation_parakeet if has_parakeet else None,
            configured_local=_build,
            whisper_in_process=_whisper_in_process if faster_whisper_here else None,
            wrap=_wrap,
        )
        if worker is not None:
            worker.cloud_behind = any(not r.on_device for r in resolution.recognizers[1:])
        self._dictation_resolution_cache = (signature, resolution)
        _pl.log.info(
            "Dictation recognizers: %s%s",
            " -> ".join(
                f"{r.id}{'/' + r.model if r.model else ''}"
                f"{' (on this computer)' if r.on_device else ''}"
                for r in resolution.recognizers
            )
            or "<none>",
            f" [{resolution.detail}]" if resolution.detail else "",
        )
        return resolution

    def _dictation_parakeet(self) -> Any | None:
        """The one Parakeet recognizer of this pipeline, built on first use."""
        instance = getattr(self, "_dictation_parakeet_instance", None)
        if instance is None:
            try:
                from dodaios.plugins.stt.parakeet_local import ParakeetLocalSTT

                instance = ParakeetLocalSTT()
            except Exception as exc:  # noqa: BLE001 — the other recognizers remain
                _pl.log.warning("Parakeet recognizer unavailable for dictation: %s", exc)
                return None
            self._dictation_parakeet_instance = instance
        return instance

    def _rest_dictation_parakeet(self) -> None:
        """Free the Parakeet model after a while without a dictation.

        The loaded model holds about 1.5 GB of memory and loads in about a
        second, while the person is already speaking. So it is released after
        at most three minutes without a dictation, sooner than the idle time
        the settings give the local engines, and loaded again with the next
        key press. An idle time of 0 keeps it loaded.
        """
        handle = getattr(self, "_dictation_parakeet_rest", None)
        if handle is not None:
            handle.cancel()
            self._dictation_parakeet_rest = None
        instance = getattr(self, "_dictation_parakeet_instance", None)
        idle_s = self._dictation_idle_release_s(getattr(self, "_dictation_cfg", None))
        if instance is None or idle_s <= 0:
            return
        idle_s = min(idle_s, _pl._DICTATION_PARAKEET_REST_S)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def _release() -> None:
            self._dictation_parakeet_rest = None
            if self.dictation_active():
                return
            # Dropping the reference is the whole release; the next dictation
            # builds the recognizer again.
            instance._recognizer = None
            _pl.log.info("Parakeet model released after %.0f s without a dictation.", idle_s)

        self._dictation_parakeet_rest = loop.call_later(idle_s, _release)

    def _dictation_stt(self) -> Any:
        """A provider-shaped reader for a finished recording, or ``None``.

        For the callers outside a live dictation (reading a kept recording
        again, a voice note from the phone). It reads through the same
        recognizers, in the same way, as a dictation does.
        """
        try:
            if not self._dictation_resolution().recognizers:
                return None
        except Exception as exc:  # noqa: BLE001 — the voice provider can still read
            _pl.log.warning("Dictation recognizers could not be resolved: %s", exc)
            return getattr(self, "_utterance_stt", None)
        from dodaios.dictation.take import RecordingReader

        return RecordingReader(
            lambda: self._dictation_resolution().recognizers,
            language_hint=self._recent_dictation_language,
        )

    def _schedule_dictation_warmup(self, provider: Any = None) -> None:  # noqa: ARG002
        """Start the local Whisper worker off the key-press path. Never raises.

        Only that engine is started ahead: on a machine with a graphics card
        its first start can take minutes. A cloud provider has nothing to
        load, and the Parakeet model loads in about a second when the key
        goes down.
        """
        if getattr(self, "_dictation_warmup_shutdown", False):
            return
        try:
            loop = asyncio.get_running_loop()
            recognizers = self._dictation_resolution().recognizers
        except Exception as exc:  # noqa: BLE001 — the first press loads it instead
            _pl.log.debug("dictation warm-up skipped: %s", exc)
            return
        if not recognizers or recognizers[0].id != "faster-whisper":
            return
        warm = getattr(recognizers[0].provider, "warm_up", None)
        current = getattr(self, "_dictation_warmup_task", None)
        if not callable(warm) or (current is not None and not current.done()):
            return

        async def _warm() -> None:
            started = time.monotonic()
            try:
                await asyncio.to_thread(warm)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the first press loads it instead
                _pl.log.warning("Dictation recognizer warm-up failed: %s", exc)
            else:
                _pl.log.info(
                    "Dictation recognizer warm-up done in %.0f ms.",
                    (time.monotonic() - started) * 1000.0,
                )

        self._dictation_warmup_task = loop.create_task(_warm(), name="dictation-stt-warmup")

    @staticmethod
    def _dictation_idle_release_s(dictation_cfg: Any) -> float:
        """Seconds without a dictation after which the local engines are released."""
        from dodaios.dictation.idle_release import DEFAULT_IDLE_MINUTES

        minutes = getattr(dictation_cfg, "local_idle_minutes", None)
        try:
            return max(0.0, float(DEFAULT_IDLE_MINUTES if minutes is None else minutes)) * 60.0
        except (TypeError, ValueError):
            return DEFAULT_IDLE_MINUTES * 60.0

    def _dictation_local_final(self, dictation_cfg: Any) -> Any:
        """The out-of-process local Whisper engine of this pipeline, or ``None``.

        ``None`` when the person switched it off (``[dictation].local_engine``)
        or the local runtime is not importable here. One instance is kept for
        the life of the pipeline, because it owns a worker process; it is
        replaced only when its model or memory setting changed. What changes
        from press to press (free accelerator memory, a worker that fails to
        start) is the engine's own business: it refuses such a call with a
        failure the take answers by moving to the next recognizer.
        """
        cached = getattr(self, "_dictation_whisper_worker", None)
        if not bool(getattr(dictation_cfg, "local_engine", True)):
            if cached is not None:
                self._dictation_whisper_worker = None
                self._close_dictation_worker(cached[1])
            return None
        try:
            from dodaios.dictation.local_final import (
                DEFAULT_FINAL_MODEL,
                DEFAULT_MIN_FREE_GB,
                LocalFinalSTT,
            )
            from dodaios.dictation.local_preview import faster_whisper_available

            if not faster_whisper_available():
                return None
            model = str(getattr(dictation_cfg, "local_model", "") or "").strip()
            min_free = getattr(dictation_cfg, "local_min_free_gb", DEFAULT_MIN_FREE_GB)
            key = (
                model or DEFAULT_FINAL_MODEL,
                float(min_free if min_free is not None else 0.0),
                self._dictation_idle_release_s(dictation_cfg),
            )
            if cached is not None and cached[0] == key:
                return cached[1]
            if cached is not None:
                self._close_dictation_worker(cached[1])
            worker = LocalFinalSTT(key[0], min_free_gb=key[1], idle_release_s=key[2])
            self._dictation_whisper_worker = (key, worker)
            return worker
        except Exception as exc:  # noqa: BLE001 — the other recognizers remain
            _pl.log.warning("Local Whisper engine unavailable for dictation (%s).", exc)
            return None

    @staticmethod
    def _close_dictation_worker(worker: Any) -> None:
        """Stop a replaced local Whisper engine's worker process. Never raises."""
        try:
            worker.close()
        except Exception:  # noqa: BLE001 — a worker that will not close is already gone
            _pl.log.debug("closing the replaced dictation worker failed", exc_info=True)

    def _reset_dictation_stt(self) -> None:
        """Drop what a provider or language change makes stale.

        Called from every place that swaps the voice provider, the recognition
        language or a dictation setting. The dictation's recognizers are
        resolved again on the next press, and the voice lane's crossover cache
        is cleared with them: it holds provider instances built from the old
        language and a chain resolved against the old provider.
        """
        self._dictation_resolution_cache = None

    def _dictation_protected_terms(self) -> tuple[str, ...]:
        """Spellings the polish pass may not "correct" into something familiar.

        The reference dictation tool's own documentation warns about this
        failure direction explicitly: a rewrite model turns an unfamiliar
        technical term into the common word it resembles, and the user cannot
        tell it happened because the sentence still reads fine. So the words a
        user has already told us they care about travel with the request and are
        checked afterwards by the drift guard.

        Three sources: the STT dictionary (words the user added by hand for
        exactly this reason, plus the shipped defaults they kept), the configured wake
        word (a name, and names are what get "corrected"), and the assistant
        name derived from it. Nothing here is a secret and nothing is free text
        from a voice turn — AP-2 territory stays out of the prompt.

        Never raises and never blocks: an unreadable dictionary costs the guard
        its input, not the user their dictation.
        """
        terms: list[str] = []
        try:
            # Shipped defaults included (the product name, PyPI, GitHub …):
            # a rewrite model "correcting" them is the same failure.
            from dodaios.speech.stt_dictionary import dictionary_protected_words

            terms.extend(dictionary_protected_words())
        except Exception as exc:  # noqa: BLE001 — an unreadable store is not fatal
            _pl.log.debug("dictation protected terms: dictionary unavailable (%s)", exc)
        phrase = getattr(self, "_wake_phrase_label", "") or ""
        for word in str(phrase).split():
            if len(word) >= 2:
                terms.append(word)
        seen: set[str] = set()
        unique: list[str] = []
        for term in terms:
            key = term.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                unique.append(term.strip())
        return tuple(unique)
