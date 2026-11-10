"""Splitting and trimming stay fast on long runs of spaces (no ReDoS shape)."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from dodaios.notify.reminders import split_dump
from dodaios.notify.when import _strip_trailer

_NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def test_split_dump_is_linear_on_long_space_runs() -> None:
    text = "buy milk" + " " * 50_000 + "x"
    started = time.perf_counter()
    split_dump(text, now=_NOW)
    assert time.perf_counter() - started < 2.0


def test_split_dump_still_splits_on_connectors() -> None:
    items = split_dump("buy milk and call mom, then water the plants", now=_NOW)
    assert [item.text.lower() for item in items] == ["buy milk", "call mom", "water the plants"]


def test_strip_trailer_drops_one_dangling_word() -> None:
    assert _strip_trailer("call mom at") == "call mom"
    assert _strip_trailer("pagar la renta a las") == "pagar la renta"
    assert _strip_trailer("buy a hat") == "buy a hat"
    assert _strip_trailer("cat") == "cat"


def test_strip_trailer_is_fast_on_long_space_runs() -> None:
    started = time.perf_counter()
    _strip_trailer("x" + " " * 50_000 + "y")
    assert time.perf_counter() - started < 1.0
