"""Record each order a coding thread takes: where it ran, on what, and how it ended.

``ChatThreads`` tells the recorder when a thread has taken an order
(:func:`note_submission`). From then until that turn ends the recorder reads
the thread's own events and writes one row per run into ``verification.db``:

* at the start, what the run is bound to: the repository and commit of its
  folder, the domain its brief points at, the requested model and effort, and
  the version of the CLI the turn starts on;
* at the end, how the turn ended, what it cost, which model really answered and
  which domain the changed files belong to.

With ``[rsi] verify = "observe"`` the changed files of an ended run are also
put through the deterministic checks (:mod:`gates`) and the result is recorded.
Nothing here sends a prompt or holds a turn.

The chat service calls listeners inline on its emit path, so :meth:`on_event`
and :meth:`note_submission` only put an item on a queue; one daemon thread does
the reading (``git``, the CLI's version, the stores). A failure in that thread
is logged and dropped: the record is best effort, the turn it describes is not.

A turn's first events are usually stored before the order is noted (the note
follows the send). The recorder therefore starts every run by reading the
thread's stored events from the order's time on, and skips anything it has
already seen when the live events arrive. The same read picks a run up again
after an app restart.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dodaios.rsi import domains, harness_probe, repo_identity

from .store import ENDED, INTERRUPTED, VerificationStore

log = logging.getLogger(__name__)

__all__ = ["RunRecorder", "install", "note_submission", "recorder", "set_recorder"]

#: The event kinds a run's record is built from; everything else is ignored inline.
_KINDS: Final[frozenset[str]] = frozenset(
    {"turn_started", "turn_finished", "context_usage", "session_updated", "user_message"}
)
#: How far back the catch-up read looks in a thread's log.
_CATCH_UP_EVENTS: Final[int] = 2_000
_STOP: Final[object] = object()


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _usage(payload: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """``(tokens_in, tokens_out, tokens_cached)`` of a ``turn_finished`` payload."""
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    cached = usage.get(
        "cache_read_input_tokens", usage.get("cached_input_tokens", usage.get("cached_tokens"))
    )
    return (
        _int(usage.get("input_tokens", usage.get("prompt_tokens"))),
        _int(usage.get("output_tokens", usage.get("completion_tokens"))),
        _int(cached),
    )


@dataclass(slots=True)
class _Open:
    """A run whose turn has not ended yet (writer thread only)."""

    run_id: str
    session_id: str
    started_ms: int
    turn_id: str = ""
    model_resolved: str = ""
    harness_version: str = ""
    last_seq: int = 0


class RunRecorder:
    """Writes ``runs`` and ``steps`` for the coding threads of one chat service."""

    def __init__(
        self,
        store: VerificationStore,
        service: Any,
        *,
        probe: Callable[[str], harness_probe.Harness] = harness_probe.for_runner,
        describe: Callable[[str], repo_identity.RepoRef] = repo_identity.describe,
        boot_id: str = "",
        verify: str = "off",
    ) -> None:
        self.store = store
        self._service = service
        self._probe = probe
        self._describe = describe
        self._boot_id = boot_id
        #: ``observe``: scan what an ended run left behind and record the result.
        self._verify = verify
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._watched: set[str] = set()
        self._watched_lock = threading.Lock()
        self._open: dict[str, _Open] = {}
        self._thread: threading.Thread | None = None

    # ----------------------------------------------------- inline entry points

    def note_submission(
        self, *, job_id: str, session_id: str, prompt: str, started_ms: int
    ) -> None:
        """A thread took an order. Inline: remembers the thread and queues the rest."""
        with self._watched_lock:
            self._watched.add(session_id)
        self._queue.put(("start", job_id, session_id, prompt, int(started_ms)))

    def on_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Chat-service listener. Inline: queues the events a run's record needs."""
        if event.get("kind") not in _KINDS:
            return
        with self._watched_lock:
            if session_id not in self._watched:
                return
        self._queue.put(("event", session_id, event))

    # ------------------------------------------------------------ the thread

    def start(self) -> None:
        """Start the writer thread and pick up runs an earlier boot left open."""
        if self._thread is not None:
            return
        self._queue.put(("resume",))
        self._thread = threading.Thread(target=self._drain, name="run-recorder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=5)
        self._thread = None

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            self._handle(item)

    def process_pending(self) -> int:
        """Handle everything queued so far in the calling thread (tests, shutdown)."""
        handled = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:  # the queue is drained: that is the end, not a failure
                return handled
            if item is _STOP:
                continue
            self._handle(item)
            handled += 1

    def _handle(self, item: tuple[Any, ...]) -> None:
        try:
            if item[0] == "start":
                self._start_run(*item[1:])
            elif item[0] == "event":
                self._apply(item[1], item[2])
            elif item[0] == "resume":
                self._resume()
        except Exception:  # noqa: BLE001 - the record is best effort, never the turn's problem
            log.warning("run recorder: %s not recorded", item[0], exc_info=True)

    # --------------------------------------------------------------- reading

    def _session(self, session_id: str) -> Any | None:
        return self._service.store.get_session(session_id)

    def _events(self, session_id: str) -> list[dict[str, Any]]:
        return self._service.store.list_events(session_id, tail=_CATCH_UP_EVENTS) or []

    @staticmethod
    def _job(job_id: str) -> Any | None:
        from dodaios.orchestrator import jobs

        return jobs.get_ledger().get(job_id)

    # --------------------------------------------------------------- writing

    def _start_run(self, job_id: str, session_id: str, prompt: str, started_ms: int) -> None:
        earlier = self._open.pop(session_id, None)
        if earlier is not None:
            # One thread runs one turn at a time: a new order means the earlier
            # run's end was never seen here.
            self._close(earlier, INTERRUPTED, "superseded", {"by": job_id}, time.time() * 1000)
        session = self._session(session_id)
        cwd = str(getattr(session, "cwd", "") or "")
        ref = self._describe(cwd) if cwd else repo_identity.RepoRef("", "", False)
        found, main, source = domains.pre_classify(prompt)
        job = self._job(job_id)
        created = self.store.start_run(
            job_id,
            session_id,
            root_span_id=str(getattr(job, "root_span_id", "") or ""),
            owner_session=str(getattr(job, "owner_session", "") or ""),
            owner_turn=str(getattr(job, "owner_turn", "") or ""),
            repo_id=ref.repo_id,
            workdir=cwd,
            isolated=ref.isolated,
            base_sha=ref.base_sha,
            brief_text=prompt,
            domains_json=found,
            primary_domain=main,
            domain_source=source,
            provider=str(getattr(session, "provider", "") or ""),
            model_requested=str(getattr(session, "model", "") or ""),
            effort=str(getattr(session, "effort", "") or ""),
            boot_id=self._boot_id,
            started_ms=started_ms,
        )
        if not created:
            return  # this order is already on record (a repeated note)
        self.store.add_step(
            job_id, 0, "bound", detail={"domains": found, "source": source}, ts_ms=started_ms
        )
        run = _Open(run_id=job_id, session_id=session_id, started_ms=started_ms)
        self._open[session_id] = run
        self._catch_up(run)

    def _resume(self) -> None:
        """Take runs an earlier boot left open back under watch, or close them."""
        for row in self.store.open_runs():
            session_id = str(row["session_id"])
            if session_id in self._open:
                continue
            run = _Open(
                run_id=str(row["run_id"]),
                session_id=session_id,
                started_ms=int(row["started_ms"]),
                turn_id=str(row["turn_id"] or ""),
                model_resolved=str(row["model_resolved"] or ""),
                harness_version=str(row["harness_version"] or ""),
            )
            if self._session(session_id) is None:
                self._close(run, INTERRUPTED, "thread_gone", {}, time.time() * 1000)
                continue
            self._open[session_id] = run
            with self._watched_lock:
                self._watched.add(session_id)
            self._catch_up(run)

    def _catch_up(self, run: _Open) -> None:
        """Apply what the thread's log already holds for this run."""
        for event in self._events(run.session_id):
            if int(event.get("ts_ms") or 0) < run.started_ms:
                continue
            if event.get("kind") in _KINDS:
                self._apply(run.session_id, event)
            if self._open.get(run.session_id) is not run:
                return  # the log already held the end of the run

    def _apply(self, session_id: str, event: dict[str, Any]) -> None:
        run = self._open.get(session_id)
        if run is None:
            return
        seq = _int(event.get("seq")) or 0
        if seq and seq <= run.last_seq:
            return  # already applied by the catch-up read
        run.last_seq = max(run.last_seq, seq)
        kind = event.get("kind")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        ts_ms = float(event.get("ts_ms") or time.time() * 1000)
        turn_id = str(payload.get("turn_id") or "")
        if kind == "turn_started":
            if not run.turn_id and turn_id:
                self._turn_started(run, turn_id, payload, ts_ms)
        elif kind == "context_usage":
            model = str(payload.get("model") or "")
            if model and (not turn_id or turn_id == run.turn_id):
                run.model_resolved = model
        elif kind == "session_updated":
            model = str(payload.get("model") or "")
            if model and run.turn_id:
                # The thread moved to another model in the middle of this run.
                self.store.update_run(run.run_id, mixed_model=True)
                self.store.add_step(
                    run.run_id, 0, "model_switched", turn_id=run.turn_id,
                    detail={"model": model}, ts_ms=int(ts_ms),
                )
        elif kind == "user_message":
            # A message without an author is not the lead's and not the app's.
            # One steered into the turn can also be a watchdog nudge, so only a
            # plain message counts as the person stepping in.
            if not payload.get("author") and not payload.get("steered"):
                self.store.update_run(run.run_id, person_intervened=True)
        elif kind == "turn_finished" and (not run.turn_id or turn_id == run.turn_id):
            self._turn_finished(run, payload, ts_ms)

    def _turn_started(
        self, run: _Open, turn_id: str, payload: dict[str, Any], ts_ms: float
    ) -> None:
        run.turn_id = turn_id
        runner = str(payload.get("runner") or "")
        harness = self._probe(runner)
        run.harness_version = harness.version
        self.store.update_run(
            run.run_id,
            turn_id=turn_id,
            runner=runner,
            provider=str(payload.get("provider") or ""),
            model_requested=str(payload.get("model") or ""),
            effort=str(payload.get("effort") or ""),
            harness_version=harness.version,
            harness_line=harness.line,
        )
        self.store.add_step(
            run.run_id, 0, "turn_started", turn_id=turn_id, harness_version=harness.version,
            detail={"runner": runner, "model": str(payload.get("model") or "")},
            ts_ms=int(ts_ms),
        )

    def _turn_finished(self, run: _Open, payload: dict[str, Any], ts_ms: float) -> None:
        status = str(payload.get("status") or "")
        self._close(
            run, ENDED, "turn_finished",
            {"status": status, "error": str(payload.get("error") or "")[:400]}, ts_ms,
            payload=payload,
        )

    def _close(
        self,
        run: _Open,
        state: str,
        step: str,
        detail: dict[str, Any],
        ts_ms: float,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        payload = payload or {}
        tokens_in, tokens_out, tokens_cached = _usage(payload)
        changed = self._changed_files(run) if state == ENDED else []
        self.store.update_run(
            run.run_id,
            state=state,
            turn_status=str(payload.get("status") or ""),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cached=tokens_cached,
            cost_usd=_float(payload.get("cost_usd")),
            wall_ms=_int(payload.get("duration_ms")),
            model_resolved=run.model_resolved,
            domain_post=domains.primary(changed) if changed else "",
            ended_ms=int(ts_ms),
        )
        self.store.add_step(
            run.run_id, 0, step, turn_id=run.turn_id, model_resolved=run.model_resolved,
            harness_version=run.harness_version, status=str(detail.get("status") or state),
            detail={**detail, "changed_files": len(changed)}, ts_ms=int(ts_ms),
        )
        if self._open.get(run.session_id) is run:
            del self._open[run.session_id]
        with self._watched_lock:
            self._watched.discard(run.session_id)
        if state == ENDED and self._verify == "observe":
            self._check_output(run)

    def _check_output(self, run: _Open) -> None:
        """Scan what the ended run left behind. Recorded only; nothing is sent."""
        from . import gates

        try:
            row = self.store.get(run.run_id) or {}
            result = gates.check_run(row, self._events(run.session_id))
            self.store.update_run(
                run.run_id,
                gate_status=result.status,
                churn_lines=result.churn if result.area is not None else None,
                tree_id=result.tree_id,
            )
            self.store.add_step(
                run.run_id, 0, "gates", turn_id=run.turn_id, status=result.status,
                detail=result.to_detail(),
            )
        except Exception:  # noqa: BLE001 - an unscanned run stays recorded as it ended
            log.warning("run recorder: output of %s not scanned", run.run_id, exc_info=True)

    def _changed_files(self, run: _Open) -> list[str]:
        from dodaios.society.coding_threads import changed_files

        try:
            return changed_files(self._events(run.session_id), run.turn_id)
        except Exception:  # noqa: BLE001 - the domain after the fact is a nicety
            log.debug("run recorder: changed files of %s unreadable", run.run_id, exc_info=True)
            return []


# ----------------------------------------------------------- process wiring

_recorder: RunRecorder | None = None


def recorder() -> RunRecorder | None:
    """The process recorder, or ``None`` while run recording is off."""
    return _recorder


def set_recorder(value: RunRecorder | None) -> None:
    """Replace the process recorder (tests, an embedding host)."""
    global _recorder
    _recorder = value


def note_submission(*, job_id: str, session_id: str, prompt: str, started_ms: int) -> None:
    """Tell the recorder a thread took an order. A no-op while recording is off."""
    current = _recorder
    if current is None:
        return
    try:
        current.note_submission(
            job_id=job_id, session_id=session_id, prompt=prompt, started_ms=started_ms
        )
    except Exception:  # noqa: BLE001 - recording must never fail the hand-off
        log.warning("run recorder: order %s not noted", job_id, exc_info=True)


def install(service: Any, data_dir: Path | str, config: Any) -> RunRecorder | None:
    """Start run recording for ``service`` when ``[rsi] enabled`` is set.

    Returns the recorder, or ``None`` when recording is off or could not start.
    """
    section = getattr(config, "rsi", None)
    if section is None or not getattr(section, "enabled", False):
        return None
    try:
        from dodaios.orchestrator.jobs import BOOT_ID

        store = VerificationStore(Path(data_dir) / "verification.db")
        made = RunRecorder(
            store, service, boot_id=BOOT_ID, verify=str(getattr(section, "verify", "off"))
        )
        service.add_event_listener(made.on_event)
        made.start()
    except Exception:  # noqa: BLE001 - a recorder that cannot start leaves the chat as it was
        log.warning("run recorder: not started", exc_info=True)
        return None
    set_recorder(made)
    log.info("run recorder: recording delegated coding runs to %s", store.path)
    return made
