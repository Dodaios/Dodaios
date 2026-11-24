"""Only http(s) leaves the window through pywebview's new-window handlers.

pywebview's platform modules (edgechromium, cocoa, gtk, qt, cef, mshtml) hand
every new-window request to ``webbrowser.open``, and on Windows that is
``os.startfile``: a page framed in the built-in Browser tab could launch any
registered URI handler. We do not edit the library. After pywebview imports its
platform module (inside ``webview.initialize``), the ``webbrowser`` name those
modules use is swapped for a shim that passes only ``http:``/``https:`` URLs to
the real ``webbrowser.open`` and logs and drops everything else.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from urllib.parse import urlparse

from loguru import logger

_SAFE_SCHEMES = frozenset({"http", "https"})


class _GuardedWebbrowser:
    """Stands in for the ``webbrowser`` module; ``open`` filters the scheme."""

    def __init__(self, real: Any) -> None:
        self._real = real

    def open(self, url: Any, *args: Any, **kwargs: Any) -> bool:
        text = str(url).strip()
        if urlparse(text).scheme.lower() not in _SAFE_SCHEMES:
            logger.warning("webview new-window request refused (not http/https): {!r}", text[:80])
            return False
        return bool(self._real.open(text, *args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def guard_platform_modules(modules: dict[str, Any] | None = None) -> int:
    """Swap ``webbrowser`` in every loaded ``webview.platforms.*`` module.

    Returns how many modules were patched. Never raises.
    """
    patched = 0
    try:
        table = sys.modules if modules is None else modules
        for name, module in list(table.items()):
            if not name.startswith("webview.platforms.") or module is None:
                continue
            current = getattr(module, "webbrowser", None)
            if current is None or isinstance(current, _GuardedWebbrowser):
                continue
            if not isinstance(current, types.ModuleType):
                continue
            module.webbrowser = _GuardedWebbrowser(current)
            patched += 1
    except Exception as exc:  # noqa: BLE001 — fail safe: the app must still start
        logger.warning("webview new-window guard could not be installed: {}", exc)
    return patched


def install_new_window_guard(webview_module: Any) -> bool:
    """Guard the platform module pywebview loads in ``webview.initialize``.

    Wraps ``webview.initialize`` so the shim goes in right after the platform
    module is imported and before any window exists. Returns whether the hook
    is in place; on any layout surprise it logs a warning and returns False.
    """
    try:
        original = webview_module.initialize
        if getattr(original, "_dodaios_guarded", False):
            return True

        def initialize(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            guard_platform_modules()
            return result

        initialize._dodaios_guarded = True  # type: ignore[attr-defined]
        webview_module.initialize = initialize
        guard_platform_modules()  # a platform module that is already loaded
        return True
    except Exception as exc:  # noqa: BLE001 — fail safe: the app must still start
        logger.warning("webview new-window guard not installed: {}", exc)
        return False


__all__ = ["guard_platform_modules", "install_new_window_guard"]
