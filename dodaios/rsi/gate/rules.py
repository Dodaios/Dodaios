"""The rules the gate decides by. Fixed here; no learner and no setting changes them.

A comparison is two states of the assistant on the same tasks: one difference
of scores per task, and what each state cost. From that the gate answers.

**Letting a candidate in** (decided on the select split):

1. fewer than :data:`MIN_PAIRS` tasks: *undecided*, nothing can be said yet;
2. the whole interval is below zero: *reject*, it is worse;
3. the whole interval is above zero: *accept*. Quality comes first, so a clear
   gain may cost more, up to the domain's cap (:data:`COST_CAPS`); beyond it,
   *reject*. The recall has no cap: every parameter's own limits already bound
   how long the prompt can get, and a ratio means nothing against a baseline
   that shows almost nothing;
4. no clear gain, but at least :data:`CHEAPER` cheaper and the lower bound is
   above ``-NOT_WORSE``: *accept*, it is as good and costs less;
5. no clear gain and it costs more than the slack: *reject*;
6. otherwise *reject* as "no clear difference": every task of the split was
   used, so asking again without new tasks would only spend the error budget.

The interval is a confidence sequence (:mod:`dodaios.rsi.sequential`): its
bounds are valid whenever they are read.

**Keeping a change that is in effect** (decided on the guard split, by
comparing the assistant as it is with the assistant without that change):

* *accept* (it stays, a change on trial becomes live) when it shows no harm:
  the mean difference is not negative and its cost is within the domain's cap;
* *reject* (it is taken back) when the whole interval is below zero, or when
  the mean is negative on the guard tasks AND not positive on the select
  tasks measured again now: the gain it was let in for is gone;
* else *undecided*: it stays as it is and is looked at again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from dodaios.rsi.sequential import Interval

from .evidence import Effect, Evidence, Verdict

__all__ = [
    "CHEAPER",
    "COST_CAPS",
    "COST_SLACK",
    "MIN_GUARD_PAIRS",
    "MIN_PAIRS",
    "NOT_WORSE",
    "Compared",
    "admit_verdict",
    "keep_verdict",
]

#: Pairs below which the select split decides nothing.
MIN_PAIRS: Final[int] = 30
#: Pairs below which the guard split decides nothing.
MIN_GUARD_PAIRS: Final[int] = 15
#: A candidate without a clear gain may cost this much more at most (share of the baseline).
COST_SLACK: Final[float] = 0.10
#: How much more a clearly better candidate may cost, per domain, as a ratio.
#: A domain that is not listed gets ``1 + COST_SLACK``.
COST_CAPS: Final[dict[str, float]] = {"recall": float("inf")}
#: A candidate that is not better must be at least this much cheaper.
CHEAPER: Final[float] = 0.05
#: ...and its lower bound must be above minus this.
NOT_WORSE: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class Compared:
    """One domain's comparison: the interval of the differences, and both costs."""

    domain: str
    interval: Interval
    baseline_tokens: float
    candidate_tokens: float
    #: Tasks the night's budget did not reach. The interval is valid on the ones it
    #: did (it holds at every look), but "no clear difference" needs every task.
    unfinished: int = 0

    @property
    def cost_ratio(self) -> float:
        """Candidate cost over baseline cost; 1.0 when neither costs anything."""
        if self.baseline_tokens <= 0:
            return 1.0 if self.candidate_tokens <= 0 else float("inf")
        return self.candidate_tokens / self.baseline_tokens

    def effect(self) -> Effect:
        found = self.interval
        return Effect(
            domain=self.domain,
            diff=round(found.mean, 4),
            low=round(found.low, 4),
            high=round(found.high, 4),
            n=found.n,
            cost_diff=round(self.candidate_tokens - self.baseline_tokens, 2),
        )


def _percent(ratio: float) -> str:
    return f"{abs(ratio - 1.0):.0%}"


def admit_verdict(
    target: Compared, others: tuple[Compared, ...] = (), *, alpha: float, baseline: str, split: str
) -> Evidence:
    """May this candidate go in? ``target`` is the domain it claims; ``others`` must not lose."""

    def evidence(verdict: Verdict, reason: str) -> Evidence:
        return Evidence(
            verdict,
            target=target.effect(),
            others=tuple(other.effect() for other in others),
            baseline=baseline,
            split=split,
            alpha=alpha,
            reason=reason,
        )

    found, ratio = target.interval, target.cost_ratio
    if found.n < MIN_PAIRS:
        return evidence(Verdict.UNDECIDED, f"only {found.n} tasks; {MIN_PAIRS} are needed")
    for other in others:
        if other.interval.n >= MIN_PAIRS and other.interval.high < 0:
            return evidence(Verdict.REJECT, f"it makes {other.domain} worse")
    if found.high < 0:
        return evidence(Verdict.REJECT, f"worse on {found.n} tasks")
    if found.low > 0:
        if ratio > COST_CAPS.get(target.domain, 1.0 + COST_SLACK):
            return evidence(Verdict.REJECT, f"better, but it costs {_percent(ratio)} more")
        return evidence(Verdict.ACCEPT, f"better on {found.n} tasks")
    if ratio <= 1.0 - CHEAPER and found.low > -NOT_WORSE:
        reason = f"as good on {found.n} tasks, and {_percent(ratio)} cheaper"
        return evidence(Verdict.ACCEPT, reason)
    if ratio > 1.0 + COST_SLACK:
        return evidence(Verdict.REJECT, f"no gain, and it costs {_percent(ratio)} more")
    return evidence(Verdict.REJECT, f"no clear difference on {found.n} tasks")


def keep_verdict(guard: Compared, select: Compared | None, *, split: str = "guard") -> Evidence:
    """Does a change that is in effect stay? Both comparisons are "with it" minus "without it"."""

    def evidence(verdict: Verdict, reason: str) -> Evidence:
        others = (select.effect(),) if select is not None else ()
        return Evidence(verdict, target=guard.effect(), others=others, split=split, reason=reason)

    found = guard.interval
    if found.n < MIN_GUARD_PAIRS:
        reason = f"only {found.n} guard tasks; {MIN_GUARD_PAIRS} are needed"
        return evidence(Verdict.UNDECIDED, reason)
    if found.high < 0:
        return evidence(Verdict.REJECT, f"worse on {found.n} new tasks")
    gone = select is not None and select.interval.n >= MIN_PAIRS and select.interval.mean <= 0
    if found.mean < 0 and gone:
        return evidence(Verdict.REJECT, "the gain it was let in for is gone")
    if found.mean >= 0 and guard.cost_ratio <= COST_CAPS.get(guard.domain, 1.0 + COST_SLACK):
        return evidence(Verdict.ACCEPT, f"held on {found.n} new tasks")
    return evidence(Verdict.UNDECIDED, f"not clear on {found.n} new tasks")
