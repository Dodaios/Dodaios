"""Architecture kit. Importing a module registers its pieces with lib.kit;
``load_all()`` registers every piece (deck builders and lookdev call it)."""

from __future__ import annotations

from importlib import import_module

MODULES = ("walls", "corridor", "ceiling", "floors", "pit", "structure", "doors", "windows", "hull")


def load_all() -> None:
    for module in MODULES:
        import_module(f"{__name__}.{module}")
