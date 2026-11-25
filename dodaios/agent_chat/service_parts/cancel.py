"""Cancelling turns and waiting for them to end."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from dodaios.agent_chat import service as _s

if TYPE_CHECKING:
    from dodaios.agent_chat.service_parts._host_state import AgentChatHostState as _HostBase
else:
    _HostBase = object


class CancelMixin(_HostBase):
    """Cancelling turns and waiting for them to end."""

    def signal_cancel(self, session_id: str, *, expected_turn_id: str | None = None) -> bool:
        """Stop planning synchronously before releasing an in-flight tool reply."""
        run = self._running.get(session_id) or getattr(self, "_preparing", {}).get(session_id)
        if run is None or (run.task is not None and run.task.done()):
            return False
        if run.task is None and run.setup_task is _s._current_task():
            # A goal's user_message pauses its old work while preparing this
            # very send. That pause must not cancel the new send itself.
            return False
        # A resumed station must never cancel a newer unrelated conversation turn.
        if expected_turn_id is not None and run.turn_id != expected_turn_id:
            return False
        run.cancel.set()
        _s.log.info(
            "agent chat %s: turn %s told to stop by %s",
            session_id,
            run.turn_id,
            _s._stop_caller(),
        )
        if run.task is None and run.setup_task is not None:
            run.setup_task.cancel()
        for aid in self.pending_approvals(session_id):
            fut = self._approvals.get(aid)
            if fut is not None and not fut.done():
                fut.set_result("cancel")
        self._cancel_questions(session_id)
        return True

    async def cancel(self, session_id: str, *, expected_turn_id: str | None = None) -> bool:
        run = self._running.get(session_id) or self._preparing.get(session_id)
        if not self.signal_cancel(session_id, expected_turn_id=expected_turn_id):
            return False
        assert run is not None
        if run.task is None:
            try:
                await asyncio.wait_for(run.ready.wait(), timeout=15.0)
            except TimeoutError:
                # Keep the seat reserved until the cancelled setup actually
                # unwinds; releasing it here could admit a second runner.
                _s.log.warning("agent chat setup did not stop within 15 seconds: %s", session_id)
                return True
            if run.task is None:
                return True
        try:
            await asyncio.wait_for(asyncio.shield(run.task), timeout=15.0)
        except TimeoutError:  # Stop escalates to task cancellation after the bounded wait.
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
        except Exception as exc:  # noqa: BLE001 — the task reported its own end already
            _s.log.debug("agent chat cancel: task ended with %s", exc)
        return True

    async def cancel_all(self) -> None:
        """App shutdown: stop every turn — except thread turns the turn host keeps.

        Those CLIs go on working in the host; their tasks end without closing
        the turn, and the next app start carries them on (``_reattach_hosted``).
        """
        if hasattr(self, "_controls"):
            await self._controls.close()
        from dodaios.agent_chat import turn_host_client

        await self._stop_reattach()
        hosted = turn_host_client.live_turn_ids()
        detached: list[asyncio.Task[None]] = []
        for run in list(self._running.values()):
            if run.turn_id in hosted and run.task is not None and not run.task.done():
                run.detached = True
                run.task.cancel()
                detached.append(run.task)
        if detached:
            await asyncio.gather(*detached, return_exceptions=True)
            _s.log.info(
                "agent chat: %d thread turn(s) keep running in the turn host", len(detached)
            )
        turn_host_client.detach_all()
        for sid in list(dict.fromkeys([*self._running, *self._preparing])):
            await self.cancel(sid)

    async def _stop_reattach(self) -> None:
        """Shutdown while restart turns are still being reattached: leave them open.

        The background service hands the app back seconds after it booted,
        often while it still asks the turn host about the turns it found open.
        Cancelling those held turns would stop CLIs that are still working,
        and closing them showed "The app restarted" on turns the next process
        could have carried on (2026-11-09). They stay open in the store and
        the host keeps their CLIs for the next process.
        """
        task = self._reattach_task
        if task is not None and not task.done():
            task.cancel()
            waited = task if isinstance(task, asyncio.Future) else asyncio.wrap_future(task)
            await asyncio.gather(waited, return_exceptions=True)
        for session_id in list(self._held_for_reattach):
            held = self._running.get(session_id)
            if held is not None and held.task is None:
                self._running.pop(session_id, None)
                held.ready.set()
        self._held_for_reattach.clear()

    @property
    def controls(self) -> Any:
        if not hasattr(self, "_controls"):
            from dodaios.agent_chat.control import ChatControls

            self._controls = ChatControls(self)
        return self._controls

    async def wait_turn(self, session_id: str) -> None:
        run = self._running.get(session_id) or self._preparing.get(session_id)
        if run is not None and run.task is None:
            await run.ready.wait()
        if run is not None and run.task is not None:
            await asyncio.shield(run.task)
