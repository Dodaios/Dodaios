"""Show a Tk window's RGBA frames through a native Core Animation layer (macOS).

Aqua-Tk 9 draws every window into a bitmap without an alpha channel
(``kCGImageAlphaNoneSkipLast``) and composites images onto it with
source-over. On a transparent overlay window that means two visible defects:
fully transparent pixels show as a black box, and a new animation frame never
erases the previous one, so the frames pile up on top of each other. Tk has no
option to change either.

So on macOS the pet's windows keep Tk only for what it does well (geometry,
mouse events, timers) and put their pixels on screen themselves:

* the Tk content view is made fully transparent (``alphaValue = 0``); AppKit's
  hit testing ignores a view's alpha, so clicks, drags and pointer
  enter/leave still reach Tk;
* a ``CALayer`` beside the content view (a sublayer of the window's frame
  view, so the view's alpha does not hide it) shows the frame. Each frame
  replaces the layer's contents outright, so nothing of the previous frame
  survives, and the frame's own alpha channel is what the desktop sees.

Every call runs on the Tk thread, which is the process's main thread on macOS
(Aqua-Tk and AppKit are main-thread only). Anything missing (no PyObjC, the
NSWindow not created yet, another platform) makes :meth:`present` return
``False`` so the caller keeps its Tk canvas path.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from PIL import Image

log = logging.getLogger("jarvis.orb")

#: Once a presenter failed for a reason that will not change (no PyObjC),
#: later presenters skip the import at once.
_UNAVAILABLE = False


def _appkit() -> tuple[Any, Any, Any] | None:
    """``(AppKit, Quartz, CoreFoundation)`` or ``None`` when PyObjC is missing."""
    global _UNAVAILABLE
    if _UNAVAILABLE or sys.platform != "darwin":
        return None
    try:
        import AppKit  # type: ignore[import-not-found] # noqa: PLC0415
        import CoreFoundation  # type: ignore[import-not-found] # noqa: PLC0415
        import Quartz  # type: ignore[import-not-found] # noqa: PLC0415
    except Exception:  # noqa: BLE001 — without PyObjC the Tk canvas path stays
        _UNAVAILABLE = True
        log.warning(
            "pyobjc unavailable: the pet on macOS falls back to Tk drawing, which "
            "leaves a black box and stacked frames behind (install the "
            "[desktop-macos] extra)."
        )
        return None
    return AppKit, Quartz, CoreFoundation


def native_frames_available() -> bool:
    """True on macOS when PyObjC can put frames on screen natively."""
    return _appkit() is not None


def cgimage_from_pil(image: Image.Image, quartz: Any, cf: Any) -> Any:
    """A ``CGImage`` holding a copy of ``image``'s pixels (straight RGBA)."""
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    width, height = rgba.size
    raw = rgba.tobytes("raw", "RGBA")
    data = cf.CFDataCreate(None, raw, len(raw))  # copies: no Python buffer stays referenced
    provider = quartz.CGDataProviderCreateWithCFData(data)
    space = quartz.CGColorSpaceCreateWithName(quartz.kCGColorSpaceSRGB)
    return quartz.CGImageCreate(
        width,
        height,
        8,
        32,
        width * 4,
        space,
        quartz.kCGImageAlphaLast | quartz.kCGBitmapByteOrderDefault,
        provider,
        None,
        False,
        quartz.kCGRenderingIntentDefault,
    )


class MacLayerPresenter:
    """Puts RGBA frames of one Tk toplevel on screen through a native layer."""

    def __init__(self, window: Any, *, name: str = "pet window") -> None:
        self._window = window
        self._name = name
        self._nswindow: Any = None
        self._view: Any = None
        self._layer: Any = None
        self._last: Image.Image | None = None
        self._hidden_views: list[Any] = []
        self._warned = False

    # -- attach ---------------------------------------------------------

    def _find_nswindow(self, appkit: Any) -> Any:
        """The NSWindow Tk made for this toplevel, or ``None`` before it exists."""
        try:
            wanted = int(self._window.winfo_toplevel().winfo_id())
        except Exception:  # noqa: BLE001 — a destroyed window has no id
            return None
        for candidate in appkit.NSApp.windows():
            tk_window = getattr(candidate, "tkWindow", None)
            if tk_window is None:
                continue
            try:
                if int(tk_window()) == wanted:
                    return candidate
            except Exception:  # noqa: BLE001 — a window being torn down
                log.debug("%s: skipped an NSWindow being torn down", self._name, exc_info=True)
        return None

    def _attached(self) -> bool:
        """Still showing through the same NSWindow and content view."""
        nswindow, layer = self._nswindow, self._layer
        if nswindow is None or layer is None:
            return False
        try:
            return nswindow.contentView() is self._view and layer.superlayer() is not None
        except Exception:  # noqa: BLE001 — a released window
            return False

    def _attach(self, appkit: Any, quartz: Any) -> bool:
        nswindow = self._find_nswindow(appkit)
        if nswindow is None:
            return False
        view = nswindow.contentView()
        frame_view = view.superview() if view is not None else None
        host = frame_view.layer() if frame_view is not None else None
        if host is None:
            return False
        self.detach()
        layer = quartz.CALayer.layer()
        layer.setMagnificationFilter_(quartz.kCAFilterNearest)
        layer.setMinificationFilter_(quartz.kCAFilterNearest)
        layer.setContentsGravity_(quartz.kCAGravityResize)
        layer.setZPosition_(1000.0)
        # Keep the top-left anchor when the window grows or shrinks between
        # two frames (the frame view's layer is not flipped: y grows upwards).
        layer.setAutoresizingMask_(quartz.kCALayerMinYMargin | quartz.kCALayerMaxXMargin)
        layer.setActions_({"contents": None, "bounds": None, "position": None, "hidden": None})
        host.addSublayer_(layer)
        # Tk keeps drawing into its own (alpha-less) bitmap; nobody sees it.
        view.setAlphaValue_(0.0)
        # Some Tk windows carry an NSVisualEffectView behind the content view
        # with an opaque white fill; Tk's black bitmap used to cover it.
        hidden: list[Any] = []
        for sibling in frame_view.subviews():
            if sibling is view or sibling.isHidden():
                continue
            if type(sibling).__name__.startswith("NSVisualEffectView"):
                sibling.setHidden_(True)
                hidden.append(sibling)
        self._hidden_views = hidden
        self._nswindow, self._view, self._layer = nswindow, view, layer
        log.info("%s: frames shown through a native layer (macOS)", self._name)
        return True

    def detach(self) -> None:
        """Take the layer away and give the Tk view its own pixels back."""
        layer, view, hidden = self._layer, self._view, self._hidden_views
        self._nswindow = self._view = self._layer = None
        self._hidden_views = []
        try:
            if layer is not None:
                layer.removeFromSuperlayer()
            if view is not None:
                view.setAlphaValue_(1.0)
            for sibling in hidden:
                sibling.setHidden_(False)
        except Exception:  # noqa: BLE001 — the window may already be gone
            log.debug("%s: native layer detach failed", self._name, exc_info=True)

    # -- frames ---------------------------------------------------------

    def refresh(self) -> None:
        """Show the last frame again if Tk replaced the window's NSWindow."""
        last = self._last
        if last is None or _appkit() is None or self._attached():
            return
        self.present(last)

    def present(self, image: Image.Image) -> bool:
        """Show ``image`` (anchored top-left, 1 image pixel per point).

        ``False`` when the native path is not available right now; the caller
        then draws through Tk as before.
        """
        mods = _appkit()
        if mods is None:
            return False
        appkit, quartz, cf = mods
        self._last = image
        try:
            if not self._attached() and not self._attach(appkit, quartz):
                return False
            view, layer = self._view, self._layer
            view_frame = view.frame()
            width, height = image.size
            # The frame view's layer is not flipped: y grows upwards, so the
            # top-left anchor sits at the content view's top edge.
            top = view_frame.origin.y + view_frame.size.height
            quartz.CATransaction.begin()
            quartz.CATransaction.setDisableActions_(True)
            layer.setFrame_(((view_frame.origin.x, top - height), (width, height)))
            layer.setContents_(cgimage_from_pil(image, quartz, cf))
            quartz.CATransaction.commit()
            return True
        except Exception:  # noqa: BLE001 — never take the overlay down for a frame
            if not self._warned:
                self._warned = True
                log.warning("%s: native layer frame failed", self._name, exc_info=True)
            self.detach()
            return False
