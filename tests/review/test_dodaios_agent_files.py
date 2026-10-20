"""Runtime tool boundaries of the review pipeline."""
from __future__ import annotations

from dodaios.core.review.spawns import DEFAULT_REVIEWER_TOOLS, DEFAULT_WORKER_TOOLS


def test_runtime_reviewer_cannot_edit_or_execute() -> None:
    assert DEFAULT_REVIEWER_TOOLS == ("Read", "Grep", "Glob")


def test_runtime_worker_has_its_required_tools() -> None:
    assert set(DEFAULT_WORKER_TOOLS) == {"Read", "Write", "Edit", "Bash", "Grep", "Glob"}
