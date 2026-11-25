"""Spoken announcements and delegation results.

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

    from dodaios.core.events import AnnouncementRequested


if TYPE_CHECKING:
    from dodaios.speech.pipeline_parts._host_state import SpeechPipelineHostState as _HostBase
else:
    _HostBase = object


class AnnouncementsMixin(_HostBase):
    """Spoken announcements and delegation results."""

    async def _on_announcement(
        self, event: AnnouncementRequested, *, cancel_heartbeats: bool = True
    ) -> None:
        """Deliver a readback through the live voice or the classic TTS path.

        Agent replies wait for an open call. Interrupt-priority announcements
        retain the existing player-stop behavior. Classic playback uses
        synthesize() and play_chunks(), the same path as ordinary answers,
        and only inside an open voice session. ``cancel_heartbeats=False``
        lets a caller that already retired its own spawn watchdog keep the
        other missions' heartbeats alive.
        """
        event_kind = getattr(event, "kind", None)
        is_readback = event_kind in _pl._READBACK_KINDS
        is_agent_reply = self._is_agent_reply(event)
        if is_readback:
            # Muting controls audio, not conversational memory. A mission that
            # finishes while muted must still be available to the next follow-up.
            session = getattr(self, "_active_realtime_handle", None)
            remember = getattr(session, "remember_announcement_context", None)
            if callable(remember):
                try:
                    # The full report too, so "what exactly did it change?"
                    # can be answered on the next turn.
                    report = str(getattr(event, "report", None) or "").strip()
                    remember(
                        text=event.text,
                        spoken_kind=event_kind,
                        detail=getattr(event, "detail", None),
                        **({"report": report} if report else {}),
                    )
                except Exception:  # noqa: BLE001 -- memory mirror is best-effort
                    _pl.log.debug(
                        "Realtime announcement context mirror failed",
                        exc_info=True,
                    )
        from dodaios.core.delegation import RESULT_SOURCES, ResultInbox

        if event.source_layer in RESULT_SOURCES:
            inbox = getattr(self, "_delegation_inbox", None)
            if inbox is None:
                inbox = self._delegation_inbox = ResultInbox()
            inbox.add(event)
            self._schedule_delegation_results()
            return
        if is_agent_reply:
            if event == getattr(self, "_agent_reply_inflight", None):
                return
            if (
                event.source_layer == "delegation.batch"
                and not self._agent_reply_floor_open()
            ):
                self._defer_agent_reply(event)
                return
            if self._agent_reply_needs_session():
                self._defer_agent_reply(event)
                _pl.log.info("Agent reply retained until an unmuted voice session is available")
                return
        if getattr(self, "_muted", False):
            _pl.log.debug("Announcement suppressed — voice muted: %r", event.text)
            return
        # Hangup-Gate: once "auflegen" fired, queued/late announcements
        # (Flash-Brain preamble, spawn-watchdog, late background readback)
        # must not punch through. The gate clears at the start of the next
        # session in `_state_loop` (line ~1726).
        hangup = getattr(self, "_hangup_event", None)
        # A readback (kind in _READBACK_KINDS — "completion" or "subagent") is a
        # FRESH turn delivering the answer the user asked for — an offloaded
        # background mission/sub-agent that finished after "auflegen" — so it must
        # punch through the hangup gate (AD-OE5/OE6 zero-silent-drop). A stale
        # preamble / untagged late announcement stays dropped. Live bug
        # 2026-06-14: a heavy research mission's result was silently dropped
        # because the user hung up 13 s after the optimistic ACK.
        # Since 2026-10-05 a readback passes this gate only to reach a live
        # call that is still open; the classic-voice gate further down keeps
        # it silent once no voice session is open.
        if hangup is not None and hangup.is_set() and not is_readback:
            _pl.log.info(
                "Announcement nach Hangup unterdrückt: %r", event.text[:80]
            )
            return
        # A completion / sub-agent readback IS the mission's answer — cancel any
        # pending "still on it" heartbeats so a reassurance never lands AFTER the
        # result (the success path does not publish JarvisAgentBackgroundCompleted,
        # so the heartbeat is not otherwise drained on completion). 2026-06-19.
        if is_readback and cancel_heartbeats:
            self._cancel_spawn_heartbeats()
        _pl.log.info(
            "📢 Announcement: %r (prio=%s lang=%s)",
            event.text, event.priority, event.language,
        )
        # When the Pre-Thinking-Ack Flash-Brain is wired in, the legacy
        # per-tool template emitter on `brain.router.ack` would double-speak:
        # the Flash-Brain already published its preamble on
        # `brain.ack_brain`, and the router's `generate_ack(tool_name, ...)`
        # callback would fire afterwards on the same utterance. Silently
        # drop the legacy source while the Flash-Brain is active so the user
        # only hears one ack per turn.
        if (
            getattr(self, "_ack_brain", None) is not None
            and getattr(event, "source_layer", None) == "brain.router.ack"
        ):
            _pl.log.debug(
                "Skipping legacy router-ack announcement %r — Flash-Brain active.",
                event.text,
            )
            return
        is_preamble = event_kind == "preamble"
        is_progress = event_kind == "progress"
        # 2026-05-26 cross-surface voice incoherence guard. After an
        # interrupt-priority announcement (typically a MissionFailed
        # readback) the user has just heard a terminal statement; a
        # follow-up "preamble" from any subscriber (Flash-Brain or
        # skill announcement) lands as an incoherent
        # second sentence — see diagnosis README. Suppress preambles
        # inside the configured quiet window.
        if is_preamble and self._last_interrupt_announcement_ts is not None:
            ack_cfg = (
                getattr(self._config, "ack_brain", None)
                if self._config is not None
                else None
            )
            quiet_ms = getattr(
                ack_cfg, "suppress_preamble_after_interrupt_ms", 5000
            )
            if quiet_ms > 0:
                elapsed = time.monotonic() - self._last_interrupt_announcement_ts
                if elapsed * 1000.0 < quiet_ms:
                    _pl.log.info(
                        "Preamble announcement suppressed — within %d ms "
                        "post-interrupt quiet window (elapsed=%.0f ms): %r",
                        quiet_ms, elapsed * 1000.0, event.text[:80],
                    )
                    return
        # Symmetric turn-boundary guard (AD-OE5) + idle guard (live bug 2026-07-01).
        # A background "still on it" heartbeat (kind="progress") is only meaningful
        # while the user is ACTIVELY in a session waiting for the mission — the mic
        # is open and Jarvis is LISTENING. It is dropped in every other state:
        # during a foreground turn (THINKING/JARVIS_SPEAKING/…) it would talk over
        # that turn, and while IDLE there is NO active session at all, so speaking
        # it is Jarvis "talking out of nowhere" into a machine the user walked away
        # from (live bug 2026-07-01: a force-spawned mission's three bounded beats
        # spoke into fresh, empty wake sessions after the user hung up). An
        # interrupt is a deliberate barge and still punches through.
        current_turn_state = (
            _pl.TurnTakingState.LISTENING if self._live_call() is not None
            else getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
        )
        if (
            event.priority != "interrupt"
            and is_progress
            and current_turn_state is not _pl.TurnTakingState.LISTENING
        ):
            _pl.log.info(
                "Progress announcement dropped — no active listening session (%s): %r",
                getattr(current_turn_state, "value", current_turn_state),
                event.text[:80],
            )
            return
        if event.priority != "interrupt" and (
            current_turn_state in _pl._USER_HOLDS_FLOOR_STATES
        ):
            # A preamble or a "still on it" heartbeat (kind="progress") is only
            # meaningful in the moment — once the user holds the floor it is
            # stale, so DROP it (never defer/replay it after the user finishes or
            # after the mission answer; events.py: progress = "droppable when
            # stale"). Completion/readback below owes the user information and is
            # deferred instead.
            if is_preamble or is_progress:
                _pl.log.info(
                    "Announcement dropped — user holds the floor (%s): %r",
                    event_kind or "normal",
                    event.text[:80],
                )
                return
            # Completion/readback owes the user information → park it and flush
            # at the next turn-boundary (AD-OE6 zero-silent-drop).
            if is_agent_reply:
                self._defer_agent_reply(event)
            else:
                self._deferred_announcements.append(event)
            _pl.log.info(
                "Announcement deferred — user holds the floor: %r",
                event.text[:80],
            )
            return
        # A preamble ("I'm about to think about this") is only coherent BEFORE
        # the answer is voiced. If the turn is already JARVIS_SPEAKING by the
        # time it reaches the handler, the answer (or another readback) is being
        # spoken right now, so the preamble is stale → drop it instead of
        # queueing it behind the answer on the shared player (live bug
        # 2026-06-20: the ack "Ich schaue mir jetzt …" played AFTER the tool
        # result). The floor guard above only covers the USER holding the floor;
        # this covers Jarvis already speaking. The remaining race — the answer
        # starting DURING the preamble's synthesis / play-lock wait — is caught
        # by the should_play predicate handed to play_chunks below.
        if is_preamble and (
            getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
            is _pl.TurnTakingState.JARVIS_SPEAKING
        ):
            _pl.log.info(
                "Preamble dropped — the assistant is already speaking the answer: %r",
                event.text[:80],
            )
            return
        # Usefulness gate (2026-07-06 interim-ack redesign): the grounded
        # router ack publishes the instant a tool is SELECTED — too early to
        # know whether the bridge is even needed. When the voice turn is
        # currently PROCESSING, hold the ack for the commit grace and only
        # speak it if the brain is STILL busy afterwards (same AD-OE5 helper
        # the Flash-Brain streaming path uses); a turn that answers within
        # the grace stays ack-free. Announcements arriving with no voice turn
        # in flight (chat path) keep legacy behavior.
        source_layer = getattr(event, "source_layer", None)
        is_instant_ack = bool(
            is_preamble and source_layer == self._INSTANT_ACK_SOURCE_LAYER
        )
        if (
            is_preamble
            and source_layer == "brain.router.ack"
            and self._interim_line_spoke_recently(_pl.PROGRESS_AFTER_S)
        ):
            # Instant acknowledgment (2026-08-17): the user just heard an
            # interim line for this turn. A second "let me check" seconds later
            # is the double-tap; the grounded router ack is welcome again only
            # once the wait has grown long enough to deserve a progress line.
            last = getattr(self, "_last_preamble_spoken", None)
            _pl.log.info(
                "Grounded ack dropped — an interim line spoke %.1fs ago: %r",
                time.monotonic() - (last[1] if last else time.monotonic()),
                event.text[:80],
            )
            return
        if (
            is_preamble
            and source_layer == "brain.router.ack"
            and getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
            is _pl.TurnTakingState.PROCESSING
        ):
            ack_cfg = getattr(getattr(self, "_config", None), "ack_brain", None)
            commit_grace_ms = int(
                getattr(ack_cfg, "grounded_ack_commit_grace_ms", 900) or 0
            )
            if commit_grace_ms > 0 and not await self._await_ack_turn_commit(
                commit_grace_ms
            ):
                _pl.log.info(
                    "Grounded ack dropped — turn left PROCESSING during the "
                    "%d ms commit grace (state=%s): %r",
                    commit_grace_ms,
                    getattr(self._turn_state, "name", self._turn_state),
                    event.text[:80],
                )
                return
        if event.priority == "interrupt":
            # Arm the quiet window BEFORE TTS so a synchronous publish of a
            # preamble immediately afterwards sees the up-to-date timestamp.
            self._last_interrupt_announcement_ts = time.monotonic()
            try:
                self._player.stop()
            except Exception as exc:  # noqa: BLE001
                _pl.log.warning("Player-Stop vor Announcement fehlgeschlagen: %s", exc)
        # Phase-1 output filter also applies to bus announcements (skill
        # output, Jarvis-Agent announce, vision privacy notices). Mandate path #2.
        # Pre-Thinking-Ack Flash-Brain (kind="preamble"): the AckGenerator
        # already ran scrub_for_voice with ack_mode=True. We still re-scrub
        # here as a safety net, but pass ack_mode=is_preamble so legitimate
        # filler-opener phrases ("Lass mich kurz nachschauen.") are
        # preserved on the second pass too.
        # Resolve the announcement's spoken language through the ONE
        # authoritative resolver — the live brain.reply_language pin and the
        # sticky conversation_language win over whatever an emitter stamped on
        # the event, and an undetectable/None tag falls back to the resolved
        # turn language, never a hardcoded German default (forensic 2026-06-23:
        # a German voice chat spoke an English "ANNOUNCEMENT" because
        # event.language was trusted verbatim). The event tag is only a hint,
        # passed where the STT tag normally goes.
        ann_lang = self._output_language(event.language, event.text or "")
        scrubbed = _pl.scrub_for_voice(
            event.text, language=ann_lang, ack_mode=is_preamble
        )
        if scrubbed.actions:
            _pl.log.info(
                "🧹 Announcement-Filter [%s]: %s (fallback=%s)",
                ann_lang, scrubbed.actions, scrubbed.fallback_used,
            )
        if _pl.is_harmless_scrub_residue(scrubbed):
            # The whole announcement was filler/honorific/markdown, so the
            # residue guard emptied it and handed back the generic error
            # phrase. Nothing failed — speaking it would report an incident
            # that never happened. Stay silent, but say so in the log.
            _pl.log.info(
                "Announcement carried no substance (%s) — staying silent "
                "instead of speaking the error phrase: %r",
                scrubbed.actions,
                (event.text or "")[:80],
            )
            return
        if not scrubbed.cleaned.strip():
            _pl.log.info("Announcement nach Filter leer — schweige.")
            return
        # Duplicate-wording safety net (2026-07-06 interim-ack redesign): no
        # emitter may speak the SAME preamble/progress line twice in quick
        # succession, regardless of source (grounded ack, Flash-Brain, skill) —
        # forensic 2026-07-05: one session spoke the identical grounded ack
        # three times. Only the ephemeral kinds are deduped;
        # completion/interrupt readbacks deliver owed answers and may repeat.
        if is_preamble or is_progress:
            dedup_cfg = getattr(getattr(self, "_config", None), "ack_brain", None)
            dedup_window_s = float(
                getattr(dedup_cfg, "preamble_dedup_window_s", 180) or 0
            )
            spoken_text = scrubbed.cleaned.strip()
            last_spoken = getattr(self, "_last_preamble_spoken", None)
            if (
                not is_instant_ack
                and dedup_window_s > 0
                and last_spoken is not None
                and last_spoken[0] == spoken_text
                and (time.monotonic() - last_spoken[1]) < dedup_window_s
            ):
                _pl.log.info(
                    "Preamble dropped — identical wording spoken %.0fs ago: %r",
                    time.monotonic() - last_spoken[1],
                    event.text[:80],
                )
                return
            # v2 anti-loop backstop: hard cap on spoken preamble/progress
            # lines per rolling 60 s window, ANY source. Kills the historical
            # "kept saying it forever" bug class at the last shared
            # chokepoint. Completion/interrupt readbacks never enter this
            # branch (owed answers are exempt).
            rate_limit = int(
                getattr(dedup_cfg, "preamble_rate_limit_per_min", 3) or 0
            )
            spoken_times = getattr(self, "_preamble_spoken_times", None)
            if spoken_times is None:
                spoken_times = _pl.deque(maxlen=32)
                self._preamble_spoken_times = spoken_times
            now_monotonic = time.monotonic()
            # The instant ack is exempt from the anti-loop cap: it is armed
            # exactly once per user utterance and cancels its predecessor, so
            # it cannot loop -- and a user issuing four commands in a minute
            # deserves four first-signs-of-life (maintainer rule 2026-08-17).
            if rate_limit > 0 and not is_instant_ack:
                recent_count = sum(
                    1 for t in spoken_times if now_monotonic - t < 60.0
                )
                if recent_count >= rate_limit:
                    _pl.log.warning(
                        "Preamble dropped — rate-limit backstop (%d spoken in "
                        "the last 60s, cap %d): %r",
                        recent_count, rate_limit, event.text[:80],
                    )
                    return
            self._last_preamble_spoken = (spoken_text, now_monotonic)
            if is_instant_ack:
                # Not counted against the cap either: one instant line must
                # never eat the budget of a later owed progress line.
                self._note_instant_ack_spoken(spoken_text, now_monotonic)
            else:
                spoken_times.append(now_monotonic)
        if await self._deliver_announcement_via_realtime(
            event,
            text=scrubbed.cleaned,
            language=ann_lang,
        ):
            return
        if self._realtime_session_owns_voice():
            # The live call rejected the delivery only because it is BUSY
            # (its delegate turn is thinking). The classic TTS voice must
            # never speak into a healthy realtime call — the user hears a
            # sudden second voice/engine (forensic 2026-07-13 17:39, the
            # wiki preamble). Ephemeral lines are stale by the time the
            # live model could speak them → drop; owed readbacks are parked
            # and replayed at the next turn boundary, where the idle live
            # model accepts them (or the call has ended and classic TTS is
            # the honest remaining surface).
            if is_preamble or is_progress:
                _pl.log.info(
                    "Announcement dropped — a live realtime call owns the "
                    "voice: %r",
                    event.text[:80],
                )
                return
            if is_agent_reply:
                self._defer_agent_reply(event)
                self._retry_agent_reply_after_boundary()
            else:
                self._deferred_announcements.append(event)
            _pl.log.info(
                "Announcement deferred — a live realtime call owns the "
                "voice: %r",
                event.text[:80],
            )
            return
        if is_agent_reply and self._agent_reply_needs_session():
            self._defer_agent_reply(event)
            return
        # The classic TTS voice speaks only inside a conversation the user
        # opened. Checked at the moment of SPEAKING, not only at arrival: the
        # user can hang up during the scrub/dedup/realtime probe above. Every
        # kind is covered — a mission, routine or sub-agent result that lands
        # while no session is open, or after a hang-up, is not voiced out of
        # nowhere (user decision 2026-10-05, replaces the AD-OE6 readback
        # punch-through). The result stays in the app and in the realtime
        # announcement memory mirrored at the top of this handler.
        if not self._classic_voice_session_open():
            if is_agent_reply:
                # Owed to the user at the next call, delivered once.
                self._defer_agent_reply(event)
                return
            _pl.log.info(
                "Announcement not spoken — no open voice session (kind=%s): %r",
                event_kind or "normal",
                event.text[:80],
            )
            return
        # Document the announcement in the session log — it is voiced through
        # this bypass path, not _speak, so it would otherwise be invisible.
        # ``detail`` carries an optional technical diagnostic (e.g. a failed
        # Computer-Use exit code + harness reason) that is NOT spoken but is
        # surfaced in the transcript for debugging.
        # A finished sub-agent / mission readback (completion / subagent) hands
        # the floor BACK to the user — drive the UI/orb into SPEAKING for its
        # duration so the mascot animates. The out-of-band announcement path
        # bypasses the turn-state machine, which is why a readback used to play
        # with no visual "Jarvis is talking" signal (2026-06-19). Only readbacks
        # animate (a preamble / progress nudge keeps its prior visual), and the
        # restore is DETERMINISTIC — IDLE once the user has hung up, else
        # LISTENING (the mic is still open). Not capturing a prior state keeps
        # this race-free against a concurrently-flushed deferred announcement.
        animate = is_readback and self._supervisor is not None
        if animate:
            await self._transition("SPEAKING")
        self._assistant_work_count = getattr(self, "_assistant_work_count", 0) + 1
        agent_reply_completed = False
        try:
            # Drive the TTS pin from the SAME resolved language as the scrub,
            # not from event.language again — a None/auto tag here used to send
            # language_code=None, which lets the multilingual TTS (Cartesia)
            # fall back to its English voice on German text (the British-accent
            # symptom; forensic 2026-06-23).
            lang_code = self._bcp47(ann_lang)
            self._register_assistant_speech(scrubbed.cleaned)
            try:
                chunks = self._tts.synthesize(scrubbed.cleaned, language_code=lang_code)
            except TypeError:
                chunks = self._tts.synthesize(scrubbed.cleaned)
            if is_preamble or is_agent_reply:
                # Staleness gate evaluated by the player right before it writes
                # audio: if the answer has started speaking by the time the
                # preamble's synthesis + play-lock wait completes, drop it so it
                # is never voiced after the answer (2026-06-20 misorder fix).
                # TypeError fallback mirrors the synthesize() compat shim above:
                # an older player / test fake without the should_play kwarg still
                # plays (the synchronous JARVIS_SPEAKING guard already covers the
                # already-speaking case; only the in-flight race is then uncovered).
                try:
                    playback_result = await self._player.play_chunks(
                        chunks,
                        should_play=lambda: (
                            not self._agent_reply_needs_session()
                            and (event.source_layer != "delegation.batch"
                                 or self._turn_state is _pl.TurnTakingState.LISTENING)
                            if is_agent_reply
                            else getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
                            is not _pl.TurnTakingState.JARVIS_SPEAKING
                        ),
                    )
                except TypeError:
                    playback_result = await self._player.play_chunks(chunks)
            else:
                playback_result = await self._player.play_chunks(chunks)
            agent_reply_completed = self._playback_confirmed(playback_result) and (
                not is_agent_reply or not self._agent_reply_needs_session()
            )
            if agent_reply_completed:
                self._emit_spoken(
                    scrubbed.cleaned,
                    ann_lang,
                    _pl._announcement_spoken_kind(getattr(event, "kind", None)),
                    getattr(event, "detail", None),
                )
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("Announcement playback failed: %s", exc)
        finally:
            if is_agent_reply and not agent_reply_completed:
                self._defer_agent_reply(event)
            self._assistant_work_count -= 1
            if animate:
                hungup = hangup is not None and hangup.is_set()
                await self._transition("IDLE" if hungup else "LISTENING")

    def _realtime_session_owns_voice(self) -> bool:
        """True while an accepted realtime call is the only valid voice.

        Provider health is deliberately irrelevant here. The handle is cleared
        only after the realtime lifecycle unwinds; until then, classic TTS must
        stay silent rather than becoming a second voice inside the same call.
        """
        return self._realtime_voice_handle() is not None

    def _classic_voice_session_open(self) -> bool:
        """True while the user is in an open classic-pipeline conversation.

        The classic TTS voice may speak an announcement only here. With no
        session (idle, hung up, or still choosing its engine), a classic
        readback would be Jarvis talking out of nowhere in a second voice;
        background results stay in the app and the conversation memory.
        """
        hangup = getattr(self, "_hangup_event", None)
        return bool(
            getattr(self, "_current_voice_session_id", None) is not None
            and not (hangup is not None and hangup.is_set())
            and not getattr(self, "_voice_engine_transitioning", False)
            and getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
            is not _pl.TurnTakingState.IDLE
        )

    def _schedule_delegation_results(self) -> None:
        """One coalescing task; a user's conversation always keeps the floor."""
        inbox = getattr(self, "_delegation_inbox", None)
        task = getattr(self, "_delegation_result_task", None)
        if (
            inbox is None or not inbox.pending
            or (task is not None and not task.done())
            or self._agent_reply_needs_session()
            or not self._agent_reply_floor_open()
            or getattr(self, "_agent_reply_inflight", None) is not None
        ):
            return
        self._delegation_result_task = asyncio.create_task(
            self._flush_delegation_results(), name="delegation-results"
        )

    async def _flush_delegation_results(self) -> None:
        from dodaios.core.delegation import BATCH_WINDOW_S

        event = None
        try:
            await asyncio.sleep(BATCH_WINDOW_S)
            if (
                self._agent_reply_needs_session()
                or not self._agent_reply_floor_open()
                or getattr(self, "_agent_reply_inflight", None) is not None
            ):
                return
            event = self._delegation_inbox.take()
            if event is not None:
                await self._on_announcement(event)
        except asyncio.CancelledError:
            if event is not None:
                self._defer_agent_reply(event)
            raise
        except Exception:
            if event is not None:
                self._defer_agent_reply(event)
            _pl.log.warning("Delegation result delivery deferred", exc_info=True)
        finally:
            self._delegation_result_task = None
            self._schedule_delegation_results()

    async def _deliver_announcement_via_realtime(
        self,
        event: AnnouncementRequested,
        *,
        text: str,
        language: str,
    ) -> bool:
        """Offer a standardized readback to the active duplex model.

        The live wrapper rejects busy, failed, or unsupported sessions. While
        the accepted realtime handle still exists, ``_on_announcement`` drops
        or defers that output; only a fully unwound call may use classic TTS.
        """
        session = self._realtime_voice_handle()
        deliver = getattr(session, "deliver_announcement", None)
        if not callable(deliver):
            return False
        agent_reply = self._is_agent_reply(event)
        browser = session is self._live_call()
        report = str(getattr(event, "report", None) or "").strip()
        if browser and agent_reply and not report:
            report = text
        receipt_capable = callable(getattr(session, "take_report_outcome", None)) and hasattr(
            session, "report_pending"
        )
        # Native handles settle on their existing audio/turn callbacks. Legacy
        # API browser handles only promise boolean acceptance, so waiting for a
        # subscription-only report receipt would strand every later handoff.
        tracked_reply = (
            (agent_reply and not browser)
            or bool(browser and receipt_capable and (agent_reply or report))
        )
        if tracked_reply:
            if getattr(self, "_agent_reply_inflight", None) is not None:
                return False
            # Register before transport I/O so fast playback cannot race acceptance.
            self._agent_reply_inflight = event
            self._agent_reply_inflight_text = text
            self._agent_reply_inflight_session = session
        accepted = False
        # The raw report goes to the live model as data to reason over; only
        # sessions that understand it are handed the keyword.
        extra: dict[str, Any] = {"report": report} if report else {}
        try:
            async def handoff() -> bool:
                return bool(await deliver(
                    text=text,
                    language=language,
                    spoken_kind=_pl._announcement_spoken_kind(
                        getattr(event, "kind", None)
                    ),
                    detail=getattr(event, "detail", None),
                    **extra,
                ))

            if browser:
                from dodaios.live.runtime import on_session_loop

                accepted = bool(await on_session_loop(session, handoff))
            else:
                accepted = await handoff()
        except Exception as exc:  # noqa: BLE001 -- classic path is load-bearing
            _pl.log.warning("Realtime announcement handoff failed: %s", exc)
            return False
        finally:
            if tracked_reply and not accepted and self._agent_reply_inflight is event:
                self._agent_reply_inflight = None
                self._agent_reply_inflight_text = ""
                self._agent_reply_inflight_session = None
        if accepted:
            _pl.log.info(
                "Announcement handed to active realtime provider %s: %r",
                getattr(self, "_active_realtime_provider", "") or "unknown",
                text[:80],
            )
        return accepted
