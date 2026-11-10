"""The watchdog wired to the running app: evidence readers and the repair actions.

Reads that can be done without the app's event loop (the chat store's open turns
and their tool calls) go through a read-only SQLite connection of the watchdog's
own, so a wedged loop or a held store lock cannot stop them. Everything that needs
the loop (probing a job, the society board, steering, writing the notice) goes
through :class:`LoopHop`, which gives up after a timeout and reports the loop as
unresponsive instead of waiting.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Final

from dodaios.orchestrator import jobs
from dodaios.orchestrator.watchdog import checks, supervisor
from dodaios.orchestrator.watchdog.checks import (
    ClaimView,
    Finding,
    JobView,
    RoutineView,
    SeatView,
    Snapshot,
    TurnView,
)
from dodaios.orchestrator.watchdog.store import WatchdogStore

log = logging.getLogger(__name__)

HOP_TIMEOUT_S: Final[float] = 20.0
_PING_TIMEOUT_S: Final[float] = 15.0
#: Interrupted work older than this is history, not something to bring back.
_INTERRUPTED_WINDOW_S: Final[int] = 6 * 3600
_CLAIM_WINDOW_S: Final[int] = 24 * 3600
_CLAIM_SCAN: Final[int] = 1500
_JOB_SCAN: Final[int] = 200
#: Detail words the watchdog and the person set on a job they already handled.
HANDLED_DETAILS: Final[frozenset[str]] = frozenset({"requeued", "stopped_by_person"})

#: Per job kind: ``async (job) -> new job id | None``. A kind without one is never re-queued.
Requeuer = Callable[[jobs.Job], Awaitable[str | None]]
_requeuers: dict[str, Requeuer] = {}


def register_requeuer(kind: str, requeue: Requeuer) -> None:
    _requeuers[kind] = requeue


class LoopUnresponsive(RuntimeError):
    """The app's event loop did not answer in time."""


class LoopHop:
    """Run a coroutine on the app's loop from a watchdog thread, with a deadline."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def __call__(
        self, factory: Callable[[], Awaitable[Any]], timeout: float = HOP_TIMEOUT_S
    ) -> Any:
        if self._loop.is_closed():
            raise LoopUnresponsive("the event loop is closed")

        async def run() -> Any:
            return await factory()

        future = asyncio.run_coroutine_threadsafe(run(), self._loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise LoopUnresponsive(f"no answer within {timeout:.0f} s") from None


def _signature(name: str, arguments: Any, result: Any) -> str:
    digest = hashlib.sha1(  # noqa: S324 - a fingerprint, not a secret
        json.dumps([arguments, str(result)[:600]], sort_keys=True, default=str).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:10]
    return f"{name}:{digest}"


class LiveSources:
    def __init__(self, runtime: Any, hop: LoopHop) -> None:
        self._runtime = runtime
        self._hop = hop
        self._log: list[str] = []
        self._stalled_since: float | None = None

    def drain_log(self) -> list[str]:
        lines, self._log = self._log, []
        return lines

    # ---------------------------------------------------------------- scan

    def snapshot(self, store: WatchdogStore, now: int) -> Snapshot:
        snap = Snapshot(now_ms=now)
        try:
            self._hop(_noop, _PING_TIMEOUT_S)
            self._stalled_since = None
        except LoopUnresponsive:
            if self._stalled_since is None:
                self._stalled_since = time.monotonic()
            snap.loop_ok = False
            snap.loop_stalled_s = int(time.monotonic() - self._stalled_since)
        snap.turns = self._turns(snap.loop_ok)
        if snap.loop_ok:
            snap.jobs = self._guarded(self._jobs, store, now, default=[])
            snap.claims = self._guarded(self._claims, snap.jobs, now, default=[])
            snap.routines = self._guarded(self._routines, now, default=[])
        snap.seats = self._seats()
        return snap

    def _guarded(self, read: Callable[..., Any], *args: Any, default: Any) -> Any:
        try:
            return read(*args)
        except Exception:  # noqa: BLE001 - one unreadable source never stops the others
            log.warning("watchdog: %s failed", getattr(read, "__name__", "read"), exc_info=True)
            return default

    # --------------------------------------------------------------- turns

    def _chat_db(self) -> str | None:
        service = self._runtime.chat_service()
        path = getattr(getattr(service, "store", None), "_path", "")
        return str(path) if path and path != ":memory:" else None

    def _turns(self, loop_ok: bool) -> list[TurnView]:
        path = self._chat_db()
        if path is None:
            return []
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
        except sqlite3.Error:
            log.warning("watchdog: chat store not readable", exc_info=True)
            return []
        try:
            rows = conn.execute(_OPEN_TURNS).fetchall()
            views = [(r, self._tool_signatures(conn, r[0], r[1])) for r in rows]
        except sqlite3.Error:
            log.warning("watchdog: open turns not readable", exc_info=True)
            return []
        finally:
            conn.close()
        states: dict[str, tuple[bool, bool, bool]] = {}
        if loop_ok and views:
            ids = [r[0][0] for r in views]
            try:
                states = self._hop(lambda: self._turn_states(ids))
            except LoopUnresponsive:
                states = {}
        out: list[TurnView] = []
        for (row, sigs) in views:
            sid, _seq, started, turn_id, last, surface = row
            running, steerable, waiting = states.get(sid, (None, False, False))
            out.append(TurnView(
                session_id=sid, turn_id=str(turn_id or ""), surface=str(surface or ""),
                started_ms=int(started), last_event_ms=int(last or started),
                running=running, steerable=steerable, waiting_on_person=waiting,
                tool_signatures=sigs,
            ))
        return out

    @staticmethod
    def _tool_signatures(
        conn: sqlite3.Connection, session_id: str, started_seq: int
    ) -> tuple[str, ...]:
        rows = conn.execute(
            "SELECT kind, payload FROM agent_chat_events WHERE session_id = ? AND seq > ? "
            "AND kind IN ('tool_call', 'tool_result') ORDER BY seq DESC LIMIT 160",
            (session_id, started_seq),
        ).fetchall()
        results: dict[str, Any] = {}
        calls: list[tuple[str, str, Any]] = []
        for kind, raw in reversed(rows):
            try:
                payload = json.loads(raw)
            except ValueError:
                continue
            call_id = str(payload.get("call_id") or "")
            if kind == "tool_result":
                results[call_id] = payload.get("output")
            else:
                calls.append((call_id, str(payload.get("name") or "tool"), payload.get("input")))
        return tuple(
            _signature(name, args, results.get(cid, "pending")) for cid, name, args in calls
        )

    async def _turn_states(self, ids: list[str]) -> dict[str, tuple[bool, bool, bool]]:
        service = self._runtime.chat_service()
        if service is None:
            return {}
        out: dict[str, tuple[bool, bool, bool]] = {}
        for sid in ids:
            waiting = bool(
                service.pending_approvals(sid)
                or service.pending_questions(sid)
                or service.pending_credential_requests(sid)
            )
            out[sid] = (bool(service.is_running(sid)), bool(service.can_steer(sid)), waiting)
        return out

    # ---------------------------------------------------------------- jobs

    def _jobs(self, store: WatchdogStore, now: int) -> list[JobView]:
        return self._hop(lambda: self._read_jobs(store, now))

    async def _read_jobs(self, store: WatchdogStore, now: int) -> list[JobView]:
        ledger = jobs.get_ledger()
        out: list[JobView] = []
        for job in ledger.recent(limit=_JOB_SCAN):
            if job.state == "interrupted":
                recent = now - job.updated_ms <= _INTERRUPTED_WINDOW_S * 1000
                if recent and job.detail not in HANDLED_DETAILS:
                    out.append(_view(job, job.updated_ms))
                continue
            if job.state not in jobs.OPEN_STATES:
                continue
            fingerprint, job = await self._evidence(job)
            if job.state == "interrupted":
                self._log.append(f"marked lost work interrupted: {job.title}")
                if job.detail not in HANDLED_DETAILS:
                    out.append(_view(job, now))
                continue
            since = store.track_progress(job.id, fingerprint, now=now)
            out.append(_view(job, since))
        return out

    @staticmethod
    async def _evidence(job: jobs.Job) -> tuple[str, jobs.Job]:
        """The job refreshed from its own evidence, plus a fingerprint of that evidence."""
        probe = jobs.probe_for(job.id)
        if probe is not None:
            try:
                result = await asyncio.wait_for(probe(), jobs.PROBE_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - a failed read keeps the last known state
                result = None
            fresh = jobs.get_ledger().get(job.id) or job
            if result is not None:
                key = [result.get("status"), result.get("progress"), result.get("detail")]
                return json.dumps(key, default=str), fresh
            return f"{fresh.state}|{fresh.detail}", fresh
        fresh = await jobs.refresh(job)
        return f"{fresh.state}|{fresh.detail}|{fresh.summary}", fresh

    # -------------------------------------------------------------- claims

    def _claims(self, job_views: list[JobView], now: int) -> list[ClaimView]:
        from dodaios.society.events import MsgType

        store = getattr(self._runtime, "store", None)
        if store is None:
            return []

        async def read() -> list[Any]:
            return await store.events_page(limit=_CLAIM_SCAN)

        events = self._hop(read)
        resulted = {e.trace_id for e in events if e.msg_type is MsgType.RESULT}
        tracked = {
            str(j.meta.get("trace_id") or "")
            for j in jobs.get_ledger().recent(limit=_JOB_SCAN, open_only=True)
        }
        out: list[ClaimView] = []
        seen: set[str] = set()
        for env in events:
            if env.msg_type is not MsgType.CLAIM or env.trace_id in resulted | tracked | seen:
                continue
            if now - env.ts_ms > _CLAIM_WINDOW_S * 1000:
                continue
            seen.add(env.trace_id)
            out.append(ClaimView(env.trace_id, str(env.from_agent), int(env.ts_ms)))
        return out

    # ------------------------------------------------------------ routines

    def _routines(self, now: int) -> list[RoutineView]:
        task_store = self._runtime.task_services()[0]
        if task_store is None:
            return []

        async def read() -> list[dict[str, Any]]:
            return await task_store.list("scheduled", limit=500)

        out: list[RoutineView] = []
        for row in self._hop(read):
            due_ns = row.get("due_at_ns")
            if not due_ns:
                continue
            due_ms = int(due_ns) // 1_000_000
            if due_ms < now:
                title = str(row.get("title") or "routine")
                out.append(RoutineView(str(row.get("id")), title, due_ms))
        return out

    # --------------------------------------------------------------- seats

    @staticmethod
    def _seats() -> list[SeatView]:
        try:
            from dodaios.brain import provider_health_ledger as health

            return [
                SeatView(o.provider, o.modality, o.status, int(o.at * 1000))
                for o in health.get_ledger().snapshot()
            ]
        except Exception:  # noqa: BLE001 - no health record means no seat findings
            log.debug("watchdog: provider health unreadable", exc_info=True)
            return []


_OPEN_TURNS = (
    "SELECT l.session_id, l.seq, e.ts_ms, json_extract(e.payload, '$.turn_id'), "
    "(SELECT MAX(x.ts_ms) FROM agent_chat_events x "
    " WHERE x.session_id = l.session_id AND x.kind != 'notice'), s.surface "
    "FROM (SELECT session_id, MAX(seq) AS seq FROM agent_chat_events "
    "      WHERE kind = 'turn_started' GROUP BY session_id) l "
    "JOIN agent_chat_events e ON e.session_id = l.session_id AND e.seq = l.seq "
    "LEFT JOIN agent_chat_sessions s ON s.session_id = l.session_id "
    "WHERE NOT EXISTS (SELECT 1 FROM agent_chat_events f "
    "  WHERE f.session_id = l.session_id AND f.seq > l.seq AND f.kind = 'turn_finished')"
)


async def _noop() -> None:
    return None


def _view(job: jobs.Job, progress_ms: int) -> JobView:
    return JobView(
        id=job.id, kind=job.kind, title=job.title, state=job.state,
        owner_session=job.owner_session, progress_ms=progress_ms,
        created_ms=job.created_ms, detail=job.detail,
    )


# ---------------------------------------------------------------- actions


class LiveActions:
    def __init__(
        self, runtime: Any, hop: LoopHop, config: Callable[[], Any] | None = None
    ) -> None:
        self._runtime = runtime
        self._hop = hop
        self._config = config

    def _service(self) -> Any | None:
        return self._runtime.chat_service()

    def can_repair(self, finding: Finding) -> bool:
        if finding.repair == checks.ACT_REQUEUE:
            return str(finding.evidence.get("kind") or "") in _requeuers
        return finding.repair == checks.ACT_NUDGE

    def repair(self, finding: Finding) -> str | None:
        try:
            if finding.repair == checks.ACT_NUDGE:
                sent = self._hop(lambda: self.nudge(finding.open_ref))
                return "asked the turn for a status" if sent else None
            if finding.repair == checks.ACT_REQUEUE:
                note = self._hop(lambda: self.requeue(str(finding.evidence.get("job_id"))))
                return note
        except LoopUnresponsive:
            return None
        except Exception:  # noqa: BLE001 - a failed repair becomes a notice, never a crash
            log.warning("watchdog: repair failed for %s", finding.key, exc_info=True)
        return None

    def post_notice(self, payload: dict[str, Any]) -> bool:
        async def post() -> bool:
            from dodaios.agent_chat.lead import lead_session

            service = self._service()
            if service is None:
                return False
            session = lead_session(service, create=False)
            if session is None:
                return False
            await service.post_notice(session.session_id, payload)
            return True

        try:
            return bool(self._hop(post))
        except Exception:  # noqa: BLE001 - the notice stays pending for the next scan
            log.info("watchdog: notice not posted", exc_info=True)
            return False

    def quiet_hours(self) -> bool:
        async def read() -> bool:
            from dodaios.agent_chat.proactive_settings import load_settings

            settings = await load_settings()
            if not settings.enabled:
                return False  # no waking-hours preference was set up
            try:
                from zoneinfo import ZoneInfo

                now = datetime.now(ZoneInfo(settings.timezone)) if settings.timezone \
                    else datetime.now().astimezone()
            except Exception:  # noqa: BLE001 - an unknown zone reads as local time
                now = datetime.now().astimezone()
            return not settings.from_hour <= now.hour <= settings.to_hour

        try:
            return bool(self._hop(read))
        except Exception:  # noqa: BLE001 - when unsure, say it (a missed notice is worse)
            return False

    def judge(self, goal: str, evidence: str) -> tuple[str, str] | None:
        from dodaios.orchestrator.watchdog import judge as judging

        async def run() -> Any:
            return await judging.judge(
                goal, evidence, config=self._config() if self._config else None
            )

        try:
            verdict = self._hop(run, judging.JUDGE_TIMEOUT_S + 30)
        except Exception:  # noqa: BLE001 - no verdict leaves the code checks standing
            return None
        return (verdict.verdict, verdict.reason) if verdict else None

    # The following run ON the loop (``watchdog_act`` and the repairs call them there).

    async def nudge(self, session_id: str) -> bool:
        service = self._service()
        if service is None or not session_id:
            return False
        return bool(await service.steer(session_id, supervisor.NUDGE_TEXT))

    async def stop_turn(self, session_id: str) -> bool:
        service = self._service()
        return bool(service is not None and await service.cancel(session_id))

    async def close_turn(self, session_id: str) -> bool:
        service = self._service()
        return bool(service is not None and await service.seal_stopped_turn(session_id))

    async def requeue(self, job_id: str) -> str | None:
        """Run an interrupted job's work again, once. Returns what was done, or ``None``."""
        job = jobs.get_ledger().get(job_id)
        build = _requeuers.get(job.kind) if job is not None else None
        if job is None or build is None or job.state != "interrupted":
            return None
        new_id = await build(job)
        if not new_id:
            return None
        jobs.get_ledger().update(
            job.id, detail="requeued", summary=f"The watchdog re-queued this as {new_id}."
        )
        return f"re-queued interrupted work ({job.title[:80]}) as {new_id}"

    async def mark_interrupted(self, job_id: str) -> bool:
        job = jobs.get_ledger().get(job_id)
        if job is None or job.state not in jobs.OPEN_STATES:
            return False
        jobs.get_ledger().update(
            job_id, state="interrupted", detail="stopped_by_person",
            summary="Marked interrupted from the watchdog notice.",
        )
        return True


# ----------------------------------------------------- society requeuer


async def _requeue_assignment(job: jobs.Job) -> str | None:
    """Send an interrupted assignment to its agent again, as a fresh request."""
    from dodaios.missions.ids import uuid7_str
    from dodaios.society.delegation_wait import ledger_job_id, track_request
    from dodaios.society.events import MsgType, now_ms
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    event_id = str(job.meta.get("event_id") or "")
    if runtime is None or not event_id:
        return None
    original = await runtime.store.get_event(event_id)
    if original is None or original.msg_type is not MsgType.ASSIGN:
        return None
    fresh = original.model_copy(update={
        "event_id": uuid7_str(), "seq": None, "trace_id": uuid7_str(),
        "parent_event_id": None, "ts_ms": now_ms(),
    })
    stored = await runtime.store.append_and_publish(fresh)
    await track_request(runtime, stored)
    return ledger_job_id(stored)


register_requeuer("society_assignment", _requeue_assignment)


def start_for_runtime(
    runtime: Any, config: Callable[[], Any] | None = None
) -> supervisor.Watchdog | None:
    """Start the watchdog beside a running society runtime (called on its loop)."""
    if supervisor.current() is not None:
        return supervisor.current()
    try:
        hop = LoopHop(asyncio.get_running_loop())
        data_dir = runtime.data_dir
        watchdog = supervisor.Watchdog(
            data_dir, LiveSources(runtime, hop), LiveActions(runtime, hop, config),
            boot_id=jobs.BOOT_ID,
        )
        watchdog.start()
    except Exception:  # noqa: BLE001 - the watchdog is a courtesy; the app starts without it
        log.warning("watchdog: not started", exc_info=True)
        return None
    supervisor.set_current(watchdog)
    return watchdog


def stop_current() -> None:
    watchdog = supervisor.current()
    if watchdog is not None:
        watchdog.stop()
        supervisor.set_current(None)


__all__ = ["LiveActions", "LiveSources", "LoopHop", "LoopUnresponsive", "register_requeuer",
           "start_for_runtime", "stop_current"]
