"""Brief taps, modifier transitions and listener replacement must not lose shortcuts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from jarvis.appshot.hotkey import AppshotShortcut
from jarvis.appshot.key_events import AppshotKeyEvents


def test_a_press_and_release_without_a_poll_interval_fires_once():
    events = []
    listener = AppshotKeyEvents()
    listener.register([["z", None, lambda: events.append("recording")]])
    key = SimpleNamespace(vk=0x5A, char="z")
    listener._on_press_key(key)
    listener._on_press_key(key)  # OS key repeat must not toggle recording twice.
    listener._on_release_key(key)
    assert events == ["recording"]


def test_control_characters_and_release_order_keep_the_same_letter(monkeypatch):
    # The test presses keys the real keyboard does not hold. Trusting the OS
    # here would drop the simulated Ctrl before Z arrives.
    monkeypatch.setattr("jarvis.appshot.key_events.key_is_down", lambda *_args: None)
    events = []
    listener = AppshotKeyEvents()
    listener.register([["control + z", None, lambda: events.append("recording")]])
    ctrl = SimpleNamespace(name="ctrl_l", char=None)
    listener._on_press_key(ctrl)
    listener._on_press_key(SimpleNamespace(vk=0x5A, char="\x1a"))
    listener._on_release_key(ctrl)
    listener._on_release_key(SimpleNamespace(vk=0x5A, char="z"))
    assert events == ["recording"]
    assert not listener._held


def test_a_shorter_chord_does_not_fire_with_the_longer_one(monkeypatch):
    monkeypatch.setattr("jarvis.appshot.key_events.key_is_down", lambda *_args: None)
    events = []
    listener = AppshotKeyEvents()
    listener.register([
        ["control + z", None, lambda: events.append("long")],
        ["z", None, lambda: events.append("short")],
    ])
    ctrl = SimpleNamespace(name="ctrl_l", char=None)
    key = SimpleNamespace(vk=0x5A, char="z")
    listener._on_press_key(ctrl)
    listener._on_press_key(key)
    listener._on_release_key(ctrl)
    listener._on_release_key(key)
    assert events == ["long"]


CTRL = SimpleNamespace(name="ctrl_l", char=None)
SHIFT = SimpleNamespace(name="shift", char=None)
X = SimpleNamespace(vk=0x58, char="x")
Y = SimpleNamespace(vk=0x59, char="y")
B = SimpleNamespace(vk=0x42, char="b")


def _area_and_recording(monkeypatch):
    monkeypatch.setattr("jarvis.appshot.key_events.key_is_down", lambda *_args: None)
    events = []
    listener = AppshotKeyEvents()
    listener.register([
        ["control + x", None, lambda: events.append("area")],
        ["control + y", None, lambda: events.append("recording")],
    ])
    return listener, events


def test_a_held_modifier_serves_the_next_shortcut_too(monkeypatch):
    listener, events = _area_and_recording(monkeypatch)
    listener._on_press_key(CTRL)
    for key in (X, Y, X):
        listener._on_press_key(key)
        listener._on_release_key(key)
    listener._on_release_key(CTRL)
    assert events == ["area", "recording", "area"]


def test_the_letter_may_go_down_before_the_modifier(monkeypatch):
    listener, events = _area_and_recording(monkeypatch)
    listener._on_press_key(X)
    listener._on_press_key(X)  # The held letter repeats before Ctrl joins.
    for _ in range(2):
        listener._on_press_key(CTRL)
        listener._on_release_key(CTRL)
    listener._on_release_key(X)
    assert events == ["area", "area"]


def test_a_shorter_chord_does_not_start_when_the_longer_one_loses_a_key(monkeypatch):
    monkeypatch.setattr("jarvis.appshot.key_events.key_is_down", lambda *_args: None)
    events = []
    listener = AppshotKeyEvents()
    listener.register([
        ["control + shift + b", None, lambda: events.append("long")],
        ["control + b", None, lambda: events.append("short")],
    ])
    for key in (CTRL, SHIFT, B):
        listener._on_press_key(key)
    listener._on_release_key(SHIFT)
    listener._on_press_key(Y)  # An unrelated key must not start it either.
    listener._on_release_key(Y)
    listener._on_release_key(B)
    listener._on_release_key(CTRL)
    assert events == ["long"]


def test_a_key_whose_release_was_lost_still_starts_the_chord_again(monkeypatch):
    down = {"x": True}
    listener, events = _area_and_recording(monkeypatch)
    monkeypatch.setattr(
        "jarvis.appshot.key_events.key_is_down", lambda name, _vk=None: down.get(name),
    )
    listener._on_press_key(X)  # Its release never arrives.
    down["x"] = False
    listener._on_press_key(Y)
    listener._on_release_key(Y)
    assert "x" not in listener._held
    listener._on_press_key(CTRL)
    down["x"] = True
    listener._on_press_key(X)
    listener._on_release_key(X)
    assert events == ["area"]


def test_a_stuck_modifier_does_not_turn_the_next_letter_into_the_chord(monkeypatch):
    # The OS says every leftover key is up. Z itself is the key this event
    # is about, so the sweep must leave it for the press and release edges.
    monkeypatch.setattr(
        "jarvis.appshot.key_events.key_is_down",
        lambda name, _vk=None: False if name != "z" else None,
    )
    events = []
    listener = AppshotKeyEvents()
    listener.register([["control + z", None, lambda: events.append("go")]])
    listener._held.add("ctrl_l")
    key = SimpleNamespace(vk=0x5A, char="z")
    listener._on_press_key(key)
    listener._on_release_key(key)
    assert events == []
    assert "ctrl_l" not in listener._held


def test_numpad_keys_keep_the_shared_binding_vocabulary():
    listener = AppshotKeyEvents()
    assert listener._token_for(SimpleNamespace(vk=0x63, char="3")) == "numpad_3"
    assert listener._token_for(SimpleNamespace(vk=0x6B, char="+")) == "add_key"


async def test_cancellation_stops_and_unregisters_the_event_listener(monkeypatch):
    from jarvis.appshot import key_events

    calls = []
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    class Listener:
        ready = True

        def register(self, rows):
            calls.append("register")
            assert rows[0][0] == "control + z"

        def start(self):
            calls.append("start")
            loop.call_soon_threadsafe(started.set)

        def stop(self):
            calls.append("stop")

        def unregister(self):
            calls.append("unregister")

    monkeypatch.setattr(key_events, "AppshotKeyEvents", Listener)
    owner = AppshotShortcut(object())
    task = asyncio.create_task(owner._run_key_events({"recording": "ctrl+z"}))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert calls == ["register", "start", "stop", "unregister"]


async def test_a_press_during_a_recording_toggle_runs_once_it_finishes():
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []
    owner = AppshotShortcut(object())

    async def take(scope: str) -> None:
        calls.append(scope)
        started.set()
        await release.wait()

    owner._take = take  # type: ignore[method-assign]
    owner._fire("recording")
    await asyncio.wait_for(started.wait(), 1)
    owner._fire("recording")
    assert calls == ["recording"]
    release.set()
    for _ in range(5):
        await asyncio.sleep(0)
        if len(calls) == 2:
            break
    assert calls == ["recording", "recording"]


async def test_missing_listener_is_reported_as_unarmed(monkeypatch):
    from jarvis.appshot import key_events

    class Listener:
        ready = False

        def register(self, rows):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def unregister(self):
            pass

    monkeypatch.setattr(key_events, "AppshotKeyEvents", Listener)
    owner = AppshotShortcut(object())
    await owner._run_key_events({"recording": "z"})
    assert not owner.status_for("recording").armed
    assert "could not start" in owner.status_for("recording").detail
