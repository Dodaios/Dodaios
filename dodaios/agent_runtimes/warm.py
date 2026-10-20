"""Warm ACP processes: an agent's runtime process kept between its turns.

Starting ``hermes acp`` or ``openclaw acp`` costs seconds before the model is
even asked: an interpreter or Node.js start, imports, the ACP handshake, the
MCP connection and the session load (measured 4-7 s per turn on Windows).
A :class:`WarmPool` keeps one process per runtime home instead, already
initialized and with the agent's conversation open, so a turn only sends
``session/prompt``. A chat that is opened can start one before the first
message (:meth:`WarmPool.warm`).

A turn borrows the process through a :class:`Lease`, which looks like a child
process to the CLI runner: this turn's stdout and stderr lines, a stdin whose
``close()`` ends the turn (not the process), and ``kill()``, which ends the
process. A process is only reused with exactly the launch it was started for
(argv, environment, working folder and the runtime's config files, as
:attr:`WarmSpec.signature`); anything else retires it and starts a fresh one.
Idle processes are stopped after :data:`IDLE_STOP_S`, and at most
:data:`MAX_WARM` are kept per runtime.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dodaios.agent_runtimes.acp import frame_line, initialize_request

log = logging.getLogger(__name__)

#: Stop a warm process after this long without a turn.
IDLE_STOP_S: Final[float] = 30 * 60

#: Warm processes kept per runtime; the least recently used one goes first.
MAX_WARM: Final[int] = 6

#: How long a new process may take to answer ``initialize``.
_HANDSHAKE_TIMEOUT_S: Final[float] = 60.0

#: How long one warm-up step (session open, warm-up run) may take. Short: a
#: warm-up holds the agent's turn slot, so a message sent meanwhile waits.
_WARM_STEP_TIMEOUT_S: Final[float] = 45.0

#: One line read from the runtime may be this long (the CLI runner's limit).
_READLINE_LIMIT: Final[int] = 16 * 1024 * 1024

_INIT_ID: Final[str] = "dodaios-warm-init"
_SESSION_ID: Final[str] = "dodaios-warm-session"
_EXERCISE_SESSION_ID: Final[str] = "dodaios-warm-exercise-session"
_EXERCISE_PROMPT_ID: Final[str] = "dodaios-warm-exercise-prompt"


def signature(*parts: Any) -> str:
    """A stable digest of launch inputs (secrets stay inside the digest)."""
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WarmSpec:
    """Everything one runtime process is started with."""

    argv: list[str]
    env: dict[str, str]
    cwd: Path
    #: Digest of the launch inputs, including the runtime config files the
    #: process reads only at start.
    signature: str
    #: ``initialize``'s ``clientInfo.version``.
    client_version: str = ""


@dataclass(frozen=True, slots=True)
class SessionWant:
    """The ACP session a turn needs open."""

    #: ``session/load`` id, or ``None`` for a fresh (or runtime-bound) session.
    resume: str | None
    #: ``session/new`` / ``session/load`` parameters (``cwd``, ``mcpServers``).
    params: dict[str, Any]
    #: An open session serves a turn without ``resume`` too: the runtime keeps
    #: the conversation by its own key (OpenClaw), not by the ACP session id.
    bound: bool = False
    #: What an open session must have been opened with to serve this turn
    #: (default: ``params``). OpenClaw leaves the one-time reset flag out, so
    #: the session a reset turn opened serves the turns after it.
    match: dict[str, Any] | None = None

    @property
    def key(self) -> str:
        return signature(self.params if self.match is None else self.match)


class _Stream:
    """The stdout/stderr of one lease: the turn's lines, then EOF."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes | BaseException] = asyncio.Queue()
        self._eof = False

    def feed(self, line: bytes | BaseException) -> None:
        if not self._eof:
            self._queue.put_nowait(line)

    def feed_eof(self) -> None:
        if not self._eof:
            self._queue.put_nowait(b"")
            self._eof = True

    async def readline(self) -> bytes:
        item = await self._queue.get()
        if isinstance(item, BaseException):
            raise item
        if item == b"":
            # Every later read is EOF too.
            self._queue.put_nowait(b"")
        return item


class _Stdin:
    """The lease's stdin: frames go to the runtime; ``close()`` ends the turn."""

    def __init__(self, lease: Lease) -> None:
        self._lease = lease

    def write(self, data: bytes) -> None:
        real = self._lease._proc.proc.stdin
        if self._lease.finished or real is None or real.is_closing():
            raise BrokenPipeError("the turn is over")
        real.write(data)

    async def drain(self) -> None:
        real = self._lease._proc.proc.stdin
        if real is not None and not self._lease.finished:
            await real.drain()

    def is_closing(self) -> bool:
        real = self._lease._proc.proc.stdin
        return self._lease.finished or real is None or real.is_closing()

    def close(self) -> None:
        self._lease.finish()


class Lease:
    """One turn on a warm process, shaped like ``asyncio.subprocess.Process``."""

    #: Never a turn-host process (``runner_cli`` reads it).
    hosted = False

    def __init__(self, pool: WarmPool, proc: _WarmProcess, want: SessionWant) -> None:
        self._pool = pool
        self._proc = proc
        self._want = want
        self.stdout = _Stream()
        self.stderr = _Stream()
        self.stdin = _Stdin(self)
        self._done = asyncio.Event()
        self._returncode: int | None = None
        #: The turn's ``AcpTurn``; read at the end to remember the open session.
        self.turn: Any = None
        #: ``initialize`` result of the process (the turn skips the request).
        self.initialized: dict[str, Any] = dict(proc.initialized or {})
        #: The ACP session already open with this turn's parameters ("" = none).
        self.open_session = proc.session_for(want)

    @property
    def pid(self) -> int:
        return int(self._proc.proc.pid)

    @property
    def returncode(self) -> int | None:
        return self._returncode

    @property
    def finished(self) -> bool:
        return self._returncode is not None

    def finish(self) -> None:
        """The turn is over; the process stays for the next one."""
        if self.finished:
            return
        self._returncode = 0
        turn = self.turn
        session = ""
        if turn is not None and getattr(turn, "saw_result", False):
            session = str(getattr(turn, "acp_session", "") or "")
            if getattr(turn, "status", "") != "done" and getattr(turn, "stop_reason", "") != (
                "cancelled"
            ):
                session = ""  # an error may have left the session half-way
        self._end()
        self._pool._returned(self._proc, self, session, self._want)

    def kill(self) -> None:
        """End the process itself (Stop, a stalled or failed turn)."""
        if self.finished:
            return
        self._returncode = -9
        self._end()
        self._pool._discard(self._proc, "the turn ended it")

    terminate = kill

    def died(self, code: int | None) -> None:
        if self.finished:
            return
        self._returncode = code if code is not None else -1
        self._end()

    def _end(self) -> None:
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        return int(self._returncode or 0)


@dataclass(slots=True)
class _WarmProcess:
    key: str
    spec_signature: str
    proc: asyncio.subprocess.Process
    tree: Any
    tracker: Any
    initialized: dict[str, Any] | None = None
    #: The ACP session open in the process and the parameters it was opened with.
    session: str = ""
    session_key: str = ""
    #: The session is a fresh one nobody prompted yet (``session/new`` ahead).
    session_fresh: bool = False
    lease: Lease | None = None
    last_used: float = field(default_factory=time.monotonic)
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    stderr_tail: collections.deque[str] = field(
        default_factory=lambda: collections.deque(maxlen=20)
    )
    tasks: list[asyncio.Task[None]] = field(default_factory=list)

    def alive(self) -> bool:
        return self.proc.returncode is None

    def can_load(self) -> bool:
        caps = (self.initialized or {}).get("agentCapabilities")
        return isinstance(caps, dict) and bool(caps.get("loadSession"))

    def session_for(self, want: SessionWant) -> str:
        if not self.session or self.session_key != want.key:
            return ""
        if want.resume is not None:
            return self.session if want.resume == self.session else ""
        return self.session if (want.bound or self.session_fresh) else ""


class WarmPool:
    """The warm processes of one runtime, by runtime home key."""

    def __init__(self, runtime: str) -> None:
        self.runtime = runtime
        self._procs: dict[str, _WarmProcess] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._reaper: asyncio.Task[None] | None = None
        #: Processes ended synchronously (:meth:`_discard`) still being reaped.
        self._draining: set[asyncio.Task[None]] = set()

    def _lock(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    # --------------------------------------------------------------- public

    async def lease(self, key: str, spec: WarmSpec, want: SessionWant) -> Lease | None:
        """A warm process for this turn (started now when none fits).

        ``None`` = no process could be prepared; the caller starts its turn
        the ordinary way, whose errors then reach the chat with their reason.
        Called with the turn slot of ``key`` held.
        """
        async with self._lock(key):
            warm = await self._ready(key, spec)
            if warm is None:
                return None
            if want.resume is not None and not warm.can_load():
                await self._retire(warm, "it cannot reopen conversations")
                return None
            lease = Lease(self, warm, want)
            warm.lease = lease
            warm.last_used = time.monotonic()
            if lease.open_session:
                warm.session_fresh = False
            log.info(
                "agent runtimes: %s turn on a warm process (%s)",
                self.runtime,
                "session open" if lease.open_session else "session to open",
            )
            return lease

    async def warm(self, key: str, spec: WarmSpec, want: SessionWant | None) -> bool:
        """Start (or keep) the process for ``key`` and open the session ahead.

        ``want=None``: the process only, no session. Called while nobody runs
        a turn of ``key`` (the caller holds its turn slot). Spends no model
        call: only the handshake and the session load.
        """
        async with self._lock(key):
            warm = await self._ready(key, spec)
            if warm is None:
                return False
            if want is None or warm.session_for(want):
                return True
            try:
                await self._open_session(warm, want)
            except (TimeoutError, OSError, RuntimeError) as exc:
                log.info("agent runtimes: %s warm-up kept without a session: %s",
                         self.runtime, exc)
            return warm.alive()

    async def exercise(
        self, key: str, spec: WarmSpec, params: dict[str, Any], text: str
    ) -> bool:
        """One throwaway prompt on the process, in a session of its own.

        Some runtimes set their agent loop up lazily on the first prompt
        (OpenClaw: seconds per Gateway start). Spent here, before the
        person's message, it is not in front of their first token. The
        caller makes sure the model call it causes bills nothing.
        """
        async with self._lock(key):
            warm = await self._ready(key, spec)
            if warm is None:
                return False
            try:
                opened = await self._request(
                    warm,
                    _EXERCISE_SESSION_ID,
                    _rpc(_EXERCISE_SESSION_ID, "session/new", params),
                    timeout_s=_WARM_STEP_TIMEOUT_S,
                )
                session = str(opened.get("sessionId") or "")
                if not session:
                    return False
                await self._request(
                    warm,
                    _EXERCISE_PROMPT_ID,
                    _rpc(
                        _EXERCISE_PROMPT_ID,
                        "session/prompt",
                        {"sessionId": session, "prompt": [{"type": "text", "text": text}]},
                    ),
                    timeout_s=_WARM_STEP_TIMEOUT_S,
                )
            except (TimeoutError, OSError, RuntimeError) as exc:
                log.info("agent runtimes: %s warm-up run failed: %s", self.runtime, exc)
                return False
            return True

    def has(self, key: str, spec_signature: str | None = None) -> bool:
        warm = self._procs.get(key)
        return (
            warm is not None
            and warm.alive()
            and (spec_signature is None or warm.spec_signature == spec_signature)
        )

    async def stop(self, keys: set[str] | None = None) -> None:
        """Stop the warm processes of ``keys`` (all when ``None``)."""
        for key, warm in list(self._procs.items()):
            if keys is None or key in keys:
                async with self._lock(key):
                    if self._procs.get(key) is warm:
                        await self._retire(warm, "stopped")
        if self._draining:
            await asyncio.gather(*list(self._draining), return_exceptions=True)

    # -------------------------------------------------------------- process

    async def _ready(self, key: str, spec: WarmSpec) -> _WarmProcess | None:
        warm = self._procs.get(key)
        if warm is not None and warm.lease is not None and not warm.lease.finished:
            return None  # a turn still owns it (never with the slot held)
        if warm is not None and (
            not warm.alive() or warm.spec_signature != spec.signature or warm.initialized is None
        ):
            reason = (
                "it exited" if not warm.alive()
                else "its launch changed" if warm.spec_signature != spec.signature
                else "its handshake never finished"
            )
            await self._retire(warm, reason)
            warm = None
        if warm is None:
            await self._make_room()
            warm = await self._spawn(key, spec)
        return warm

    async def _spawn(self, key: str, spec: WarmSpec) -> _WarmProcess | None:
        from dodaios.core.process_tree import (
            TURN_MARKER_ENV,
            DescendantTracker,
            make_process_tree,
        )
        from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

        env = dict(spec.env)
        marker = ""
        if os.name != "nt":
            # Descendants that detach are still found by this mark (POSIX).
            from uuid import uuid4

            marker = uuid4().hex
            env[TURN_MARKER_ENV] = marker
        tree = make_process_tree(f"{self.runtime}-warm-{key}")
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=str(spec.cwd),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=NO_WINDOW_CREATIONFLAGS,
                start_new_session=os.name != "nt",
                limit=_READLINE_LIMIT,
            )
        except (OSError, ValueError) as exc:
            tree.close()
            log.info("agent runtimes: %s warm process did not start: %s", self.runtime, exc)
            return None
        tree.assign(proc.pid)
        tracker = DescendantTracker(proc.pid, interval_s=5.0, marker=marker or None)
        tracker.start()
        warm = _WarmProcess(key, spec.signature, proc, tree, tracker)
        warm.tasks = [
            asyncio.create_task(self._read_stdout(warm)),
            asyncio.create_task(self._read_stderr(warm)),
        ]
        self._procs[key] = warm
        self._ensure_reaper()
        try:
            result = await self._request(
                warm, _INIT_ID, initialize_request(_INIT_ID, spec.client_version)
            )
        except (TimeoutError, OSError, RuntimeError) as exc:
            tail = " | ".join(list(warm.stderr_tail)[-3:])
            log.info("agent runtimes: %s warm process failed its handshake: %s %s",
                     self.runtime, exc, tail)
            await self._retire(warm, "its handshake failed")
            return None
        except BaseException:
            # Cancelled mid-handshake (Stop, app shutdown): never leave a
            # half-started process for the next turn to pick up.
            self._discard(warm, "its start was cancelled")
            raise
        warm.initialized = result
        log.info(
            "agent runtimes: %s warm process for %s ready in %.1f s",
            self.runtime, key, time.monotonic() - started,
        )
        return warm

    async def _open_session(self, warm: _WarmProcess, want: SessionWant) -> None:
        params = dict(want.params)
        if want.resume is not None:
            if not warm.can_load():
                return
            result = await self._request(
                warm, _SESSION_ID,
                _rpc(_SESSION_ID, "session/load", params | {"sessionId": want.resume}),
                timeout_s=_WARM_STEP_TIMEOUT_S,
            )
            if not result:
                raise RuntimeError("the conversation could not be reopened")
            warm.session, warm.session_fresh = want.resume, False
        else:
            result = await self._request(
                warm, _SESSION_ID, _rpc(_SESSION_ID, "session/new", params),
                timeout_s=_WARM_STEP_TIMEOUT_S,
            )
            session = str(result.get("sessionId") or "")
            if not session:
                raise RuntimeError("session/new returned no session id")
            warm.session, warm.session_fresh = session, True
        warm.session_key = want.key

    async def _request(
        self,
        warm: _WarmProcess,
        rid: str,
        frame: dict[str, Any],
        *,
        timeout_s: float = _HANDSHAKE_TIMEOUT_S,
    ) -> dict[str, Any]:
        stdin = warm.proc.stdin
        if stdin is None:
            raise RuntimeError("no stdin")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        warm.pending[rid] = future
        try:
            stdin.write(frame_line(frame).encode("utf-8"))
            await stdin.drain()
            return await asyncio.wait_for(future, timeout=timeout_s)
        finally:
            warm.pending.pop(rid, None)

    async def _read_stdout(self, warm: _WarmProcess) -> None:
        stream = warm.proc.stdout
        assert stream is not None
        while True:
            try:
                raw = await stream.readline()
            except ValueError as exc:
                if warm.lease is not None and not warm.lease.finished:
                    warm.lease.stdout.feed(exc)
                    continue
                log.info("agent runtimes: %s warm process sent an oversized line", self.runtime)
                continue
            if not raw:
                break
            lease = warm.lease
            if lease is not None and not lease.finished:
                lease.stdout.feed(raw)
                continue
            self._answer(warm, raw)
        code = await warm.proc.wait()
        if warm.lease is not None and len(warm.tasks) > 1:
            # The turn reports why the process ended from its stderr: let the
            # last lines arrive before the turn's streams close.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(warm.tasks[1]), timeout=2)
        for future in warm.pending.values():
            if not future.done():
                future.set_exception(RuntimeError(f"the process exited ({code})"))
        if warm.lease is not None:
            warm.lease.died(code)
        if self._procs.get(warm.key) is warm and warm.lease is None:
            log.info("agent runtimes: %s warm process for %s exited (%s)",
                     self.runtime, warm.key, code)

    def _answer(self, warm: _WarmProcess, raw: bytes) -> None:
        """A line outside any turn: the pool's own requests, else dropped."""
        try:
            obj = json.loads(raw)
        except ValueError:  # runtime diagnostics between turns are not ACP frames
            return
        if not isinstance(obj, dict):
            return
        future = warm.pending.get(str(obj.get("id"))) if "method" not in obj else None
        if future is not None and not future.done():
            if isinstance(obj.get("error"), dict):
                message = str(obj["error"].get("message") or "error")
                future.set_exception(RuntimeError(message))
            else:
                result = obj.get("result")
                future.set_result(result if isinstance(result, dict) else {})
            return
        if "method" in obj and obj.get("id") is not None:
            # A request with no turn to answer it (a late permission ask).
            reply = {
                "jsonrpc": "2.0",
                "id": obj.get("id"),
                "error": {"code": -32601, "message": "no turn is running"},
            }
            stdin = warm.proc.stdin
            if stdin is not None and not stdin.is_closing():
                with contextlib.suppress(OSError, RuntimeError):
                    stdin.write(frame_line(reply).encode("utf-8"))

    async def _read_stderr(self, warm: _WarmProcess) -> None:
        stream = warm.proc.stderr
        assert stream is not None
        while True:
            try:
                raw = await stream.readline()
            except ValueError:
                continue  # one oversized diagnostic line: dropped
            if not raw:
                return
            lease = warm.lease
            if lease is not None and not lease.finished:
                lease.stderr.feed(raw)
            else:
                text = raw.decode("utf-8", errors="replace").rstrip()
                if text:
                    warm.stderr_tail.append(text)

    # ------------------------------------------------------------ lifecycle

    def _returned(
        self, warm: _WarmProcess, lease: Lease, session: str, want: SessionWant
    ) -> None:
        if warm.lease is lease:
            warm.lease = None
        warm.last_used = time.monotonic()
        if session and warm.alive():
            warm.session, warm.session_key, warm.session_fresh = session, want.key, False
        else:
            warm.session, warm.session_key, warm.session_fresh = "", "", False

    def _discard(self, warm: _WarmProcess, reason: str) -> None:
        """Synchronous retire, for a lease killed from a timer or callback."""
        if self._procs.get(warm.key) is warm:
            del self._procs[warm.key]
        _kill_now(warm)
        with contextlib.suppress(RuntimeError):  # no running loop: nothing to reap on
            task = asyncio.get_running_loop().create_task(_drained(warm))
            self._draining.add(task)
            task.add_done_callback(self._draining.discard)
        log.info("agent runtimes: %s warm process for %s ended: %s",
                 self.runtime, warm.key, reason)

    async def _retire(self, warm: _WarmProcess, reason: str) -> None:
        if self._procs.get(warm.key) is warm:
            del self._procs[warm.key]
        if warm.lease is not None:
            warm.lease.died(-9)
        stdin = warm.proc.stdin
        if warm.proc.returncode is None and stdin is not None and not stdin.is_closing():
            # An ACP agent ends when its stdin closes; give it a moment.
            stdin.close()
            try:
                await asyncio.wait_for(warm.proc.wait(), timeout=3)
            except TimeoutError:
                log.debug("agent runtimes: %s warm process ignored EOF", self.runtime)
        _kill_now(warm)
        await _drained(warm)
        log.info("agent runtimes: %s warm process for %s stopped: %s",
                 self.runtime, warm.key, reason)

    async def _make_room(self) -> None:
        # Only idle processes whose key nobody is working on right now.
        idle = [
            w for w in self._procs.values()
            if w.lease is None and not self._lock(w.key).locked()
        ]
        while len(self._procs) >= MAX_WARM and idle:
            oldest = min(idle, key=lambda w: w.last_used)
            idle.remove(oldest)
            await self._retire(oldest, "too many warm processes")

    def _ensure_reaper(self) -> None:
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.get_running_loop().create_task(self._reap_idle())

    async def _reap_idle(self) -> None:
        while self._procs:
            await asyncio.sleep(60)
            now = time.monotonic()
            for key, warm in list(self._procs.items()):
                if warm.lease is not None:
                    continue
                if not warm.alive() or now - warm.last_used > IDLE_STOP_S:
                    async with self._lock(key):
                        if self._procs.get(key) is warm and warm.lease is None:
                            await self._retire(warm, "idle")


def _kill_now(warm: _WarmProcess) -> None:
    if warm.proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            warm.proc.kill()
    # Whatever the runtime started (MCP servers, shell children) goes with it.
    warm.tree.close()
    warm.tracker.close()


async def _drained(warm: _WarmProcess) -> None:
    """Wait for a killed process and its pipe readers, so no pipe outlives them."""
    with contextlib.suppress(TimeoutError, ProcessLookupError, OSError):
        await asyncio.wait_for(warm.proc.wait(), timeout=5)
    readers = [task for task in warm.tasks if task is not asyncio.current_task()]
    if not readers:
        return
    _done, pending = await asyncio.wait(readers, timeout=2)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _rpc(rid: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
