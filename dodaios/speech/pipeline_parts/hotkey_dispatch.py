"""Hotkey loop and dictate key handlers.

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
    from dodaios.trigger.hotkey import HotkeyTrigger


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class HotkeyDispatchMixin(_HostBase):
    """Hotkey loop and dictate key handlers."""

    # ------------------------------------------------------------------
    # Hotkey-Loop
    # ------------------------------------------------------------------

    async def _hotkey_loop(self, trigger: HotkeyTrigger) -> None:
        async for event_name in trigger.events():
            # One raising handler must not end this loop: it is the ONLY
            # consumer of every global shortcut, and its death is invisible
            # from the desktop (a log line the WebView cannot show) — every
            # key simply stops working until a restart. The edge is dropped,
            # the next one is served (AP-18 for the hotkey lane, BUG-191).
            try:
                self._dispatch_hotkey_event(event_name)
            except Exception:  # noqa: BLE001 — contained on purpose, logged in full
                _pl.log.exception("Hotkey %r handler failed; the edge was dropped.", event_name)

    def _dispatch_hotkey_event(self, event_name: str) -> None:
        """Route one hotkey edge to its handler (the body of ``_hotkey_loop``)."""
        if event_name == "call":
            _pl.log.info("📞 CALL via Hotkey")
            # A deliberate key press — exempt from the post-hangup wake
            # lock (no speaker-echo path), same contract as PTT below. It is
            # also the gesture that may ask macOS for the microphone: the first
            # press of an undecided microphone raises the dialog and starts
            # nothing ("allowed - press again").
            if self._state == _pl.PipelineState.IDLE and self._activation_state_allows():
                refusal = self._ensure_microphone("voice")
                if refusal is not None:
                    _pl.log.info("Call key ignored: %s", refusal)
                    return
            self._explicit_call_pending = True
            self._call_event.set()
        elif event_name == "dictate_press":
            self._on_dictate_press()
        elif event_name == "dictate_release":
            self._on_dictate_release()
        elif event_name == "dictate_cancel":
            self._on_dictate_cancel()
        elif event_name == "dictate_early":
            self._on_dictate_early()
        elif event_name == "dictate_abandon":
            self._on_dictate_abandon()
        elif event_name == "dictate":
            # Legacy [dictation].mode = "toggle": one press starts, the
            # next stops. Only reached when the HOLD key is in toggle mode.
            self._on_dictate_toggle()
        elif event_name == "dictate_toggle":
            # The dedicated hands-free key. Same handler, its own binding.
            self._on_dictate_toggle()
        elif event_name == "paste_last":
            self._on_paste_last()
        elif event_name == "hangup":
            _pl.log.info("📵 HANGUP via Hotkey")
            self._trigger_voice_hangup()

    # ------------------------------------------------------------------
    # Dictation hotkey edges
    # ------------------------------------------------------------------

    def _on_dictate_press(self) -> None:
        """Dictation key DOWN — start recording into the focused text field.

        Idempotent by design: every backend reports a press exactly once per
        real chord-down (the Windows poller too — ``HotkeyChecker.run`` fires
        ``on_press`` only on the ``key_state != 1`` transition, whatever older
        comments in this file claimed), but a stray duplicate edge inside the
        grace window is still treated as the same hold. Only the first edge
        from "key up" starts anything.

        **The latch heals itself.** A key-up edge can be lost — the pynput and
        Quartz backends clear their own chord state without firing ``on_release``
        when the input permission is revoked mid-chord, and a focus change, a
        UAC prompt or an RDP reconnect can do the same. A latch that only a
        release could clear then swallowed EVERY later press, which presents as
        "the dictation shortcut just stopped working" with no error and no way
        back except an app restart. So a press that arrives long after the last
        one reported the key down is treated as what it physically is — a fresh
        press on a key nobody is holding — not as a repeat. A second press edge
        can only exist if the chord went up in between, so anything past the
        grace window is either a lost key-up or a genuinely new press, and both
        want the same repair.

        **A press while a dictation nobody is holding is running is its STOP**
        (BUG-191). The latch says "up", yet the lane is busy: a hands-free key,
        the bar, a REST call started it — or a release edge never made it here
        and the recording is still open. Before this, that press went to
        ``start_dictation``, was refused as ``already_running`` (a refusal the
        bar deliberately paints as nothing), and the latch was dropped again:
        the key did nothing, visibly, forever, and only a restart ended the
        recording. The dictation key is the kill switch of its own lane — an
        explicit press ends whatever is running and delivers it, which is what
        the user pressing it means.
        """
        if getattr(self, "_dictate_early_pending", False):
            # The confirmation of a solo hold key whose recording already
            # started at key-down (``_on_dictate_early``): it is a dictation
            # now, and the release submits it. Nothing else to do: should the
            # early recording have ended meanwhile, this hold started one
            # already, and a second one on the same hold would surprise.
            self._dictate_early_pending = False
            _pl.log.debug("Dictation key held alone — the early recording stays.")
            return
        now = time.monotonic()
        last_seen = float(getattr(self, "_dictate_key_seen_at", 0.0))
        latched = bool(getattr(self, "_dictate_key_down", False))
        stale = latched and (now - last_seen) > _pl._DICTATE_HOLD_REPEAT_GRACE_S
        self._dictate_key_seen_at = now
        if latched and not stale:
            return  # the same hold, re-reported inside the grace window
        if stale:
            _pl.log.info(
                "Dictation key-up edge was lost %.1fs ago — clearing the stale "
                "hold latch so the shortcut keeps working.",
                now - last_seen,
            )
            self._dictate_key_down = False
            if self.dictation_active():
                # The orphaned recording is still running with the microphone
                # open. Treat this press as the release that never arrived:
                # finish and deliver what was said instead of starting a second
                # dictation on top of it. The latch is clear, so the user's next
                # press starts a fresh one.
                self.stop_dictation()
                return
        if self.dictation_active():
            _pl.log.info(
                "Dictation key pressed while a dictation nobody is holding is "
                "still running (via=%s, %.1fs since the last edge) — finishing "
                "it instead of refusing the press.",
                getattr(self, "_dictation_started_by", "") or "unknown",
                now - last_seen if last_seen else 0.0,
            )
            self.stop_dictation()
            return
        self._dictate_key_down = True
        _pl.log.info("Dictation key down — starting a hold recording.")
        if not self.start_dictation(
            target=self._configured_dictation_target(), source="hold_key"
        ):
            # Could not start (no microphone, no STT). Drop the latch
            # immediately so the NEXT press is a fresh attempt rather than
            # being swallowed as a repeat. A live voice session is NOT one of
            # these: it is accepted and handed over, and the latch has to stay
            # so the release can cancel a handover that is still running.
            self._dictate_key_down = False

    def _on_dictate_early(self) -> None:
        """A modifier-only hold key went down ALONE: start recording at once.

        Such a key (a bare ``cmd``) is confirmed as a dictation only after it
        was held alone for ``SOLO_HOLD_S``, because it is also the first half
        of every shortcut that uses it. Waiting for that before anything
        happened made the Dodaios Bar rise a noticeable moment after the key
        went down (reported 2026-11-14). So the recording, and with it the
        bar, starts here at key-down, on approval: ``dictate_press`` confirms
        it, ``dictate_abandon`` (a shortcut, or a tap) takes it back without a
        trace.

        Only the plain start is taken early. Everything that would be seen or
        felt when the hold turns out to be ``cmd+c`` waits for the
        confirmation, which then runs the ordinary press: a refusal (it paints
        a cross on the bar), a voice conversation (the handover hangs it up,
        and beside a live call its input is held), a dictation that is already
        running (the press is its stop) and a microphone macOS has not decided
        on yet (the press may raise the system dialog).
        """
        if getattr(self, "_dictate_key_down", False) or self.dictation_active():
            return
        if not self._dictation_can_start_quietly():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # the confirmation's ordinary press says why
        self._dictate_key_seen_at = time.monotonic()
        self._dictate_key_down = True
        self._dictate_early_pending = True
        _pl.log.info("Dictation key down alone — starting the hold recording at once.")
        self._commit_dictation(
            loop, target=self._configured_dictation_target(), source="hold_key"
        )

    def _dictation_can_start_quietly(self) -> bool:
        """Would a dictation start right now with nothing but its bar to show?

        ``start_dictation``'s checks without any of its side effects: nothing
        is refused, published or asked. ``False`` for anything that is not the
        plain start.
        """
        if getattr(self, "_utterance_stt", None) is None:
            return False
        if self._live_call_owns_microphone() or self._voice_session_holds_microphone():
            return False
        if not self._user_capture_allowed():
            return False
        try:
            state = self._permission_service().check("microphone")
        except Exception:  # noqa: BLE001 - unknown: the confirmed press asks properly
            _pl.log.debug(
                "Microphone state unreadable for an early dictation start.", exc_info=True
            )
            return False
        return str(getattr(state, "value", state)) in ("granted", "not_required")

    def _on_dictate_abandon(self) -> None:
        """The early start of a solo hold key was a shortcut or a tap: undo it.

        Another key joined inside the window (``cmd+c``), or the key went up
        before it (a tap on Command). Nobody dictated, so the recording goes
        the way the bar's X sends it, and leaves nothing behind: no history
        row, no statistics, no "nothing was heard" mark. The bar rests again.
        """
        if not getattr(self, "_dictate_early_pending", False):
            return  # nothing started early; the confirmation never came either
        self._dictate_early_pending = False
        if not getattr(self, "_dictate_key_down", False):
            return
        self._dictate_key_down = False
        if not self.dictation_active():
            return
        _pl.log.info("Dictation key was a shortcut or a tap — taking the early recording back.")
        self._dictation_leave_no_trace = True
        self.request_dictation_stop(discard=True)

    def _on_dictate_release(self) -> None:
        """Dictation key UP — stop recording and submit what was held."""
        if not self._dictate_key_down:
            _pl.log.debug("Dictation key up with no hold latched — nothing to submit.")
            return
        self._dictate_key_down = False
        _pl.log.info(
            "Dictation key up after %.1fs — submitting the hold recording.",
            time.monotonic() - float(getattr(self, "_dictate_key_seen_at", 0.0) or 0.0),
        )
        self.stop_dictation()

    def _on_dictate_cancel(self) -> None:
        """Another key joined a modifier-only hold key: it was a shortcut.

        Only a modifier-only dictation key sends this (``SOLO_HOLD_EVENTS``),
        when a key or click joins after the hold had already started the
        recording: ``cmd`` held a moment, then ``tab``. The recording is
        discarded the way the bar's X discards it, so nothing is read or
        typed, no "nothing was heard" mark follows, and the bar rests at once.
        """
        if not self._dictate_key_down:
            _pl.log.debug("Dictation key cancel with no hold latched — nothing to discard.")
            return
        self._dictate_key_down = False
        _pl.log.info("Dictation key joined by another key — discarding the hold recording.")
        self.request_dictation_stop(discard=True)

    def _on_dictate_toggle(self) -> None:
        """Toggle mode: start if idle, stop if running.

        ``dictation_active`` covers the handover window too, so the second press
        of a hands-free toggle cancels a voice-session handover that has not
        finished instead of falling through and asking for a second dictation.
        """
        if self.dictation_active():
            _pl.log.info("Dictation toggle key — stopping the running dictation.")
            self.stop_dictation()
            return
        _pl.log.info("Dictation toggle key — starting a hands-free recording.")
        self.start_dictation(
            target=self._configured_dictation_target(), source="toggle_key"
        )

    def _on_paste_last(self) -> None:
        """"Insert the last dictation again" key — re-deliver the last transcript.

        Needs no microphone, no speech-to-text and no recording, which is the
        whole point: it stays useful exactly where dictation itself cannot run.

        Scheduled as a task rather than executed here, because the work behind
        it is blocking — it parses the history file and sleeps around the paste
        chord — and this handler runs ON the pipeline's event loop, the same
        loop a live voice turn uses (AP-9). A press while one is still running
        is dropped rather than queued: two overlapping pastes race over the
        clipboard restore and the loser puts the WRONG content back.
        """
        if getattr(self, "_paste_last_busy", False):
            _pl.log.debug("paste-last key ignored: a paste is already in flight")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _pl.log.debug("paste-last key ignored: no running event loop")
            return
        self._paste_last_busy = True
        loop.create_task(self._paste_last_dictation(), name="dictation-paste-last")

    async def _paste_last_dictation(self) -> None:
        """The blocking half of :meth:`_on_paste_last`. Never raises.

        Goes through ``insert_last_dictation`` — the SAME delivery path the
        REST route and a fresh dictation use — so the three can never drift
        apart. Anything short of "the text was typed where you were pointing"
        is announced on the bus instead of logged: the reported bug for this
        whole feature was a key that looked bound and did nothing visible.
        """
        try:
            from dodaios.dictation.insert import insert_last_dictation

            result = await asyncio.to_thread(
                insert_last_dictation, settings=getattr(self, "_dictation_cfg", None)
            )
        except Exception as exc:  # noqa: BLE001 — a paste is never worth a crash
            _pl.log.warning("paste-last failed (non-fatal)", exc_info=True)
            self._refuse_dictation(
                "paste_unavailable",
                "The last dictation could not be pasted again "
                f"({type(exc).__name__}).",
            )
            return
        finally:
            self._paste_last_busy = False

        reason = str(getattr(result, "reason", "") or "")
        detail = str(getattr(result, "detail", "") or "")
        insert = getattr(result, "insert", None)
        status = str(getattr(insert, "status", "") or "")
        _pl.log.info(
            "📋 paste-last: ok=%s reason=%s status=%s (%d chars)",
            bool(getattr(result, "ok", False)),
            reason or "-",
            status or "-",
            len(str(getattr(result, "text", "") or "")),
        )
        if getattr(result, "ok", False) and status not in ("clipboard_only", "paste_sent"):
            return  # the text is in the field the user was looking at — proof enough
        # Everything else owes an explanation: nothing saved, history off, or a
        # host that cannot type into another window (the text is on the
        # clipboard then, which the detail sentence says).
        token = {
            "not_found": "nothing_to_paste",
            "history_disabled": "history_disabled",
        }.get(reason, "paste_unavailable")
        self._refuse_dictation(
            token, detail or "The last dictation could not be pasted again."
        )

    def _configured_dictation_target(self) -> str:
        """``[dictation].target`` — ``auto`` by default, resolved at start."""
        cfg = getattr(self, "_dictation_cfg", None)
        return str(getattr(cfg, "target", "auto") or "auto")
