"""Boot-time recovery: seal, reattach and resume the turns a restart cut off."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING, Any

from dodaios.agent_chat import service as _s

if TYPE_CHECKING:
    from dodaios.agent_chat.service import _Running


if TYPE_CHECKING:
    from dodaios.agent_chat.service_parts._host_state import AgentChatHostState as _HostBase
else:
    _HostBase = object


class RestoreMixin(_HostBase):
    """Boot-time recovery: seal, reattach and resume the turns a restart cut off."""

    def start_restart_recovery(self) -> None:
        """Queue the previous process's messages and waits again, on the app loop.

        Called once by the app when it builds the service; tests and tools call
        :meth:`recover_after_restart` themselves.
        """
        loop, on_loop = _s._app_loop()
        if loop is None or self._restart_recovery_task is not None:
            return
        if on_loop:
            self._restart_recovery_task = loop.create_task(
                self.recover_after_restart(), name="agent-chat-restart-recovery"
            )
        else:
            self._restart_recovery_task = asyncio.run_coroutine_threadsafe(
                self.recover_after_restart(), loop
            )

    async def recover_after_restart(self) -> None:
        """Take up the work a restart interrupted (durable queue, parked waits).

        Each part is best effort and independent: a failure is logged and never
        stops the other, nor the app.
        """
        from dodaios.agent_chat.send_queue import recover_waiting

        try:
            restored = await recover_waiting(self)
            if restored:
                _s.log.info(
                    "agent chat: %d waiting message(s) queued again after a restart", restored
                )
        except Exception:  # noqa: BLE001 - the chats recover one by one when opened
            _s.log.warning("agent chat: queue recovery failed", exc_info=True)
        try:
            await self.parked_work.rehydrate()
        except Exception:  # noqa: BLE001 - the delegates' own reports still arrive
            _s.log.warning("agent chat: parked wait recovery failed", exc_info=True)
        try:
            from dodaios.agent_chat import side_threads

            await side_threads.recover(self)
        except Exception:  # noqa: BLE001 - a side thread's own log stays readable
            _s.log.warning("agent chat: side thread recovery failed", exc_info=True)
        try:
            from dodaios.society.boot_sweep import sweep_open_jobs

            await sweep_open_jobs()
        except Exception:  # noqa: BLE001 - job_status settles a job when it is read
            _s.log.warning("agent chat: open jobs not swept", exc_info=True)

    def _seal_orphaned_turns(self) -> None:
        """Close every turn a previous process left open.

        The runner's task lives in memory, so a turn that was running when the
        app quit, crashed or was restarted can never send another event: its
        CLI's pipe went with the old process. Left open, the thread showed
        "Working" for ever and froze on the last line the old process wrote,
        while the agent's real ending never arrived (2026-10-05). This service
        is built once per process, before it runs a turn of its own, so every
        open turn here is such an orphan. It ends as failed, stamped with the
        last moment the session heard anything, so the thread list keeps its
        order. A CLI that outlived its parent is not hunted down here: a stop
        by folder would also hit the person's own terminals in that folder.

        A thread turn (surface ``agent``) is the exception: its CLI runs in
        the turn host (``turn_host_client``) and may still be working. While
        such a host or its spool exists, those turns are held as running and
        handed to :meth:`_reattach_hosted`, which carries on every one the
        host still knows and seals the rest exactly like here.
        """
        try:
            orphans = self.store.open_turns()
        except sqlite3.Error:
            _s.log.warning(
                "agent chat: could not look for turns a restart left open", exc_info=True
            )
            return
        loop, on_loop = _s._app_loop()
        if loop is None and orphans:
            _s.log.warning(
                "agent chat: built outside the app's loop, so open thread turns "
                "cannot be carried on"
            )
        hosted_possible: bool | None = None
        deferred: list[tuple[str, str, int, int]] = []
        sealed = 0
        for session_id, turn_id, started_ms, last_ms in orphans:
            if not turn_id:
                continue
            if loop is not None and self._may_be_hosted(session_id):
                if hosted_possible is None:
                    from dodaios.agent_chat import turn_host_client

                    hosted_possible = turn_host_client.may_hold_turns()
                if hosted_possible:
                    deferred.append((session_id, turn_id, started_ms, last_ms))
                    continue
            self.store.append_event(session_id, _s._orphan_event(turn_id, started_ms, last_ms))
            sealed += 1
        if sealed:
            _s.log.info("agent chat: closed %d turn(s) a restart left open", sealed)
        if deferred and loop is not None:
            for session_id, turn_id, _started, _last in deferred:
                # Held as running until the host answers: a message sent now
                # must not start a second CLI on the same conversation.
                held = _s._Running(turn_id, asyncio.Event())
                held.setup_task = None
                self._running[session_id] = held
                self._held_for_reattach.add(session_id)
            if on_loop:
                self._reattach_task = loop.create_task(
                    self._reattach_hosted(deferred), name="agent-chat-reattach"
                )
            else:
                # Built in a worker thread (a sync route): hand the work to the
                # app's loop, where every turn task of this service runs.
                self._reattach_task = asyncio.run_coroutine_threadsafe(
                    self._reattach_hosted(deferred), loop
                )

    async def wait_reattached(self) -> None:
        """Until the restart's thread turns are reattached or sealed (tests, tools)."""
        task = self._reattach_task
        if task is None:
            return
        if isinstance(task, asyncio.Future):
            await task
        else:
            await asyncio.wrap_future(task)

    def _may_be_hosted(self, session_id: str) -> bool:
        session = self.store.get_session(session_id)
        return session is not None and session.surface == "agent"

    async def _reattach_hosted(self, orphans: list[tuple[str, str, int, int]]) -> None:
        """Carry on every open thread turn whose CLI the turn host still holds."""
        try:
            await self._reattach_hosted_turns(orphans)
        except asyncio.CancelledError:
            # Shutdown mid-reattach: the turns stay open and their CLIs stay
            # in the host for the next process (``_stop_reattach``).
            raise
        except Exception:  # noqa: BLE001 — a held thread must never stay on Working
            _s.log.exception("agent chat: reattaching thread turns failed")
            for session_id, turn_id, started_ms, last_ms in orphans:
                held = self._running.get(session_id)
                if held is None or held.turn_id != turn_id or held.task is not None:
                    continue
                self._running.pop(session_id, None)
                held.ready.set()
                if self.store.turn_terminal(session_id, turn_id) is None:
                    self._publish_event(session_id, _s._orphan_event(turn_id, started_ms, last_ms))

    async def _reattach_hosted_turns(self, orphans: list[tuple[str, str, int, int]]) -> None:
        from dodaios.agent_chat import turn_host_client

        client = None
        for delay in (0.0, 5.0, 15.0, 30.0):
            if delay:
                await asyncio.sleep(delay)
            client = await turn_host_client.get_client(start=False)
            # Patience only for a host that is alive but busy; a spool alone
            # is read at once.
            if client is not None or not await asyncio.to_thread(turn_host_client.host_running):
                break
        by_turn: dict[str, Any] = {}
        if client is not None:
            for host_id, info in list(client.turns.items()):
                meta = info.get("meta") or {}
                by_turn[str(meta.get("turn_id") or "")] = ("host", host_id)
        for record in turn_host_client.read_spool():
            meta = record.get("meta") or {}
            by_turn.setdefault(str(meta.get("turn_id") or ""), ("spool", record))
        open_ids = {turn_id for _sid, turn_id, _s, _l in orphans}
        resumed = 0
        for session_id, turn_id, started_ms, last_ms in orphans:
            held = self._running.get(session_id)
            source = by_turn.get(turn_id)
            proc = None
            try:
                if source is not None and source[0] == "host" and client is not None:
                    proc = await client.attach(source[1])
                elif source is not None and source[0] == "spool":
                    proc = turn_host_client.spooled_cli(source[1])
            except (ConnectionError, OSError, ValueError, KeyError):
                _s.log.warning("agent chat: could not reattach turn %s", turn_id, exc_info=True)
                proc = None
            if proc is None or held is None or held.turn_id != turn_id:
                if held is not None and held.turn_id == turn_id and held.task is None:
                    self._running.pop(session_id, None)
                    self._held_for_reattach.discard(session_id)
                    held.ready.set()
                if self.store.turn_terminal(session_id, turn_id) is None:
                    _s.log.info(
                        "agent chat: turn %s ended by the restart (turn host %s)",
                        turn_id,
                        "does not hold it" if client is not None else "not reachable",
                    )
                    self._publish_event(session_id, _s._orphan_event(turn_id, started_ms, last_ms))
                continue
            self._held_for_reattach.discard(session_id)
            self._resume_hosted_turn(session_id, held, proc)
            resumed += 1
        # A CLI the host holds for a turn nobody has open any more (closed by
        # an older build, deleted thread) has no reader: end it.
        for turn_id, source in by_turn.items():
            if not turn_id or turn_id in open_ids:
                continue
            try:
                if source[0] == "host" and client is not None:
                    stray = await client.attach(source[1])
                    if stray is not None:
                        stray.kill()
                        stray.release()
                elif source[0] == "spool":
                    turn_host_client.spooled_cli(source[1]).release()
            except (ConnectionError, OSError, ValueError, KeyError):
                _s.log.warning("agent chat: stray hosted turn %s not ended", turn_id, exc_info=True)
        if resumed:
            _s.log.info("agent chat: carried on %d thread turn(s) across a restart", resumed)

    def _resume_hosted_turn(self, session_id: str, run: _Running, proc: Any) -> None:
        """Run the rest of a reattached thread turn as this session's task."""
        from dodaios.agent_chat.runner_cli import resume_hosted_cli_turn

        session = self.store.get_session(session_id)
        assert session is not None
        turn_id = run.turn_id
        runner = str((getattr(proc, "meta", {}) or {}).get("runner") or "")
        kit = _s.kit_for(session.surface)
        handle = _s.TurnHandle(
            session=session,
            turn_id=turn_id,
            emit=lambda ev: self._emit(session_id, ev),
            request_approval=lambda call_id, name, args, summary: self._ask(
                session_id, turn_id, call_id, name, args, summary
            ),
            cancel=run.cancel,
            history=self.store.list_events(session_id),
            assistant_name=self._assistant_name(),
            bus=self._bus(),
            surface=session.surface,
            stance=session.permission_mode if kit.uses_stance else "",
            control_service=self,
            # The CLI still reads its stdin after the restart: without this, a
            # message sent mid-turn could not reach it, and "Send now" stopped
            # the whole turn, its sub-agents with it.
            on_steer=lambda writer: self._set_steerer(session_id, turn_id, writer),
            on_conversation=lambda vendor: self._keep_conversation(session_id, vendor),
        )
        superseded = self._hold_unanswered_approvals(session_id, turn_id, handle.history)
        left_open = _s._questions_left_open(turn_id, handle.history)

        async def _carry_on() -> None:
            finished = False
            try:
                for approval_id in superseded:
                    await self._emit(
                        session_id,
                        _s.make_event(
                            "approval_resolved",
                            {"turn_id": turn_id, "approval_id": approval_id, "decision": "expired"},
                        ),
                    )
                for question_id, answers in left_open.items():
                    await self._emit(
                        session_id,
                        _s.make_event(
                            "question_resolved",
                            {"turn_id": turn_id, "question_id": question_id, "answers": answers},
                        ),
                    )
                vendor = await resume_hosted_cli_turn(handle, proc)
                finished = True
                if vendor and vendor != session.vendor_session:
                    self.store.update_session(session_id, vendor_session=vendor)
            except asyncio.CancelledError:
                if not run.detached:
                    await self._emit(
                        session_id,
                        _s.make_event(
                            "turn_finished",
                            {
                                "turn_id": turn_id,
                                "status": "cancelled",
                                "duration_ms": 0,
                                "usage": {},
                                "error": None,
                            },
                        ),
                    )
                raise
            except _s.TurnHandedOver:
                run.detached = True
                _s.log.info("agent chat turn %s handed over to another app process", turn_id)
            except Exception as exc:  # noqa: BLE001 — a runner bug must not leave the UI spinning
                _s.log.exception("agent chat: reattached turn %s crashed", turn_id)
                await self._emit(
                    session_id,
                    _s.make_event(
                        "turn_finished",
                        {
                            "turn_id": turn_id,
                            "status": "error",
                            "duration_ms": 0,
                            "usage": {},
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    ),
                )
            finally:
                if self._running.get(session_id) is run:
                    self._running.pop(session_id, None)
                for aid in self.pending_approvals(session_id):
                    fut = self._approvals.pop(aid, None)
                    self._approval_session.pop(aid, None)
                    if fut is not None and not fut.done():
                        fut.set_result("cancel")
                for key in [k for k in self._unanswered if k[:2] == (session_id, turn_id)]:
                    self._unanswered.pop(key, None)
                self._cancel_questions(session_id)
                if finished and kit.turn_prompts:
                    try:
                        await self._open_turn_prompts(session_id, turn_id, runner)
                    except Exception:  # noqa: BLE001 — a missing card leaves the reply readable
                        _s.log.exception("agent chat: end-of-turn card failed for %s", turn_id)

        run.task = asyncio.create_task(_carry_on(), name=f"agent-chat-{turn_id[:8]}")
        run.ready.set()

    def _hold_unanswered_approvals(
        self, session_id: str, turn_id: str, history: list[dict[str, Any]]
    ) -> list[str]:
        """Keep a restart's open approval cards for the CLI to ask again.

        The previous process waited on the card's answer when it quit; the CLI
        in the turn host still waits on its permission prompt, and the host
        replays that line because it was never acknowledged, so the resumed
        runner asks again. That question must reuse the card already on screen:
        a fresh id left the old card on top of the composer, and its buttons
        answered "no such pending approval" for ever (2026-10-06). The newest
        open card per tool call is held for :meth:`_ask`; the ids returned are
        older duplicates (or cards without a call id) that only get closed.
        """
        open_by_call: dict[str, list[str]] = {}
        resolved: set[str] = set()
        for event in history:
            payload = event.get("payload") or {}
            if str(payload.get("turn_id") or "") != turn_id:
                continue
            approval_id = str(payload.get("approval_id") or "")
            if not approval_id:
                continue
            if event.get("kind") == "approval_resolved":
                resolved.add(approval_id)
            elif event.get("kind") == "approval_required":
                call_id = str(payload.get("call_id") or "")
                open_by_call.setdefault(call_id, []).append(approval_id)
        superseded: list[str] = []
        for call_id, ids in open_by_call.items():
            still_open = [aid for aid in dict.fromkeys(ids) if aid not in resolved]
            if not still_open:
                continue
            if call_id:
                self._unanswered[(session_id, turn_id, call_id)] = still_open[-1]
                still_open = still_open[:-1]
            superseded.extend(still_open)
        return superseded

    def _retire_cli_seats(self) -> None:
        """Move chats off a CLI seat their surface no longer offers.

        The front page's chat runs on provider APIs only (``cli_seats``).
        A session opened before that — a Codex or Antigravity seat, or a
        Claude one carrying a Claude Code model id — would otherwise show a
        provider its own picker does not list, or send the endpoint a model
        name only the CLI understands. It moves to the API row of the same
        brand instead (``catalog.api_seat``), keeping its title, its folder,
        its permission mode and its whole transcript.

        Once per database, not once per boot (``data_version``): it rewrites
        a pick, and a pick made afterwards — a live model id the curated
        list does not carry — must survive every later start untouched.
        """
        if self.store.data_version() >= _s._CLI_SEATS_RETIRED:
            return
        for surface in _s.SURFACES:
            if _s.kit_for(surface).cli_seats:
                continue
            for row in _s.PROVIDER_ROWS:
                # Rows that were always an API seat have nothing to migrate.
                if row.runner == "api":
                    continue
                for session in self.store.sessions_on(surface, row.id):
                    provider, model = _s.api_seat(session.provider, session.model)
                    if (provider, model) == (session.provider, session.model):
                        continue
                    self.store.reseat_session(session.session_id, provider=provider, model=model)
                    _s.log.info(
                        "agent chat: %s left the %s CLI seat for %s %s",
                        session.session_id,
                        row.id,
                        provider,
                        f"({model})" if model else "(its default model)",
                    )
        self.store.set_data_version(_s._CLI_SEATS_RETIRED)
