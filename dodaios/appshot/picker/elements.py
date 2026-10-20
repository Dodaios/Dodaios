"""Read the parts of a window — panels, lists, fields, buttons — for snapping.

Runs ONLY inside ``python -m dodaios.appshot.picker`` (PySide6, AP-26).

Hovering a window lifts the whole window out of the dim. To offer the parts
inside it too, the picker asks the OS accessibility tree which elements the
window holds and where they are: on Windows UI Automation
(``FindAllBuildCache`` with the bounding rectangle cached, one cross-process
call per window, typically 10-200 ms). Other platforms report nothing, so
the picker keeps snapping to whole windows there.

The walk runs on a worker thread so the overlay never waits for it; the
window under the pointer is read first, each window at most once per pick,
and results arrive as a Qt signal. Rects are in capture space (physical
pixels on Windows), the same space as the window rects from the main
process, so the picker maps both the same way.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

#: Elements read per window at most: enough for any real layout, and a hard
#: stop for pages with tens of thousands of nodes.
MAX_PARTS = 3000
#: How long one window may keep UI Automation busy (ms) before it gives up.
UIA_TIMEOUT_MS = 1000
#: The kinds of element that make a part: containers and pictures. Single
#: buttons, rows, items, tabs, text runs, links and web components are left
#: out; they made hovering light up pieces nobody meant to take.
PART_KINDS = (
    "DataGrid", "Document", "Edit", "Group", "Image", "List", "Menu", "MenuBar",
    "Pane", "StatusBar", "Tab", "Table", "ToolBar", "Tree", "Window",
)

Scan = Callable[[int], list[list[int]]]


class ElementScanner(QObject):
    """Reads windows' parts on a worker thread; ``found(handle, rects)`` reports them."""

    found = Signal(object, object)

    def __init__(self, scan: Callable[[], Scan | None] | None = None) -> None:
        super().__init__()
        #: Builds the scan function ON the worker thread (COM lives there).
        self._make_scan = scan or uia_scan
        self._lock = threading.Condition()
        self._queue: list[int] = []
        self._results: dict[int, list[list[int]]] = {}
        self._session = 0
        self._thread: threading.Thread | None = None
        self._stopped = False
        #: The platform cannot read parts: requests are dropped at once.
        self._unavailable = False

    def reset(self) -> None:
        """A new pick: forget what was read, the windows may have changed."""
        with self._lock:
            self._queue.clear()
            self._results.clear()
            self._session += 1

    def request(self, handle: int) -> None:
        """Read ``handle``'s parts next (a pointer moved onto it)."""
        if not handle:
            return
        with self._lock:
            if self._unavailable:
                return
            cached = self._results.get(handle)
            if cached is None:
                if handle in self._queue:
                    self._queue.remove(handle)
                self._queue.insert(0, handle)
                self._start()
                self._lock.notify()
        if cached is not None:
            self.found.emit(handle, cached)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            self._queue.clear()
            self._lock.notify()

    def _start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="appshot-picker-parts", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        try:
            scan = self._make_scan()
        except Exception:  # noqa: BLE001 - no reader: the picker snaps to whole windows
            scan = None
        if scan is None:
            with self._lock:
                self._unavailable = True
                self._queue.clear()
            return
        while True:
            with self._lock:
                while not self._queue and not self._stopped:
                    self._lock.wait()
                if self._stopped:
                    return
                handle = self._queue.pop(0)
                session = self._session
            try:
                rects = scan(handle)
            except Exception:  # noqa: BLE001 - an unreadable window keeps whole-window snapping
                rects = []
            with self._lock:
                if session != self._session or self._stopped:
                    continue
                self._results[handle] = rects
            self.found.emit(handle, rects)


def uia_scan() -> Scan | None:
    """A UI Automation reader for this thread; ``None`` off Windows or without it."""
    if sys.platform != "win32":
        return None
    try:
        import comtypes  # noqa: PLC0415

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:  # this thread already has COM: synchronous calls work in either
            pass
        try:
            from comtypes.gen import UIAutomationClient as uia_api  # noqa: PLC0415
        except ImportError:  # first use on this machine: generate the UIA wrappers
            import comtypes.client  # noqa: PLC0415

            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as uia_api  # noqa: PLC0415
        uia = comtypes.CoCreateInstance(
            uia_api.CUIAutomation8._reg_clsid_,
            interface=uia_api.IUIAutomation2,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
        uia.TransactionTimeout = UIA_TIMEOUT_MS
        uia.ConnectionTimeout = UIA_TIMEOUT_MS
        kinds = [getattr(uia_api, f"UIA_{name}ControlTypeId") for name in PART_KINDS]
        wanted = uia.CreateAndCondition(
            uia.CreateOrConditionFromArray(
                [uia.CreatePropertyCondition(uia_api.UIA_ControlTypePropertyId, k) for k in kinds]
            ),
            uia.CreatePropertyCondition(uia_api.UIA_IsOffscreenPropertyId, False),
        )
        cache = uia.CreateCacheRequest()
        cache.AddProperty(uia_api.UIA_BoundingRectanglePropertyId)
        cache.AutomationElementMode = uia_api.AutomationElementMode_None
        descendants = uia_api.TreeScope_Descendants
    except Exception as exc:  # noqa: BLE001 - no UI Automation: whole windows only
        sys.stderr.write(f"appshot-picker: window parts unavailable ({exc!r}).\n")
        return None

    def scan(handle: int) -> list[list[int]]:
        root = uia.ElementFromHandle(handle)
        found = root.FindAllBuildCache(descendants, wanted, cache)
        rects: list[list[int]] = []
        for index in range(min(int(found.Length), MAX_PARTS)):
            box = found.GetElement(index).CachedBoundingRectangle
            width, height = box.right - box.left, box.bottom - box.top
            if width > 0 and height > 0:
                rects.append([int(box.left), int(box.top), int(width), int(height)])
        return rects

    return scan


__all__ = ["MAX_PARTS", "PART_KINDS", "ElementScanner", "uia_scan"]
