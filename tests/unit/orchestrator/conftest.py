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


def holding(_cell: str, _root: str) -> dict:
    """The binding of a run whose coding policy holds it (the old enforce mode)."""
    from dodaios.rsi.policy import Policy

    policy = Policy(hold=True)
    return {"policy_id": policy.id, "arm": "active", "policy_json": policy.to_text()}
