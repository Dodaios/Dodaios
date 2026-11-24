"""Late access to ``dodaios.ui.web.server``.

The module-level names tests patch (``DIST_DIR``, the timeouts, ...) live in
``server``; the parts read them through it at call time so a patch is seen.
"""

from __future__ import annotations

from types import ModuleType


def server_module() -> ModuleType:
    from dodaios.ui.web import server

    return server
