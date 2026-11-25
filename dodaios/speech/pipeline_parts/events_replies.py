"""Event publishing and the agent-reply floor around live calls.

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

    from dodaios.core.events import AnnouncementRequested


class EventsAndRepliesMixin:
    """Event publishing and the agent-reply floor around live calls."""

    async def _emit_wake(self, keyword: str, confidence: float = 0.0) -> None:
        self._wake_detected_monotonic = time.monotonic()
        self._last_wake_keyword = keyword
        if self._bus is not None:
            try:
                await self._bus.publish(
                    _pl.WakeWordDetected(
                        source_layer="speech",
                        keyword=keyword,
                        confidence=confidence,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                _pl.log.warning("WakeWordDetected publish failed: %s", exc)

    async def _publish_event(self, event: Any) -> None:
        if self._bus is None:
            return
        try:
            await self._bus.publish(event)
        except Exception as exc:  # noqa: BLE001
            _pl.log.warning("%s publish failed: %s", type(event).__name__, exc)

    def _publish_event_soon(self, event: Any) -> None:
        """Publish from SYNCHRONOUS code without blocking the caller.

        ``start_dictation`` and the dictation teardown both have to announce
        themselves from places that cannot ``await``: a plain method, and a
        ``finally`` in a task that may already be cancelled. Scheduling the
        publish as its own task keeps both honest — a cancelled dictation still
        gets its terminal event out, and a broken subscriber can never propagate
        back into the caller (AP-18).

        A missing bus or a missing loop is a clean no-op: unit tests build
        pipelines via ``__new__`` and must not need an event bus to exercise the
        dictation lane.
        """
        if getattr(self, "_bus", None) is None:
            return

        def _spawn(loop: asyncio.AbstractEventLoop) -> None:
            # Hold a strong reference until the publish finishes: the event loop
            # only keeps a weak one, so a fire-and-forget task can be collected
            # mid-flight and the event would simply vanish.
            pending = getattr(self, "_detached_publishes", None)
            if pending is None:
                pending = set()
                self._detached_publishes = pending
            task = loop.create_task(self._publish_event(event))
            pending.add(task)
            task.add_done_callback(pending.discard)

        try:
            _spawn(asyncio.get_running_loop())
            return
        except RuntimeError:
            pass
        owner = getattr(self, "_runtime_loop", None)
        if owner is None or not owner.is_running():
            _pl.log.debug("%s not published: no running loop.", type(event).__name__)
            return
        try:
            owner.call_soon_threadsafe(_spawn, owner)
        except RuntimeError as exc:
            _pl.log.debug("%s publish scheduling failed: %s", type(event).__name__, exc)

    # ------------------------------------------------------------------
    # Skills-Brain-Integration: Phase Skills-1
    # ------------------------------------------------------------------

    @staticmethod
    def _is_agent_reply(event: AnnouncementRequested) -> bool:
        """A readback that is owed to the user but must wait for an open call.

        An agent's reply, and every piece of background news nobody asked for
        in this conversation (a routine or automation result, a scheduled job
        failing or recovering). Spoken into an idle machine it is Jarvis
        talking without having been called; held here, it is delivered at the
        next call, once, and only after the audio actually finished.
        """
        return (
            event.source_layer in _pl._HELD_FOR_CALL_SOURCES
            and event.kind in _pl._READBACK_KINDS
        )

    @staticmethod
    def _live_call() -> Any | None:
        """The browser or native live call that owns the voice right now.

        Such a call runs beside this pipeline (``dodaios.live``): the pipeline
        never sees its turns, and its handle is not ``_active_realtime_handle``.
        Owed agent replies and readbacks still have to reach it (live
        2026-10-02: Scout's report waited in silence for the whole call).
        """
        from dodaios.live.runtime import active

        return next(
            (
                session
                for session in active()
                if getattr(session, "is_active", False)
                and _pl.SpeechPipeline._is_side_call(session)
            ),
            None,
        )

    @staticmethod
    def _is_side_call(session: Any) -> bool:
        """A live call this pipeline does not drive itself.

        A desktop realtime call (``surface="desktop"``) is driven by
        ``_active_realtime_session``, which settles its replies on
        ``turn_complete``; only browser/native calls need the pause signals.
        """
        return getattr(session, "surface", "browser") != "desktop"

    def _realtime_voice_handle(self) -> Any | None:
        """The duplex session that speaks for Jarvis now, desktop or live call."""
        handle = getattr(self, "_active_realtime_handle", None)
        if handle is not None:
            return handle
        return self._live_call()

    def _agent_reply_floor_open(self) -> bool:
        """Whether an owed reply may start now without talking over anyone."""
        live = self._live_call()
        if live is not None:
            return bool(getattr(live, "ready_for_report", True))
        state = getattr(self, "_turn_state", _pl.TurnTakingState.IDLE)
        return state is _pl.TurnTakingState.LISTENING

    def _agent_reply_needs_session(self) -> bool:
        if self._live_call() is not None:
            # A live call is an open, available session of its own; its
            # pauses decide the timing (``_agent_reply_floor_open``).
            return bool(getattr(self, "_muted", False))
        hangup = getattr(self, "_hangup_event", None)
        return bool(
            getattr(self, "_muted", False)
            or (hangup is not None and hangup.is_set())
            or getattr(self, "_turn_state", _pl.TurnTakingState.IDLE) is _pl.TurnTakingState.IDLE
            or getattr(self, "_voice_engine_transitioning", False)
        )

    def _defer_agent_reply(self, event: AnnouncementRequested) -> None:
        pending = getattr(self, "_deferred_announcements", None)
        if pending is None:
            pending = self._deferred_announcements = []
        if event not in pending:
            pending.append(event)

    def _settle_agent_reply(self, *, completed: bool) -> None:
        """Only a drained speaker queue confirms a realtime agent readback."""
        event = getattr(self, "_agent_reply_inflight", None)
        self._agent_reply_inflight = None
        self._agent_reply_inflight_text = ""
        self._agent_reply_inflight_session = None
        if event is not None and not completed:
            retries = getattr(self, "_agent_reply_retries", None)
            if retries is None:
                retries = self._agent_reply_retries = []
            if event not in retries:
                retries.append(event)
            _pl.log.info("Agent reply interrupted; retained for the next voice session")

    def _restore_agent_replies(self) -> None:
        """Rejoin the existing floor-aware queue when a new call starts."""
        for event in getattr(self, "_agent_reply_retries", []):
            self._defer_agent_reply(event)
        self._agent_reply_retries = []
        pending = getattr(self, "_deferred_announcements", None)
        if pending:
            pending.sort(key=lambda event: event.timestamp_ns)

    def live_call_paused(self, session: Any) -> None:
        """Consume the receipt on the call's loop, then settle on the pipeline loop."""
        if not self._is_side_call(session):
            return
        take = getattr(session, "take_report_outcome", None)
        outcome = take() if callable(take) else ""
        self._call_on_runtime_loop(self._on_live_call_boundary, session, outcome, False)

    def live_call_ended(self, session: Any) -> None:
        if not self._is_side_call(session):
            return
        take = getattr(session, "take_report_outcome", None)
        outcome = take() if callable(take) else ""
        self._call_on_runtime_loop(self._on_live_call_boundary, session, outcome, True)

    def _call_on_runtime_loop(self, callback: Any, *args: Any) -> None:
        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None  # A native callback may arrive without an event loop.
        if owner is not None and owner.is_running() and current is not owner:
            owner.call_soon_threadsafe(callback, *args)
        elif current is not None:
            callback(*args)

    def _on_live_call_boundary(self, session: Any, outcome: str, ended: bool) -> None:
        current_live = session is self._live_call()
        session_id = str(getattr(session, "session_id", ""))
        if (
            not ended and current_live
            and getattr(self, "_live_replies_restored_for", None) != session_id
        ):
            # Restore earlier calls before settling this call's failed report;
            # that fresh failure must not immediately restart inference here.
            self._live_replies_restored_for = session_id
            self._restore_agent_replies()
        if getattr(self, "_agent_reply_inflight_session", None) is session:
            if outcome in {"completed", "failed"} or ended:
                # A failed/cancelled/unfinished report stays owed to the next
                # call. Never loop through inference merely because audio failed.
                self._settle_agent_reply(completed=outcome == "completed")
        if ended:
            return
        if not current_live:
            return
        self._schedule_delegation_results()
        if getattr(self, "_deferred_announcements", None):
            self._retry_agent_reply_after_boundary()

    def _requeue_unvoiced_reply(self, event: AnnouncementRequested) -> None:
        """A reply the live model never started stays first in line.

        Bounded per reply: a call that keeps ignoring it hands it to the next
        call instead of retrying forever. The chat notice holds it either way.
        """
        attempts = getattr(self, "_agent_reply_attempts", None)
        if attempts is None:
            attempts = self._agent_reply_attempts = {}
        key = (event.source_layer, event.trace_id, event.detail)
        attempts[key] = attempts.get(key, 0) + 1
        if attempts[key] >= _pl._LIVE_REPLY_MAX_ATTEMPTS:
            attempts.pop(key, None)
            retries = getattr(self, "_agent_reply_retries", None)
            if retries is None:
                retries = self._agent_reply_retries = []
            if event not in retries:
                retries.append(event)
            _pl.log.warning(
                "Agent reply was not voiced by the live call; retained for the next call"
            )
            return
        pending = getattr(self, "_deferred_announcements", None)
        if pending is None:
            pending = self._deferred_announcements = []
        if event not in pending:
            pending.insert(0, event)
        _pl.log.info("Agent reply was not voiced yet; offering it again at the next pause")

    def _retry_agent_reply_after_boundary(self) -> None:
        """Let the live wrapper finish resetting after the speaker drains."""
        previous = getattr(self, "_agent_reply_retry_task", None)
        if previous is not None and not previous.done():
            return
        if self._agent_reply_needs_session():
            return
        self._agent_reply_retry_task = asyncio.create_task(
            self._retry_pending_agent_replies(), name="agent-reply-boundary"
        )

    async def _retry_pending_agent_replies(self) -> None:
        while True:
            # No provider request is made while its wrapper reports busy.
            # This closes the gap between the desktop's LISTENING callback
            # and the provider wrapper clearing its completed turn state.
            await asyncio.sleep(0.1)
            if (
                self._agent_reply_needs_session()
                or not self._agent_reply_floor_open()
                or getattr(self, "_agent_reply_inflight", None) is not None
            ):
                return
            # A live call has no turn boundary this pipeline sees, so its
            # parked completion readbacks are offered at the same pauses.
            live = self._live_call() is not None
            event = next((event for event in self._deferred_announcements
                          if self._is_agent_reply(event)
                          or (live and event.kind in _pl._READBACK_KINDS)), None)
            if event is None:
                return
            self._deferred_announcements.remove(event)
            try:
                await self._on_announcement(event)
            except asyncio.CancelledError:
                self._defer_agent_reply(event)
                raise
            except Exception:
                self._defer_agent_reply(event)
                _pl.log.warning(
                    "Agent reply retry failed; retained for a later turn", exc_info=True
                )
                return
            if live and event in self._deferred_announcements:
                # The live call refused it although it reported a pause (a
                # failed send). Count it and wait for the next pause instead
                # of retrying ten times a second.
                self._deferred_announcements.remove(event)
                self._requeue_unvoiced_reply(event)
                return
