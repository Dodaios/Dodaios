"""What a learning round may spend on model calls, asked before every call.

The work decides how many calls a round makes; this module decides how many
it may make. Building tasks goes on while the gate still lacks tasks
(``night.tasks_wanted``), and replays go on while comparisons are still open
(a result is reused per arm, so a finished comparison asks nothing). Before
every single call the runner asks a :class:`Budget`, so no learner, task or
loop can spend past it:

* only on a subscription or a local model, never a key billed per token (the
  world of a domain is not built at all without one: see ``lead_world``, and
  the task builder never asks a per-token key: ``night._model_ask``);
* only while the person is away (the round starts after
  ``night.IDLE_AFTER_S``; a call is not started once they are back), and
  only while the backend keeps the round (a call is not started once it
  halts: the app opens over the background service, or the backend stops);
* when the plan's usage windows can be read (:func:`plan_usage`: a live
  reading, or one no older than :data:`USAGE_FRESH_S`): never a call while any
  window is :data:`FULL_PERCENT` full or more, and no more than
  :data:`BUDGET_SHARE` of a window spent in one round (measured from where the
  window stood when the round's first call was asked for);
* when they cannot be read (a local model, a CLI whose usage this build cannot
  read, a reading that is only an old snapshot): the fixed caps of before,
  :data:`REPLAY_CALLS` replays a round, and the task builder's own
  (``night.MAX_MODEL_CALLS``, ``night.RAMP_MODEL_CALLS`` while too few tasks
  exist to decide on);
* and never more than :data:`CEILING_CALLS` calls of one kind in one round,
  whatever the plan says: a guard against a fault, not the limit in practice.

**Why the ceiling is 200.** The work of an honest round stays well below it.
The first decision on the person's own recall tasks needs about 120 tasks (30
in the select split, which gets a quarter of them); at the seven to ten tasks a
call has given, that is 12 to 20 calls. A comparison of a candidate on 30
replayed tasks is 60 calls, and a round that checks a change, decides on one
and measures the advantage makes about three of them. So 200 never cuts work
that is really needed, while a fault (a usage reading that stays live but
stops moving, a model whose answers add nothing) still ends at a known cost:
200 lead calls are about 2.5 million input tokens, most of them read from the
provider's cache because the lead's system prompt repeats, about what five
long working sessions of the person send.

A lead call carries the lead's whole system prompt, about 50 000 characters
(some 12 500 tokens), plus the CLI's own prompt and the tool list. A
first_move replay is one call; a brief replay one, and one more for each call
of the lead it answers (the kit, a look into the repository: each makes the
CLI ask the model again; ``brief_replay``). One :class:`Budget` object serves
both replay domains of a round, so neither can spend past it.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Final

__all__ = [
    "BUDGET_SHARE",
    "CEILING_CALLS",
    "FIRST_MOVE_CALLS",
    "FULL_PERCENT",
    "REPLAY_CALLS",
    "USAGE_FRESH_S",
    "Budget",
    "Usage",
    "plan_usage",
]

log = logging.getLogger(__name__)

#: Share of a plan's usage window one round may use for model calls. Fixed.
BUDGET_SHARE: Final[float] = 0.20
#: A usage window this full leaves the plan to the person: no call starts.
#: The same line the self-build loop keeps (``self_build.code.seat.FULL_PERCENT``).
FULL_PERCENT: Final[float] = 80.0
#: Calls of one kind (building tasks, replaying the lead) one round makes at most,
#: whatever the plan's windows say: the runaway guard (see the module text).
CEILING_CALLS: Final[int] = 200
#: Replays of lead turns one round may make, for ``first_move`` and ``brief``
#: together, when the plan's usage windows cannot be read.
REPLAY_CALLS: Final[int] = 40
#: The same cap under the name it had while only ``first_move`` replayed.
FIRST_MOVE_CALLS: Final[int] = REPLAY_CALLS
#: A usage reading older than this is a snapshot, not a reading: the round then
#: counts the windows as unreadable, since a number that does not move could
#: never stop it.
USAGE_FRESH_S: Final[float] = 15 * 60

#: Window name -> how full it is, in percent (``agent_usage.UsageWindow``).
Usage = Mapping[str, float]


def plan_usage(platform: str, *, now: Callable[[], float] = time.time) -> Usage | None:
    """How full the active ``platform`` account's windows are; ``None``: not readable.

    Read through ``agent_usage`` (at most once a minute per account). A reading
    that is neither live nor fresh (:data:`USAGE_FRESH_S`) counts as unreadable.
    """
    try:
        from dodaios import agent_accounts, agent_usage

        if not agent_usage.supports_usage(platform):
            return None
        account = agent_accounts.active_account(platform)
        found = agent_usage.collect([account]).get(account.id)
    except Exception:  # broad-except: no reading: the fixed caps apply instead
        log.debug("self-improvement: the plan's usage could not be read", exc_info=True)
        return None
    if found is None or found.status != "ok" or not found.windows:
        return None
    if found.source != "live" and (found.as_of is None or now() - found.as_of > USAGE_FRESH_S):
        return None
    return {f"{w.kind}:{w.scope_label or w.raw_label or ''}": w.percent for w in found.windows}


class Budget:
    """One round's allowance of model calls of one kind.

    ``cap`` is the ceiling while the plan's windows can be read; ``fallback``
    (default: the ceiling) is the cap while they cannot.
    """

    def __init__(
        self,
        cap: int,
        *,
        fallback: int | None = None,
        usage: Callable[[], Usage | None] | None = None,
        idle: Callable[[], bool] | None = None,
        halted: Callable[[], bool] | None = None,
    ) -> None:
        self.cap = int(cap)
        self.fallback = min(self.cap, int(fallback)) if fallback is not None else self.cap
        self._usage = usage
        self._idle = idle
        self._halted = halted
        self._start: dict[str, float] | None = None
        self._lock = threading.Lock()
        #: The cap that held at the last question: the ceiling, or the fallback.
        self._limit = self.fallback
        self.calls = 0
        #: Why the last refusal happened ("" while calls are allowed).
        self.stopped = ""
        #: The most of one usage window this round has used so far, in percent points.
        self.share = 0.0
        #: Whether the plan's windows could be read at the last question (None: never asked).
        self.read: bool | None = None

    @property
    def left(self) -> int:
        return max(0, self._limit - self.calls)

    def _why_not(self) -> str:
        if self._halted is not None and self._halted():
            return "the backend let go of the round"
        if self._idle is not None and not self._idle():
            return "the person is back"
        reading = self._usage() if self._usage is not None else None
        self.read = reading is not None
        if reading is None:
            # The plan's windows cannot be read: the fixed cap applies.
            self._limit = self.fallback
            if self.calls >= self.fallback:
                return f"the round's {self.fallback} model calls are spent"
            return ""
        self._limit = self.cap
        if self.calls >= self.cap:
            return f"the round's ceiling of {self.cap} model calls is reached"
        now = {str(k): float(v) for k, v in reading.items()}
        if self._start is None:
            self._start = dict(now)
        for name, percent in now.items():
            self.share = max(self.share, percent - self._start.get(name, percent))
        if any(percent >= FULL_PERCENT for percent in now.values()):
            return f"a usage window of the plan is {FULL_PERCENT:.0f} % full"
        for name, percent in now.items():
            if percent - self._start.get(name, percent) >= BUDGET_SHARE * 100:
                return f"this round used {BUDGET_SHARE:.0%} of the {name} window"
        return ""

    def take(self, calls: int = 1) -> str:
        """Ask for ``calls`` calls at once. ``""``: go ahead (they are counted); else why not.

        A request for more than is left is refused without stopping the round:
        a smaller one may still fit.
        """
        with self._lock:
            if self.stopped:
                return self.stopped
            why = self._why_not()
            if why:
                self.stopped = why
                return why
            limit = min(self.cap, self._limit)
            if self.calls + calls > limit:
                return f"the round's {limit} model calls are nearly spent"
            self.calls += calls
            return ""

    def public(self) -> dict[str, object]:
        """What the round's report keeps of it (``NightReport.calls``)."""
        return {
            "calls": self.calls,
            "cap": self.cap,
            "fallback": self.fallback,
            "stopped": self.stopped,
            "share": round(self.share, 2),
            "usage_read": self.read,
        }
