"""Tunable parts of the score, with the defaults the docs describe.

The owner edits an optional JSON file (``agent_score.json`` in the app data
directory, or ``--config``)::

    {"importance": {"mail": 1.0, "settings": 0.2},
     "signal_weights": {"owner_correction": 0.5},
     "latency_lambda_usd_per_s": 0.001}

Unknown keys are ignored; values outside their range are clamped.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .classes import DEFAULT_IMPORTANCE

log = logging.getLogger(__name__)

#: How much of a turn's utility each signal removes (or, for ``verified``, adds).
DEFAULT_SIGNAL_WEIGHTS: Final[dict[str, float]] = {
    "cancelled_base": 0.25,  # a cancelled turn starts here instead of 1.0
    "tool_error": 0.3,  # times the share of failed tool calls
    "verify_failed": 0.5,
    "verify_unverified": 0.1,
    "verified": 0.1,  # bonus, utility stays <= 1
    "unbacked_claim": 0.5,
    "approval_denied": 0.3,
    "owner_correction": 0.4,
    "repeated_request": 0.4,
    "undo": 0.4,
    "routing_blend": 0.15,  # share of the class utility taken from the routing eval
}

DEFAULT_LAMBDA_USD_PER_S: Final[float] = 0.001
#: Maximum share of turns that may carry an unbacked done-claim for a window to be rated.
DEFAULT_MAX_UNBACKED_RATE: Final[float] = 0.02
#: A routing accuracy drop larger than this between two runs is a self-change regression.
DEFAULT_REGRESSION_TOLERANCE: Final[float] = 0.05


@dataclass(slots=True)
class ScoreConfig:
    importance: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_IMPORTANCE))
    signal_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SIGNAL_WEIGHTS))
    latency_lambda_usd_per_s: float = DEFAULT_LAMBDA_USD_PER_S
    max_unbacked_rate: float = DEFAULT_MAX_UNBACKED_RATE
    regression_tolerance: float = DEFAULT_REGRESSION_TOLERANCE

    def weight(self, name: str) -> float:
        return self.signal_weights.get(name, DEFAULT_SIGNAL_WEIGHTS.get(name, 0.0))


def _num(value: Any, lo: float, hi: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(hi, max(lo, float(value)))


def load_config(path: Path | None) -> ScoreConfig:
    """Defaults, overlaid with the owner's file when it exists and parses."""
    cfg = ScoreConfig()
    if path is None or not Path(path).is_file():
        return cfg
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("agent score: %s is not readable JSON; using defaults", path)
        return cfg
    if not isinstance(raw, dict):
        return cfg
    for key, value in (raw.get("importance") or {}).items():
        n = _num(value, 0.0, 10.0)
        if n is not None:
            cfg.importance[str(key)] = n
    for key, value in (raw.get("signal_weights") or {}).items():
        n = _num(value, 0.0, 1.0)
        if n is not None:
            cfg.signal_weights[str(key)] = n
    for attr, hi in (
        ("latency_lambda_usd_per_s", 100.0),
        ("max_unbacked_rate", 1.0),
        ("regression_tolerance", 1.0),
    ):
        n = _num(raw.get(attr), 0.0, hi)
        if n is not None:
            setattr(cfg, attr, n)
    return cfg
