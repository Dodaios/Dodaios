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
put through the deterministic checks (:mod:`gates`), GitHub is asked what
became of its commit (:mod:`evidence`), and the result is recorded. Nothing is
sent and no turn is held.

With ``verify = "enforce"`` a run is not over when its turn ends. It stays
open while its output is checked, and :mod:`driver` decides what follows: the
run is over (with a verdict), its checks are waited for, or one follow-up order
goes to the same thread (:mod:`send`) and the run goes on with the next turn.
The recorder never looks at an agent while it works: it acts when a turn has
ended and when evidence that was still open is read again.

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

import asyncio
import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dodaios.rsi import domains, harness_probe, repo_identity

from . import driver, evidence, review, send
from .store import CHECKING, ENDED, INTERRUPTED, RUNNING, VerificationStore

log = logging.getLogger(__name__)

__all__ = ["RunRecorder", "install", "note_submission", "recorder", "set_recorder"]

#: The event kinds a run's record is built from; everything else is ignored inline.
_KINDS: Final[frozenset[str]] = frozenset(
    {"turn_started", "turn_finished", "context_usage", "session_updated", "user_message"}
)
#: How far back the catch-up read looks in a thread's log.
_CATCH_UP_EVENTS: Final[int] = 2_000
_STOP: Final[object] = object()
#: The writer thread wakes for due evidence no sooner and no later than this.
_MIN_WAIT_S: Final[float] = 1.0
_MAX_WAIT_S: Final[float] = 300.0
#: How long the writer thread waits for the chat service to take a follow-up order.
_SEND_TIMEOUT_S: Final[float] = 60.0
_REASON_MAX: Final[int] = 600


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
    #: Which output of the run this is: 0, then 1 after the first follow-up order.
    iteration: int = 0
    #: The turn a follow-up order started; the next ``turn_started`` must be it.
    expect_turn: str = ""
    #: The newest output ended and what it left is being checked.
    checking: bool = False


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
        read_evidence: Callable[[str, str], evidence.Evidence] = evidence.read,
        clock: Callable[[], float] = time.time,
        send_follow_up: Callable[[str, str, str, int], str] | None = None,
        review_mode: str = "off",
        review_paid: bool = False,
        review_call: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self._service = service
        self._probe = probe
        self._describe = describe
        self._boot_id = boot_id
        #: ``observe``: scan what an ended run left behind and record the result.
        self._verify = verify
        self._read_evidence = read_evidence
        self._clock = clock
        #: When the landing and checks of a run are read again (``run_id`` -> ms).
        self._due: dict[str, int] = {}
        #: When a run whose checks are waited for is decided at the latest.
        self._decide_at: dict[str, int] = {}
        #: ``(session, order, run, output) -> turn id``; raises ``send.Refused``.
        self._send_follow_up = send_follow_up or self._send_via_service
        #: ``triggered``: an output a fixed trigger picks gets one model's review.
        self._review_mode = review_mode
        self._review_paid = review_paid
        #: ``(run row, scan detail) -> review detail``; blocks while the review runs.
        self._review_call = review_call or self._review_via_service
        self._verdict_listeners: list[Callable[[str, str], None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._watched: set[str] = set()
        #: Orders noted inline whose run the writer thread has not written yet.
        self._noted: set[str] = set()
        self._watched_lock = threading.Lock()
        self._open: dict[str, _Open] = {}
        self._thread: threading.Thread | None = None

    # ----------------------------------------------------- inline entry points

    def note_submission(
        self, *, job_id: str, session_id: str, prompt: str, started_ms: int
    ) -> None:
        """A thread took an order. Inline: remembers the thread and queues the rest."""
        try:
            # The loop the chat service runs on: a follow-up order is sent on it.
            self._loop = asyncio.get_running_loop()
        except RuntimeError:  # called off the loop (a test, a script): keep what is known
            pass
        with self._watched_lock:
            self._watched.add(session_id)
            self._noted.add(job_id)
        self._queue.put(("start", job_id, session_id, prompt, int(started_ms)))

    def is_noted(self, job_id: str) -> bool:
        """True for an order that was noted and whose run is not on record yet."""
        with self._watched_lock:
            return job_id in self._noted

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
            try:
                item = self._queue.get(timeout=self._wait_s())
            except queue.Empty:  # nothing was queued: what is due gets its turn
                self.tick()
                continue
            if item is _STOP:
                return
            self._handle(item)

    def _wait_s(self) -> float | None:
        """How long the thread may sleep: until the next evidence is due, else for good."""
        times = [*self._due.values(), *self._decide_at.values()]
        if not times:
            # A run that is being checked shows it is alive at least this often.
            return _MAX_WAIT_S if any(run.checking for run in self._open.values()) else None
        ahead = (min(times) - self._clock() * 1000) / 1000
        return min(max(ahead, _MIN_WAIT_S), _MAX_WAIT_S)

    @property
    def enforcing(self) -> bool:
        """True when a run stays open until its output was checked."""
        return self._verify == "enforce"

    def add_verdict_listener(self, listener: Callable[[str, str], None]) -> None:
        """Call ``listener(run_id, session_id)`` when a run got its verdict.

        Called on the writer thread: a listener hands over, it does not work.
        """
        if listener not in self._verdict_listeners:
            self._verdict_listeners.append(listener)

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
        try:
            self._bind(job_id, session_id, prompt, started_ms)
        finally:
            with self._watched_lock:
                self._noted.discard(job_id)

    def _bind(self, job_id: str, session_id: str, prompt: str, started_ms: int) -> None:
        earlier = self._open.pop(session_id, None)
        if earlier is not None:
            # One thread runs one turn at a time: a new order means the earlier
            # run's end was never seen here, or its check is no longer wanted.
            self._close(
                earlier, INTERRUPTED, "superseded", {"by": job_id}, time.time() * 1000,
                verdict=driver.SUPERSEDED, reason="the thread took a new order",
            )
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

    def _bind_policy(self, run: _Open, runner: str, line: str) -> None:
        """Freeze the run's policy (``rsi.bind``) once its cell is known: at its first turn."""
        if not self.enforcing or run.iteration:
            return
        row = self.store.get(run.run_id) or {}
        if row.get("policy_id"):
            return  # bound before (a run picked up again after a restart)
        from dodaios.rsi import bind, selector

        cell = selector.cell_of({**row, "runner": runner, "harness_line": line})
        root = str(row.get("root_span_id") or run.run_id)
        self.store.update_run(run.run_id, **bind.binding_fields(cell, root))

    def _resume(self) -> None:
        """Take runs an earlier boot left open back under watch, or close them."""
        if self._verify != "off":
            for row in self.store.evidence_due():
                self._due[str(row["run_id"])] = int(row["evidence_due_ms"])
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
                iteration=int(row.get("iteration") or 0),
                checking=row.get("state") == CHECKING,
            )
            if self._session(session_id) is None:
                self._close(
                    run, INTERRUPTED, "thread_gone", {}, time.time() * 1000,
                    verdict=driver.UNVERIFIED, reason="the thread was deleted",
                )
                continue
            if run.iteration and not run.checking:
                # A follow-up order was sent; its turn may not have been seen yet.
                sent = next(
                    (
                        str(step.get("turn_id") or "")
                        for step in reversed(self.store.steps(run.run_id))
                        if step.get("step") == "follow_up_sent"
                    ),
                    "",
                )
                if sent and sent != run.turn_id:
                    run.turn_id, run.expect_turn = "", sent
            self._open[session_id] = run
            with self._watched_lock:
                self._watched.add(session_id)
            self._catch_up(run, self._seen_until(run, row))
            if self.enforcing and self._open.get(session_id) is run and run.checking:
                # The app stopped while this output was being checked.
                self._decide(run.run_id)

    def _seen_until(self, run: _Open, row: dict[str, Any]) -> int | None:
        """Up to when the thread's log is already in the record of a run picked up again."""
        if run.checking:
            return int(row.get("ended_ms") or 0) or None
        if run.iteration:
            sent = [
                int(step.get("ts_ms") or 0)
                for step in self.store.steps(run.run_id)
                if step.get("step") == "follow_up_intent"
            ]
            return max(sent) if sent else None
        return None

    def _catch_up(self, run: _Open, after_ms: int | None = None) -> None:
        """Apply what the thread's log already holds for this run.

        ``after_ms``: only what came later than that (a run picked up again
        after its first output must not read its earlier turns as news).
        """
        for event in self._events(run.session_id):
            at = int(event.get("ts_ms") or 0)
            if at < run.started_ms or (after_ms is not None and at <= after_ms):
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
            if run.checking or (run.expect_turn and turn_id and turn_id != run.expect_turn):
                # A turn nobody here started: the thread is someone else's now.
                if turn_id and turn_id != run.turn_id:
                    self._finish(run, driver.SUPERSEDED, "another turn started in the thread")
            elif not run.turn_id and turn_id:
                run.expect_turn = ""
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
                    run.run_id, run.iteration, "model_switched", turn_id=run.turn_id,
                    detail={"model": model}, ts_ms=int(ts_ms),
                )
        elif kind == "user_message":
            # A message without an author is not the lead's and not the app's.
            # One steered into the turn can also be a watchdog nudge, so only a
            # plain message counts as the person stepping in.
            if not payload.get("author") and not payload.get("steered"):
                self.store.update_run(run.run_id, person_intervened=True)
                if self.enforcing:
                    # The thread is the person's from here on: no check, no order.
                    self._finish(run, driver.SUPERSEDED, "the person wrote into the thread")
        elif kind == "turn_finished" and not run.checking and (
            not run.turn_id or turn_id == run.turn_id
        ):
            if self.enforcing:
                self._output_ended(run, payload, ts_ms)
            else:
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
        try:
            self._bind_policy(run, runner, harness.line)
        except Exception:  # noqa: BLE001 - an unbound run runs under the code's own limits
            log.warning("run recorder: no policy bound to %s", run.run_id, exc_info=True)
        self.store.add_step(
            run.run_id, run.iteration, "turn_started", turn_id=turn_id,
            harness_version=harness.version,
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
        verdict: str = "",
        reason: str = "",
    ) -> None:
        """End a run for good. ``verdict`` is recorded only while output is enforced."""
        tokens_in, tokens_out, tokens_cached = _usage(payload or {})
        changed = self._changed_files(run) if state == ENDED else []
        judged = self.enforcing and bool(verdict)
        fields: dict[str, Any] = {"state": state, "model_resolved": run.model_resolved}
        if payload is not None or not run.iteration:
            # A run ended without a turn's end on record keeps what its
            # earlier turns cost.
            payload = payload or {}
            fields |= {
                "turn_status": str(payload.get("status") or ""),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_cached": tokens_cached,
                "cost_usd": _float(payload.get("cost_usd")),
                "wall_ms": _int(payload.get("duration_ms")),
                "domain_post": domains.primary(changed) if changed else "",
                "ended_ms": int(ts_ms),
            }
        if judged:
            fields |= {"verdict": verdict, "verdict_reason": reason[:_REASON_MAX]}
        self.store.update_run(run.run_id, **fields)
        self.store.add_step(
            run.run_id, run.iteration, step, turn_id=run.turn_id,
            model_resolved=run.model_resolved, harness_version=run.harness_version,
            status=str(detail.get("status") or state),
            detail={**detail, "changed_files": len(changed)}, ts_ms=int(ts_ms),
        )
        self._let_go(run)
        if judged:
            self._tell(run)
        if state == ENDED and self._verify == "observe":
            self._check_output(run)

    def _let_go(self, run: _Open) -> None:
        if self._open.get(run.session_id) is run:
            del self._open[run.session_id]
        with self._watched_lock:
            self._watched.discard(run.session_id)
        self._decide_at.pop(run.run_id, None)

    def _tell(self, run: _Open) -> None:
        for listener in list(self._verdict_listeners):
            try:
                listener(run.run_id, run.session_id)
            except Exception:  # noqa: BLE001 - a listener's trouble is not the record's
                log.warning("run recorder: verdict listener failed", exc_info=True)

    # ------------------------------------------------------- enforced output

    def _output_ended(self, run: _Open, payload: dict[str, Any], ts_ms: float) -> None:
        """A turn of an enforced run ended: record it, check what it left, decide."""
        row = self.store.get(run.run_id) or {}
        tokens_in, tokens_out, tokens_cached = _usage(payload)
        changed = self._changed_files(run)
        status = str(payload.get("status") or "")
        self.store.update_run(
            run.run_id,
            state=CHECKING,
            turn_status=status,
            # A run's cost is that of all its turns.
            tokens_in=_plus(row.get("tokens_in"), tokens_in),
            tokens_out=_plus(row.get("tokens_out"), tokens_out),
            tokens_cached=_plus(row.get("tokens_cached"), tokens_cached),
            cost_usd=_plus(row.get("cost_usd"), _float(payload.get("cost_usd"))),
            wall_ms=_plus(row.get("wall_ms"), _int(payload.get("duration_ms"))),
            model_resolved=run.model_resolved,
            domain_post=domains.primary(changed) if changed else str(row.get("domain_post") or ""),
            ended_ms=int(ts_ms),
            heartbeat_ms=int(self._clock() * 1000),
        )
        self.store.add_step(
            run.run_id, run.iteration, "turn_finished", turn_id=run.turn_id,
            model_resolved=run.model_resolved, harness_version=run.harness_version,
            status=status,
            detail={
                "status": status, "error": str(payload.get("error") or "")[:400],
                "changed_files": len(changed),
            },
            ts_ms=int(ts_ms),
        )
        run.checking = True
        if status == "done":
            self._check_output(run)
        self._decide(run.run_id)

    def _decide(self, run_id: str, now_ms: int | None = None) -> None:
        """Ask :mod:`driver` what follows the newest output of ``run_id``, and do it."""
        row = self.store.get(run_id)
        if row is None or row.get("state") != CHECKING:
            return
        run = self._open.get(str(row["session_id"]))
        if run is None or run.run_id != run_id:
            return
        now = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        output = int(row.get("iteration") or 0)
        steps = self.store.steps(run_id)

        def detail_of(wanted: Callable[[dict[str, Any]], bool], at: int) -> dict[str, Any] | None:
            for step in reversed(steps):
                if int(step.get("iteration") or 0) == at and wanted(step):
                    return step.get("detail") or {}
            return None

        def is_scan(step: dict[str, Any]) -> bool:
            return step.get("step") == "gates"

        before = detail_of(is_scan, output - 1) if output else None
        scan = detail_of(is_scan, output) or {}
        reviewed = detail_of(lambda step: step.get("step") == "review", output)
        started = any(
            step.get("step") == "review_intent" and int(step.get("iteration") or 0) == output
            for step in steps
        )
        if reviewed is None and started:
            # Started and never answered (the app stopped meanwhile): no second call.
            reviewed = {"verdict": review.NONE, "reason": "the review did not finish"}
        trigger = ""
        if self._review_mode == "triggered":
            trigger = review.trigger(run_id, output, scan, list(scan.get("paths") or []))
        spent = review.budget(
            root_reviews=self.store.root_reviews(str(row.get("root_span_id") or "")),
            day_reviews=self.store.reviews_since(review.day_window(now)),
        ) if trigger else ""
        decision = driver.decide(
            row,
            detail_of(is_scan, output),
            detail_of(evidence.is_step, output),
            now_ms=now,
            said=self._said(run.session_id),
            root_follow_ups=self.store.root_follow_ups(str(row.get("root_span_id") or "")),
            same_boot=str(row.get("boot_id") or "") == self._boot_id,
            previous_tree=str((before or {}).get("tree_id") or ""),
            reviewed=reviewed,
            review_trigger=trigger,
            review_budget=spent,
        )
        self.store.update_run(run_id, heartbeat_ms=now)
        if decision.action == driver.WAIT:
            ended = int(row.get("ended_ms") or now)
            ahead = [
                ended + after_s * 1000
                for after_s in (evidence.NO_CHECKS_GIVE_UP_S, driver.EVIDENCE_WAIT_S)
                if ended + after_s * 1000 > now
            ]
            # Decided again when the checks are read again, and at the latest then.
            self._decide_at[run_id] = min(ahead) if ahead else now
        elif decision.action == driver.FOLLOW_UP:
            self._follow_up(run, row, decision, now)
        elif decision.action == driver.REVIEW:
            self._review(run, row, scan, decision, now)
        else:
            self._finish(run, decision.verdict, decision.reason, now_ms=now)

    def _said(self, session_id: str) -> str:
        from dodaios.society.coding_threads import last_turn

        try:
            return str(last_turn(self._events(session_id))[1] or "")
        except Exception:  # noqa: BLE001 - without the closing line the checks still decide
            log.debug("run recorder: last answer of %s unreadable", session_id, exc_info=True)
            return ""

    def _follow_up(
        self, run: _Open, row: dict[str, Any], decision: driver.Decision, now: int
    ) -> None:
        """Send one follow-up order, exactly once: the intent is on record before it goes."""
        output = int(row.get("iteration") or 0)
        self.store.add_step(
            run.run_id, output, "follow_up_intent", status=decision.template,
            detail={
                "prompt": decision.prompt, "signature": decision.signature,
                "reason": decision.reason,
            },
            ts_ms=now,
        )
        try:
            turn_id = self._send_follow_up(run.session_id, decision.prompt, run.run_id, output)
        except send.Refused as exc:  # the thread is not the agent's: the run ends, said why
            self._finish(
                run, driver.FAILED,
                f"{decision.reason}; no follow-up order was sent because {exc}", now_ms=now,
            )
            return
        except Exception as exc:  # noqa: BLE001 - whether it went is unknown: never send twice
            log.warning("run recorder: follow-up to %s not confirmed", run.run_id, exc_info=True)
            self._finish(
                run, driver.FAILED,
                f"{decision.reason}; the follow-up order could not be confirmed "
                f"({type(exc).__name__})",
                now_ms=now,
            )
            return
        seen = json.loads(row.get("signatures_json") or "[]")
        self.store.update_run(
            run.run_id,
            state=RUNNING,
            iteration=output + 1,
            follow_ups=int(row.get("follow_ups") or 0) + 1,
            signatures_json=json.dumps([*seen, decision.signature]),
            evidence_due_ms=None,
            heartbeat_ms=now,
        )
        self.store.add_step(
            run.run_id, output, "follow_up_sent", turn_id=turn_id, status=decision.template,
            ts_ms=now,
        )
        self._due.pop(run.run_id, None)
        self._decide_at.pop(run.run_id, None)
        run.iteration, run.turn_id, run.expect_turn, run.checking = output + 1, "", turn_id, False

    def _review(
        self, run: _Open, row: dict[str, Any], scan: dict[str, Any], decision: driver.Decision,
        now: int,
    ) -> None:
        """One model's review of the newest output, then the decision again."""
        output = int(row.get("iteration") or 0)
        self.store.add_step(
            run.run_id, output, "review_intent", status="triggered",
            detail={"trigger": decision.reason}, ts_ms=now,
        )
        try:
            found = self._review_call(row, scan)
        except Exception as exc:  # noqa: BLE001 - a review that failed proves nothing
            log.warning("run recorder: review of %s failed", run.run_id, exc_info=True)
            found = {"verdict": review.NONE, "reason": f"the review failed ({type(exc).__name__})"}
        self.store.add_step(
            run.run_id, output, "review", status=str(found.get("verdict") or review.NONE),
            detail={**found, "trigger": decision.reason}, ts_ms=int(self._clock() * 1000),
        )
        self._decide(run.run_id)

    def _review_via_service(self, row: dict[str, Any], scan: dict[str, Any]) -> dict[str, Any]:
        """Run the review on the chat service's loop, from the writer thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return {"verdict": review.NONE, "reason": "no model could be reached for a review"}

        async def job() -> dict[str, Any]:
            seat = await asyncio.to_thread(
                review.pick_seat, str(row.get("provider") or ""), paid=self._review_paid
            )
            diff = await asyncio.to_thread(gates_diff, scan)
            found = await review.run(
                seat, brief=str(row.get("brief_text") or ""), diff=diff,
                findings=list(scan.get("findings") or []),
            )
            return found.to_detail()

        reviewing = asyncio.run_coroutine_threadsafe(job(), loop)
        return reviewing.result(timeout=review.REVIEW_TIMEOUT_S + _SEND_TIMEOUT_S)

    def _send_via_service(self, session_id: str, prompt: str, run_id: str, output: int) -> str:
        """Hand the order to the chat service on its own loop, from the writer thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            raise send.Refused("the chat service cannot be reached")
        sending = asyncio.run_coroutine_threadsafe(
            send.follow_up(self._service, session_id, prompt, run_id=run_id, iteration=output),
            loop,
        )
        return sending.result(timeout=_SEND_TIMEOUT_S)

    def _finish(
        self, run: _Open, verdict: str, reason: str, *, now_ms: int | None = None
    ) -> None:
        """The run is over: record how it was judged and tell who waits for it."""
        now = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        self.store.update_run(
            run.run_id, state=ENDED, verdict=verdict, verdict_reason=reason[:_REASON_MAX],
            heartbeat_ms=now,
        )
        self.store.add_step(
            run.run_id, run.iteration, "verdict", turn_id=run.turn_id, status=verdict,
            detail={"reason": reason}, ts_ms=now,
        )
        run.checking = False
        self._let_go(run)
        self._tell(run)

    def tick(self, now_ms: int | None = None) -> None:
        """What the writer thread does when nothing was queued: read and decide what is due."""
        now = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        self.read_due(now)
        for run_id in [run_id for run_id, due in self._decide_at.items() if due <= now]:
            self._decide_at.pop(run_id, None)
            try:
                self._decide(run_id, now)
            except Exception:  # noqa: BLE001 - the run stays open; the next tick tries again
                log.warning("run recorder: %s not decided", run_id, exc_info=True)
        for run in list(self._open.values()):
            if run.checking:
                # Whoever waits for the run sees that its check is alive.
                self.store.update_run(run.run_id, heartbeat_ms=now)

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
                run.run_id, run.iteration, "gates", turn_id=run.turn_id, status=result.status,
                detail=result.to_detail(), ts_ms=int(self._clock() * 1000),
            )
        except Exception:  # noqa: BLE001 - an unscanned run stays recorded as it ended
            log.warning("run recorder: output of %s not scanned", run.run_id, exc_info=True)
            return
        try:
            self._first_evidence(row, result)
        except Exception:  # noqa: BLE001 - a run without evidence stays "unverified"
            log.warning("run recorder: evidence of %s not read", run.run_id, exc_info=True)

    # -------------------------------------------------------------- evidence

    def _first_evidence(self, row: dict[str, Any], result: Any) -> None:
        """Right after the scan: what became of the commit the run left behind."""
        if result.area is None or not result.tree_id:
            return  # nothing could be pinned on the run, so no commit is its own
        run_id = str(row["run_id"])
        head = str(result.head_sha or "")
        self.store.update_run(run_id, head_sha=head)
        if not result.files:
            found = evidence.Evidence(
                evidence.NONE, evidence.NONE, head, reason="the run changed no file"
            )
        elif not head or head == str(result.area.base or ""):
            found = evidence.Evidence(
                evidence.NONE, evidence.NONE, head, reason="the work is not committed"
            )
        else:
            found = self._read_evidence(str(row.get("repo_id") or ""), head)
        self._note_evidence({**row, "head_sha": head}, found)

    def read_due(self, now_ms: int | None = None) -> int:
        """Read again what is due. Returns how many runs were asked about."""
        now = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        asked = 0
        for run_id in [run_id for run_id, due in self._due.items() if due <= now]:
            self._due.pop(run_id, None)
            try:
                row = self.store.get(run_id)
                if row is None or not row.get("head_sha"):
                    self.store.update_run(run_id, evidence_due_ms=None)
                    continue
                found = self._read_evidence(str(row.get("repo_id") or ""), str(row["head_sha"]))
                self._note_evidence(row, found, now_ms=now)
                asked += 1
                if row.get("state") == CHECKING:
                    self._decide(run_id, now)
            except Exception:  # noqa: BLE001 - the record keeps what was read before
                log.warning("run recorder: evidence of %s not read again", run_id, exc_info=True)
        return asked

    def _note_evidence(
        self, row: dict[str, Any], found: evidence.Evidence, *, now_ms: int | None = None
    ) -> None:
        run_id = str(row["run_id"])
        now = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        due = _next_read(found, int(row.get("ended_ms") or now), now)
        self.store.update_run(
            run_id, landing=found.landing, ci_status=found.checks, evidence_due_ms=due
        )
        if due is None:
            self._due.pop(run_id, None)
        else:
            self._due[run_id] = due
        output = int(row.get("iteration") or 0)
        earlier = [
            s for s in self.store.steps(run_id)
            if evidence.is_step(s) and int(s.get("iteration") or 0) == output
        ]
        detail = found.to_detail()
        if earlier and _same_evidence(earlier[-1].get("detail") or {}, detail):
            return  # nothing new to tell
        # One row per reading that told something new: "evidence", "evidence:1", ...
        name = "evidence" if not earlier else f"evidence:{len(earlier)}"
        self.store.add_step(
            run_id, output, name, status=f"{found.landing}/{found.checks}", detail=detail,
            ts_ms=now,
        )

    def _changed_files(self, run: _Open) -> list[str]:
        from dodaios.society.coding_threads import changed_files

        try:
            return changed_files(self._events(run.session_id), run.turn_id)
        except Exception:  # noqa: BLE001 - the domain after the fact is a nicety
            log.debug("run recorder: changed files of %s unreadable", run.run_id, exc_info=True)
            return []


def gates_diff(scan: dict[str, Any]) -> str:
    """The diff an output scan read (blocks on ``git``)."""
    from .gates import diff_of

    return diff_of(scan)


def _plus(before: Any, more: Any) -> Any:
    """Sum of two counts where either may be unknown."""
    if more is None:
        return before
    return more if before is None else before + more


def _next_read(found: evidence.Evidence, ended_ms: int, now_ms: int) -> int | None:
    """When ``found`` is to be read again, or ``None`` when the record keeps it."""
    if found.settled:
        return None
    waited_s = (now_ms - ended_ms) / 1000
    no_checks_yet = found.checks == evidence.NONE and found.landing in (
        evidence.PUSHED, evidence.MERGED,
    )
    if no_checks_yet and waited_s >= evidence.NO_CHECKS_GIVE_UP_S:
        return None  # CI would have started by now: the commit has no checks
    for after_s in evidence.RECHECK_AFTER_S:
        due = ended_ms + after_s * 1000
        if due > now_ms:
            return due
    return None


def _same_evidence(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = ("landing", "checks", "pr", "draft", "checked_sha", "failing")
    return all(before.get(key) == after.get(key) for key in keys)


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


def _install_workdirs(store: VerificationStore, service: Any, section: Any) -> None:
    """Give new threads a worktree of their own while their output is verified.

    With the setting off nothing new is made; a worktree made earlier and put
    away is still restored for its thread.
    """
    from . import workdir

    making = (
        bool(getattr(section, "enabled", False))
        and str(getattr(section, "verify", "off")) != "off"
        and bool(getattr(section, "worktree_per_run", False))
    )

    def idle_ms(session_id: str) -> int:
        if service.is_running(session_id):
            return 0
        session = service.store.get_session(session_id)
        if session is None:
            return 0
        last = max(
            int(getattr(session, "updated_ms", 0) or 0),
            int(getattr(session, "last_message_ms", 0) or 0),
        )
        return max(0, int(time.time() * 1000) - last)

    workdir.set_dirs(
        workdir.WorkDirs(
            store,
            thread_exists=lambda sid: service.store.get_session(sid) is not None,
            idle_ms=idle_ms,
            shared=getattr(section, "shared_checkout_repos", ()) or (),
            making=making,
        )
    )


def _restore_only(service: Any, data_dir: Path | str, section: Any) -> None:
    """Recording is off: keep restoring the worktrees that were put away while it was on."""
    path = Path(data_dir) / "verification.db"
    if not path.is_file():
        return
    try:
        store = VerificationStore(path)
        if store.workdirs_away() == 0:
            store.close()
            return
        _install_workdirs(store, service, section)
    except Exception:  # noqa: BLE001 - an unreadable record leaves the chat as it was
        log.warning("run recorder: worktrees put away earlier cannot be restored", exc_info=True)


def install(service: Any, data_dir: Path | str, config: Any) -> RunRecorder | None:
    """Start run recording for ``service`` when ``[rsi] enabled`` is set.

    Returns the recorder, or ``None`` when recording is off or could not start.
    """
    section = getattr(config, "rsi", None)
    if section is None or not getattr(section, "enabled", False):
        _restore_only(service, data_dir, section)
        return None
    try:
        from dodaios.orchestrator.jobs import BOOT_ID

        store = VerificationStore(Path(data_dir) / "verification.db")
        made = RunRecorder(
            store, service, boot_id=BOOT_ID, verify=str(getattr(section, "verify", "off")),
            review_mode=str(getattr(section, "review", "off") or "off"),
            review_paid=bool(getattr(section, "review_paid", False)),
        )
        service.add_event_listener(made.on_event)
        made.start()
    except Exception:  # noqa: BLE001 - a recorder that cannot start leaves the chat as it was
        log.warning("run recorder: not started", exc_info=True)
        return None
    set_recorder(made)
    _install_workdirs(store, service, section)
    if made.enforcing:
        from dodaios.rsi import bind
        from dodaios.rsi.policy import store_for

        bind.set_store(store_for(data_dir))
    log.info("run recorder: recording delegated coding runs to %s", store.path)
    return made
