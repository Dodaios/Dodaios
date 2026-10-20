"""Nav grid maths shared by the cook and the tests (numpy only, no bpy).

The cook samples floor heights on a fine grid (k x k samples per cell, NaN
where blocked); these functions reduce the samples to cells, erode the
walkable area by the body clearance and encode heights into the 8-bit PNG
the runtime reads (0 = blocked, else y = (v - HEIGHT_ZERO) * HEIGHT_STEP).
"""

from __future__ import annotations

import math

import numpy as np

CELL_M = 0.2
CLEARANCE_M = 0.25  # body radius kept clear of walls and drops
MAX_STEP_M = 0.3  # largest height difference a body steps over
HEIGHT_ZERO = 128
HEIGHT_STEP_M = 0.025


def reduce_samples(samples: np.ndarray, k: int, max_step: float = MAX_STEP_M) -> np.ndarray:
    """(rows*k, cols*k) sample heights -> (rows, cols) cell heights, NaN = blocked.

    A cell is walkable when all its samples are and they differ by at most
    `max_step`; its height is the centre sample (k odd).
    """
    rows, cols = samples.shape[0] // k, samples.shape[1] // k
    blocks = samples.reshape(rows, k, cols, k).transpose(0, 2, 1, 3).reshape(rows, cols, k * k)
    walkable = ~np.isnan(blocks).any(axis=2)
    filled = np.where(np.isnan(blocks), 0.0, blocks)
    walkable &= filled.max(axis=2) - filled.min(axis=2) <= max_step
    return np.where(walkable, blocks[:, :, (k * k) // 2], np.nan)


def clearance_offsets(cell: float, clearance: float) -> list[tuple[int, int]]:
    """Neighbour offsets whose cell square a disc of radius `clearance` overlaps."""
    reach = math.ceil(clearance / cell + 0.5)
    offsets = []
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            gap = math.hypot(max(0.0, abs(di) - 0.5), max(0.0, abs(dj) - 0.5)) * cell
            if (di, dj) != (0, 0) and gap < clearance:
                offsets.append((di, dj))
    return offsets


def erode(
    heights: np.ndarray,
    cell: float = CELL_M,
    clearance: float = CLEARANCE_M,
    max_step: float = MAX_STEP_M,
) -> np.ndarray:
    """Block every cell whose body disc touches a blocked cell or a drop > max_step."""
    offsets = clearance_offsets(cell, clearance)
    reach = max((max(abs(di), abs(dj)) for di, dj in offsets), default=0)
    rows, cols = heights.shape
    padded = np.pad(heights, reach, constant_values=np.nan)
    keep = ~np.isnan(heights)
    with np.errstate(invalid="ignore"):
        for di, dj in offsets:
            neighbour = padded[reach + di : reach + di + rows, reach + dj : reach + dj + cols]
            keep &= np.abs(neighbour - heights) <= max_step
    return np.where(keep, heights, np.nan)


def encode(heights: np.ndarray) -> np.ndarray:
    """Cell heights (NaN = blocked) -> uint8 nav image."""
    codes = np.clip(np.round(np.nan_to_num(heights) / HEIGHT_STEP_M) + HEIGHT_ZERO, 1, 255)
    return np.where(np.isnan(heights), 0, codes).astype(np.uint8)
