"""A modifier-only hold key fires only while held alone (2026-11-14).

With ``hotkey_dictate = "cmd"`` every Command shortcut (``cmd+c``,
``cmd+tab``, a Command-click) used to start a dictation on the Command
key-down: the microphone opened, the Dodaios Bar sprang into its level bars
and the empty take ended on a "nothing was heard" mark. It looked like the
wake word firing by itself. These tests pin the gate in front of such a key.
"""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.trigger.backends import solo_hold
from dodaios.trigger.backends.pynput import PynputBackend
from dodaios.trigger.backends.quartz import QuartzHotkeyBackend
from dodaios.trigger.backends.solo_hold import SoloHold, SoloHoldHooks
from dodaios.trigger.hotkey import HotkeyTrigger

_FLAG_SHIFT = 1 << 17
_FLAG_CMD = 1 << 20
_KC_C = 0x08
_KC_TAB = 0x30


class _ManualTimer:
    """``threading.Timer`` stand-in that fires only when the test says so."""

    created: list[_ManualTimer] = []

    def __init__(self, delay: float, fn: Any, args: tuple = ()) -> None:
        self.delay = delay
        self.fn = fn
        self.args = args
        self.cancelled = False
        self.started = False
        self.daemon = False
        _ManualTimer.created.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.fn(*self.args)


@pytest.fixture(autouse=True)
def _manual_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    _ManualTimer.created = []
    monkeypatch.setattr(solo_hold, "_timer_factory", _ManualTimer)


def _last_timer() -> _ManualTimer:
    assert _ManualTimer.created, "no press was scheduled"
    return _ManualTimer.created[-1]


def _gate(events: list[str]) -> SoloHold:
    return SoloHold(
        lambda: events.append("press"),
        lambda: events.append("release"),
        lambda: events.append("cancel"),
    )


# ---------------------------------------------------------------- the gate


def test_held_alone_fires_after_the_delay_then_releases() -> None:
    events: list[str] = []
    gate = _gate(events)
    gate.down(alone=True)
    assert events == []
    assert _last_timer().delay == solo_hold.SOLO_HOLD_S
    _last_timer().fire()
    gate.up()
    assert events == ["press", "release"]


def test_a_key_before_the_delay_makes_it_a_shortcut() -> None:
    events: list[str] = []
    gate = _gate(events)
    gate.down(alone=True)
    gate.spoil()
    _last_timer().fire()  # cancelled: must not fire
    gate.up()
    assert events == []


def test_a_key_after_the_press_cancels_and_the_release_stays_silent() -> None:
    events: list[str] = []
    gate = _gate(events)
    gate.down(alone=True)
    _last_timer().fire()
    gate.spoil()
    gate.up()
    assert events == ["press", "cancel"]


def test_a_quick_tap_fires_nothing() -> None:
    events: list[str] = []
    gate = _gate(events)
    gate.down(alone=True)
    gate.up()
    _last_timer().fire()  # a late timer of an ended hold
    assert events == []


def test_down_with_other_input_held_never_fires() -> None:
    events: list[str] = []
    gate = _gate(events)
    gate.down(alone=False)
    gate.up()
    assert events == []
    assert _ManualTimer.created == []


def test_a_stale_timer_cannot_fire_into_the_next_hold() -> None:
    events: list[str] = []
    gate = _gate(events)
    gate.down(alone=True)
    stale = _last_timer()
    gate.up()
    gate.down(alone=True)
    stale.cancelled = False  # even if the cancel lost the race
    stale.fire()
    assert events == []
    _last_timer().fire()
    assert events == ["press"]


# ------------------------------------------------- the early start (2026-11-14)
#
# Waiting the whole window before anything happened made the Dodaios Bar rise a
# noticeable moment after Command went down. With an ``on_early`` hook the
# recording starts at the key-down, and the window only decides whether it
# stays (``press`` confirms it) or is taken back without a trace (``abandon``).


def _early_gate(events: list[str]) -> SoloHold:
    return SoloHold(
        lambda: events.append("press"),
        lambda: events.append("release"),
        lambda: events.append("cancel"),
        on_early=lambda: events.append("early"),
        on_abandon=lambda: events.append("abandon"),
    )


def test_early_start_fires_at_the_key_down() -> None:
    events: list[str] = []
    gate = _early_gate(events)
    gate.down(alone=True)
    assert events == ["early"]
    _last_timer().fire()
    gate.up()
    assert events == ["early", "press", "release"]


def test_early_start_is_taken_back_by_a_shortcut_inside_the_window() -> None:
    events: list[str] = []
    gate = _early_gate(events)
    gate.down(alone=True)
    gate.spoil()  # the c of cmd+c
    _last_timer().fire()  # cancelled: must not confirm
    gate.up()
    assert events == ["early", "abandon"]


def test_early_start_is_taken_back_by_a_tap() -> None:
    events: list[str] = []
    gate = _early_gate(events)
    gate.down(alone=True)
    gate.up()
    _last_timer().fire()
    assert events == ["early", "abandon"]


def test_early_start_a_key_after_the_window_cancels_as_before() -> None:
    events: list[str] = []
    gate = _early_gate(events)
    gate.down(alone=True)
    _last_timer().fire()
    gate.spoil()  # cmd held a moment, then tab
    gate.up()
    assert events == ["early", "press", "cancel"]


def test_early_start_never_fires_with_other_input_held() -> None:
    events: list[str] = []
    gate = _early_gate(events)
    gate.down(alone=False)
    gate.spoil()
    gate.up()
    assert events == []


def test_early_start_a_listener_stop_takes_it_back() -> None:
    events: list[str] = []
    gate = _early_gate(events)
    gate.down(alone=True)
    gate.reset()
    _last_timer().fire()
    assert events == ["early", "abandon"]


def test_without_an_early_hook_reset_and_tap_stay_silent() -> None:
    events: list[str] = []
    gate = _gate(events)
    gate.down(alone=True)
    gate.reset()
    gate.down(alone=True)
    gate.up()
    assert events == []


# ---------------------------------------------------------------- Quartz


def _quartz(events: list[str]) -> QuartzHotkeyBackend:
    backend = QuartzHotkeyBackend()
    backend._permission_check = lambda: True
    backend.register([["window", lambda: events.append("press"), lambda: events.append("release")]])
    backend.set_solo_hold({"window": lambda: events.append("cancel")})
    return backend


def test_quartz_cmd_c_starts_no_dictation() -> None:
    events: list[str] = []
    backend = _quartz(events)
    backend._handle_flags(_FLAG_CMD)
    backend._handle_key_down(_KC_C)
    backend._handle_key_up(_KC_C)
    _last_timer().fire()
    backend._handle_flags(0)
    assert events == []


def test_quartz_cmd_held_alone_dictates() -> None:
    events: list[str] = []
    backend = _quartz(events)
    backend._handle_flags(_FLAG_CMD)
    _last_timer().fire()
    backend._handle_flags(0)
    assert events == ["press", "release"]


def test_quartz_cmd_tab_after_the_press_cancels() -> None:
    events: list[str] = []
    backend = _quartz(events)
    backend._handle_flags(_FLAG_CMD)
    _last_timer().fire()
    backend._handle_key_down(_KC_TAB)
    backend._handle_key_up(_KC_TAB)
    backend._handle_flags(0)
    assert events == ["press", "cancel"]


def test_quartz_a_second_modifier_makes_it_a_shortcut() -> None:
    events: list[str] = []
    backend = _quartz(events)
    backend._handle_flags(_FLAG_CMD)
    backend._handle_flags(_FLAG_CMD | _FLAG_SHIFT)  # cmd+shift+4 on its way
    _last_timer().fire()
    backend._handle_flags(0)
    assert events == []


def test_quartz_command_click_makes_it_a_shortcut() -> None:
    events: list[str] = []
    backend = _quartz(events)
    backend._handle_flags(_FLAG_CMD)
    backend._spoil_solo()  # what the tap does on a primary click
    _last_timer().fire()
    backend._handle_flags(0)
    assert events == []


def test_quartz_a_lost_letter_key_up_does_not_block_the_key() -> None:
    events: list[str] = []
    backend = _quartz(events)
    backend._held.add("c")  # its key-up never arrived
    backend._handle_flags(_FLAG_CMD)
    _last_timer().fire()
    assert events == ["press"]


def test_quartz_combos_with_a_plain_key_keep_firing_at_once() -> None:
    events: list[str] = []
    backend = QuartzHotkeyBackend()
    backend._permission_check = lambda: True
    backend.register([["window + d", lambda: events.append("press"), None]])
    backend.set_solo_hold({})
    backend._handle_flags(_FLAG_CMD)
    backend._handle_key_down(0x02)  # d
    assert events == ["press"]
    assert _ManualTimer.created == []


def _quartz_early(events: list[str]) -> QuartzHotkeyBackend:
    backend = QuartzHotkeyBackend()
    backend._permission_check = lambda: True
    backend.register([["window", lambda: events.append("press"), lambda: events.append("release")]])
    backend.set_solo_hold(
        {
            "window": SoloHoldHooks(
                cancel=lambda: events.append("cancel"),
                early=lambda: events.append("early"),
                abandon=lambda: events.append("abandon"),
            )
        }
    )
    return backend


def test_quartz_early_cmd_starts_at_the_key_down() -> None:
    events: list[str] = []
    backend = _quartz_early(events)
    backend._handle_flags(_FLAG_CMD)
    assert events == ["early"]
    _last_timer().fire()
    backend._handle_flags(0)
    assert events == ["early", "press", "release"]


def test_quartz_early_cmd_c_takes_the_start_back() -> None:
    events: list[str] = []
    backend = _quartz_early(events)
    backend._handle_flags(_FLAG_CMD)
    backend._handle_key_down(_KC_C)
    backend._handle_key_up(_KC_C)
    _last_timer().fire()
    backend._handle_flags(0)
    assert events == ["early", "abandon"]


def test_quartz_early_command_click_takes_the_start_back() -> None:
    events: list[str] = []
    backend = _quartz_early(events)
    backend._handle_flags(_FLAG_CMD)
    backend._spoil_solo()  # what the tap does on a primary click
    backend._handle_flags(0)
    assert events == ["early", "abandon"]


def test_quartz_stop_forgets_a_pending_hold() -> None:
    events: list[str] = []
    backend = _quartz(events)
    backend._handle_flags(_FLAG_CMD)
    backend.stop()
    _last_timer().fire()
    assert events == []


# ---------------------------------------------------------------- pynput


class _Key:
    def __init__(self, name: str | None = None, char: str | None = None) -> None:
        self.name = name
        self.char = char


def _pynput(events: list[str]) -> PynputBackend:
    backend = PynputBackend()
    backend.register([["window", lambda: events.append("press"), lambda: events.append("release")]])
    backend.set_solo_hold({"window": lambda: events.append("cancel")})
    return backend


def test_pynput_super_c_starts_nothing() -> None:
    events: list[str] = []
    backend = _pynput(events)
    backend._on_press_key(_Key(name="cmd"))
    backend._on_press_key(_Key(char="c"))
    backend._on_release_key(_Key(char="c"))
    _last_timer().fire()
    backend._on_release_key(_Key(name="cmd"))
    assert events == []


def test_pynput_right_super_held_alone_dictates() -> None:
    events: list[str] = []
    backend = _pynput(events)
    backend._on_press_key(_Key(name="cmd_r"))
    _last_timer().fire()
    backend._on_release_key(_Key(name="cmd_r"))
    assert events == ["press", "release"]


def test_pynput_key_after_the_press_cancels() -> None:
    events: list[str] = []
    backend = _pynput(events)
    backend._on_press_key(_Key(name="cmd"))
    _last_timer().fire()
    backend._on_press_key(_Key(name="tab"))
    backend._on_release_key(_Key(name="tab"))
    backend._on_release_key(_Key(name="cmd"))
    assert events == ["press", "cancel"]


# ---------------------------------------------------------------- the trigger


def test_trigger_gates_only_a_modifier_only_dictation_hold_key() -> None:
    trigger = HotkeyTrigger(
        {"dictate": ["cmd"], "ptt": ["right_alt"], "dictate_toggle": ["ctrl+alt"]},
        push_to_talk={"dictate", "ptt"},
    )
    assert set(trigger._solo_hold_cancels()) == {"window"}


def test_trigger_starts_the_solo_hold_key_early() -> None:
    """The gated key gets all three exits: early start, take-back, cancel."""
    trigger = HotkeyTrigger({"dictate": ["cmd"]}, push_to_talk={"dictate"})
    hooks = trigger._solo_hold_cancels()["window"]
    assert isinstance(hooks, SoloHoldHooks)
    assert callable(hooks.early) and callable(hooks.abandon) and callable(hooks.cancel)


def test_trigger_leaves_a_dictation_chord_with_a_plain_key_alone() -> None:
    trigger = HotkeyTrigger({"dictate": ["cmd+d"]}, push_to_talk={"dictate"})
    assert trigger._solo_hold_cancels() == {}


def test_trigger_leaves_a_toggle_mode_dictation_key_alone() -> None:
    trigger = HotkeyTrigger({"dictate": ["cmd"]}, push_to_talk=set())
    assert trigger._solo_hold_cancels() == {}


def test_trigger_arms_backends_that_can_gate_and_skips_others() -> None:
    trigger = HotkeyTrigger({"dictate": ["cmd"]}, push_to_talk={"dictate"})
    seen: list[dict] = []

    class _Gating:
        def set_solo_hold(self, cancels: dict) -> None:
            seen.append(cancels)

    trigger._arm_solo_hold(_Gating())  # type: ignore[arg-type]
    trigger._arm_solo_hold(object())  # type: ignore[arg-type]  # Windows poller
    assert len(seen) == 1 and set(seen[0]) == {"window"}
