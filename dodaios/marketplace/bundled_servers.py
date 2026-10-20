"""Which stored MCP commands start a server that ships inside this package.

A catalog entry starts a bundled server with ``python -m <module>``. That
command is stored configuration, not a reference the code owns: the seed
catalog carries it, a user's catalog override keeps its own copy of it, and
the browser evidence of a plugin is bound to it. So a command names its module
the way it was published, and every reader that has to recognise a bundled
server accepts the module under each name this package has been importable as.
The earlier names keep resolving to the same modules, so such a command also
still starts.

Import-light: the route layer and the worker bridge both import this.
"""

from __future__ import annotations

from collections.abc import Sequence

from dodaios.core.branding import LEGACY_PACKAGE_NAMES

__all__ = [
    "AMD_SERVER_MODULES",
    "CONNECTED_SERVER_MODULES",
    "runs_amd_server",
    "runs_bundled_server",
    "runs_connected_server",
]

# Today's import name first, read off this module so that it is right wherever
# the package lives, then every name it was published under: a stored command
# that uses one of those is as much a bundled server.
_PACKAGE_NAMES = tuple(dict.fromkeys((__name__.partition(".")[0], *LEGACY_PACKAGE_NAMES)))


def _module_names(suffix: str) -> frozenset[str]:
    return frozenset(f"{package}.{suffix}" for package in _PACKAGE_NAMES)


#: The in-process REST bridge most first-party connectors run through.
CONNECTED_SERVER_MODULES = _module_names("plugins.tool.connected_server")
#: The AMD GPU status server.
AMD_SERVER_MODULES = _module_names("marketplace.amd_mcp")


def _module_run(command: Sequence[object]) -> str | None:
    """The module of ``<interpreter> -m <module> ...``, else ``None``."""
    if len(command) > 2 and command[1] == "-m" and isinstance(command[2], str):
        return command[2]
    return None


def runs_connected_server(command: Sequence[object]) -> bool:
    """True when ``command`` starts the bundled REST bridge."""
    return _module_run(command) in CONNECTED_SERVER_MODULES


def runs_amd_server(command: Sequence[object]) -> bool:
    """True when ``command`` starts the bundled AMD GPU server."""
    return _module_run(command) in AMD_SERVER_MODULES


def runs_bundled_server(command: Sequence[object]) -> bool:
    """True when ``command`` starts any server shipped inside this package."""
    return runs_connected_server(command) or runs_amd_server(command)
