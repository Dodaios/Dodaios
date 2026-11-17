"""Per-pixel transparency for the Dodaios Bar's Tk window on Windows.

The Tk surface used to cut the bar out with a colour key: every pixel was
either fully drawn or fully gone. A colour key cannot show a pixel that is
half covered, so the rounded rim came out as stair steps and thin lines as
grey smudges. ``UpdateLayeredWindow`` instead hands Windows a premultiplied
BGRA bitmap, so the edge of the pill blends with whatever is behind it.

How it fits the Tk window:

- Tk paints its own canvas into the window, but once a window is layered and
  fed through ``UpdateLayeredWindow`` Windows shows only that bitmap, so the
  canvas stays as the input surface (clicks, hover, drag and drop) and its
  pixels never reach the screen.
- Windows hit-tests a layered window on its alpha: a fully transparent pixel
  lets the click through to the window below, exactly like the colour key.
- ``SetLayeredWindowAttributes`` (Tk's ``-alpha`` and ``-transparentcolor``)
  and ``UpdateLayeredWindow`` exclude each other on one window, so a surface
  that uses this class must not set either attribute.
- Tk replaces its wrapper window when ``overrideredirect`` changes. The
  wrapper is looked up again on every frame and made layered again when it is
  new, so a replaced wrapper costs one frame and nothing more.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Any

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_ULW_ALPHA = 0x00000002
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_DIB_RGB_COLORS = 0


def premultiplied_bgra(frame: Image.Image) -> bytes:
    """Top-down premultiplied BGRA bytes of ``frame``: what Windows composites."""
    rgba = np.asarray(frame.convert("RGBA"), dtype=np.uint16)
    alpha = rgba[..., 3]
    out = np.empty(rgba.shape, dtype=np.uint8)
    for dst, src in ((0, 2), (1, 1), (2, 0)):
        out[..., dst] = (rgba[..., src] * alpha + 127) // 255
    out[..., 3] = alpha
    return out.tobytes()


class LayeredWindow:
    """Shows RGBA frames on a Tk toplevel with true per-pixel alpha (Windows).

    Every method is best-effort and returns ``False`` instead of raising, so
    the caller can fall back to the colour key.
    """

    def __init__(self, root: Any) -> None:
        self._root = root
        self._hwnd = 0
        self._api: Any = None
        self._dc = None
        self._bitmap = None
        self._old_bitmap = None
        self._bits = None
        self._size: tuple[int, int] = (0, 0)
        self._last: Image.Image | None = None

    @staticmethod
    def supported() -> bool:
        return sys.platform == "win32"

    # -- native setup ------------------------------------------------------
    def _load(self) -> Any:
        if self._api is not None:
            return self._api
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [
                ("BlendOp", ctypes.c_ubyte),
                ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte),
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_long.restype = ctypes.c_ssize_t
        user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND,
            wintypes.HDC,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.HDC,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(BLENDFUNCTION),
            wintypes.DWORD,
        ]
        user32.UpdateLayeredWindow.restype = wintypes.BOOL
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.c_void_p,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.DeleteDC.restype = wintypes.BOOL

        api = type("Api", (), {})()
        api.user32, api.gdi32 = user32, gdi32
        api.get_long, api.set_long = get_long, set_long
        api.BLENDFUNCTION, api.BITMAPINFOHEADER = BLENDFUNCTION, BITMAPINFOHEADER
        self._api = api
        return api

    def _outer_hwnd(self, api: Any) -> int:
        inner = int(self._root.winfo_id())
        return int(api.user32.GetParent(inner) or inner)

    def _ensure_layered(self, api: Any) -> int:
        hwnd = self._outer_hwnd(api)
        if hwnd != self._hwnd:
            style = int(api.get_long(hwnd, _GWL_EXSTYLE))
            if not style & _WS_EX_LAYERED:
                api.set_long(hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED)
            self._hwnd = hwnd
        return hwnd

    def _reset_layered(self, api: Any, hwnd: int) -> None:
        try:
            style = int(api.get_long(hwnd, _GWL_EXSTYLE))
            api.set_long(hwnd, _GWL_EXSTYLE, style & ~_WS_EX_LAYERED)
            api.set_long(hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED)
        except Exception:  # noqa: BLE001 - best-effort repair
            log.debug("bar layered style reset failed", exc_info=True)
        self._hwnd = 0

    def _ensure_bitmap(self, api: Any, size: tuple[int, int]) -> bool:
        if self._dc is not None and self._size == size:
            return True
        self._free_bitmap()
        w, h = size
        header = api.BITMAPINFOHEADER(
            ctypes.sizeof(api.BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0
        )
        bits = ctypes.c_void_p()
        dc = api.gdi32.CreateCompatibleDC(None)
        if not dc:
            return False
        bitmap = api.gdi32.CreateDIBSection(
            dc, ctypes.byref(header), _DIB_RGB_COLORS, ctypes.byref(bits), None, 0
        )
        if not bitmap or not bits.value:
            api.gdi32.DeleteDC(dc)
            return False
        self._dc, self._bitmap, self._bits, self._size = dc, bitmap, bits, size
        self._old_bitmap = api.gdi32.SelectObject(dc, bitmap)
        return True

    def _free_bitmap(self) -> None:
        api = self._api
        if api is None or self._dc is None:
            return
        try:
            if self._old_bitmap:
                api.gdi32.SelectObject(self._dc, self._old_bitmap)
            if self._bitmap:
                api.gdi32.DeleteObject(self._bitmap)
            api.gdi32.DeleteDC(self._dc)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            log.debug("bar layered bitmap cleanup failed", exc_info=True)
        self._dc = self._bitmap = self._old_bitmap = self._bits = None
        self._size = (0, 0)

    # -- public ------------------------------------------------------------
    def present(self, frame: Image.Image, opacity: float = 1.0) -> bool:
        """Show ``frame`` (RGBA, window size) at window ``opacity`` (0 to 1)."""
        if not self.supported():
            return False
        try:
            api = self._load()
            hwnd = self._ensure_layered(api)
            size = (int(frame.width), int(frame.height))
            if size[0] <= 0 or size[1] <= 0 or not self._ensure_bitmap(api, size):
                return False
            data = premultiplied_bgra(frame)
            ctypes.memmove(self._bits, data, len(data))
            win_size = (ctypes.c_long * 2)(*size)
            origin = (ctypes.c_long * 2)(0, 0)
            alpha = max(0, min(255, round(float(opacity) * 255)))
            blend = api.BLENDFUNCTION(_AC_SRC_OVER, 0, alpha, _AC_SRC_ALPHA)
            ok = bool(
                api.user32.UpdateLayeredWindow(
                    hwnd,
                    None,
                    None,
                    ctypes.byref(win_size),
                    self._dc,
                    ctypes.byref(origin),
                    0,
                    ctypes.byref(blend),
                    _ULW_ALPHA,
                )
            )
            if ok:
                self._last = frame
            else:
                # Another layered mode (Tk's -alpha) claimed the window. Turning
                # the layered style off and on again hands it back to
                # UpdateLayeredWindow on the next frame.
                log.debug("UpdateLayeredWindow failed: %s", ctypes.get_last_error())
                self._reset_layered(api, hwnd)
            return ok
        except Exception:  # noqa: BLE001 - the bar must degrade, never crash
            log.debug("bar layered present failed", exc_info=True)
            return False

    def set_opacity(self, opacity: float) -> bool:
        """Show the last frame again at ``opacity`` (the reveal fade)."""
        if self._last is None:
            return False
        return self.present(self._last, opacity)

    def forget_window(self) -> None:
        """The wrapper may have been replaced: look it up on the next frame."""
        self._hwnd = 0

    def close(self) -> None:
        self._free_bitmap()
        self._last = None
