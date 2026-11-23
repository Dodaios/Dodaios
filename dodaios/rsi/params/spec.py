"""What a parameter is: a number the assistant may tune, inside limits it may not move.

Behaviour that used to be a constant in the code (how strongly a pinned memory
is preferred, how many memories a message may bring up) is declared here as a
:class:`Param`: a name, the value the app ships with, and the limits. The
limits are part of the kernel. A learner can move a value between them and can
never widen them.

A name is for ever. When a parameter is renamed, the old name goes into
``aliases`` of the new one, so a value learned under the old name keeps
working after the update.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Param", "ParamError", "Value"]

Value = int | float | bool


class ParamError(ValueError):
    """A value or a name that is not valid for the declared parameters."""


@dataclass(frozen=True, slots=True)
class Param:
    #: ``<area>.<what>``, lower case. Never reused for another meaning.
    name: str
    #: The value the app ships with.
    default: Value
    #: Limits, both included. ``None`` for a bool.
    low: float | None = None
    high: float | None = None
    #: One sentence a person can read: what a higher value does.
    doc: str = ""
    #: Benchmark domains that can measure a change of it. Empty: nothing can, so
    #: no learner may change it.
    domains: tuple[str, ...] = ()
    #: Names this parameter had in earlier versions.
    aliases: tuple[str, ...] = ()
    #: The smallest step that is worth trying (a hint for the tuner).
    step: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.default, bool):
            if self.low is not None or self.high is not None:
                raise ParamError(f"{self.name}: a switch has no limits")
            return
        if self.low is None or self.high is None:
            raise ParamError(f"{self.name}: a number needs both limits")
        if not self.low <= self.default <= self.high:
            raise ParamError(f"{self.name}: the default is outside its own limits")

    @property
    def kind(self) -> type:
        return type(self.default)

    def coerce(self, value: Any) -> Value:
        """``value`` as this parameter's type, or :class:`ParamError`."""
        if self.kind is bool:
            if not isinstance(value, bool):
                raise ParamError(f"{self.name} is on or off, not {value!r}")
            return value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ParamError(f"{self.name} is a number, not {value!r}")
        if value != value or value in (float("inf"), float("-inf")):
            raise ParamError(f"{self.name} is a number, not {value!r}")
        if self.kind is int:
            if float(value) != int(value):
                raise ParamError(f"{self.name} is a whole number, not {value!r}")
            value = int(value)
        else:
            value = float(value)
        if not self.low <= value <= self.high:
            raise ParamError(f"{self.name} must be {self.low} to {self.high}, not {value!r}")
        return value

    def valid(self, value: Any) -> bool:
        try:
            self.coerce(value)
        except ParamError:  # "not valid" is the answer this method exists to give
            return False
        return True
