"""What recurring follow-up orders say the first brief was missing.

When the same follow-up order keeps coming in one cell, the first brief left
something out that a line in it could have said. The miner reads the
follow-up orders recorded under a cell's active policy and, when one of a few
fixed patterns recurs in at least :data:`MIN_CITED` runs, suggests exactly one
line to add to the policy's domain block, citing those runs.

The lines are fixed sentences, not model output, and none of them tells an
agent to do less checking. Because they are written here and reviewed like any
code, a policy whose text is made of them only (:data:`LINES`) is an ordinary
self-change: it goes on trial by itself, half of the person's requests in the
cell carry it, and the selector's gate decides on the measured runs whether it
stays. Nobody is asked. Any other text for agents is still the owner's call
(``core_reasons`` in ``dodaios/self_change/surfaces.py``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .policy import MAX_BLOCK_CHARS, Policy, PolicyError

__all__ = ["LINES", "MIN_CITED", "PATTERNS", "Suggestion", "suggest"]

#: Runs a pattern must have cost a follow-up order in before it is suggested.
MIN_CITED: Final[int] = 5

_CHECK_FILES = re.compile(r"\bC4\b")
_TESTS_WEAKENED = re.compile(r"\bC[127]\b")
_LINT = re.compile(
    r"\b(lint|ruff|eslint|flake8|pylint|prettier|format|mypy|pyright|tsc|type)", re.IGNORECASE
)
_TESTS = re.compile(r"\b(test|tests|pytest|jest|vitest|unit|e2e)\b", re.I)


@dataclass(frozen=True, slots=True)
class Pattern:
    name: str
    template: str
    matches: re.Pattern[str]
    line: str


PATTERNS: Final[tuple[Pattern, ...]] = (
    Pattern(
        "check_files",
        "T2",
        _CHECK_FILES,
        "Leave test, lint, type and CI configuration as it is unless the order asks you to "
        "change it.",
    ),
    Pattern(
        "tests_kept",
        "T2",
        _TESTS_WEAKENED,
        "Keep every existing test and its assertions; when one fails, fix the code, or say "
        "why the test is wrong.",
    ),
    Pattern(
        "lint_first",
        "T1",
        _LINT,
        "Run this repository's linters and type checks before you commit.",
    ),
    Pattern(
        "tests_first",
        "T1",
        _TESTS,
        "Run the tests that cover your change before you commit, and make them pass.",
    ),
)

#: Every line the miner can add. A domain block made of these only goes on trial
#: without the owner; they are fixed in the code, not written by a model.
LINES: Final[frozenset[str]] = frozenset(p.line for p in PATTERNS)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One line to add, and the runs whose follow-up orders it would have spared."""

    pattern: str
    line: str
    cited: tuple[str, ...]

    def policy(self, active: Policy) -> Policy:
        """``active`` with this line added to its domain block."""
        block = "\n".join(part for part in (active.domain_block, self.line) if part)
        return Policy(
            p_max=active.p_max,
            evidence_wait_s=active.evidence_wait_s,
            domain_block=block,
            hold=active.hold,
        )


def suggest(
    active: Policy,
    runs: Iterable[tuple[dict[str, Any], Sequence[dict[str, Any]]]],
    *,
    allowed: Callable[[Policy], bool] = lambda _policy: True,
) -> Suggestion | None:
    """The best supported line the active policy's block does not have yet, or ``None``.

    ``allowed`` can rule a candidate out (the trainer's: one whose trial ended
    lately is not tried again yet); the next best line is taken then.
    """
    cited: dict[str, list[str]] = {p.name: [] for p in PATTERNS}
    for run, steps in runs:
        run_id = str(run.get("run_id") or "")
        seen: set[str] = set()
        for step in steps:
            if step.get("step") != "follow_up_intent":
                continue
            template = str(step.get("status") or "")
            reason = str((step.get("detail") or {}).get("reason") or "")
            for pattern in PATTERNS:
                if pattern.name in seen or template != pattern.template:
                    continue
                if pattern.matches.search(reason):
                    seen.add(pattern.name)
                    cited[pattern.name].append(run_id)
    for pattern in sorted(PATTERNS, key=lambda p: -len(cited[p.name])):
        runs_cited = cited[pattern.name]
        if len(runs_cited) < MIN_CITED or pattern.line in active.domain_block:
            continue
        found = Suggestion(pattern.name, pattern.line, tuple(runs_cited))
        try:
            candidate = found.policy(active)
        except PolicyError:
            continue  # the block would grow past its limit
        if len(candidate.domain_block) <= MAX_BLOCK_CHARS and allowed(candidate):
            return found
    return None
