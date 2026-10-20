"""The import names of the package under test.

A guard that forbids or blocks imports of the package has to cover every name
the package can be imported as: the one it has today and each earlier one that
still resolves to the same modules. Tests take the names from here instead of
spelling one out, so a guard keeps guarding when the package directory moves.
"""

from __future__ import annotations

import dodaios as _package
from dodaios.core.branding import LEGACY_PACKAGE_NAMES

__all__ = ["PACKAGE_NAME", "PACKAGE_NAMES", "is_package_module"]

#: The name the package is imported as today.
PACKAGE_NAME = _package.__name__
#: Every importable name, today's first.
PACKAGE_NAMES = tuple(dict.fromkeys((PACKAGE_NAME, *LEGACY_PACKAGE_NAMES)))


def is_package_module(name: str) -> bool:
    """True when ``name`` is the package or a module inside it, under any of its names."""
    return name.partition(".")[0] in PACKAGE_NAMES
