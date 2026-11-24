"""Guards shared by the kernel tests."""

from __future__ import annotations

import pytest

from dodaios.rsi import night as nights


@pytest.fixture
def real_past_work() -> None:
    """Ask for this to let a night read coding records (from folders the test names)."""


@pytest.fixture(autouse=True)
def no_real_coding_records(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """A night under test never reads this machine's own coding records."""
    if "real_past_work" not in request.fixturenames:
        monkeypatch.setattr(nights, "_past_work", lambda bench, homes=None: {})
