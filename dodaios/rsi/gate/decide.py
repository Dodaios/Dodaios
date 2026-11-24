"""The measured gate: it runs the comparisons and hands the registry its evidence.

For a candidate (a parameter value that waits for its measurement) the gate
runs the select tasks of the domain twice, as the assistant is now and as it
would be with the candidate, and decides by :mod:`rules`. For a change that is
in effect it runs the guard tasks as the assistant is now and as it would be
without that change.

Nothing here touches the live assistant: both runs compute under an overlay.
The only thing that changes anything is the registry call at the end
(``admit``, ``decline``, ``settle``), and that call stores the evidence.

**What a task can tell.** A task whose truth the person confirmed by correcting
the assistant (``Role.GAIN``) can show a gain; one they only accepted
(``Role.GUARD``) can show a regression and nothing else. So "better" rests on
the gain tasks of the select split, "as good" on all of them, and the guard
tasks alone must not get clearly worse; keeping a change rests on all
guard-split tasks.

**A night's budget.** A domain that asks a model may run out of calls in the
middle of a comparison (``budget.Budget``). Its interval is still valid on the
tasks it reached, so a clear verdict stands; "no clear difference" waits for
the rest, which the next night measures (the results already paid for are
reused), and no error budget is spent on a comparison that did not finish.

**Whose tasks decide.** ``sources`` says which tasks a decision may rest on.
An installation decides on tasks built from the person's own work; the seed
suite decides only in a sandbox (a test, the public demo run), because a value
tuned on an invented person's memories says nothing about a real person's.
With no such tasks yet, a candidate simply waits: unmeasured, never applied.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import dodaios
from dodaios.rsi import overlay as overlays
from dodaios.rsi import params
from dodaios.rsi.bench import run
from dodaios.rsi.bench.model import NEEDS_MODEL, Domain, Role, Source, Split, Task, role_of
from dodaios.rsi.bench.store import BenchStore
from dodaios.rsi.fingerprint import Fingerprint
from dodaios.rsi.sequential import PairedSequence
from dodaios.self_change import SelfChangeError, SelfChangeRegistry, StaleEvidence, State, Surface
from dodaios.self_change.store import Change

from .alpha import ALPHA, AlphaLedger
from .evidence import Evidence, Verdict
from .rules import MIN_PAIRS, Compared, admit_verdict, keep_verdict

__all__ = ["LIVE", "Decision", "MeasuredGate"]


def _clear(found: Evidence, gain: Compared | None = None) -> bool:
    """A verdict that stands on part of the tasks: the interval left zero on one side.

    Its bounds hold at every look, so "better", "worse" and "as good and cheaper"
    are as true on the tasks measured so far as they will be on all of them.
    "No clear difference" is not: it needs every task of the split.
    """
    if found.verdict is Verdict.ACCEPT:
        return True
    if found.verdict is not Verdict.REJECT or found.target is None:
        return False
    if found.target.high < 0 or any(o.n >= MIN_PAIRS and o.high < 0 for o in found.others):
        return True
    return gain is not None and gain.interval.n >= MIN_PAIRS and gain.interval.high < 0


log = logging.getLogger(__name__)

#: The overlay of "the assistant as it is": learned values apply, nothing is written.
LIVE: Final[overlays.Overlay] = overlays.Overlay(label="live")
#: Level of the guard comparison (one look per change and night).
_GUARD_ALPHA: Final[float] = 0.05
#: How a void result names a run the night's budget did not cover.
_BUDGET_VOID: Final = "budget"

WorldsOf = Callable[[], run.Worlds]


@dataclass(frozen=True, slots=True)
class Decision:
    """What the gate did with one change."""

    change_id: str
    target: str
    evidence: Evidence
    #: ``admitted``, ``declined``, ``kept``, ``taken back`` or ``waiting``.
    outcome: str
    #: The state the change was in before (``proposed``, ``trial``, ``live``).
    was: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "target": self.target,
            "outcome": self.outcome,
            "was": self.was,
            "evidence": self.evidence.public(),
        }


class MeasuredGate:
    def __init__(
        self,
        registry: SelfChangeRegistry,
        bench: BenchStore,
        worlds: WorldsOf,
        *,
        sources: Sequence[Source] = (Source.MINED, Source.MADE),
    ) -> None:
        self.registry = registry
        self.bench = bench
        self._worlds = worlds
        self.sources = tuple(sources)
        self._alpha = AlphaLedger(bench)

    # ----------------------------------------------------------- the state

    def live(self) -> Fingerprint:
        """Which assistant is running right now."""
        return Fingerprint.of(
            app=dodaios.__version__,
            changes=self.registry.learned_ids(),
            params=params.values(),
        )

    def tasks(self, domain: Domain, split: Split, role: Role | None = None) -> list[Task]:
        """The tasks a decision on ``split`` may rest on (of one ``role``, when given)."""
        found: list[Task] = []
        for source in self.sources:
            found += self.bench.tasks(domain, splits=(split,), source=source)
        if role is not None:
            found = [task for task in found if role_of(task) is role]
        return found

    # ---------------------------------------------------------- comparing

    def compare(
        self,
        domain: Domain,
        split: Split,
        baseline: overlays.Overlay,
        candidate: overlays.Overlay,
        *,
        seed: str,
        alpha: float,
        role: Role | None = None,
    ) -> Compared:
        """Both states on the split's tasks, in an order fixed by ``seed``."""
        tasks = run.shuffled(self.tasks(domain, split, role), seed)
        worlds = self._worlds()
        if domain in NEEDS_MODEL and domain.value not in worlds:
            tasks = []  # nothing can run them tonight (no subscription seat): nothing is spent
        changes = self.registry.learned_ids()
        store = None if self.bench.readonly else self.bench

        def arm(overlay: overlays.Overlay) -> Fingerprint:
            return run.arm_of(overlay, changes=changes, domain=domain, worlds=worlds)

        before = run.measure(tasks, baseline, worlds, arm=arm(baseline), store=store)
        after = run.measure(tasks, candidate, worlds, arm=arm(candidate), store=store)
        paired = run.pair(before, after)
        sequence = PairedSequence(alpha)
        cut = {r.task_id for r in (*before, *after) if r.void.startswith(_BUDGET_VOID)}
        return Compared(
            domain=domain.value,
            interval=sequence.extend(paired.differences),
            baseline_tokens=paired.baseline_tokens,
            candidate_tokens=paired.candidate_tokens,
            unfinished=len(cut),
        )

    def can_decide(self, domain: Domain) -> bool:
        """True while the select tasks of ``domain`` can decide on a candidate.

        False while there are too few of them, and when their budget is used up.
        """
        if len(self.tasks(domain, Split.SELECT)) < MIN_PAIRS:
            return False
        groups = self.bench.groups(domain, Split.SELECT, self.sources)
        return self._alpha.left(domain, Split.SELECT, groups) > 0

    @staticmethod
    def _seed(step: str, change: Change) -> str:
        """What fixes the order of a comparison: the question asked, never its results.

        The n-th version of a target always walks the tasks in the same order, so
        a comparison can be repeated and gives the same answer.
        """
        return f"{step}:{change.surface.value}:{change.target}:v{change.version}"

    @staticmethod
    def _value(text: str | None, default: Any) -> Any:
        if text is None:
            return default
        try:
            return json.loads(text)["value"]
        except (ValueError, KeyError, TypeError):  # an unreadable text has no effect: the default
            return default

    def _parameter(self, change: Change) -> tuple[params.Param, Any, Any]:
        """The parameter a change is about, its value with the change and without it."""
        store = params.installed()
        param = (store.index if store is not None else params.INDEX).get(change.target)
        if param is None or change.surface is not Surface.PARAMETER:
            raise SelfChangeError(f"nothing can measure {change.surface.value} {change.target!r}")
        with_it = param.coerce(self._value(change.after, param.default))
        try:
            without = param.coerce(self._value(change.before, param.default))
        except params.ParamError:  # the earlier value no longer fits today's limits
            without = param.default
        return param, with_it, without

    # ---------------------------------------------------------- candidates

    def decide(self, change: Change) -> Evidence:
        """Measure one candidate on the select tasks. Changes nothing."""
        param, value, _ = self._parameter(change)
        domains = [Domain(name) for name in param.domains]
        if not domains or not any(self.tasks(d, Split.SELECT) for d in domains):
            return Evidence(Verdict.UNMEASURED, reason="there are no tasks yet to measure it on")
        candidate = overlays.Overlay(label=f"candidate:{change.id}", params={param.name: value})
        compared: list[Compared] = []
        gain: Compared | None = None
        spend: list[Domain] = []
        for domain in domains:
            have = len(self.tasks(domain, Split.SELECT))
            if have < MIN_PAIRS:
                # Too few tasks decide nothing, so none of the budget is spent on asking.
                reason = f"only {have} tasks to decide on; {MIN_PAIRS} are needed"
                return Evidence(Verdict.UNDECIDED, split=Split.SELECT.value, reason=reason)
            groups = self.bench.groups(domain, Split.SELECT, self.sources)
            if self._alpha.left(domain, Split.SELECT, groups) <= 0:
                reason = "the tasks it would be decided on are used up until new ones arrive"
                return Evidence(Verdict.UNDECIDED, split=Split.SELECT.value, reason=reason)
            seed = self._seed("admit", change)

            def part(role: Role | None, *, on: Domain = domain, seed: str = seed) -> Compared:
                return self.compare(
                    on, Split.SELECT, LIVE, candidate, seed=seed, alpha=ALPHA, role=role
                )

            compared.append(part(None))
            spend.append(domain)
            if self.tasks(domain, Split.SELECT, Role.GUARD):
                # What the person only accepted shows harm, never a gain: "better" rests
                # on the rest, and the accepted part alone must not get clearly worse.
                if domain is domains[0]:
                    gain = part(Role.GAIN)
                compared.append(part(Role.GUARD))
        found = admit_verdict(
            compared[0],
            tuple(compared[1:]),
            alpha=ALPHA,
            baseline=self.live().id,
            split=Split.SELECT.value,
            gain=gain,
        )
        cut = any(c.unfinished for c in (*compared, *([gain] if gain else [])))
        if cut and not _clear(found, gain):
            done, left = compared[0].interval.n, compared[0].unfinished
            reason = (
                f"measured on {done} tasks so far; the night's model calls ran out before "
                f"the other {left}, which the next night measures"
            )
            return Evidence(
                Verdict.UNDECIDED, target=found.target, split=Split.SELECT.value, reason=reason
            )
        for domain in spend:  # a decision was made: it counts against the split's budget
            groups = self.bench.groups(domain, Split.SELECT, self.sources)
            self._alpha.spend(domain, Split.SELECT, groups)
        return found

    def consider(self, change: Change) -> Decision:
        """Measure a candidate and act on the result."""
        found = self.decide(change)
        outcome = "waiting"
        try:
            if found.accepted:
                self.registry.admit(change.id, found, live=self.live().id)
                outcome = "admitted"
            elif found.verdict is Verdict.REJECT:
                self.registry.decline(change.id, found)
                outcome = "declined"
        except StaleEvidence:  # measured again in the next round, against the new state
            outcome = "waiting"
        return Decision(change.id, change.target, found, outcome, change.state.value)

    def consider_all(self) -> list[Decision]:
        """Every candidate, oldest first. One going in makes the next be measured against it."""
        done: list[Decision] = []
        for change in self.registry.candidates():
            try:
                done.append(self.consider(change))
            except SelfChangeError as exc:  # kept as the reason of a waiting decision
                reason = Evidence(Verdict.UNMEASURED, reason=str(exc))
                done.append(Decision(change.id, change.target, reason, "waiting"))
        return done

    # ------------------------------------------------- changes in effect

    def check(self, change: Change) -> Evidence:
        """Is the assistant better with this change than without it, on the guard tasks."""
        param, _, without = self._parameter(change)
        domain = Domain(param.domains[0]) if param.domains else None
        if domain is None or not self.tasks(domain, Split.GUARD):
            return Evidence(Verdict.UNDECIDED, reason="there are no guard tasks yet")
        ablated = overlays.Overlay(label=f"without:{change.id}", params={param.name: without})
        seed = self._seed("keep", change)
        guard = self.compare(domain, Split.GUARD, ablated, LIVE, seed=seed, alpha=_GUARD_ALPHA)
        select = None
        if guard.interval.mean < 0 and guard.interval.high >= 0 and not guard.unfinished:
            again = self._seed("again", change)
            select = self.compare(
                domain,
                Split.SELECT,
                ablated,
                LIVE,
                seed=again,
                alpha=_GUARD_ALPHA,
                role=Role.GAIN,
            )
        found = keep_verdict(guard, select)
        cut = guard.unfinished or (select.unfinished if select is not None else 0)
        if cut and not (found.verdict is Verdict.REJECT and guard.interval.high < 0):
            # Only "clearly worse" stands on part of the tasks; the rest is measured next night.
            reason = f"checked on {guard.interval.n} tasks so far; the rest comes next night"
            return Evidence(Verdict.UNDECIDED, target=found.target, split="guard", reason=reason)
        return found

    def settle(self, change: Change) -> Decision:
        """Check a change that is in effect and act on the result."""
        found = self.check(change)
        outcome = "waiting"
        if found.accepted:
            self.registry.settle(change.id, found)
            outcome = "kept"
        elif found.verdict is Verdict.REJECT:
            self.registry.settle(change.id, found)
            outcome = "taken back"
        return Decision(change.id, change.target, found, outcome, change.state.value)

    def settle_all(self, *, newest: int = 5) -> list[Decision]:
        """Check what is on trial, and the newest live changes (does what was kept still pay).

        Newest first: taking a change back also takes back what was built on it,
        so the later ones are looked at before the one they rest on.
        """
        learned = [c for c in self.registry.learned() if c.surface is Surface.PARAMETER]
        on_trial = [c for c in learned if c.state is State.TRIAL]
        live = [c for c in learned if c.state is State.LIVE][-newest:]
        done: list[Decision] = []
        for change in sorted([*on_trial, *live], key=lambda c: -c.seq):
            current = self.registry.store.get(change.id)
            if current is None or current.state not in (State.TRIAL, State.LIVE):
                continue  # already taken back with a change it was built on
            try:
                done.append(self.settle(current))
            except SelfChangeError as exc:  # kept as the reason of a waiting decision
                reason = Evidence(Verdict.UNDECIDED, reason=str(exc))
                done.append(Decision(change.id, change.target, reason, "waiting"))
        return done
