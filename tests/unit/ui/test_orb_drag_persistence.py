"""Unit tests for ui.orb.drag_persistence — vendored helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from ui.orb.drag_persistence import (
    DEFAULT_MARGIN_PX,
    DEFAULT_X_RELATIVE,
    DEFAULT_Y_RELATIVE,
    MascotPosition,
    ResolvedPlacement,
    _ScreenSnapshot,
    clamp_to_work_area,
    clear_position_in_toml,
    load_position_from_toml,
    load_saved_position,
    resolve_placement,
    restore_pet_origin,
    save_position_to_toml,
)


def _screen(name, *, x=0, y=0, w=1920, h=1080, primary=False):
    return _ScreenSnapshot(name=name, geometry=(x, y, w, h), is_primary=primary)


def test_mascot_position_is_frozen_dataclass():
    pos = MascotPosition(monitor="\\\\.\\DISPLAY1", x_relative=100, y_relative=50)
    assert pos.monitor == "\\\\.\\DISPLAY1"
    assert pos.x_relative == 100
    assert pos.y_relative == 50
    with pytest.raises(AttributeError):
        pos.x_relative = 200  # type: ignore[misc]


def test_clamp_inside_work_area_is_noop():
    x, y = clamp_to_work_area(500, 500, (0, 0, 1920, 1080), mascot_size_px=108)
    assert (x, y) == (500, 500)


def test_clamp_pulls_back_off_screen_right():
    x, y = clamp_to_work_area(1900, 500, (0, 0, 1920, 1080), mascot_size_px=108)
    # Max x = 0 + 1920 - 108 - 16 (margin) = 1796.
    assert x == 1796
    assert y == 500


def test_clamp_pulls_back_off_screen_top_left():
    x, y = clamp_to_work_area(-50, -10, (0, 0, 1920, 1080), mascot_size_px=108)
    assert (x, y) == (DEFAULT_MARGIN_PX, DEFAULT_MARGIN_PX)


def test_screen_snapshot_is_frozen():
    snap = _ScreenSnapshot(name="\\\\.\\DISPLAY1", geometry=(0, 0, 1920, 1080), is_primary=True)
    assert snap.name == "\\\\.\\DISPLAY1"
    assert snap.geometry == (0, 0, 1920, 1080)
    assert snap.is_primary is True


def test_resolved_placement_fields():
    rp = ResolvedPlacement(abs_x=10, abs_y=20, monitor="X", recovered=True)
    assert rp.abs_x == 10
    assert rp.abs_y == 20
    assert rp.monitor == "X"
    assert rp.recovered is True


def test_resolve_with_persisted_monitor_present_uses_it():
    screens = [_screen("\\\\.\\DISPLAY1", primary=True)]
    persisted = MascotPosition(monitor="\\\\.\\DISPLAY1", x_relative=300, y_relative=100)
    placement = resolve_placement(persisted, screens, mascot_size_px=108)
    assert placement.abs_x == 300
    assert placement.abs_y == 100
    assert placement.monitor == "\\\\.\\DISPLAY1"
    assert placement.recovered is False


def test_resolve_falls_back_to_primary_when_monitor_missing():
    screens = [_screen("\\\\.\\DISPLAY2", primary=True, x=100, y=200)]
    persisted = MascotPosition(monitor="\\\\.\\DISPLAY99", x_relative=500, y_relative=400)
    placement = resolve_placement(persisted, screens, mascot_size_px=108)
    assert placement.abs_x == 100 + DEFAULT_X_RELATIVE
    assert placement.abs_y == 200 + DEFAULT_Y_RELATIVE
    assert placement.recovered is True
    assert placement.monitor == "\\\\.\\DISPLAY2"


def test_resolve_with_no_persisted_uses_primary_default():
    screens = [_screen("\\\\.\\DISPLAY1", primary=True)]
    placement = resolve_placement(None, screens, mascot_size_px=108)
    assert placement.abs_x == DEFAULT_X_RELATIVE
    assert placement.abs_y == DEFAULT_Y_RELATIVE
    assert placement.recovered is True


def test_resolve_with_no_screens_returns_default():
    persisted = MascotPosition(monitor="X", x_relative=10, y_relative=20)
    placement = resolve_placement(persisted, [], mascot_size_px=108)
    assert placement.recovered is True
    assert placement.monitor == ""


def test_resolve_drops_pin_on_secondary_monitor_when_require_primary_true():
    """Defense (BUG-027): a persisted pin on a non-primary monitor is treated
    like a missing monitor — the orb falls back to the primary anchor. This
    prevents the orb from spawning invisibly after an accidental drag onto
    a secondary monitor the user is not currently looking at."""
    primary = _screen("\\\\.\\DISPLAY1", x=0, y=0, w=2560, h=1440, primary=True)
    secondary = _screen("\\\\.\\DISPLAY2", x=-3840, y=0, w=2560, h=1440)
    persisted = MascotPosition(
        monitor="\\\\.\\DISPLAY2", x_relative=2428, y_relative=1268,
    )
    placement = resolve_placement(
        persisted, [primary, secondary], mascot_size_px=108, require_primary=True,
    )
    assert placement.recovered is True
    assert placement.monitor == "\\\\.\\DISPLAY1"
    assert placement.abs_x == DEFAULT_X_RELATIVE
    assert placement.abs_y == DEFAULT_Y_RELATIVE


def test_resolve_honors_secondary_pin_when_require_primary_false():
    """Power-user escape hatch: passing require_primary=False keeps the orb
    on the secondary monitor pin even though it is not the primary."""
    primary = _screen("\\\\.\\DISPLAY1", x=0, y=0, w=2560, h=1440, primary=True)
    secondary = _screen("\\\\.\\DISPLAY2", x=-3840, y=0, w=2560, h=1440)
    persisted = MascotPosition(
        monitor="\\\\.\\DISPLAY2", x_relative=2428, y_relative=1268,
    )
    placement = resolve_placement(
        persisted, [primary, secondary], mascot_size_px=108, require_primary=False,
    )
    assert placement.recovered is False
    assert placement.monitor == "\\\\.\\DISPLAY2"
    assert placement.abs_x == -3840 + 2428  # -1412


def test_resolve_with_require_primary_still_honors_primary_pin():
    """The defense must not regress the happy path: a pin on the primary
    monitor must still be honoured regardless of require_primary."""
    primary = _screen("\\\\.\\DISPLAY1", x=0, y=0, w=2560, h=1440, primary=True)
    persisted = MascotPosition(
        monitor="\\\\.\\DISPLAY1", x_relative=2300, y_relative=1200,
    )
    placement = resolve_placement(
        persisted, [primary], mascot_size_px=108, require_primary=True,
    )
    assert placement.recovered is False
    assert placement.monitor == "\\\\.\\DISPLAY1"
    assert placement.abs_x == 2300
    assert placement.abs_y == 1200


def test_resolve_require_primary_defaults_to_true():
    """Explicit default contract: omitting require_primary uses the safe
    primary-only policy so callers default-defend against BUG-027."""
    primary = _screen("\\\\.\\DISPLAY1", x=0, y=0, w=2560, h=1440, primary=True)
    secondary = _screen("\\\\.\\DISPLAY2", x=-3840, y=0, w=2560, h=1440)
    persisted = MascotPosition(
        monitor="\\\\.\\DISPLAY2", x_relative=2428, y_relative=1268,
    )
    placement = resolve_placement(persisted, [primary, secondary], mascot_size_px=108)
    assert placement.recovered is True
    assert placement.monitor == "\\\\.\\DISPLAY1"


# ---------------------------------------------------------------------------
# TOML load / save / clear
# ---------------------------------------------------------------------------


def test_load_returns_none_when_file_missing(tmp_path: Path):
    assert load_position_from_toml(tmp_path / "nope.toml") is None


def test_load_returns_position_with_empty_monitor_when_section_missing(tmp_path: Path):
    p = tmp_path / "j.toml"
    p.write_text("[profile]\nname = 'x'\n", encoding="utf-8")
    pos = load_position_from_toml(p)
    assert pos is not None
    assert pos.monitor == ""


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "j.toml"
    pos = MascotPosition(monitor="\\\\.\\DISPLAY1", x_relative=1340, y_relative=720)
    save_position_to_toml(p, pos)
    loaded = load_position_from_toml(p)
    assert loaded == pos


def test_save_preserves_existing_other_sections_and_comments(tmp_path: Path):
    p = tmp_path / "j.toml"
    p.write_text(
        "# Top comment\n"
        "[profile]\n"
        "name = \"default\"  # inline comment\n"
        "\n"
        "[overlay]\n"
        "enabled = true\n",
        encoding="utf-8",
    )
    pos = MascotPosition(monitor="\\\\.\\DISPLAY1", x_relative=100, y_relative=50)
    save_position_to_toml(p, pos)
    text = p.read_text(encoding="utf-8")
    assert "# Top comment" in text
    assert "# inline comment" in text
    assert "[overlay]" in text
    assert "[overlay.mascot]" in text
    assert "position_monitor" in text


def test_clear_removes_three_keys_keeps_rest(tmp_path: Path):
    p = tmp_path / "j.toml"
    p.write_text(
        "[overlay]\n"
        "enabled = true\n"
        "\n"
        "[overlay.mascot]\n"
        'position_monitor = "\\\\.\\DISPLAY1"\n'
        "position_x_relative = 100\n"
        "position_y_relative = 50\n",
        encoding="utf-8",
    )
    clear_position_in_toml(p)
    text = p.read_text(encoding="utf-8")
    assert "position_monitor" not in text
    assert "position_x_relative" not in text
    assert "position_y_relative" not in text
    assert "[overlay]" in text
    assert "enabled = true" in text


def test_clear_is_noop_when_file_missing(tmp_path: Path):
    clear_position_in_toml(tmp_path / "absent.toml")  # must not raise


def test_a_drag_with_no_monitor_name_round_trips(tmp_path: Path):
    """macOS and Linux save a spot with an empty monitor name."""
    p = tmp_path / "j.toml"
    p.write_text("[ui]\npet_id = \"gigi\"\n", encoding="utf-8")
    save_position_to_toml(p, MascotPosition(monitor="", x_relative=640, y_relative=480))
    assert load_saved_position(p) == MascotPosition(monitor="", x_relative=640, y_relative=480)
    assert 'pet_id = "gigi"' in p.read_text(encoding="utf-8")


def test_an_undragged_file_is_not_a_saved_pet_spot(tmp_path: Path):
    p = tmp_path / "j.toml"
    p.write_text("[profile]\nname = 'x'\n", encoding="utf-8")
    assert load_saved_position(p) is None


def test_a_saved_spot_with_no_monitor_is_kept_and_clamped_on_screen():
    screen = (0, 0, 1920, 1080)
    home = restore_pet_origin(
        MascotPosition(monitor="", x_relative=400, y_relative=300),
        [],
        fallback_screen=screen,
        width=100,
        height=120,
    )
    assert home == (400, 300)
    off = restore_pet_origin(
        MascotPosition(monitor="", x_relative=9000, y_relative=-40),
        [],
        fallback_screen=screen,
        width=100,
        height=120,
    )
    assert off == (1920 - 100 - DEFAULT_MARGIN_PX, DEFAULT_MARGIN_PX)


def test_a_missing_monitor_is_clamped_onto_the_screen_that_remains():
    screens = [_screen("\\\\.\\DISPLAY1", primary=True, x=0, y=0, w=1920, h=1080)]
    home = restore_pet_origin(
        MascotPosition(monitor="\\\\.\\DISPLAY99", x_relative=400, y_relative=80),
        screens,
        fallback_screen=(0, 0, 800, 600),
        width=100,
        height=120,
    )
    assert home == (400, 80)
    # A monitor that is still plugged in keeps the pin, primary or not.
    assert (
        restore_pet_origin(
            MascotPosition(monitor="\\\\.\\DISPLAY1", x_relative=400, y_relative=80),
            screens,
            fallback_screen=(0, 0, 800, 600),
            width=100,
            height=120,
        )
        == (400, 80)
    )


def test_a_pin_on_a_connected_second_monitor_is_kept():
    screens = [
        _screen("\\\\.\\DISPLAY1", primary=True, x=0, y=0, w=1920, h=1080),
        _screen("\\\\.\\DISPLAY2", primary=False, x=1920, y=0, w=1920, h=1080),
    ]
    home = restore_pet_origin(
        MascotPosition(monitor="\\\\.\\DISPLAY2", x_relative=100, y_relative=200),
        screens,
        fallback_screen=(0, 0, 800, 600),
        width=100,
        height=120,
    )
    assert home == (1920 + 100, 200)


def test_a_drop_on_a_second_display_saves_that_display(monkeypatch):
    """Mouse-up must record the display under the drop, not the primary.

    The window origin can still be the spot from drag start, on the main
    display, while the pointer is on a second display. Clamping that point
    back onto the primary is the snap on release.
    """
    import ui.orb.drag_persistence as mod
    from ui.orb.drag_persistence import pin_at_drop, screens_from_tk

    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(
        mod,
        "_darwin_display_list",
        lambda: [
            ("PRIMARY", (0, 0, 1920, 1080), True),
            ("SECOND", (1920, 0, 1680, 1050), False),
        ],
    )
    screens = screens_from_tk(None)
    # Origin still on the primary. The pointer is on the second display.
    x, y, pos = pin_at_drop(
        400, 300, screens, width=120, height=140, pointer=(2500, 480)
    )
    assert pos.monitor == "SECOND"
    assert (x, y) == (2500 - 120 // 2, 480 - 140 // 2)
    assert pos.x_relative == x - 1920
    assert pos.y_relative == y
    # A pet that already followed the pointer stays on that spot.
    kept_x, kept_y, kept = pin_at_drop(
        2500, 420, screens, width=100, height=120, pointer=(2600, 500)
    )
    assert kept.monitor == "SECOND"
    assert (kept_x, kept_y) == (2500, 420)
    assert (kept.x_relative, kept.y_relative) == (2500 - 1920, 420)
    # A pointer sample that still reads as the primary must not pull it back.
    stay_x, stay_y, stay = pin_at_drop(
        2500, 420, screens, width=100, height=120, pointer=(100, 100)
    )
    assert stay.monitor == "SECOND"
    assert (stay_x, stay_y) == (2500, 420)


def test_a_drop_off_every_display_clamps_onto_one_that_exists():
    """A point on no connected display is pulled onto a screen that remains."""
    from ui.orb.drag_persistence import pin_at_drop

    primary = _screen("PRIMARY", primary=True, x=0, y=0, w=1920, h=1080)
    x, y, pos = pin_at_drop(
        9000, -40, [primary], width=100, height=120, pointer=(9000, -40)
    )
    assert pos.monitor == "PRIMARY"
    assert (x, y) == (1920 - 100 - DEFAULT_MARGIN_PX, DEFAULT_MARGIN_PX)
    assert (pos.x_relative, pos.y_relative) == (x, y)


# ---------------------------------------------------------------------------
# screens_from_tk (Win32 EnumDisplayMonitors)
# ---------------------------------------------------------------------------

import sys  # noqa: E402


def test_screens_from_tk_returns_at_least_one_screen_on_windows():
    if sys.platform != "win32":
        pytest.skip("EnumDisplayMonitors is Win32-only")
    from ui.orb.drag_persistence import screens_from_tk
    screens = screens_from_tk(root=None)  # we don't need a real Tk root
    assert len(screens) >= 1
    primary = [s for s in screens if s.is_primary]
    assert len(primary) == 1  # exactly one primary monitor


def test_screens_from_tk_returns_empty_on_non_windows(monkeypatch):
    import ui.orb.drag_persistence as mod
    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert mod.screens_from_tk(root=None) == []
