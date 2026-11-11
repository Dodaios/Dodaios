"""Delegated work that left its turn: the chat stays free, the result returns later.

"Brief the agent in terminal two" is answered in seconds, but the agent then
works for minutes. The turn used to stay open for all of that time, so the
next message ("and create an agent for the docs") waited behind it. Here the
waiting turn hands its seat over the moment the person sends something else:

* the turn closes with what it has said so far ("sent, it is working");
* its :class:`~dodaios.agent_chat.delegation_wait.DelegationWait` goes on
  outside the turn, reading the same local evidence, calling no model;
* when the delegates have reported, the earlier request is continued in a turn
  of its own, marked in the timeline as the result of that request;
* every turn started meanwhile is told what is still running, so it neither
  resends that work nor waits for it.

A parked request is saved in the chat database while it waits (also while its
turn still waits inside the turn), and :meth:`ParkedWorkBoard.rehydrate` rebuilds
the wait on boot: work whose evidence is durable (a society task on the board)
goes on being read, work that died with the process (a terminal pane) reports
"interrupted", and the earlier request is continued once, as before. The saved
row is removed when the continuation has been sent or the wait is stopped.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import random
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final

from dodaios.core.delegated_work import DelegatedWork, collect_delegated_work
from dodaios.core.protocols import current_chat_turn

from .delegation_wait import DelegationWait, SeatYielded, continuation_prompt

log = logging.getLogger(__name__)

__all__ = ["BACKGROUND_ORIGIN", "ParkedWork", "ParkedWorkBoard"]

#: ``origin`` of the ``user_message`` that opens a parked request's result turn.
#: Mirrored in ``components/agentchat/reduce.ts`` (parity-tested).
BACKGROUND_ORIGIN: Final[str] = "background"
#: How long a new message waits for the waiting turn to close before it queues.
_RELEASE_TIMEOUT_S: Final[float] = 10.0
#: How often finished work checks whether the chat is free for its result.
_POLL_S: Final[float] = 0.5
_REQUEST_CHARS: Final[int] = 400
#: A parked request older than this is reported as lost after a restart, not continued.
STALE_AFTER_S: Final[float] = 24 * 3600.0


@dataclass(slots=True, eq=False)
class ParkedWork:
    """One request whose delegates are still working after its turn closed."""

    turn_id: str
    #: What the person typed, for the timeline and for the model's context.
    request: str
    #: The prompt the turn ran with; its continuation needs the whole of it.
    original: str
    gate: DelegationWait
    rows: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    #: The delegates have reported; only the chat's seat is still awaited.
    reported: bool = False

    def names(self) -> list[str]:
        """Who is still working on it."""
        return [
            work.name for key, work in self.gate.work.items() if key not in self.gate.delivered
        ]


def _short(text: str) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= _REQUEST_CHARS else flat[: _REQUEST_CHARS - 1] + "…"


class ParkedWorkBoard:
    """Which turns only wait, and which requests continue in the background."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._waiting: dict[str, DelegationWait] = {}
        self._parked: dict[str, list[ParkedWork]] = {}
        #: Rebuilds a probe for saved work (tests); the default reads the society board.
        self.resolver: Callable[[str, str], Awaitable[DelegatedWork | None]] | None = None

    # -- a turn that only waits ------------------------------------------------

    @staticmethod
    def parks(session: Any) -> bool:
        """Dodaios' own chat takes several orders; an agent's one chat keeps its turn."""
        return getattr(session, "surface", "") == "jarvis"

    @contextmanager
    def waiting(self, handle: Any, gate: DelegationWait) -> Iterator[None]:
        """Mark ``handle``'s turn as only waiting for its delegates."""
        session_id = handle.session.session_id
        if not self.parks(handle.session):
            yield
            return
        self._waiting[session_id] = gate
        from .send_queue import has_waiting

        request = self._request_text(gate.original)
        turn_id = handle.turn_id
        gate.on_change = lambda: self._save(session_id, turn_id, request, gate)
        self._save(session_id, turn_id, request, gate)
        if has_waiting(self._service, session_id):
            # A message queued while the model was still answering.
            gate.yield_seat.set()
        keep = False
        try:
            yield
        except SeatYielded:
            keep = True  # carry() takes the saved row over
            raise
        except asyncio.CancelledError:
            # A stop of the person ends the wait for good; the app shutting
            # down must leave it for the next boot.
            keep = not handle.cancel.is_set()
            raise
        finally:
            if self._waiting.get(session_id) is gate:
                del self._waiting[session_id]
            if not keep:
                self._drop(session_id, turn_id)

    async def release(self, session_id: str) -> bool:
        """Free the chat for a new message if its running turn only waits.

        True once the seat is free. A turn that is still answering or running
        a tool is left alone, and the new message queues behind it as before.
        """
        gate = self._waiting.get(session_id)
        run = getattr(self._service, "_running", {}).get(session_id)
        task = getattr(run, "task", None)
        if gate is None or task is None:
            return False
        gate.yield_seat.set()
        # The seat is free as soon as the turn has let go of it; the turn's
        # own closing work may still run and is not waited for.
        deadline = asyncio.get_running_loop().time() + _RELEASE_TIMEOUT_S
        while self._service.is_running(session_id):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.wait({task}, timeout=min(0.02, remaining))
        return True

    # -- the wait outside its turn ----------------------------------------------

    def carry(
        self, handle: Any, gate: DelegationWait, original: str, rows: list[dict[str, Any]]
    ) -> ParkedWork:
        """Continue ``gate`` after its turn closed; called from inside that turn."""
        session_id = handle.session.session_id
        parked = ParkedWork(
            turn_id=handle.turn_id,
            request=self._request_text(original),
            original=original,
            gate=gate,
            rows=list(rows),
        )
        self._parked.setdefault(session_id, []).append(parked)
        gate.detached = True
        gate.on_change = lambda: self._save_parked(session_id, parked)
        self._save_parked(session_id, parked)
        # Started from the turn's own task, so the trusted turn identity that
        # late delegate registrations are checked against travels with it.
        parked.task = asyncio.create_task(
            self._carry(session_id, parked), name=f"chat-parked-{handle.turn_id[:8]}"
        )
        log.info(
            "agent chat %s: turn %s handed its seat over; %d delegate(s) continue",
            session_id, handle.turn_id, len(parked.names()),
        )
        return parked

    @staticmethod
    def _request_text(original: str) -> str:
        turn = current_chat_turn.get()
        return _short(turn.user_text if turn is not None else original)

    # -- what survives a restart ---------------------------------------------

    def _save(self, session_id: str, turn_id: str, request: str, gate: DelegationWait) -> None:
        """Write the wait to the chat database; best effort, never raises."""
        record = {
            "request": request,
            "original": gate.original,
            "work": [{"key": key, "name": work.name} for key, work in gate.work.items()],
            "delivered": sorted(gate.delivered),
            "results": gate.results,
            "reported": False,
        }
        self._write(session_id, turn_id, record)

    def _save_parked(self, session_id: str, parked: ParkedWork, *, reported: bool = False) -> None:
        gate = parked.gate
        record = {
            "request": parked.request,
            "original": parked.original,
            "work": [{"key": key, "name": work.name} for key, work in gate.work.items()],
            "delivered": sorted(gate.delivered),
            "results": parked.rows if reported else gate.results,
            "reported": reported,
        }
        self._write(session_id, parked.turn_id, record)

    def _write(self, session_id: str, turn_id: str, record: dict[str, Any]) -> None:
        if not record["work"] and not record["results"]:
            return  # nothing to wait for yet
        save = getattr(getattr(self._service, "store", None), "save_parked_work", None)
        if save is None:
            return
        try:
            save(session_id, turn_id, record)
        except Exception:  # noqa: BLE001 - the wait still runs; only a restart would lose it
            log.warning("agent chat %s: parked wait not saved", session_id, exc_info=True)

    def _drop(self, session_id: str, turn_id: str | None = None) -> None:
        drop = getattr(getattr(self._service, "store", None), "delete_parked_work", None)
        if drop is None:
            return
        try:
            drop(session_id, turn_id)
        except Exception:  # noqa: BLE001 - a stale row is dropped on the next boot's age check
            log.warning("agent chat %s: parked wait not removed", session_id, exc_info=True)

    async def rehydrate(self) -> int:
        """After a restart: take up every saved wait again. Returns how many resumed."""
        listing = getattr(getattr(self._service, "store", None), "parked_work", None)
        if listing is None:
            return 0
        try:
            records = await asyncio.to_thread(listing)
        except Exception:  # noqa: BLE001 - the delegates' own reports still arrive
            log.warning("agent chat: saved waits could not be read", exc_info=True)
            return 0
        resumed = 0
        for record in records:
            try:
                if await self._rehydrate_one(record):
                    resumed += 1
            except Exception:  # noqa: BLE001 - one broken record must not stop the others
                log.warning(
                    "agent chat: saved wait %s not resumed", record.get("turn_id"), exc_info=True
                )
        return resumed

    async def _rehydrate_one(self, record: dict[str, Any]) -> bool:
        session_id, turn_id = str(record["session_id"]), str(record["turn_id"])
        if any(item.turn_id == turn_id for item in self._parked.get(session_id, ())):
            return False  # already carried in this process
        if self._service.store.get_session(session_id) is None:
            self._drop(session_id, turn_id)
            return False
        gate = DelegationWait(_stub(turn_id, session_id))
        gate.detached = True
        gate.original = str(record["original"])
        age_s = time.time() - int(record.get("created_ms") or 0) / 1000
        if age_s > STALE_AFTER_S:
            # Old enough that the person has moved on: say so, never answer late.
            stale = ParkedWork(
                turn_id=turn_id, request=str(record["request"]), original=gate.original, gate=gate
            )
            await self._lost(session_id, stale)
            return False
        gate.delivered = {str(key) for key in record.get("delivered") or []}
        gate.results = [row for row in record.get("results") or [] if isinstance(row, dict)]
        reported = bool(record.get("reported"))
        if not reported:
            for entry in record.get("work") or []:
                key, name = str(entry.get("key") or ""), str(entry.get("name") or "")
                if key and key not in gate.delivered:
                    gate.add(await self._resolve(key, name))
        parked = ParkedWork(
            turn_id=turn_id, request=str(record["request"]), original=gate.original,
            gate=gate, rows=list(gate.results), reported=reported,
        )
        self._parked.setdefault(session_id, []).append(parked)
        gate.on_change = lambda: self._save_parked(session_id, parked)
        parked.task = asyncio.create_task(
            self._carry(session_id, parked), name=f"chat-parked-{turn_id[:8]}"
        )
        log.info("agent chat %s: wait of turn %s resumed after a restart", session_id, turn_id)
        return True

    async def _resolve(self, key: str, name: str) -> DelegatedWork:
        """A probe for saved work, read from the jobs ledger.

        The ledger rebuilds a probe where the evidence is durable (the society
        board, a mission's store) and ends the job as ``interrupted`` where it
        died with the process. Work the ledger does not know reports the same.
        """
        work: DelegatedWork | None = None
        try:
            if self.resolver is not None:
                work = await self.resolver(key, name)
            else:
                work = _ledger_work(key, name)
        except Exception:  # noqa: BLE001 - falls back to the honest "interrupted" below
            log.warning("agent chat: work %s could not be resumed", key, exc_info=True)
        return work or _interrupted_work(key, name)

    def running(self, session_id: str) -> list[ParkedWork]:
        return list(self._parked.get(session_id, ()))

    def stop(self, session_id: str) -> int:
        """Drop the chat's background waits; the delegated work itself runs on.

        Called when the chat is deleted, and for a stop pressed while no turn
        is running: then the waits are all there is to stop. A stop pressed
        during a turn stops that turn and leaves earlier requests alone.
        """
        parked = self._parked.pop(session_id, [])
        for item in parked:
            item.gate.stop.set()
        self._drop(session_id)
        return len(parked)

    def context_note(self, session_id: str) -> str:
        """What a new turn must know about requests still running behind it."""
        lines = [
            f'- "{item.request}" (working on it: {", ".join(item.names()) or "being finished"})'
            for item in self.running(session_id)
            if not item.reported
        ]
        if not lines:
            return ""
        return (
            "[Background work of this chat, for your information only. These earlier "
            "requests were handed to agents that are still working; each result arrives "
            "in this chat on its own and is then answered separately. Do not send that "
            "work again, do not wait for it, and do not report it as finished. Answer "
            "the person's message.\n" + "\n".join(lines) + "]"
        )

    async def _carry(self, session_id: str, parked: ParkedWork) -> None:
        try:
            if parked.reported:
                rows = list(parked.rows)  # a restart came after the reports
            else:
                with collect_delegated_work(parked.gate.add):
                    rows = [*parked.rows, *await parked.gate.collect()]
                parked.reported = True
                parked.rows = rows
                self._save_parked(session_id, parked, reported=True)
            if rows and parked in self._parked.get(session_id, ()):
                await self._resume(session_id, parked, rows)
            else:
                self._drop(session_id, parked.turn_id)
        except asyncio.CancelledError:
            log.info("agent chat %s: background wait of %s stopped", session_id, parked.turn_id)
            raise
        except Exception:
            log.exception("agent chat %s: background wait of %s failed", session_id, parked.turn_id)
            await self._lost(session_id, parked)
        finally:
            remaining = [item for item in self._parked.get(session_id, ()) if item is not parked]
            if remaining:
                self._parked[session_id] = remaining
            else:
                self._parked.pop(session_id, None)

    async def _resume(
        self, session_id: str, parked: ParkedWork, rows: list[dict[str, Any]]
    ) -> None:
        """Continue the earlier request once the chat has room for it."""
        from .send_queue import has_waiting
        from .service import NoSuchSession, SessionBusy

        prompt = continuation_prompt(rows, parked.original, later=True)
        while not parked.gate.stop.is_set():
            # The person's own waiting messages go first: they were typed
            # before this result existed.
            if not self._service.is_running(session_id) and not has_waiting(
                self._service, session_id
            ):
                try:
                    await self._service.send(
                        session_id, prompt, display_text=parked.request, background_result=True
                    )
                except SessionBusy:
                    pass  # Another turn took the seat first; try again shortly.
                except NoSuchSession:
                    log.info("agent chat %s was deleted before its result arrived", session_id)
                    self._drop(session_id, parked.turn_id)
                    return
                else:
                    # The request is on the timeline now; the saved wait is done.
                    self._drop(session_id, parked.turn_id)
                    return
            # Jitter only spreads the polls of several waiting results.
            await asyncio.sleep(_POLL_S + random.uniform(0, _POLL_S / 2))  # noqa: S311

    async def _lost(self, session_id: str, parked: ParkedWork) -> None:
        """Say so in the chat when a background result cannot be brought back."""
        self._drop(session_id, parked.turn_id)
        try:
            await self._service.post_notice(session_id, {
                "kind": "background_result_lost",
                "turn_id": parked.turn_id,
                "text": parked.request,
            })
        except Exception:  # noqa: BLE001 — the failure above is already logged with its cause
            log.warning("agent chat %s: lost-result notice not posted", session_id, exc_info=True)


def _stub(turn_id: str, session_id: str) -> Any:
    """The part of a turn handle a wait outside its turn reads."""
    from types import SimpleNamespace

    async def emit(_event: dict[str, Any]) -> None:
        return None

    return SimpleNamespace(
        turn_id=turn_id,
        session=SimpleNamespace(session_id=session_id),
        cancel=asyncio.Event(),
        emit=emit,
    )


def job_id_for_key(key: str) -> str | None:
    """The jobs-ledger id behind a delegated-work key (the writers' own convention)."""
    from dodaios.orchestrator import jobs

    kind, _, rest = key.partition(":")
    if kind == "society" and rest:
        return jobs.job_id_for("society_assignment", rest)
    if kind in ("mission", "artifact") and rest:
        return rest
    if kind == "team" and rest:
        return jobs.job_id_for("team_thread", rest)
    if kind == "coding":
        return jobs.job_id_for("ide_submission", key)
    if kind == "async" and rest:
        return rest
    return None


def _ledger_work(key: str, name: str) -> DelegatedWork | None:
    """Delegated work whose probe reads its row in the jobs ledger, or ``None``."""
    from dodaios.orchestrator import jobs

    job_id = job_id_for_key(key)
    if job_id is None or jobs.get_ledger().get(job_id) is None:
        return None
    # The writers register their rehydrators when imported; a boot that never
    # imported them must not read their jobs as dead.
    for module in (
        "dodaios.society.delegation_wait",
        "dodaios.orchestrator.mission_jobs",
        "dodaios.orchestrator.async_tools",
    ):
        try:
            importlib.import_module(module)
        except Exception:  # noqa: BLE001 - that kind then reports "interrupted"
            log.warning("agent chat: %s could not be loaded", module, exc_info=True)

    async def probe() -> dict[str, Any] | None:
        job = jobs.get_ledger().get(job_id)
        if job is None:
            return {"status": "interrupted", "report": f"{name}: its record is gone."}
        job = await jobs.refresh(job)
        if not job.settled:
            return {"status": "running", "progress": job.detail or job.state}
        report = job.summary or job.error or f"{name} ended as {job.state}."
        if job.kind == "async_tool":
            from dodaios.orchestrator import async_tools

            report = async_tools.report_for(job) or report
        row: dict[str, Any] = {"status": job.state, "report": report}
        if job.result_ref:
            row["result_ref"] = job.result_ref
        return row

    return DelegatedWork(key, name, probe)


def _interrupted_work(key: str, name: str) -> DelegatedWork:
    """Work that died with the previous process: it reports that, once."""

    async def probe() -> dict[str, Any] | None:
        return {
            "status": "interrupted",
            "report": (
                f"{name or 'The agent'} was still working when the app restarted. "
                "Its result was not captured. Ask again if it still matters."
            ),
        }

    return DelegatedWork(key, name, probe)
