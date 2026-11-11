"""Every test here gets a private jobs ledger and project store in memory."""

from __future__ import annotations

import pytest

from dodaios.orchestrator import jobs
from dodaios.projects.store import ProjectStore, set_store


@pytest.fixture(autouse=True)
def ledger():
    store = jobs.JobLedger(":memory:")
    jobs.set_ledger(store)
    try:
        yield store
    finally:
        jobs.set_ledger(None)
        store.close()


@pytest.fixture
def store():
    projects = ProjectStore(":memory:")
    set_store(projects)
    try:
        yield projects
    finally:
        set_store(None)
        projects.close()
