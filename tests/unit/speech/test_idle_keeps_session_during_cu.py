"""The process-wide "a Computer-Use mission is running" probe.

Live failure 2026-06-10 20:46: a voice call hung up on its idle timer while a
CU mission was still clicking. ``cu_mission_active()`` is the probe that tells
the voice side a mission is live (the call's termination snapshot records it);
a cancelled mission is winding down and must not count.
"""
from __future__ import annotations

import pytest

from dodaios.harness.computer_use_context import (
    cu_mission_active,
    register_active_cu_token,
)


class FakeToken:
    def __init__(self, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled


@pytest.fixture(autouse=True)
def _clear_cu_token():
    register_active_cu_token(None)
    yield
    register_active_cu_token(None)


# ---------------------------------------------------------------------------
# cu_mission_active — the process-wide "a CU mission is running" probe
# ---------------------------------------------------------------------------


def test_cu_mission_active_false_without_token() -> None:
    assert cu_mission_active() is False


def test_cu_mission_active_true_with_live_token() -> None:
    register_active_cu_token(FakeToken())
    assert cu_mission_active() is True


def test_cu_mission_active_false_for_cancelled_token() -> None:
    # A cancelled mission is winding down — it must not keep the session
    # open (the hangup that cancelled it wants the session CLOSED).
    register_active_cu_token(FakeToken(cancelled=True))
    assert cu_mission_active() is False
