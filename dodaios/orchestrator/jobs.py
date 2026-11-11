"""The durable jobs ledger: one row per started unit of work.

Delegating is half of orchestration; the other half is knowing what became of
it. Every async hand-off (a mission, an artifact build, an assignment to a team
agent, a prompt typed into a coding pane, a team thread) writes ONE row here the
moment it starts and gets a ``job_id`` back, which the tool result carries. The
lead and the agents then ask ``job_status`` or ``await_jobs`` (see
``dodaios/plugins/tool/job_tools.py``) instead of polling shells and log files.

State is derived from evidence, never from a model. Each writer supplies the
same read-only probe the delegation wait already uses (the society board, the
CLI's completion record, the mission store, the team thread's own row). A probe
result is applied to the row by :func:`apply_result`, so the ledger, the
in-turn wait and the two tools all read one source of truth. A job whose process
is gone (the app restarted) with no way to re-read its evidence is marked
``interrupted``, never ``done``.

SQLite in the app's data directory (``jobs.db``), opened like the other stores:
one connection in WAL mode behind a lock. Every write is best effort for the
caller: a ledger problem must never fail the work it describes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

KINDS: Final[tuple[str, ...]] = (
    "mission",
    "artifact",
    "society_assignment",
    "ide_submission",
    "team_thread",
    "routine",
)
STATES: Final[tuple[str, ...]] = (
    "queued",
    "running",
    "done",
    "failed",
    "blocked",
    "interrupted",
    "cancelled",
)
#: Work that is still going: a wait keeps waiting for these.
OPEN_STATES: Final[frozenset[str]] = frozenset({"queued", "running"})
#: Evidence that closes a job for good. ``blocked`` and ``interrupted`` can still
#: move (an answer arrives, a recovered record shows the end).
FINAL_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})

_SUMMARY_MAX: Final[int] = 600
_ERROR_MAX: Final[int] = 400
#: One probe read may not hold a status call longer than this.
PROBE_TIMEOUT_S: Final[float] = 5.0

#: What a probe's ``status`` word means for the ledger. Anything not listed is
#: ``blocked``: unknown evidence is surfaced to the reader, never read as done.
_STATUS_TO_STATE: Final[dict[str, str]] = {
    "queued": "queued",
    "pending": "queued",
    "running": "running",
    "progress": "running",
    "done": "done",
    "completed": "done",
    "complete": "done",
    "ok": "done",
    "success": "done",
    "approved": "done",
    "answered": "done",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "exited": "failed",
    "unavailable": "failed",
    "timed_out": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "stopped": "cancelled",
    "superseded": "cancelled",
    "interrupted": "interrupted",
}

#: Per process: an open row from another boot whose evidence cannot be re-read.
BOOT_ID: Final[str] = uuid.uuid4().hex[:12]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    owner_session TEXT NOT NULL DEFAULT '',
    owner_turn    TEXT NOT NULL DEFAULT '',
    target        TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL DEFAULT '',
    state         TEXT NOT NULL,
    detail        TEXT NOT NULL DEFAULT '',
    ref           TEXT NOT NULL DEFAULT '',
    result_ref    TEXT NOT NULL DEFAULT '',
    summary       TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    cost_usd      REAL,
    meta          TEXT NOT NULL DEFAULT '{}',
    boot_id       TEXT NOT NULL DEFAULT '',
    created_ms    INTEGER NOT NULL,
    updated_ms    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs(owner_session, updated_ms DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_open ON jobs(state, updated_ms DESC);
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clip(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    owner_session: str
    owner_turn: str
    target: str
    title: str
    state: str
    detail: str
    ref: str
    result_ref: str
    summary: str
    error: str
    cost_usd: float | None
    meta: dict[str, Any]
    boot_id: str
    created_ms: int
    updated_ms: int

    @property
    def settled(self) -> bool:
        return self.state not in OPEN_STATES

    def to_dict(self, *, full: bool = False) -> dict[str, Any]:
        """Summary-first: the fields a reader acts on; ``full`` adds the plumbing."""
        row: dict[str, Any] = {
            "job_id": self.id,
            "kind": self.kind,
            "title": self.title,
            "state": self.state,
        }
        if self.detail and self.detail != self.state:
            row["status"] = self.detail
        if self.result_ref:
            row["result_ref"] = self.result_ref
        if self.summary:
            row["summary"] = self.summary
        if self.error:
            row["error"] = self.error
        if self.cost_usd is not None:
            row["cost_usd"] = self.cost_usd
        row["age_s"] = max(0, (_now_ms() - self.created_ms) // 1000)
        if full:
            row.update(
                target=self.target,
                owner_session=self.owner_session,
                owner_turn=self.owner_turn,
                created_ms=self.created_ms,
                updated_ms=self.updated_ms,
            )
        return row


_COLUMNS = (
    "id, kind, owner_session, owner_turn, target, title, state, detail, ref, result_ref, "
    "summary, error, cost_usd, meta, boot_id, created_ms, updated_ms"
)
_SELECT_ONE = (
    "SELECT id, kind, owner_session, owner_turn, target, title, state, detail, ref, "
    "result_ref, summary, error, cost_usd, meta, boot_id, created_ms, updated_ms "
    "FROM jobs WHERE id = ?"
)
_INSERT = (
    "INSERT OR IGNORE INTO jobs (id, kind, owner_session, owner_turn, target, title, state, "
    "detail, ref, result_ref, summary, error, cost_usd, meta, boot_id, created_ms, updated_ms) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _job(row: tuple[Any, ...]) -> Job:
    try:
        meta = json.loads(row[13] or "{}")
    except ValueError:  # a damaged meta column reads as no metadata
        meta = {}
    return Job(
        id=row[0], kind=row[1], owner_session=row[2], owner_turn=row[3], target=row[4],
        title=row[5], state=row[6], detail=row[7], ref=row[8], result_ref=row[9],
        summary=row[10], error=row[11], cost_usd=row[12],
        meta=meta if isinstance(meta, dict) else {}, boot_id=row[14],
        created_ms=row[15], updated_ms=row[16],
    )


class JobLedger:
    """SQLite store of jobs. One connection, WAL, a lock around every use."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        with self._lock:
            if self._path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(
        self,
        kind: str,
        *,
        job_id: str,
        owner_session: str = "",
        owner_turn: str = "",
        target: str = "",
        title: str = "",
        state: str = "running",
        ref: str = "",
        meta: dict[str, Any] | None = None,
    ) -> Job:
        """Insert the row; an id that exists already keeps its row (idempotent)."""
        if kind not in KINDS:
            raise ValueError(f"unknown job kind: {kind}")
        if state not in STATES:
            raise ValueError(f"unknown job state: {state}")
        now = _now_ms()
        with self._lock:
            self._conn.execute(
                _INSERT,
                (
                    job_id, kind, owner_session, owner_turn, _clip(target, 300),
                    _clip(title, 160), state, "", ref, "", "", "", None,
                    json.dumps(meta or {}, ensure_ascii=False), BOOT_ID, now, now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                _SELECT_ONE, (job_id,)
            ).fetchone()
        return _job(row)

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        detail: str | None = None,
        ref: str | None = None,
        result_ref: str | None = None,
        summary: str | None = None,
        error: str | None = None,
        cost_usd: float | None = None,
    ) -> Job | None:
        """Apply evidence. A job that ended for good keeps its ending."""
        with self._lock:
            row = self._conn.execute(
                _SELECT_ONE, (job_id,)
            ).fetchone()
            if row is None:
                return None
            current = _job(row)
            if current.state in FINAL_STATES:
                # Late or repeated evidence may still fill a missing reference.
                if result_ref and not current.result_ref:
                    self._conn.execute(
                        "UPDATE jobs SET result_ref = ?, updated_ms = ? WHERE id = ?",
                        (result_ref, _now_ms(), job_id),
                    )
                    self._conn.commit()
                    row = self._conn.execute(
                        _SELECT_ONE, (job_id,)
                    ).fetchone()
                return _job(row)
            if state is not None and state not in STATES:
                raise ValueError(f"unknown job state: {state}")
            fields = {
                "state": state,
                "detail": detail,
                "ref": ref,
                "result_ref": result_ref,
                "summary": None if summary is None else _clip(summary, _SUMMARY_MAX),
                "error": None if error is None else _clip(error, _ERROR_MAX),
                "cost_usd": cost_usd,
            }
            changed = {k: v for k, v in fields.items() if v is not None}
            if not changed:
                return current
            changed["updated_ms"] = _now_ms()
            assignments = ", ".join(f"{name} = ?" for name in changed)
            sql = f"UPDATE jobs SET {assignments} WHERE id = ?"  # noqa: S608 - fixed column names
            self._conn.execute(sql, (*changed.values(), job_id))
            self._conn.commit()
            row = self._conn.execute(
                _SELECT_ONE, (job_id,)
            ).fetchone()
        updated = _job(row)
        if updated.state in FINAL_STATES:
            _notify_ended(updated)
        return updated

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                _SELECT_ONE, (job_id,)
            ).fetchone()
        return _job(row) if row else None

    def recent(
        self, *, owner_session: str = "", limit: int = 20, open_only: bool = False
    ) -> list[Job]:
        """Newest first. Open jobs come before settled ones so none is cut off."""
        where, args = [], []
        if owner_session:
            where.append("owner_session = ?")
            args.append(owner_session)
        if open_only:
            where.append("state IN ('queued','running')")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM jobs {clause} "  # noqa: S608 - fixed clauses
                "ORDER BY (state IN ('queued','running')) DESC, updated_ms DESC LIMIT ?",
                (*args, max(1, int(limit))),
            ).fetchall()
        return [_job(row) for row in rows]


# --------------------------------------------------------------------- module state

_ledger: JobLedger | None = None
_ledger_lock = threading.Lock()
Probe = Callable[[], Awaitable[dict[str, Any] | None]]
#: job id -> the read-only evidence probe of THIS process.
_probes: dict[str, Probe] = {}
#: kind -> rebuilds a probe for a job from an earlier boot, when its evidence is
#: durable (a mission's own store). Kinds without one become ``interrupted``.
_rehydrators: dict[str, Callable[[Job], Probe | None]] = {}


#: Called once a job reaches a final state (thread subscriptions end with their job).
_end_listeners: list[Callable[[Job], None]] = []


def register_end_listener(listener: Callable[[Job], None]) -> None:
    if listener not in _end_listeners:
        _end_listeners.append(listener)


def _notify_ended(job: Job) -> None:
    for listener in list(_end_listeners):
        try:
            listener(job)
        except Exception:  # noqa: BLE001 - a listener never fails the work it observes
            log.warning("jobs: end listener failed for %s", job.id, exc_info=True)


def register_rehydrator(kind: str, build: Callable[[Job], Probe | None]) -> None:
    _rehydrators[kind] = build


def get_ledger() -> JobLedger:
    """The process ledger, opened on first use in the app's data directory."""
    global _ledger
    with _ledger_lock:
        if _ledger is None:
            from dodaios.core.config import DATA_DIR

            _ledger = JobLedger(Path(DATA_DIR) / "jobs.db")
        return _ledger


def set_ledger(ledger: JobLedger | None) -> None:
    """Replace the process ledger (tests, an embedding host)."""
    global _ledger
    with _ledger_lock:
        _ledger = ledger
    _probes.clear()


def job_id_for(kind: str, key: str) -> str:
    """A stable id for work that already has an identity (an event, a pane turn).

    The id can be computed by the caller that formats the tool result, without
    any handle to the writer.
    """
    return "job_" + hashlib.sha1(f"{kind}:{key}".encode(), usedforsecurity=False).hexdigest()[:12]


def new_job_id() -> str:
    return "job_" + uuid.uuid4().hex[:12]


def owner_of(ctx: Any = None) -> tuple[str, str]:
    """``(session, turn)`` that started the work: the trusted chat turn, else the
    chat the executor says the call came from, else nobody."""
    try:
        from dodaios.core.protocols import current_chat_turn

        turn = current_chat_turn.get()
    except Exception:  # noqa: BLE001 - provenance is optional
        turn = None
    if turn is not None and turn.session_id:
        return turn.session_id, turn.turn_id
    config = getattr(ctx, "config", None)
    ref = str(config.get("approval_ref") or "") if isinstance(config, dict) else ""
    if ref.startswith("agent-chat:"):
        return ref.removeprefix("agent-chat:"), ""
    return "", ""


def state_from_status(status: Any) -> str:
    word = str(status or "").strip().lower()
    return _STATUS_TO_STATE.get(word, "blocked")


def apply_result(job_id: str, result: dict[str, Any] | None) -> Job | None:
    """Write one probe reading into the ledger. ``None`` means no evidence yet."""
    if result is None:
        return get_ledger().get(job_id)
    status = str(result.get("status") or "")
    state = state_from_status(status)
    report = str(result.get("report") or result.get("done") or "")
    return get_ledger().update(
        job_id,
        state=state,
        detail=str(result.get("detail") or status).lower() or None,
        summary=report if state != "running" and report else None,
        error=report if state == "failed" and report else None,
        result_ref=str(result.get("result_ref") or "") or None,
    )


def finish(
    job_id: str | None,
    state: str,
    *,
    summary: str = "",
    error: str = "",
    result_ref: str = "",
    ref: str = "",
    cost_usd: float | None = None,
) -> None:
    """Record an ending a writer saw directly (a crashed dispatch, a finished page)."""
    if not job_id:
        return
    try:
        get_ledger().update(
            job_id,
            state=state,
            summary=summary or None,
            error=error or None,
            result_ref=result_ref or None,
            ref=ref or None,
            cost_usd=cost_usd,
        )
    except Exception:  # noqa: BLE001 - the ledger never fails the work it describes
        log.warning("jobs: could not record %s for %s", state, job_id, exc_info=True)


def link(job_id: str | None, ref: str) -> None:
    """Attach the identity the work only gets after it starts (a mission id)."""
    if not job_id or not ref:
        return
    try:
        get_ledger().update(job_id, ref=ref)
    except Exception:  # noqa: BLE001
        log.warning("jobs: could not link %s to %s", job_id, ref, exc_info=True)


def ledgered(job_id: str, probe: Callable[[], Awaitable[dict[str, Any] | None]]):
    """``probe`` that also writes what it reads into the ledger.

    The wrapper returns the probe's result unchanged, so the in-turn wait and the
    job tools share one evidence read and one record.
    """

    async def read() -> dict[str, Any] | None:
        result = await probe()
        try:
            apply_result(job_id, result)
        except Exception:  # noqa: BLE001 - recording is not the work
            log.warning("jobs: could not record evidence for %s", job_id, exc_info=True)
        return result

    return read


def start(
    kind: str,
    *,
    job_id: str | None = None,
    target: str = "",
    title: str = "",
    ctx: Any = None,
    owner: tuple[str, str] | None = None,
    probe: Callable[[], Awaitable[dict[str, Any] | None]] | None = None,
    state: str = "running",
    ref: str = "",
    meta: dict[str, Any] | None = None,
) -> str | None:
    """Write the row for work that just started; ``None`` if the ledger is down.

    ``probe`` is remembered for this process so :func:`refresh` can derive the
    state later. The returned id is what the tool result hands to the model.
    """
    session, turn = owner if owner is not None else owner_of(ctx)
    jid = job_id or new_job_id()
    try:
        get_ledger().create(
            kind, job_id=jid, owner_session=session, owner_turn=turn, target=target,
            title=title, state=state, ref=ref, meta=meta,
        )
    except Exception:  # noqa: BLE001 - never fail the work for its record
        log.warning("jobs: could not record a %s job", kind, exc_info=True)
        return None
    if probe is not None:
        _probes[jid] = ledgered(jid, probe)
    return jid


def probe_for(job_id: str) -> Callable[[], Awaitable[dict[str, Any] | None]] | None:
    """The ledgered probe of a job started in this process, for the delegation wait."""
    return _probes.get(job_id)


async def refresh(job: Job) -> Job:
    """The job as the evidence shows it now. Reads only; never dispatches work."""
    import asyncio

    if job.state in FINAL_STATES:
        return job
    probe = _probes.get(job.id)
    if probe is None and job.boot_id != BOOT_ID:
        if job.kind in ("mission", "artifact"):
            from dodaios.orchestrator import mission_jobs  # noqa: F401 - registers its rehydrator
        build = _rehydrators.get(job.kind)
        probe = build(job) if build is not None else None
        if probe is not None:
            _probes[job.id] = probe
    if probe is None:
        if job.boot_id != BOOT_ID and not job.settled:
            # Its process ended and nothing here can read its evidence again.
            updated = get_ledger().update(
                job.id,
                state="interrupted",
                detail="interrupted",
                summary="The app restarted while this was running; its outcome is unknown.",
            )
            return updated or job
        return job
    try:
        await asyncio.wait_for(probe(), PROBE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - a failed read leaves the last known state
        log.warning("jobs: evidence read failed for %s", job.id, exc_info=True)
    return get_ledger().get(job.id) or job


def with_job_id(output: Any, job_id: str | None, ctx: Any = None) -> Any:
    """Put the job id into a tool's text result for a model that must read it.

    A spoken acknowledgement of the classic voice path carries no tool origin and
    is returned untouched; the id rides in the result's structured data instead.
    """
    if not job_id:
        return output
    if isinstance(output, dict):
        return {**output, "job_id": job_id}
    config = getattr(ctx, "config", None)
    if isinstance(output, str) and isinstance(config, dict) and config.get("tool_origin"):
        return f"{output}\n(job_id: {job_id}; check it with job_status or await_jobs)"
    return output


__all__ = [
    "BOOT_ID",
    "FINAL_STATES",
    "KINDS",
    "OPEN_STATES",
    "STATES",
    "Job",
    "JobLedger",
    "apply_result",
    "finish",
    "get_ledger",
    "job_id_for",
    "ledgered",
    "link",
    "new_job_id",
    "owner_of",
    "probe_for",
    "refresh",
    "register_end_listener",
    "register_rehydrator",
    "set_ledger",
    "start",
    "state_from_status",
    "with_job_id",
]
