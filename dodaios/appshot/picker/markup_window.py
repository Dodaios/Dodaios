"""The appshot picker's screen window: toolbar up front, mark first, take on release.

Runs ONLY inside ``python -m dodaios.appshot.picker`` (PySide6, AP-26).

- The overlay opens with the marking toolbar centred at the top of the
  screen under the pointer, and the **area** tool chosen. Dragging an area,
  or clicking a window, takes the appshot the moment the mouse is released:
  there is no second step to confirm it.
- Hovering offers the parts of the window under the pointer too: a panel,
  a list, a field, a button (:mod:`dodaios.appshot.picker.elements`). The
  smallest part under the pointer lights up; the mouse wheel steps out to
  the larger parts around it and the whole window, and back in. A click
  takes what is lit.
- Any drawing tool can be picked first (its button, its letter, Tab or the
  middle mouse button) and used anywhere on the frozen screen. Back on the
  area tool, the area drag then takes the appshot with every marking in it.
- Space takes the whole screen with its markings; so do Enter, Ctrl+C / S / E
  and the finishing buttons while no area is kept.
- With "adjust before taking" switched on, a released area stays with its
  resize handles instead: it is marked up, resized and moved, and Enter, a
  double-click in it or the check button takes it. The parent remembers the
  switch (``[appshot].region_keep_area``).
- Esc, or a right-click on nothing, closes the overlay; a right-click on a
  marking removes it.

The marking rules live in :mod:`dodaios.appshot.picker.markup_model`, the
painting and the toolbar in :mod:`dodaios.appshot.picker.annotate`.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen

from dodaios.appshot import picker as wire
from dodaios.appshot.picker import annotate
from dodaios.appshot.picker import markup_model as mm
from dodaios.appshot.picker.renderer import EDGE_GAP, HALO, INK, _screen_info, _SelectWindow
from dodaios.appshot.region import snap_targets_on_screen

#: Cursor per kept-area resize handle.
_HANDLE_CURSORS = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "w": Qt.CursorShape.SizeHorCursor,
}
#: Cursor per marking grip kind (:func:`markup_model.grip_cursor`).
_GRIP_CURSORS = {
    "fdiag": Qt.CursorShape.SizeFDiagCursor,
    "bdiag": Qt.CursorShape.SizeBDiagCursor,
    "hor": Qt.CursorShape.SizeHorCursor,
    "grab": Qt.CursorShape.OpenHandCursor,
}
#: Arrow keys nudge the selected marking.
_NUDGE = {
    Qt.Key.Key_Left: (-1.0, 0.0),
    Qt.Key.Key_Right: (1.0, 0.0),
    Qt.Key.Key_Up: (0.0, -1.0),
    Qt.Key.Key_Down: (0.0, 1.0),
}
#: Keyboard shortcuts for the toolbar's actions (with Ctrl / Cmd).
_ACTION_KEYS = {
    Qt.Key.Key_C: wire.ACTION_COPY,
    Qt.Key.Key_S: wire.ACTION_SAVE,
    Qt.Key.Key_E: wire.ACTION_EDIT,
}
#: Extra room around a marking being drawn or dragged, so its arrow head,
#: shadow, grips and dashed frame repaint with it (logical px, plus widths).
_LIVE_PAD = 24.0
_LIVE_PAD_PER_WIDTH = 6.0


class _MarkupState:
    """Everything one screen window holds: the markings, the kept area, the tool."""

    def __init__(self) -> None:
        #: The kept area (logical px), with "adjust before taking" on; ``None``
        #: while no area is chosen.
        self.sel: QRectF | None = None
        self.shapes: list[mm.Shape] = []
        self.history = mm.History()
        self.tool = mm.AREA
        #: Where Tab and the middle button go from the area tool.
        self.last_drawing = mm.ARROW
        self.color = mm.PALETTE[0]
        self.width_index = mm.DEFAULT_WIDTH_INDEX
        self.arrow_style = mm.ARROW_STYLES[0]
        self.text_style = mm.TEXT_STYLES[0]
        self.redact_mode = mm.REDACT_MODES[0]
        #: The background frame (preset, padding, radius, shadow), or ``None``.
        self.background: dict | None = None
        #: The marking being dragged out right now.
        self.drawing: mm.Shape | None = None
        #: The text being typed (not in ``shapes`` while open); where an edited
        #: text came from, and how it was, so Esc can put it back.
        self.typing: mm.Shape | None = None
        self.typing_index: int | None = None
        self.typing_original: mm.Shape | None = None
        #: Index into ``shapes`` of the selected marking (grips shown).
        self.selected: int | None = None
        #: ``("area", handle)`` / ``("area-move", None)`` / ``("grip", grip)``
        #: / ``("move", None)``.
        self.drag: tuple[str, str | None] | None = None
        #: The selected marking as it was when a grip drag began.
        self.original: mm.Shape | None = None
        self.last: QPointF | None = None
        self.moved = False

    #: The choices that follow the pointer from one screen to the next.
    STYLE = (
        "tool",
        "last_drawing",
        "color",
        "width_index",
        "arrow_style",
        "text_style",
        "redact_mode",
        "background",
    )

    @property
    def width(self) -> float:
        return mm.WIDTHS[self.width_index]

    @property
    def engaged(self) -> bool:
        """Anything on this screen that moving to another one would lose."""
        return bool(
            self.shapes
            or self.sel is not None
            or self.typing is not None
            or self.drawing is not None
        )

    def box(self) -> mm.Box:
        sel = self.sel
        assert sel is not None
        return (sel.x(), sel.y(), sel.width(), sel.height())

    def selected_shape(self) -> mm.Shape | None:
        if self.selected is None or not 0 <= self.selected < len(self.shapes):
            return None
        return self.shapes[self.selected]


def _box(rect: QRectF) -> mm.Box:
    return (rect.x(), rect.y(), rect.width(), rect.height())


class MarkupWindow(_SelectWindow):
    """One screen of the appshot picker: choose an area and mark it, in any order."""

    def __init__(self, screen, frozen, owner) -> None:
        super().__init__(screen, frozen, owner)
        self._markup = _MarkupState()
        self._patches = annotate.HidePatches(frozen, self._scale)
        self._toolbar: annotate.Toolbar | None = None
        #: Where the marking being drawn or dragged was painted last.
        self._painted_live: QRectF | None = None
        #: The parts of each snap window (by handle), in logical pixels.
        self._parts: dict[int, list[QRectF]] = {}
        #: How far the mouse wheel stepped out from the smallest part under
        #: the pointer, and which part that was (a new one starts at 0 again).
        self._depth = 0
        self._depth_base: QRectF | None = None

    def release_capture(self) -> None:
        """Drop pixels explicitly, including the preview's bound-method cycle."""
        self._frozen = None
        self._patches = annotate.HidePatches(None, self._scale)
        self._markup = _MarkupState()

    # -- the toolbar ---------------------------------------------------------
    def arm(self) -> None:
        bar = self._ensure_toolbar()
        self._sync_toolbar()
        bar.show()
        bar.raise_()
        self._update_cursor(self._pointer_point())

    def disarm(self) -> None:
        if self._toolbar is not None:
            self._toolbar.hide()

    def adopt(self, other) -> None:
        state = getattr(other, "_markup", None)
        if not isinstance(state, _MarkupState):
            return
        for name in _MarkupState.STYLE:
            value = getattr(state, name)
            setattr(self._markup, name, dict(value) if isinstance(value, dict) else value)

    # -- the parts of the window under the pointer ----------------------------
    def ask_parts_under_cursor(self) -> None:
        point = QPointF(self.mapFromGlobal(QCursor.pos()))
        if self.rect().contains(point.toPoint()):
            self._ask_parts(point)

    def _ask_parts(self, point: QPointF) -> None:
        index = self._window_at(point)
        if index is not None:
            self._owner.want_parts(self._snap_handles[index])

    def add_parts(self, handle: int, rects: list) -> None:
        """Window ``handle``'s parts (capture space) arrived: keep the ones on this screen."""
        indices = [i for i, h in enumerate(self._snap_handles) if h == handle]
        if not indices:
            return
        boxes = [
            box
            for _i, box in snap_targets_on_screen(
                _screen_info(self.screen_ref),
                (self.width(), self.height()),
                self._monitors,
                rects,
                min_px=mm.MIN_PART_PX,
            )
        ]
        window = self._snaps[indices[0]]
        above = [_box(rect) for rect in self._snaps[: indices[0]]]
        parts = mm.window_parts(_box(window), boxes, covers=above)
        self._parts[handle] = [QRectF(*box) for box in parts]
        if self._pointer is not None and self._choosing():
            self._follow_parts(self._pointer)
            self._repaint_changes()

    def _window_at(self, point: QPointF) -> int | None:
        """The top-most snap window under ``point``."""
        for index, rect in enumerate(self._snaps):
            if rect.contains(point):
                return index
        return None

    def _candidates(self, point: QPointF) -> list[QRectF]:
        """What a click at ``point`` may take: parts smallest first, then the window."""
        index = self._window_at(point)
        if index is None:
            return []
        window = self._snaps[index]
        parts = self._parts.get(self._snap_handles[index], [])
        boxes = mm.snap_candidates((point.x(), point.y()), _box(window), [_box(p) for p in parts])
        return [QRectF(*box) for box in boxes]

    def _follow_parts(self, point: QPointF) -> None:
        """A new part under the pointer starts the wheel over at the smallest one."""
        candidates = self._candidates(point)
        smallest = candidates[0] if candidates else None
        if smallest != self._depth_base:
            self._depth_base = smallest
            self._depth = 0

    def _snap_at(self, point: QPointF) -> QRectF | None:
        candidates = self._candidates(point)
        if not candidates:
            return None
        return candidates[min(self._depth, len(candidates) - 1)]

    def _ensure_toolbar(self) -> annotate.Toolbar:
        if self._toolbar is None:
            bar = annotate.Toolbar(
                self, language=self._owner.language, dpr=self.screen_ref.devicePixelRatio() or 1.0
            )
            bar.tool_chosen.connect(self._set_tool)
            bar.color_chosen.connect(self._set_color)
            bar.width_cycled.connect(lambda: self._step_width(1, wrap=True))
            bar.action.connect(self._toolbar_action)
            bar.option_chosen.connect(self._set_option)
            bar.keep_toggled.connect(self._set_keep)
            self._toolbar = bar
        return self._toolbar

    def _sync_toolbar(self) -> None:
        bar = self._toolbar
        if bar is None:
            return
        m = self._markup
        bar.set_tool(m.tool)
        bar.set_color(m.color)
        bar.set_width(m.width)
        bar.set_keep(self._owner.keep_area)
        self._sync_options()
        self._sync_history()

    def _show_toolbar(self) -> None:
        if self._toolbar is not None and self._owner.marking in (None, self):
            self._place_toolbar()
            self._toolbar.show()
            self._toolbar.raise_()

    def _place_toolbar(self) -> None:
        bar = self._toolbar
        if bar is None:
            return
        bar.adjustSize()
        sel = self._markup.box() if self._markup.sel is not None else None
        x, y = mm.toolbar_spot(sel, (bar.width(), bar.height()), (self.width(), self.height()))
        bar.move(round(x), round(y))

    def _sync_history(self) -> None:
        if self._toolbar is not None:
            h = self._markup.history
            self._toolbar.set_history(h.can_undo, h.can_redo)

    def _sync_options(self) -> None:
        """The looks shown for the current tool (or the selected marking's kind)."""
        bar = self._toolbar
        if bar is None:
            return
        m = self._markup
        kind = m.tool
        selected = m.selected_shape()
        if kind in (mm.MOVE, mm.AREA) and selected is not None:
            kind = selected.kind
        if kind == mm.ARROW:
            style = selected.style if selected is not None and selected.kind == mm.ARROW else ""
            options = [(s, f"arrow_{s}") for s in mm.ARROW_STYLES]
            bar.set_options(options, style or m.arrow_style, "arrow")
        elif kind == mm.TEXT:
            style = selected.style if selected is not None and selected.kind == mm.TEXT else ""
            options = [(s, f"text_{s}") for s in mm.TEXT_STYLES]
            bar.set_options(options, style or m.text_style, "text")
        elif kind == mm.REDACT:
            mode = selected.mode if selected is not None and selected.kind == mm.REDACT else ""
            options = [(s, f"redact_{s}") for s in mm.REDACT_MODES]
            bar.set_options(options, mode or m.redact_mode, "redact")
        elif kind == mm.BACKGROUND:
            options = [("off", "background_off")]
            options += [(preset, "preset") for preset, _stops in mm.BACKGROUND_PRESETS]
            chosen = m.background["preset"] if m.background else "off"
            bar.set_options(options, chosen, "background")
        else:
            bar.set_options([], "")
        self._place_toolbar()

    def _sync_lock(self) -> None:
        """Markings keep the toolbar on this screen; without them it may follow the pointer."""
        if self._markup.engaged:
            self._owner.lock(self)
        else:
            self._owner.unlock(self)

    # -- choices -------------------------------------------------------------
    def _commit(self) -> None:
        self._markup.history.push(self._markup.shapes)
        self._sync_history()

    def _set_tool(self, kind: str) -> None:
        self._commit_typing()
        m = self._markup
        if kind != mm.AREA:
            m.last_drawing = kind
        m.tool = kind
        if mm.grab_scope(kind) == "none":
            m.selected = None
        if kind == mm.BACKGROUND and m.background is None:
            m.background = dict(mm.DEFAULT_BACKGROUND)
        if self._toolbar is not None:
            self._toolbar.set_tool(kind)
        self._painted_numbers = None
        self._painted_hole = None
        self._sync_options()
        self._update_cursor(self._pointer_point())
        self.update()

    def _set_keep(self, keep: bool) -> None:
        self._owner.set_keep_area(keep)

    def _set_color(self, colour: str) -> None:
        m = self._markup
        m.color = colour
        target = m.typing or m.selected_shape()
        if target is not None:
            target.color = colour
            if target is not m.typing:
                self._commit()
        if self._toolbar is not None:
            self._toolbar.set_color(colour)
        self.update()

    def _step_width(self, step: int, *, wrap: bool = False, to: int | None = None) -> None:
        m = self._markup
        count = len(mm.WIDTHS)
        if to is not None:
            m.width_index = max(0, min(count - 1, to))
        else:
            index = m.width_index + step
            m.width_index = index % count if wrap else max(0, min(count - 1, index))
        target = m.typing or m.selected_shape()
        if target is not None:
            target.width = m.width
            if target.kind == mm.TEXT:
                target.size = mm.text_size(m.width)
            elif target.kind == mm.COUNTER:
                target.size = mm.counter_size(m.width)
            if target is not m.typing:
                self._commit()
        if self._toolbar is not None:
            self._toolbar.set_width(m.width)
        self.update()

    def _set_option(self, group: str, value: str) -> None:
        m = self._markup
        selected = m.selected_shape()
        changed = False
        if group == "arrow":
            m.arrow_style = value
            if selected is not None and selected.kind == mm.ARROW:
                selected.style, changed = value, True
        elif group == "text":
            m.text_style = value
            target = m.typing or (selected if selected and selected.kind == mm.TEXT else None)
            if target is not None:
                target.style = value
                changed = target is not m.typing
        elif group == "redact":
            m.redact_mode = value
            if selected is not None and selected.kind == mm.REDACT:
                selected.mode, changed = value, True
        elif group == "background":
            if value == "off":
                m.background = None
            else:
                m.background = {**(m.background or mm.DEFAULT_BACKGROUND), "preset": value}
        if changed:
            self._commit()
        self._sync_options()
        self.update()

    def _toolbar_action(self, name: str) -> None:
        if name == "undo":
            self._undo(redo=False)
        elif name == "redo":
            self._undo(redo=True)
        elif name == "cancel":
            self._owner.finish(None, None)
        elif name in wire.ACTIONS:
            self._deliver(name)

    def _undo(self, *, redo: bool) -> None:
        m = self._markup
        m.typing = None
        m.typing_index = None
        state = m.history.redo() if redo else m.history.undo()
        if state is not None:
            m.shapes = state
            m.selected = None
        self._sync_history()
        self._sync_options()
        self._sync_lock()
        self.update()

    # -- taking the appshot --------------------------------------------------
    def area_chosen(self, frac: tuple[float, float, float, float]) -> None:
        """The area drag ended: take it at once, or keep it to adjust it first."""
        fx, fy, fw, fh = frac
        rect = QRectF(fx * self.width(), fy * self.height(), fw * self.width(), fh * self.height())
        if not self._owner.keep_area:
            self._deliver(wire.ACTION_DONE, area=rect)
            return
        m = self._markup
        m.sel = rect
        self._pointer = None
        self._painted_numbers = None
        self._painted_hole = None
        self._sync_options()
        self._show_toolbar()
        self._sync_lock()
        self._update_cursor(None)
        self.update()

    def _deliver(self, action: str, *, area: QRectF | None = None, whole: bool = False) -> None:
        """Take the appshot: the area (kept, given, or the whole screen) plus the markings."""
        self._commit_typing()
        m = self._markup
        full = QRectF(0, 0, self.width(), self.height())
        sel = full if whole else (area or m.sel or full)
        frac = (
            sel.x() / self.width(),
            sel.y() / self.height(),
            sel.width() / self.width(),
            sel.height() / self.height(),
        )
        markup: dict | None = None
        if m.shapes or m.background:
            markup = {
                "overlay": annotate.render_overlay(m.shapes, sel, self._scale())
                if m.shapes
                else "",
                "hides": mm.hide_fractions(m.shapes, _box(sel)),
            }
            if m.background:
                markup["background"] = dict(m.background)
        self._owner.finish(self, frac, action=action, markup=markup)

    # -- text ----------------------------------------------------------------
    def _start_typing(self, at: mm.Point, *, index: int | None = None) -> None:
        """Open the text box: a new one at ``at``, or the text at ``index``."""
        m = self._markup
        if index is not None:
            m.typing = m.shapes.pop(index)
            m.typing_index = index
            m.typing_original = m.typing.copy()
        else:
            size = mm.text_size(m.width)
            m.typing = mm.Shape(
                mm.TEXT,
                color=m.color,
                width=m.width,
                size=size,
                style=m.text_style,
                points=[(at[0], at[1] - size * 0.62)],
            )
            m.typing_index = None
        m.selected = None
        self._sync_options()
        self._sync_lock()
        self.update()

    def _commit_typing(self, *, cancel: bool = False) -> None:
        m = self._markup
        shape, index = m.typing, m.typing_index
        if shape is None:
            return
        m.typing, m.typing_index = None, None
        original, m.typing_original = m.typing_original, None
        if cancel:
            if index is not None and original is not None:
                # Esc on an edited text keeps it as it was.
                m.shapes.insert(min(index, len(m.shapes)), original)
            self._sync_lock()
            self.update()
            return
        shape.text = shape.text.rstrip()
        if mm.is_meaningful(shape):
            at = min(index, len(m.shapes)) if index is not None else len(m.shapes)
            m.shapes.insert(at, shape)
            # A finished text shows its points, like every fresh marking.
            m.selected = at
            self._commit()
            self._sync_options()
        elif index is not None:
            self._commit()  # emptied: the text is gone
        self._sync_lock()
        self.update()

    def _text_at(self, point: mm.Point) -> int | None:
        index = mm.shape_at(self._markup.shapes, point, annotate.qt_measure, areas=False)
        if index is not None and self._markup.shapes[index].kind == mm.TEXT:
            return index
        return None

    def _grabbable(self, point: mm.Point) -> int | None:
        """The marking a press at ``point`` would move with the current tool."""
        m = self._markup
        scope = mm.grab_scope(m.tool)
        if scope in ("none", "grips"):
            return None
        index = mm.shape_at(m.shapes, point, annotate.qt_measure, areas=scope == "any")
        if index is None or (m.tool == mm.TEXT and m.shapes[index].kind == mm.TEXT):
            return None
        return index

    # -- keys ----------------------------------------------------------------
    def focusNextPrevChild(self, next_child: bool) -> bool:  # noqa: N802 (Qt override)
        # Tab switches between the area and the last drawing tool, not focus.
        return False

    def keyPressEvent(self, event) -> None:  # noqa: N802, C901 - one key table
        marking = self._owner.marking
        if marking is not None and marking is not self:
            marking.keyPressEvent(event)
            return
        m = self._markup
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        if m.typing is not None:
            self._typing_key(event, key, mods, ctrl)
            return
        if key == Qt.Key.Key_Escape:
            if self._start is not None:
                self._cancel_area_drag()
            elif m.selected is not None:
                m.selected = None
                self._sync_options()
                self.update()
            else:
                self._owner.finish(None, None)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._deliver(wire.ACTION_DONE)
        elif key == Qt.Key.Key_Space and not ctrl:
            self._deliver(wire.ACTION_DONE, whole=True)
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self._set_tool(mm.other_tool(m.tool, m.last_drawing))
        elif ctrl and key == Qt.Key.Key_Z:
            self._undo(redo=bool(mods & Qt.KeyboardModifier.ShiftModifier))
        elif ctrl and key == Qt.Key.Key_Y:
            self._undo(redo=True)
        elif ctrl and key in _ACTION_KEYS:
            self._deliver(_ACTION_KEYS[key])
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and m.selected is not None:
            del m.shapes[m.selected]
            m.selected = None
            self._commit()
            self._sync_options()
            self._sync_lock()
            self.update()
        elif key in _NUDGE and m.selected is not None:
            dx, dy = _NUDGE[key]
            step = 10.0 if mods & Qt.KeyboardModifier.ShiftModifier else 1.0
            m.shapes[m.selected] = mm.translated(m.shapes[m.selected], dx * step, dy * step)
            self._commit()
            self.update()
        elif not ctrl and Qt.Key.Key_1 <= key <= Qt.Key.Key_5:
            self._step_width(0, to=int(key) - int(Qt.Key.Key_1))
        elif not ctrl and event.text():
            letter = event.text().upper()
            for kind, shortcut in mm.TOOL_KEYS.items():
                if shortcut == letter:
                    self._set_tool(kind)
                    break

    def _typing_key(self, event, key, mods, ctrl: bool) -> None:
        shape = self._markup.typing
        assert shape is not None
        if key == Qt.Key.Key_Escape:
            self._commit_typing(cancel=True)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & Qt.KeyboardModifier.ShiftModifier:
                shape.text += "\n"
            else:
                self._commit_typing()
                return
        elif key == Qt.Key.Key_Backspace:
            shape.text = shape.text[:-1]
        elif ctrl and key == Qt.Key.Key_V:
            shape.text += QGuiApplication.clipboard().text()
        elif not ctrl and event.text() and event.text().isprintable():
            shape.text += event.text()
        self.update()

    # -- the mouse -----------------------------------------------------------
    def _inert(self) -> bool:
        """Another screen holds the markings: this one waits."""
        return self._owner.marking is not None and self._owner.marking is not self

    def mousePressEvent(self, event) -> None:  # noqa: N802, C901 - one press table
        if self._inert():
            return
        self._owner.focus_on(self)
        m = self._markup
        p = event.position()
        point = (p.x(), p.y())
        button = event.button()
        if button == Qt.MouseButton.RightButton:
            self._right_click(point)
            return
        if button == Qt.MouseButton.MiddleButton:
            self._set_tool(mm.other_tool(m.tool, m.last_drawing))
            return
        if button != Qt.MouseButton.LeftButton:
            return
        self._commit_typing()
        # Ctrl skips taking hold of markings: draw (or choose) right over them.
        free = not bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        selected = m.selected_shape()
        if free and selected is not None and mm.grab_scope(m.tool) != "none":
            grip = mm.grip_at(selected, point, mm.HANDLE_GRAB_PX + 1, annotate.qt_measure)
            if grip is not None:
                m.drag, m.original, m.moved = ("grip", grip), selected.copy(), False
                return
        if m.sel is not None:
            handle = mm.handle_at(m.box(), point)
            if handle is not None:
                m.drag = ("area", handle)
                return
        grabbed = self._grabbable(point) if free else None
        if grabbed is not None:
            m.selected = grabbed
            m.drag, m.last, m.moved = ("move", None), p, False
            self._sync_options()
            self.update()
            return
        if m.selected is not None:
            m.selected = None
            self._sync_options()
            self.update()
        if m.tool == mm.AREA:
            if m.sel is not None and m.sel.contains(p):
                m.drag, m.last = ("area-move", None), p
                return
            self._start = p
            self._end = p
            self._pointer = p
            # The toolbar steps aside while the area is drawn, so nothing
            # covers what is being chosen.
            if self._toolbar is not None:
                self._toolbar.hide()
            self.update()
            return
        if m.tool in (mm.MOVE, mm.BACKGROUND):
            return
        if m.tool == mm.TEXT:
            self._start_typing(point, index=self._text_at(point))
            return
        if m.tool == mm.COUNTER:
            m.shapes.append(
                mm.Shape(
                    mm.COUNTER,
                    color=m.color,
                    width=m.width,
                    size=mm.counter_size(m.width),
                    points=[point],
                    number=mm.next_counter(m.shapes),
                )
            )
            m.selected = len(m.shapes) - 1
            self._commit()
            self._sync_options()
        elif m.tool in mm.STROKE_KINDS:
            m.drawing = mm.Shape(m.tool, color=m.color, width=m.width, points=[point])
        else:
            m.drawing = mm.Shape(
                m.tool,
                color=m.color,
                width=m.width,
                points=[point, point],
                style=m.arrow_style if m.tool == mm.ARROW else "",
                mode=m.redact_mode if m.tool == mm.REDACT else "",
            )
        self._sync_lock()
        self._touch_live()

    def _right_click(self, point: mm.Point) -> None:
        """Undo the gesture in progress, remove a marking, or close."""
        m = self._markup
        if self._start is not None:
            self._cancel_area_drag()
            return
        if m.drawing is not None:
            m.drawing = None
            self._sync_lock()
            self._touch_live()
            return
        if m.typing is not None:
            self._commit_typing(cancel=True)
            return
        index = mm.shape_at(m.shapes, point, annotate.qt_measure)
        if index is not None:
            del m.shapes[index]
            m.selected = None
            self._commit()
            self._sync_options()
            self._sync_lock()
            self.update()
            return
        if m.sel is not None:
            m.sel = None
            m.drag = None
            self._sync_options()
            self._sync_lock()
            self._update_cursor(point)
            self.update()
            return
        self._owner.finish(None, None)

    def _cancel_area_drag(self) -> None:
        self._start = None
        self._end = None
        self._show_toolbar()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._inert():
            return
        self._owner.focus_on(self)
        m = self._markup
        p = event.position()
        point = (p.x(), p.y())
        if self._start is not None:
            self._end = p
            self._pointer = p
            self._repaint_changes()
            return
        drag = m.drag
        if drag is not None and drag[0] == "area" and m.sel is not None:
            sel = mm.resize(m.box(), drag[1] or "se", point, (self.width(), self.height()))
            m.sel = QRectF(*sel)
            self._place_toolbar()
            self.update()
            return
        if drag is not None and drag[0] == "area-move" and m.sel is not None and m.last:
            delta = p - m.last
            sel = m.sel
            x = max(0.0, min(self.width() - sel.width(), sel.x() + delta.x()))
            y = max(0.0, min(self.height() - sel.height(), sel.y() + delta.y()))
            m.sel = QRectF(x, y, sel.width(), sel.height())
            m.last = p
            self._place_toolbar()
            self.update()
            return
        if drag is not None and drag[0] == "grip" and m.selected is not None and m.original:
            m.shapes[m.selected] = mm.reshape(
                m.original, drag[1] or "se", point, annotate.qt_measure
            )
            m.moved = True
            self._touch_live()
            return
        if drag is not None and drag[0] == "move" and m.selected is not None and m.last:
            delta = p - m.last
            m.shapes[m.selected] = mm.translated(m.shapes[m.selected], delta.x(), delta.y())
            m.last, m.moved = p, True
            self._touch_live()
            return
        shape = m.drawing
        if shape is not None:
            if shape.kind in mm.STROKE_KINDS:
                lx, ly = shape.points[-1]
                if abs(point[0] - lx) + abs(point[1] - ly) >= 1.5:
                    shape.points.append(point)
            else:
                end = point
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    end = mm.constrain(shape.kind, shape.points[0], point)
                shape.points[-1] = end
            self._touch_live()
            return
        self._pointer = p
        if self._choosing():
            self._ask_parts(p)
            self._follow_parts(p)
        self._repaint_changes()
        self._update_cursor(point)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._inert() or event.button() != Qt.MouseButton.LeftButton:
            return
        if self._start is not None:
            frac = self._take_drag(event.position())
            if frac is None:
                self._show_toolbar()
                self.update()
                return
            self.area_chosen(frac)
            return
        m = self._markup
        drag, m.drag = m.drag, None
        m.original = None
        if drag is not None and drag[0] in ("area", "area-move"):
            self._sync_options()
            self.update()
            return
        if drag is not None and drag[0] in ("move", "grip") and m.moved:
            self._commit()
        shape, m.drawing = m.drawing, None
        if shape is not None and mm.is_meaningful(shape):
            m.shapes.append(shape)
            self._commit()
            # Every fresh marking shows its points at once (the previous one
            # loses them), so it can be moved and reshaped right away.
            m.selected = len(m.shapes) - 1
            self._sync_options()
        self._sync_lock()
        self._touch_live()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Double-click a text to change it; double-click in a kept area to take it."""
        if self._inert():
            return
        m = self._markup
        if m.typing is not None:
            return
        p = event.position()
        if m.tool in (mm.MOVE, mm.TEXT):
            index = self._text_at((p.x(), p.y()))
            if index is not None:
                m.drag = None
                self._start_typing((p.x(), p.y()), index=index)
                return
        if m.sel is not None and m.sel.contains(p) and m.tool in (mm.AREA, mm.MOVE):
            m.drag = None
            self._deliver(wire.ACTION_DONE)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._inert():
            return
        steps = event.angleDelta().y()
        if not steps:
            return
        if self._choosing() and self._start is None and self._pointer is not None:
            # Choosing: the wheel steps out to the larger parts and back in.
            candidates = self._candidates(self._pointer)
            if candidates:
                step = 1 if steps > 0 else -1
                self._depth = max(0, min(len(candidates) - 1, self._depth + step))
                self._repaint_changes()
            return
        self._step_width(1 if steps > 0 else -1)

    def _pointer_point(self) -> mm.Point | None:
        p = self._pointer
        return (p.x(), p.y()) if p is not None else None

    def _update_cursor(self, point: mm.Point | None) -> None:  # noqa: C901 - one cursor table
        m = self._markup
        if point is not None:
            selected = m.selected_shape()
            if selected is not None and mm.grab_scope(m.tool) != "none":
                grip = mm.grip_at(selected, point, mm.HANDLE_GRAB_PX + 1, annotate.qt_measure)
                if grip is not None:
                    self.setCursor(_GRIP_CURSORS[mm.grip_cursor(grip)])
                    return
            if m.sel is not None:
                handle = mm.handle_at(m.box(), point)
                if handle is not None:
                    self.setCursor(_HANDLE_CURSORS[handle])
                    return
            if self._grabbable(point) is not None:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return
            if m.tool == mm.AREA and m.sel is not None and m.sel.contains(QPointF(*point)):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return
        if m.tool == mm.TEXT:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif m.tool in (mm.MOVE, mm.BACKGROUND):
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(self._cross)

    # -- what the crosshair shows --------------------------------------------
    def _choosing(self) -> bool:
        """The area tool is out and no area is kept: snapping and numbers show."""
        return self._markup.tool == mm.AREA and self._markup.sel is None

    def _hole(self) -> QRectF | None:
        if self._markup.sel is not None:
            return None
        sel = self._selection()
        if sel is not None:
            return sel
        if self._choosing() and self._pointer is not None:
            return self._snap_at(self._pointer)
        return None

    def _numbers(self) -> tuple[str, str] | None:
        if self._selection() is None and not self._choosing():
            return None
        return super()._numbers()

    # -- painting ------------------------------------------------------------
    def _live_rect(self) -> QRectF | None:
        """What the marking being drawn or dragged covers, with room for its frills."""
        m = self._markup
        shape = m.drawing or m.selected_shape()
        if shape is None or not shape.points:
            return None
        if shape.kind == mm.SPOTLIGHT:
            # A spotlight dims everything around it.
            return QRectF(0, 0, self.width(), self.height())
        x, y, w, h = mm.bounds(shape, annotate.qt_measure)
        pad = _LIVE_PAD + shape.width * _LIVE_PAD_PER_WIDTH
        return QRectF(x, y, w, h).adjusted(-pad, -pad, pad, pad)

    def _touch_live(self) -> None:
        """Repaint where the live marking is now and where it was."""
        rect = self._live_rect()
        dirty = rect
        if self._painted_live is not None:
            dirty = self._painted_live if dirty is None else dirty.united(self._painted_live)
        self._painted_live = rect
        if self._markup.sel is not None or dirty is None:
            self.update()
        else:
            self.update(dirty.toAlignedRect())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        full = QRectF(0, 0, self.width(), self.height())
        if self._frozen is not None:
            painter.drawPixmap(full, self._frozen, QRectF(self._frozen.rect()))
        if self._markup.sel is not None:
            self._paint_kept(painter, full)
            painter.end()
            return
        hole = self._hole()
        self._paint_veil(painter, full, hole)
        self._paint_markings(painter, full)
        if hole is not None:
            self._paint_border(painter, hole)
        self._paint_numbers(painter)
        painter.end()

    def _paint_markings(self, painter: QPainter, area: QRectF) -> None:
        m = self._markup
        live = [*m.shapes, *(s for s in (m.drawing,) if s is not None)]
        if live:
            for shape in (s for s in live if s.kind == mm.REDACT):
                annotate.paint_shape(painter, shape, hide_source=self._patches)
            for shape in (s for s in live if s.kind != mm.REDACT):
                annotate.paint_shape(painter, shape)
            annotate.paint_spotlights(painter, live, area)
        if m.typing is not None:
            labels = annotate.labels_for(self._owner.language)
            annotate.paint_typing(painter, m.typing, labels["placeholder"], caret=True)
        selected = m.selected_shape()
        if selected is not None:
            annotate.paint_picked(painter, selected)

    def _paint_kept(self, painter: QPainter, full: QRectF) -> None:
        """A kept area: the world around it darker, markings cut to it, handles."""
        m = self._markup
        sel = m.sel
        assert sel is not None
        dim = QPainterPath()
        dim.addRect(full)
        cut = QPainterPath()
        cut.addRect(sel)
        painter.fillPath(dim.subtracted(cut), annotate.DIM_OUTSIDE)
        if self._frozen is None:
            # Live overlay: a fully clear pixel lets clicks fall through to the
            # window below, so the area keeps an invisible film to draw on.
            painter.fillRect(sel, QColor(0, 0, 0, 1))
        if m.background:
            annotate.paint_background_frame(painter, sel, m.background)
        painter.save()
        painter.setClipRect(sel, Qt.ClipOperation.IntersectClip)
        live = [*m.shapes, *(s for s in (m.drawing,) if s is not None)]
        for shape in (s for s in live if s.kind == mm.REDACT):
            annotate.paint_shape(painter, shape, hide_source=self._patches)
        for shape in (s for s in live if s.kind != mm.REDACT):
            annotate.paint_shape(painter, shape)
        annotate.paint_spotlights(painter, live, sel)
        painter.restore()
        if m.typing is not None:
            labels = annotate.labels_for(self._owner.language)
            annotate.paint_typing(painter, m.typing, labels["placeholder"], caret=True)
        selected = m.selected_shape()
        if selected is not None:
            annotate.paint_picked(painter, selected)
        annotate.paint_selection_frame(painter, sel)
        self._paint_size(painter, sel)

    def _paint_size(self, painter: QPainter, sel: QRectF) -> None:
        """``W x H`` in capture pixels, just above the area's top-left corner."""
        scale = self._scale()
        text = f"{round(sel.width() * scale)} × {round(sel.height() * scale)}"
        ascent = self._metrics.ascent()
        y = sel.top() - 6.0
        if y - ascent < EDGE_GAP:
            y = sel.top() + ascent + 6.0
        path = QPainterPath()
        path.addText(QPointF(sel.left() + 1.0, y), self._font, text)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        halo = QPen(HALO, 2.6)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(path, halo)
        painter.fillPath(path, INK)
        painter.restore()


__all__ = ["MarkupWindow"]
