"""The macOS share sheet for the desktop WebView.

The Artifacts stage's "Share" button stages a file (``dodaios/ui/web/artifact_share.py``)
and posts its path here through a dedicated WKWebView script-message handler,
``window.webkit.messageHandlers.jarvisShare``. The handler runs on AppKit's
main thread and opens ``NSSharingServicePicker`` next to the button that was
pressed — the same sheet Finder and Preview offer: AirDrop, Mail, Messages,
Notes, "Save to Files" and whatever share extensions the person installed.

The handler exists in JavaScript only when this bridge registered, so the
frontend's capability check (`canNativeShare`) is truthful: elsewhere (a plain
browser, Windows, Linux, a headless server) the stage downloads the staged
file instead.

Path safety: the renderer can only name files inside the share staging folder
(:func:`dodaios.ui.web.artifact_share.share_folder`). A compromised page cannot
put any other file of the person's into a share sheet.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Discriminator the frontend puts first in its message (src/lib/nativeShare.ts).
MESSAGE_TAG = "jarvis-share"
#: Handler name — MUST match `MACOS_MESSAGE_HANDLER` in src/lib/nativeShare.ts.
MACOS_MESSAGE_HANDLER = "jarvisShare"


class ShareRequest:
    """One parsed request: the files and where the button sits (CSS pixels)."""

    __slots__ = ("files", "rect")

    def __init__(self, files: list[str], rect: tuple[float, float, float, float]) -> None:
        self.files = files
        self.rect = rect


def parse_share_message(message: object) -> ShareRequest | None:
    """Our request, or None when a message is not ours or is malformed."""
    data = message
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (TypeError, ValueError):  # not JSON, so not one of ours
            return None
    if (
        not isinstance(data, Sequence)
        or isinstance(data, (str, bytes, bytearray))
        or len(data) < 2
        or data[0] != MESSAGE_TAG
        or not isinstance(data[1], Mapping)
    ):
        return None
    body = data[1]
    raw_files = body.get("files", [])
    if not isinstance(raw_files, Sequence) or isinstance(raw_files, (str, bytes, bytearray)):
        return None
    rect_raw = body.get("rect") or {}
    if not isinstance(rect_raw, Mapping):
        rect_raw = {}

    def number(key: str) -> float:
        try:
            return float(rect_raw.get(key, 0) or 0)
        except (TypeError, ValueError):  # a missing coordinate anchors at the corner
            return 0.0

    rect = (number("x"), number("y"), number("width"), number("height"))
    return ShareRequest([str(path) for path in raw_files], rect)


def allowed_files(paths: Sequence[str], base: Path) -> list[str]:
    """The existing regular files inside ``base``; everything else is dropped."""
    try:
        root = base.resolve()
    except OSError:  # no staging folder means nothing was staged
        return []
    out: list[str] = []
    for raw in paths:
        try:
            resolved = Path(raw).resolve()
        except OSError:  # an unreadable path is simply not shared
            continue
        if not resolved.is_file() or root not in resolved.parents:
            log.debug("native_share: %r is not a staged file, skipped", raw)
            continue
        out.append(str(resolved))
    return out


def view_rect(
    webview: Any, rect: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """A CSS-pixel rectangle in the WebView's own view coordinates."""
    x, y, width, height = rect
    zoom = 1.0
    try:
        zoom = float(webview.pageZoom()) or 1.0
    except Exception:  # noqa: BLE001 — older WebKit has no pageZoom; points equal CSS pixels
        zoom = 1.0
    x, y, width, height = x * zoom, y * zoom, max(width * zoom, 1.0), max(height * zoom, 1.0)
    try:
        flipped = bool(webview.isFlipped())
    except Exception:  # noqa: BLE001 — assume AppKit's default, origin at the bottom
        flipped = False
    if not flipped:
        bounds_height = float(webview.bounds().size.height)
        y = bounds_height - y - height
    return x, y, width, height


def install_native_share() -> bool:
    """Register the share-sheet handler in every new desktop window.

    Call once before ``webview.start()``. macOS only; returns False elsewhere
    and never raises — a missing dependency just leaves the stage on its
    download fallback.
    """
    if sys.platform != "darwin":
        return False
    try:
        import AppKit  # type: ignore[import-not-found, import-untyped] # noqa: N813, PLC0415
        import Foundation  # type: ignore[import-not-found, import-untyped] # noqa: N813, PLC0415
        import objc  # type: ignore[import-not-found, import-untyped] # noqa: PLC0415
        import webview.platforms.cocoa as cocoa  # type: ignore[import-untyped] # noqa: PLC0415

        from dodaios.ui.web.artifact_share import share_folder  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — optional desktop internals absent
        log.warning("native_share: share sheet bridge unavailable (%s)", exc)
        return False

    browser_class = cocoa.BrowserView
    if getattr(browser_class, "_jarvis_share_installed", False):
        return True

    try:
        script_message_protocol = objc.protocolNamed("WKScriptMessageHandler")

        class JarvisShareMessageHandler(  # type: ignore[call-arg] # noqa: D101
            AppKit.NSObject,
            protocols=[script_message_protocol],
        ):
            def userContentController_didReceiveScriptMessage_(
                self,
                _controller: Any,
                message: Any,
            ) -> None:
                request = parse_share_message(message.body())
                if request is None:
                    return
                try:
                    files = allowed_files(request.files, share_folder())
                    if not files:
                        return
                    webview = message.webView()
                    items = [Foundation.NSURL.fileURLWithPath_(path) for path in files]
                    picker = AppKit.NSSharingServicePicker.alloc().initWithItems_(items)
                    x, y, width, height = view_rect(webview, request.rect)
                    # The picker must outlive this call; the next share replaces it.
                    self.picker = picker
                    picker.showRelativeToRect_ofView_preferredEdge_(
                        AppKit.NSMakeRect(x, y, width, height),
                        webview,
                        AppKit.NSMinYEdge if not bool(webview.isFlipped()) else AppKit.NSMaxYEdge,
                    )
                except Exception:  # noqa: BLE001 — contain failures on AppKit's UI thread
                    log.exception("native_share: share sheet failed")

        original_init = browser_class.__init__

        def _patched_browser_init(self: Any, window: Any) -> None:
            original_init(self, window)
            try:
                handler = JarvisShareMessageHandler.alloc().init()
                self.webview.configuration().userContentController().addScriptMessageHandler_name_(
                    handler,
                    MACOS_MESSAGE_HANDLER,
                )
                self._jarvis_share_message_handler = handler
            except Exception:  # noqa: BLE001 — window creation must still succeed
                log.exception("native_share: WKWebView handler registration failed")

        browser_class.__init__ = _patched_browser_init  # type: ignore[method-assign]
        browser_class._jarvis_share_original_init = original_init  # type: ignore[attr-defined]
        browser_class._jarvis_share_installed = True  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — pywebview/AppKit internals changed
        log.warning("native_share: share sheet bridge unavailable (%s)", exc)
        return False

    log.info("native_share: macOS share sheet installed")
    return True
