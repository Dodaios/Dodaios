"""Every parameter the assistant may tune, with the value it ships with and its limits.

Add a parameter here, read it with ``params.get(name)`` where the constant was,
and name the benchmark domain that can measure it. A parameter without such a
domain stays at its default: nothing could tell whether a change helped.

The defaults are the constants the code had before they moved here. Changing a
default is a normal code change; values learned against the old default stay
in effect and are measured again first (see ``live.py``).
"""

from __future__ import annotations

from typing import Final

from .spec import Param, ParamError

__all__ = ["CATALOG", "INDEX", "Index"]

_RECALL = ("recall",)

CATALOG: Final[tuple[Param, ...]] = (
    # ---- memory search (dodaios/memory/vault/store.py)
    Param(
        "recall.entity_boost", 1.5, 1.0, 3.0, step=0.1, domains=_RECALL,
        doc="How much a memory moves up when it names a person or thing from the message.",
    ),
    Param(
        "recall.pinned_boost", 1.2, 1.0, 2.0, step=0.05, domains=_RECALL,
        doc="How much a pinned memory moves up in a search.",
    ),
    Param(
        "recall.recency_floor", 0.7, 0.3, 1.0, step=0.05, domains=_RECALL,
        doc="The weight a very old memory keeps; 1.0 means age does not matter.",
    ),
    Param(
        "recall.recency_days", 365, 30, 1460, step=30, domains=_RECALL,
        doc="Over how many days a memory's freshness fades.",
    ),
    Param(
        "recall.fetch_factor", 4, 2, 12, step=1, domains=_RECALL,
        doc="How many candidates a search ranks, as a multiple of what it returns.",
    ),
    # ---- per-message recall (dodaios/memory/vault/runtime.py)
    Param(
        "recall.turn_limit", 6, 2, 10, step=1, domains=_RECALL,
        doc="The most memories one message may bring up.",
    ),
    Param(
        "recall.turn_max_chars", 900, 300, 1500, step=100, domains=_RECALL,
        doc="The most characters the memories for one message may take in the prompt.",
    ),
    Param(
        "recall.relative_floor", 0.35, 0.05, 0.9, step=0.05, domains=_RECALL,
        doc="How close to the best hit a memory must score to be shown.",
    ),
    Param(
        "recall.lesson_base", 0.6, 0.2, 1.0, step=0.05, domains=_RECALL,
        doc="Where a fitting lesson ranks against the best search hit, before its own fit counts.",
    ),
    Param(
        "recall.lesson_cap", 1.5, 1.0, 2.0, step=0.1, domains=_RECALL,
        doc="How far above the best search hit a lesson may rank at most.",
    ),
    # ---- lessons (dodaios/memory/vault/lessons.py)
    Param(
        "lessons.recall_threshold", 0.4, 0.1, 0.9, step=0.05, domains=_RECALL,
        doc="How much of a lesson's words a message must share for the lesson to come up.",
    ),
    Param(
        "lessons.recall_limit", 3, 1, 6, step=1, domains=_RECALL,
        doc="The most lessons one message may bring up.",
    ),
)


class Index:
    """The declared parameters by name, with the names they had before."""

    def __init__(self, params: tuple[Param, ...]) -> None:
        self.params = params
        self._names: dict[str, Param] = {}
        self._aliases: dict[str, str] = {}
        for param in params:
            if param.name in self._names:
                raise ParamError(f"the parameter {param.name!r} is declared twice")
            self._names[param.name] = param
        for param in params:
            for alias in param.aliases:
                if alias in self._names or alias in self._aliases:
                    raise ParamError(f"the old name {alias!r} is in use")
                self._aliases[alias] = param.name

    def canonical(self, name: str) -> str | None:
        """Today's name for ``name`` (which may be an earlier one); ``None`` when unknown."""
        if name in self._names:
            return name
        return self._aliases.get(name)

    def get(self, name: str) -> Param | None:
        found = self.canonical(name)
        return self._names[found] if found is not None else None

    def by_name(self, name: str) -> Param:
        """The declared parameter. An unknown name is a programming error."""
        found = self.get(name)
        if found is None:
            raise ParamError(f"no parameter is called {name!r}")
        return found


INDEX: Final[Index] = Index(CATALOG)
