"""Every test here gets a private jobs ledger in memory."""

from __future__ import annotations

import pytest

from dodaios.orchestrator import jobs


@pytest.fixture(autouse=True)
def ledger():
    store = jobs.JobLedger(":memory:")
    jobs.set_ledger(store)
    try:
        yield store
    finally:
        jobs.set_ledger(None)
        store.close()
