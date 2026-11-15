"""The person's input in the managed browser follows the hand and never queues behind the page."""

from __future__ import annotations

import asyncio
import sys
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner():
    previous = sys.stdout
    try:
        from dodaios.society.browser import live_runner
    finally:
        sys.stdout = previous
    return live_runner


class Session:
    """A CDP session whose wheel events are answered when the test says so."""

    def __init__(self, context: Context) -> None:
        self.context = context
        self.detached = False

    async def send(self, method: str, params: dict | None = None) -> dict:
        if method == "Target.getTargetInfo":
            self.context.target_lookups += 1
            return {"targetInfo": {"targetId": "tab-1"}}
        answer = asyncio.get_running_loop().create_future()
        self.context.events.append((method, dict(params or {}), answer))
        return await answer

    async def detach(self) -> None:
        self.detached = True


class Mouse:
    def __init__(self, log: list) -> None:
        self.log = log

    async def click(self, x, y, button="left") -> None:
        self.log.append(("click", x, y))

    async def move(self, x, y) -> None:
        self.log.append(("move", x, y))


class Page:
    def __init__(self) -> None:
        self.viewport_size = {"width": 1280, "height": 800}
        self.log: list = []
        self.mouse = Mouse(self.log)

    def is_closed(self) -> bool:
        return False

    async def evaluate(self, script: str) -> None:
        self.log.append(("next frame",))


class Context:
    def __init__(self) -> None:
        self.pages = [Page()]
        self.events: list[tuple[str, dict, asyncio.Future]] = []
        self.target_lookups = 0

    async def new_cdp_session(self, page) -> Session:
        return Session(self)


@pytest.fixture
def worker(runner):
    worker = runner.Worker()
    worker.context = Context()
    worker.page = worker.context.pages[0]
    worker.manual = True
    return worker


def wheels(worker) -> list[dict]:
    return [params for method, params, _ in worker.context.events if params.get("type")]


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_scroll_does_not_wait_for_the_page_to_answer(worker):
    for step in (10, 20, 30):
        await asyncio.wait_for(
            worker._command("scroll", {"x": 300, "y": 200, "dx": 0, "dy": step}), 2
        )
    await settle()
    # All three are on their way, in order, though the page answered none yet.
    assert [(w["type"], w["x"], w["y"], w["deltaY"]) for w in wheels(worker)] == [
        ("mouseWheel", 300.0, 200.0, 10.0),
        ("mouseWheel", 300.0, 200.0, 20.0),
        ("mouseWheel", 300.0, 200.0, 30.0),
    ]
    assert len(worker.wheels) == 3
    for _, _, answer in worker.context.events:
        answer.set_result({})
    await settle()
    assert worker.wheels == set()


async def test_a_click_after_a_scroll_waits_until_the_page_took_the_scroll(worker):
    await worker._command("scroll", {"x": 300, "y": 200, "dx": 0, "dy": 400})
    await settle()
    click = asyncio.ensure_future(worker._command("click", {"x": 50, "y": 60}))
    await settle()
    assert worker.page.log == []
    worker.context.events[0][2].set_result({})
    await asyncio.wait_for(click, 2)
    # The page's own scroll position follows with its next frame.
    assert worker.page.log == [("next frame",), ("click", 50.0, 60.0)]
    # An input that follows no scroll waits for nothing.
    await worker._command("click", {"x": 51, "y": 61})
    assert worker.page.log[2:] == [("click", 51.0, 61.0)]


async def test_a_page_that_draws_no_frame_does_not_hold_the_click(worker, runner, monkeypatch):
    monkeypatch.setattr(runner, "WHEEL_LANDS_S", 0.05)

    async def never(_script: str) -> None:
        await asyncio.get_running_loop().create_future()

    worker.page.evaluate = never
    await worker._command("scroll", {"x": 300, "y": 200, "dx": 0, "dy": 400})
    await settle()
    worker.context.events[0][2].set_result({})
    await asyncio.wait_for(worker._command("click", {"x": 50, "y": 60}), 2)
    assert worker.page.log == [("click", 50.0, 60.0)]


async def test_a_page_that_stops_answering_bounds_the_scrolls_in_flight(
    worker, runner, monkeypatch
):
    monkeypatch.setattr(runner, "MAX_WHEELS_IN_FLIGHT", 3)
    monkeypatch.setattr(runner, "WHEEL_SETTLE_S", 0.01)
    for _ in range(3):
        await worker._command("scroll", {"x": 1, "y": 1, "dx": 0, "dy": 5})
    with pytest.raises(RuntimeError, match="does not react to scrolling"):
        await worker._command("scroll", {"x": 1, "y": 1, "dx": 0, "dy": 5})
    await settle()
    assert len(wheels(worker)) == 3
    # One answer makes room again.
    worker.context.events[0][2].set_result({})
    await settle()
    await worker._command("scroll", {"x": 1, "y": 1, "dx": 0, "dy": 5})
    await settle()
    assert len(wheels(worker)) == 4
    for task in list(worker.wheels):
        task.cancel()


async def test_a_wheel_event_that_never_arrives_is_forgotten_quietly(worker):
    await worker._command("scroll", {"x": 1, "y": 1, "dx": 0, "dy": 5})
    await settle()
    worker.context.events[0][2].set_exception(RuntimeError("Target closed"))
    await settle()
    assert worker.wheels == set()
    # The next scroll opens a new session instead of using the dead one.
    assert worker.input_cdp is None


async def test_a_scroll_without_a_place_goes_where_the_pointer_was(worker):
    await worker._command("click", {"x": 640, "y": 100, "move_only": True})
    await worker._command("scroll", {"dx": 0, "dy": 5})
    await settle()
    assert [(w["x"], w["y"]) for w in wheels(worker)] == [(640.0, 100.0)]
    for task in list(worker.wheels):
        task.cancel()


async def test_a_tab_is_asked_for_its_id_once(worker):
    for _ in range(5):
        assert await worker.focused() is worker.page
    assert worker.context.target_lookups == 1
    assert worker.tabs == {"tab-1": worker.page}
    # A tab that closed is forgotten, a new one is asked.
    worker.context.pages = [Page()]
    await worker.focused()
    assert worker.context.target_lookups == 2
    assert list(worker.target_ids) == worker.context.pages


async def test_a_new_picture_goes_out_without_waiting_for_the_next_beat(
    worker, runner, monkeypatch
):
    monkeypatch.setattr(runner, "POLL_INTERVAL_S", 30)
    asyncio.get_running_loop().call_later(0.01, worker.frame_ready.set)
    # Without the signal this would sleep the 30 s.
    await asyncio.wait_for(worker.next_frame(time.monotonic() - 1), 5)
    assert not worker.frame_ready.is_set()


@pytest.mark.parametrize(("manual", "expected"), [(True, 1 / 30), (False, 1 / 15)])
async def test_pictures_come_faster_while_the_person_works_in_the_page(
    worker, runner, monkeypatch, manual, expected
):
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    worker.manual = manual
    worker.frame_ready.set()
    await worker.next_frame(time.monotonic())
    assert len(slept) == 1
    assert expected * 0.5 < slept[0] <= expected


async def test_a_real_window_and_the_screenshot_fallback_are_asked_at_their_pace(
    worker, runner, monkeypatch
):
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    worker.capture_fallback = True
    await worker.next_frame(time.monotonic())
    worker.capture_fallback = False
    worker.native = SimpleNamespace(failed=False)
    await worker.next_frame(time.monotonic())
    assert slept == [runner.POLL_INTERVAL_S, runner.POLL_INTERVAL_S]


async def test_a_slow_page_load_does_not_hold_the_next_input(worker, runner, monkeypatch):
    monkeypatch.setattr(runner, "LOAD_WAIT_S", 0.01)
    arrived = asyncio.get_running_loop().create_future()

    async def slow_page():
        await arrived

    await asyncio.wait_for(worker.load(slow_page()), 2)
    assert len(worker.loads) == 1
    arrived.set_exception(RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
    await settle()
    # It failed after the wait: the browser shows its own error page.
    assert worker.loads == set()


async def test_a_page_load_that_fails_at_once_is_reported(worker):
    async def refused():
        raise RuntimeError("net::ERR_FAILED")

    with pytest.raises(RuntimeError, match="ERR_FAILED"):
        await worker.load(refused())
    await settle()
    assert worker.loads == set()


async def test_a_fast_page_load_is_finished_when_the_input_returns(worker):
    done: list[str] = []

    async def fast():
        await asyncio.sleep(0)
        done.append("loaded")

    await worker.load(fast())
    assert done == ["loaded"]


@pytest.mark.parametrize(
    ("proposal", "scheme"),
    [
        ({"navigate": {"url": "https://example.org/"}}, ""),
        ({"navigate": {"url": "example.org:8080/path"}}, ""),
        ({"navigate": {"url": "about:blank"}}, ""),
        ({"search": {"query": "chrome://settings explained"}}, ""),
        ({"navigate": {"url": "chrome://settings"}}, "chrome"),
        ({"navigate": {"url": " FILE:///etc/hosts", "new_tab": True}}, "file"),
        ({"go_to_url": {"url": "devtools://devtools/bundled/inspector.html"}}, "devtools"),
        ({"click": {"index": 3}}, ""),
    ],
)
def test_the_agent_opens_websites_only(runner, proposal, scheme):
    assert runner.internal_address(proposal) == scheme


async def test_a_tab_that_is_just_navigating_is_asked_again(worker):
    """A real Chrome window: the visible tab is found though its page is mid-navigation."""
    answers: list = [RuntimeError("Execution context was destroyed"), True]

    async def evaluate(_script: str):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def title() -> str:
        return "Upload fixture"

    worker.page.evaluate = evaluate
    worker.page.title = title
    # The window's caption still names the page before the navigation.
    worker.native = SimpleNamespace(title=lambda: "Live browser fixture - Chrome", failed=False)
    assert await worker.focused(strict_native=True) is worker.page
    assert answers == []


async def test_a_tab_that_never_answers_still_fails_the_question(worker, runner, monkeypatch):
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(runner.asyncio, "sleep", no_wait)
    asked = 0

    async def evaluate(_script: str):
        nonlocal asked
        asked += 1
        raise RuntimeError("Execution context was destroyed")

    worker.page.evaluate = evaluate
    with pytest.raises(RuntimeError, match="Execution context"):
        await worker.shown(worker.page)
    assert asked == 5
