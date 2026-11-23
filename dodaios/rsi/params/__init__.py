"""Parameters: numbers the assistant may tune, inside limits it may not move.

``params.get("recall.turn_limit")`` replaces a constant in the code. The
catalog declares every parameter with its shipped default and its limits; the
store keeps what was learned and survives app updates. See docs/self-improvement.md.
"""

from __future__ import annotations

from .catalog import CATALOG, INDEX, Index
from .live import (
    DB_NAME,
    Entry,
    ParamStore,
    get,
    install,
    installed,
    learned,
    release,
    text_for,
    values,
)
from .spec import Param, ParamError

__all__ = [
    "CATALOG",
    "DB_NAME",
    "INDEX",
    "Entry",
    "Index",
    "Param",
    "ParamError",
    "ParamStore",
    "get",
    "install",
    "installed",
    "learned",
    "release",
    "text_for",
    "values",
]
