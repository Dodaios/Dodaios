"""``lead_turns.db``: what the lead was given each turn, and what it did first.

A later benchmark replays a past turn of the lead (the assistant's own chat):
it gives the model exactly what it was given then, with one thing changed, and
compares the first move. This file is what it replays from. One row per lead
turn, written once and never changed:

* when, which chat session and turn, the CLI, model and effort;
* the system prompt and the message, exactly as the CLI got them
  (``runner_cli.lead_model_input``), compressed;
* a hash of the tool list the chat is offered, so a replay can tell whether
  its tools are still the ones the turn had;
* the vendor conversation a resumed turn continued, whether the turn carried a
  running task on, and how many pictures went with the message;
* the first move: the first tool call's name and arguments (and whether a
  line of text came before it), or that the model answered in text only.

Only the lead's turns are kept: the ``jarvis`` surface, not a slash command.
A turn that produced nothing (an error before the first output) is not kept.

The file stays on this machine: nothing reads it but the benchmark, and
nothing sends it anywhere. It keeps at most :data:`RETENTION_DAYS` days and at
most :data:`MAX_BYTES` of stored text (the oldest rows go first); deleted text
is overwritten on disk (``secure_delete``). Deleting a chat session deletes its
rows (:func:`forget_session`, called by ``AgentChatStore.delete_session``).

Recording never slows or breaks a turn. The recorder is told about events on
the chat's emit path and only notes them there; the row is written by a
background task, off the event loop, once the first move is known. Any failure
is logged once and the row is skipped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dodaios.rsi.storage import Db, Schema, open_db

__all__ = [
    "DB_NAME",
    "MAX_BYTES",
    "RETENTION_DAYS",
    "LeadTurn",
    "LeadTurnStore",
    "TurnRecorder",
    "drain",
    "forget_session",
    "store",
]

log = logging.getLogger(__name__)

DB_NAME: Final = "lead_turns.db"
#: How long a row is kept.
RETENTION_DAYS: Final = 90
#: How much stored text (compressed) the file keeps at most; the oldest rows go first.
#: A lead turn takes about 25 KB (its system prompt runs past 50 000 characters), so
#: this holds roughly 8 000 turns, three months of a busy chat.
MAX_BYTES: Final = 200 * 1024 * 1024
_DAY_MS: Final = 24 * 60 * 60 * 1000

SCHEMA: Final = Schema(
    DB_NAME,
    (
        """
        CREATE TABLE turns (
            seq               INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms             INTEGER NOT NULL,
            bytes             INTEGER NOT NULL,
            app               TEXT NOT NULL,
            session_id        TEXT NOT NULL,
            turn_id           TEXT NOT NULL,
            cli               TEXT NOT NULL,
            model             TEXT NOT NULL,
            effort            TEXT NOT NULL,
            resumed           TEXT NOT NULL DEFAULT '',
            continuation      INTEGER NOT NULL DEFAULT 0,
            images            INTEGER NOT NULL DEFAULT 0,
            tools_digest      TEXT NOT NULL,
            first_kind        TEXT NOT NULL,
            first_tool        TEXT NOT NULL DEFAULT '',
            text_before_tool  INTEGER NOT NULL DEFAULT 0,
            first_args_z      BLOB NOT NULL,
            system_z          BLOB NOT NULL,
            message_z         BLOB NOT NULL
        );
        CREATE INDEX turns_session ON turns(session_id);
        CREATE INDEX turns_age ON turns(ts_ms, bytes);
        CREATE TRIGGER turns_no_update BEFORE UPDATE ON turns
        BEGIN SELECT RAISE(ABORT, 'a recorded lead turn is never changed'); END;
        """,
    ),
)


@dataclass(frozen=True, slots=True)
class LeadTurn:
    """One recorded lead turn."""

    session_id: str
    turn_id: str
    cli: str
    model: str
    effort: str
    #: The system prompt and the message, exactly as the CLI got them.
    system: str
    message: str
    tools_digest: str
    #: ``tool``: the model called a tool (``first_tool``, ``first_args``);
    #: ``text``: it answered in text only.
    first_kind: str
    first_tool: str = ""
    first_args: dict[str, Any] = field(default_factory=dict)
    #: A line of text came before the first tool call.
    text_before_tool: bool = False
    #: The vendor conversation the turn continued (``""``: a fresh one).
    resumed: str = ""
    #: The turn carried a running task on (no new request from the person).
    continuation: bool = False
    #: Pictures that went with the message (not kept here).
    images: int = 0
    ts_ms: int = 0
    app: str = ""
    seq: int = 0


def _pack(text: str) -> bytes:
    return zlib.compress(text.encode("utf-8"), 6)


def _unpack(blob: bytes) -> str:
    return zlib.decompress(blob).decode("utf-8")


def _now() -> int:
    return int(time.time() * 1000)


class LeadTurnStore:
    """The handle on ``lead_turns.db``."""

    def __init__(self, path: Path | str) -> None:
        self._db: Db = open_db(path, SCHEMA)
        if not self._db.readonly:
            with self._db.lock:
                # What is deleted (old rows, a deleted chat) is overwritten, not left in free pages.
                self._db.conn.execute("PRAGMA secure_delete = ON")
            self.prune()

    @property
    def readonly(self) -> bool:
        return self._db.readonly

    def close(self) -> None:
        self._db.close()

    def append(self, turn: LeadTurn, *, now_ms: int | None = None) -> None:
        """Add one turn, then drop what is past the age or the size limit."""
        args = _pack(json.dumps(turn.first_args, sort_keys=True, ensure_ascii=False, default=str))
        system, message = _pack(turn.system), _pack(turn.message)
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO turns (ts_ms, bytes, app, session_id, turn_id, cli, model, effort,"
                " resumed, continuation, images, tools_digest, first_kind, first_tool,"
                " text_before_tool, first_args_z, system_z, message_z)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    turn.ts_ms or _now(),
                    len(args) + len(system) + len(message),
                    turn.app,
                    turn.session_id,
                    turn.turn_id,
                    turn.cli,
                    turn.model,
                    turn.effort,
                    turn.resumed,
                    int(turn.continuation),
                    int(turn.images),
                    turn.tools_digest,
                    turn.first_kind,
                    turn.first_tool,
                    int(turn.text_before_tool),
                    args,
                    system,
                    message,
                ),
            )
            self._db.conn.commit()
        self.prune(now_ms=now_ms)

    def prune(self, *, now_ms: int | None = None, max_bytes: int = MAX_BYTES) -> int:
        """Drop rows older than :data:`RETENTION_DAYS`, then the oldest beyond ``max_bytes``."""
        if self._db.readonly:
            return 0
        cutoff = (now_ms if now_ms is not None else _now()) - RETENTION_DAYS * _DAY_MS
        with self._db.lock:
            conn = self._db.conn
            removed = conn.execute("DELETE FROM turns WHERE ts_ms < ?", (cutoff,)).rowcount
            total = int(conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM turns").fetchone()[0])
            if total > max_bytes:
                excess, doomed = total - max_bytes, []
                # Oldest first, read from the (ts_ms, bytes) index, not the rows.
                oldest = conn.execute("SELECT seq, bytes FROM turns ORDER BY ts_ms, seq").fetchall()
                for row in oldest:
                    if excess <= 0:
                        break
                    doomed.append((row["seq"],))
                    excess -= int(row["bytes"])
                conn.executemany("DELETE FROM turns WHERE seq = ?", doomed)
                removed += len(doomed)
            conn.commit()
        return int(removed)

    def forget_session(self, session_id: str) -> int:
        """Delete every row of a chat session. Returns how many went."""
        if self._db.readonly:
            return 0
        with self._db.lock:
            cur = self._db.conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
            self._db.conn.commit()
        return int(cur.rowcount)

    def turns(self, *, session_id: str = "", limit: int = 100) -> list[LeadTurn]:
        """Recorded turns, newest first."""
        sql, args = "SELECT * FROM turns", []
        if session_id:
            sql += " WHERE session_id = ?"
            args.append(session_id)
        with self._db.lock:
            rows = self._db.conn.execute(sql + " ORDER BY seq DESC LIMIT ?", [*args, limit])
            found = rows.fetchall()
        return [
            LeadTurn(
                session_id=row["session_id"],
                turn_id=row["turn_id"],
                cli=row["cli"],
                model=row["model"],
                effort=row["effort"],
                system=_unpack(row["system_z"]),
                message=_unpack(row["message_z"]),
                tools_digest=row["tools_digest"],
                first_kind=row["first_kind"],
                first_tool=row["first_tool"],
                first_args=dict(json.loads(_unpack(row["first_args_z"]))),
                text_before_tool=bool(row["text_before_tool"]),
                resumed=row["resumed"],
                continuation=bool(row["continuation"]),
                images=int(row["images"]),
                ts_ms=int(row["ts_ms"]),
                app=row["app"],
                seq=int(row["seq"]),
            )
            for row in found
        ]

    def stored_bytes(self) -> int:
        with self._db.lock:
            return int(
                self._db.conn.execute("SELECT COALESCE(SUM(bytes), 0) FROM turns").fetchone()[0]
            )


# ------------------------------------------------------------------ the app's file

_LOCK = threading.Lock()
_OPEN: dict[str, LeadTurnStore] = {}
#: Sessions deleted while this process ran: a turn still being written for one is dropped.
_FORGOTTEN: set[str] = set()
#: Background writes still running (kept so they are not collected mid-way).
_PENDING: set[asyncio.Task[None]] = set()
_warned = False


def _db_path() -> Path:
    from dodaios.core.paths import runtime_data_dir

    return runtime_data_dir() / DB_NAME


def store() -> LeadTurnStore:
    """The app's own ``lead_turns.db``, opened once per process."""
    path = str(_db_path())
    with _LOCK:
        found = _OPEN.get(path)
        if found is None:
            found = _OPEN[path] = LeadTurnStore(path)
        return found


def _skip(what: str) -> None:
    """Log the first failure with its cause; later ones only at debug level."""
    global _warned
    if not _warned:
        _warned = True
        log.warning("lead turns: %s (logged once; recording carries on)", what, exc_info=True)
    else:
        log.debug("lead turns: %s", what, exc_info=True)


def forget_session(session_id: str) -> int:
    """Delete the rows of a chat session the person deleted. Never raises."""
    if not session_id:
        return 0
    _FORGOTTEN.add(session_id)
    try:
        if not _db_path().exists():
            return 0
        return store().forget_session(session_id)
    except Exception:  # noqa: BLE001 - a failed erase is logged; the chat's own deletion stands
        _skip(f"the rows of deleted session {session_id} were not deleted")
        return 0


def _append(turn: LeadTurn) -> None:
    if turn.session_id in _FORGOTTEN:
        return
    found = store()
    if found.readonly:
        return  # a newer app wrote this file: it keeps it, this one pauses
    found.append(turn)


async def _tools_digest(session_id: str) -> str:
    try:
        from dodaios.mcp.dodaios_tools_server import tool_list_digest

        return await tool_list_digest(session_id)
    except Exception:  # noqa: BLE001 - without the hash the row still holds the turn
        log.debug("lead turns: tool list hash unavailable", exc_info=True)
        return ""


async def drain() -> None:
    """Wait for the rows still being written (tests, and a clean shutdown)."""
    while _PENDING:
        await asyncio.gather(*list(_PENDING), return_exceptions=True)


# ------------------------------------------------------------------ one turn


class TurnRecorder:
    """Collects one lead turn: what the CLI was handed, then the model's first move.

    :meth:`planned` takes what the CLI is handed (``runner_cli.LeadModelInput``)
    each time the turn plans a run; the run that makes the first move is the
    one kept. :meth:`observe` sees every event of the turn; :meth:`finish` is
    called when the turn has ended. All three only note things and never raise.
    """

    def __init__(
        self, session_id: str, turn_id: str, *, continuation: bool = False, images: int = 0
    ) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self._continuation = continuation
        self._images = images
        self._input: Any = None
        self._resumed = ""
        self._planned_ms = 0
        self._text = False
        self._done = False

    def planned(self, model_input: Any, *, resume: str | None) -> None:
        if self._done or self._text:
            return  # the first move came from an earlier run of this turn
        self._input = model_input
        self._resumed = resume or ""
        self._planned_ms = _now()

    def observe(self, event: dict[str, Any]) -> None:
        if self._done or self._input is None:
            return
        try:
            payload = event.get("payload") or {}
            if payload.get("agent_id"):
                return  # a sub-agent's own conversation, not the lead's move
            kind = event.get("kind")
            if kind in {"text_delta", "assistant_text"} and str(payload.get("text") or "").strip():
                self._text = True
            elif kind == "tool_call":
                raw = payload.get("input")
                self._write(
                    "tool",
                    tool=str(payload.get("name") or ""),
                    args=dict(raw) if isinstance(raw, dict) else {"input": raw},
                )
        except Exception:  # noqa: BLE001 - recording never fails the turn's own emit path
            _skip("an event of a lead turn could not be read")

    def finish(self) -> None:
        if not self._done and self._input is not None and self._text:
            self._write("text")
        self._done = True

    def _write(self, kind: str, *, tool: str = "", args: dict[str, Any] | None = None) -> None:
        self._done = True
        try:
            from dodaios import __version__

            source = self._input
            turn = LeadTurn(
                session_id=self.session_id,
                turn_id=self.turn_id,
                cli=str(source.cli),
                model=str(source.model),
                effort=str(source.effort),
                system=str(source.system),
                message=str(source.message),
                tools_digest="",
                first_kind=kind,
                first_tool=tool,
                first_args=args or {},
                text_before_tool=kind == "tool" and self._text,
                resumed=self._resumed,
                continuation=self._continuation,
                images=self._images,
                ts_ms=self._planned_ms,
                app=str(__version__),
            )
            task = asyncio.get_running_loop().create_task(_record(turn))
        except Exception:  # noqa: BLE001 - recording never fails the turn
            _skip("a lead turn could not be queued for recording")
            return
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)


async def _record(turn: LeadTurn) -> None:
    try:
        digest = await _tools_digest(turn.session_id)
        await asyncio.to_thread(_append, _with_digest(turn, digest))
    except Exception:  # noqa: BLE001 - the record is best effort, never the turn's problem
        _skip(f"lead turn {turn.turn_id} was not recorded")


def _with_digest(turn: LeadTurn, digest: str) -> LeadTurn:
    from dataclasses import replace

    return replace(turn, tools_digest=digest)
