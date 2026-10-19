"""Native hosts for the canonical Jarvis Bar control strip.

``JarvisBarOverlay`` is imported lazily so this package stays importable on a
headless host (no tkinter) for capability probing and tests.
"""
from __future__ import annotations

__all__ = ["JarvisBarOverlay", "NullOverlay"]


def __getattr__(name: str):  # lazy: avoid importing tkinter on headless import
    if name == "JarvisBarOverlay":
        from dodaios.ui.dodaiosbar.overlay import JarvisBarOverlay

        return JarvisBarOverlay
    if name == "NullOverlay":
        from dodaios.ui.dodaiosbar.null_overlay import NullOverlay

        return NullOverlay
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
