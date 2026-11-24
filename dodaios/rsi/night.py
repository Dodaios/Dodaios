"""The night cycle: one round of the assistant improving itself.

While the person is away the kernel does, in this order:

1. **checks what is in effect.** Every change on trial, and the newest live
   ones, are compared with the assistant without them. What no longer pays is
   taken back. After an app update everything in effect is checked: the
   assistant as it ships has changed, so what was learned against the old one
   has to prove itself again.
2. **lets the learners propose.** Each gets practice tasks and nothing else.
3. **decides.** The gate measures every candidate on tasks no learner saw and
   lets it in or not.
4. **measures the learned advantage.** The assistant as it is now against the
   assistant as it ships, on the sealed tasks: the number the person sees.
5. **writes down what it did**, in ``bench.db`` (``nights``, ``series``).

Nothing is announced. The night is quiet: no notice, no sound, no voice.

    python -m dodaios.rsi.night --sandbox                # try it on the seed suite
    python -m dodaios.rsi.night --sandbox --plant recall.relative_floor=0.9 --nights 3

``--sandbox`` builds a throwaway installation that decides on the seed suite
and prints what each night did. It reads and changes nothing of a real one.

**What a night may spend.** Measuring the recall asks no model. The
``first_move`` and ``brief`` domains replay lead turns (one model call for a
first move, two for a brief); their limits are fixed in
:mod:`dodaios.rsi.budget`, not in a setting, shared by the two domains, and
asked before every call: only while the person is away (:data:`IDLE_AFTER_S`),
at most ``REPLAY_CALLS`` calls and :data:`BUDGET_SHARE` of a plan's usage
window a night, never above 80 % of a window, never on a key that bills per
token.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import dodaios
from dodaios.learners.lines import LineLearner
from dodaios.learners.tuner import Proposal, Trial, Tuner
from dodaios.rsi import lines as standing
from dodaios.rsi import overlay as overlays
from dodaios.rsi import params
from dodaios.rsi.bench import run, seedsuite
from dodaios.rsi.bench.model import NEEDS_MODEL, Domain, Role, Source, Split, Task
from dodaios.rsi.bench.recall import RecallWorld
from dodaios.rsi.bench.store import DB_NAME, BenchStore, PracticeView
from dodaios.rsi.budget import BUDGET_SHARE
from dodaios.rsi.gate.decide import LIVE, Decision, MeasuredGate
from dodaios.rsi.sequential import interval_of
from dodaios.self_change import Draft, SelfChangeRegistry, State, Surface

__all__ = [
    "BUDGET_SHARE",
    "EVERY_S",
    "IDLE_AFTER_S",
    "LINES",
    "MAX_MODEL_CALLS",
    "MODEL_PRACTICE",
    "RAMP_MODEL_CALLS",
    "Night",
    "NightReport",
    "NightService",
    "install",
    "sandbox",
]

log = logging.getLogger(__name__)

#: The person must have been away this long before a night starts.
IDLE_AFTER_S: Final[float] = 15 * 60
#: At most one night in this time.
EVERY_S: Final[float] = 20 * 3600
#: Model calls one night may make to build tasks. Fixed.
MAX_MODEL_CALLS: Final[int] = 8
#: The same while the person's own tasks are too few for the gate to decide on
#: (fewer than ``MIN_PAIRS`` in the select split): the first nights build more,
#: so the first decision comes in one or two nights instead of three or four.
RAMP_MODEL_CALLS: Final[int] = 24
#: For how long a value the gate turned down is not proposed again.
_SKIP_MS: Final[int] = 30 * 24 * 3600 * 1000
#: Practice tasks a learner tries a move on per night, in a domain that asks a
#: model: every try is a call, and the gate decides on other tasks anyway.
MODEL_PRACTICE: Final[int] = 12
TUNER: Final = "tuner"
LINES: Final = "lines"
_LOOP_KEY: Final = "loop"


@dataclass(slots=True)
class NightReport:
    ts_ms: int
    app: str
    #: The loop is stopped: nothing was done.
    paused: bool = False
    #: The app version of the night before, when it differs from this one.
    updated_from: str = ""
    #: Tasks in use per domain and split.
    tasks: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Tasks built this night from the person's own memory and messages.
    made: dict[str, Any] = field(default_factory=dict)
    settled: list[dict[str, Any]] = field(default_factory=list)
    proposed: list[dict[str, Any]] = field(default_factory=list)
    decided: list[dict[str, Any]] = field(default_factory=list)
    measured: list[dict[str, Any]] = field(default_factory=list)
    #: Model calls per domain that asks a model: made, allowed, and why they stopped.
    calls: dict[str, dict[str, Any]] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "paused": self.paused,
            "updated_from": self.updated_from,
            "tasks": self.tasks,
            "made": self.made,
            "settled": self.settled,
            "proposed": self.proposed,
            "decided": self.decided,
            "measured": self.measured,
            "calls": self.calls,
        }

    @property
    def idle(self) -> bool:
        """True when the night had nothing to work on."""
        made = any(
            self.made.get(k)
            for k in ("questions", "messages", "forgotten", "past_work", "lead_turns")
        )
        return not (made or self.settled or self.proposed or self.decided or self.measured)

    def lines(self) -> list[str]:
        """The night in plain words."""
        if self.paused:
            return ["The loop is stopped; nothing was done."]
        out: list[str] = []
        if self.updated_from:
            out.append(f"The app was updated ({self.updated_from} -> {self.app}): "
                       "everything learned was checked again.")
        new_tasks = int(self.made.get("questions") or 0) + int(self.made.get("messages") or 0)
        if new_tasks:
            out.append(
                f"Built {new_tasks} tasks from your own memory and messages "
                f"({self.made.get('calls', 0)} model calls)."
            )
        if self.made.get("forgotten"):
            out.append(f"Erased {self.made['forgotten']} tasks about memories that are gone.")
        if self.made.get("past_work"):
            out.append(f"Stored {self.made['past_work']} tasks from your past coding work.")
        if self.made.get("lead_turns"):
            out.append(f"Stored {self.made['lead_turns']} first-move tasks from your lead turns.")
        for domain, spent in self.calls.items():
            if spent.get("calls"):
                stop = f"; stopped: {spent['stopped']}" if spent.get("stopped") else ""
                out.append(f"Replayed {spent['calls']} {domain} tasks on the model{stop}.")
        for row in self.settled:
            if row["outcome"] == "kept" and row.get("was") == "live":
                continue  # what was live and stays live is not news
            out.append(f"Checked {row['target']}: {row['outcome']} ({row['evidence']['reason']}).")
        for row in self.proposed:
            out.append(f"Proposed {row['target']} = {row['value']}: {row['reason']}.")
        for row in self.decided:
            found = row["evidence"]
            numbers = ""
            if found.get("target"):
                t = found["target"]
                numbers = f" [{t['diff']:+.3f}, between {t['low']:+.3f} and {t['high']:+.3f}]"
            out.append(f"Measured {row['target']}: {row['outcome']}, {found['reason']}{numbers}.")
        for row in self.measured:
            out.append(
                f"Learned advantage in {row['domain']}: {row['diff']:+.3f} "
                f"(now {row['now_score']:.3f}, as shipped {row['factory_score']:.3f}, "
                f"{row['n']} sealed tasks; prompt {row['factory_tokens']:.0f} -> "
                f"{row['now_tokens']:.0f} tokens per task)."
            )
        return out or ["Nothing to do: there are no tasks to measure on yet."]


class Night:
    """One installation's night. ``sources`` says whose tasks decide (see the gate)."""

    def __init__(
        self,
        registry: SelfChangeRegistry,
        bench: BenchStore,
        worlds: Callable[[], run.Worlds],
        *,
        sources: Sequence[Source] = (Source.MINED, Source.MADE),
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
        learners: Sequence[str] = (TUNER, LINES),
        prepare: Callable[[], dict[str, Any]] | None = None,
        finish: Callable[[], None] | None = None,
    ) -> None:
        self.registry = registry
        #: Runs first in a night: copies the memory, builds tasks. Returns what it made.
        self._prepare = prepare
        #: Runs last: lets go of what ``prepare`` opened.
        self._finish = finish
        #: Which learners propose in a night. Checking and measuring happen regardless.
        self.learners = tuple(learners)
        self.bench = bench
        self.sources = tuple(sources)
        self._worlds = worlds
        self._clock = clock
        self.gate = MeasuredGate(registry, bench, worlds, sources=self.sources)
        store = params.installed()
        self._index = store.index if store is not None else params.INDEX
        self._tuner = Tuner(self._index)
        self._lines = LineLearner()

    # ---------------------------------------------------------------- state

    def paused(self) -> bool:
        return bool(self.bench.get_meta(_LOOP_KEY).get("paused"))

    def pause(self, paused: bool) -> None:
        """The person's stop. Nothing is proposed, measured or changed while it is set."""
        self.bench.set_meta(_LOOP_KEY, {**self.bench.get_meta(_LOOP_KEY), "paused": bool(paused)})

    def last_ms(self) -> int:
        return int(self.bench.get_meta(_LOOP_KEY).get("last_ms") or 0)

    def due(self) -> bool:
        return not self.paused() and self._clock() - self.last_ms() >= EVERY_S * 1000

    # ---------------------------------------------------------------- steps

    def _domains(self) -> list[Domain]:
        return [d for d in Domain if any(self.gate.tasks(d, split) for split in Split)]

    def _settle(self, everything: bool) -> list[Decision]:
        return self.gate.settle_all(newest=10_000 if everything else 5)

    def _recently_declined(self, author: str = TUNER) -> set[tuple[str, Any]]:
        since = self._clock() - _SKIP_MS
        skip: set[tuple[str, Any]] = set()
        for change in self.registry.store.list(since_ms=since, limit=2000):
            if change.surface is not Surface.PARAMETER or change.author != author:
                continue
            if change.state in (State.BLOCKED, State.REVERTED, State.PROPOSED):
                try:
                    skip.add((change.target, json.loads(change.after or "{}").get("value")))
                except ValueError:  # an unreadable text names no value to skip
                    continue
        return skip

    def _waiting(self, domain: Domain) -> bool:
        """A candidate of ``domain`` waits for its measurement."""
        for change in self.registry.candidates():
            param = self._index.get(change.target) if change.surface is Surface.PARAMETER else None
            if param is not None and domain.value in param.domains:
                return True
        return False

    def _propose(self, domain: Domain) -> dict[str, Any] | None:
        if not self.gate.can_decide(domain):
            return None  # nothing could decide on a proposal, so none is made
        model = domain in NEEDS_MODEL
        if model and self._waiting(domain):
            # Every measurement costs model calls: the one waiting is finished first.
            return None
        tasks = [
            t for t in PracticeView(self.bench).tasks(domain) if t.source in self.sources
        ]
        worlds = self._worlds()
        if model:
            if domain.value not in worlds:
                return None  # no seat to replay on tonight
            tasks = run.shuffled(tasks, f"practice:{domain.value}")[:MODEL_PRACTICE]
        if not tasks:
            return None
        store = self.bench if model and not self.bench.readonly else None

        def try_values(values: Mapping[str, Any]) -> Trial:
            overlay = overlays.Overlay(label="practice", params=dict(values))
            arm = run.arm_of(overlay, domain=domain, worlds=worlds)
            measured = run.measure(tasks, overlay, worlds, arm=arm, store=store)
            results = [r for r in measured if r.counts]
            if not results:
                return Trial(0.0, 0.0, 0)
            n = len(results)
            return Trial(sum(r.score for r in results) / n, sum(r.tokens for r in results) / n, n)

        switches = [
            name for name in standing.LEARNABLE if domain.value in self._index.by_name(name).domains
        ]
        found: Proposal | None = None
        author = ""
        if switches and LINES in self.learners:
            author = LINES
            current = {name: params.get(name) for name in switches}
            found = self._lines.propose(current, try_values, skip=self._recently_declined(LINES))
        elif not switches and TUNER in self.learners:
            author = TUNER
            found = self._tuner.propose(
                domain.value, params.values(), try_values, skip=self._recently_declined(TUNER)
            )
        if found is None:
            return None
        param = self._index.by_name(found.name)
        self.registry.propose(
            Draft(
                Surface.PARAMETER,
                param.name,
                params.text_for(param, found.value),
                author=author,
                reason=found.reason(),
            )
        )
        return {
            "target": param.name,
            "value": found.value,
            "current": found.current,
            "gain": found.gain,
            "cost_ratio": round(found.cost_ratio, 4),
            "reason": found.reason(),
            "learner": author,
        }

    def _advantage(self, domain: Domain, now_ms: int) -> dict[str, Any] | None:
        """The assistant as it is against the assistant as it ships, on the sealed tasks.

        Only tasks whose right answer is known count: a gain over what the person
        merely accepted is not a gain anyone can tell (``Role``).
        """
        tasks = run.shuffled(
            self.gate.tasks(domain, Split.SEALED, Role.GAIN), f"advantage:{domain.value}"
        )
        if not tasks:
            return None
        worlds = self._worlds()
        model = domain in NEEDS_MODEL
        if model and domain.value not in worlds:
            return None
        changes = self.registry.learned_ids()
        from dodaios.rsi import adopt

        # As it ships: no learned value, and none of the notes the assistant wrote itself.
        factory = overlays.Overlay(
            label="factory", factory=True, hidden_memories=adopt.memory_ids(self.registry)
        )
        shipped_arm = run.arm_of(factory, domain=domain, worlds=worlds)
        now_arm = run.arm_of(LIVE, changes=changes, domain=domain, worlds=worlds)
        if model and now_arm.id == shipped_arm.id:
            # Nothing learned touches what this domain replays: both sides are the
            # same assistant, the advantage is zero, and no call is spent on saying so.
            return None
        store = self.bench if model and not self.bench.readonly else None
        shipped = run.measure(tasks, factory, worlds, arm=shipped_arm, store=store)
        now = shipped
        if now_arm.id != shipped_arm.id:  # something is learned: the two can differ
            now = run.measure(tasks, LIVE, worlds, arm=now_arm, store=store)
        paired = run.pair(shipped, now)
        if paired.n == 0:
            return None
        found = interval_of(paired.differences)
        own = any(s is not Source.SEED for s in self.sources)
        return {
            "ts_ms": now_ms,
            "app": dodaios.__version__,
            "domain": domain.value,
            "split": Split.SEALED.value,
            "source": "own" if own else "seed",
            "now_score": round(paired.candidate_mean, 4),
            "factory_score": round(paired.baseline_mean, 4),
            "diff": round(found.mean, 4),
            "low": round(found.low, 4),
            "high": round(found.high, 4),
            "n": paired.n,
            "now_tokens": round(paired.candidate_tokens, 2),
            "factory_tokens": round(paired.baseline_tokens, 2),
            "arm_now": now_arm.id,
            "arm_factory": shipped_arm.id,
            "parts": run.parts(tasks, shipped, now),
        }

    # ------------------------------------------------------------------ run

    def run(self) -> NightReport:
        now_ms = self._clock()
        report = NightReport(ts_ms=now_ms, app=dodaios.__version__)
        if self.paused():
            report.paused = True
            return report
        if self.bench.readonly:  # a newer app owns the file: this one only watches
            return report
        state = self.bench.get_meta(_LOOP_KEY)
        before = str(state.get("app") or "")
        if before and before != dodaios.__version__:
            report.updated_from = before
        try:
            if self._prepare is not None:
                report.made = self._prepare()
            report.tasks = self.bench.counts()
            report.settled = [d.public() for d in self._settle(bool(report.updated_from))]
            for domain in self._domains():
                proposed = self._propose(domain)
                if proposed is not None:
                    report.proposed.append(proposed)
            report.decided = [d.public() for d in self.gate.consider_all()]
            for domain in self._domains():
                point = self._advantage(domain, now_ms)
                if point is not None:
                    report.measured.append(point)
            shared: dict[int, list[str]] = {}
            budgets: dict[int, Any] = {}
            for name, world in self._worlds().items():
                budget = getattr(world, "budget", None)
                if budget is not None:
                    shared.setdefault(id(budget), []).append(name)
                    budgets[id(budget)] = budget
            for key, names in shared.items():
                # Domains on one budget share its calls: they are reported once.
                budget = budgets[key]
                report.calls["+".join(names)] = {
                    "calls": budget.calls,
                    "cap": budget.cap,
                    "stopped": budget.stopped,
                }
        finally:
            if self._finish is not None:
                self._finish()
        if report.measured:
            self.bench.add_series(report.measured)
        self.bench.add_night(dodaios.__version__, report.public())
        self.bench.set_meta(
            _LOOP_KEY, {**state, "app": dodaios.__version__, "last_ms": now_ms}
        )
        return report


# ------------------------------------------------------------- in the app


class NightService:
    """Runs the installation's nights while a backend runs and the person is away.

    The backend is the desktop app while its window is open, and the windowless
    background service while it is closed (``dodaios.core.background_service``
    keeps the service for as long as :meth:`learning` holds). Both read and
    write the same ``bench.db``, registry and parameter files, so the app sees
    what the service did when it opens again.
    """

    #: How often the app looks whether a night is due.
    LOOK_EVERY_S: Final[float] = 10 * 60

    def __init__(
        self,
        night: Night,
        idle: Callable[[], bool],
        *,
        chat_db: Path | None = None,
        halt: threading.Event | None = None,
    ) -> None:
        self.night = night
        #: The person's chat record, for the page's "in daily use" part. Read-only.
        self.chat_db = chat_db
        self._idle = idle
        self._task: Any = None
        #: Set when the backend lets go (the app opens, the backend stops). The
        #: night's model calls read it: none starts after it, one in flight is cut.
        self._halt = halt if halt is not None else threading.Event()
        self._busy = threading.Event()
        self.last: NightReport | None = None

    # ---------------------------------------------------------------- state

    def learning(self) -> bool:
        """Nights are to come: the person has not stopped the loop and this app may write.

        An older app that meets a newer ``bench.db`` only watches (``readonly``):
        it has nothing to learn, so nothing to keep running for.
        """
        return not self.night.paused() and not self.night.bench.readonly

    @property
    def busy(self) -> bool:
        """A night is running right now."""
        return self._busy.is_set()

    @property
    def halted(self) -> bool:
        return self._halt.is_set()

    def halt(self) -> None:
        """Let go: no night starts any more, and a running one makes no more model calls.

        The running night's call in flight is cut (its result is void and not kept),
        every later step runs without a model, and the night ends by writing its
        report as usual, as when the person comes back (``budget``). Never blocks.
        """
        if not self._halt.is_set():
            self._halt.set()
            if self.busy:
                log.info("self-improvement: the running night stops its model calls")

    async def wind_down(self, within_s: float, *, poll_s: float = 0.25) -> bool:
        """:meth:`halt`, then wait at most ``within_s`` for a running night to end.

        ``True`` when no night is running any more.
        """
        import asyncio

        self.halt()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, within_s)
        # The flag is cleared by the night's worker thread, so it is polled.
        while self.busy and loop.time() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(poll_s)
        return not self.busy

    # ------------------------------------------------------------------ run

    def tick(self) -> NightReport | None:
        """Run a night when one is due and the person is away. Blocking; call it off the loop."""
        if self.halted or not self.night.due() or not self._idle():
            return None
        self._busy.set()
        try:
            self.last = self.night.run()
        finally:
            self._busy.clear()
        # One line in the log per night: names and numbers only, never a memory's words.
        log.info("self-improvement night: %s", " | ".join(self.last.lines()))
        return self.last

    async def _watch(self) -> None:
        import asyncio

        try:
            while True:
                await asyncio.sleep(self.LOOK_EVERY_S)
                try:
                    await asyncio.to_thread(self.tick)
                except Exception:  # noqa: BLE001 — a failed night never takes the app down
                    log.warning("self-improvement: the night failed", exc_info=True)
        finally:
            # The backend's loop ends (its tasks are cancelled before it waits for
            # its worker threads): a running night winds down instead of holding it.
            self.halt()

    def start(self) -> None:
        import asyncio

        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._watch())

    def stop(self) -> None:
        """The backend shuts down: no more looks, and a running night winds down (:meth:`halt`)."""
        self.halt()
        if self._task is not None:
            self._task.cancel()
            self._task = None


def _person_idle() -> bool:
    from dodaios.self_build.code.idle import person_idle

    return person_idle(IDLE_AFTER_S)


#: How long one task-building call may take.
_ASK_TIMEOUT_S: Final[float] = 240.0
#: How often a waiting call looks whether the night was halted.
_HALT_POLL_S: Final[float] = 0.5


def _model_ask(
    config: Any, loop: Any, halted: Callable[[], bool] | None = None
) -> Callable[[str, str], str | None]:
    """Ask the assistant's own provider, on its subscription or a local model, from a thread.

    Never a key that bills per token (``allow_metered=False``): without a
    subscription or a local model the answer is ``None`` and no tasks are made.
    Once ``halted`` answers true no call starts, and a call in flight is cancelled
    and answers ``None``: the maker then makes nothing more this night.
    """

    def ask(system: str, prompt: str) -> str | None:
        import asyncio

        from dodaios.memory.learning.review import ModelReviewer

        if loop is None or loop.is_closed() or (halted is not None and halted()):
            return None
        reviewer = ModelReviewer(
            config,
            system=lambda: system,
            parser=lambda text: text,
            max_tokens=1800,
            caller="rsi_tasks",
            allow_metered=False,
        )
        future = asyncio.run_coroutine_threadsafe(reviewer(prompt), loop)
        return _wait_for(future, halted)

    return ask


def _wait_for(
    future: concurrent.futures.Future[Any],
    halted: Callable[[], bool] | None,
    *,
    timeout_s: float = _ASK_TIMEOUT_S,
    poll_s: float = _HALT_POLL_S,
) -> str | None:
    """The call's answer, or ``None`` once the night is halted or the call ran out of time."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            answer = future.result(timeout=poll_s)
        except concurrent.futures.TimeoutError:  # still waiting: look at the halt and the clock
            if (halted is not None and halted()) or time.monotonic() >= deadline:
                future.cancel()
                return None
            continue
        return str(answer) if answer else None


def calls_tonight(bench: BenchStore) -> int:
    """How many model calls tonight's task building may make (``RAMP_MODEL_CALLS`` early on)."""
    from dodaios.rsi.gate.rules import MIN_PAIRS

    own = bench.tasks(Domain.RECALL, splits=(Split.SELECT,), source=Source.MADE)
    return RAMP_MODEL_CALLS if len(own) < MIN_PAIRS else MAX_MODEL_CALLS


def _past_work(
    bench: BenchStore, homes: dict[str, Path] | None = None, folders: list[str] | None = None
) -> dict[str, Any]:
    """Store the tasks from past coding work before their records are deleted. No model call.

    The coding CLIs delete a session's record after some weeks; a task that was
    stored stays (:mod:`dodaios.rsi.bench.past_work.intake`). Reads the records
    and the local clones only. ``folders`` gets the clones that were read.
    """
    if bench.readonly:
        return {}
    from dodaios.rsi.bench import past_work

    try:
        taken = past_work.take_in(bench, homes=homes, composed=past_work.logged_briefs())
    except Exception:  # noqa: BLE001 - a record or clone that cannot be read costs no night
        log.warning("self-improvement: tasks from past coding work not read", exc_info=True)
        return {}
    if folders is not None:
        folders[:] = taken.folders
    return {"past_work": taken.new, "past_work_retired": taken.retired}


def install(
    data_dir: Path, registry: SelfChangeRegistry, *, config: Any = None, loop: Any = None
) -> NightService:
    """The installation's own nights: they decide on the person's tasks, never on the seed suite.

    With ``config`` and the app's ``loop`` a night first copies the memory and
    builds tasks from the person's own memory and messages (a few model calls
    on the assistant's subscription). Without them, or until such tasks exist,
    a night finds nothing to measure and changes nothing.
    """
    from dodaios.memory.vault import runtime as vault_runtime
    from dodaios.rsi.bench.own.maker import OwnRecallMaker
    from dodaios.rsi.bench.own.world import LiveWorld

    home = Path(data_dir)
    bench = BenchStore(home / DB_NAME)
    halt = threading.Event()
    if config is None:
        return NightService(Night(registry, bench, lambda: {}), _person_idle, halt=halt)
    world = LiveWorld(vault_runtime.vault_path(config), home / "rsi")
    maker = OwnRecallMaker(
        bench, world, home / "agent_chat.db", _model_ask(config, loop, halt.is_set)
    )

    tonight: dict[str, Any] = {}

    def prepare() -> dict[str, Any]:
        clones: list[str] = []
        made = _past_work(bench, folders=clones)
        made.update(_lead(bench, home, loop, tonight, clones, halted=halt.is_set))
        if not world.refresh():
            return made
        from dodaios.rsi import adopt

        if world.vault is not None:
            adopt.how_tos(registry, world.vault)
        return {**maker.run(calls_tonight(bench)), **made}

    def worlds() -> run.Worlds:
        return {**world.worlds(), **tonight}

    def finish() -> None:
        _close_brief(tonight)
        tonight.clear()
        world.close()

    night = Night(registry, bench, worlds, prepare=prepare, finish=finish)
    return NightService(night, _person_idle, chat_db=home / "agent_chat.db", halt=halt)


def _close_brief(tonight: dict[str, Any]) -> None:
    """Remove tonight's scratch clones of the brief replay. Never fails a night."""
    from dodaios.rsi.bench import brief_replay

    world = tonight.get(brief_replay.WORLD)
    close = getattr(getattr(world, "checkout", None), "close", None)
    if callable(close):
        try:
            close()
        except OSError:  # a file still held open stays until the next night removes the folder
            log.info("self-improvement: a scratch clone was not removed", exc_info=True)


def _lead(
    bench: BenchStore,
    home: Path,
    loop: Any,
    tonight: dict[str, Any],
    clones: Sequence[str] = (),
    *,
    halted: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """first_move tasks from the lead's recorded turns, and tonight's replays. No model call here.

    The replay worlds are built for this night only (their budget is this
    night's, one for both) and only on the lead's plan
    (:mod:`dodaios.rsi.bench.lead_world`). ``clones`` are the person's clones
    the intake of past coding work read: a brief replay works on them.
    ``halted`` stops the replays' calls when the backend lets go.
    """
    from dodaios.rsi import lead_turns
    from dodaios.rsi.bench import brief_replay, lead_replay, lead_world
    from dodaios.rsi.bench.own import lead as own_lead

    if not (home / lead_turns.DB_NAME).is_file():
        return {}
    made: dict[str, Any] = {}
    try:
        turns = lead_turns.store(home / lead_turns.DB_NAME)
        rows, chat = own_lead.read(turns, home / "agent_chat.db")
        made = own_lead.take_in(bench, rows, chat, now_ms=int(time.time() * 1000))
        built = lead_world.build(
            home=home,
            turns=turns,
            loop=loop,
            idle=_person_idle,
            bench=bench,
            folders=clones,
            halted=halted,
        )
    except Exception:  # broad-except: an unreadable record costs the domain this night, no more
        log.warning("self-improvement: the lead's turns could not be read", exc_info=True)
        return made
    if built.world is not None:
        tonight[lead_replay.WORLD] = built.world
    else:
        made["lead_replay"] = built.reason
    if built.brief is not None:
        tonight[brief_replay.WORLD] = built.brief
    elif built.world is not None:
        made["brief_replay"] = built.brief_reason
    return made


# ------------------------------------------------------------------ sandbox


@dataclass(slots=True)
class Sandbox:
    """A throwaway installation: its own parameters, registry and benchmark file."""

    night: Night
    registry: SelfChangeRegistry
    bench: BenchStore
    store: params.ParamStore
    #: The seed memory, when the sandbox decides on the seed suite.
    world: seedsuite.SeedWorld | None = None

    def close(self) -> None:
        self.registry.close()
        self.bench.close()
        if self.world is not None:
            self.world.close()
        params.release(self.store)


def sandbox(
    data_dir: Path,
    *,
    plant: Mapping[str, Any] | None = None,
    learners: Sequence[str] = (TUNER,),
    tasks: Sequence[Task] | None = None,
    worlds: run.Worlds | None = None,
    sources: Sequence[Source] = (Source.SEED,),
) -> Sandbox:
    """Build a sandbox in ``data_dir``. ``plant`` puts values in effect as if learned earlier.

    By default it decides on the seed suite. ``tasks``, ``worlds`` and
    ``sources`` build it on other tasks instead.
    """
    store = params.install(data_dir)
    if store is None:  # ``install`` only answers None for ``None``
        raise RuntimeError("the sandbox could not open its parameter store")
    for name, value in (plant or {}).items():
        store.write(name, params.text_for(store.index.by_name(name), value))
    registry = SelfChangeRegistry(data_dir)
    registry.register_handler(Surface.PARAMETER, store)
    bench = BenchStore(Path(data_dir) / DB_NAME)
    world = None
    if tasks is None or worlds is None:
        world = seedsuite.build_world()
        tasks = seedsuite.recall_tasks()
        worlds = {seedsuite.SEED_WORLD: RecallWorld(world.vault, world.ids)}
    bench.put_tasks(tasks)
    found = worlds
    night = Night(registry, bench, lambda: found, sources=sources, learners=learners)
    return Sandbox(night, registry, bench, store, world)


def _plant(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in pairs:
        name, _, raw = item.partition("=")
        param = params.INDEX.by_name(name.strip())
        out[param.name] = param.coerce(json.loads(raw.strip()))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dodaios.rsi.night", description=__doc__)
    parser.add_argument("--sandbox", nargs="?", const="", metavar="DIR",
                        help="run on the seed suite in a throwaway folder (DIR keeps it)")
    parser.add_argument("--nights", type=int, default=1, help="how many nights to run")
    parser.add_argument("--plant", action="append", default=[], metavar="NAME=VALUE",
                        help="a value that is in effect before the first night")
    args = parser.parse_args(argv)
    if args.sandbox is None:
        parser.error("only --sandbox runs from the command line; the app runs its own nights")
    with tempfile.TemporaryDirectory() as scratch:
        home = Path(args.sandbox or scratch)
        home.mkdir(parents=True, exist_ok=True)
        box = sandbox(home, plant=_plant(args.plant))
        try:
            for number in range(1, max(1, args.nights) + 1):
                print(f"Night {number}")
                for line in box.night.run().lines():
                    print(f"  {line}")
            learned = params.learned()
            print("In effect now: " + (json.dumps(learned, sort_keys=True) if learned else
                                         "the shipped values."))
        finally:
            box.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
