"""The runner of the first_move domain: replay a lead turn and read its first move.

A replay gives the lead's CLI what a turn gave it, with the change under test
applied, and reads the first move from the stream:

* a task from the person's own lead turns names a row of ``lead_turns.db``;
  the CLI gets that row's system prompt and message exactly as recorded, with
  the standing lines switched as the run's overlay says (:func:`lines.apply`);
* a seed task carries a request; the CLI gets it as the lead's message
  (``dodaios_harness.lead_message``, built under the run's overlay) on top of
  the lead's current input (``runner_cli.lead_model_input``).

The tools are offered and never run: the replay's tool server lists the lead's
tools and runs none of them, and the CLI is stopped at its first tool call
(:mod:`dodaios.rsi.bench.lead_cli`).

**What answers is fixed for a night** (:class:`Platform`: the CLI and its
version, the model, the effort, the tool list), and it is part of the arm's
fingerprint, so a result is reused for an unchanged arm and never for another
one (``run.measure``). The model the CLI says it ran is checked on every call;
a run on another model does not count, and a pair whose two runs name
different models is no pair (``run.pair``).

**Every call is asked for** from the night's :class:`~dodaios.rsi.budget.Budget`
first; a task the budget does not cover gets a void result that says so, and
the comparison carries on from there the next night.

What a replay cannot see: the CLI's own conversation on a resumed turn (the
record names it, it is not part of the input), so a replay starts a fresh
conversation with the recorded system prompt and message; the person's own
MCP servers (the lead runs with only the app's server, and so does the replay).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any, Final

from dodaios.rsi import lines
from dodaios.rsi.budget import Budget

from .first_move import Move, score
from .model import Measured, Task

__all__ = ["WORLD", "FirstMoveWorld", "LeadInput", "Platform", "run", "same_model"]

#: The name a first_move world has among a night's worlds.
WORLD: Final = "first_move"


@dataclass(frozen=True, slots=True)
class LeadInput:
    """What the lead's CLI is given for one replay."""

    system: str
    message: str


@dataclass(frozen=True, slots=True)
class Platform:
    """What answers a replay. Fixed for a night; both arms of a pair run on it."""

    cli: str
    model: str
    effort: str = ""
    #: The CLI's own version (``claude --version``).
    cli_version: str = ""
    #: A hash of the tool list the replay offers (``tool_list_digest``'s shape).
    tools: str = ""
    #: A hash of what a seed task's message is put on (the lead's current system prompt).
    base: str = ""

    @property
    def seat(self) -> str:
        return f"{self.cli}:{self.model}"

    def extra(self) -> dict[str, str]:
        """What the fingerprint holds beside the switches: everything that shapes a replay."""
        return {
            "first_move.cli_version": self.cli_version,
            "first_move.effort": self.effort,
            "first_move.tools": self.tools,
            "first_move.base": self.base,
        }


#: Runs one replay and returns the first move. Blocking.
Driver = Callable[[LeadInput, Platform], Move]


@dataclass(slots=True)
class FirstMoveWorld:
    """What a night needs to run first_move tasks."""

    platform: Platform
    driver: Driver
    budget: Budget
    #: The tool names the replay offers; ``None`` when unknown (then nothing is skipped).
    offered: Collection[str] | None = None
    #: A recorded lead turn by its ``seq`` in ``lead_turns.db`` (``None``: gone).
    recorded: Callable[[int], Any] | None = None
    #: What the lead is given for a request today, built under the active overlay.
    seed_input: Callable[[str], LeadInput] | None = None


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def same_model(asked: str, answered: str) -> bool:
    """Whether the CLI ran the model the platform names (an alias names a family)."""
    if not asked or not answered:
        return True
    a, b = asked.strip().lower(), answered.strip().lower()
    return a == b or a in b or b in a


def _input(task: Task, world: FirstMoveWorld) -> LeadInput | str:
    """The input of one replay under the active overlay, or why there is none."""
    ref = task.payload.get("turn")
    if isinstance(ref, dict):
        if world.recorded is None:
            return "no record of lead turns to replay from"
        row = world.recorded(int(ref.get("seq") or 0))
        if row is None:
            return "the recorded turn is gone"
        if str(row.cli) != world.platform.cli:
            return f"recorded on {row.cli}; the lead runs on {world.platform.cli}"
        message = lines.apply(str(row.message), lines.switches())
        if message is None:
            return "the recorded message has no place for a line this arm puts back"
        return LeadInput(str(row.system), message)
    utterance = str(task.payload.get("utterance") or "")
    if not utterance:
        return "the task names neither a recorded turn nor a request"
    if world.seed_input is None:
        return "nothing builds the lead's input for a request"
    return world.seed_input(utterance)


def run(task: Task, world: FirstMoveWorld) -> Measured:
    """Replay one task under the active overlay and score its first move."""
    found = _input(task, world)
    if isinstance(found, str):
        return Measured(0.0, 0, found, void=found)
    tokens = round(len(found.message) / 4)
    if world.offered is not None:
        missing = [t for t in task.check.get("requires") or () if t not in world.offered]
        if missing:
            why = f"needs {', '.join(missing)}, which the lead does not have"
            return Measured(0.0, tokens, why, void=why)
    refused = world.budget.take()
    if refused:
        return Measured(0.0, tokens, refused, void=f"budget: {refused}")
    move = world.driver(found, world.platform)
    seat = f"{world.platform.cli}:{move.model or world.platform.model}"
    if not same_model(world.platform.model, move.model):
        why = f"the model changed: asked {world.platform.model}, answered {move.model}"
        return Measured(0.0, tokens, why, seat=seat, void="the model changed", calls=1)
    return score(task.check, move, message=found.message, seat=seat)
