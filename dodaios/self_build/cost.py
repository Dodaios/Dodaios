"""What a build cost: every model call for it carries its caller tag.

Builders run their model calls inside :func:`attributed`; the cost ledger
then stores ``caller = "self_build:<id>"`` and :func:`spent` sums it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

from dodaios.costs.ledger import ledger_path, read_usage, usage_context

from .ledger import now_ms
from .records import BuildRecord, caller_for


@contextlib.contextmanager
def attributed(build_id: str) -> Iterator[None]:
    """Tag every model call inside the block with the build's caller."""
    with usage_context(caller_for(build_id)):
        yield


def spent(record: BuildRecord, *, path: Path | None = None) -> dict[str, float]:
    """Tokens and dollars recorded for ``record`` since it was opened."""
    source = path or ledger_path()
    totals = {"tokens": 0.0, "usd": 0.0}
    if not source.is_file():
        return totals
    caller = record.caller
    for row in read_usage(source, record.created_ms, now_ms()):
        if row.caller == caller:
            totals["tokens"] += row.tokens_in + row.tokens_out
            totals["usd"] += row.cost_usd
    return totals
