"""The pet goes back to where it was dragged, and its strip behaves (docs/pets.md).

Three contracts, none of which needs a real window:

- a pinned pet opens on its own monitor, waits on the primary screen while
  that monitor is unplugged, and keeps the saved pin for when it returns;
- the control strip fades out through the window's opacity, and anything
  that wants it back makes it solid at once;
- a press keeps the strip up, and the release reads the pointer instead of
  trusting Enter and Leave events that a moving window never got.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import ui.orb.overlay as overlay_mod
from ui.orb import controls as orb_controls
from ui.orb.drag_persistence import MascotPosition, _ScreenSnapshot, load_pinned_position
from ui.orb.overlay import OrbOverlay, PetControlStrip, strip_fade_alpha

PRIMARY = _ScreenSnapshot(name="MAIN", geometry=(0, 0, 1920, 1080), is_primary=True)
SIDE = _ScreenSnapshot(name="SIDE", geometry=(1920, 0, 1920, 1080), is_primary=False)


def _pet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, screens: list) -> tuple[OrbOverlay, Path]:
    pet = OrbOverlay(style="pet")
    root = MagicMock()
    root.winfo_screenwidth.return_value = 1920
    root.winfo_screenheight.return_value = 1080
    pet._root = root
    pet._running = True
    pet._win_w, pet._win_h = 180, 180
    toml = tmp_path / "jarvis.toml"
    toml.write_text("[overlay]\nenabled = true\n", encoding="utf-8")
    monkeypatch.setattr(overlay_mod, "JARVIS_TOML_PATH", toml)
    monkeypatch.setattr(overlay_mod, "screens_from_tk", lambda _root: list(screens))
    monkeypatch.setattr(pet, "_reassert_topmost", lambda **_kw: None)
    return pet, toml


# --- the pet's home ----------------------------------------------------------


def test_a_pet_pinned_to_a_second_monitor_opens_there(tmp_path, monkeypatch) -> None:
    pet, _ = _pet(tmp_path, monkeypatch, [PRIMARY, SIDE])
    pin = MascotPosition(monitor="SIDE", x_relative=300, y_relative=200)
    assert pet._pet_home_xy(pin, [PRIMARY, SIDE]) == (1920 + 300, 200)
    assert pet._pet_displaced is False


def test_a_pet_whose_monitor_is_gone_waits_on_the_primary_screen(tmp_path, monkeypatch) -> None:
    pet, _ = _pet(tmp_path, monkeypatch, [PRIMARY])
    pin = MascotPosition(monitor="SIDE", x_relative=300, y_relative=200)
    assert pet._pet_home_xy(pin, [PRIMARY]) == (300, 200)
    assert pet._pet_displaced is True


def test_a_pinned_spot_is_pulled_back_inside_the_screen(tmp_path, monkeypatch) -> None:
    pet, _ = _pet(tmp_path, monkeypatch, [PRIMARY])
    pin = MascotPosition(monitor="MAIN", x_relative=5000, y_relative=5000)
    x, y = pet._pet_home_xy(pin, [PRIMARY])
    assert x + pet._win_w <= 1920
    assert y + pet._win_h + pet._pet_below_height() <= 1080


def test_an_unplugged_monitor_does_not_overwrite_the_saved_pin(tmp_path, monkeypatch) -> None:
    screens = [PRIMARY, SIDE]
    pet, toml = _pet(tmp_path, monkeypatch, screens)
    pet._manual_pinned = True
    pet._mascot_x, pet._mascot_y = 1920 + 300, 200
    pet._on_drag_press(SimpleNamespace(x_root=2230, y_root=210))
    pet._on_drag_motion(SimpleNamespace(x_root=2330, y_root=310))
    pet._on_drag_release(SimpleNamespace(x_root=2330, y_root=310))
    saved = load_pinned_position(toml)
    assert saved == MascotPosition(monitor="SIDE", x_relative=400, y_relative=300)

    screens.remove(SIDE)  # the second monitor is unplugged
    pet._schedule_position_recheck()
    assert pet._pet_displaced is True
    assert pet._mascot_x + pet._win_w <= 1920  # pulled onto the screen that is left
    assert load_pinned_position(toml) == saved

    screens.append(SIDE)  # and plugged back in
    pet._schedule_position_recheck()
    assert pet._pet_displaced is False
    assert (pet._mascot_x, pet._mascot_y) == (1920 + 400, 300)
    assert load_pinned_position(toml) == saved


def test_dragging_a_waiting_pet_gives_it_a_new_home(tmp_path, monkeypatch) -> None:
    pet, toml = _pet(tmp_path, monkeypatch, [PRIMARY])
    pet._pet_home = MascotPosition(monitor="SIDE", x_relative=300, y_relative=200)
    pet._pet_displaced = True
    pet._mascot_x, pet._mascot_y = 300, 200
    pet._on_drag_press(SimpleNamespace(x_root=310, y_root=210))
    pet._on_drag_motion(SimpleNamespace(x_root=710, y_root=410))
    pet._on_drag_release(SimpleNamespace(x_root=710, y_root=410))
    assert pet._pet_displaced is False
    assert pet._pet_home == MascotPosition(monitor="MAIN", x_relative=700, y_relative=400)
    assert load_pinned_position(toml) == pet._pet_home


def test_reset_position_forgets_the_home(tmp_path, monkeypatch) -> None:
    pet, toml = _pet(tmp_path, monkeypatch, [PRIMARY])
    pet._pet_home = MascotPosition(monitor="SIDE", x_relative=300, y_relative=200)
    pet._pet_displaced = True
    monkeypatch.setattr(
        pet, "_resolve_anchor", lambda _w, _h: SimpleNamespace(x=40, y=50, taskbar_aligned=True)
    )
    pet._on_reset_double_click()
    assert pet._pet_home is None and pet._pet_displaced is False
    assert load_pinned_position(toml) is None


# --- the strip keeps its size ----------------------------------------------------


def test_the_strip_does_not_grow_with_the_pet() -> None:
    pet = OrbOverlay(style="pet", pet_scale=2.0)
    pet._dpi_ratio = 1.5
    assert pet._pet_strip_scale() == 1.5
    small = OrbOverlay(style="pet", pet_scale=0.5)
    small._dpi_ratio = 1.5
    assert small._pet_below_height() == pet._pet_below_height()


# --- the strip fades out ---------------------------------------------------------


class _Top:
    """The strip's window: records opacity and withdraws, runs timers by hand."""

    def __init__(self) -> None:
        self.log: list[tuple] = []
        self.timers: dict[str, object] = {}
        self._n = 0

    def after(self, _ms: int, fn: object) -> str:
        self._n += 1
        self.timers[f"t{self._n}"] = fn
        return f"t{self._n}"

    def after_cancel(self, timer_id: str) -> None:
        self.timers.pop(timer_id, None)

    def fire(self) -> None:
        ((timer_id, fn),) = self.timers.items()
        del self.timers[timer_id]
        fn()  # type: ignore[operator]

    def wm_attributes(self, name: str, value: float) -> None:
        assert name == "-alpha"
        self.log.append(("alpha", round(value, 2)))

    def withdraw(self) -> None:
        self.log.append(("withdraw",))

    def deiconify(self) -> None:
        self.log.append(("deiconify",))

    def lift(self) -> None:
        pass

    def geometry(self, _spec: str) -> None:
        pass


def _strip(wanted: list[bool]) -> tuple[PetControlStrip, _Top]:
    strip = PetControlStrip.__new__(PetControlStrip)
    top = _Top()
    strip._top = top  # type: ignore[assignment]
    strip._canvas = None
    strip._scale = 1.0
    strip._state = orb_controls.PetStripState()
    strip._visible = True
    strip._pointer_inside = False
    strip._hide_after_id = None
    strip._mac_transparent = False
    strip._keep_visible = lambda: wanted[0]
    strip._orb_x, strip._orb_y, strip._orb_w, strip._orb_h = 100, 100, 180, 180
    strip._width, strip._height = orb_controls.pet_strip_size(1.0)
    return strip, top


def test_the_fade_runs_from_solid_to_gone() -> None:
    assert strip_fade_alpha(-1.0, 0.2) == 1.0
    assert strip_fade_alpha(0.0, 0.2) == 1.0
    assert strip_fade_alpha(0.1, 0.2) == pytest.approx(0.5)
    assert strip_fade_alpha(0.2, 0.2) == 0.0
    assert strip_fade_alpha(0.1, 0.0) == 0.0


def test_after_the_grace_the_strip_fades_then_hides(monkeypatch: pytest.MonkeyPatch) -> None:
    strip, top = _strip([False])
    now = [100.0]
    monkeypatch.setattr(overlay_mod.time, "monotonic", lambda: now[0])
    strip.hide_after_grace()
    top.fire()  # the grace is over: the fade begins, the strip is still up
    assert strip.visible is True
    now[0] += strip.FADE_MS / 2000
    top.fire()
    assert top.log[-1] == ("alpha", 0.5)
    now[0] += strip.FADE_MS / 1000
    top.fire()
    assert strip.visible is False
    # Solid again only after it left the screen, ready for the next show.
    assert top.log[-2:] == [("withdraw",), ("alpha", 1.0)]
    assert top.timers == {}


def test_a_strip_that_is_wanted_again_turns_solid_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    wanted = [False]
    strip, top = _strip(wanted)
    now = [100.0]
    monkeypatch.setattr(overlay_mod.time, "monotonic", lambda: now[0])
    strip.hide_after_grace()
    top.fire()
    now[0] += strip.FADE_MS / 2000
    top.fire()
    assert top.log[-1] == ("alpha", 0.5)
    strip.show()  # the pointer came back to the pet
    assert top.log[-1] == ("alpha", 1.0)
    assert strip.visible is True and top.timers == {}


def test_a_call_that_starts_mid_fade_keeps_the_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    wanted = [False]
    strip, top = _strip(wanted)
    now = [100.0]
    monkeypatch.setattr(overlay_mod.time, "monotonic", lambda: now[0])
    strip.hide_after_grace()
    top.fire()
    now[0] += strip.FADE_MS / 2000
    top.fire()
    wanted[0] = True
    top.fire()
    assert strip.visible is True
    assert top.log[-1] == ("alpha", 1.0)
    assert ("withdraw",) not in top.log


def test_a_wanted_strip_never_starts_to_fade() -> None:
    strip, top = _strip([True])
    strip.hide_after_grace()
    assert top.timers == {} and top.log == []


# --- a press keeps the strip, the release reads the pointer -------------------------


class _Row:
    """The strip as the overlay sees it, at a fixed place on screen."""

    def __init__(self, box: tuple[int, int, int, int]) -> None:
        self.box = box
        self.calls: list[str] = []
        self.pointer_inside = False

    def set_state(self, **_kwargs: object) -> None:
        pass

    def show(self) -> None:
        self.calls.append("show")

    def hide_after_grace(self) -> None:
        self.calls.append("grace")

    def update_anchor(self, _x: int, _y: int) -> None:
        pass

    def sync_pointer(self, x: int, y: int) -> bool:
        x0, y0, w, h = self.box
        self.pointer_inside = x0 <= x < x0 + w and y0 <= y < y0 + h
        return self.pointer_inside


def _pet_with_row(tmp_path, monkeypatch) -> tuple[OrbOverlay, _Row]:
    pet, _ = _pet(tmp_path, monkeypatch, [PRIMARY])
    pet._mascot_x, pet._mascot_y = 500, 500
    pet._mode = "idle"
    row = _Row((520, 690, 140, 40))
    pet._controls = row  # type: ignore[assignment]
    pet._window_mapped = lambda: True  # type: ignore[method-assign]
    return pet, row


def test_the_strip_stays_up_for_the_whole_press(tmp_path, monkeypatch) -> None:
    pet, row = _pet_with_row(tmp_path, monkeypatch)
    assert pet._pet_strip_wanted() is False
    pet._on_drag_press(SimpleNamespace(x_root=510, y_root=510))
    assert row.calls == ["show"]
    pet._on_orb_pointer_leave()  # the pointer outran the window mid-drag
    assert pet._pet_strip_wanted() is True


def test_dropping_the_pet_under_the_pointer_keeps_the_strip(tmp_path, monkeypatch) -> None:
    pet, row = _pet_with_row(tmp_path, monkeypatch)
    pet._on_drag_press(SimpleNamespace(x_root=510, y_root=510))
    pet._on_orb_pointer_leave()
    pet._on_drag_motion(SimpleNamespace(x_root=810, y_root=610))
    pet._root.winfo_pointerxy.return_value = (810, 610)  # still on the figure
    row.calls.clear()
    pet._on_drag_release(SimpleNamespace(x_root=810, y_root=610))
    assert pet._pointer_over_orb is True
    assert row.calls == ["show"]


def test_a_release_with_the_pointer_elsewhere_lets_the_strip_go(tmp_path, monkeypatch) -> None:
    pet, row = _pet_with_row(tmp_path, monkeypatch)
    pet._on_orb_pointer_enter()
    pet._on_drag_press(SimpleNamespace(x_root=510, y_root=510))
    pet._root.winfo_pointerxy.return_value = (50, 50)  # no Leave ever arrived
    row.calls.clear()
    pet._on_drag_release(SimpleNamespace(x_root=510, y_root=510))  # a click, not a drag
    assert pet._pointer_over_orb is False
    assert row.calls == ["grace"]


def test_a_hover_that_outlived_the_pointer_is_dropped(tmp_path, monkeypatch) -> None:
    pet, row = _pet_with_row(tmp_path, monkeypatch)
    pet._on_orb_pointer_enter()
    pet._root.winfo_pointerxy.return_value = (50, 50)
    row.calls.clear()
    pet._reconcile_pet_hover()
    assert pet._pointer_over_orb is False
    assert row.calls == ["grace"]


def test_a_real_hover_is_left_alone(tmp_path, monkeypatch) -> None:
    pet, row = _pet_with_row(tmp_path, monkeypatch)
    pet._on_orb_pointer_enter()
    pet._root.winfo_pointerxy.return_value = (560, 560)
    row.calls.clear()
    pet._reconcile_pet_hover()
    assert pet._pointer_over_orb is True
    assert row.calls == []


def test_the_real_strip_knows_where_it_is() -> None:
    strip, _top = _strip([False])
    width, height = strip._width, strip._height
    left = 100 + 180 // 2 - width // 2
    top_y = strip._row_y()
    assert strip.sync_pointer(left + 1, top_y + 1) is True
    assert strip.pointer_inside is True
    assert strip.sync_pointer(left + width, top_y + 1) is False
    assert strip.sync_pointer(left + 1, top_y + height) is False
    strip._visible = False
    assert strip.contains(left + 1, top_y + 1) is False
