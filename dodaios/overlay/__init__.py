"""On-screen overlay surfaces and helpers.

This package holds the LIVE desktop-presence building blocks:

- ``virtual_cursor`` / ``system_cursor`` — the Jarvis cursor swap during
  Computer-Use actions.
- ``drop_bridge`` / ``drop_target`` — drag-and-drop onto the floating
  overlay.

Import the submodules directly. The on-screen bar and orb surfaces live in
``dodaios.ui.dodaiosbar``. The former OS-Level subprocess overlay
(edge-glow / mascot / cursor-trail IPC stack) was removed in 2026-07; the
Computer-Use screen indicator that replaced its edge-glow lives in
``dodaios.cu.indicator``.
"""

from __future__ import annotations

__all__: list[str] = []
