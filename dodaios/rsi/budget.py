"""What a night may spend on model calls, enforced before every call.

The limits are fixed here, not in a setting, and the runner asks :class:`Budget`
before each call, so no learner, task or loop can spend past them:

* only on a subscription or a local model, never a key billed per token (the
  world of a domain is not built at all without one: see ``lead_replay``);
* only while the person is away (the night starts after
  ``night.IDLE_AFTER_S``; a call is not started once they are back), and
  only while the backend keeps the night (a call is not started once it
  halts: the app opens over the background service, or the backend stops);
* at most :data:`REPLAY_CALLS` calls a night for the domains that replay
  lead turns, ``first_move`` and ``brief`` together: one :class:`Budget`
  object serves both worlds of a night, so neither can spend past it. A
  first_move replay is one call; a brief replay one, and one more for each
  call of the lead it answers (the kit, a look into the repository: each makes
  the CLI ask the model again; ``brief_replay``). A lead call carries the
  lead's whole system prompt, about 50 000
  characters (some 12 500 tokens) plus the CLI's own prompt and the tool list,
  so 40 calls are roughly half a million input tokens, most of it read from
  the provider's cache because the system prompt repeats. That is about what
  one long working session of the person sends, and enough to finish one
  comparison of a candidate on 30 tasks (60 calls, with the unchanged side
  cached) in two nights;
* when the plan's usage windows can be read: never a call while any window is
  :data:`FULL_PERCENT` full or more, and no more than :data:`BUDGET_SHARE` of a
  window spent in one night (measured from where the window stood when the
  night's first call was asked for). When they cannot be read, the cap alone
  applies.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Final

__all__ = ["BUDGET_SHARE", "FIRST_MOVE_CALLS", "FULL_PERCENT", "REPLAY_CALLS", "Budget", "Usage"]

#: Share of a plan's usage window a night may use for model calls. Fixed.
BUDGET_SHARE: Final[float] = 0.20
#: A usage window this full leaves the plan to the person: no call starts.
#: The same line the self-build loop keeps (``self_build.code.seat.FULL_PERCENT``).
FULL_PERCENT: Final[float] = 80.0
#: Model calls one night may make replaying lead turns, for ``first_move`` and
#: ``brief`` together.
REPLAY_CALLS: Final[int] = 40
#: The same cap under the name it had while only ``first_move`` replayed.
FIRST_MOVE_CALLS: Final[int] = REPLAY_CALLS

#: Window name -> how full it is, in percent (``agent_usage.UsageWindow``).
Usage = Mapping[str, float]


class Budget:
    """One night's allowance of model calls for one domain."""

    def __init__(
        self,
        cap: int,
        *,
        usage: Callable[[], Usage | None] | None = None,
        idle: Callable[[], bool] | None = None,
        halted: Callable[[], bool] | None = None,
    ) -> None:
        self.cap = int(cap)
        self._usage = usage
        self._idle = idle
        self._halted = halted
        self._start: dict[str, float] | None = None
        self._lock = threading.Lock()
        self.calls = 0
        #: Why the last refusal happened ("" while calls are allowed).
        self.stopped = ""

    @property
    def left(self) -> int:
        return max(0, self.cap - self.calls)

    def _why_not(self) -> str:
        if self.calls >= self.cap:
            return f"the night's {self.cap} model calls are spent"
        if self._halted is not None and self._halted():
            return "the backend let go of the night"
        if self._idle is not None and not self._idle():
            return "the person is back"
        reading = self._usage() if self._usage is not None else None
        if reading is None:
            return ""  # the plan's windows cannot be read: the cap alone applies
        now = {str(k): float(v) for k, v in reading.items()}
        if any(percent >= FULL_PERCENT for percent in now.values()):
            return f"a usage window of the plan is {FULL_PERCENT:.0f} % full"
        if self._start is None:
            self._start = dict(now)
        for name, percent in now.items():
            spent = percent - self._start.get(name, percent)
            if spent >= BUDGET_SHARE * 100:
                return f"this night used {BUDGET_SHARE:.0%} of the {name} window"
        return ""

    def take(self, calls: int = 1) -> str:
        """Ask for ``calls`` calls at once. ``""``: go ahead (they are counted); else why not.

        A request for more than is left is refused without stopping the night:
        a smaller one may still fit.
        """
        with self._lock:
            if self.stopped:
                return self.stopped
            why = self._why_not()
            if why:
                self.stopped = why
                return why
            if self.calls + calls > self.cap:
                return f"the night's {self.cap} model calls are nearly spent"
            self.calls += calls
            return ""
