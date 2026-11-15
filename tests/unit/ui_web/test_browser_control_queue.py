"""The live browser socket's input queue: order kept, motion folded together."""

from __future__ import annotations

import asyncio

import pytest

from dodaios.ui.web.society_browser_routes import ControlQueue


def scroll(dy: float, x: float = 10, y: float = 20, **more) -> dict:
    return {"x": x, "y": y, "dx": 0, "dy": dy, **more}


async def drain(queue: ControlQueue, count: int) -> list[tuple[str, dict, str]]:
    return [await asyncio.wait_for(queue.get(), 1) for _ in range(count)]


async def test_wheel_events_waiting_behind_each_other_become_one():
    queue = ControlQueue()
    for step in range(1, 121):
        queue.put("scroll", scroll(15, x=step, y=step + 1), "g")
    assert await drain(queue, 1) == [("scroll", {"x": 120, "y": 121, "dx": 0, "dy": 1800}, "g")]


async def test_an_input_between_two_scrolls_keeps_its_place():
    queue = ControlQueue()
    queue.put("scroll", scroll(10), "g")
    queue.put("scroll", scroll(10), "g")
    queue.put("click", {"x": 1, "y": 2}, "g")
    queue.put("scroll", scroll(-5), "g")
    queue.put("scroll", scroll(-5), "g")
    assert [(op, args.get("dy")) for op, args, _ in await drain(queue, 3)] == [
        ("scroll", 20),
        ("click", None),
        ("scroll", -10),
    ]


async def test_scrolls_made_for_another_picture_stay_apart():
    queue = ControlQueue()
    queue.put("scroll", scroll(10), "old")
    queue.put("scroll", scroll(10), "new")
    queue.put("scroll", scroll(10, geometry_id="a"), "new")
    queue.put("scroll", scroll(10, geometry_id="b"), "new")
    assert [(args["dy"], generation) for _, args, generation in await drain(queue, 4)] == [
        (10, "old"),
        (10, "new"),
        (10, "new"),
        (10, "new"),
    ]


async def test_only_the_newest_hover_waits_and_behind_every_input():
    queue = ControlQueue()
    for x in range(50):
        queue.put("click", {"x": x, "y": 0, "move_only": True}, "g")
    queue.put("key", {"key": "Enter"}, "g")
    # The key came after those motions: they are older than it and dropped.
    queue.put("click", {"x": 99, "y": 0, "move_only": True}, "g")
    assert [(op, args.get("x")) for op, args, _ in await drain(queue, 2)] == [
        ("key", None),
        ("click", 99),
    ]


async def test_a_browser_far_behind_refuses_more_input():
    queue = ControlQueue(maxsize=3)
    for n in range(3):
        queue.put("key", {"key": str(n)}, "g")
    with pytest.raises(asyncio.QueueFull):
        queue.put("key", {"key": "x"}, "g")
    # Wheel events still fold into a waiting scroll, and motion still fits.
    queue = ControlQueue(maxsize=1)
    queue.put("scroll", scroll(5), "g")
    queue.put("scroll", scroll(5), "g")
    queue.put("click", {"x": 1, "y": 1, "move_only": True}, "g")
    assert [args.get("dy") for _, args, _ in await drain(queue, 2)] == [10, None]


async def test_the_reader_waits_for_the_next_input():
    queue = ControlQueue()
    waiting = asyncio.ensure_future(queue.get())
    await asyncio.sleep(0)
    assert not waiting.done()
    queue.put("key", {"key": "a"}, "g")
    assert await asyncio.wait_for(waiting, 1) == ("key", {"key": "a"}, "g")
