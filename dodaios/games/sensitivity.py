"""Mouse sensitivity maths: cm/360, eDPI and converting between games.

A game turns the camera by ``yaw * sens`` degrees for every mouse count, and
a mouse sends ``dpi`` counts per inch. So one full turn takes
``360 / (yaw * sens * dpi)`` inches, times 2.54 for centimetres. Two settings
feel the same when that distance is equal, which gives the conversion
``sens_b = sens_a * yaw_a * dpi_a / (yaw_b * dpi_b)``.

Only hip-fire is converted: scoped and ADS multipliers depend on each game's
field of view and are left to the player.
"""

from __future__ import annotations

import math

CM_PER_INCH = 2.54


def _check(name: str, value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def cm_per_360(yaw: float, sens: float, dpi: float) -> float:
    """Centimetres of mouse travel for one full 360° turn."""
    yaw, sens, dpi = _check("yaw", yaw), _check("sens", sens), _check("dpi", dpi)
    return 360.0 / (yaw * sens * dpi) * CM_PER_INCH


def edpi(sens: float, dpi: float) -> float:
    """Effective DPI: sensitivity times DPI (only comparable within one game)."""
    return _check("sens", sens) * _check("dpi", dpi)


def convert(
    sens: float,
    from_yaw: float,
    to_yaw: float,
    from_dpi: float,
    to_dpi: float | None = None,
) -> float:
    """The sensitivity in the target game that gives the same cm/360."""
    to_dpi = from_dpi if to_dpi is None else to_dpi
    counts = _check("sens", sens) * _check("from_yaw", from_yaw) * _check("from_dpi", from_dpi)
    return counts / (_check("to_yaw", to_yaw) * _check("to_dpi", to_dpi))


def sens_for_cm(cm: float, yaw: float, dpi: float) -> float:
    """The sensitivity that gives ``cm`` centimetres per 360° turn."""
    return 360.0 * CM_PER_INCH / (_check("cm", cm) * _check("yaw", yaw) * _check("dpi", dpi))
