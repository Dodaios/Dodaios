"""Pointer telemetry shows the agent's approved browser mouse input, never typing."""

import pytest

from dodaios.society.browser.pointer import PointerTracker, glide_seconds


async def test_pointer_tracks_real_click_and_keeps_click_when_mouse_moves():
    events = []

    async def send(**kwargs):
        return {"ok": True}

    async def no_wait(seconds):
        return None

    tracker = PointerTracker("generation", lambda kind, **data: events.append((kind, data)),
                             lambda: True, lambda x, y: (x * 2, y * 2 + 80, 2560, 1680),
                             sleep=no_wait)
    observed = tracker.wrap(send)
    await observed("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 20, "y": 30})
    await observed("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 40, "y": 50})
    assert events[-1][1]["x"] == 80
    assert events[-1][1]["click_id"] == 1
    assert events[-1][1]["click_x"] == 40
    assert events[-1][1]["click_y"] == 140
    tracker.clear()
    assert events[-1][1]["visible"] is False
    await observed("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 40, "y": 50})
    assert events[-1][1]["click_id"] == 0


async def test_pointer_never_exposes_typed_text_or_unapproved_activity():
    events = []

    async def send(**kwargs):
        return {}

    enabled = False
    tracker = PointerTracker("g", lambda *args, **kwargs: events.append(kwargs),
                             lambda: enabled, lambda x, y: (x, y, 1280, 800))
    observed = tracker.wrap(send)
    await observed("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 10, "y": 10})
    enabled = True
    await observed("Input.insertText", {"text": "private login input"})
    assert events == []


async def test_failed_mouse_command_has_no_click_marker():
    events = []

    async def send(**kwargs):
        raise RuntimeError("Disconnected")

    async def no_wait(seconds):
        return None

    tracker = PointerTracker("g", lambda *args, **kwargs: events.append(kwargs),
                             lambda: True, lambda x, y: (x, y, 1280, 800), sleep=no_wait)
    with pytest.raises(RuntimeError, match="Disconnected"):
        await tracker.wrap(send)("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 1, "y": 2})
    # The arrow may have travelled there; no press is marked for a failed click.
    assert all(event["click_id"] == 0 for event in events)


async def test_a_move_is_shown_first_and_sent_after_the_arrow_has_travelled():
    timeline = []

    async def send(**kwargs):
        timeline.append(("sent", kwargs["params"]["type"]))
        return {}

    async def wait(seconds):
        timeline.append(("waited", round(seconds, 3)))

    tracker = PointerTracker("g", lambda kind, **data: timeline.append(("shown", data["x"], data["click_id"])),
                             lambda: True, lambda x, y: (x, y, 1280, 800), sleep=wait)
    observed = tracker.wrap(send)
    await observed("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 100, "y": 100})
    # The first move enters in the middle of the page and travels from there.
    assert timeline == [
        ("shown", 640.0, 0),
        ("shown", 100.0, 0),
        ("waited", round(glide_seconds(((640 - 100) ** 2 + (400 - 100) ** 2) ** 0.5) - 0.06, 3)),
        ("sent", "mousePressed"),
        ("shown", 100.0, 1),
    ]
    timeline.clear()
    await observed("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 600, "y": 100})
    assert timeline == [
        ("shown", 600.0, 1),
        ("waited", round(glide_seconds(500) - 0.06, 3)),
        ("sent", "mousePressed"),
        ("shown", 600.0, 2),
    ]
    timeline.clear()
    # The release and a press on the same point need no second glide.
    await observed("Input.dispatchMouseEvent", {"type": "mousePressed", "x": 601, "y": 100})
    assert [entry[0] for entry in timeline] == ["sent", "shown"]


async def test_no_glide_wait_while_the_person_drives():
    waits = []

    async def send(**kwargs):
        return {}

    async def wait(seconds):
        waits.append(seconds)

    tracker = PointerTracker("g", lambda *args, **kwargs: None, lambda: False,
                             lambda x, y: (x, y, 1280, 800), sleep=wait)
    observed = tracker.wrap(send)
    tracker.shown = (0.0, 0.0)
    await observed("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 900, "y": 500})
    assert waits == []


def test_glide_matches_the_viewer_arrow():
    assert glide_seconds(0) == 0
    assert glide_seconds(40) == 0.28
    assert glide_seconds(500) == pytest.approx(0.39)
    assert glide_seconds(5000) == 0.65


async def test_native_upgrade_waits_for_the_active_browser_task(tmp_path):
    import asyncio
    import os
    from types import SimpleNamespace
    from dodaios.society.browser.live import LiveSessions

    if os.name != "nt":
        pytest.skip("Windows native-session upgrade")
    live = LiveSessions(tmp_path)
    old = SimpleNamespace(closed=False, state={"full_window": False},
                          run_lock=asyncio.Lock(), control_lock=asyncio.Lock(),
                          control_owner=None, window_upgrade_pending=False)
    agent = SimpleNamespace(agent_id="busy", browser_mode="own")
    live.profiles.assign(agent.agent_id, "own", None)
    old.profile_binding = live.profiles.resolve(agent)
    old.profile_lease = None
    live.sessions["busy"] = old
    await old.run_lock.acquire()
    try:
        assert await live.ensure(agent, window_view=True) is old
        assert old.window_upgrade_pending
        assert not old.closed
    finally:
        old.run_lock.release()
