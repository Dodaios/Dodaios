"""``<frozen exe> -m <module>`` for the package's own modules.

A PyInstaller executable has no ``-m``. Plugin commands stored in the catalog
(``python -m dodaios.plugins.tool.connected_server <id>``) are rewritten to
start the app's own executable (``sys.executable``), so the executable has to
answer that form or the server never starts and the plugin has no tools.
"""

from __future__ import annotations

import runpy
import sys

from dodaios.core.branding import LEGACY_PACKAGE_NAMES

__all__ = ["run_package_module"]

_PACKAGE = __name__.partition(".")[0]


def _own_module(module: str) -> str | None:
    """``module`` under today's package name, or ``None`` when it is not ours."""
    head, dot, rest = module.partition(".")
    if not dot or not rest:
        return None
    if head == _PACKAGE:
        return module
    if head in LEGACY_PACKAGE_NAMES:
        return f"{_PACKAGE}.{rest}"
    return None


def run_package_module(module: str, args: list[str]) -> int:
    """Run ``module`` as ``__main__`` with ``args``; 2 for a module that is not ours."""
    target = _own_module(module)
    if target is None:
        if sys.stderr is not None:
            sys.stderr.write(f"-m is only available for {_PACKAGE} modules, not {module!r}\n")
        return 2
    sys.argv = [target, *args]
    runpy.run_module(target, run_name="__main__", alter_sys=True)
    return 0
