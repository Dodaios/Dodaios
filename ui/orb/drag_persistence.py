"""Drag-and-pin persistence helpers for the Tk Jarvis orb.

These are vendored from OS-Level/src/overlay/mascot_position.py to avoid
cross-package sys.path manipulation at runtime. The dormant PySide6
overlay keeps its own copy. If both ever need to diverge, that's fine;
if they ever need to converge, factor into a shared utility package.

Public surface:
  - MascotPosition (frozen dataclass)
  - clamp_to_work_area(x, y, monitor_geo, mascot_size_px) -> (x, y)
  - resolve_placement(persisted, screens, mascot_size_px) -> ResolvedPlacement
  - load_position_from_toml(path) -> MascotPosition | None
  - save_position_to_toml(path, pos) -> None
  - clear_position_in_toml(path) -> None
  - pin_at_drop(x, y, screens, *, width, height, pointer=None) -> (x, y, pos)
  - screens_from_tk(root) -> list[_ScreenSnapshot]   (Win32, or Quartz on macOS)
  - DEFAULT_MARGIN_PX, DEFAULT_X_RELATIVE, DEFAULT_Y_RELATIVE
"""
from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


DEFAULT_X_RELATIVE: int = 200
DEFAULT_Y_RELATIVE: int = 80
DEFAULT_MARGIN_PX: int = 16


@dataclass(frozen=True)
class MascotPosition:
    """Persisted orb position. ``monitor`` is the Win32 device name."""

    monitor: str
    x_relative: int
    y_relative: int


@dataclass(frozen=True)
class _ScreenSnapshot:
    """Platform-free monitor description for resolve_placement()."""

    name: str  # Win32 device name on Windows; symbolic id elsewhere
    geometry: tuple[int, int, int, int]  # (x, y, w, h) work-area in logical px
    is_primary: bool


@dataclass(frozen=True)
class ResolvedPlacement:
    """Result of resolve_placement() — where the orb actually goes."""

    abs_x: int
    abs_y: int
    monitor: str
    recovered: bool  # True if primary-fallback was used


def clamp_to_work_area(
    abs_x: int,
    abs_y: int,
    monitor_geometry: tuple[int, int, int, int],
    *,
    mascot_size_px: int = 108,
    margin_px: int = DEFAULT_MARGIN_PX,
) -> tuple[int, int]:
    """Keep the orb fully inside the work area minus a safety margin."""
    sx, sy, sw, sh = monitor_geometry
    min_x = sx + margin_px
    min_y = sy + margin_px
    max_x = sx + sw - mascot_size_px - margin_px
    max_y = sy + sh - mascot_size_px - margin_px
    return (max(min_x, min(abs_x, max_x)), max(min_y, min(abs_y, max_y)))


def clamp_window_origin(
    x: int,
    y: int,
    screen: tuple[int, int, int, int],
    *,
    width: int,
    height: int,
    margin_px: int = DEFAULT_MARGIN_PX,
) -> tuple[int, int]:
    """Pull a window's top-left onto ``screen``.

    A window bigger than the screen stays at the margin.
    """
    sx, sy, sw, sh = screen
    wide = max(1, int(width))
    tall = max(1, int(height))
    min_x = sx + margin_px
    min_y = sy + margin_px
    max_x = sx + sw - wide - margin_px
    max_y = sy + sh - tall - margin_px
    if max_x < min_x:
        max_x = min_x
    if max_y < min_y:
        max_y = min_y
    return (max(min_x, min(int(x), max_x)), max(min_y, min(int(y), max_y)))


def _assert_visibility_contract(
    placement: ResolvedPlacement,
    screens: Sequence[_ScreenSnapshot],
    require_primary: bool,
) -> ResolvedPlacement:
    """Post-condition gate (BUG-027 / ADR-0016 visible-feedback contract).

    When ``require_primary`` is set AND the caller has at least one screen,
    the returned monitor MUST be the ``is_primary=True`` screen. Any other
    outcome is a logic regression inside :func:`resolve_placement` itself
    and is caught at the source instead of producing an invisible orb at
    runtime. The escape-hatch (``require_primary=False``) skips the check.
    """
    if not require_primary or not screens or not placement.monitor:
        return placement
    by_name = {s.name: s for s in screens}
    screen = by_name.get(placement.monitor)
    assert screen is not None and screen.is_primary, (
        f"resolve_placement contract violated: returned monitor "
        f"{placement.monitor!r} is not primary (require_primary=True). "
        f"Candidates: {[s.name + '(primary)' if s.is_primary else s.name for s in screens]}"
    )
    return placement


def resolve_placement(
    persisted: MascotPosition | None,
    screens: Sequence[_ScreenSnapshot],
    *,
    mascot_size_px: int = 108,
    require_primary: bool = True,
) -> ResolvedPlacement:
    """Resolve where to place the orb on boot, with multi-step recovery.

    Inputs:
      - ``persisted``: position saved during a previous session (or None).
      - ``screens``: current monitor layout from EnumDisplayMonitors.
      - ``require_primary`` (BUG-027 defense): when True (the safe default),
        a persisted pin on a non-primary monitor is treated like a missing
        monitor and the orb falls back to the primary anchor. This prevents
        the orb from spawning invisibly on a secondary screen the user is
        not currently looking at. Power users can override this by passing
        False via ``[overlay.mascot] allow_secondary_monitor_pin = true``
        in jarvis.toml.

    Returns ``ResolvedPlacement``. ``recovered=True`` means the persisted
    pin was discarded for any of the recovery reasons (missing monitor,
    no screens, or — when ``require_primary`` is set — non-primary pin).
    Callers are expected to ``clear_position_in_toml`` when ``recovered``
    is True so the next boot starts clean.

    Post-condition (ADR-0016): when ``require_primary`` is True AND
    ``screens`` is non-empty, the returned monitor is guaranteed to be
    primary. Violation raises ``AssertionError`` — that is a logic bug
    inside this function, not a recoverable runtime state.
    """
    if not screens:
        return _assert_visibility_contract(
            ResolvedPlacement(
                abs_x=DEFAULT_X_RELATIVE,
                abs_y=DEFAULT_Y_RELATIVE,
                monitor="",
                recovered=True,
            ),
            screens,
            require_primary,
        )

    by_name = {s.name: s for s in screens}

    if persisted is not None and persisted.monitor in by_name:
        screen = by_name[persisted.monitor]
        if require_primary and not screen.is_primary:
            # BUG-027 defense: skip the persisted pin, fall through to the
            # primary-default branch below.
            logger.info(
                "resolve_placement: pin on non-primary monitor %r dropped "
                "(require_primary=True); falling back to primary anchor",
                screen.name,
            )
        else:
            sx, sy, sw, sh = screen.geometry
            max_rel_x = max(0, sw - mascot_size_px - DEFAULT_MARGIN_PX)
            max_rel_y = max(0, sh - mascot_size_px - DEFAULT_MARGIN_PX)
            rel_x = max(DEFAULT_MARGIN_PX, min(persisted.x_relative, max_rel_x))
            rel_y = max(DEFAULT_MARGIN_PX, min(persisted.y_relative, max_rel_y))
            return _assert_visibility_contract(
                ResolvedPlacement(
                    abs_x=sx + rel_x,
                    abs_y=sy + rel_y,
                    monitor=screen.name,
                    recovered=False,
                ),
                screens,
                require_primary,
            )

    primary = next((s for s in screens if s.is_primary), screens[0])
    sx, sy, _sw, _sh = primary.geometry
    return _assert_visibility_contract(
        ResolvedPlacement(
            abs_x=sx + DEFAULT_X_RELATIVE,
            abs_y=sy + DEFAULT_Y_RELATIVE,
            monitor=primary.name,
            recovered=True,
        ),
        screens,
        require_primary,
    )


def restore_pet_origin(
    persisted: MascotPosition,
    screens: Sequence[_ScreenSnapshot],
    *,
    fallback_screen: tuple[int, int, int, int],
    width: int,
    height: int,
) -> tuple[int, int] | None:
    """Where a saved pet spot opens.

    A named monitor that is still connected keeps the spot, including a
    second display. A missing monitor, or a spot with no monitor name, is
    pulled onto a screen that exists. The caller must not delete that spot.
    """
    named = None
    if persisted.monitor:
        named = next((s for s in screens if s.name == persisted.monitor), None)
    if named is not None:
        raw_x = named.geometry[0] + persisted.x_relative
        raw_y = named.geometry[1] + persisted.y_relative
        return clamp_window_origin(
            raw_x, raw_y, named.geometry, width=width, height=height
        )
    if persisted.monitor and screens:
        home = next((s for s in screens if s.is_primary), screens[0])
        raw_x = home.geometry[0] + persisted.x_relative
        raw_y = home.geometry[1] + persisted.y_relative
        area = home.geometry
    else:
        raw_x = persisted.x_relative
        raw_y = persisted.y_relative
        area = fallback_screen
    return clamp_window_origin(raw_x, raw_y, area, width=width, height=height)


def _screen_at(
    screens: Sequence[_ScreenSnapshot], x: int, y: int
) -> _ScreenSnapshot | None:
    """The screen whose geometry contains ``(x, y)``, if any."""
    for screen in screens:
        sx, sy, sw, sh = screen.geometry
        if sx <= x < sx + sw and sy <= y < sy + sh:
            return screen
    return None


def _drop_screen(
    pointer_hit: _ScreenSnapshot | None,
    center_hit: _ScreenSnapshot | None,
    screens: Sequence[_ScreenSnapshot],
) -> _ScreenSnapshot | None:
    """Which screen a mouse-up belongs on.

    The pointer wins. A pointer that still reads as the primary while the
    pet's center is already on another display does not — that reading is
    what pulled a second-monitor drop back onto the main screen. A point on
    no connected display falls through to a screen that exists.
    """
    if pointer_hit is not None and center_hit is not None:
        if pointer_hit.is_primary and not center_hit.is_primary:
            return center_hit
        return pointer_hit
    if pointer_hit is not None:
        return pointer_hit
    if center_hit is not None:
        return center_hit
    if not screens:
        return None
    return next((screen for screen in screens if screen.is_primary), screens[0])


def pin_at_drop(
    x: int,
    y: int,
    screens: Sequence[_ScreenSnapshot],
    *,
    width: int,
    height: int,
    pointer: tuple[int, int] | None = None,
) -> tuple[int, int, MascotPosition]:
    """Where a drag should stay when the button comes up.

    Returns the clamped window origin and the relative pin to save. The
    display is the one under ``pointer`` (or under the window center when
    the pointer is missing). A window whose origin is still on the primary,
    from drag start, is moved so its center sits on the pointer's display.
    A point on no connected display is clamped onto a screen that exists.
    With no screens at all the origin is kept and the monitor name is empty.
    """
    wide = max(1, int(width))
    tall = max(1, int(height))
    origin_x, origin_y = int(x), int(y)
    center = (origin_x + wide // 2, origin_y + tall // 2)
    pointer_hit = (
        _screen_at(screens, int(pointer[0]), int(pointer[1]))
        if pointer is not None
        else None
    )
    center_hit = _screen_at(screens, center[0], center[1])
    screen = _drop_screen(pointer_hit, center_hit, screens)
    if screen is None:
        return (
            origin_x,
            origin_y,
            MascotPosition(monitor="", x_relative=origin_x, y_relative=origin_y),
        )
    if pointer is not None and pointer_hit is screen and center_hit is not screen:
        origin_x = int(pointer[0]) - wide // 2
        origin_y = int(pointer[1]) - tall // 2
    clamped_x, clamped_y = clamp_window_origin(
        origin_x, origin_y, screen.geometry, width=wide, height=tall
    )
    sx, sy, _sw, _sh = screen.geometry
    return (
        clamped_x,
        clamped_y,
        MascotPosition(
            monitor=screen.name,
            x_relative=clamped_x - sx,
            y_relative=clamped_y - sy,
        ),
    )


# ---------------------------------------------------------------------------
# TOML load / save / clear — atomic, comment-preserving.
# ---------------------------------------------------------------------------


def load_position_from_toml(path: Path) -> MascotPosition | None:
    """Read [overlay.mascot] from jarvis.toml. None if file is missing."""
    if not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning("load_position_from_toml: %s", exc)
        return None
    overlay = data.get("overlay") or {}
    section = overlay.get("mascot") or {}
    monitor = section.get("position_monitor", "")
    if not isinstance(monitor, str):
        monitor = ""
    x_rel = int(section.get("position_x_relative", DEFAULT_X_RELATIVE))
    y_rel = int(section.get("position_y_relative", DEFAULT_Y_RELATIVE))
    return MascotPosition(monitor=monitor, x_relative=x_rel, y_relative=y_rel)


def load_saved_position(path: Path) -> MascotPosition | None:
    """A spot a drag wrote. None when the file has no position keys.

    ``load_position_from_toml`` fills defaults when the keys are absent, so a
    file that was never dragged looks like a pin. An empty monitor name is a
    real pin: macOS and Linux have no Win32 device name.
    """
    if not path.is_file():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        logger.warning("load_saved_position: %s", exc)
        return None
    section = (data.get("overlay") or {}).get("mascot") or {}
    if "position_x_relative" not in section or "position_y_relative" not in section:
        return None
    try:
        x_rel = int(section["position_x_relative"])
        y_rel = int(section["position_y_relative"])
    except (TypeError, ValueError):
        return None
    monitor = section.get("position_monitor", "")
    if not isinstance(monitor, str):
        monitor = ""
    return MascotPosition(monitor=monitor, x_relative=x_rel, y_relative=y_rel)


def load_allow_secondary_monitor_pin(path: Path) -> bool:
    """Read [overlay.mascot] allow_secondary_monitor_pin (default False).

    BUG-027 power-user escape hatch. When True the orb honours a persisted
    pin even on a non-primary monitor. When False (the safe default) the
    orb falls back to the primary anchor on boot, so an accidental drag
    onto a secondary screen does not leave the orb invisible.
    """
    if not path.is_file():
        return False
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return False
    overlay = data.get("overlay") or {}
    section = overlay.get("mascot") or {}
    return bool(section.get("allow_secondary_monitor_pin", False))


def save_position_to_toml(path: Path, position: MascotPosition) -> None:
    """Atomic write of the three position fields. Comment-preserving."""
    if not path.is_file():
        new_text = (
            "[overlay.mascot]\n"
            f'position_monitor = "{_escape_toml_str(position.monitor)}"\n'
            f"position_x_relative = {position.x_relative}\n"
            f"position_y_relative = {position.y_relative}\n"
        )
        _atomic_write_text(path, new_text)
        return

    text = path.read_text(encoding="utf-8")
    section_re = re.compile(r"^\[overlay\.mascot\]\s*$", re.MULTILINE)
    if not section_re.search(text):
        if not text.endswith("\n"):
            text += "\n"
        text += (
            "\n[overlay.mascot]\n"
            f'position_monitor = "{_escape_toml_str(position.monitor)}"\n'
            f"position_x_relative = {position.x_relative}\n"
            f"position_y_relative = {position.y_relative}\n"
        )
        _atomic_write_text(path, text)
        return

    text = _replace_or_append_field(
        text, section_header="[overlay.mascot]",
        field="position_monitor",
        value=f'"{_escape_toml_str(position.monitor)}"',
    )
    text = _replace_or_append_field(
        text, section_header="[overlay.mascot]",
        field="position_x_relative", value=str(position.x_relative),
    )
    text = _replace_or_append_field(
        text, section_header="[overlay.mascot]",
        field="position_y_relative", value=str(position.y_relative),
    )
    _atomic_write_text(path, text)


def clear_position_in_toml(path: Path) -> None:
    """Remove the three position_* keys from [overlay.mascot]. No-op if file missing."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    section_re = re.compile(r"^\[overlay\.mascot\]\s*$", re.MULTILINE)
    if not section_re.search(text):
        return

    region_re = re.compile(
        r"(^\[overlay\.mascot\]\s*\n)(.*?)(?=^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = region_re.search(text)
    if m is None:
        return
    region_body = m.group(2)
    for field in ("position_monitor", "position_x_relative", "position_y_relative"):
        region_body = re.sub(
            rf"^\s*{re.escape(field)}\s*=.*?\n",
            "",
            region_body,
            flags=re.MULTILINE,
        )
    new_text = text[: m.start(2)] + region_body + text[m.end(2) :]
    _atomic_write_text(path, new_text)


def _atomic_write_text(path: Path, text: str) -> None:
    """tempfile + os.replace() — atomic on Win32."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _escape_toml_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _replace_or_append_field(
    text: str, *, section_header: str, field: str, value: str
) -> str:
    section_pattern = re.escape(section_header)
    region_re = re.compile(
        rf"(^{section_pattern}\s*\n)(.*?)(?=^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    region_m = region_re.search(text)
    if region_m is None:
        return text

    region_text = region_m.group(2)
    field_re = re.compile(
        rf"^(?P<lead>\s*){re.escape(field)}\s*=.*?$",
        re.MULTILINE,
    )
    if field_re.search(region_text):
        new_region = field_re.sub(
            lambda m: f"{m.group('lead')}{field} = {value}",
            region_text,
            count=1,
        )
    else:
        new_region = f"{field} = {value}\n" + region_text

    return text[: region_m.start(2)] + new_region + text[region_m.end(2) :]


# ---------------------------------------------------------------------------
# screens_from_tk — Win32 EnumDisplayMonitors, Quartz on macOS.
# ---------------------------------------------------------------------------


def _darwin_display_list() -> list[tuple[str, tuple[int, int, int, int], bool]]:
    """Active macOS displays as ``(name, geometry, is_primary)``.

    Names are Quartz display ids, so a pin can find the same screen next
    launch. Geometry is global points with the origin at the top-left of the
    main display — the same space as the Tk pointer. Empty when Quartz is
    missing or the machine has no display.
    """
    try:
        from Quartz import (  # noqa: PLC0415
            CGDisplayBounds,
            CGGetActiveDisplayList,
            CGMainDisplayID,
        )
    except Exception:  # noqa: BLE001 — pyobjc not installed
        return []
    try:
        err, display_ids, count = CGGetActiveDisplayList(16, None, None)
        main_id = int(CGMainDisplayID())
    except Exception:  # noqa: BLE001 — headless, or the display server is gone
        return []
    if err or not display_ids or not count:
        return []
    found: list[tuple[str, tuple[int, int, int, int], bool]] = []
    for display in list(display_ids)[:count]:
        left = top = width = height = 0
        try:
            rect = CGDisplayBounds(display)
            left, top = int(rect.origin.x), int(rect.origin.y)
            width, height = int(rect.size.width), int(rect.size.height)
        except Exception:  # noqa: BLE001 — one bad display must not hide the rest
            logger.debug("display bounds unavailable", exc_info=True)
        if width <= 0 or height <= 0:
            continue
        found.append((str(int(display)), (left, top, width, height), int(display) == main_id))
    if found and not any(primary for _name, _geo, primary in found):
        name, geometry, _primary = found[0]
        found[0] = (name, geometry, True)
    return found


def screens_from_tk(root) -> list[_ScreenSnapshot]:
    """Monitors the pet can be pinned to.

    Windows uses EnumDisplayMonitors device names. macOS uses Quartz display
    ids: Tk has no monitor list there, and an empty list made mouse-up clamp
    every drop onto the primary screen. Other platforms return an empty list
    and the caller keeps the point.

    The ``root`` parameter is accepted for API symmetry with the Qt sibling
    but is unused — both platforms are read from the OS, not from Tk.
    """
    _ = root
    if sys.platform == "darwin":
        return [
            _ScreenSnapshot(name=name, geometry=geometry, is_primary=primary)
            for name, geometry, primary in _darwin_display_list()
        ]
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except (ImportError, OSError):
        return []

    user32 = ctypes.windll.user32

    class _MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    MONITORINFOF_PRIMARY = 0x00000001
    out: list[_ScreenSnapshot] = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _enum_proc(hmonitor, _hdc, _rect, _lparam):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            return 1
        rc = info.rcWork
        out.append(
            _ScreenSnapshot(
                name=info.szDevice,
                geometry=(rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top),
                is_primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
            )
        )
        return 1

    user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_enum_proc), 0)
    return out


__all__ = [
    "DEFAULT_MARGIN_PX",
    "DEFAULT_X_RELATIVE",
    "DEFAULT_Y_RELATIVE",
    "MascotPosition",
    "ResolvedPlacement",
    "_ScreenSnapshot",
    "clamp_to_work_area",
    "clamp_window_origin",
    "clear_position_in_toml",
    "load_allow_secondary_monitor_pin",
    "load_position_from_toml",
    "load_saved_position",
    "pin_at_drop",
    "resolve_placement",
    "restore_pet_origin",
    "save_position_to_toml",
    "screens_from_tk",
]
