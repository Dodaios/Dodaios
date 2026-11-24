"""Record each order a coding thread takes: where it ran, on what, and how it ended.

``ChatThreads`` tells the recorder when a thread has taken an order
(:func:`note_submission`). From then until that turn ends the recorder reads
the thread's own events and writes one row per run into ``verification.db``:

* at the start, what the run is bound to: the repository and commit of its
  folder, the domain its brief points at, the requested model and effort, and
  the version of the CLI the turn starts on;
* at the end, how the turn ended, what it cost, which model really answered and
  which domain the changed files belong to.

Every run is judged; there is no switch. When its turn ends, the changed files
go through the deterministic checks (:mod:`gates`), GitHub is asked what
became of its commit (:mod:`evidence`), and :mod:`driver` decides what follows
until the run has a verdict. ``[rsi] enabled`` and ``[rsi] verify`` are no
longer read.

Whether a run is *held* is a question of the coding policy it is bound to
(``Policy.hold``, :mod:`dodaios.rsi.policy`), asked per run:

* **A run that holds** behaves as the old ``verify = "enforce"``: the lead's
  job is over only with the verdict, and a finding brings one follow-up order
  to the same thread (:mod:`send`), within the driver's limits.
* **A run that does not hold** (the factory policy) changes nothing the person
  sees: the lead's job ends with the turn, and nothing is sent to the agent.
  Where the driver would have sent a follow-up order or asked for a review,
  the recorder writes a step that says which one was withheld and why, and the
  run reaches its verdict from the evidence. Its checks are waited for in this
  thread, up to the policy's limit. When the thread takes a new order or the
  person writes into it meanwhile, the run is *detached*: it stops reading the
  thread and is still decided from the commit it left behind.

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
from dodaios.rsi.policy import Policy

from . import driver, evidence, review, send
from .store import CHECKING, ENDED, INTERRUPTED, RUNNING, VerificationStore

log = logging.getLogger(__name__)

__all__ = [
    "AFTER_SIGNALS", "RunRecorder", "holds_policy", "install", "note_submission", "recorder",
    "set_recorder",
]

#: The event kinds a run's record is built from; everything else is ignored inline.
_KINDS: Final[frozenset[str]] = frozenset(
    {"turn_started", "turn_finished", "context_usage", "session_updated", "user_message"}
)
#: How far back the catch-up read looks in a thread's log.
_CATCH_UP_EVENTS: Final[int] = 2_000
_STOP: Final[object] = object()
#: Hours after a verified run's end at which its merged work is read again, to
#: catch a regression that turned up after the verdict (the plan's W = 72 h).
LEAK_CHECKS_H: Final[tuple[int, ...]] = (24, 72)
#: The writer thread wakes for due evidence no sooner and no later than this.
_MIN_WAIT_S: Final[float] = 1.0
_MAX_WAIT_S: Final[float] = 300.0
#: How long the writer thread waits for the chat service to take a follow-up order.
_SEND_TIMEOUT_S: Final[float] = 60.0
_REASON_MAX: Final[int] = 600
#: How many runs' "does it hold" answers are kept for the inline questions.
_HOLDING_KEPT: Final[int] = 4_096
#: Why an order the driver wanted was not given.
_NOT_HELD: Final[str] = "the run's coding policy does not hold it"
#: Why an order is not given to a run whose thread moved on to other work.
_MOVED_ON: Final[str] = "the thread moved on to other work"
#: How much of the person's message a step keeps.
_SAID_KEPT: Final[int] = 300
#: The signals the watch after a verdict records, as run columns.
AFTER_SIGNALS: Final[tuple[str, ...]] = (
    "leaked", "taken_over", "asked_again", "pr_closed", "reverted",
)


def holds_policy(text: Any) -> bool:
    """True when the frozen policy text of a run holds it. Never raises.

    No text, or one that does not parse, is the factory policy: it does not hold.
    """
    if not text:
        return False
    try:
        return Policy.from_text(str(text)).hold
    except Exception:  # noqa: BLE001 - an unreadable policy must never hold the person's work
        return False


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
        read_evidence: Callable[[str, str], evidence.Evidence] = evidence.read,
        clock: Callable[[], float] = time.time,
        send_follow_up: Callable[[str, str, str, int], str] | None = None,
        review_mode: str = "off",
        review_paid: bool = False,
        review_call: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
        policy_for: Callable[[str, str], dict[str, Any]] | None = None,
        snapshot: Callable[[str], str | None] | None = None,
    ) -> None:
        self.store = store
        self._service = service
        self._probe = probe
        self._describe = describe
        self._boot_id = boot_id
        #: ``(cell, request) -> run columns`` of the policy a run is bound to;
        #: ``dodaios.rsi.bind.binding_fields`` unless a test or host says otherwise.
        self._policy_for = policy_for
        self._read_evidence = read_evidence
        #: ``folder -> tree id`` of a checkout as it is now (a throwaway index;
        #: the folder is untouched). ``GitWorkspace.snapshot`` unless a test says otherwise.
        self._snapshot = snapshot
        self._clock = clock
        #: When the landing and checks of a run are read again (``run_id`` -> ms).
        self._due: dict[str, int] = {}
        #: When a run whose checks are waited for is decided at the latest.
        self._decide_at: dict[str, int] = {}
        #: When a verified run's merged work is read again for a regression.
        self._leak_at: dict[str, int] = {}
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
        #: Runs that do not hold, whose output is still being decided after the
        #: thread moved on (``run_id`` -> run). Writer thread only.
        self._background: dict[str, _Open] = {}
        #: Whether a run's policy holds it (``run_id`` -> bool), for the inline
        #: questions of the chat; guarded by ``_watched_lock``.
        self._holding: dict[str, bool] = {}
        self._thread: threading.Thread | None = None

    # ----------------------------------------------------- inline entry points

    def note_submission(
        self,
        *,
        job_id: str,
        session_id: str,
        prompt: str,
        started_ms: int,
        policy: dict[str, Any] | None = None,
    ) -> None:
        """A thread took an order. Inline: remembers the thread and queues the rest.

        ``policy`` is the binding the order was sent under, when the sender
        bound it first (a domain block went into the brief).
        """
        try:
            # The loop the chat service runs on: a follow-up order is sent on it.
            self._loop = asyncio.get_running_loop()
        except RuntimeError:  # called off the loop (a test, a script): keep what is known
            pass
        holding = holds_policy((policy or {}).get("policy_json"))
        with self._watched_lock:
            self._watched.add(session_id)
            self._noted.add(job_id)
            self._remember_hold(job_id, holding)
        self._queue.put(("start", job_id, session_id, prompt, int(started_ms), policy or {}))

    def is_noted(self, job_id: str) -> bool:
        """True for an order that was noted and whose run is not on record yet."""
        with self._watched_lock:
            return job_id in self._noted

    def holds(self, job_id: str) -> bool:
        """True when the run of ``job_id`` is held until its output was checked.

        Inline and cheap: answered from memory, never from the database. A run
        whose policy is not known here (not bound yet, or bound before an app
        restart and already over) does not hold.
        """
        with self._watched_lock:
            return self._holding.get(job_id, False)

    @property
    def judging(self) -> bool:
        """Every run is scanned, its evidence read and a verdict written. Always true."""
        return True

    def _remember_hold(self, job_id: str, holding: bool) -> None:
        """Keep whether ``job_id`` holds (caller holds ``_watched_lock``)."""
        self._holding[job_id] = holding
        if len(self._holding) > _HOLDING_KEPT:
            for old in list(self._holding)[: _HOLDING_KEPT // 4]:
                self._holding.pop(old, None)

    def _set_hold(self, job_id: str, holding: bool) -> None:
        with self._watched_lock:
            self._remember_hold(job_id, holding)

    def _run_holds(self, run_id: str, row: dict[str, Any] | None = None) -> bool:
        """Whether a run holds, from its record (writer thread)."""
        found = row if row is not None else (self.store.get(run_id) or {})
        return holds_policy(found.get("policy_json"))

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
        times = [*self._due.values(), *self._decide_at.values(), *self._leak_at.values()]
        if not times:
            # A run that is being checked shows it is alive at least this often.
            return _MAX_WAIT_S if any(run.checking for run in self._runs_open()) else None
        ahead = (min(times) - self._clock() * 1000) / 1000
        return min(max(ahead, _MIN_WAIT_S), _MAX_WAIT_S)

    def _runs_open(self) -> list[_Open]:
        """Every run not decided yet: those of a thread, and the detached ones."""
        return [*self._open.values(), *self._background.values()]

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

    def _start_run(
        self, job_id: str, session_id: str, prompt: str, started_ms: int,
        policy: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._bind(job_id, session_id, prompt, started_ms, policy or {})
        finally:
            with self._watched_lock:
                self._noted.discard(job_id)

    def _bind(
        self, job_id: str, session_id: str, prompt: str, started_ms: int,
        policy: dict[str, Any],
    ) -> None:
        earlier = self._open.get(session_id)
        # The run this order follows: the open one, or one already detached
        # when the order's turn started a moment before it was noted.
        previous = earlier or max(
            (r for r in self._background.values() if r.session_id == session_id),
            key=lambda r: r.started_ms, default=None,
        )
        asked = self._asked_again(previous, prompt, job_id) if previous is not None else ""
        if earlier is not None and earlier.checking and not (
            asked and self._run_holds(earlier.run_id)
        ):
            # Its turn is over: it is still decided from what it left behind,
            # while the thread takes the new order. A new, unrelated order is
            # not a verdict on it.
            self._detach(earlier, f"the thread took a new order ({job_id})")
        elif earlier is not None:
            # One thread runs one turn at a time: a new order means the earlier
            # run's end was never seen here, or its check is no longer wanted.
            del self._open[session_id]
            self._close(
                earlier, INTERRUPTED, "superseded", {"by": job_id}, time.time() * 1000,
                verdict=driver.SUPERSEDED, reason="the thread took a new order",
            )
        session = self._session(session_id)
        cwd = str(getattr(session, "cwd", "") or "")
        ref = self._describe(cwd) if cwd else repo_identity.RepoRef("", "", False)
        # A shared checkout: what it holds now, so the run's own change can be
        # told from what was there before (``gates.shared_area``).
        start_tree = self._take_snapshot(cwd) if cwd and not ref.isolated else ""
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
            start_tree=start_tree,
            **{k: v for k, v in policy.items() if k in ("policy_id", "arm", "policy_json")},
        )
        if not created:
            return  # this order is already on record (a repeated note)
        self.store.add_step(
            job_id, 0, "bound", detail={"domains": found, "source": source}, ts_ms=started_ms
        )
        run = _Open(run_id=job_id, session_id=session_id, started_ms=started_ms)
        self._open[session_id] = run
        with self._watched_lock:
            # Closing or detaching the earlier run let go of the thread.
            self._watched.add(session_id)
        self._catch_up(run)

    def _bind_policy(self, run: _Open, runner: str, line: str) -> None:
        """Freeze the run's policy (``rsi.bind``) once its cell is known: at its first turn."""
        if run.iteration:
            return
        row = self.store.get(run.run_id) or {}
        if row.get("policy_id"):
            return  # bound before (by the sender, or before an app restart)
        from dodaios.rsi import bind, selector

        cell = selector.cell_of({**row, "runner": runner, "harness_line": line})
        root = str(row.get("root_span_id") or run.run_id)
        fields = (self._policy_for or bind.binding_fields)(cell, root)
        self.store.update_run(run.run_id, **fields)
        self._set_hold(run.run_id, holds_policy(fields.get("policy_json")))

    def _detach(self, run: _Open, why: str) -> None:
        """A run that does not hold leaves its thread; its output is still decided.

        It reads no more of the thread's events: what comes now is someone
        else's. Its verdict comes from the scan and the commit it left behind.
        """
        if self._open.get(run.session_id) is run:
            del self._open[run.session_id]
        self._background[run.run_id] = run
        with self._watched_lock:
            if run.session_id not in self._open:
                self._watched.discard(run.session_id)
        self.store.add_step(
            run.run_id, run.iteration, "detached", turn_id=run.turn_id,
            detail={"why": why}, ts_ms=int(self._clock() * 1000),
        )

    def _resume(self) -> None:
        """Take runs an earlier boot left open back under watch, or close them."""
        for row in self.store.evidence_due():
            self._due[str(row["run_id"])] = int(row["evidence_due_ms"])
        for row in self.store.leak_due():
            self._leak_at[str(row["run_id"])] = int(row["leak_due_ms"])
        for row in self.store.open_runs():
            session_id = str(row["session_id"])
            holding = holds_policy(row.get("policy_json"))
            self._set_hold(str(row["run_id"]), holding)
            if row.get("state") == CHECKING and not holding:
                # Its turn is over and nothing waits for it: decided from what it
                # left behind, whatever the thread does now.
                run = self._background[str(row["run_id"])] = _Open(
                    run_id=str(row["run_id"]), session_id=session_id,
                    started_ms=int(row["started_ms"]), turn_id=str(row["turn_id"] or ""),
                    model_resolved=str(row["model_resolved"] or ""),
                    harness_version=str(row["harness_version"] or ""),
                    iteration=int(row.get("iteration") or 0), checking=True,
                )
                self._decide(run.run_id)
                continue
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
            if self._open.get(session_id) is run and run.checking:
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
                    if run.checking and not self._run_holds(run.run_id):
                        self._detach(run, "another turn started in the thread")
                    else:
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
                self._person_wrote(run, str(payload.get("text") or ""), int(ts_ms))
        elif kind == "turn_finished" and not run.checking and (
            not run.turn_id or turn_id == run.turn_id
        ):
            self._output_ended(run, payload, ts_ms)

    # ------------------------------------------------- what the person did next

    def _person_wrote(self, run: _Open, text: str, at: int) -> None:
        """The person wrote into the run's thread. Writer thread; sends nothing.

        In the middle of the turn, or as a correction, a repeat or an undo of
        the result, it is a takeover: a negative outcome on the run. A new and
        unrelated request after the result is not; the run is still judged
        from its own commit.
        """
        holding = self._run_holds(run.run_id)
        if not run.checking:
            self._taken_over(
                run, "", "the person wrote into the thread while it worked", text, at,
                midturn=True,
            )
            if holding:
                # The thread is the person's from here on: no check, no order.
                self._finish(run, driver.SUPERSEDED, "the person wrote into the thread")
            # Else the turn runs on: its end, cost and scan are still recorded,
            # and the driver ends the run as superseded.
            return
        row = self.store.get(run.run_id) or {}
        kind = _follow_up_kind(str(row.get("brief_text") or ""), text)
        if not kind:
            self._detach(run, "the person wrote a new request into the thread")
            return
        self._taken_over(
            run, kind, f"the person's next message reads as a {kind} of the result", text, at
        )
        if holding:
            self._finish(run, driver.SUPERSEDED, f"the person took the result over ({kind})")
        else:
            self._detach(run, f"the person took the result over ({kind})")

    def _taken_over(
        self, run: _Open, kind: str, why: str, text: str, at: int, *, midturn: bool = False
    ) -> None:
        """Record a takeover. Only one in the middle of the turn makes the person part
        of the run's own work (``person_intervened``); one after the result leaves
        the run judged from its commit, and the takeover counts against it."""
        if midturn:
            self.store.update_run(run.run_id, person_intervened=True, taken_over=True)
        else:
            self.store.update_run(run.run_id, taken_over=True)
        self.store.add_step(
            run.run_id, run.iteration, "taken_over", turn_id=run.turn_id, status=kind or "midturn",
            detail={"why": why, "kind": kind, "said": text[:_SAID_KEPT]}, ts_ms=at,
        )

    def _asked_again(self, earlier: _Open, prompt: str, job_id: str) -> str:
        """Mark ``earlier`` when the thread's new order repeats or corrects it. Returns the kind."""
        try:
            row = self.store.get(earlier.run_id) or {}
            kind = _follow_up_kind(str(row.get("brief_text") or ""), prompt)
            if kind:
                self._note_asked_again(earlier.run_id, int(row.get("iteration") or 0), kind,
                                       f"the next order ({job_id})", prompt)
            return kind
        except Exception:  # noqa: BLE001 - a missed signal leaves the record as it was
            log.warning("run recorder: next order of %s not read", earlier.run_id, exc_info=True)
            return ""

    def _note_asked_again(
        self, run_id: str, iteration: int, kind: str, source: str, text: str
    ) -> None:
        self.store.update_run(run_id, asked_again=True)
        self.store.add_step(
            run_id, iteration, "asked_again", status=kind,
            detail={"kind": kind, "source": source, "said": text[:_SAID_KEPT]},
            ts_ms=int(self._clock() * 1000),
        )

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
        """End a run for good without a check of its output (it was cut short)."""
        tokens_in, tokens_out, tokens_cached = _usage(payload or {})
        changed = self._changed_files(run) if state == ENDED else []
        judged = bool(verdict)
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

    def _let_go(self, run: _Open) -> None:
        if self._open.get(run.session_id) is run:
            del self._open[run.session_id]
        self._background.pop(run.run_id, None)
        with self._watched_lock:
            if run.session_id not in self._open:
                # A later run of the same thread still reads its events.
                self._watched.discard(run.session_id)
        self._decide_at.pop(run.run_id, None)

    def _tell(self, run: _Open) -> None:
        for listener in list(self._verdict_listeners):
            try:
                listener(run.run_id, run.session_id)
            except Exception:  # noqa: BLE001 - a listener's trouble is not the record's
                log.warning("run recorder: verdict listener failed", exc_info=True)

    # ------------------------------------------------------- judged output

    def _output_ended(self, run: _Open, payload: dict[str, Any], ts_ms: float) -> None:
        """A turn of a run ended: record it, check what it left, decide."""
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
                # This turn's own share, so a replay can cut the run at any output.
                "tokens_out": tokens_out,
                "cost_usd": _float(payload.get("cost_usd")),
                "duration_ms": _int(payload.get("duration_ms")),
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
            run = self._background.get(run_id)
        if run is None:
            return
        # A detached run's thread moved on: no order goes into it any more.
        moved_on = run_id in self._background
        holding = holds_policy(row.get("policy_json")) and not moved_on
        why_not = _MOVED_ON if moved_on else _NOT_HELD
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
        def decided(review_trigger: str) -> driver.Decision:
            return driver.decide(
                row,
                detail_of(is_scan, output),
                detail_of(evidence.is_step, output),
                now_ms=now,
                said=self._said(run.session_id),
                root_follow_ups=self.store.root_follow_ups(str(row.get("root_span_id") or "")),
                same_boot=str(row.get("boot_id") or "") == self._boot_id,
                previous_tree=str((before or {}).get("tree_id") or ""),
                reviewed=reviewed,
                review_trigger=review_trigger,
                review_budget=spent,
                self_checks=detail_of(lambda step: step.get("step") == "self_checks", output),
            )

        decision = decided(trigger)
        if decision.action == driver.REVIEW and not holding:
            # A review is a model call made to steer the run; this run is not
            # steered. Judged as if no review were due.
            self._withheld(
                run, output, "review_withheld", {"trigger": decision.reason}, now, why_not
            )
            decision = decided("")
        self.store.update_run(run_id, heartbeat_ms=now)
        if decision.action == driver.FOLLOW_UP and not holding:
            self._withheld(
                run, output, "follow_up_withheld",
                {
                    "template": decision.template, "signature": decision.signature,
                    "reason": decision.reason, "prompt": decision.prompt,
                },
                now, why_not,
            )
            self._finish(
                run, driver.FAILED,
                f"{decision.reason}; no follow-up order was sent because {why_not}",
                now_ms=now,
            )
        elif decision.action == driver.WAIT:
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

    def _withheld(
        self, run: _Open, output: int, step: str, detail: dict[str, Any], now: int,
        why: str = _NOT_HELD,
    ) -> None:
        """Record an order the driver wanted and the run does not get."""
        self.store.add_step(
            run.run_id, output, step, turn_id=run.turn_id, status="withheld",
            detail={**detail, "why": why}, ts_ms=now,
        )

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
        if verdict != driver.SUPERSEDED:
            self._watch_after(run.run_id, now)

    # ------------------------------------------------- the watch after a verdict

    def _watch_after(self, run_id: str, now: int, after_h: int = LEAK_CHECKS_H[0]) -> None:
        """Look at a judged run again later: what the person and the repository did next.

        At 24 and 72 hours after its end (``LEAK_CHECKS_H``): whether its merged
        work turned red (a leak), its pull request was closed without merging,
        its commit was reverted, or the person corrected or repeated the
        request in the thread. Each is a step and a column the selector reads.
        """
        row = self.store.get(run_id) or {}
        due = int(row.get("ended_ms") or now) + after_h * 3600 * 1000
        self.store.update_run(run_id, leak_due_ms=due)
        self._leak_at[run_id] = due

    def read_leaks(self, now_ms: int | None = None) -> int:
        """Run the watch after the verdict where it is due. Returns how many runs were read.

        Reads only: GitHub (one call, for a run with a commit on it), ``git log``
        in the run's folder, and the thread's record. Never sends anything; a
        failure leaves the record as it was.
        """
        now = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        asked = 0
        for run_id in [r for r, due in self._leak_at.items() if due <= now]:
            self._leak_at.pop(run_id, None)
            try:
                row = self.store.get(run_id) or {}
                asked += 1
                transient = self._look_again(row, now)
                ended = int(row.get("ended_ms") or now)
                later = [h for h in LEAK_CHECKS_H if ended + h * 3600 * 1000 > now]
                if later or transient:
                    due = ended + later[0] * 3600 * 1000 if later else now + 3600 * 1000
                    self.store.update_run(run_id, leak_due_ms=due)
                    self._leak_at[run_id] = due
                else:
                    self.store.update_run(run_id, leak_due_ms=None)
            except Exception:  # noqa: BLE001 - the record keeps the verdict as it stood
                log.warning("run recorder: %s not looked at again", run_id, exc_info=True)
        return asked

    #: The generalised name of :meth:`read_leaks`.
    read_after = read_leaks

    def _look_again(self, row: dict[str, Any], now: int) -> bool:
        """One look after the verdict. True when GitHub could not answer (look again soon)."""
        run_id = str(row["run_id"])
        output = int(row.get("iteration") or 0)
        head = str(row.get("head_sha") or "")
        transient = False
        if head and str(row.get("landing") or "") in (
            evidence.PUSHED, evidence.PR_OPEN, evidence.PR_CLOSED, evidence.MERGED,
        ):
            try:
                found = self._read_evidence(str(row.get("repo_id") or ""), head)
            except Exception:  # noqa: BLE001 - GitHub out of reach: look again later
                log.info("run recorder: GitHub not read for %s", run_id, exc_info=True)
                found = None
                transient = True
            if found is not None:
                transient = bool(found.transient)
                merged_red = found.landing == evidence.MERGED and found.checks == evidence.FAILING
                if merged_red and row.get("verdict") == driver.VERIFIED and not row.get("leaked"):
                    self.store.update_run(run_id, leaked=True)
                    self.store.add_step(
                        run_id, output, "leak", status="failing", detail=found.to_detail(),
                        ts_ms=now,
                    )
                    log.warning(
                        "run recorder: %s was verified, and its merged work fails now", run_id
                    )
                if found.landing == evidence.PR_CLOSED and not row.get("pr_closed"):
                    self.store.update_run(run_id, pr_closed=True)
                    self.store.add_step(
                        run_id, output, "pr_closed", status="closed", detail=found.to_detail(),
                        ts_ms=now,
                    )
        if head and not row.get("reverted"):
            revert = _revert_of(str(row.get("workdir") or ""), head)
            if revert:
                self.store.update_run(run_id, reverted=True)
                self.store.add_step(
                    run_id, output, "reverted", status="reverted",
                    detail={"revert_sha": revert, "head_sha": head}, ts_ms=now,
                )
        if not row.get("asked_again") and not row.get("taken_over"):
            self._read_what_came_next(row)
        return transient

    def _read_what_came_next(self, row: dict[str, Any]) -> None:
        """The thread after the run: did the person (or the lead's next order) ask again?"""
        run_id, session_id = str(row["run_id"]), str(row["session_id"])
        brief = str(row.get("brief_text") or "")
        since = int(row.get("ended_ms") or 0)
        following = [
            r for r in self.store.runs(since_ms=since, limit=50)
            if str(r.get("session_id") or "") == session_id and str(r["run_id"]) != run_id
        ]
        until = min((int(r["started_ms"]) for r in following), default=None)
        nxt = min(following, key=lambda r: int(r["started_ms"]), default=None)
        if nxt is not None:
            kind = _follow_up_kind(brief, str(nxt.get("brief_text") or ""))
            if kind:
                self._note_asked_again(
                    run_id, int(row.get("iteration") or 0), kind,
                    f"the next order ({nxt['run_id']})", str(nxt.get("brief_text") or ""),
                )
                return
        for event in self._events(session_id):
            at = int(event.get("ts_ms") or 0)
            if at <= since or (until is not None and at >= until):
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event.get("kind") != "user_message" or payload.get("author") or payload.get(
                "steered"
            ):
                continue
            text = str(payload.get("text") or "")
            kind = _follow_up_kind(brief, text)
            if kind:
                self._note_asked_again(
                    run_id, int(row.get("iteration") or 0), kind, "the person", text
                )
                return

    def tick(self, now_ms: int | None = None) -> None:
        """What the writer thread does when nothing was queued: read and decide what is due."""
        now = int(self._clock() * 1000) if now_ms is None else int(now_ms)
        self.read_due(now)
        self.read_leaks(now)
        for run_id in [run_id for run_id, due in self._decide_at.items() if due <= now]:
            self._decide_at.pop(run_id, None)
            try:
                self._decide(run_id, now)
            except Exception:  # noqa: BLE001 - the run stays open; the next tick tries again
                log.warning("run recorder: %s not decided", run_id, exc_info=True)
        for run in self._runs_open():
            if run.checking:
                # Whoever waits for the run sees that its check is alive.
                self.store.update_run(run.run_id, heartbeat_ms=now)

    def _take_snapshot(self, folder: str) -> str:
        """The tree id of ``folder`` as it is now, or ``""``. Never raises."""
        try:
            if self._snapshot is None:
                from dodaios.agent_chat.team.workspace import GitWorkspace

                self._snapshot = GitWorkspace().snapshot
            return str(self._snapshot(folder) or "")
        except Exception:  # noqa: BLE001 - without it the run is recorded as unattributed
            log.warning("run recorder: no snapshot of %s", folder, exc_info=True)
            return ""

    def _neighbours(self, row: dict[str, Any]) -> dict[str, list[str]]:
        """Files each other run open in the same shared checkout meanwhile touched."""
        from . import gates

        if row.get("isolated") or not row.get("start_tree"):
            return {}
        now = int(self._clock() * 1000)
        out: dict[str, list[str]] = {}
        for other in self.store.neighbours(
            str(row["run_id"]), str(row.get("workdir") or ""),
            int(row.get("started_ms") or 0), int(row.get("ended_ms") or now),
        ):
            began = int(other.get("started_ms") or 0)
            until = int(other.get("ended_ms") or now)
            events = [
                e for e in self._events(str(other["session_id"]))
                if int(e.get("ts_ms") or 0) <= until
            ]
            touched = gates.written_paths(events, began)
            for step in self.store.steps(str(other["run_id"])):
                if step.get("step") == "gates":
                    touched += list((step.get("detail") or {}).get("paths") or [])
            out[str(other["run_id"])] = touched
        return out

    def _check_output(self, run: _Open) -> None:
        """Scan what the ended output left behind, and read its first evidence."""
        from . import gates, self_checks

        try:
            row = self.store.get(run.run_id) or {}
            events = self._events(run.session_id)
            result = gates.check_run(
                row, events, snapshot=self._snapshot,
                reported=gates.written_paths(events, run.started_ms),
                neighbours=self._neighbours(row),
            )
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
            # What the agent's own checks said: read from its record, never run here.
            own = self_checks.read(events, run.started_ms)
            self.store.add_step(
                run.run_id, run.iteration, "self_checks", turn_id=run.turn_id,
                status="passed" if own["passed"] else "not_passed", detail=own,
                ts_ms=int(self._clock() * 1000),
            )
        except Exception:  # noqa: BLE001 - without it the run is judged on the rest
            log.warning("run recorder: own checks of %s not read", run.run_id, exc_info=True)
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
        elif not head or head in (str(result.area.base or ""), str(row.get("base_sha") or "")):
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


def _follow_up_kind(request: str, text: str) -> str:
    """``repeat``, ``correction``, ``undo`` or ``""`` for a message after a result."""
    from dodaios.evals.agent_score.signals import follow_up_kind

    try:
        return follow_up_kind(request, text)
    except Exception:  # noqa: BLE001 - an unreadable message is no signal
        log.debug("run recorder: message not classified", exc_info=True)
        return ""


def _revert_of(folder: str, head: str) -> str:
    """The commit that reverted ``head`` in ``folder``'s repository, or ``""``. Reads only."""
    if not folder or not head or not Path(folder).is_dir():
        return ""
    from .gates import _git

    found = _git(
        folder, "log", "--all", "-F", f"--grep=This reverts commit {head}", "--format=%H",
        "-n", "1",
    )
    return found.splitlines()[0].strip() if found else ""


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


def note_submission(
    *,
    job_id: str,
    session_id: str,
    prompt: str,
    started_ms: int,
    policy: dict[str, Any] | None = None,
) -> None:
    """Tell the recorder a thread took an order. A no-op while recording is off."""
    current = _recorder
    if current is None:
        return
    try:
        current.note_submission(
            job_id=job_id, session_id=session_id, prompt=prompt, started_ms=started_ms,
            policy=policy,
        )
    except Exception:  # noqa: BLE001 - recording must never fail the hand-off
        log.warning("run recorder: order %s not noted", job_id, exc_info=True)


def _install_workdirs(store: VerificationStore, service: Any, section: Any) -> None:
    """Serve thread folders: restore worktrees put away earlier, make new ones on request.

    New worktrees are made only with ``[rsi] worktree_per_run = true`` (off by
    default). A worktree made earlier and put away is restored for its thread
    either way.
    """
    from . import workdir

    making = bool(getattr(section, "worktree_per_run", False))

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


def _install_policies(
    made: RunRecorder,
    store: VerificationStore,
    data_dir: Path | str,
    self_change: Callable[[], Any] | None,
) -> None:
    """Bind runs to the stored coding policies, and let the trainer change them.

    Without the policy store every run is bound to the factory policy, which
    does not hold: the chat runs as before.
    """
    try:
        from dodaios.rsi import bind
        from dodaios.rsi.policy import store_for

        policies = store_for(data_dir)
        bind.set_store(policies)
        if self_change is not None:
            from dodaios.rsi.trainer import Trainer

            # Steering policies change only through measured, reversible self-changes.
            made.add_verdict_listener(Trainer(store, policies, self_change).on_verdict)
    except Exception:  # noqa: BLE001 - unbound runs are judged under the factory policy
        log.warning("run recorder: coding policies unavailable", exc_info=True)


def install(
    service: Any,
    data_dir: Path | str,
    config: Any,
    *,
    self_change: Callable[[], Any] | None = None,
) -> RunRecorder | None:
    """Start run recording and judging for ``service``. There is no switch.

    ``[rsi] enabled`` and ``[rsi] verify`` are not read any more (an old config
    that sets them still loads). Whether a run is held is its coding policy's
    question (``Policy.hold``); the factory policy does not hold. Returns the
    recorder, or ``None`` when it could not start: the chat then runs as
    without it.
    """
    section = getattr(config, "rsi", None)
    try:
        from dodaios.orchestrator.jobs import BOOT_ID

        store = VerificationStore(Path(data_dir) / "verification.db")
        made = RunRecorder(
            store, service, boot_id=BOOT_ID,
            review_mode=str(getattr(section, "review", "off") or "off"),
            review_paid=bool(getattr(section, "review_paid", False)),
        )
    except Exception:  # noqa: BLE001 - a recorder that cannot start leaves the chat as it was
        log.warning("run recorder: not started", exc_info=True)
        return None
    # Before the first verdict: a run picked up again may be decided at once.
    _install_policies(made, store, data_dir, self_change)
    try:
        service.add_event_listener(made.on_event)
        made.start()
    except Exception:  # noqa: BLE001 - a recorder that cannot start leaves the chat as it was
        log.warning("run recorder: not started", exc_info=True)
        remove = getattr(service, "remove_event_listener", None)
        if callable(remove):
            try:
                remove(made.on_event)
            except Exception:  # noqa: BLE001 - nothing more to undo
                log.debug("run recorder: listener not removed", exc_info=True)
        return None
    set_recorder(made)
    try:
        _install_workdirs(store, service, section)
    except Exception:  # noqa: BLE001 - threads then run in the folder they were given
        log.warning("run recorder: thread folders not served", exc_info=True)
    log.info("run recorder: recording delegated coding runs to %s", store.path)
    return made
