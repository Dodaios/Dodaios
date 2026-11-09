"""The rendered-pixel colour ban of art-pipeline 8.3 (pure Python).

A pixel of a reference view or VFX frame (UI hidden) is banned when its HSV
hue lies in 160-330 degrees with saturation above 0.25 and value above 0.08.
A14.3 passes at 0 banned pixels.
"""

from __future__ import annotations

import colorsys
from collections.abc import Iterable

HUE_LO = 160.0
HUE_HI = 330.0
MIN_SAT = 0.25
MIN_VALUE = 0.08


def is_banned(r: int, g: int, b: int) -> bool:
    """`r, g, b` are 8-bit display values."""
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return HUE_LO <= h * 360.0 <= HUE_HI and s > MIN_SAT and v > MIN_VALUE


def count_banned(pixels: Iterable[tuple[int, int, int]]) -> int:
    return sum(1 for p in pixels if is_banned(*p[:3]))


def count_banned_image(path) -> tuple[int, int]:
    """(banned, total) pixels of a PNG; needs Pillow and numpy."""
    import numpy as np
    from PIL import Image

    img = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    mx = img.max(axis=-1)
    d = mx - img.min(axis=-1)
    sat = np.where(mx > 0, d / np.maximum(mx, 1e-12), 0.0)
    safe = np.maximum(d, 1e-12)
    hue = np.where(
        mx == r,
        ((g - b) / safe) % 6.0,
        np.where(mx == g, (b - r) / safe + 2.0, (r - g) / safe + 4.0),
    )
    hue = np.where(d > 0, hue * 60.0, 0.0)
    banned = (hue >= HUE_LO) & (hue <= HUE_HI) & (sat > MIN_SAT) & (mx > MIN_VALUE)
    return int(banned.sum()), int(banned.size)
