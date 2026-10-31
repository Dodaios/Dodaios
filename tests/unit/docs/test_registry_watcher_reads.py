"""The doc watcher must not reload on its own reads.

BC-250 2026-10-29: DocIndexReloaded fired about every 0.6 s for hours (118,033
of the day's 118,372 flight-recorder events) and the idle server used about a
quarter of a core. watchdog 6 reports a plain read of a file as `opened` and
`closed_no_write`; the watcher reloaded on any event of a .md file, and a
reload reads every .md file, so each reload scheduled the next one.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dodaios.docs import registry as registry_module
from dodaios.docs.registry import DocRegistry

DOC = """---
title: "Concept: Router"
slug: router-concept
diataxis: explanation
status: active
phase: 5
tags: [brain]
---

# Concept: Router

Body.
"""

pytestmark = pytest.mark.skipif(
    not registry_module._HAVE_WATCHDOG, reason="watchdog is not installed"
)


async def _count_reloads(registry: DocRegistry, seconds: float) -> int:
    calls = 0
    original = registry.reload

    async def counting_reload() -> None:
        nonlocal calls
        calls += 1
        await original()

    registry.reload = counting_reload  # type: ignore[method-assign]
    await asyncio.sleep(seconds)
    registry.reload = original  # type: ignore[method-assign]
    return calls


@pytest.mark.asyncio
async def test_reading_the_docs_does_not_trigger_another_reload(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "router.md").write_text(DOC, encoding="utf-8")
    registry = DocRegistry([root], index_db=None, debounce_ms=50)
    try:
        await registry.ensure_loaded()
        assert registry.start_watcher(asyncio.get_running_loop())
        await registry.reload()  # reads every .md file, as each reload does
        assert await _count_reloads(registry, 1.5) == 0
    finally:
        registry.close()


def test_a_read_does_not_count_as_a_doc_change(tmp_path: Path) -> None:
    """macOS delivers a read as ``modified`` because the access time moved."""
    root = tmp_path / "docs"
    root.mkdir()
    page = root / "router.md"
    page.write_text(DOC, encoding="utf-8")
    registry = DocRegistry([root], index_db=None)
    try:
        registry._remember_docs()
        page.read_bytes()
        assert registry._doc_bytes_changed(str(page)) is False
        page.write_text(DOC.replace("Body.", "Edited body."), encoding="utf-8")
        assert registry._doc_bytes_changed(str(page)) is True
        page.unlink()
        assert registry._doc_bytes_changed(str(page)) is True
    finally:
        registry.close()


@pytest.mark.asyncio
async def test_an_edited_doc_is_still_reloaded(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    page = root / "router.md"
    page.write_text(DOC, encoding="utf-8")
    registry = DocRegistry([root], index_db=None, debounce_ms=50)
    try:
        await registry.ensure_loaded()
        assert registry.start_watcher(asyncio.get_running_loop())
        await asyncio.sleep(0.3)
        calls = 0
        original = registry.reload

        async def counting_reload() -> None:
            nonlocal calls
            calls += 1
            await original()

        registry.reload = counting_reload  # type: ignore[method-assign]
        page.write_text(DOC.replace("Body.", "Edited body."), encoding="utf-8")
        for _ in range(40):
            await asyncio.sleep(0.05)
            if calls:
                break
        registry.reload = original  # type: ignore[method-assign]
        assert calls >= 1
    finally:
        registry.close()
