"""One desktop realtime voice session, run as a class instead of one function.

``VoicePipeline._active_realtime_session`` used to be a single 1,260-line
coroutine whose phases shared state through ``nonlocal`` closures. The same
code now lives here: the shared state is attributes of
:class:`RealtimeSessionRunner`, each phase and each provider event is one
method, and the event dispatch table is built once per session.

Nothing about the behaviour changed: same await points, same ordering, same
exception and cancellation handling, same per-chunk work on the microphone
pump. Module-level names of the pipeline (constants, ``time``, ``log``,
``level_tap`` and so on) are read through ``_pl`` at call time so the pipeline
module stays the one place that owns and patches them.
"""

from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from dodaios.core.cancellation import raise_if_cancelling
from dodaios.core.redact import safe_preview
from dodaios.sessions.constants import HANGUP_TURN_COMPLETE, SPOKEN_KIND_REPLY
from dodaios.speech import pipeline as _pl
from dodaios.speech import provider_refusal

if TYPE_CHECKING:
    from dodaios.speech.pipeline import VoicePipeline, _SessionInputBuffer

# Returned by a start-up phase that wants the next phase to run; any other
# value is the hangup reason that ends the call.
_CONTINUE: Any = object()


class RealtimeSessionRunner:
    """State and phases of one ``_active_realtime_session`` call."""

    def __init__(self, pipe: VoicePipeline, input_buffer: _SessionInputBuffer | None) -> None:
        self.pipe = pipe
        self.input_buffer = input_buffer
        self.input_chunks: Any = None
        self.session_id = ""
        self.playback: Any = None
        self.barge_detector: Any = None
        self.thinking_detector: Any = None
        self.barge_feed_executor: ThreadPoolExecutor | None = None
        self.barge_warm_task: asyncio.Task[Any] | None = None
        # The microphone must fall quiet ONCE before the thinking barge arms,
        # or the user's own trailing words would arm it against themselves.
        self.thinking_barge_quiet_since = 0.0
        # Provider PCM is owned by ``playback``; the independent surface-TTS
        # fallback used to bypass that adapter and was awaited inline. A barge
        # then stopped PortAudio but left the TTS producer alive, so its next
        # chunk reopened the stream and resumed untracked speech. Keep explicit
        # ownership of that producer so every output-cancel boundary can stop
        # generation before it aborts the shared player.
        self.surface_playback_task: asyncio.Task[Any] | None = None
        self.surface_playback_epoch = 0
        self.terminal_output_closed = False
        # A grounded surface reply that arrived while the voice was muted.
        # Held (newest wins) and re-delivered on unmute instead of being
        # silently discarded - see the error_spoken mute branch.
        self.held_muted_reply: dict[str, Any] | None = None
        self.muted_reply_flush_task: asyncio.Task[Any] | None = None
        self.turn_complete = asyncio.Event()
        self.speaking = False
        self.post_output_echo_guard_until = 0.0
        # End of the tail's physically-audible phase (device latency residue);
        # frames captured past it but still inside the echo guard are buffered
        # in ``tail_pending`` and flushed once the guard expires.
        self.post_output_hw_tail_until = 0.0
        self.tail_pending: deque[bytes] = deque()
        self.tail_pending_bytes = 0
        # The last provider refusal this attempt saw (plan / key / credit /
        # busy / unreachable), classified by dodaios.speech.provider_refusal.
        # A refusal is not a provider that might still answer: the call ends
        # and the person is told why.
        self.last_refusal: Any = None
        self.last_refused_provider = ""
        # Per-segment accumulator of the session's assistant transcript
        # deltas: registered with the PIPELINE's own text echo guard when the
        # segment closes, so a late speaker echo of realtime output is never
        # taken for the user (BUG-089).
        self.assistant_transcript_parts: list[str] = []
        # Start-up buffer and task bookkeeping (see _send_microphone).
        self.provider_ready = asyncio.Event()
        self.preroll: deque[bytes] = deque()
        self.preroll_bytes = 0
        self.wait_tasks: set[asyncio.Task[Any]] = set()
        self.reason: str | None = None
        self.session: Any | None = None
        self.microphone_task: asyncio.Task[Any] | None = None
        self.hangup_task: asyncio.Task[Any] | None = None
        self.build_task: asyncio.Task[Any] | None = None
        self.handshake_task: asyncio.Task[Any] | None = None
        self.build_started_at = 0.0
        self._build_realtime_session: Any = None
        # One table for the provider event frames, built once per session.
        self._event_handlers: dict[str, Any] = {
            "audio_starting": self._on_audio_starting,
            "language": self._on_language,
            "audio_ready": self._on_audio_ready,
            "transcript": self._on_transcript,
            "thinking": self._on_thinking,
            "provider_fallback": self._on_provider_fallback,
            "audio_failed": self._on_audio_failed,
            "tts_cancel": self._on_tts_cancel,
            "hangup": self._on_hangup,
            "output_recover": self._on_output_recover,
            "turn_complete": self._on_turn_complete,
            "error_spoken": self._on_error_spoken,
            "provider_error": self._on_provider_error,
            "provider_warning": self._on_provider_warning,
        }

    # ------------------------------------------------------------------
    # Entry point and lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> str:
        """Run the session; the return value is the hangup reason."""
        pipe = self.pipe
        handled, handover_reason = await self._browser_handover()
        if handled:
            return handover_reason or _pl.HANGUP_HOTKEY
        if not self._prepare():
            await self._announce_unavailable()
            return _pl.HANGUP_ERROR
        try:
            async with pipe._session_input_source(self.input_buffer) as input_chunks:
                self.input_chunks = input_chunks
                return await self._run_call()
        except asyncio.CancelledError:
            self.reason = "shutdown"
            raise
        except Exception as exc:  # noqa: BLE001 - the call ends with its reason
            return await self._on_session_failure(exc)
        finally:
            await self._teardown()

    async def _browser_handover(self) -> tuple[bool, str | None]:
        """Hand the call to the browser window when it owns this call.

        Returns ``(True, reason)`` when the browser call ran, else
        ``(False, None)`` and the desktop session continues.
        """
        from dodaios.realtime.factory import realtime_handshake_budget_s

        pipe = self.pipe
        config = pipe._config

        def _browser_handover_budget_s() -> float | None:
            """The hand-over budget when the browser owns this call, else ``None``.

            Both answers can read credentials (an unpinned engine is resolved
            from the keys), so they run off the voice loop together.
            """
            if not pipe._realtime_browser_audio(config):
                return None
            return realtime_handshake_budget_s(config)

        handover_budget_s = await _pl._run_voice_critical_thread(_browser_handover_budget_s)
        if handover_budget_s is not None:
            from dodaios.live.runtime import run_browser_call

            outcome: dict[str, str] = {}
            reason = await run_browser_call(
                pipe._bus,
                pipe._hangup_event,
                timeout_s=max(45.0, handover_budget_s + 5.0),
                input_buffer=self.input_buffer,
                session_id=pipe._current_voice_session_id or "",
                outcome=outcome,
            )
            if outcome.get("cause") == "timeout":
                # No window took the call. The window that would show an error
                # never saw the request, so without this the connecting state
                # ends in idle with no reason anywhere (issue #828).
                _pl.log.warning("Voice start timed out: the app window did not take the call.")
                pipe._last_realtime_start_error = {
                    "provider": "",
                    "message": (
                        "The app window did not start the voice call in time. "
                        "Open the main window and start voice again."
                    ),
                    "at": _pl.time.time(),
                }
            elif not outcome:
                pipe._last_realtime_start_error = None
            return True, reason
        return False, None

    def _prepare(self) -> bool:
        """Imports, detectors, the playback adapter and the barge-in warm-up.

        Returns ``False`` when the optional realtime stack is not installed
        (the call then ends with a notice). Everything here is synchronous, so
        no event can interleave with it.
        """
        pipe = self.pipe
        try:
            from dodaios.realtime.desktop import (
                DesktopRealtimeBargeInDetector,
                DesktopRealtimePlayback,
            )
            from dodaios.realtime.factory import build_realtime_session

            self._build_realtime_session = build_realtime_session
        except ImportError as exc:
            _pl.log.warning("Realtime desktop stack is unavailable: %s", exc)
            return False

        session_id = getattr(pipe, "_current_voice_session_id", None) or str(uuid4())
        self.session_id = session_id
        self.playback = DesktopRealtimePlayback(pipe._player)
        # ONE barge-in policy for every voice surface ([voice] barge_in; #153).
        from dodaios.speech.barge_in import profile_for as _barge_profile_for

        barge_profile = _barge_profile_for(pipe._config)
        self.barge_detector = DesktopRealtimeBargeInDetector(
            output_active=_pl.level_tap.playback_active,
            **barge_profile.detector_kwargs(),
        )
        # Per-frame Silero inference runs OFF the voice event loop - the same
        # BUG-062/BUG-084 class the old turn-based barge monitor fixed with
        # to_thread; inline it stalled playback on slow CPUs (Intel-Mac test
        # machine). ONE worker preserves frame order and the detector's
        # internal state; _run_voice_critical_thread would spawn a fresh
        # thread per frame.
        self.barge_feed_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"rt-barge-feed-{self.session_id}"
        )
        # Second detector for the SILENT wait (see the thinking-phase branch in
        # _send_microphone). A separate instance rather than a mode flag on the
        # one above: that one's state machine is keyed to a playback response
        # (start_output/stop_output per answer, per-response echo calibration),
        # and interleaving a second, differently-armed window through it would
        # corrupt the calibration the playback barge depends on.
        #
        # ``output_active=None`` is what makes it work at all: with the
        # playback probe attached, ``feed`` returns None forever while nothing
        # plays (dodaios/realtime/desktop.py - the ``_playback_started`` gate),
        # which is precisely why no detector existed for this phase. With no
        # probe the window opens on start_output(). For the same reason the
        # echo machinery is inert here and wants to be: nothing is playing, so
        # there is no echo to discriminate, and the only question left is the
        # one Silero answers - is this sustained, deliberate speech.
        #
        # The grace period drops to a token value: on the playback detector it
        # exists to collect echo for the adaptive floor, and here there is
        # none to collect. Detection strictness is unchanged (0.97 / 12 frames
        # ~= 0.4 s of speech), so a cough or a door does not take the floor.
        self.thinking_detector = DesktopRealtimeBargeInDetector(
            output_active=None, **barge_profile.detector_kwargs(grace_s=0.05)
        )
        self.barge_warm_task = asyncio.create_task(
            self._warm_barge_detector(), name=f"rt-barge-warm-{self.session_id}"
        )
        # Default: the session failed. Every genuine hangup path below
        # overwrites it.
        self.reason = _pl.HANGUP_ERROR
        return True

    async def _run_call(self) -> str:
        """Start the microphone, assemble the session, handshake, then serve."""
        # A shared capture buffer already owns and meters production
        # input, so leave it unread until the provider accepts audio.
        # The legacy direct-call path has no such producer and starts
        # its local pump immediately.
        if self.input_buffer is None:
            self.microphone_task = asyncio.create_task(
                self._send_microphone(), name=f"rt-mic-{self.session_id}"
            )

        outcome = await self._assemble_session()
        if outcome is not _CONTINUE:
            return outcome
        outcome = await self._handshake()
        if outcome is not _CONTINUE:
            return outcome
        return await self._serve_until_end()

    async def _assemble_session(self) -> Any:
        """Build the provider session off the voice loop (hangup can win)."""
        pipe = self.pipe
        self.hangup_task = asyncio.create_task(
            pipe._hangup_event.wait(), name=f"rt-hangup-{self.session_id}"
        )
        self.wait_tasks.add(self.hangup_task)
        self.build_started_at = _pl.time.monotonic()
        self.build_task = asyncio.create_task(
            _pl._run_voice_critical_thread(
                lambda: self._build_realtime_session(
                    cfg=pipe._config,
                    bus=pipe._bus,
                    session_id=self.session_id,
                    send_binary=self._send_binary,
                    send_json=self._send_json,
                    half_duplex=True,
                    surface="desktop",
                    brain=getattr(pipe, "_brain", None),
                )
            ),
            name=f"rt-build-{self.session_id}",
        )
        self.wait_tasks.add(self.build_task)
        done, _pending = await asyncio.wait(
            {self.build_task, self.hangup_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if self.hangup_task in done and pipe._hangup_event.is_set():
            self.reason = _pl.HANGUP_HOTKEY
            self.build_task.cancel()
            return _pl.HANGUP_HOTKEY
        self.session = self.build_task.result()
        build_ms = (_pl.time.monotonic() - self.build_started_at) * 1000.0
        _pl.log.info("Realtime desktop session assembled in %.0f ms.", build_ms)
        if self.session is None:
            # No provider could be built. A provider that said no on the last
            # call and was left out by the factory is named with its reason;
            # otherwise the person hears that no realtime provider is ready.
            self._remember_primary_refusal()
            _pl.log.warning("No realtime voice provider is ready; the call ends.")
            await self._announce_unavailable()
            self.reason = _pl.HANGUP_ERROR
            return _pl.HANGUP_ERROR
        # Desktop plays provider PCM through the process-local
        # AudioPlayer, whose write path stamps level_tap's playback
        # window — a PHYSICAL "audio is audible right now" probe. The
        # session's half-duplex mute release uses it so the mic stays
        # shut while the prebuffered/device-drained reply tail is
        # still audible (provider-frame silence alone reopened into
        # that tail and fed the reply back in on open speakers).
        # Capability injection: only this surface owns the player, so
        # only this surface installs the probe (getattr keeps older
        # session objects working).
        probe_setter = getattr(self.session, "set_playback_probe", None)
        if callable(probe_setter):
            probe_setter(_pl.level_tap.playback_active)
        return _CONTINUE

    async def _handshake(self) -> Any:
        """Run the provider handshake (hangup can win), then open the gate."""
        pipe = self.pipe
        handshake_started_at = _pl.time.monotonic()
        self.handshake_task = asyncio.create_task(
            self.session.handle_control({"type": "audio_start", "sample_rate": 16_000}),
            name=f"rt-handshake-{self.session_id}",
        )
        self.wait_tasks.add(self.handshake_task)
        done, _pending = await asyncio.wait(
            {self.handshake_task, self.hangup_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if self.hangup_task in done and pipe._hangup_event.is_set():
            self.reason = _pl.HANGUP_HOTKEY
            self.handshake_task.cancel()
            return _pl.HANGUP_HOTKEY
        self.handshake_task.result()
        pipe._active_realtime_handle = self.session
        _pl.log.info(
            "Realtime desktop provider handshake completed in %.0f ms (%.0f ms total startup).",
            (_pl.time.monotonic() - handshake_started_at) * 1000.0,
            (_pl.time.monotonic() - self.build_started_at) * 1000.0,
        )
        # Completed startup tasks must not remain in the live-session
        # FIRST_COMPLETED set; either would end a healthy realtime session
        # immediately.
        self.wait_tasks.discard(self.build_task)
        self.wait_tasks.discard(self.handshake_task)
        self.provider_ready.set()
        return _CONTINUE

    async def _serve_until_end(self) -> str:
        """Pump audio until hangup, provider end, turn end or failure."""
        pipe = self.pipe
        if self.microphone_task is None:
            self.microphone_task = asyncio.create_task(
                self._send_microphone(), name=f"rt-mic-{self.session_id}"
            )
        await pipe._set_turn_state(_pl.TurnTakingState.LISTENING)
        provider_task = asyncio.create_task(
            self.session.wait_finished(), name=f"rt-provider-{self.session_id}"
        )
        self.wait_tasks.update({self.microphone_task, provider_task, self.hangup_task})
        if not pipe._continue_listening_after_response:
            self.wait_tasks.add(
                asyncio.create_task(self.turn_complete.wait(), name=f"rt-turn-{self.session_id}")
            )
        done, _pending = await asyncio.wait(self.wait_tasks, return_when=asyncio.FIRST_COMPLETED)
        return await self._decide_exit(done)

    async def _decide_exit(self, done: Any) -> str:
        """Why the wait ended, in the order that matters: hangup key, voice
        hangup, single-turn end, then a provider/early failure."""
        pipe = self.pipe
        if self.hangup_task in done and pipe._hangup_event.is_set():
            self.reason = _pl.HANGUP_HOTKEY
            return _pl.HANGUP_HOTKEY
        # Voice hang-up ("auflegen" / end_call): the session ends its
        # own pump and reports the reason. Checked
        # before turn_complete: in single-turn mode both fire, and
        # voice_pattern is the more specific cause.
        session_hangup = str(getattr(self.session, "hangup_reason", "") or "")
        if session_hangup:
            self.reason = session_hangup
            return session_hangup
        if self.turn_complete.is_set():
            self.reason = HANGUP_TURN_COMPLETE
            return HANGUP_TURN_COMPLETE
        for task in done:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None:
                _pl.log.warning(
                    "Realtime desktop task ended with %s: %s",
                    type(exc).__name__,
                    exc,
                )
        # The provider ended or failed. There is no second voice path: end
        # the call and say why (the provider's refusal when it gave one).
        self.reason = _pl.HANGUP_ERROR
        _pl.log.warning("Realtime provider ended the call unexpectedly.")
        await self._announce_unavailable()
        return _pl.HANGUP_ERROR

    async def _on_session_failure(self, exc: Exception) -> str:
        """Any failure of the session ends the call with its reason."""
        pipe = self.pipe
        _pl.log.warning("Realtime desktop session failed: %s", exc)
        if self.last_refusal is None:
            refusal = provider_refusal.describe(exc)
            if refusal is not None:
                self.last_refusal = refusal
                self.last_refused_provider = self.last_refused_provider or str(
                    (pipe._last_realtime_start_error or {}).get("provider", "")
                )
                provider_refusal.remember(self.last_refused_provider, refusal)
        self.reason = _pl.HANGUP_ERROR
        await self._announce_unavailable()
        return _pl.HANGUP_ERROR

    async def _teardown(self) -> None:
        """Always-run cleanup: playback, detectors, tasks, then the session."""
        pipe = self.pipe
        if getattr(pipe, "_active_realtime_handle", None) is self.session:
            pipe._settle_agent_reply(completed=False)
            pipe._active_realtime_handle = None
        # Invalidate even when synthesis is paused before child-task
        # creation; terminal teardown must own that pre-playback window too.
        try:
            await self._cancel_output_playback(terminal=True)
        except Exception as exc:  # noqa: BLE001 -- teardown remains best-effort
            _pl.log.warning("Realtime terminal playback close failed: %s", exc)
        self.barge_detector.stop_output()
        self.barge_feed_executor.shutdown(wait=False, cancel_futures=True)
        if self.muted_reply_flush_task is not None:
            if not self.muted_reply_flush_task.done():
                self.muted_reply_flush_task.cancel()
            try:
                await self.muted_reply_flush_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - teardown
                pass
        if self.held_muted_reply is not None:
            # Honest audible-gap marker: the session ended while the voice
            # was still muted, so the grounded reply never became audible.
            # The transcript carries the text.
            _pl.log.warning(
                "Realtime session ended while voice was muted — the held "
                "reply was never audible; the transcript carries it."
            )
        if not self.barge_warm_task.done():
            self.barge_warm_task.cancel()
        try:
            await self.barge_warm_task
        except asyncio.CancelledError:
            pass
        await self._reap_session_tasks()
        await self._end_session()

    async def _reap_session_tasks(self) -> None:
        """Cancel and bound-reap the start-up, pump and provider tasks."""
        # The mic pump may not be in wait_tasks yet when the session
        # build/handshake failed — cancel it explicitly either way.
        if self.microphone_task is not None and not self.microphone_task.done():
            self.microphone_task.cancel()
        for task in self.wait_tasks:
            if not task.done():
                task.cancel()
        # Re-delivered and BOUNDED, never a bare ``await task`` (BUG-185).
        # The mic pump awaits ``wait_for`` per frame, and on Python 3.11
        # that swallows a cancel landing in the same loop step the frame
        # completes (CPython gh-86296) — live 2026-08-25 20:23: two
        # cancels eaten, this finally then awaited the pump for as long
        # as the app ran, ``_state`` never returned to IDLE, and every
        # dictation press refused ``handover_failed`` until a restart.
        # A pump that outlives the budget is abandoned here; the capture
        # context below closes its source, which ends the generator.
        for task in self.wait_tasks:
            await _pl.cancel_and_reap(
                task,
                budget_s=_pl._SESSION_TASK_REAP_BUDGET_S,
                heartbeat_s=_pl._SESSION_TASK_REAP_HEARTBEAT_S,
            )
        if self.microphone_task is not None:
            await _pl.cancel_and_reap(
                self.microphone_task,
                budget_s=_pl._SESSION_TASK_REAP_BUDGET_S,
                heartbeat_s=_pl._SESSION_TASK_REAP_HEARTBEAT_S,
            )

    async def _end_session(self) -> None:
        """Bounded ``session.end`` and the last playback close."""
        if self.session is not None:
            # Defense in depth around the two bounded closes inside end()
            # (provider socket 5 s + turn-completed 3 s): should end() ever
            # stall anywhere else, this outer bound still frees the realtime
            # finally so the supervisor reaches its own IDLE teardown —
            # returning _state to IDLE (wake re-arms) and publishing the
            # SystemStateChanged(IDLE) that repaints the JarvisBar. Without
            # it a single unbounded await here strands the session ACTIVE.
            try:
                await asyncio.wait_for(self.session.end(reason=self.reason), timeout=8.0)
            except TimeoutError:
                _pl.log.warning(
                    "Realtime session.end() timed out during teardown; "
                    "forcing the supervisor back to idle so wake re-arms."
                )
            except Exception as exc:  # noqa: BLE001 — teardown best-effort
                _pl.log.warning("Realtime session.end() failed: %s", exc)
        # ``session.end`` quiesces the provider pump. Close once more to
        # collect any callback that had already crossed the surface
        # boundary when terminal teardown began. ``close`` is idempotent
        # and permanently rejects later audio.
        try:
            await self._cancel_output_playback(terminal=True)
        except Exception as exc:  # noqa: BLE001 -- teardown remains best-effort
            _pl.log.warning("Realtime final playback cleanup failed: %s", exc)

    # ------------------------------------------------------------------
    # Refusal bookkeeping
    # ------------------------------------------------------------------

    async def _announce_refusal(self, continued_on: str) -> str:
        """Announce the remembered refusal; returns the sentence, ``""`` if none."""
        pipe = self.pipe
        if self.last_refusal is None:
            return ""
        refusal, self.last_refusal = self.last_refusal, None
        return await provider_refusal.announce(
            pipe._bus,
            session_id=self.session_id,
            provider=self.last_refused_provider,
            refusal=refusal,
            language=_pl._phrase_lang(pipe._output_language(None, "")),
            continued_on=continued_on,
        )

    async def _announce_unavailable(self) -> None:
        """Tell the person why the call ended: the refusal, or no provider.

        Spoken through the notice voice when the call owns the speaker; a
        capture-first session (its microphone is live) shows it instead, so
        the notice is never recorded as the user's own speech.
        """
        pipe = self.pipe
        text = await self._announce_refusal(provider_refusal.CONTINUED_NONE)
        await pipe._notify_voice_unavailable(text, spoken=self.input_buffer is None)

    def _remember_primary_refusal(self) -> None:
        """Pick up a remembered refusal of the configured primary provider."""
        pipe = self.pipe
        realtime_cfg = getattr(getattr(pipe._config, "brain", None), "realtime", None)
        primary = str(getattr(realtime_cfg, "provider", "") or "").strip()
        refusal = provider_refusal.fresh_refusal(primary) if primary else None
        if refusal is not None and self.last_refusal is None:
            self.last_refusal, self.last_refused_provider = refusal, primary

    # ------------------------------------------------------------------
    # Output segments, playback and the echo tail
    # ------------------------------------------------------------------

    def _reported_output_latency_s(self) -> float:
        pipe = self.pipe
        try:
            latency = float(getattr(pipe._player, "output_latency_s", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return min(_pl._REALTIME_OUTPUT_LATENCY_CAP_S, max(0.0, latency))

    def _reported_input_latency_s(self) -> float:
        try:
            from dodaios.audio.capture import (  # noqa: PLC0415
                last_input_latency_s,
            )

            return max(0.0, float(last_input_latency_s()))
        except Exception:  # noqa: BLE001 - a missing figure only costs margin
            _pl.log.debug(
                "Capture latency unavailable; echo tail keeps its fixed margin only",
                exc_info=True,
            )
            return 0.0

    def _clear_tail_pending(self) -> None:
        self.tail_pending.clear()
        self.tail_pending_bytes = 0

    def _close_output_segment(self, *, preserve_echo_tail: bool) -> None:
        """Keep half-duplex protection through physical speaker drain."""
        pipe = self.pipe
        was_audible = self.speaking or bool(self.assistant_transcript_parts)
        self.speaking = False
        # The provider queue has drained here, but a persistent PortAudio
        # stream may still hold up to one reported device-latency of audio.
        # Include that hardware horizon before the ordinary acoustic tail.
        if self.assistant_transcript_parts:
            pipe._register_assistant_speech(" ".join(self.assistant_transcript_parts))
            self.assistant_transcript_parts.clear()
        elif was_audible:
            pipe._touch_assistant_speech_activity()
        if preserve_echo_tail:
            output_latency_s = self._reported_output_latency_s()
            # A frame handed to us now was RECORDED one capture latency
            # ago, so the audible phase reaches that much further back.
            # Without it the guard released frames still carrying the
            # assistant's own voice, the provider heard itself, and the
            # model answered its own last sentence.
            input_latency_s = self._reported_input_latency_s()
            audible_s = output_latency_s + input_latency_s + _pl._REALTIME_HW_ECHO_TAIL_MARGIN_S
            # Never end the tail before the audible phase it protects; on a
            # slow capture path that simply leaves nothing to buffer, which
            # is correct - those frames are echo, not the user.
            guard_s = max(
                _pl._REALTIME_POST_OUTPUT_ECHO_GUARD_S + output_latency_s,
                audible_s,
            )
            now = _pl.time.monotonic()
            self.post_output_echo_guard_until = now + guard_s
            self.post_output_hw_tail_until = now + audible_s
            _pl.log.info(
                "Realtime echo tail armed for %.3fs (device output latency "
                "%.3fs, capture latency %.3fs, audible phase %.3fs).",
                guard_s,
                output_latency_s,
                input_latency_s,
                audible_s,
            )
            return
        self.post_output_echo_guard_until = 0.0
        self.post_output_hw_tail_until = 0.0
        self._clear_tail_pending()
        self.barge_detector.stop_output()

    async def _warm_barge_detector(self) -> None:
        try:
            await _pl._run_voice_critical_thread(self.barge_detector.warmup)
            # BOTH detectors, or the thinking-phase one is silently dead:
            # ``feed`` returns None while ``_ready`` is false, so an
            # unwarmed detector looks exactly like a room that never
            # speaks. They share the bundled ONNX model, so the second
            # warmup is a cache hit, not a second load.
            await _pl._run_voice_critical_thread(self.thinking_detector.warmup)
        except Exception as exc:  # noqa: BLE001 -- voice still works without local VAD
            _pl.log.warning(
                "Realtime desktop barge-in detector unavailable; continuing half-duplex: %s",
                exc,
            )

    async def _cancel_output_playback(self, *, terminal: bool = False) -> None:
        """Cancel surface generation and provider playback as one unit."""

        if terminal:
            self.terminal_output_closed = True
        # Invalidate the parent callback before cancelling its child. A new
        # surface fallback may start while the old callback is unwinding;
        # only the newest epoch may close the shared speaking segment.
        self.surface_playback_epoch += 1
        surface_task = self.surface_playback_task
        self.surface_playback_task = None
        if surface_task is not None and not surface_task.done():
            # Cancel before AudioPlayer.stop(): a blocked native write can
            # still unwind after the abort, but the owning coroutine can no
            # longer advance its async generator and reopen the stream.
            surface_task.cancel()
        if terminal:
            await self.playback.close()
        else:
            await self.playback.cancel()
        if surface_task is not None:
            await asyncio.gather(surface_task, return_exceptions=True)

    async def _flush_held_reply_on_unmute(self) -> None:
        """Deliver the held grounded reply the moment the user unmutes.

        Polling the mute flag keeps this free of bus subscriptions and
        Tk-thread marshalling; 200 ms is well under the human threshold
        for "it answered when I unmuted". Replaying through ``_send_json``
        re-runs the full error_spoken contract (epoch cancel, echo-guard
        registration, mode-separated TTS resolve) — and if the user
        re-muted in the gap, the reply is simply held again.
        """
        pipe = self.pipe
        while getattr(pipe, "_muted", False):
            if self.terminal_output_closed:
                return
            await asyncio.sleep(0.2)
        pending, self.held_muted_reply = self.held_muted_reply, None
        if pending is None or self.terminal_output_closed:
            return
        _pl.log.info("Voice unmuted — delivering the held realtime reply now.")
        await self._send_json(pending)

    def _hold_muted_surface_reply(self, message: dict[str, Any], cleaned: str) -> None:
        self.held_muted_reply = dict(message)
        _pl.log.warning(
            "Realtime surface reply arrived while voice is muted — "
            "holding %d chars for delivery on unmute instead of "
            "dropping the answer.",
            len(cleaned),
        )
        if self.muted_reply_flush_task is None or self.muted_reply_flush_task.done():
            self.muted_reply_flush_task = asyncio.create_task(
                self._flush_held_reply_on_unmute(),
                name=f"rt-muted-reply-flush-{self.session_id}",
            )

    async def _send_binary(self, pcm: bytes) -> None:
        pipe = self.pipe
        if self.terminal_output_closed:
            return
        if not self.speaking:
            self.post_output_echo_guard_until = 0.0
            self.post_output_hw_tail_until = 0.0
            # Frames buffered during the previous turn's tail belong to a
            # user moment the provider has already moved past; uploading
            # them under fresh assistant output would interleave stale
            # audio into the new turn.
            self._clear_tail_pending()
            self.speaking = True
            self.barge_detector.start_output()
            await pipe._set_turn_state(_pl.TurnTakingState.JARVIS_SPEAKING)
        if self.terminal_output_closed:
            return
        await self.playback.send_binary(pcm)

    # ------------------------------------------------------------------
    # Provider event frames (send_json): one method per kind
    # ------------------------------------------------------------------

    async def _send_json(self, message: dict[str, Any]) -> None:
        """Dispatch one provider frame; unknown kinds are ignored."""
        handler = self._event_handlers.get(str(message.get("type", "")))
        if handler is not None:
            await handler(message)

    async def _on_audio_starting(self, message: dict[str, Any]) -> None:
        # The provider handshake is ABOUT to run and can legitimately
        # take tens of seconds. Until this arrived, the session was
        # accepted into LISTENING (see the activation path) and nothing
        # touched that again until the transport was up — so the bar,
        # the orb and the web UI all claimed the user was being heard
        # while the provider had not accepted a single frame (ST-7).
        pipe = self.pipe
        pipe._active_realtime_language = str(message.get("language", "") or "")
        _pl.log.info(
            "Realtime desktop session starting: provider=%s language=%s budget=%ss",
            message.get("provider", "unknown"),
            pipe._active_realtime_language or "unknown",
            message.get("handshake_budget_s", "unknown"),
        )
        # SupervisorState.CONNECTING exists since the 2026-08-06
        # campaign; the surfaces show a live "connecting" look for
        # the whole handshake instead of freezing on their previous
        # state (the WARN branch that used to sit here is retired).
        await pipe._transition(_pl._REALTIME_CONNECTING_STATE)

    async def _on_language(self, message: dict[str, Any]) -> None:
        # Mid-call language flip from the ONE resolver. Recorded so the
        # surface can label the call honestly; never re-derived here.
        pipe = self.pipe
        pipe._active_realtime_language = str(message.get("language", "") or "")
        _pl.log.info(
            "Realtime desktop call language: %s",
            pipe._active_realtime_language or "unknown",
        )

    async def _on_audio_ready(self, message: dict[str, Any]) -> None:
        pipe = self.pipe
        if self.speaking:
            # A transport that just completed its handshake cannot be
            # mid-output: an open segment here is stale state from
            # before an in-place rebuild whose dead turn never sent
            # its turn_complete. Left open, the echo guard feeds
            # every microphone frame only to the local barge-in
            # detector and the rebuilt session hears nothing
            # (BUG-085). Drain politely first so a salvaged audio
            # tail keeps its last words.
            await self.playback.finish_turn()
            self._close_output_segment(preserve_echo_tail=True)
            await pipe._set_turn_state(_pl.TurnTakingState.LISTENING)
        self.playback.set_sample_rate(int(message.get("output_sample_rate", 24_000) or 24_000))
        pipe._active_realtime_provider = str(message.get("provider", "") or "")
        pipe._active_realtime_model = str(message.get("model", "") or "")
        pipe._voice_engine_transitioning = False
        # A session is up — whatever failed on the way here is history.
        pipe._last_realtime_start_error = None
        _pl.log.info(
            "Realtime desktop session ready: provider=%s model=%s input=%sHz output=%sHz",
            message.get("provider", "unknown"),
            message.get("model", "unknown"),
            message.get("input_sample_rate", "unknown"),
            message.get("output_sample_rate", "unknown"),
        )
        # The handshake put the machine into CONNECTING; nothing took it
        # back out. On a hosted provider that gap is under a second and
        # the next event papers over it, but a self-hosted server needs
        # seconds, and the bar sat on "connecting" for a call that was
        # already listening (field report 2026-08-06). Say the true
        # state now: from here the session hears the user.
        await pipe._transition("LISTENING")
        pipe._start_listening_cue()

    async def _on_transcript(self, message: dict[str, Any]) -> None:
        pipe = self.pipe
        role = str(message.get("role", ""))
        if role == "user" and bool(message.get("is_final", False)):
            await pipe._set_turn_state(_pl.TurnTakingState.PROCESSING)
        elif role == "assistant":
            delta = str(message.get("text", "") or "")
            if delta:
                self.assistant_transcript_parts.append(delta)

    async def _on_thinking(self, message: dict[str, Any]) -> None:
        # A short Realtime bridge sentence has finished, while the
        # delegated action continues. Drain that exact audio segment
        # before returning the taskbar/orb to THINKING. The next audio
        # delta starts a fresh SPEAKING segment through _send_binary.
        pipe = self.pipe
        await self.playback.finish_turn()
        self._close_output_segment(
            preserve_echo_tail=self.speaking,
        )
        await pipe._set_turn_state(_pl.TurnTakingState.PROCESSING)

    async def _on_provider_fallback(self, message: dict[str, Any]) -> None:
        """One provider failed its handshake; the call may still cross to the next family."""
        pipe = self.pipe
        # One provider's handshake failed; the session may still cross
        # to the next family. Recorded so the status surfaces can name
        # the reason if nothing comes up — audio_ready clears it.
        pipe._last_realtime_start_error = {
            "provider": str(message.get("provider", "") or ""),
            "message": str(message.get("error", "") or ""),
            "at": _pl.time.time(),
        }
        refusal = provider_refusal.describe(str(message.get("error", "") or ""))
        if refusal is not None:
            self.last_refusal = refusal
            self.last_refused_provider = str(message.get("provider", "") or "")
            provider_refusal.remember(self.last_refused_provider, refusal)
            await self._announce_refusal(provider_refusal.CONTINUED_REALTIME)

    async def _on_audio_failed(self, message: dict[str, Any]) -> None:
        # Terminal: no provider could open a session. Without this
        # branch the desktop surfaces watched the connecting window
        # expire into idle with no reason shown (live 2026-08-08).
        pipe = self.pipe
        pipe._last_realtime_start_error = {
            "provider": str(message.get("provider", "") or ""),
            "message": str(message.get("error", "") or ""),
            "at": _pl.time.time(),
        }
        refusal = provider_refusal.describe(str(message.get("error", "") or ""))
        if refusal is not None:
            self.last_refusal = refusal
            self.last_refused_provider = str(message.get("provider", "") or "")
            provider_refusal.remember(self.last_refused_provider, refusal)

    async def _on_tts_cancel(self, message: dict[str, Any]) -> None:
        pipe = self.pipe
        pipe._settle_agent_reply(completed=False)
        self._close_output_segment(preserve_echo_tail=False)
        await self._cancel_output_playback()
        await pipe._set_turn_state(_pl.TurnTakingState.LISTENING)

    async def _on_hangup(self, message: dict[str, Any]) -> None:
        pipe = self.pipe
        pipe._settle_agent_reply(completed=False)
        self._close_output_segment(preserve_echo_tail=False)
        await self._cancel_output_playback()

    async def _on_output_recover(self, message: dict[str, Any]) -> None:
        pipe = self.pipe
        recover = getattr(pipe._player, "recover_output_device", None)
        if callable(recover):
            recover()

    async def _on_turn_complete(self, message: dict[str, Any]) -> None:
        pipe = self.pipe
        playback_completed = await self.playback.finish_turn()
        interrupted_during_drain = not self.speaking
        pipe._settle_agent_reply(
            completed=bool(
                playback_completed
                and not interrupted_during_drain
                and not pipe._agent_reply_needs_session()
            )
        )
        self._close_output_segment(
            preserve_echo_tail=not interrupted_during_drain,
        )
        await pipe._set_turn_state(_pl.TurnTakingState.LISTENING)
        if not pipe._continue_listening_after_response and not interrupted_during_drain:
            self.turn_complete.set()

    async def _on_error_spoken(self, message: dict[str, Any]) -> None:
        pipe = self.pipe
        if self.terminal_output_closed:
            return
        text = str(message.get("text", "") or "").strip()
        language = _pl._phrase_lang(
            str(message.get("language", "") or "") or pipe._output_language(None, text)
        )
        scrubbed = _pl.scrub_for_voice(text, language=language)
        if _pl.is_harmless_scrub_residue(scrubbed):
            # Filler-only surface text. The residue guard turned it
            # into the generic error phrase; re-rendering that would
            # announce a failure the user does not have.
            # Only the scrub actions and the length: the filler text
            # itself stems from the provider message and carries no
            # diagnostic value worth logging.
            _pl.log.info(
                "Realtime surface fallback carried no substance (%s) "
                "— dropping it instead of speaking the error phrase "
                "(%d chars)",
                scrubbed.actions,
                len(text),
            )
            return
        cleaned = scrubbed.cleaned.strip()
        if cleaned and getattr(pipe, "_muted", False):
            # Voice muted at delivery time (orb double-double-click):
            # this is the GROUNDED answer to a question the user asked
            # while unmuted — discarding it makes the whole turn
            # inaudible with a transcript that claims Jarvis spoke
            # (live 2026-07-21 17:45: mute landed 0.5 s before the
            # surface fallback; "Tomorrow is Wednesday." was never
            # heard). Mute still means quiet NOW, so hold the reply
            # and deliver it the moment the user unmutes.
            self._hold_muted_surface_reply(message, cleaned)
            return
        surface_tts = (
            pipe._resolve_realtime_surface_tts(pipe._active_realtime_provider) if cleaned else None
        )
        if cleaned and surface_tts is None:
            # STRICT mode separation (maintainer mandate 2026-07-17):
            # a realtime session must never spend pipeline credentials
            # or speak with the pipeline's [tts] voice — not even as a
            # last resort. Without a realtime-scoped TTS the reply
            # stays TEXT-ONLY (the transcript already carries it);
            # this log line is the honest audible-gap marker.
            _pl.log.warning(
                "Realtime surface fallback has no realtime-scoped TTS "
                "for provider %r — keeping the turn text-only instead "
                "of borrowing the pipeline voice (mode separation).",
                pipe._active_realtime_provider,
            )
        if cleaned and surface_tts is not None:
            await self._render_surface_reply(message, cleaned, language, surface_tts)

    async def _on_provider_error(self, message: dict[str, Any]) -> None:
        # Only the redacted, capped error text -- never the raw
        # message dict, whose provider detail may echo a credential
        # or a provider error body (AP-34).
        _pl.log.warning(
            "Realtime desktop status: provider_error: %s",
            safe_preview(message.get("error"), max_chars=300),
        )

    async def _on_provider_warning(self, message: dict[str, Any]) -> None:
        # Recoverable: the session continues on the same provider.
        _pl.log.warning(
            "Realtime desktop provider warning: %s",
            message.get("error", ""),
        )

    async def _render_surface_reply(
        self, message: dict[str, Any], cleaned: str, language: str, surface_tts: Any
    ) -> None:
        # Realtime has already failed to render this grounded text.
        # Re-render through the REALTIME-scoped TTS (same provider
        # family + realtime credential slots + session voice —
        # strict mode separation 2026-07-17) on the same
        # AudioPlayer as an independent last mile. The existing mic
        # pump and local barge detector remain active, so this does
        # not open a second microphone or replay the user's request.
        pipe = self.pipe
        await self._cancel_output_playback()
        if self.terminal_output_closed:
            return
        self.surface_playback_epoch += 1
        active_surface_epoch = self.surface_playback_epoch
        self.speaking = True
        self.barge_detector.start_output()
        # Pre-synthesis registration mirrors _speak (BUG-084): the
        # canned phrase is about to be audible on this machine's
        # speakers, and its echo must never become a user turn
        # (BUG-089).
        pipe._register_assistant_speech(cleaned)
        await pipe._set_turn_state(_pl.TurnTakingState.JARVIS_SPEAKING)
        if self.terminal_output_closed or self.surface_playback_epoch != active_surface_epoch:
            # A cancel can arrive while the state callback yields,
            # before there is a child playback task to own. Its
            # epoch invalidates this render before synthesis starts.
            return
        try:
            # Voice-identity continuity: the realtime session names
            # the voice it was speaking with, so this last mile does
            # not flip speakers mid-conversation (Fenrir→Charon,
            # live forensic 2026-07-17 10:04). Honored only when the
            # resolved TTS actually offers that voice — a capability
            # check, never a provider pin (AP-21); no match keeps
            # the TTS's own configured voice exactly as before.
            voice_hint = str(message.get("voice", "") or "").strip() or None
            if voice_hint:
                try:
                    list_voices = getattr(surface_tts, "list_voices", None)
                    known = set(list_voices() or []) if callable(list_voices) else set()
                except Exception:  # noqa: BLE001 -- a hint must never block speech
                    known = set()
                if voice_hint not in known:
                    voice_hint = None
            lang_code = pipe._bcp47(language)
            # Pass ``voice`` only when a validated hint exists:
            # protocol-compatible TTS doubles/legacy providers
            # without that kwarg must keep their language_code
            # instead of dropping to the bare-text retry.
            synth_kwargs: dict[str, Any] = {
                "language_code": lang_code,
            }
            if voice_hint:
                synth_kwargs["voice"] = voice_hint
            try:
                chunks = surface_tts.synthesize(cleaned, **synth_kwargs)
            except TypeError:
                try:
                    chunks = surface_tts.synthesize(cleaned, language_code=lang_code)
                except TypeError:
                    chunks = surface_tts.synthesize(cleaned)
            active_surface_task = asyncio.create_task(
                pipe._player.play_chunks(
                    chunks,
                    should_play=lambda: self.surface_playback_epoch == active_surface_epoch,
                ),
                name=f"rt-surface-tts-{self.session_id}",
            )
            self.surface_playback_task = active_surface_task
            try:
                playback_result = await active_surface_task
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None and current_task.cancelling():
                    raise
                # A concurrent local barge-in cancels the owned child
                # task, not this provider-pump callback. The turn stays
                # alive and simply records no spoken receipt.
                playback_result = False
            finally:
                if self.surface_playback_task is active_surface_task:
                    self.surface_playback_task = None
            if pipe._playback_confirmed(playback_result):
                if (
                    cleaned == getattr(pipe, "_agent_reply_inflight_text", "")
                    and not pipe._agent_reply_needs_session()
                ):
                    pipe._settle_agent_reply(completed=True)
                pipe._emit_spoken(
                    cleaned,
                    language,
                    str(message.get("spoken_kind", "") or SPOKEN_KIND_REPLY),
                    detail=(str(message.get("detail", "") or "") or None),
                    tts=surface_tts,
                )
        except Exception as exc:  # noqa: BLE001 -- final voice fallback
            _pl.log.warning(
                "Realtime surface TTS fallback failed: %s",
                exc,
            )
        finally:
            if self.surface_playback_epoch == active_surface_epoch:
                self._close_output_segment(
                    preserve_echo_tail=self.speaking,
                )
                # A progress/preamble line is not the end of the
                # turn. Returning to LISTENING here made the
                # Jarvis Bar look ready while the Tool Model was
                # still running (live 2026-08-19: "I'll play
                # that" → still bars → music starts seconds
                # later). The thinking look stays until the
                # result is spoken.
                spoken_kind = str(message.get("spoken_kind", "") or "")
                await pipe._set_turn_state(
                    _pl.TurnTakingState.PROCESSING
                    if spoken_kind
                    in (
                        _pl.SPOKEN_KIND_PROGRESS,
                        _pl.SPOKEN_KIND_PREAMBLE,
                    )
                    else _pl.TurnTakingState.LISTENING
                )

    # ------------------------------------------------------------------
    # Microphone pump
    # ------------------------------------------------------------------

    def _thinking_barge_armed(self, active_session: Any, now: float) -> bool:
        owed = getattr(active_session, "owes_the_user_a_reply", None)
        if not callable(owed) or not owed():
            self.thinking_barge_quiet_since = 0.0
            return False
        speaking_now = getattr(active_session, "_user_is_speaking", None)
        if callable(speaking_now) and speaking_now():
            # Still the same utterance the provider just committed.
            self.thinking_barge_quiet_since = 0.0
            return False
        if not self.thinking_barge_quiet_since:
            self.thinking_barge_quiet_since = now
        return (now - self.thinking_barge_quiet_since) >= _pl._THINKING_BARGE_QUIET_S

    # Provider PCM is owned by ``playback``; the independent surface-TTS
    # fallback used to bypass that adapter and was awaited inline. A barge
    # then stopped PortAudio but left the TTS producer alive, so its next
    # chunk reopened the stream and resumed untracked speech. Keep explicit

    async def _flush_tail_pending(self) -> None:
        """Forward microphone audio buffered during the echo tail.

        The tail's post-audible phase holds no speaker echo by
        construction, so its frames are the user's own words (or
        room silence the provider VAD ignores). Delivering them
        late — instead of never — is what closes the post-turn
        deaf window.
        """
        if not self.tail_pending:
            return
        frames = list(self.tail_pending)
        self._clear_tail_pending()
        _pl.log.info(
            "Realtime echo tail expired; forwarding %d buffered microphone frames (%.2fs).",
            len(frames),
            sum(len(f) for f in frames) / (16_000 * 2),
        )
        for pcm in frames:
            await self.session.handle_audio_frame(pcm)

    async def _send_microphone(self) -> None:
        pipe = self.pipe
        async for chunk in pipe._session_input_stream(self.input_chunks):
            # ``handle_audio_frame`` bounds its provider send with a
            # timeout; on 3.11 that can eat the teardown's cancel
            # (BUG-185). One frame later it is honoured here.
            raise_if_cancelling()
            if not self.provider_ready.is_set():
                if self.preroll_bytes + len(chunk.pcm) > _pl._SESSION_START_BUFFER_MAX_BYTES:
                    raise RuntimeError(
                        "Realtime startup exceeded the 30-second "
                        "audio buffer; command prefix preserved, "
                        "session aborted."
                    )
                self.preroll.append(chunk.pcm)
                self.preroll_bytes += len(chunk.pcm)
                continue
            while self.preroll:
                buffered = self.preroll.popleft()
                self.preroll_bytes = max(0, self.preroll_bytes - len(buffered))
                await self.session.handle_audio_frame(buffered)
            now = _pl.time.monotonic()
            echo_guard_active = bool(self.speaking or now < self.post_output_echo_guard_until)
            if echo_guard_active:
                interrupted_pcm = await asyncio.get_running_loop().run_in_executor(
                    self.barge_feed_executor,
                    self.barge_detector.feed,
                    chunk.pcm,
                )
                if interrupted_pcm is None:
                    # Provider half-duplex remains intact: speaker
                    # echo, including the hardware playback tail,
                    # is inspected locally but never uploaded.
                    # Past the audible phase the frame cannot be
                    # echo anymore — retain it for the tail flush
                    # instead of dropping the user's first words.
                    if not self.speaking and now >= self.post_output_hw_tail_until:
                        self.tail_pending.append(chunk.pcm)
                        self.tail_pending_bytes += len(chunk.pcm)
                        while (
                            self.tail_pending_bytes > _pl._REALTIME_TAIL_PENDING_MAX_BYTES
                            and len(self.tail_pending) > 1
                        ):
                            dropped = self.tail_pending.popleft()
                            self.tail_pending_bytes -= len(dropped)
                    continue
                _pl.log.info("Realtime desktop barge-in confirmed by local CPU VAD")
                # The detector's capture supersedes the buffered
                # tail frames (they overlap its pre-speech window).
                self._clear_tail_pending()
                self.post_output_echo_guard_until = 0.0
                await self.session.handle_control({"type": "barge_in"})
                await self.session.handle_audio_frame(interrupted_pcm)
                continue
            if bool(getattr(self.barge_detector, "active", False)):
                self.barge_detector.stop_output()
            await self._flush_tail_pending()
            # THINKING-PHASE BARGE-IN. Everything above this line
            # only runs while audio plays, which is why speaking
            # over Jarvis worked and speaking over his THINKING
            # did nothing (live 2026-08-13 12:11:12: the provider
            # edge was deferred and he answered the original
            # question 11.7 s later regardless). The same Silero
            # detector, armed for the silent wait, closes that
            # hole with the mechanism that already works.
            #
            # Arming is deliberately two-condition:
            #   - the session owes a reply and nothing is audible;
            #   - the microphone has fallen quiet since the turn
            #     was committed, so the user's OWN trailing words
            #     cannot arm it against themselves (that shape is
            #     turn fragmentation, handled by the session's
            #     _user_is_speaking hold, not by a barge).
            # The frame is still uploaded either way — unlike the
            # playback branch there is no echo to withhold, and
            # the words have to reach the provider or the
            # interruption would take the floor and say nothing.
            if self._thinking_barge_armed(self.session, now):
                if not self.thinking_detector.active:
                    self.thinking_detector.start_output()
                confirmed_pcm = await asyncio.get_running_loop().run_in_executor(
                    self.barge_feed_executor,
                    self.thinking_detector.feed,
                    chunk.pcm,
                )
                if confirmed_pcm is not None:
                    _pl.log.info(
                        "Realtime desktop barge-in confirmed by "
                        "local CPU VAD while the assistant was thinking"
                    )
                    self.thinking_detector.stop_output()
                    self.thinking_barge_quiet_since = 0.0
                    await self.session.handle_control({"type": "barge_in"})
                    # The detector's own capture carries the
                    # opening syllables its confirmation consumed;
                    # uploading the raw frame too would double them.
                    await self.session.handle_audio_frame(confirmed_pcm)
                    continue
            elif self.thinking_detector.active:
                self.thinking_detector.stop_output()
            await self.session.handle_audio_frame(chunk.pcm)
