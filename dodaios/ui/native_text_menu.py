"""The engine's own right-click menu for text in the desktop window (Windows).

pywebview switches WebView2's built-in context menu off outside debug mode, so
a right-click in a text field showed only the app's small Cut / Copy / Paste
menu, without the spelling suggestions for the word under the cursor.

This module turns the built-in menu back on for text only:

* A right-click on an editable field or on selected text opens WebView2's own
  menu, with its spelling suggestions, minus the page items and submenus that make no
  sense in an app (Back, Reload, Print, Writing direction, More tools).
* Everywhere else the native menu is cancelled, so the app's own menus stay
  the only ones there.
* The page learns it may leave text right-clicks to the engine through
  ``window.__DODAIOS_NATIVE_TEXT_MENU`` (see ``EditContextMenu.tsx``). The flag
  is set only after the filter is in place; without it the app's menu stays.

Installed by patching ``EdgeChrome.on_webview_ready`` before ``webview.start()``.
Never raises: a missing .NET piece just leaves the old behaviour.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

log = logging.getLogger(__name__)

PAGE_FLAG_SCRIPT = "window.__DODAIOS_NATIVE_TEXT_MENU = true;"

# Native items that belong to a browser page, not to a text box in an app.
HIDDEN_ITEM_NAMES = frozenset(
    {
        "back",
        "forward",
        "reload",
        "saveAs",
        "print",
        "createQrCode",
        "share",
        "webCapture",
        "inspectElement",
        "copyLinkToHighlight",
        "openLinkInNewWindow",
        "saveLinkAs",
        "saveImageAs",
        "saveMediaAs",
    }
)


def wants_native_menu(*, is_editable: bool, has_selection: bool) -> bool:
    """True when the engine's menu should open for this right-click."""
    return is_editable or has_selection


def prune_menu(items: Any) -> None:
    """Drop page items and submenus (Writing direction, More tools), then the
    separators left standing at an edge or next to another separator."""
    for index in range(items.Count - 1, -1, -1):
        item = items[index]
        if str(item.Name) in HIDDEN_ITEM_NAMES or str(item.Kind) == "Submenu":
            items.RemoveAt(index)
    previous_was_separator = True  # a separator at the top goes too
    index = 0
    while index < items.Count:
        is_separator = str(items[index].Kind) == "Separator"
        if is_separator and previous_was_separator:
            items.RemoveAt(index)
            continue
        previous_was_separator = is_separator
        index += 1
    if items.Count and str(items[items.Count - 1].Kind) == "Separator":
        items.RemoveAt(items.Count - 1)


def on_context_menu_requested(_sender: Any, args: Any) -> None:
    """Show the native menu for text only, without the page items."""
    try:
        target = args.ContextMenuTarget
        if not wants_native_menu(
            is_editable=bool(target.IsEditable),
            has_selection=bool(target.HasSelection),
        ):
            args.Handled = True  # no menu at all; the page shows its own
            return
        prune_menu(args.MenuItems)
    except Exception:  # noqa: BLE001 - a menu must never take the UI thread down
        log.exception("native_text_menu: filtering the menu failed")


def enable_on_core(core: Any) -> bool:
    """Wire one CoreWebView2. Returns True when the native text menu is live."""
    try:
        core.ContextMenuRequested += on_context_menu_requested
    except Exception as exc:  # noqa: BLE001 - runtime too old for the event
        log.warning("native_text_menu: no ContextMenuRequested event (%s)", exc)
        return False
    core.Settings.AreDefaultContextMenusEnabled = True
    core.AddScriptToExecuteOnDocumentCreatedAsync(PAGE_FLAG_SCRIPT)
    # The page may already be loaded when the WebView reports ready.
    core.ExecuteScriptAsync(PAGE_FLAG_SCRIPT)
    return True


def install_native_text_menu() -> bool:
    """Patch pywebview so every WebView2 window gets the text menu."""
    if sys.platform != "win32":
        return False
    try:
        import webview.platforms.edgechromium as ec
    except Exception as exc:  # noqa: BLE001 - pywebview/.NET not present
        log.warning("native_text_menu: WebView2 backend unavailable (%s)", exc)
        return False
    if getattr(ec.EdgeChrome, "_dodaios_text_menu_installed", False):
        return True
    original = ec.EdgeChrome.on_webview_ready

    def _patched_on_webview_ready(self, sender, args):  # noqa: ANN001, ANN202
        result = original(self, sender, args)
        try:
            core = sender.CoreWebView2
            if core is not None and enable_on_core(core):
                log.info("native_text_menu: native text menu enabled")
        except Exception:  # noqa: BLE001 - the old menu stays
            log.exception("native_text_menu: enabling failed")
        return result

    ec.EdgeChrome.on_webview_ready = _patched_on_webview_ready  # type: ignore[method-assign]
    ec.EdgeChrome._dodaios_text_menu_installed = True  # type: ignore[attr-defined]
    return True
