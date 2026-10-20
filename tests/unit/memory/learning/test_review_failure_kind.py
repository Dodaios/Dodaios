"""A failed learning review logs a fixed word, never anything from the call."""

from __future__ import annotations

import asyncio

from dodaios.memory.learning.review import _failure_kind


def test_failure_kind_is_a_fixed_word() -> None:
    assert _failure_kind(TimeoutError()) == "timeout"
    assert _failure_kind(asyncio.CancelledError()) == "cancelled"
    assert _failure_kind(RuntimeError("provider said: secret conversation text")) == "error"
