"""Benchmark tasks from coding work the person already had done.

The coding CLIs keep a record of every session, and the repository keeps every
merged pull request. Together they say what was asked and what the right
result was, for work that already happened: tasks with a known answer from the
first day, before the app has recorded a single run of its own.

    python -m dodaios.rsi.bench.past_work --repo .

:mod:`.sessions` reads the records, :mod:`.history` reads the repository,
:mod:`.tasks` joins them, :mod:`.intake` stores them (docs/self-improvement.md,
"Tasks from past coding work"). Everything is read locally; nothing is sent
anywhere.
"""

from __future__ import annotations

from dodaios.rsi.bench.past_work.history import (
    History,
    MergedChange,
    merged_changes,
    read_history,
)
from dodaios.rsi.bench.past_work.intake import Taken, read_changes, take_in
from dodaios.rsi.bench.past_work.sessions import PastSession, read_sessions
from dodaios.rsi.bench.past_work.tasks import (
    LeftOut,
    Mined,
    Piece,
    logged_briefs,
    mine,
    pieces,
)

__all__ = [
    "History",
    "LeftOut",
    "MergedChange",
    "Mined",
    "PastSession",
    "Piece",
    "Taken",
    "logged_briefs",
    "merged_changes",
    "mine",
    "pieces",
    "read_changes",
    "read_history",
    "read_sessions",
    "take_in",
]
