"""Hovering in the area picker offers the parts of a window, not only the window.

The geometry is plain data; the scanner runs on its worker thread with a
fake reader (no UI Automation needed); the window is the real Qt window on
the offscreen platform. Qt parts auto-skip without PySide6.
"""

from __future__ import annotations

import importlib.util
import os
import threading

import pytest

from dodaios.appshot import region
from dodaios.appshot.picker import markup_model as mm

needs_qt = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed (the area picker is a [desktop] extra)",
)

W, H = 1600, 900
WINDOW = [100, 100, 1000, 700]
#: A sidebar, a list in it, a content pane, the pane's inner area that is
#: nearly the pane itself, a single button row (too small to offer) and a
#: speck.
PARTS = [
    [100, 100, 250, 700],
    [110, 200, 230, 120],
    [350, 100, 750, 700],
    [356, 104, 740, 690],
    [110, 400, 230, 30],
    [0, 0, 5, 5],
]
MONITORS = [
    {"left": 0, "top": 0, "width": W, "height": H},
    {"left": 0, "top": 0, "width": W, "height": H},
]


# ----------------------------------------------------------------- geometry


def test_window_parts_are_cut_to_the_window_without_copies_or_slivers() -> None:
    window = (100.0, 100.0, 1000.0, 700.0)
    parts = mm.window_parts(
        window,
        [
            (50.0, 150.0, 200.0, 100.0),  # sticks out on the left
            (50.0, 150.0, 200.0, 100.0),  # the same again
            (100.0, 100.0, 1000.0, 700.0),  # the window itself
            (300.0, 300.0, 10.0, 10.0),  # a speck
            (300.0, 300.0, 400.0, 30.0),  # a button row: thinner than 40 px
            (300.0, 400.0, 90.0, 90.0),  # a tile: under 1.5 % of the window
            (2000.0, 0.0, 100.0, 100.0),  # outside
        ],
    )
    assert parts == [(100.0, 150.0, 150.0, 100.0)]


def test_a_part_mostly_under_another_window_is_not_offered() -> None:
    window = (0.0, 0.0, 1000.0, 1000.0)
    sidebar = (0.0, 0.0, 300.0, 1000.0)
    page = (300.0, 0.0, 700.0, 1000.0)
    on_top = [(250.0, 0.0, 750.0, 1000.0)]
    assert mm.window_parts(window, [sidebar, page], covers=on_top) == [sidebar]


def test_candidates_run_from_the_smallest_part_out_to_the_window() -> None:
    window = (100.0, 100.0, 1000.0, 700.0)
    parts = [tuple(float(v) for v in p) for p in PARTS[:4]]
    assert mm.snap_candidates((120, 210), window, parts) == [
        (110.0, 200.0, 230.0, 120.0),
        (100.0, 100.0, 250.0, 700.0),
        window,
    ]
    # The pane's inner area is nearly the pane: one step, the larger one.
    assert mm.snap_candidates((600, 400), window, parts) == [(350.0, 100.0, 750.0, 700.0), window]
    assert mm.snap_candidates((5, 5), window, parts) == [window]


def test_a_page_under_browser_bars_stays_its_own_step() -> None:
    window = (0.0, 0.0, 2560.0, 1392.0)
    page = (0.0, 120.0, 2560.0, 1272.0)
    assert mm.snap_candidates((900, 700), window, [page]) == [page, window]


def test_the_layout_carries_a_handle_beside_each_window(monkeypatch) -> None:
    from dodaios.platform import window_state as ws
    from dodaios.screen_context import ports

    class Win:
        def __init__(self, handle, minimized=False):
            self.handle = handle
            self.minimized = minimized

    class Displays:
        def monitors(self):
            return MONITORS

    monkeypatch.setattr(ports, "make_display_enumerator", lambda: Displays())
    monkeypatch.setattr(ws, "list_windows", lambda: [Win(11), Win(22, minimized=True), Win(None)])
    monkeypatch.setattr(
        ws, "window_frame_rect", lambda win: (0, 0, 100 + 10 * bool(win.handle), 50)
    )
    monkeypatch.setattr(region, "_is_cloaked", lambda _h: False)
    layout = region.snap_layout()
    assert layout["windows"] == [[0, 0, 110, 50], [0, 0, 100, 50]]
    assert layout["handles"] == [11, 0]


def test_snap_targets_keep_their_index_when_others_drop_out() -> None:
    screen = {"x": 0.0, "y": 0.0, "w": float(W), "h": float(H), "dpr": 1.0}
    targets = region.snap_targets_on_screen(
        screen, (W, H), MONITORS, [[0, 0, 5, 5], WINDOW, "junk"], min_px=24
    )
    assert targets == [(1, (100.0, 100.0, 1000.0, 700.0))]


# ------------------------------------------------------------------ scanner


@pytest.fixture(scope="module")
def qt():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait_for(qt, condition, timeout_s: float = 3.0) -> None:
    import time

    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(0.01)
    assert condition()


@needs_qt
def test_the_scanner_reads_each_window_once_per_pick_on_its_own_thread(qt) -> None:
    from dodaios.appshot.picker.elements import ElementScanner

    calls: list[tuple[int, str]] = []

    def make_scan():
        def scan(handle: int) -> list[list[int]]:
            calls.append((handle, threading.current_thread().name))
            return [[handle, 0, 10, 10]]

        return scan

    scanner = ElementScanner(make_scan)
    found: list[tuple] = []
    scanner.found.connect(lambda handle, rects: found.append((handle, rects)))
    scanner.request(7)
    _wait_for(qt, lambda: found)
    assert found == [(7, [[7, 0, 10, 10]])]
    assert calls[0][1] == "appshot-picker-parts", "never on the Qt thread"
    scanner.request(7)
    _wait_for(qt, lambda: len(found) == 2)
    assert len(calls) == 1, "a window is read once per pick"
    scanner.reset()
    scanner.request(7)
    _wait_for(qt, lambda: len(found) == 3)
    assert len(calls) == 2, "a new pick reads it again"
    scanner.stop()


@needs_qt
def test_without_a_reader_the_scanner_stays_quiet(qt) -> None:
    from dodaios.appshot.picker.elements import ElementScanner

    scanner = ElementScanner(lambda: None)
    found: list = []
    scanner.found.connect(lambda *args: found.append(args))
    scanner.request(5)
    _wait_for(qt, lambda: scanner._unavailable)
    scanner.request(6)
    qt.processEvents()
    assert found == [] and scanner._queue == []


# ------------------------------------------------------------------- window


@pytest.fixture
def picker(qt, monkeypatch):
    from PySide6.QtGui import QColor, QGuiApplication, QPixmap

    from dodaios.appshot.picker import markup_window, renderer

    events: list[dict] = []
    asked: list[int] = []
    monkeypatch.setattr(renderer, "_emit", events.append)
    info = {"x": 0.0, "y": 0.0, "w": float(W), "h": float(H), "dpr": 1.0}
    monkeypatch.setattr(renderer, "_screen_info", lambda _s: info)
    monkeypatch.setattr(markup_window, "_screen_info", lambda _s: info)
    owner = renderer.Picker(qt, language="en", resident=True)
    monkeypatch.setattr(owner, "want_parts", asked.append)
    frozen = QPixmap(W, H)
    frozen.fill(QColor(40, 90, 160))
    win = markup_window.MarkupWindow(QGuiApplication.primaryScreen(), frozen, owner)
    win.setGeometry(0, 0, W, H)
    owner._windows.append(win)
    owner._focused = win
    owner._started = True
    win.show()
    win.arm()
    win.set_layout(MONITORS, [WINDOW], [4242])
    yield owner, win, events, asked
    if not owner._done:
        owner.finish(None, None)


def _move(win, x: float, y: float) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    win.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y), Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        )
    )


def _click(win, x: float, y: float) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    left = Qt.MouseButton.LeftButton
    for kind, held, handler in (
        (QEvent.Type.MouseButtonPress, left, win.mousePressEvent),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton, win.mouseReleaseEvent),
    ):
        handler(QMouseEvent(kind, QPointF(x, y), QPointF(x, y), left, held,
                            Qt.KeyboardModifier.NoModifier))


def _wheel(win, x: float, y: float, up: bool) -> None:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    win.wheelEvent(
        QWheelEvent(
            QPointF(x, y), QPointF(x, y), QPoint(0, 0), QPoint(0, 120 if up else -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
    )


@needs_qt
def test_hovering_asks_for_the_parts_and_lights_the_smallest_one(picker) -> None:
    owner, win, events, asked = picker
    _move(win, 120, 210)
    assert asked and asked[-1] == 4242, "the window under the pointer is read"
    assert win._hole() == win._snaps[0], "until its parts arrive, the whole window lights up"
    win.add_parts(4242, PARTS)
    assert (win._hole().x(), win._hole().y(), win._hole().width(), win._hole().height()) == (
        110, 200, 230, 120,
    )


@needs_qt
def test_the_wheel_steps_out_and_a_click_takes_what_is_lit(picker) -> None:
    owner, win, events, asked = picker
    win.add_parts(4242, PARTS)
    _move(win, 120, 210)
    _wheel(win, 120, 210, up=True)
    assert win._hole().width() == 250, "one step out: the sidebar"
    _wheel(win, 120, 210, up=True)
    _wheel(win, 120, 210, up=True)
    assert win._hole().width() == 1000, "it stops at the whole window"
    _wheel(win, 120, 210, up=False)
    _click(win, 120, 210)
    selection = next(e for e in events if e.get("event") == "selection")
    assert selection["rect"] == pytest.approx([100 / W, 100 / H, 250 / W, 700 / H])


@needs_qt
def test_a_new_part_under_the_pointer_starts_at_the_smallest_again(picker) -> None:
    owner, win, events, asked = picker
    win.add_parts(4242, PARTS)
    _move(win, 120, 210)
    _wheel(win, 120, 210, up=True)
    _move(win, 600, 400)
    assert win._hole().width() == 750


@needs_qt
def test_small_pieces_are_never_lit(picker) -> None:
    owner, win, events, asked = picker
    win.add_parts(4242, PARTS)
    _move(win, 120, 410)
    assert win._hole().width() == 250, "the button row is skipped: the sidebar lights up"


@needs_qt
def test_parts_of_another_window_are_ignored(picker) -> None:
    owner, win, events, asked = picker
    win.add_parts(9999, PARTS)
    _move(win, 120, 210)
    assert win._hole() == win._snaps[0]
