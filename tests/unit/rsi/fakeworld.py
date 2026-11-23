"""A made-up recall world whose answers are known exactly, for end-to-end tests.

The seed suite is real search on real text: what a parameter does there is
small, and whether the gate can prove it depends on which tasks fell into
which split. A test of the loop itself needs effects that cannot be mistaken.
Here a task's score follows two parameters by rule:

* 60 % of the messages need a memory that is looked up. They get it while
  ``recall.min_score`` is at most :data:`SHOWN_UP_TO`; above that nothing is
  shown and they score 0. The other 40 % always score 1.
* what is shown costs 25 tokens per memory of ``recall.turn_limit``; when
  nothing is shown the cost is 0.

So a ``min_score`` of 12 is plainly bad (0.4 instead of 1.0), lowering it to 8
is plainly better, a ``turn_limit`` of 2 is exactly as good as 6 and two thirds
cheaper, and no other parameter does anything.
"""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.rsi import night as nights
from dodaios.rsi import params
from dodaios.rsi.bench import recall, run
from dodaios.rsi.bench.model import Domain, Source, Task, task_id

WORLD = "fake"
SCORE = "recall.min_score"
LIMIT = "recall.turn_limit"
#: The plainly bad value: nothing is looked up at all.
BLIND = 12.0
SHOWN_UP_TO = 9.0
TASKS = 600


def tasks(n: int = TASKS) -> list[Task]:
    return [
        Task(
            id=task_id(Domain.RECALL, Source.MADE, f"fake-{i}"),
            domain=Domain.RECALL,
            source=Source.MADE,
            group=f"fake-group-{i}",
            payload={"world": WORLD, "i": i},
        )
        for i in range(n)
    ]


def scorer(task: Task, worlds: Any) -> recall.Scored:
    shown = float(params.get(SCORE)) <= SHOWN_UP_TO
    needs_lookup = int(task.payload["i"]) % 10 < 6
    score = 1.0 if shown or not needs_lookup else 0.0
    tokens = 25 * int(params.get(LIMIT)) if shown else 0
    return recall.Scored(score, tokens)


def splits() -> dict[str, int]:
    out: dict[str, int] = {}
    for task in tasks():
        out[task.split.value] = out.get(task.split.value, 0) + 1
    return out


def sandbox(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, **more: Any) -> nights.Sandbox:
    """A throwaway installation that decides on the made-up world."""
    monkeypatch.setitem(run._RUNNERS, Domain.RECALL, scorer)
    return nights.sandbox(
        tmp_path, tasks=tasks(), worlds={WORLD: object()}, sources=(Source.MADE,), **more
    )
