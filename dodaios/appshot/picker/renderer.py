"""PySide6 area picker for region appshots.

Runs ONLY inside ``python -m dodaios.appshot.picker``; the main process never
imports this module (AP-26). One frameless, always-on-top window per screen:

- **Frozen screen.** Each screen is grabbed once before the overlay appears
  and shown under a light dim, so nothing moves under the selection. Where the
  grab fails (no permission, odd platform) a translucent dim layer over the
  live desktop stands in.
- **Crosshair.** The pointer is a thin crosshair with a small ring in the
  middle; beside it, two small numbers — the position before the drag, the
  width and height while dragging. No lens, no labels in boxes, no banner.
- **Window snapping.** Hovering lifts the window under the pointer out of the
  dim (rectangles from the main process, top-most first); a click without a
  drag takes exactly that window.
- **Drag to select.** The screen around the selection
  clears and the selected area itself turns a translucent grey, with one thin
  border.

This module holds that plain area chooser (:class:`_SelectWindow`, which the
screen recorder uses as it is) and the process around the windows
(:class:`Picker`). The appshot's windows add the marking toolbar on top
(:mod:`dodaios.appshot.picker.markup_window`): it is up from the start, the
screen can be marked before the area is chosen, and releasing the area drag
takes the appshot at once.

Only the parts that change are repainted, so the numbers follow the pointer
without dragging a full 4K repaint behind them. Esc or a right-click cancels.
The result is reported as fractions of its screen, so mixed-DPI layouts map
back to capture pixels exactly (see :mod:`dodaios.appshot.region`).
"""

from __future__ import annotations

import sys
import threading
from contextlib import suppress
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from dodaios.appshot import picker as wire

if TYPE_CHECKING:
    from dodaios.appshot.picker.elements import ElementScanner
from dodaios.appshot.region import (
    grab_preview,
    match_monitor,
    selection_fractions,
    snap_targets_on_screen,
)

#: A light veil before the drag (the picker is armed). While dragging the
#: veil lifts and the selection itself takes a neutral grey tint instead, so
#: the chosen area reads as "marked" on light and dark content alike.
DIM_IDLE = QColor(0, 0, 0, 55)
SELECTION_TINT = QColor(128, 128, 132, 105)
#: The selection border: a white hairline with a faint dark edge outside it,
#: so it reads on light and dark content alike.
_BORDER = QColor(255, 255, 255, 235)
_BORDER_EDGE = QColor(0, 0, 0, 70)

#: The numbers beside the crosshair: dark ink with a white halo.
INK = QColor(20, 20, 22)
HALO = QColor(255, 255, 255, 235)
_NUMBER_PT = 8.5
#: Offset of the numbers from the crosshair centre, and the screen-edge gap.
_NUMBER_OFFSET = QPointF(12.0, 10.0)
EDGE_GAP = 4.0

#: Crosshair cursor geometry (logical px): arm length, ring radius.
_CROSS_ARM = 11
_CROSS_RING = 3.5

#: Windows smaller than this (logical px, either side) are not snap targets.
_MIN_SNAP_PX = 24


def _screen_info(screen) -> dict[str, float]:
    g = screen.geometry()
    return {
        "x": float(g.x()),
        "y": float(g.y()),
        "w": float(g.width()),
        "h": float(g.height()),
        "dpr": float(screen.devicePixelRatio() or 1.0),
    }


def _emit(payload: dict) -> None:
    # A failed write means the parent is gone; exiting is all that is left.
    with suppress(Exception):
        sys.stdout.write(wire.encode(payload))
        sys.stdout.flush()


def _claim_keyboard(window: QWidget) -> None:
    """Windows: take the keyboard, so the toolbar's keys work before the first click.

    Windows keeps the foreground with the app the user was in when a
    background process asks for it; the overlay would then stay deaf to
    Space, Tab and the tool letters until it is clicked once. The shared,
    hardened foreground path (:mod:`dodaios.platform.window_state`) takes it.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # noqa: PLC0415

        hwnd = int(window.winId())
        if int(ctypes.windll.user32.GetForegroundWindow() or 0) == hwnd:
            return
        from dodaios.platform.window_state import _force_foreground_windows  # noqa: PLC0415

        _force_foreground_windows(hwnd)
    except Exception as exc:  # noqa: BLE001 - a click still hands the keyboard over
        sys.stderr.write(f"appshot-picker: could not take the keyboard ({exc!r}).\n")


def number_font() -> QFont:
    font = QFont()
    font.setPointSizeF(_NUMBER_PT)
    font.setWeight(QFont.Weight.DemiBold)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    return font


def crosshair_cursor(dpr: float) -> QCursor:
    """The crosshair: two thin arms with a ring at the centre.

    Drawn by the OS as the real cursor (no lag behind the mouse), at the
    screen's pixel density, black on a white halo so it reads everywhere.
    """
    arm = _CROSS_ARM
    side = arm * 2 + 3
    scale = max(1.0, float(dpr))
    pixmap = QPixmap(round(side * scale), round(side * scale))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = side / 2.0
    gap = _CROSS_RING + 1.5
    segments = (
        (QPointF(c - arm, c), QPointF(c - gap, c)),
        (QPointF(c + gap, c), QPointF(c + arm, c)),
        (QPointF(c, c - arm), QPointF(c, c - gap)),
        (QPointF(c, c + gap), QPointF(c, c + arm)),
    )
    for colour, width in ((HALO, 3.0), (INK, 1.1)):
        pen = QPen(colour, width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for a, b in segments:
            painter.drawLine(a, b)
        painter.drawEllipse(QPointF(c, c), _CROSS_RING, _CROSS_RING)
    painter.end()
    hot = round(c)
    return QCursor(pixmap, hot, hot)


class _SelectWindow(QWidget):
    """One screen's selection canvas: drag an area or click a window."""

    def __init__(self, screen, frozen: QPixmap | None, owner: Picker) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if frozen is None:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if sys.platform == "darwin":
            # Qt::Tool is an NSPanel on macOS; without this it stays invisible
            # while this never-activated process is in the background.
            always_show = getattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow", None)
            if always_show is not None:
                self.setAttribute(always_show)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setCursor(crosshair_cursor(screen.devicePixelRatio() or 1.0))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.screen_ref = screen
        self._frozen = frozen
        self._owner = owner
        self._start: QPointF | None = None
        self._end: QPointF | None = None
        self._pointer: QPointF | None = None
        #: Snap targets in this window's logical coordinates, top-most first,
        #: and the window handle behind each (``0`` = unknown).
        self._snaps: list[QRectF] = []
        self._snap_handles: list[int] = []
        self._monitors: list[dict] = []
        self._monitor: dict | None = None
        self._font = number_font()
        self._metrics = QFontMetricsF(self._font)
        #: What was painted last, so the next move repaints only what changed.
        self._painted_numbers: QRectF | None = None
        self._painted_hole: QRectF | None = None
        self._cross = crosshair_cursor(screen.devicePixelRatio() or 1.0)

    def release_capture(self) -> None:
        """Drop the frozen frame's pixels explicitly."""
        self._frozen = None

    # -- the toolbar hooks (the appshot window has a toolbar; this one not) --
    def arm(self) -> None:
        """The pointer is on this screen: show what belongs to it."""

    def disarm(self) -> None:
        """The pointer left for another screen."""

    def adopt(self, other: _SelectWindow) -> None:
        """Carry over choices made on ``other`` (the screen the pointer left)."""

    def ask_parts_under_cursor(self) -> None:
        """Snapping to the parts of a window belongs to the appshot window."""

    def add_parts(self, handle: int, rects: list) -> None:
        """The parts of window ``handle`` arrived; this window takes whole windows."""

    # -- data from the main process ------------------------------------------
    def set_layout(
        self, monitors: list[dict], windows: list[list[int]], handles: list | None = None
    ) -> None:
        """Map capture-space window rects onto this screen's logical pixels."""
        info = _screen_info(self.screen_ref)
        self._monitors = monitors
        self._monitor = match_monitor(info, monitors)
        targets = snap_targets_on_screen(
            info, (self.width(), self.height()), monitors, windows, min_px=_MIN_SNAP_PX
        )
        handles = handles if isinstance(handles, list) else []
        self._snaps = [QRectF(*rect) for _index, rect in targets]
        self._snap_handles = [
            handles[index] if index < len(handles) and isinstance(handles[index], int) else 0
            for index, _rect in targets
        ]
        self.update()

    # -- input ---------------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            self._owner.finish(None, None)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._owner.finish(None, None)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position()
            self._end = event.position()
            self._owner.focus_on(self)
            # The veil lifts for the drag: one full repaint.
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._pointer = event.position()
        if self._start is not None:
            self._end = event.position()
        self._owner.focus_on(self)
        self._repaint_changes()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        frac = self._take_drag(event.position())
        if frac is None:
            self.update()
            return
        self.area_chosen(frac)

    def _take_drag(self, end: QPointF) -> tuple[float, float, float, float] | None:
        """End the drag at ``end``: its area, or the window under a plain click."""
        start = self._start
        self._start = None
        self._end = None
        if start is None:
            return None
        frac = selection_fractions(
            start.x(), start.y(), end.x(), end.y(), self.width(), self.height()
        )
        if frac is None:
            # A click, not a drag: take the window under the pointer, if any.
            snap = self._snap_at(end)
            if snap is not None:
                frac = (
                    snap.x() / self.width(),
                    snap.y() / self.height(),
                    snap.width() / self.width(),
                    snap.height() / self.height(),
                )
        return frac

    def area_chosen(self, frac: tuple[float, float, float, float]) -> None:
        """An area is chosen: report it."""
        self._owner.finish(self, frac)

    def clear_pointer(self) -> None:
        if self._pointer is not None or self._start is not None:
            self._pointer = None
            self._start = None
            self._end = None
            self.update()

    # -- geometry ------------------------------------------------------------
    def _selection(self) -> QRectF | None:
        if self._start is None or self._end is None:
            return None
        return QRectF(self._start, self._end).normalized()

    def _snap_at(self, point: QPointF) -> QRectF | None:
        for rect in self._snaps:
            if rect.contains(point):
                return rect
        return None

    def _hole(self) -> QRectF | None:
        sel = self._selection()
        if sel is not None:
            return sel
        if self._pointer is not None:
            return self._snap_at(self._pointer)
        return None

    def _scale(self) -> float:
        """Device pixels per logical pixel — from the frozen frame when present."""
        if self._frozen is not None and self.width() > 0:
            return self._frozen.width() / self.width()
        return float(self.screen_ref.devicePixelRatio() or 1.0)

    def _capture_point(self, point: QPointF) -> tuple[int, int]:
        """``point`` in capture coordinates (what the screenshot will use)."""
        mon = self._monitor
        if mon is None:
            scale = self._scale()
            return round(point.x() * scale), round(point.y() * scale)
        fx = point.x() / max(1.0, self.width())
        fy = point.y() / max(1.0, self.height())
        return (
            round(float(mon.get("left", 0)) + fx * float(mon.get("width", 0))),
            round(float(mon.get("top", 0)) + fy * float(mon.get("height", 0))),
        )

    def _numbers(self) -> tuple[str, str] | None:
        """The two stacked numbers: position, or width and height while dragging."""
        sel = self._selection()
        if sel is not None:
            scale = self._scale()
            return str(round(sel.width() * scale)), str(round(sel.height() * scale))
        if self._pointer is None:
            return None
        x, y = self._capture_point(self._pointer)
        return str(x), str(y)

    def _numbers_rect(self) -> QRectF | None:
        """Where the numbers go: below-right of the crosshair, flipped at edges."""
        point = self._end if self._end is not None else self._pointer
        numbers = self._numbers()
        if point is None or numbers is None:
            return None
        w = max(self._metrics.horizontalAdvance(n) for n in numbers) + 4.0
        line = self._metrics.height()
        h = line * 2 + 2.0
        x = point.x() + _NUMBER_OFFSET.x()
        y = point.y() + _NUMBER_OFFSET.y()
        if x + w > self.width() - EDGE_GAP:
            x = point.x() - _NUMBER_OFFSET.x() - w
        if y + h > self.height() - EDGE_GAP:
            y = point.y() - _NUMBER_OFFSET.y() - h
        return QRectF(round(x), round(y), round(w), round(h))

    def _repaint_changes(self) -> None:
        """Repaint the old and new numbers, and the hole only when it changed."""
        numbers = self._numbers_rect()
        hole = self._hole()
        dirty = QRectF()
        for part in (numbers, self._painted_numbers):
            if part is not None:
                dirty = dirty.united(part.adjusted(-3, -3, 3, 3))
        if hole != self._painted_hole:
            for part in (hole, self._painted_hole):
                if part is not None:
                    dirty = dirty.united(part.adjusted(-3, -3, 3, 3))
        self._painted_numbers = numbers
        self._painted_hole = hole
        if not dirty.isEmpty():
            self.update(dirty.toAlignedRect())

    # -- painting ------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        full = QRectF(0, 0, self.width(), self.height())
        if self._frozen is not None:
            painter.drawPixmap(full, self._frozen, QRectF(self._frozen.rect()))
        hole = self._hole()
        self._paint_veil(painter, full, hole)
        if hole is not None:
            self._paint_border(painter, hole)
        self._paint_numbers(painter)
        painter.end()

    def _paint_veil(self, painter: QPainter, full: QRectF, hole: QRectF | None) -> None:
        """Dim the screen around the hole; while dragging, tint the hole instead."""
        if self._selection() is not None and hole is not None:
            # Dragging: the surroundings stay clear, the selection turns grey.
            painter.fillRect(hole, SELECTION_TINT)
            return
        dim = QPainterPath()
        dim.addRect(full)
        if hole is not None:
            cut = QPainterPath()
            cut.addRect(hole)
            dim = dim.subtracted(cut)
        painter.fillPath(dim, DIM_IDLE)

    def _paint_border(self, painter: QPainter, rect: QRectF) -> None:
        # Drawn without antialiasing so both hairlines land on whole pixels.
        r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_BORDER_EDGE, 1.0))
        painter.drawRect(r.adjusted(-1.0, -1.0, 1.0, 1.0))
        painter.setPen(QPen(_BORDER, 1.0))
        painter.drawRect(r)

    def _paint_numbers(self, painter: QPainter) -> None:
        numbers = self._numbers()
        box = self._numbers_rect()
        if numbers is None or box is None:
            return
        line = self._metrics.height()
        ascent = self._metrics.ascent()
        path = QPainterPath()
        for i, text in enumerate(numbers):
            # Right-aligned in their column.
            x = box.right() - 2.0 - self._metrics.horizontalAdvance(text)
            path.addText(QPointF(x, box.top() + 1.0 + ascent + i * line), self._font, text)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        halo = QPen(HALO, 2.6)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(path, halo)
        painter.fillPath(path, INK)
        painter.restore()


class Picker(QObject):
    """Owns the per-screen windows and reports exactly one result."""

    def __init__(
        self, app: QApplication, *, language: str = "en", resident: bool = False
    ) -> None:
        super().__init__()
        self._app = app
        self.language = language
        self._resident = resident
        self._started = False
        self._windows: list[_SelectWindow] = []
        self._focused: _SelectWindow | None = None
        #: The window being marked up; the others stay inert until it is clear.
        self.marking: _SelectWindow | None = None
        #: "Adjust the area before taking it": a released area stays to be
        #: resized and marked, instead of being taken at once.
        self.keep_area = False
        self._marking_sent = False
        self._done = False
        #: Reads the parts of the window under the pointer (Windows); made on
        #: the first pick, then kept warm with the rest of the runtime.
        self._parts: ElementScanner | None = None
        self._parts_asked: set[int] = set()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._done = False
        self._marking_sent = False
        self._parts_asked = set()
        if self._parts is not None:
            self._parts.reset()
        screens = QGuiApplication.screens()
        # Freeze every screen BEFORE any overlay window exists.
        frozen = {id(s): self._grab(s) for s in screens}
        self._windows = [self.make_window(s, frozen[id(s)]) for s in screens]
        cursor_screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._focused = next(
            (w for w in self._windows if w.screen_ref is cursor_screen),
            self._windows[0] if self._windows else None,
        )
        for win in self._windows:
            win.show()
        if self._focused is not None:
            self._focused.arm()
            self._focused.raise_()
            self._focused.activateWindow()
            self._focused.setFocus()
            _claim_keyboard(self._focused)
        self._app.processEvents()
        _emit({"event": wire.EVENT_READY})

    def make_window(self, screen, frozen: QPixmap | None) -> _SelectWindow:
        """The appshot's window; capture modes provide their own."""
        from dodaios.appshot.picker.markup_window import MarkupWindow  # noqa: PLC0415

        return MarkupWindow(screen, frozen, self)

    @staticmethod
    def _grab(screen) -> QPixmap | None:
        return grab_preview(screen)

    def set_layout(
        self, monitors: list[dict], windows: list[list[int]], handles: list | None = None
    ) -> None:
        for win in self._windows:
            win.set_layout(monitors, windows, handles)
        if self._focused is not None:
            # The window under the pointer is the likeliest target: read it now.
            self._focused.ask_parts_under_cursor()

    def want_parts(self, handle: int) -> None:
        """The pointer is over window ``handle``: read its parts, once per pick."""
        if not handle or handle in self._parts_asked or not self._started:
            return
        self._parts_asked.add(handle)
        if self._parts is None:
            if sys.platform != "win32":
                return
            from dodaios.appshot.picker.elements import ElementScanner  # noqa: PLC0415

            self._parts = ElementScanner()
            self._parts.found.connect(self._parts_found)
        self._parts.request(handle)

    @Slot(object, object)
    def _parts_found(self, handle: object, rects: object) -> None:
        if not self._started or not isinstance(handle, int) or not isinstance(rects, list):
            return
        for win in self._windows:
            win.add_parts(handle, rects)

    def focus_on(self, window: _SelectWindow) -> None:
        """The pointer moved onto ``window``: only that screen shows the numbers."""
        if self._focused is window or self.marking is not None:
            return
        previous = self._focused
        for other in self._windows:
            if other is not window:
                other.clear_pointer()
        self._focused = window
        if previous is not None:
            previous.disarm()
            window.adopt(previous)
        window.arm()

    def lock(self, window: _SelectWindow) -> None:
        """``window`` holds markings: the toolbar stays there, keys go there."""
        if self.marking is window:
            return
        self.marking = window
        self._focused = window
        for other in self._windows:
            if other is not window:
                other.clear_pointer()
                other.disarm()
        window.raise_()
        window.activateWindow()
        window.setFocus()
        if not self._marking_sent:
            self._marking_sent = True
            # The parent drops its global Esc now: Esc may end a text box here.
            _emit({"event": wire.EVENT_MARKING})

    def unlock(self, window: _SelectWindow) -> None:
        """``window`` holds nothing any more: the toolbar may follow the pointer."""
        if self.marking is window:
            self.marking = None

    def set_keep_area(self, keep: bool) -> None:
        """The user flipped "adjust before taking"; the parent remembers it."""
        self.keep_area = bool(keep)
        _emit({"event": wire.EVENT_OPTION, "keep_area": self.keep_area})

    def finish(
        self,
        window: _SelectWindow | None,
        frac,
        *,
        action: str = "done",
        markup: dict | None = None,
    ) -> None:
        if self._done:
            return
        self._done = True
        info = _screen_info(window.screen_ref) if window is not None else None
        for win in self._windows:
            win.hide()
        # The overlay must be off the glass before the parent grabs.
        self._app.processEvents()
        # Keep only the GUI runtime warm. Bound Qt callbacks can outlive the
        # native widget until GC, so explicitly release its pixels first.
        for win in self._windows:
            win.release_capture()
            win.close()
            win.deleteLater()
        self._windows.clear()
        self._focused = None
        self.marking = None
        self._started = False
        if self._parts is not None:
            self._parts.reset()
        if info is None or frac is None:
            _emit({"event": wire.EVENT_SELECTION, "cancelled": True})
        else:
            payload: dict = {
                "event": wire.EVENT_SELECTION,
                "screen": info,
                "rect": list(frac),
                "action": action,
            }
            if markup is not None:
                payload["markup"] = markup
            _emit(payload)
        if not self._resident:
            self._app.quit()

    @Slot(str)
    def on_line(self, raw: str) -> None:
        payload = wire.decode(raw)
        if payload is None:
            return
        cmd = payload.get("cmd")
        if cmd == wire.CMD_START and self._resident and not self._started:
            self.language = str(payload.get("language") or "en")
            self.keep_area = payload.get("keep_area") is True
            self.start()
            self.set_layout(
                payload.get("monitors", []), payload.get("windows", []), payload.get("handles")
            )
        elif cmd == wire.CMD_QUIT:
            self.on_eof()
        elif cmd == wire.CMD_CANCEL and self._started:
            self.finish(None, None)
        elif cmd == wire.CMD_LAYOUT:
            monitors = payload.get("monitors")
            windows = payload.get("windows")
            if isinstance(monitors, list) and isinstance(windows, list):
                self.set_layout(
                    [m for m in monitors if isinstance(m, dict)], windows, payload.get("handles")
                )

    @Slot()
    def on_eof(self) -> None:
        if self._started:
            self.finish(None, None)
        if self._parts is not None:
            self._parts.stop()
        self._app.quit()


class _StdinPump(QObject):
    """Reads stdin on a daemon thread; signals deliver to the Qt thread."""

    line = Signal(str)
    eof = Signal()

    def start(self) -> None:
        threading.Thread(target=self._run, name="appshot-picker-stdin", daemon=True).start()

    def _run(self) -> None:
        # A dying pipe simply means "parent gone" — treated as EOF.
        with suppress(Exception):
            for raw in sys.stdin:
                self.line.emit(raw)
        self.eof.emit()


def run(language: str = "en", *, resident: bool = False) -> int:
    """Picker main loop. Returns the process exit code."""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    try:
        app = QApplication(sys.argv[:1] or ["appshot-picker"])
    except Exception as exc:  # noqa: BLE001 - no display / no platform plugin
        sys.stderr.write(f"appshot-picker: no usable display ({exc!r}).\n")
        return wire.EXIT_NO_GUI
    from dodaios.platform.qt_sidecar import hide_from_dock

    hide_from_dock()  # macOS: no "Python" Dock icon for the resident picker
    app.setQuitOnLastWindowClosed(False)
    if not QGuiApplication.screens():
        return wire.EXIT_NO_GUI
    picker = Picker(app, language=language, resident=resident)
    pump = _StdinPump()
    pump.line.connect(picker.on_line, Qt.ConnectionType.QueuedConnection)
    pump.eof.connect(picker.on_eof, Qt.ConnectionType.QueuedConnection)
    if resident:
        # Import/initialize Qt without taking pixels, creating windows or
        # stealing focus. The next start command samples the current desktop.
        _emit({"event": wire.EVENT_STANDBY})
    else:
        picker.start()
    pump.start()
    return app.exec()


__all__ = ["Picker", "crosshair_cursor", "number_font", "run"]
