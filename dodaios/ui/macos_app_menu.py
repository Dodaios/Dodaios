"""'Restart Dodaios' in the macOS application menu.

People restart the app often (a pending setting, a stuck connector), and the
only way was Settings. pywebview 6.1+ puts the items of a ``Menu`` titled
``__app__`` into the application menu, the one that holds "Quit Dodaios", and
keeps them when it rebuilds the menu bar. Older pywebview would show
``__app__`` as a menu of its own, so the item is only added where it works.

The click goes through the same restart as Settings. Like the Settings button
it asks first while missions run, because a restart ends them.
"""

from __future__ import annotations

import importlib.metadata
import logging
import re
import sys
from collections.abc import Callable, Sequence
from typing import Any

from dodaios.core.branding import PRODUCT_NAME

log = logging.getLogger(__name__)

#: pywebview's marker for items that belong in the application menu.
MENU_TITLE = "__app__"
_MIN_PYWEBVIEW = (6, 1)


def supports_app_menu(version: str) -> bool:
    """True for a pywebview version that places ``__app__`` items in the app menu."""
    match = re.match(r"(\d+)\.(\d+)", version or "")
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= _MIN_PYWEBVIEW


def _installed_pywebview() -> str:
    try:
        return importlib.metadata.version("pywebview")
    except importlib.metadata.PackageNotFoundError:
        return ""


def restart_from_menu(
    restart: Callable[[], bool],
    running_missions: Callable[[], Sequence[str]],
    confirm: Callable[[str, str], bool],
) -> bool:
    """Restart the app; while missions run, only after the person agrees."""
    running = list(running_missions())
    if running:
        message = f"{len(running)} running mission(s) will stop. Restart {PRODUCT_NAME} anyway?"
        if not confirm(f"Restart {PRODUCT_NAME}", message):
            log.info("Menu restart cancelled: %d mission(s) running", len(running))
            return False
    log.info("Desktop restart requested through the application menu")
    return bool(restart())


def app_menu(
    *,
    restart: Callable[[], bool],
    running_missions: Callable[[], Sequence[str]],
    confirm: Callable[[str, str], bool],
    platform: str | None = None,
    pywebview_version: str | None = None,
) -> list[Any]:
    """The ``menu`` list for ``webview.start``: empty where it does not apply."""
    if (platform or sys.platform) != "darwin":
        return []
    version = _installed_pywebview() if pywebview_version is None else pywebview_version
    if not supports_app_menu(version):
        log.info("pywebview %s has no application-menu items; no Restart item", version or "?")
        return []
    from webview.menu import Menu, MenuAction

    return [
        Menu(
            MENU_TITLE,
            [
                MenuAction(
                    f"Restart {PRODUCT_NAME}",
                    lambda: restart_from_menu(restart, running_missions, confirm),
                )
            ],
        )
    ]
