"""The voice orb as a native desktop overlay (Tkinter + Pillow + numpy).

History of approaches tried and why we landed on Tkinter:
    - pywebview + WebView2 Canvas: WebView2 renders via DirectComposition,
      so SetWindowRgn/LWA_COLORKEY have no effect → a rectangular box remained.
    - PySide6 + WA_TranslucentBackground: Qt6+DWM on Windows 11 frequently
      delivers only an opaque black backing buffer + a DropShadow frame
      instead of real transparency. Dozens of known Qt bugs, no robust fix.
    - Tkinter + wm_attributes('-transparentcolor'): uses the classic
      Win32 SetLayeredWindowAttributes API with LWA_COLORKEY. Stable since
      Windows 2000, independent of DWM compositor quirks. Magenta (#FF00FF)
      becomes pixel-perfect transparent — Windows routes those pixels
      straight through to the desktop.

Rendering pipeline:
    :class:`ui.orb.voice_orb.VoiceOrbRenderer` computes one RGB frame per tick
    with the magenta colour key around the sphere. Windows keys it out; macOS
    gets an RGBA frame (:func:`key_to_alpha`) shown through a native layer
    (``ui/orb/mac_layer.py``).

The window used to wear the mascot and the desktop pet as well. Pets live in
the app only now (``docs/pets.md``), so the voice orb is the one look left.

Public API:
    overlay = OrbOverlay()                  # the procedural voice orb
    overlay.start()                         # blocks until mainloop exit
    overlay.show(mode="listen")             # voice modes: idle/listen/speak/think
    overlay.show(mode="dictate")            # dictation modes: recording ...
    overlay.show(mode="dictate_transcribing")  # ... and transcribing
    overlay.hide()
    overlay.set_level(0.42)

Standalone test:
    python -m ui.orb.overlay                # demo sequence
    python -m ui.orb.overlay --sticky       # permanently visible (preview)
    python -m ui.orb.overlay --mic          # sticky + mic-reactive
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageTk

from dodaios.core.config import DEFAULT_CONFIG_FILE as JARVIS_TOML_PATH
from dodaios.core.win32_dpi import ensure_dpi_awareness as _ensure_dpi_awareness
from dodaios.ui.dodaiosbar.modes import ACTIVE_VOICE_MODES, MODES
from dodaios.ui.overlay_styles import LEGACY_STYLE_ALIASES, ORB_STYLES
from ui.orb import controls as orb_controls
from ui.orb.drag_persistence import (
    MascotPosition,
    clamp_to_work_area,
    clear_position_in_toml,
    load_allow_secondary_monitor_pin,
    load_position_from_toml,
    resolve_placement,
    save_position_to_toml,
    screens_from_tk,
)
from ui.orb.mac_layer import MacLayerPresenter
from ui.orb.taskbar import (
    MascotAnchor,
    compute_mascot_position,
    get_taskbar_info,
    get_tray_notify_rect,
)
from ui.orb.voice_orb import VoiceOrbRenderer

#: The look this window wears (ONE definition, in dodaios.ui.overlay_styles):
#: ``voice_orb``, the procedural weather sphere — the desktop twin of the
#: in-app orb. Always on top and draggable to any monitor.
DEFAULT_ORB_STYLE = "voice_orb"


@dataclass
class _DragState:
    """In-flight drag tracking. ``moved`` flips True once the threshold is crossed."""

    start_root_x: int
    start_root_y: int
    offset_x: int  # event.x_root - window x at press time
    offset_y: int
    moved: bool = False



#: The voice orb's window. The sphere rests at 70 % of the window (162 px —
#: the 50 % larger sphere the maintainer asked for on 2026-08-06), and the
#: margin that leaves is where the aura lives. The corona and its outgoing
#: waves have to be drawn INSIDE this window like everything else, so the
#: window has to be bigger than the thing it draws.
VOICE_ORB_WIN_W = 216
VOICE_ORB_WIN_H = 216


def window_size_for_style(style: str) -> tuple[int, int]:
    """Window size for one orb style (the voice orb is the only one left)."""
    return VOICE_ORB_WIN_W, VOICE_ORB_WIN_H


MARGIN_RIGHT = 24
MARGIN_TOP = 28

# Anchor margins fed to ui.orb.taskbar.compute_mascot_position so the orb
# stands on the real Windows taskbar top edge (Shell_TrayWnd, read live).
TRAY_SAFE_MARGIN_PX = 14
RIGHT_EDGE_MARGIN_PX = 24
TASKBAR_OVERLAP_PX = 1
AUTOHIDE_BOTTOM_MARGIN_PX = 16
POSITION_RECHECK_MS = 1500

# Drag-and-pin threshold (manhattan distance, px). Below this we treat
# the gesture as a click (no movement, no persistence). Raised from 5 to
# 16 on 2026-05-18 (BUG-027): an over-eager 5 px threshold meant a casual
# mouse twitch during a double-click could commit a pin, which silently
# moved the orb onto a secondary monitor where the user could not see it.
DRAG_THRESHOLD_PX = 16

# Mute gesture window (ms). After one ``<Double-Button-1>`` event we wait
# this long for a second double-click; only then does the mute toggle
# actually fire. The 2026-05-17 single-double-click implementation
# muted Jarvis whenever the user clicked the freshly popped-up orb,
# silently locking the wake-loop. Two double-clicks (four clicks total)
# in under 600 ms is intentional, easy to perform when wanted, and
# practically impossible to trigger by accident on an aware-popup hit.
MUTE_GESTURE_WINDOW_MS = 600



COLOR_KEY_HEX = "#FF00FF"
COLOR_KEY_RGB = np.array([255, 0, 255], dtype=np.uint8)


def key_to_alpha(img: Image.Image) -> Image.Image:
    """RGB frame → RGBA with the magenta color key mapped to full transparency.

    Windows keys the magenta out natively (layered-window color key); macOS
    has no color-key concept, so the Tk surface there shows RGBA frames on a
    ``-transparent`` root instead. Exact-match keying mirrors the Windows
    contract: only pure ``COLOR_KEY_RGB`` pixels vanish.
    """
    arr = np.asarray(img, dtype=np.uint8)
    alpha = np.where((arr == COLOR_KEY_RGB).all(axis=-1), 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack((arr, alpha)), "RGBA")


# Warn-once latch: the clear-backing pass runs on every reveal, but a missing
# pyobjc should produce ONE actionable warning, not a log storm.
_WARNED_NO_APPKIT = False


def apply_macos_clear_backing() -> None:
    """Make every NSWindow of THIS process paint a clear backing (BUG-075).

    Tk 8.6 aqua turned the ``systemTransparent`` background into true
    per-pixel transparency; Tk 9 (bundled by uv's python-build-standalone)
    paints it as an opaque appearance color instead — the surface showed a
    solid grey box around its artwork. A non-opaque window backing with a
    clear background is the native, Tk-version-independent equivalent.
    Runs only inside the overlay host process, whose every window wants a
    clear backing. Safe post-BUG-067: Tk owns ``NSApp`` before any window
    exists here. Best-effort, never raises.
    """
    if sys.platform != "darwin":
        return
    import logging  # noqa: PLC0415

    orb_log = logging.getLogger("jarvis.orb")
    try:
        from AppKit import NSApp, NSColor  # type: ignore[import-not-found] # noqa: PLC0415
    except Exception:  # noqa: BLE001
        # Without this pass Tk 9 paints the window backing as an OPAQUE grey
        # box (BUG-075) — the single most visible macOS defect. Say so loudly
        # once instead of hiding the cause in a debug line.
        global _WARNED_NO_APPKIT
        if not _WARNED_NO_APPKIT:
            _WARNED_NO_APPKIT = True
            orb_log.warning(
                "pyobjc (AppKit) unavailable — Tk 9 paints the orb backing "
                "as an opaque grey box. Install the [desktop-macos] extra "
                "(pip install 'personal-jarvis[desktop-macos]') to fix it."
            )
        return
    try:
        wins = list(NSApp.windows())
        for win in wins:
            win.setOpaque_(False)
            win.setBackgroundColor_(NSColor.clearColor())
            win.setHasShadow_(False)
        from dodaios.platform.capture_exclusion import (  # noqa: PLC0415
            exclude_macos_app_windows,
        )

        exclude_macos_app_windows()
        orb_log.debug("macOS clear-backing applied to %d window(s)", len(wins))
    except Exception:  # noqa: BLE001 — cosmetic; the grey box is the degrade
        orb_log.warning("macOS clear-backing pass failed", exc_info=True)


def reassert_macos_topmost(window: Any) -> None:
    """Put a just-revealed window back above ordinary windows on macOS.

    Aqua-Tk 9 drops the NSWindow level when a window is withdrawn and mapped
    again: ``wm attributes -topmost`` still reads 1, but the window comes back
    at the normal level (layer 0) and sinks under every other app. The orb
    hides and reveals its windows all the time, so it would vanish behind the
    browser while the app reports it as shown. Setting the attribute again
    restores the floating level; it never activates the window or takes focus.
    Call it after every ``deiconify``. No-op elsewhere, never raises.
    """
    if sys.platform != "darwin" or window is None:
        return
    try:
        window.wm_attributes("-topmost", True)
    except tk.TclError:
        logging.getLogger("jarvis.orb").debug("macOS topmost re-assert failed", exc_info=True)


_GWL_EXSTYLE = -20
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080


def _apply_jarvis_icon_to_tk_root(root: tk.Tk) -> None:
    """Set the Jarvis taskbar/titlebar icon on this Tk root.

    Thin wrapper over the canonical, cross-platform
    :func:`dodaios.ui.icon_utils.apply_tk_window_icon` so the orb and the
    JarvisBar share ONE implementation — the two used to drift apart, which is
    how the JarvisBar regressed to the Python logo (BUG #UI-Pin-2026-05-05).
    Best-effort; any failure is silent (the orb is cosmetic).
    """
    try:
        from dodaios.ui.icon_utils import apply_tk_window_icon

        apply_tk_window_icon(root)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("jarvis.orb").debug(
            "Tk icon setup failed; continuing without it.",
            exc_info=True,
        )


def _coerce_style(style: str | None) -> str:
    """Return a style this window can actually render.

    Unknown values (the removed ``mascot`` and ``pet`` looks, the legacy
    ``orb``, a typo, a value written by a newer build) fall back to the voice
    orb with one warning rather than leaving the desktop without an overlay.
    """
    candidate = (style or "").strip().lower()
    if candidate in ORB_STYLES:
        return candidate
    if candidate and candidate not in LEGACY_STYLE_ALIASES:
        logging.getLogger("jarvis.orb").warning(
            "Unknown orb style %r — falling back to %r (known: %s).",
            style,
            DEFAULT_ORB_STYLE,
            ", ".join(ORB_STYLES),
        )
    return DEFAULT_ORB_STYLE


def _apply_color_key(root: tk.Tk) -> bool:
    """Make the key colour transparent on this Tk root. False = not supported.

    Windows keys the magenta out natively on the layered window. On Linux the
    same attribute is accepted only under a compositing window manager; under a
    bare X11 session (and on Wayland) Tk raises, and the honest outcome is "no
    overlay" rather than an opaque magenta square parked on the desktop. The
    caller degrades; this never raises.
    """
    try:
        root.wm_attributes("-transparentcolor", COLOR_KEY_HEX)
        root.configure(bg=COLOR_KEY_HEX)
        return True
    except tk.TclError:
        import logging

        logging.getLogger("jarvis.orb").warning(
            "This desktop session does not support Tk's transparent colour key "
            "(typical for Wayland or X11 without a compositor) — the on-screen "
            "orb stays hidden. Voice, the tray icon and the app window are "
            "unaffected; pick 'None (hidden)' as the display style to silence "
            "this."
        )
        return False


def _hide_tk_window_from_task_switcher(root: tk.Tk) -> None:
    """Marks the orb window as a toolwindow so it doesn't count as an app."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(root.winfo_id())
        user32 = ctypes.windll.user32
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        style = int(get_long(hwnd, _GWL_EXSTYLE))
        style = (style | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW
        set_long(hwnd, _GWL_EXSTYLE, style)
    except Exception:
        # Pure desktop cosmetics. If Win32 doesn't take effect, the orb
        # stays functional and may just show up as an extra window.
        return


def _exclude_tk_window_from_capture(root: tk.Tk) -> None:
    """Keep the orb / transcription bubble out of screenshots. Best-effort."""
    try:
        from dodaios.platform.capture_exclusion import (  # noqa: PLC0415
            exclude_tk_window_from_capture,
        )

        exclude_tk_window_from_capture(root)
    except Exception:  # noqa: BLE001 — overlay must degrade, never crash
        return


class OrbControlRow:
    """The four round controls under the voice orb — see :mod:`ui.orb.controls`.

    Its own frameless, always-on-top Toplevel rather than extra pixels on the
    orb's window, for three reasons that all point the same way: the orb window
    is exactly the sphere (a taller window would put an invisible click-eating
    rectangle over whatever is underneath), the row has to appear and disappear
    on its own schedule, and the orb's frame loop must not repaint four static
    discs sixty times a second.

    Visibility is deliberately conditional (maintainer decision 2026-08-06): at
    rest the desktop shows a sphere and nothing else. The row arrives when the
    pointer does, or when a conversation is running — the two moments where a
    control is something the user is reaching for rather than clutter they did
    not ask for.
    """

    #: Grace period between losing the pointer and hiding, in ms. The row is a
    #: separate window a few pixels below the orb, so travelling from one to
    #: the other means genuinely leaving both — without this the row would
    #: vanish under the pointer on its way to being clicked.
    HOVER_GRACE_MS = 260

    #: After a hang-up, ignore clicks for this long. Same guard as the Jarvis
    #: Bar's close-X: the optimistic state flip must not let a second click
    #: land as "start a new session" (the request_hangup storm, 2026-06-19).
    CLICK_GUARD_S = 0.6

    #: Actions whose click arms :attr:`CLICK_GUARD_S` while a session runs.
    GUARDED_ACTIONS: tuple[str, ...] = ("mic", "close")

    def __init__(self, parent: tk.Tk, orb_x: int, orb_y: int, orb_w: int, orb_h: int) -> None:
        self._parent = parent
        self._orb_x = orb_x
        self._orb_y = orb_y
        self._orb_w = orb_w
        self._orb_h = orb_h
        self._top: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._image_id: int | None = None
        # macOS: frames go through a native layer (see ui/orb/mac_layer.py).
        self._presenter: MacLayerPresenter | None = None
        self._state = self._initial_state()
        self._visible = False
        self._pointer_inside = False
        self._hide_after_id: str | None = None
        self._pressed_action: str | None = None
        self._click_block_until = 0.0
        self._on_action: Callable[[str], None] | None = None
        self._width, self._height = self._row_size()
        self._build()

    # -- layout hooks --------------------------------------------------------

    def _initial_state(self) -> Any:
        return orb_controls.ControlState()

    def _row_size(self) -> tuple[int, int]:
        return orb_controls.row_size()

    def _render_frame(self) -> Image.Image:
        return orb_controls.render_row(self._state, color_key=tuple(COLOR_KEY_RGB.tolist()))

    def _hit(self, x: float, y: float) -> str | None:
        return orb_controls.hit_test(x, y)

    def _with_hovered(self, action: str | None) -> Any:
        return orb_controls.ControlState(
            active=self._state.active,
            speaker_muted=self._state.speaker_muted,
            hovered=action,
            can_attach=self._state.can_attach,
        )

    def _row_y(self) -> int:
        return self._orb_y + self._orb_h + orb_controls.ROW_GAP_FROM_ORB

    # -- wiring ---------------------------------------------------------

    def set_on_action(self, callback: Callable[[str], None] | None) -> None:
        """Route a resolved button press ("attach"/"mic"/"close"/"speaker")."""
        self._on_action = callback

    def _build(self) -> None:
        top = tk.Toplevel(self._parent)
        top.overrideredirect(True)
        top.wm_attributes("-topmost", True)
        self._mac_transparent = False
        if sys.platform == "darwin":
            try:
                top.wm_attributes("-transparent", True)
                top.configure(bg="systemTransparent")
                self._mac_transparent = True
            except tk.TclError:
                logging.getLogger("jarvis.orb").warning(
                    "macOS -transparent unsupported — the orb controls render opaque"
                )
                top.configure(bg=COLOR_KEY_HEX)
        else:
            top.wm_attributes("-transparentcolor", COLOR_KEY_HEX)
            top.configure(bg=COLOR_KEY_HEX)
        _hide_tk_window_from_task_switcher(top)
        _exclude_tk_window_from_capture(top)
        top.withdraw()

        canvas = tk.Canvas(
            top,
            width=self._width,
            height=self._height,
            bg="systemTransparent" if self._mac_transparent else COLOR_KEY_HEX,
            highlightthickness=0,
            borderwidth=0,
        )
        canvas.pack(fill="both", expand=True)
        if self._mac_transparent:
            top.update_idletasks()
            apply_macos_clear_backing()

        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<Enter>", self._on_enter)
        canvas.bind("<Leave>", self._on_leave)
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<ButtonRelease-1>", self._on_release)

        self._top = top
        self._canvas = canvas
        self._repaint()

    # -- geometry -------------------------------------------------------

    def update_anchor(self, orb_x: int, orb_y: int) -> None:
        """Follow the orb after a drag / monitor change."""
        self._orb_x = orb_x
        self._orb_y = orb_y
        if self._visible:
            self._place()

    def set_orb_size(self, orb_w: int, orb_h: int) -> None:
        """Re-centre under an orb that changed size (a live style swap)."""
        self._orb_w = orb_w
        self._orb_h = orb_h
        if self._visible:
            self._place()

    def _place(self) -> None:
        if self._top is None:
            return
        x = self._orb_x + self._orb_w // 2 - self._width // 2
        y = self._row_y()
        try:
            self._top.geometry(f"{self._width}x{self._height}+{x}+{y}")
        except tk.TclError:
            pass

    # -- state ----------------------------------------------------------

    def set_state(
        self,
        *,
        active: bool | None = None,
        speaker_muted: bool | None = None,
        can_attach: bool | None = None,
    ) -> None:
        """Update what the discs say, repainting only on a real change."""
        state = orb_controls.ControlState(
            active=self._state.active if active is None else bool(active),
            speaker_muted=(
                self._state.speaker_muted if speaker_muted is None else bool(speaker_muted)
            ),
            hovered=self._state.hovered,
            can_attach=self._state.can_attach if can_attach is None else bool(can_attach),
        )
        if state == self._state:
            return
        self._state = state
        self._repaint()

    def _repaint(self) -> None:
        if self._canvas is None:
            return
        try:
            frame = self._render_frame()
            image = key_to_alpha(frame) if self._mac_transparent else frame
            if self._mac_transparent:
                if self._presenter is None:
                    self._presenter = MacLayerPresenter(self._top, name="orb controls")
                if self._presenter.present(image):
                    return
            self._photo = ImageTk.PhotoImage(image, master=self._canvas)
            if self._image_id is None:
                self._image_id = self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
            else:
                self._canvas.itemconfigure(self._image_id, image=self._photo)
        except tk.TclError:
            pass

    # -- visibility -----------------------------------------------------

    def show(self) -> None:
        if self._top is None or self._visible:
            return
        self._cancel_pending_hide()
        self._place()
        try:
            self._top.deiconify()
            reassert_macos_topmost(self._top)
            if self._mac_transparent:
                apply_macos_clear_backing()
            self._top.lift()
        except tk.TclError:
            return
        self._visible = True

    def hide(self) -> None:
        self._cancel_pending_hide()
        self._pointer_inside = False
        if self._state.hovered is not None:
            self._state = self._with_hovered(None)
            self._repaint()
        if self._top is None or not self._visible:
            return
        try:
            self._top.withdraw()
        except tk.TclError:
            pass
        self._visible = False

    def hide_after_grace(self) -> None:
        """Hide unless the pointer comes back within :attr:`HOVER_GRACE_MS`."""
        if self._top is None or not self._visible:
            return
        self._cancel_pending_hide()
        try:
            self._hide_after_id = self._top.after(self.HOVER_GRACE_MS, self._grace_elapsed)
        except tk.TclError:
            self.hide()

    def _grace_elapsed(self) -> None:
        self._hide_after_id = None
        if self._pointer_inside:
            return
        self.hide()

    def _cancel_pending_hide(self) -> None:
        if self._hide_after_id is None or self._top is None:
            self._hide_after_id = None
            return
        try:
            self._top.after_cancel(self._hide_after_id)
        except tk.TclError:
            pass
        self._hide_after_id = None

    @property
    def pointer_inside(self) -> bool:
        return self._pointer_inside

    def contains(self, x: int, y: int) -> bool:
        """True when the screen point is on the row where it was last placed."""
        if not self._visible:
            return False
        left = self._orb_x + self._orb_w // 2 - self._width // 2
        top = self._row_y()
        return left <= x < left + self._width and top <= y < top + self._height

    def sync_pointer(self, x: int, y: int) -> bool:
        """Take the pointer's real position over the last Enter or Leave."""
        inside = self.contains(x, y)
        self._pointer_inside = inside
        if not inside:
            self._set_hovered(None)
        return inside

    @property
    def window(self) -> tk.Toplevel | None:
        return self._top

    @property
    def visible(self) -> bool:
        return self._visible

    def destroy(self) -> None:
        self._cancel_pending_hide()
        top = self._top
        self._top = None
        self._canvas = None
        self._photo = None
        if top is None:
            return
        try:
            top.destroy()
        except tk.TclError:
            pass

    # -- pointer --------------------------------------------------------

    def _on_enter(self, event: tk.Event) -> None:
        self._pointer_inside = True
        self._cancel_pending_hide()
        self._on_motion(event)

    def _on_leave(self, _event: tk.Event) -> None:
        self._pointer_inside = False
        self._set_hovered(None)
        self.hide_after_grace()

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hovered(self._hit(event.x, event.y))

    def _set_hovered(self, action: str | None) -> None:
        if action == self._state.hovered:
            return
        self._state = self._with_hovered(action)
        self._repaint()
        if self._canvas is not None:
            try:
                self._canvas.configure(cursor="hand2" if action else "")
            except tk.TclError:
                pass

    def _on_press(self, event: tk.Event) -> None:
        self._pressed_action = self._hit(event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        pressed = self._pressed_action
        self._pressed_action = None
        if pressed is None:
            return
        # Press and release must agree: a pointer that slid off the disc did
        # not click it, and every action here is one the user would rather not
        # trigger by accident.
        if self._hit(event.x, event.y) != pressed:
            return
        if time.monotonic() < self._click_block_until:
            return
        if pressed in self.GUARDED_ACTIONS and self._state.active:
            self._click_block_until = time.monotonic() + self.CLICK_GUARD_S
        callback = self._on_action
        if callback is None:
            return
        try:
            callback(pressed)
        except Exception:  # noqa: BLE001 — a bad action must not kill the Tk loop
            logging.getLogger("jarvis.orb").debug(
                "orb control action %r failed", pressed, exc_info=True
            )


FRAME_INTERVAL_MS = 16  # ~60 FPS while the orb is on screen


class OrbOverlay:
    """Public facade — Tkinter-based, thread-safe via a UI queue.

    tkinter itself is not thread-safe, so every call from other threads
    (Jarvis-Core, the demo thread) is queued and drained by the Tk loop.
    """

    def __init__(
        self,
        sticky: bool = False,
        mic_reactive: bool = False,
        style: str | None = None,
    ) -> None:
        """
        style: one of :data:`ORB_STYLES` (only ``"voice_orb"`` today). Anything
        else, including the removed ``"mascot"`` and ``"pet"``, becomes the
        voice orb.
        """
        self._sticky = sticky
        self._mic_reactive = mic_reactive
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._renderer: VoiceOrbRenderer | None = None
        self._mac_transparent = False
        # Cached anchor of the window's top-left corner.
        self._mascot_x: int = 0
        self._mascot_y: int = 0
        # Drag-and-pin state. _manual_pinned switches the 1500 ms recheck
        # loop into clamp-only mode and tells boot to skip the taskbar
        # anchor.
        self._manual_pinned: bool = False
        self._drag_state: _DragState | None = None
        self._boot_flash_target_xy: tuple[int, int] | None = None
        # Double-double-click on the orb fires this callback (user spec
        # 2026-05-17 + revision 2026-05-18: two double-clicks within
        # MUTE_GESTURE_WINDOW_MS toggle the Jarvis-wide mute). The orb
        # stays decoupled from the bus — OrbBusBridge injects a
        # callable that publishes ``VoiceMuteToggleRequested``.
        self._mute_toggle_callback: Callable[[], None] | None = None
        # Right-click raises the main window. OrbBusBridge injects a callable
        # that publishes ``ShowWindowRequested``; the orb itself stays
        # bus-agnostic (same contract as the mute toggle).
        self._on_show_window: Callable[[], None] | None = None
        # The control row's actions. Each is optional: wired, the callback
        # decides (the macOS host forwards it to the parent process, which is
        # the only place a SpeechPipeline exists); unwired, the row falls back
        # to the live pipeline in THIS process — the same two-step the Jarvis
        # Bar uses for its own talk / hang-up buttons.
        self._on_talk: Callable[[], None] | None = None
        self._on_hangup: Callable[[], None] | None = None
        self._on_speaker_toggle: Callable[[], None] | None = None
        #: The four round controls under the sphere.
        self._controls: OrbControlRow | None = None
        self._pointer_over_orb = False
        self._speaker_muted = False
        # Frame-loop bookkeeping: ONE pending tick at most.
        self._frame_after_id: str | None = None
        # macOS: the frames go through a native layer instead of the Tk
        # canvas, which leaves a black box and stacked frames behind there
        # (ui/orb/mac_layer.py).
        self._presenter: MacLayerPresenter | None = None
        self._frame_error_logged = False
        # Counter + Tk timer-id for the two-double-click gesture. The
        # earlier single-double-click implementation muted Jarvis as soon
        # as the user clicked twice on the popup logo, which fired
        # accidentally whenever the user clicked the freshly appeared
        # orb. Two double-clicks (four rapid clicks) is intentional.
        self._mute_click_count: int = 0
        self._mute_click_reset_id: str | None = None
        # ADR-0016 visible-feedback contract: bridge injects a callable
        # that publishes ``UserVisibleFeedback`` from the bus side. The
        # orb stays bus-agnostic; this lets unit tests run without a bus.
        # Signature: ``(mode: str, observed: dict[str, Any]) -> None``.
        self._feedback_publisher: Callable[[str, dict[str, Any]], None] | None = None
        self._show_until_t: float = 0.0
        self._pending_hide_after_id: str | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._image_id: int | None = None
        self._mode: str = "idle"
        self._ext_level: float | None = None
        self._t0: float = 0.0
        self._running: bool = False
        self._started = threading.Event()
        self._ui_queue: queue.Queue = queue.Queue()
        self._tk_thread_id: int | None = None
        # Lazy import so the orb stays startable even without sounddevice
        # (mic-reactive mode is optional).
        self._mic = None
        self._style = _coerce_style(style)
        self._win_w, self._win_h = window_size_for_style(self._style)

    # --- Public API ----------------------------------------------------

    def start(self, auto_demo: bool = False) -> None:
        self._tk_thread_id = threading.get_ident()
        # Test-safety guard: under pytest, never put a REAL orb window on the
        # developer's desktop unless explicitly opted in (JARVIS_GUI_TESTS=1).
        # A routine `pytest tests/unit/` run (and parallel runs across
        # worktrees) would otherwise leave a live 'JarvisOrb' Tk window on
        # screen until the test process exits. No production effect: pytest is
        # never imported in the live app. ``_started`` is still set so a
        # ``start_in_thread`` caller unblocks immediately instead of timing out.
        if "pytest" in sys.modules and not os.environ.get("JARVIS_GUI_TESTS"):
            self._started.set()
            return
        from dodaios.ui.tk_runtime import prepare_tk_runtime

        prepare_tk_runtime()
        # DPI awareness MUST be set before Win32 GetWindowRect calls, else
        # taskbar coords come back DPI-virtualised and the orb ends up
        # misplaced on 125%/150% scaled displays.
        _ensure_dpi_awareness()
        self._root = tk.Tk()
        self._root.title("JarvisOrb")
        self._root.overrideredirect(True)  # Frameless, no drop shadow
        self._root.wm_attributes("-topmost", True)
        # Per-pixel transparency, per platform: Windows keys out the magenta
        # color key on the layered window; macOS has no color key, so there
        # the WINDOW itself becomes transparent (Aqua-Tk's "-transparent" +
        # the systemTransparent background) and every frame carries a real
        # alpha channel instead (key_to_alpha in the frame loop).
        if sys.platform == "darwin":
            try:
                self._root.wm_attributes("-transparent", True)
                self._root.configure(bg="systemTransparent")
                self._mac_transparent = True
            except tk.TclError:
                logging.getLogger("jarvis.orb").warning(
                    "macOS -transparent unsupported — the orb will show its key colour"
                )
                self._root.configure(bg=COLOR_KEY_HEX)
        else:
            if not _apply_color_key(self._root):
                # No per-pixel transparency on this session: showing the window
                # would put an opaque magenta square on the user's desktop.
                # Tear the root down and report started, so the caller's
                # start_in_thread() unblocks instead of timing out.
                try:
                    self._root.destroy()
                except tk.TclError:
                    pass
                self._root = None
                self._started.set()
                return
            # The colour key belongs to THIS window only. Once this Tk loop
            # stops pumping — any long GIL-holding stretch on another thread
            # does it — Windows paints an unlayered ``Ghost`` stand-in over the
            # same rectangle, and the keyed-out padding arrives as an opaque
            # black box around the orb. Same defect as the bar's.
            try:
                from dodaios.core.process_utils import disable_windows_app_ghosting

                disable_windows_app_ghosting()
            except Exception:  # noqa: BLE001 — cosmetic; the orb must still boot
                logging.getLogger("jarvis.orb").debug(
                    "window-ghosting suppression unavailable — a stalled orb may "
                    "show an opaque box",
                    exc_info=True,
                )
        # Apply the Jarvis icon BEFORE hiding from the task switcher: Windows
        # caches the taskbar entry on first show, so even a brief flash with
        # the default pythonw icon sticks.
        _apply_jarvis_icon_to_tk_root(self._root)
        _hide_tk_window_from_task_switcher(self._root)
        _exclude_tk_window_from_capture(self._root)

        # Resolve the anchor. If the user has manually pinned the orb in a
        # prior session, restore that position; otherwise compute the live
        # Windows-taskbar-aligned default.
        #
        # BUG-027 defense: when the persisted pin lives on a non-primary
        # monitor, resolve_placement reports recovered=True so we clear the
        # stale entry and fall back to the primary anchor. The user can opt
        # out via ``[overlay.mascot] allow_secondary_monitor_pin = true``
        # in jarvis.toml.
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        persisted = load_position_from_toml(JARVIS_TOML_PATH)
        if persisted is not None and persisted.monitor:
            screens = screens_from_tk(self._root)
            allow_secondary = load_allow_secondary_monitor_pin(JARVIS_TOML_PATH)
            placement = resolve_placement(
                persisted,
                screens,
                mascot_size_px=self._win_w,
                require_primary=not allow_secondary,
            )
            if not placement.recovered:
                # Persisted monitor still present — honour user's pin.
                self._manual_pinned = True
                self._mascot_x = placement.abs_x
                self._mascot_y = placement.abs_y
                # L1 gate (BUG-027 / ADR-0016): when the honored pin is on
                # a NON-primary monitor in a multi-monitor topology, start
                # the orb at the primary anchor and migrate after a brief
                # visible flash. Single-monitor and primary-pin boots
                # skip the flash entirely (no visual noise in 99% case).
                resolved_screen = next((s for s in screens if s.name == placement.monitor), None)
                if (
                    len(screens) > 1
                    and resolved_screen is not None
                    and not resolved_screen.is_primary
                ):
                    primary_anchor = self._resolve_anchor(screen_w, screen_h)
                    self._boot_flash_target_xy = (placement.abs_x, placement.abs_y)
                    self._root.geometry(
                        f"{self._win_w}x{self._win_h}+{primary_anchor.x}+{primary_anchor.y}"
                    )
                else:
                    self._root.geometry(
                        f"{self._win_w}x{self._win_h}+{placement.abs_x}+{placement.abs_y}"
                    )
            else:
                # Monitor gone, no screens, or pin on non-primary monitor
                # while require_primary is set — fall back to default and
                # clear the stale entry so next boot starts clean.
                try:
                    clear_position_in_toml(JARVIS_TOML_PATH)
                except OSError:
                    pass
                anchor = self._resolve_anchor(screen_w, screen_h)
                self._mascot_x = anchor.x
                self._mascot_y = anchor.y
                self._root.geometry(f"{self._win_w}x{self._win_h}+{anchor.x}+{anchor.y}")
        else:
            anchor = self._resolve_anchor(screen_w, screen_h)
            self._mascot_x = anchor.x
            self._mascot_y = anchor.y
            self._root.geometry(f"{self._win_w}x{self._win_h}+{anchor.x}+{anchor.y}")

        self._canvas = tk.Canvas(
            self._root,
            width=self._win_w,
            height=self._win_h,
            bg="systemTransparent" if self._mac_transparent else COLOR_KEY_HEX,
            highlightthickness=0,
            borderwidth=0,
        )
        self._canvas.pack(fill="both", expand=True)
        if self._mac_transparent:
            # Tk 9 needs the native backing cleared too (BUG-075); flush
            # geometry so the NSWindow exists before the AppKit pass.
            self._root.update_idletasks()
            apply_macos_clear_backing()

        # Drag + interaction bindings. Tk dispatch:
        #   <Button-1> → drag-start (always fires, even on a double-click)
        #   <B1-Motion> → drag-update (only fires while LMB held)
        #   <ButtonRelease-1> → drag-finish (or no-op if it was a click)
        #   <Double-Button-1> → mute toggle (fires after Button-1+Release)
        #   <Button-3>       → raise the main window
        #   <Button-2>       → reset position
        self._canvas.bind("<ButtonPress-1>", self._on_drag_press)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_release)
        self._canvas.bind("<Double-Button-1>", self._on_mute_double_click)
        self._canvas.bind("<Button-3>", self._on_right_click)
        self._canvas.bind("<Button-2>", self._on_reset_double_click)
        # Pointer presence drives the control row (see OrbControlRow): reaching
        # for the orb is the moment its controls become useful.
        self._canvas.bind("<Enter>", self._on_orb_pointer_enter)
        self._canvas.bind("<Leave>", self._on_orb_pointer_leave)

        # Drag-drop onto the orb (desktop extra, cross-platform via tkdnd).
        # Pure addition, fully guarded: a no-op when tkinterdnd2 is absent
        # (NullDropTarget) so the live overlay is never destabilised. Dropped
        # paths/text go to the process-global bridge, which the desktop app
        # marshals to the brain intake (dodaios/brain/drop_context.ingest_drop).
        try:
            from dodaios.overlay.drop_bridge import dispatch_drop
            from dodaios.overlay.drop_target import make_drop_target

            make_drop_target().register(self._canvas, dispatch_drop)
        except Exception:  # noqa: BLE001 — drop is optional; never block orb boot.
            logging.getLogger("jarvis.orb").debug(
                "orb drop target registration skipped", exc_info=True
            )

        self._ensure_controls()
        self._renderer = self._build_renderer()
        self._t0 = time.perf_counter()
        self._running = True

        # ADR-0016 L1 — selective boot flash. When the persisted pin is
        # honored on a secondary monitor (Power-User mode), show the orb
        # at the primary anchor for 800 ms BEFORE migrating to the pin.
        # Skipped in single-monitor / primary-pin / default-anchor boots.
        if self._boot_flash_target_xy is not None and not self._sticky:
            target_x, target_y = self._boot_flash_target_xy
            self._root.deiconify()
            reassert_macos_topmost(self._root)
            self._root.after(800, lambda: self._finish_boot_flash(target_x, target_y))
        elif not self._sticky:
            self._root.withdraw()

        self._started.set()

        # Start the mic listener only after window creation, so any
        # sounddevice errors (no mic, PortAudio init) surface only after the
        # orb is visible and aren't silently swallowed at startup.
        if self._mic_reactive:
            try:
                from ui.orb.mic_listener import MicListener

                self._mic = MicListener(on_level=self.set_level)
                self._mic.start()
            except Exception as exc:  # noqa: BLE001
                print(f"[orb] Mic-reactive mode failed to start: {exc}")

        if auto_demo:
            threading.Thread(target=self._run_demo, daemon=True).start()

        self._schedule_ui_queue()
        # Through the guard, not a direct call: a show() drained just above may
        # already have armed the loop, and a second chain would double every tick.
        self._ensure_frame_loop()
        self._schedule_position_recheck()
        self._root.mainloop()

    def _resolve_anchor(self, screen_w: int, screen_h: int) -> MascotAnchor:
        """Read live taskbar+tray rects from Win32 and compute the orb's anchor."""
        return compute_mascot_position(
            screen_w,
            screen_h,
            mascot_size=self._win_w,
            taskbar=get_taskbar_info(),
            tray_rect=get_tray_notify_rect(),
            tray_safe_margin_px=TRAY_SAFE_MARGIN_PX,
            right_edge_margin_px=RIGHT_EDGE_MARGIN_PX,
            overlap_px=TASKBAR_OVERLAP_PX,
            autohide_bottom_margin_px=AUTOHIDE_BOTTOM_MARGIN_PX,
        )

    def _clamp_position(
        self, x: int, y: int, monitor_geo: tuple[int, int, int, int]
    ) -> tuple[int, int]:
        """Keep the window on the visible work area."""
        return clamp_to_work_area(x, y, monitor_geo, mascot_size_px=self._win_w)

    def _move_attached(self, x: int, y: int, _screen_w: int = 0) -> None:
        """Bring the control row along after the window moved."""
        if self._controls is not None:
            self._controls.update_anchor(x, y)

    def _schedule_position_recheck(self) -> None:
        """Re-resolve the orb anchor periodically.

        Two paths:
        - manual_pinned=False: taskbar-anchor recompute (DPI / monitor /
          taskbar resize tracking).
        - manual_pinned=True: clamp-only — keep the orb on the visible work
          area if monitors changed; otherwise leave it alone.
        """
        if not self._running or not self._root:
            return
        try:
            screen_w = self._root.winfo_screenwidth()
            screen_h = self._root.winfo_screenheight()
            if self._manual_pinned:
                screens = screens_from_tk(self._root)
                monitor_geo, monitor_name = self._monitor_at_orb_center(screens)
                clamped_x, clamped_y = self._clamp_position(
                    self._mascot_x, self._mascot_y, monitor_geo
                )
                if (clamped_x, clamped_y) != (self._mascot_x, self._mascot_y):
                    self._mascot_x = clamped_x
                    self._mascot_y = clamped_y
                    self._root.geometry(f"{self._win_w}x{self._win_h}+{clamped_x}+{clamped_y}")
                    self._move_attached(clamped_x, clamped_y, screen_w)
                    try:
                        save_position_to_toml(
                            JARVIS_TOML_PATH,
                            MascotPosition(
                                monitor=monitor_name,
                                x_relative=clamped_x - monitor_geo[0],
                                y_relative=clamped_y - monitor_geo[1],
                            ),
                        )
                    except OSError:
                        pass
            else:
                anchor = self._resolve_anchor(screen_w, screen_h)
                if (anchor.x, anchor.y) != (self._mascot_x, self._mascot_y):
                    self._mascot_x = anchor.x
                    self._mascot_y = anchor.y
                    self._root.geometry(f"{self._win_w}x{self._win_h}+{anchor.x}+{anchor.y}")
                    self._move_attached(anchor.x, anchor.y, screen_w)
        except (tk.TclError, OSError):
            logging.getLogger("jarvis.orb").debug("orb position recheck skipped", exc_info=True)
        if self._root is not None:
            self._root.after(POSITION_RECHECK_MS, self._schedule_position_recheck)

    # ------------------------------------------------------------------
    # Drag-and-pin handlers (Spec: docs/superpowers/specs/2026-05-17-orb-drag-design.md)
    # ------------------------------------------------------------------

    def _on_drag_press(self, event: tk.Event) -> None:
        if self._root is None:
            return
        self._drag_state = _DragState(
            start_root_x=event.x_root,
            start_root_y=event.y_root,
            offset_x=event.x_root - self._mascot_x,
            offset_y=event.y_root - self._mascot_y,
            moved=False,
        )
        try:
            self._root.configure(cursor="fleur")
        except tk.TclError:
            pass

    def _on_drag_motion(self, event: tk.Event) -> None:
        if self._drag_state is None or self._root is None:
            return
        dx = event.x_root - self._drag_state.start_root_x
        dy = event.y_root - self._drag_state.start_root_y
        if not self._drag_state.moved and (abs(dx) + abs(dy)) < DRAG_THRESHOLD_PX:
            return
        self._drag_state.moved = True
        new_x = event.x_root - self._drag_state.offset_x
        new_y = event.y_root - self._drag_state.offset_y
        self._mascot_x = new_x
        self._mascot_y = new_y
        try:
            self._root.geometry(f"{self._win_w}x{self._win_h}+{new_x}+{new_y}")
        except tk.TclError:
            return
        self._move_attached(new_x, new_y, self._root.winfo_screenwidth())

    def _on_drag_release(self, _event: tk.Event) -> None:
        if self._root is not None:
            try:
                self._root.configure(cursor="")
            except tk.TclError:
                pass
        state = self._drag_state
        self._drag_state = None
        if state is None or not state.moved:
            return  # click, not drag

        screens = screens_from_tk(self._root)
        monitor_geo, monitor_name = self._monitor_at_orb_center(screens)
        clamped_x, clamped_y = self._clamp_position(self._mascot_x, self._mascot_y, monitor_geo)
        if (clamped_x, clamped_y) != (self._mascot_x, self._mascot_y):
            self._mascot_x = clamped_x
            self._mascot_y = clamped_y
            try:
                self._root.geometry(f"{self._win_w}x{self._win_h}+{clamped_x}+{clamped_y}")
            except tk.TclError:
                logging.getLogger("jarvis.orb").debug("orb clamp move failed", exc_info=True)
        if self._controls is not None:
            self._controls.update_anchor(self._mascot_x, self._mascot_y)

        self._manual_pinned = True
        pin = MascotPosition(
            monitor=monitor_name,
            x_relative=self._mascot_x - monitor_geo[0],
            y_relative=self._mascot_y - monitor_geo[1],
        )
        try:
            save_position_to_toml(JARVIS_TOML_PATH, pin)
        except OSError as exc:
            # Persistence failure is non-fatal — orb stays at new position
            # for this session; next restart falls back to default.
            print(f"[orb] save_position_to_toml failed: {exc}")

    def set_on_mute_toggle(self, callback: Callable[[], None] | None) -> None:
        """Inject the Jarvis-wide mute toggle action.

        Fired when the user double-clicks the orb twice. The callback is
        responsible for the actual mute logic — this layer just translates
        the gesture. Pass ``None`` to detach. The orb knows nothing about
        Jarvis-Core, EventBus, or Supervisor states; the bridge publishes.
        """
        self._mute_toggle_callback = callback

    # ------------------------------------------------------------------
    # Control row
    # ------------------------------------------------------------------

    def _ensure_controls(self) -> None:
        """Create the row of four round controls under the sphere once."""
        if self._root is None or self._controls is not None:
            return
        try:
            row = OrbControlRow(
                parent=self._root,
                orb_x=self._mascot_x,
                orb_y=self._mascot_y,
                orb_w=self._win_w,
                orb_h=self._win_h,
            )
        except tk.TclError:
            logging.getLogger("jarvis.orb").debug("orb control row unavailable", exc_info=True)
            return
        row.set_on_action(self._on_control_action)
        row.set_state(
            active=self._mode in ACTIVE_VOICE_MODES,
            speaker_muted=self._speaker_muted,
        )
        self._controls = row

    def _on_orb_pointer_enter(self, _event: tk.Event | None = None) -> None:
        self._pointer_over_orb = True
        row = self._controls
        if row is not None:
            row.show()

    def _on_orb_pointer_leave(self, _event: tk.Event | None = None) -> None:
        self._pointer_over_orb = False
        row = self._controls
        if row is None:
            return
        # A live conversation keeps the controls out: hanging up is the one
        # thing the user reaches for mid-call, and hunting for a row that hides
        # itself is worse than a row that stays.
        if self._mode in ACTIVE_VOICE_MODES:
            return
        row.hide_after_grace()

    def _sync_controls_visibility(self) -> None:
        """Reconcile the row with mode + pointer after a state change."""
        row = self._controls
        if row is None:
            return
        active = self._mode in ACTIVE_VOICE_MODES
        row.set_state(active=active)
        # Never on its own: the row is the orb's controls, so a mode change
        # arriving while the sphere is withdrawn must not float four buttons
        # over an empty desktop.
        if not self._orb_is_visible():
            row.hide()
            return
        if active or self._pointer_over_orb or row.pointer_inside:
            row.show()
        else:
            row.hide_after_grace()

    def _reveal_controls(self) -> None:
        """Post-deiconify pass: refresh the speaker disc, then place the row."""
        if self._controls is None:
            return
        self._refresh_speaker_state()
        self._sync_controls_visibility()

    def _orb_is_visible(self) -> bool:
        if self._root is None:
            return False
        try:
            return bool(self._root.winfo_viewable())
        except tk.TclError:
            return False

    def _on_control_action(self, action: str) -> None:
        """Run one control-row button. Always on the Tk thread."""
        if action == "attach":
            self._do_attach()
        elif action in ("mic", "orb"):
            self._do_talk_or_hangup()
        elif action == "close":
            self._do_close()
        elif action == "speaker":
            self._do_speaker_toggle()

    def _do_attach(self) -> None:
        """Pick files and hand them to the conversation (same path as a drop)."""
        log = logging.getLogger("jarvis.orb")
        count = orb_controls.pick_and_dispatch_files(
            self._root, on_error=lambda message: log.warning("orb attach: %s", message)
        )
        if count:
            log.info("orb attach: handed %d file(s) to the conversation", count)

    def _do_talk_or_hangup(self) -> None:
        """The mic disc: start a conversation, or end the running one."""
        if self._mode in ACTIVE_VOICE_MODES:
            self._do_hangup()
            return
        callback = self._on_talk
        if callback is not None:
            callback()
            return
        pipeline = self._speech_pipeline()
        starter = getattr(pipeline, "request_voice_session", None)
        if callable(starter):
            starter()

    def _do_hangup(self) -> None:
        callback = self._on_hangup
        if callback is not None:
            callback()
        else:
            pipeline = self._speech_pipeline()
            hangup = getattr(pipeline, "request_hangup", None)
            if callable(hangup):
                hangup()
        # Local feedback now instead of waiting for microphone teardown plus
        # the EventBus round-trip; the authoritative state reconciles it.
        self._set_mode("idle")
        self._sync_controls_visibility()

    def _do_close(self) -> None:
        """X: end the conversation and put the orb away, like the in-app X."""
        if self._mode in ACTIVE_VOICE_MODES:
            self._do_hangup()
        row = self._controls
        if row is not None:
            row.hide()
        self._pointer_over_orb = False
        self._show_until_t = 0.0
        self._actually_hide()

    def _do_speaker_toggle(self) -> None:
        """Silence / restore the assistant's voice for this session only."""
        callback = self._on_speaker_toggle
        if callback is not None:
            callback()
            # The host process cannot see the pipeline, so it cannot report the
            # resulting state either. Mirror optimistically — the next reveal
            # re-reads the truth via _refresh_speaker_state.
            self._speaker_muted = not self._speaker_muted
        else:
            result = orb_controls.toggle_speaker_mute(source="orb")
            if result is None:
                logging.getLogger("jarvis.orb").info(
                    "orb speaker toggle ignored — no live speech pipeline"
                )
                return
            self._speaker_muted = result
        row = self._controls
        if row is not None:
            row.set_state(speaker_muted=self._speaker_muted)

    def _refresh_speaker_state(self) -> None:
        """Re-read the real TTS mute so the disc cannot drift out of sync."""
        if self._on_speaker_toggle is not None:
            return  # hosted: this process has no pipeline to ask
        muted = orb_controls.speaker_is_muted()
        if muted == self._speaker_muted:
            return
        self._speaker_muted = muted
        row = self._controls
        if row is not None:
            row.set_state(speaker_muted=muted)

    @staticmethod
    def _speech_pipeline():
        """The live pipeline, or ``None`` off the desktop process."""
        try:
            from dodaios.core.runtime_refs import get_speech_pipeline
        except Exception:  # noqa: BLE001 — importable in practice; never fatal
            return None
        return get_speech_pipeline()

    def set_on_talk(self, callback: Callable[[], None] | None) -> None:
        """Inject "start a voice session" (the mic disc while idle).

        Wired by ``dodaios.ui.dodaiosbar.host`` when the orb runs in the macOS
        companion process, where no SpeechPipeline exists; the parent applies
        it. In-process the orb calls the pipeline itself.
        """
        self._on_talk = callback

    def set_on_hangup(self, callback: Callable[[], None] | None) -> None:
        """Inject "end the running session" (the mic disc while active, and X)."""
        self._on_hangup = callback

    def set_on_speaker_toggle(self, callback: Callable[[], None] | None) -> None:
        """Inject the assistant-voice mute toggle (the speaker disc)."""
        self._on_speaker_toggle = callback

    def set_on_show_window(self, callback: Callable[[], None] | None) -> None:
        """Inject the main-window action used by a right-click on the orb.

        Same bus-agnostic contract as ``set_on_mute_toggle``: OrbBusBridge
        passes a callable that publishes ``ShowWindowRequested``. Pass
        ``None`` to detach.
        """
        self._on_show_window = callback

    def _on_right_click(self, _event: tk.Event | None = None) -> None:
        """A right-click raises the main window."""
        self._open_main_window()

    def _open_main_window(self) -> None:
        callback = self._on_show_window
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            # The Tk thread must not crash on a downstream bus hiccup.
            logging.getLogger("jarvis.orb").warning("orb show-window callback raised: %r", exc)

    def _on_mute_double_click(self, _event: tk.Event) -> None:
        """First half of the mute gesture: increment a counter and arm a
        reset timer. Mute toggles only after a *second* ``<Double-Button-1>``
        within ``MUTE_GESTURE_WINDOW_MS`` ms (i.e. four clicks in quick
        succession). One stray double-click — e.g. when the user clicks
        the orb the moment it pops up — leaves the counter at 1 and
        expires harmlessly.

        Tk fires ``<Double-Button-1>`` *in addition* to the regular
        ``<Button-1>`` press/release pair. The press already entered
        ``_on_drag_press`` and primed the drag state; we abort it here so
        a cursor twitch between the second press and release does not
        commit a move.
        """
        self._drag_state = None
        self._mute_click_count += 1
        if self._mute_click_count >= 2:
            # Second double-click inside the window — fire the toggle.
            # Reset book-keeping first so a downstream callback exception
            # cannot strand the counter in the "armed" state.
            self._mute_click_count = 0
            self._cancel_mute_click_reset()
            self._fire_mute_toggle()
            return
        # First double-click. Cancel any previous timer (defensive) and
        # arm a fresh one that resets the counter if no second gesture
        # follows.
        self._cancel_mute_click_reset()
        if self._root is None:
            # Tests / headless harness: no timer available. Without the
            # reset timer the second click ought to still toggle, so
            # this branch is a graceful no-op for the timer-arm step.
            return
        try:
            self._mute_click_reset_id = self._root.after(
                MUTE_GESTURE_WINDOW_MS, self._reset_mute_click_count
            )
        except tk.TclError as exc:
            # Root went away mid-gesture — treat as graceful no-op so the
            # next legitimate gesture still works after the orb is rebuilt.
            print(f"[orb] mute gesture timer-arm failed: {exc}")

    def _reset_mute_click_count(self) -> None:
        """Tk-timer callback: clear the counter after ``MUTE_GESTURE_WINDOW_MS``
        with no second double-click. Called from the Tk main-thread, so no
        synchronisation needed.
        """
        self._mute_click_count = 0
        self._mute_click_reset_id = None

    def _cancel_mute_click_reset(self) -> None:
        """Cancel the pending Tk-after timer, if any. Safe to call when
        no timer is armed (e.g. before the first click of a gesture).
        """
        if self._mute_click_reset_id is None or self._root is None:
            self._mute_click_reset_id = None
            return
        try:
            self._root.after_cancel(self._mute_click_reset_id)
        except tk.TclError:
            # Timer already fired or root disposed — both are harmless.
            pass
        self._mute_click_reset_id = None

    def _fire_mute_toggle(self) -> None:
        """Invoke the registered mute-toggle callback exactly once.

        Used by the two-double-click gesture path *and* by the right-
        click context menu, which is the always-on recovery path: it
        must NOT require a four-click ritual to undo an accidental mute.
        """
        callback = self._mute_toggle_callback
        if callback is None:
            print("[orb] mute toggle gesture fired without registered callback")
            return
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            # Tk thread must not crash on a downstream bus hiccup — the
            # gesture is supposed to silence Jarvis, not blow up the orb.
            print(f"[orb] mute toggle callback raised: {exc!r}")

    def _on_reset_double_click(self, _event: tk.Event | None = None) -> None:
        """Reset the orb to its default anchor position.

        Historically bound to ``<Double-Button-1>`` (moved to mute on
        2026-05-17) and then reachable via the right-click menu. Spec
        2026-06-02 binds it to middle-click (``<Button-2>``) since right-click
        now raises the main window. Still reachable via the voice
        ``OrbResetRequested`` path and kept callable by the same name so the
        existing reset-coverage stays valid.
        """
        if self._root is None:
            return
        self._manual_pinned = False
        self._drag_state = None
        try:
            clear_position_in_toml(JARVIS_TOML_PATH)
        except OSError as exc:
            print(f"[orb] clear_position_in_toml failed: {exc}")
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        anchor = self._resolve_anchor(screen_w, screen_h)
        self._mascot_x = anchor.x
        self._mascot_y = anchor.y
        try:
            self._root.geometry(f"{self._win_w}x{self._win_h}+{anchor.x}+{anchor.y}")
        except tk.TclError:
            return
        if self._controls is not None:
            self._controls.update_anchor(anchor.x, anchor.y)

    def _monitor_at_orb_center(self, screens: list) -> tuple[tuple[int, int, int, int], str]:
        """Return (geometry, device_name) of the monitor containing the orb center."""
        cx = self._mascot_x + self._win_w // 2
        cy = self._mascot_y + self._win_h // 2
        for s in screens:
            sx, sy, sw, sh = s.geometry
            if sx <= cx < sx + sw and sy <= cy < sy + sh:
                return s.geometry, s.name
        # Fallback: primary monitor.
        primary = next((s for s in screens if s.is_primary), None)
        if primary is not None:
            return primary.geometry, primary.name
        if screens:
            return screens[0].geometry, screens[0].name
        # Last resort: single-screen guess.
        if self._root is not None:
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            return (0, 0, sw, sh), ""
        return (0, 0, 1920, 1080), ""

    #: Min on-screen duration after a show() call. Even if hide() is invoked
    #: immediately afterwards, the orb stays visible for at least this long.
    SHOW_MIN_DURATION_S: float = 2.5

    def show(self, mode: str = "listen") -> None:
        """Reveal the orb in ``mode``. Thread-safe.

        The mode is validated SYNCHRONOUSLY, on the caller's thread, before the
        reveal is queued. That ordering is the contract, not a detail: the work
        itself is handed to the Tk thread, so a mode rejected inside ``_show``
        would be dropped later, on another thread, where no exception can ever
        reach the caller — the call would return "successfully" and the user
        would simply see nothing. Callers that keep a fallback look for a
        surface which cannot render a mode depend on hearing about the
        rejection here.

        Raises ``ValueError`` for a mode outside the shared vocabulary.
        """
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode!r} (allowed: {', '.join(MODES)})")

        def _show() -> None:
            self._cancel_pending_hide()
            self._set_mode(mode)
            if self._root:
                self._root.deiconify()
                reassert_macos_topmost(self._root)
                if self._mac_transparent:
                    # Tk 9 can (re)materialize the NSWindow on mapping after a
                    # withdraw; a construction-time clear-backing pass does not
                    # survive that, leaving the opaque grey box (BUG-075).
                    # Re-assert on every reveal — idempotent and cheap.
                    apply_macos_clear_backing()
                # ADR-0016 visible-feedback contract: schedule a post-frame
                # visibility snapshot. 50 ms gives Tk time to actually map
                # the window before we sample winfo_viewable / winfo_x.
                # We must NOT block the deiconify path — publish is fire-
                # and-forget; failures are swallowed by the publisher.
                self._root.after(50, self._publish_visibility_feedback, mode)
                # Same 50 ms reason: the row asks whether the orb is mapped,
                # and right after deiconify Tk still says it is not. The
                # speaker disc re-reads the real TTS mute here too, so a mute
                # set elsewhere (settings slider, voice command) is reflected
                # rather than remembered wrong.
                self._root.after(50, self._reveal_controls)
                self._ensure_frame_loop()
            now = time.perf_counter() - self._t0
            self._show_until_t = max(self._show_until_t, now + self.SHOW_MIN_DURATION_S)

        self._enqueue_ui(_show)

    def _finish_boot_flash(self, target_x: int, target_y: int) -> None:
        """ADR-0016 L1: end the boot-flash phase by migrating the orb to
        the persisted pin and hiding it again. Runs on the Tk thread.

        Defensive: if a wake-word arrived during the 800 ms flash and the
        orb is already in a visible state for LISTENING etc., the
        ``_show_until_t`` guard keeps it on-screen at the target position
        rather than withdrawing immediately.
        """
        if self._root is None:
            return
        self._mascot_x = target_x
        self._mascot_y = target_y
        try:
            self._root.geometry(f"{self._win_w}x{self._win_h}+{target_x}+{target_y}")
        except tk.TclError:
            return
        now = time.perf_counter() - self._t0
        if now >= self._show_until_t:
            try:
                self._root.withdraw()
            except tk.TclError:
                logging.getLogger("jarvis.orb").debug("boot-flash withdraw failed", exc_info=True)
        self._boot_flash_target_xy = None

    def set_feedback_publisher(
        self, callback: Callable[[str, dict[str, Any]], None] | None
    ) -> None:
        """Inject the ADR-0016 visible-feedback publisher.

        Called from ``OrbBusBridge.attach`` so the bridge owns the bus
        reference and the orb stays bus-agnostic. Set to ``None`` to
        detach (useful in unit tests).
        """
        self._feedback_publisher = callback

    def _publish_visibility_feedback(self, mode: str) -> None:
        """Sample the live Tk geometry and forward to the registered
        publisher (if any). Runs on the Tk main thread via ``root.after``.

        Errors must NOT propagate — a bad bus or a stale root would
        otherwise crash the Tk event loop and freeze the orb. The bridge
        owns monitor naming, so ``observed`` carries no monitor.
        """
        publisher = self._feedback_publisher
        if publisher is None or self._root is None:
            return
        try:
            viewable = int(self._root.winfo_viewable())
            x = int(self._root.winfo_x())
            y = int(self._root.winfo_y())
            geometry = f"{self._win_w}x{self._win_h}+{x}+{y}"
        except tk.TclError:
            return
        observed = {"viewable": viewable, "geometry": geometry, "x": x, "y": y}
        try:
            publisher(mode, observed)
        except Exception:  # noqa: BLE001
            logging.getLogger("jarvis.orb").debug(
                "feedback publisher raised; suppressed", exc_info=True
            )

    def hide(self) -> None:
        def _hide() -> None:
            self._cancel_pending_hide()
            if not self._root:
                return
            now = time.perf_counter() - self._t0
            remaining_s = self._show_until_t - now
            if remaining_s > 0.001:
                wait_ms = max(1, int(round(remaining_s * 1000)))
                self._pending_hide_after_id = self._root.after(wait_ms, self._actually_hide)
            else:
                self._actually_hide()

        self._enqueue_ui(_hide)

    def _actually_hide(self) -> None:
        self._pending_hide_after_id = None
        # The controls belong to the orb, not to the desktop: a row of buttons
        # left floating where the sphere used to be is a widget with nothing
        # behind it.
        row = self._controls
        if row is not None:
            row.hide()
        self._pointer_over_orb = False
        if self._root is not None:
            try:
                self._root.withdraw()
            except tk.TclError:
                logging.getLogger("jarvis.orb").debug("orb withdraw failed", exc_info=True)

    def stop(self) -> None:
        """Tear the orb overlay down at runtime (live display-style swap).

        Clears ``_running`` so the after-loops (``_schedule_frame`` /
        ``_schedule_ui_queue`` / ``_schedule_position_recheck``) all stop
        rescheduling on their next tick, then destroys the control row and the
        root on the Tk thread. Fully guarded so a teardown hiccup never
        propagates.
        """
        self._running = False
        root = self._root
        if root is None:
            return

        def _teardown() -> None:
            try:
                row = self._controls
                self._controls = None
                if row is not None:
                    row.destroy()
            except Exception:  # noqa: BLE001 — teardown must reach root.destroy
                logging.getLogger("jarvis.orb").debug(
                    "orb control row teardown failed", exc_info=True
                )
            try:
                root.destroy()
            except Exception:  # noqa: BLE001 — the process may be exiting anyway
                logging.getLogger("jarvis.orb").debug("orb root destroy failed", exc_info=True)

        try:
            root.after(0, _teardown)
        except Exception:  # noqa: BLE001 — a dead interpreter has nothing to tear down
            logging.getLogger("jarvis.orb").debug("orb teardown scheduling failed", exc_info=True)

    def _cancel_pending_hide(self) -> None:
        if self._pending_hide_after_id is not None and self._root is not None:
            try:
                self._root.after_cancel(self._pending_hide_after_id)
            except tk.TclError:
                pass
            self._pending_hide_after_id = None

    # --- Surface methods the voice orb answers without a picture -----------
    #
    # The bridge drives every overlay surface through one vocabulary. The
    # voice orb carries its whole state in how the sphere moves (maintainer,
    # 2026-08-06): it swells on the voice and its colours churn while it
    # thinks, so it shows no speech bubble and plays no figure animations.

    def show_comment(self, text: str, duration_ms: int = 3500) -> None:
        """No speech bubble on the voice orb."""

    def show_listening_transcript(self, text: str = "", duration_ms: int = 30000) -> None:
        """No transcript bubble on the voice orb."""

    def hide_comment(self) -> None:
        """Nothing to hide: the voice orb shows no bubble."""

    def start_mouth_animation(self, duration_ms: int = 60000) -> None:
        """The voice orb has no mouth; its sphere follows the voice level."""

    def stop_mouth_animation(self) -> None:
        """The voice orb has no mouth."""

    def play_animation(self, name: str, **params: Any) -> None:
        """The voice orb plays no named figure animations."""

    def stop_animation(self, name: str) -> None:
        """The voice orb plays no named figure animations."""

    def clear_animations(self) -> None:
        """The voice orb plays no named figure animations."""

    def active_animations(self) -> list[str]:
        """Always empty: the voice orb plays no named figure animations."""
        return []

    def set_speaker_muted(self, muted: bool) -> None:
        """Mirror the assistant-voice mute on the speaker disc. Thread-safe."""
        self._speaker_muted = bool(muted)

        def _apply() -> None:
            row = self._controls
            if row is not None:
                row.set_state(speaker_muted=self._speaker_muted)

        self._enqueue_ui(_apply)

    def set_mode(self, mode: str) -> None:
        """Repaint the orb in ``mode`` without touching visibility.

        Validated synchronously for the same reason as :meth:`show` — see there.
        """
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode!r} (allowed: {', '.join(MODES)})")
        self._enqueue_ui(lambda: self._set_mode(mode))

    def set_level(self, level: float) -> None:
        # A plain attribute write from the audio threads (atomic under the
        # GIL); the Tk thread reads it on its next frame tick.
        self._ext_level = max(0.0, min(1.0, float(level)))

    def set_style(self, style: str) -> None:
        """Keep the voice orb: it is the only look this window has.

        Kept for the shared surface vocabulary (a live style swap calls it);
        every value resolves to ``voice_orb``.
        """
        self._style = _coerce_style(style)

    def _build_renderer(self) -> VoiceOrbRenderer | None:
        try:
            return VoiceOrbRenderer(
                size=self._win_w,
                color_key=(int(COLOR_KEY_RGB[0]), int(COLOR_KEY_RGB[1]), int(COLOR_KEY_RGB[2])),
            )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("jarvis.orb").warning(
                "VoiceOrbRenderer init failed (%s); overlay will stay hidden.", exc
            )
            return None

    # --- Internal --------------------------------------------------------

    def _set_mode(self, mode: str) -> None:
        """Apply ``mode`` on the Tk thread. The public entry points already
        validated it; this stays a guard for the internal call sites."""
        if mode not in MODES:
            raise ValueError(f"Unknown mode: {mode!r} (allowed: {', '.join(MODES)})")
        changed = mode != self._mode
        self._mode = mode
        if changed:
            self._sync_controls_visibility()

    def _enqueue_ui(self, fn) -> None:
        """Queue UI work for the Tk thread.

        Direct ``root.after`` calls from the backend asyncio thread are
        unreliable on Windows and can raise ``RuntimeError: main thread is not
        in main loop``. The Tk event loop drains this queue itself.
        """
        if self._root is None:
            return
        if self._tk_thread_id == threading.get_ident():
            fn()
            return
        self._ui_queue.put(fn)

    def _schedule_ui_queue(self) -> None:
        if not self._running or self._root is None:
            return
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001
                logging.getLogger("jarvis.orb").exception("Orb UI command failed")
        self._root.after(20, self._schedule_ui_queue)

    # --- Thread lifecycle for integration into async/asyncio worlds -----

    def start_in_thread(self, auto_demo: bool = False, timeout: float = 3.0) -> None:
        """Starts the Tk mainloop on a daemon thread and returns.

        On Windows, Tk is stable on a background thread as long as all UI
        mutations are queued — show/hide/set_mode/set_level already do this.

        On macOS this is a logged no-op: Aqua-Tk (like AppKit) is
        main-thread-only, and a Tk root on a worker thread aborts the whole
        process natively (BUG-057, same class as the BUG-056 tray).

        Blocks until the window actually exists (self._started event),
        so the caller can safely call show()/hide() afterward without
        running into a None root.
        """
        _log = logging.getLogger("jarvis.orb")

        if sys.platform == "darwin":
            _log.info(
                "Orb overlay not started: macOS allows Tk windows on the "
                "main thread only — running without the on-screen orb."
            )
            return

        def _run():
            try:
                self.start(auto_demo=auto_demo)
            except Exception as exc:  # noqa: BLE001
                # pythonw.exe has no stdout → print goes nowhere. The logger
                # writes to the watchdog log and makes silent deaths visible.
                _log.exception("Orb thread start failed: %s", exc)

        t = threading.Thread(target=_run, name="orb-tk-mainloop", daemon=True)
        t.start()
        ok = self._started.wait(timeout=timeout)
        if not ok:
            _log.error(
                "Orb window not initialized within %.1fs — UI will not pop up.",
                timeout,
            )
        else:
            _log.info("Orb overlay Tk mainloop is running (window initialized).")

    def _schedule_frame(self) -> None:
        """One frame tick. Re-arms itself; ONE pending tick exists at most.

        Two rules on top of painting. A withdrawn window gets no ticks at all
        (nothing is on screen to animate); every path that maps the window
        restarts the loop through :meth:`_ensure_frame_loop`. And one failing
        frame never ends the animation: the re-arm sits in a ``finally``.
        """
        self._frame_after_id = None
        if not self._running or not self._root or not self._canvas or not self._renderer:
            return
        if not self._window_mapped():
            return
        try:
            self._paint_frame()
        except Exception:  # noqa: BLE001 — logged once; the loop must survive a bad frame
            if not self._frame_error_logged:
                self._frame_error_logged = True
                logging.getLogger("jarvis.orb").exception("orb frame failed; animation continues")
        finally:
            self._arm_frame(FRAME_INTERVAL_MS)

    def _paint_frame(self) -> None:
        """Paint the frame due now."""
        renderer = self._renderer
        t = time.perf_counter() - self._t0
        img = renderer.render(t, self._mode, self._ext_level)
        if self._mac_transparent:
            # macOS has no color key — the frame carries a real alpha
            # channel instead (magenta → fully transparent).
            img = key_to_alpha(img)
            if self._present_native(img):
                return

        # The PhotoImage must be kept as self._photo — otherwise Tkinter
        # garbage-collects the image before it gets rendered.  It must also be
        # created in this root's Tcl interpreter: the macOS companion process
        # keeps a separate bootstrap Tk root alive to initialize NSApp, so an
        # unqualified PhotoImage lands in that other interpreter and the
        # canvas reports ``image \"pyimageN\" does not exist``.
        self._photo = ImageTk.PhotoImage(img, master=self._root)
        self._show_photo(self._photo)

    def _present_native(self, image: Image.Image) -> bool:
        """Show ``image`` through the macOS native layer. False: use the Tk canvas."""
        if not self._mac_transparent or self._root is None:
            return False
        if self._presenter is None:
            self._presenter = MacLayerPresenter(self._root, name="voice orb")
        return self._presenter.present(image)

    def _show_photo(self, photo: Any) -> None:
        if self._image_id is None:
            self._image_id = self._canvas.create_image(0, 0, anchor="nw", image=photo)
        else:
            self._canvas.itemconfig(self._image_id, image=photo)

    def _arm_frame(self, delay_ms: int) -> None:
        root = self._root
        if root is None or not self._running:
            return
        try:
            self._frame_after_id = root.after(max(1, int(delay_ms)), self._schedule_frame)
        except (tk.TclError, RuntimeError):
            logging.getLogger("jarvis.orb").debug("orb frame re-arm failed", exc_info=True)

    def _kick_frame(self) -> None:
        """Repaint right away, replacing the pending tick."""
        root = self._root
        if root is None or not self._running:
            return
        pending = self._frame_after_id
        self._frame_after_id = None
        if pending is not None:
            try:
                root.after_cancel(pending)
            except tk.TclError:
                logging.getLogger("jarvis.orb").debug("frame tick cancel failed", exc_info=True)
        self._arm_frame(1)

    def _ensure_frame_loop(self) -> None:
        """Restart the frame loop after the window was mapped again."""
        if self._frame_after_id is None:
            self._kick_frame()

    def _window_mapped(self) -> bool:
        """Is the orb window mapped (not withdrawn)? Test doubles count as mapped."""
        root = self._root
        if root is None:
            return False
        try:
            return str(root.state()) != "withdrawn"
        except (tk.TclError, AttributeError):
            return True

    def _run_demo(self) -> None:
        self._started.wait(timeout=5.0)
        time.sleep(0.5)

        self.show(mode="listen")
        time.sleep(8.0)

        self.set_mode("speak")
        time.sleep(5.0)

        self.hide()
        time.sleep(1.5)

        self.show(mode="listen")
        time.sleep(4.0)
        self.hide()


def main() -> int:
    parser = argparse.ArgumentParser(description="Dodaios voice orb overlay")
    parser.add_argument(
        "--sticky",
        action="store_true",
        help="Window permanently visible (design preview)",
    )
    parser.add_argument(
        "--mic",
        action="store_true",
        help="Mic-reactive: the sphere follows the microphone volume",
    )
    args = parser.parse_args()
    sticky = args.sticky or args.mic
    overlay = OrbOverlay(sticky=sticky, mic_reactive=args.mic)
    # No auto demo with --mic (otherwise the demo script would hide the orb
    # exactly while the user is speaking into the mic).
    overlay.start(auto_demo=not sticky)
    return 0


if __name__ == "__main__":
    sys.exit(main())
