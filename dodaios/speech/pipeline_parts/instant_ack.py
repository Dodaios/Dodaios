"""Background completion and spawn watchdogs.

Moved out of ``pipeline.py`` without a behaviour change. Module-level names
of the pipeline are read through ``_pl`` at call time so the pipeline module
stays the one place that owns and patches them.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import TYPE_CHECKING

from dodaios.speech import pipeline as _pl

if TYPE_CHECKING:
    from dodaios.core.events import (
        ActionProposed,
        JarvisAgentAnnouncement,
        JarvisAgentBackgroundCompleted,
    )


class InstantAckMixin:
    """Background completion and spawn watchdogs."""

    # ------------------------------------------------------------------
    # Instant acknowledgment (2026-08-17)
    # ------------------------------------------------------------------

    _INSTANT_ACK_SOURCE_LAYER = "brain.instant_ack"

    def _instant_ack_compose_all(self) -> bool:
        ack_cfg = getattr(getattr(self, "_config", None), "ack_brain", None)
        return bool(getattr(ack_cfg, "instant_ack_compose_all", False))

    async def _on_action_proposed(self, event: ActionProposed) -> None:
        """Remember the tool the current voice turn is running (progress line)."""
        if (
            getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
            is not _pl.TurnTakingState.PROCESSING
        ):
            return

    def _interim_line_spoke_recently(self, within_s: float) -> bool:
        """Any preamble/progress line (instant ack, router ack, heartbeat) just spoke."""
        last = getattr(self, "_last_preamble_spoken", None)
        return bool(last is not None and (time.monotonic() - last[1]) < within_s)

    def _note_instant_ack_spoken(self, text: str, at: float | None = None) -> None:
        """Record the moment an instant ack actually went to the speaker.

        ``at`` is the same monotonic stamp stored in ``_last_preamble_spoken``
        so the progress line can tell the turn's own ack from other emitters.
        """
        _pl.note_spoken(text)

    async def _await_ack_turn_commit(self, grace_ms: int) -> bool:
        """Poll the turn-state for up to ``grace_ms``; True only if it stays
        PROCESSING throughout — the continuation grace from AD-OE5.

        The Pre-Thinking-Ack is ready a few hundred ms after the VAD endpoint,
        often before the VAD has registered that the user merely paused and kept
        talking. Returning False the instant the turn leaves PROCESSING (the
        continuation interrupt flips it to LISTENING/USER_SPEAKING, or the brain
        answered → JARVIS_SPEAKING) lets the caller drop the ack before it can
        speak over the user.
        """
        step_s = 0.05
        steps = max(1, int(grace_ms / 1000.0 / step_s))
        for _ in range(steps):
            if self._turn_state is not _pl.TurnTakingState.PROCESSING:
                return False
            await asyncio.sleep(step_s)
        return self._turn_state is _pl.TurnTakingState.PROCESSING

    async def _on_background_completed(
        self, event: JarvisAgentBackgroundCompleted
    ) -> None:
        """Announce a finished background Jarvis-Agent task.

        The readback goes through ``_on_announcement`` like every other
        announcement: an open realtime call speaks it, an open classic
        session speaks it, and with no open voice session it is not voiced
        at all (user decision 2026-10-05: no spoken news out of nowhere).

        CRIT-5 (2026-05-17): cancel the oldest pending spawn-watchdog --
        FIFO matches the sequential dispatch model. If the watchdog has
        already fired and emitted "Bin noch dran.", the cancel is a
        cheap no-op.
        """
        if self._spawn_watchdog_tasks:
            task = self._spawn_watchdog_tasks.pop(0)
            if not task.done():
                task.cancel()
        if getattr(self, "_muted", False):
            _pl.log.debug("Background-completed announcement suppressed — voice muted")
            return
        # WS3b (live bug 2026-06-14): a Jarvis-Agent mission that completes AFTER
        # the user hung up still owes them its result. This readback is a FRESH
        # turn (the answer they asked for), not a stale leftover from the aborted
        # turn, so it must NOT be dropped by the hangup gate (AD-OE6
        # zero-silent-drop). The mission ran in its own subprocess + Job Object;
        # hangup never killed it. The mute guard above still silences a
        # deliberately-muted session, and the phrases below stay priority
        # "normal" → queued behind any current speech, never barging
        # mid-utterance (AD-OE5).
        # Resolve the readback language from the original request utterance,
        # falling back to the worker summary text (pin > conversation-stickiness
        # > detected utterance/summary > default) so an English/Spanish user
        # never hears "Fertig." in German, and the "Done./Fertig." prefix never
        # mismatches the summary language (forensic 2026-06-23: announcement
        # emitters bypassed the resolver).
        lang = self._output_language(
            None,
            getattr(event, "utterance", "") or getattr(event, "summary", "") or "",
        )
        ph = self._BG_READBACK_PHRASES.get(lang, self._BG_READBACK_PHRASES["en"])
        if event.success and event.summary:
            summ = event.summary.strip()
            if len(summ) > 200:
                summ = summ[:200].rsplit(" ", 1)[0] + "…"
            text = ph["done_summ"].format(s=summ)
        elif event.success:
            text = ph["done"]
        else:
            err_short = (event.error or ph["unknown_err"])[:80]
            text = ph["fail"].format(e=err_short)
        # Defense-in-Depth: Summary/Error kann aus dem Jarvis-Agent-Pfad kommen
        # und Engineering-Tokens (Sub-Agent, Subprocess, MCP) enthalten.
        # scrub_for_voice filtert die raus, sonst leakt Worker-Mechanik
        # in den Voice-Kanal (vgl. Mandat-Pfad #2 Output-Filter).
        scrubbed = _pl.scrub_for_voice(text, language=lang)
        if scrubbed.actions:
            _pl.log.info(
                "🧹 Background-Filter: %s (fallback=%s)",
                scrubbed.actions, scrubbed.fallback_used,
            )
        if _pl.is_harmless_scrub_residue(scrubbed) or not scrubbed.cleaned.strip():
            # The worker's own summary did not survive the filter. Speaking the
            # residue guard's error phrase would invent a failure on a mission
            # that succeeded as often as not — but silence is not the answer
            # either: the user is waiting for THIS result (AD-OE6,
            # zero-silent-drop). Retry with the deterministic phrase that
            # carries no summary, which is hand-tuned to pass the filter.
            plain = (
                ph["done"] if event.success
                else ph["fail"].format(e=ph["unknown_err"])
            )
            _pl.log.info(
                "Agent background finished (success=%s) — the readback "
                "carried no substance (%s), falling back to the summary-less "
                "phrase instead of the error phrase: %r",
                event.success,
                scrubbed.actions,
                text[:80],
            )
            if plain != text:
                scrubbed = _pl.scrub_for_voice(plain, language=lang)
            if _pl.is_harmless_scrub_residue(scrubbed) or not scrubbed.cleaned.strip():
                # Even the canned line does not survive. Staying silent beats
                # claiming a failure, but it means a completion went
                # unannounced — say so in the log, loudly.
                _pl.log.warning(
                    "Agent background finished (success=%s) and was "
                    "NEVER announced: both the summary and the canned phrase "
                    "were filtered away (%s)",
                    event.success,
                    scrubbed.actions,
                )
                return
        cleaned = scrubbed.cleaned.strip()
        _pl.log.info(
            "Agent background finished (success=%s, duration=%.1fs) — readback: %r",
            event.success, event.duration_s, cleaned,
        )
        # One choke point for every spoken announcement: ``_on_announcement``
        # hands the readback to an open realtime call, defers it while the
        # user holds the floor, and never lets the classic TTS voice speak
        # it outside an open voice session.
        await self._on_announcement(
            _pl.AnnouncementRequested(
                source_layer="harness.jarvis_agent.background",
                text=cleaned,
                language=lang,
                priority="normal",
                kind="subagent",
            ),
            # The FIFO pop above retired this mission's own watchdog; a
            # newer mission that is still running keeps its heartbeat.
            cancel_heartbeats=False,
        )

    async def _on_spawn_announcement(self, event: JarvisAgentAnnouncement) -> None:
        """Spawn-ACK ist auf User-Wunsch (2026-05-12) deaktiviert.

        History:
            2026-04-25 .. 2026-05-10 — Pfad war stumm (User-Wunsch).
            2026-05-11 — kurz reaktiviert mit fixer Phrase "Okay, mache ich."
                         weil der User ein Voice-Feedback wollte um stille
                         Timeouts vom erfolgreichen Spawn unterscheiden zu
                         koennen.
            2026-05-12 — User widerruft. Jede Spawn-ACK-Phrase nervt; der
                         User unterscheidet Spawn vs. Timeout jetzt visuell
                         (Sub-Agents-Board) und ueber den Background-
                         Completed-Voice-Readback am Ende der Mission.

        Der Bus-Event selbst (``JarvisAgentAnnouncement``) wird in
        ``spawn_worker.py`` weiterhin publisht und vom UI gelesen — wir
        unterdruecken hier nur den Voice-Pfad. Cleanup-Logging behalten wir
        einmalig pro Event, damit man im Log noch sehen kann dass der ACK
        absichtlich ueber-sprungen wurde (debug-friendly bei spaeteren
        Voice-Bug-Reports).
        """
        _pl.log.info(
            "Spawn-ACK suppress't (User-Wunsch 2026-05-12) — action=%r target=%r",
            event.action, event.target,
        )
        # CRIT-5 (2026-05-17) + heartbeat rework (2026-06-19): schedule the
        # background-mission heartbeat so the user hears a varied, language-
        # resolved "still on it" reassurance while a long mission runs (first
        # beat well before the old 90 s, then bounded). _on_background_completed
        # cancels it on the crash path; a completion readback cancels it via
        # _cancel_spawn_heartbeats in the happy path.
        self._schedule_spawn_watchdog()
        return

    def _schedule_spawn_watchdog(self) -> None:
        """Start the background-mission heartbeat: a bounded series of varied,
        language-resolved "still on it" reassurances while the mission has not
        completed (see ``_spawn_watchdog_body``). FIFO-cancelled by
        ``_on_background_completed``; also cancelled on a completion readback via
        ``_cancel_spawn_heartbeats``."""
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            self._spawn_watchdog_body(
                origin_session_id=getattr(self, "_current_voice_session_id", None)
            ),
            name=f"spawn-watchdog-{len(self._spawn_watchdog_tasks)}",
        )
        self._spawn_watchdog_tasks.append(task)

    def _pick_heartbeat_phrase(self) -> tuple[str, str]:
        """Pick one varied "still on it" heartbeat phrase + its language.

        Language flows through the single output-language resolver
        (``_output_language``: ``brain.reply_language`` pin > sticky
        conversation language > ``DEFAULT_LOCALE``) — never hard-coded "de", so
        a German / English / Spanish conversation hears the heartbeat in its own
        language. The phrase comes from the varied ``STILL_RUNNING_PHRASES`` pool
        with a small no-repeat guard so consecutive beats differ. The pool lives
        in the allowlisted spawn-announcement module (keeps the German/Spanish
        runtime strings out of this file); a lazy import + neutral fallback keeps
        the spoken path crash-proof.
        """
        lang = _pl._phrase_lang(self._output_language(None, ""))
        try:
            from dodaios.brain.ack_brain.spawn_announcement import (  # noqa: PLC0415
                STILL_RUNNING_PHRASES,
            )

            pool = STILL_RUNNING_PHRASES.get(lang) or STILL_RUNNING_PHRASES["en"]
        except Exception:  # noqa: BLE001 — the heartbeat must never crash the loop
            return ("Still working on it.", lang)
        recent = getattr(self, "_heartbeat_recent", None)
        choices = [p for p in pool if recent is None or p not in recent] or list(pool)
        choice = random.choice(choices)  # noqa: S311 — phrase variety, not crypto
        if recent is not None:
            recent.append(choice)
        return (choice, lang)

    async def _spawn_watchdog_body(
        self, *, origin_session_id: str | None = None
    ) -> None:
        """Speak a bounded, varied, language-resolved "still on it" heartbeat
        while a background mission runs.

        Replaces the old one-shot, German-only "Bin noch dran." (2026-06-19):
        the first beat fires after ``_spawn_watchdog_delay_s`` (90 s of silence
        read as a crash), then up to ``_heartbeat_max_count`` total,
        ``_heartbeat_interval_s`` apart, so the wait feels alive instead of dead.
        Each beat is picked fresh (``_pick_heartbeat_phrase``) and emitted as a
        ``priority="normal"`` ``AnnouncementRequested`` — which the AD-OE5 floor
        guard in ``_on_announcement`` drops if the user holds the floor (never
        speaks over the user). A muted session stays silent. ``CancelledError``
        (mission finished / completion readback) exits quietly.

        On EVERY terminal path the task removes itself from
        ``_spawn_watchdog_tasks``. That list is the "background mission in flight"
        signal read by ``_active_session``'s idle-timeout override and by
        ``_finish_after_response``; a done-but-still-listed task would hold the
        voice session open forever, because the success path never publishes the
        ``JarvisAgentBackgroundCompleted`` event that would otherwise drain it. The
        hard cap bounds the in-flight hold to the heartbeat lifetime.

        A beat belongs to the voice session the mission was started in
        (``origin_session_id``; ``None`` for a typed chat). It is skipped once
        a DIFFERENT voice session is open: that call never asked for the
        mission, and inside a live call the line lands as backend commentary
        that the duplex model voices over the user and that stalls its reply
        to a short greeting (live bug 2026-10-02 17:58, "Hallo, was geht ab?"
        unanswered for 6 s after a chat mission's beat entered the new call).
        """
        try:
            max_count = max(1, getattr(self, "_heartbeat_max_count", 3))
            interval = getattr(self, "_heartbeat_interval_s", 60.0)
            delay = self._spawn_watchdog_delay_s
            for beat in range(1, max_count + 1):
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                delay = interval
                if getattr(self, "_muted", False):
                    _pl.log.debug("Spawn-heartbeat: muted, skipping beat %d", beat)
                    continue
                current_session_id = getattr(self, "_current_voice_session_id", None)
                if (
                    current_session_id is not None
                    and current_session_id != origin_session_id
                ):
                    _pl.log.info(
                        "Spawn-heartbeat #%d skipped — the mission was not "
                        "started in the open voice session",
                        beat,
                    )
                    continue
                if self._bus is None:
                    return
                phrase, lang = self._pick_heartbeat_phrase()
                _pl.log.info(
                    "Spawn-heartbeat #%d (mission still running) — %r (%s)",
                    beat, phrase, lang,
                )
                try:
                    await self._bus.publish(
                        _pl.AnnouncementRequested(
                            text=phrase,
                            language=lang,
                            priority="normal",
                            # "progress" = droppable when stale: if the user
                            # holds the floor when this lands, _on_announcement
                            # DROPS it (never defers/replays a stale "still on
                            # it" after the user finishes or after the answer).
                            kind="progress",
                        )
                    )
                except Exception:  # noqa: BLE001
                    _pl.log.warning(
                        "Spawn-heartbeat: AnnouncementRequested publish failed",
                        exc_info=True,
                    )
        finally:
            # Self-remove on every exit. _on_background_completed may have
            # already popped this task (FIFO cancel) — remove() is then a
            # harmless no-op (ValueError swallowed).
            me = asyncio.current_task()
            try:
                self._spawn_watchdog_tasks.remove(me)
            except ValueError:
                pass

    def _cancel_spawn_heartbeats(self) -> None:
        """Cancel every pending spawn heartbeat.

        Called when a mission delivers its actual answer (a readback —
        ``kind="completion"`` or ``kind="subagent"``) so Jarvis never says "still
        on it" right AFTER the result. The
        success path does not publish ``JarvisAgentBackgroundCompleted``, so the
        heartbeat is otherwise only drained by its own cap; this is the precise
        hook that silences it the moment the answer lands. Each cancelled task
        still self-removes from ``_spawn_watchdog_tasks`` in its ``finally``.
        """
        tasks = getattr(self, "_spawn_watchdog_tasks", None)
        if not tasks:
            return
        for task in list(tasks):
            if not task.done():
                task.cancel()
