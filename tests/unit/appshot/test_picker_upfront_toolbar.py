"""The area picker opens with its marking toolbar up and takes the area on release.

Drives the real picker window on Qt's offscreen platform: the toolbar is
there before anything is chosen, markings drawn first ride along with the
area, releasing the drag takes the appshot without a confirm step, and
"adjust before taking" keeps the old adjust-then-Enter flow. Auto-skips
without PySide6 (a [desktop] extra).
"""

from __future__ import annotations

import importlib.util
import os

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed (the area picker is a [desktop] extra)",
)

W, H = 1600, 900


@pytest.fixture(scope="module")
def qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def picker(qt, monkeypatch):
    from PySide6.QtGui import QColor, QGuiApplication, QPixmap  # noqa: PLC0415

    from dodaios.appshot.picker import renderer  # noqa: PLC0415
    from dodaios.appshot.picker.markup_window import MarkupWindow  # noqa: PLC0415

    events: list[dict] = []
    monkeypatch.setattr(renderer, "_emit", events.append)
    owner = renderer.Picker(qt, language="en", resident=True)
    screen = QGuiApplication.primaryScreen()

    def window() -> MarkupWindow:
        frozen = QPixmap(W, H)
        frozen.fill(QColor(40, 90, 160))
        win = MarkupWindow(screen, frozen, owner)
        win.setGeometry(0, 0, W, H)
        owner._windows.append(win)
        return win

    first = window()
    owner._started = True
    owner._focused = first
    first.show()
    first.arm()
    yield owner, first, window, events
    if not owner._done:
        owner.finish(None, None)


def _mouse(win, kind: str, x: float, y: float, button=None, modifiers=None) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: PLC0415
    from PySide6.QtGui import QMouseEvent  # noqa: PLC0415

    button = button or Qt.MouseButton.LeftButton
    modifiers = modifiers or Qt.KeyboardModifier.NoModifier
    types = {
        "press": QEvent.Type.MouseButtonPress,
        "move": QEvent.Type.MouseMove,
        "release": QEvent.Type.MouseButtonRelease,
        "double": QEvent.Type.MouseButtonDblClick,
    }
    if kind == "move":
        changed, held = Qt.MouseButton.NoButton, button
    elif kind == "release":
        changed, held = button, Qt.MouseButton.NoButton
    else:
        changed, held = button, button
    event = QMouseEvent(types[kind], QPointF(x, y), QPointF(x, y), changed, held, modifiers)
    {
        "press": win.mousePressEvent,
        "move": win.mouseMoveEvent,
        "release": win.mouseReleaseEvent,
        "double": win.mouseDoubleClickEvent,
    }[kind](event)


def _drag(win, a: tuple[float, float], b: tuple[float, float], **kw) -> None:
    _mouse(win, "press", *a, **kw)
    _mouse(win, "move", (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, **kw)
    _mouse(win, "move", *b, **kw)
    _mouse(win, "release", *b, **kw)


def _key(win, key, text: str = "", modifiers=None) -> None:
    from PySide6.QtCore import QEvent, Qt  # noqa: PLC0415
    from PySide6.QtGui import QKeyEvent  # noqa: PLC0415

    win.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, key, modifiers or Qt.KeyboardModifier.NoModifier, text)
    )


def _selection(events: list[dict]) -> dict | None:
    return next((e for e in events if e.get("event") == "selection"), None)


def test_the_toolbar_is_up_before_any_area_is_chosen(picker) -> None:
    from dodaios.appshot.picker import markup_model as mm  # noqa: PLC0415

    owner, win, _window, events = picker
    bar = win._toolbar
    assert bar is not None and bar.isVisible(), "the toolbar shows the moment the overlay opens"
    assert win._markup.tool == mm.AREA, "the area tool is the one in hand"
    assert bar._tool_buttons[mm.AREA].isChecked()
    assert bar.y() == 12, "it sits at the top of the screen, not under a selection"
    assert abs((bar.x() + bar.width() / 2) - W / 2) <= 1, "centred"
    assert _selection(events) is None


def test_releasing_the_area_drag_takes_the_appshot_at_once(picker) -> None:
    owner, win, _window, events = picker
    _drag(win, (100, 120), (300, 270))
    selection = _selection(events)
    assert selection is not None, "no confirm step: the release takes it"
    assert selection["action"] == "done"
    assert selection["rect"] == pytest.approx([100 / W, 120 / H, 200 / W, 150 / H])
    assert "markup" not in selection


def test_markings_drawn_first_ride_along_with_the_area(picker) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    from dodaios.appshot.picker import markup_model as mm  # noqa: PLC0415

    owner, win, _window, events = picker
    _key(win, Qt.Key.Key_A, "a")
    assert win._markup.tool == mm.ARROW
    _drag(win, (150, 150), (260, 210))
    assert len(win._markup.shapes) == 1
    # The parent drops its global Esc once something is marked.
    assert {"event": "marking"} in events
    assert _selection(events) is None, "drawing never takes the appshot"
    _key(win, Qt.Key.Key_Tab)
    assert win._markup.tool == mm.AREA, "Tab goes back to the area tool"
    _drag(win, (100, 100), (400, 300))
    selection = _selection(events)
    assert selection is not None
    assert selection["markup"]["overlay"], "the arrow is burnt into the appshot"


def test_ctrl_starts_the_area_right_over_a_marking(picker) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    owner, win, _window, events = picker
    _key(win, Qt.Key.Key_F, "f")
    _drag(win, (100, 100), (300, 300))
    _key(win, Qt.Key.Key_K, "k")
    # A plain press on the filled box would take hold of it ...
    _drag(win, (200, 200), (220, 220))
    assert _selection(events) is None
    assert win._markup.shapes[0].points[0] == pytest.approx((120, 120))
    # ... with Ctrl it starts the area there instead.
    _drag(win, (150, 150), (350, 330), modifiers=Qt.KeyboardModifier.ControlModifier)
    assert _selection(events) is not None


def test_space_takes_the_whole_screen(picker) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    owner, win, _window, events = picker
    _key(win, Qt.Key.Key_Space, " ")
    selection = _selection(events)
    assert selection is not None and selection["rect"] == pytest.approx([0, 0, 1, 1])


def test_keep_area_leaves_the_area_to_adjust_then_enter_takes_it(picker) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    owner, win, _window, events = picker
    owner.keep_area = True
    _drag(win, (100, 100), (300, 250))
    assert _selection(events) is None, "the area stays"
    assert win._markup.sel is not None
    assert win._toolbar is not None and win._toolbar.isVisible()
    # Its handles still resize it.
    _drag(win, (300, 250), (400, 300))
    _key(win, Qt.Key.Key_Return)
    selection = _selection(events)
    assert selection is not None
    assert selection["rect"] == pytest.approx([100 / W, 100 / H, 300 / W, 200 / H])


def test_keep_area_double_click_in_the_area_takes_it(picker) -> None:
    owner, win, _window, events = picker
    owner.keep_area = True
    _drag(win, (100, 100), (300, 250))
    _mouse(win, "double", 200, 180)
    assert _selection(events) is not None


def test_flipping_the_switch_reports_it_to_the_parent(picker) -> None:
    owner, win, _window, events = picker
    assert win._toolbar is not None
    win._toolbar._keep.click()
    assert owner.keep_area is True
    assert {"event": "option", "keep_area": True} in events
    win._toolbar._keep.click()
    assert {"event": "option", "keep_area": False} in events


def test_right_click_removes_a_marking_then_closes(picker) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    owner, win, _window, events = picker
    _key(win, Qt.Key.Key_R, "r")
    _drag(win, (100, 100), (300, 300))
    assert len(win._markup.shapes) == 1
    right = Qt.MouseButton.RightButton
    _mouse(win, "press", 100, 200, button=right)
    assert win._markup.shapes == [], "a right-click on a marking removes it"
    assert _selection(events) is None
    _mouse(win, "press", 500, 500, button=right)
    assert _selection(events) == {"event": "selection", "cancelled": True}


def test_esc_closes_a_text_box_before_it_closes_the_overlay(picker) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    owner, win, _window, events = picker
    _key(win, Qt.Key.Key_T, "t")
    _mouse(win, "press", 200, 200)
    assert win._markup.typing is not None
    _key(win, Qt.Key.Key_H, "H")
    _key(win, Qt.Key.Key_I, "i")
    _key(win, Qt.Key.Key_Return)
    assert [s.text for s in win._markup.shapes] == ["Hi"]
    _mouse(win, "press", 400, 400)
    _key(win, Qt.Key.Key_Escape)
    assert win._markup.typing is None and _selection(events) is None
    _key(win, Qt.Key.Key_Escape)  # deselects the text
    _key(win, Qt.Key.Key_Escape)
    assert _selection(events) == {"event": "selection", "cancelled": True}


def test_the_toolbar_follows_the_pointer_until_something_is_marked(picker) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    from dodaios.appshot.picker import markup_model as mm  # noqa: PLC0415

    owner, first, window, events = picker
    second = window()
    second.show()
    _key(first, Qt.Key.Key_D, "d")
    owner.focus_on(second)
    assert first._toolbar is not None and not first._toolbar.isVisible()
    assert second._toolbar is not None and second._toolbar.isVisible()
    assert second._markup.tool == mm.PEN, "the chosen tool comes along"
    _drag(second, (50, 50), (120, 90))
    assert owner.marking is second
    owner.focus_on(first)
    assert second._toolbar.isVisible(), "markings keep the toolbar on their screen"
    _mouse(first, "press", 10, 10)
    assert first._markup.drawing is None, "the other screen waits"


def test_the_plain_chooser_still_finishes_on_release(qt, monkeypatch) -> None:
    """The screen recorder's window has no toolbar and still ends on release."""
    from PySide6.QtGui import QGuiApplication, QPixmap  # noqa: PLC0415

    from dodaios.appshot.picker import renderer  # noqa: PLC0415

    finished: list[tuple] = []

    class Owner:
        marking = None
        language = "en"

        def focus_on(self, _window) -> None:
            return None

        def finish(self, window, frac) -> None:
            finished.append((window, frac))

    win = renderer._SelectWindow(QGuiApplication.primaryScreen(), QPixmap(W, H), Owner())
    win.setGeometry(0, 0, W, H)
    win.arm()
    _drag(win, (0, 0), (W / 2, H / 2))
    assert finished and finished[0][1] == pytest.approx((0, 0, 0.5, 0.5))
    win.close()
