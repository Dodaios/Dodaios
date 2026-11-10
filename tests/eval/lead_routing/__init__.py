"""Lead routing evals: does the typed lead pick the right first tool?

The golden set lives in ``tests/fixtures/lead_routing/*.yaml``. See
``docs/lead-routing-evals.md`` for what it measures and how to run it.
"""
from __future__ import annotations

from .cases import Case, Expect, load_cases, validate_cases
from .catalog import LeadCatalog, build_lead_catalog
from .scoring import (
    CaseResult,
    Recording,
    Report,
    format_table,
    load_recordings,
    score_case,
    score_cases,
)

__all__ = [
    "Case",
    "CaseResult",
    "Expect",
    "LeadCatalog",
    "Recording",
    "Report",
    "build_lead_catalog",
    "format_table",
    "load_recordings",
    "load_cases",
    "score_case",
    "score_cases",
    "validate_cases",
]
