"""A viewer's panel sets the page size; the agent's own tasks never see it."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest


class Page:
    def __init__(self) -> None:
        self.viewport_size = {"width": 1280, "height": 800}
        self.sized: list[tuple[int, int]] = []

    def is_closed(self) -> bool:
        return False

    async def set_viewport_size(self, size: dict) -> None:
        self.viewport_size = dict(size)
        self.sized.append((size["width"], size["height"]))


@pytest.fixture
def worker():
    previous = sys.stdout
    try:
        from dodaios.society.browser import live_runner
    finally:
        sys.stdout = previous
    worker = live_runner.Worker()
    worker.page = Page()
    worker.context = SimpleNamespace(pages=[worker.page, Page()])
    worker.viewers = True
    return worker


async def test_a_watched_page_takes_the_panel_size_and_goes_back(worker):
    await worker._command("viewport", {"width": 420, "height": 900})
    assert [page.viewport_size for page in worker.context.pages] == [
        {"width": 420, "height": 900}
    ] * 2
    assert worker.view_fields(worker.page) == {"width": 420, "height": 900}
    await worker._command("viewport", {})
    assert worker.page.viewport_size == {"width": 1280, "height": 800}


async def test_an_unchanged_size_is_not_set_again(worker):
    await worker._command("viewport", {"width": 420, "height": 900})
    await worker.fit_views()
    assert worker.page.sized == [(420, 900)]


async def test_the_size_is_kept_within_bounds(worker):
    await worker._command("viewport", {"width": 80, "height": 9000})
    assert worker.page.viewport_size == {"width": 320, "height": 2560}


async def test_the_agent_task_runs_at_the_usual_size(worker):
    await worker._command("viewport", {"width": 420, "height": 900})
    worker.job = asyncio.get_running_loop().create_future()
    await worker.fit_views()
    assert worker.page.viewport_size == {"width": 1280, "height": 800}
    worker.job.set_result(None)
    await worker.fit_views()
    assert worker.page.viewport_size == {"width": 420, "height": 900}


async def test_nobody_watching_means_the_usual_size(worker):
    await worker._command("viewport", {"width": 420, "height": 900})
    worker.viewers = False
    await worker.fit_views()
    assert worker.page.viewport_size == {"width": 1280, "height": 800}


async def test_a_real_chrome_window_keeps_its_own_size(worker):
    worker.native = object()
    await worker._command("viewport", {"width": 420, "height": 900})
    assert worker.page.sized == []
