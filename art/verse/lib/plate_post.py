"""Plate assembly maths shared by the cook and the tests (numpy only, no bpy).

Plates are rendered as border regions, so the GPU denoiser never holds more
than one region (bounded VRAM on 100 m decks); `regions()` plans them with an
overlap that is cropped away, so seams fall inside denoised context. The glow
(bloom) is computed once for the whole plate on a quarter-resolution
scene-linear image, with radii in metres so every deck blooms alike at any
density, and added back region by region. Memory stays at one region plus the
quarter-resolution glow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

REGION_MAX_PX = 4096
REGION_OVERLAP_PX = 64
REGION_ALIGN_PX = 16
GLOW_FACTOR = 4  # glow is computed at 1/GLOW_FACTOR resolution
BLOOM_THRESHOLD = 1.0  # scene-linear luminance where glow starts
BLOOM_STRENGTH = 0.12
BLOOM_RADII_M = (0.04, 0.15, 0.5)  # glow kernel sigmas, metres on the plate
BLOOM_WEIGHTS = (0.5, 0.3, 0.2)
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


@dataclass(frozen=True)
class Region:
    """Rendered (padded) rectangle and the inner part kept from it; [start, stop)."""

    row0: int
    row1: int
    col0: int
    col1: int
    inner_row0: int
    inner_row1: int
    inner_col0: int
    inner_col1: int

    def inner_slice(self) -> tuple[slice, slice]:
        """The inner part in the padded region's own pixel coordinates."""
        return (
            slice(self.inner_row0 - self.row0, self.inner_row1 - self.row0),
            slice(self.inner_col0 - self.col0, self.inner_col1 - self.col0),
        )


def _split(size: int, parts: int, align: int) -> list[tuple[int, int]]:
    edges = [min(size, round(size * i / parts / align) * align) for i in range(parts)] + [size]
    return list(zip(edges[:-1], edges[1:], strict=True))


def regions(
    width: int,
    height: int,
    max_px: int = REGION_MAX_PX,
    overlap: int = REGION_OVERLAP_PX,
    align: int = REGION_ALIGN_PX,
) -> list[Region]:
    """Cover a width x height frame with padded regions of at most max_px per side."""
    inner = max_px - 2 * overlap
    cols, rows = math.ceil(width / inner), math.ceil(height / inner)
    if cols == rows == 1:
        return [Region(0, height, 0, width, 0, height, 0, width)]
    plan = []
    for r0, r1 in _split(height, rows, align):
        for c0, c1 in _split(width, cols, align):
            plan.append(
                Region(
                    row0=max(0, r0 - overlap),
                    row1=min(height, r1 + overlap),
                    col0=max(0, c0 - overlap),
                    col1=min(width, c1 + overlap),
                    inner_row0=r0,
                    inner_row1=r1,
                    inner_col0=c0,
                    inner_col1=c1,
                )
            )
    return plan


def bright(linear: np.ndarray) -> np.ndarray:
    """The part of each pixel's energy above BLOOM_THRESHOLD (RGB, scene-linear)."""
    luminance = linear @ _LUMA
    excess = np.clip(luminance - BLOOM_THRESHOLD, 0.0, None) / np.maximum(luminance, 1e-6)
    return (linear * excess[..., None]).astype(np.float32)


def downsample(image: np.ndarray, factor: int = GLOW_FACTOR) -> np.ndarray:
    """Box-average by `factor` (image sides must be multiples of it)."""
    height, width, channels = image.shape
    blocks = image.reshape(height // factor, factor, width // factor, factor, channels)
    return blocks.mean(axis=(1, 3), dtype=np.float32)


def _box_blur(image: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """Running mean of width 2*radius+1 along `axis`, edges clamped."""
    if radius < 1:
        return image
    pad = [(0, 0)] * image.ndim
    pad[axis] = (radius + 1, radius)
    summed = np.cumsum(np.pad(image, pad, mode="edge"), axis=axis, dtype=np.float64)
    length = summed.shape[axis]
    upper = np.take(summed, np.arange(2 * radius + 1, length), axis=axis)
    lower = np.take(summed, np.arange(0, length - 2 * radius - 1), axis=axis)
    return ((upper - lower) / (2 * radius + 1)).astype(np.float32)


def gaussian_blur(image: np.ndarray, sigma_px: float) -> np.ndarray:
    """Three box passes per axis approximate a Gaussian of `sigma_px`."""
    radius = max(0, round((math.sqrt(4 * sigma_px**2 + 1) - 1) / 2))
    for axis in (0, 1):
        for _ in range(3):
            image = _box_blur(image, radius, axis)
    return image


def glow(small_bright: np.ndarray, px_per_m_small: float) -> np.ndarray:
    """Weighted sum of blurs of the bright part (at the reduced resolution)."""
    total = np.zeros_like(small_bright)
    for radius_m, weight in zip(BLOOM_RADII_M, BLOOM_WEIGHTS, strict=True):
        total += weight * gaussian_blur(small_bright, radius_m * px_per_m_small)
    return total


def upsample_window(
    small: np.ndarray, factor: int, row0: int, row1: int, col0: int, col1: int
) -> np.ndarray:
    """Bilinear sample of a reduced image over full-resolution rows/cols [0, 1)."""

    def axis(start: int, stop: int, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        position = (np.arange(start, stop) + 0.5) / factor - 0.5
        low = np.clip(np.floor(position).astype(int), 0, size - 1)
        high = np.clip(low + 1, 0, size - 1)
        weight = np.clip(position - low, 0.0, 1.0).astype(np.float32)
        return low, high, weight

    y0, y1, wy = axis(row0, row1, small.shape[0])
    x0, x1, wx = axis(col0, col1, small.shape[1])
    rows = small[y0] * (1 - wy)[:, None, None] + small[y1] * wy[:, None, None]
    return rows[:, x0] * (1 - wx)[None, :, None] + rows[:, x1] * wx[None, :, None]


def bloom(linear: np.ndarray, px_per_m: float, factor: int = GLOW_FACTOR) -> np.ndarray:
    """Whole-image bloom (same result as the cook's region-wise path)."""
    small = glow(downsample(bright(linear), factor), px_per_m / factor)
    height, width = linear.shape[:2]
    return linear + BLOOM_STRENGTH * upsample_window(small, factor, 0, height, 0, width)
