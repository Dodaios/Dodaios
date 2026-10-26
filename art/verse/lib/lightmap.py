"""Lightmap atlas helpers for the realtime export (pure numpy, no bpy).

Used inside Blender by `lib.realtime` (packing, denoising, gap filling) and
outside it by `scripts/verse/package_realtime.py` (RGBM encoding) and the
tests. Format details: docs/verse/realtime.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------- packing


@dataclass(frozen=True)
class Placement:
    page: int
    x: int  # texel of the rectangle's inner (unpadded) left edge
    y: int  # texel of the inner top edge, row 0 at the top
    scale: float  # 1, or < 1 when the rectangle had to shrink to fit a page


def pack_skyline(
    sizes: list[tuple[float, float]],
    groups: list[int],
    page_px: int,
    pad: int,
) -> list[Placement]:
    """Place rectangles (w, h in texels) on square pages, skyline bottom-left.

    Rectangles are taken by group (a room), the tallest first within a
    group, so a room's surfaces share as few pages as possible. Each drops
    to the lowest spot on a page's skyline that fits it, on the first page
    with room for it (small ones fill holes on earlier pages): rectangles of
    very different sizes (a 1600 texel floor next to key banks) fill about
    80 % of the pages, shelf packing about half. Every rectangle keeps `pad`
    free texels on each side (neighbours are at least 2 * pad apart). A
    rectangle larger than a page is shrunk to fit.
    """
    order = sorted(range(len(sizes)), key=lambda i: (groups[i], -sizes[i][1], -sizes[i][0]))
    placements: list[Placement | None] = [None] * len(sizes)
    usable = page_px - 2 * pad
    skylines: list[list[list[int]]] = []  # per page: segments [x, top, width]
    for i in order:
        w, h = sizes[i]
        scale = min(1.0, usable / max(w, h, 1e-9))
        cw = math.ceil(w * scale) + 2 * pad
        ch = math.ceil(h * scale) + 2 * pad
        spot = None
        for page, skyline in enumerate(skylines):
            spot = _skyline_spot(skyline, cw, ch, page_px)
            if spot is not None:
                spot = (page, *spot)
                break
        if spot is None:
            skylines.append([[0, 0, page_px]])
            spot = (len(skylines) - 1, 0, 0)
        page, x, y = spot
        _skyline_add(skylines[page], x, y + ch, cw)
        placements[i] = Placement(page, x + pad, y + pad, scale)
    return [p for p in placements if p is not None]


def _skyline_spot(
    skyline: list[list[int]], cw: int, ch: int, page_px: int
) -> tuple[int, int] | None:
    """Lowest (then leftmost) (x, y) on the skyline where a cw x ch rectangle fits."""
    best = None
    for start in range(len(skyline)):
        x = skyline[start][0]
        if x + cw > page_px:
            break
        y, reach, k = 0, x, start
        while reach < x + cw:
            y = max(y, skyline[k][1])
            reach = skyline[k][0] + skyline[k][2]
            k += 1
        if y + ch <= page_px and (best is None or (y + ch, x) < (best[1] + ch, best[0])):
            best = (x, y)
    return best


def _skyline_add(skyline: list[list[int]], x: int, top: int, cw: int) -> None:
    """Raise the skyline to `top` over [x, x + cw) and merge equal neighbours."""
    end = x + cw
    out: list[list[int]] = []
    for sx, sy, sw in skyline:
        se = sx + sw
        if se <= x or sx >= end:
            out.append([sx, sy, sw])
            continue
        if sx < x:
            out.append([sx, sy, x - sx])
        if se > end:
            out.append([end, sy, se - end])
    out.append([x, top, cw])
    out.sort()
    merged: list[list[int]] = []
    for segment in out:
        if merged and merged[-1][1] == segment[1] and merged[-1][0] + merged[-1][2] == segment[0]:
            merged[-1][2] += segment[2]
        else:
            merged.append(segment)
    skyline[:] = merged


# ---------------------------------------------------------------- denoising

DENOISE_BAND = 512  # rows per band (memory: ~1 GB peak on a 4096 px page)


def denoise(
    irradiance: np.ndarray,
    normal: np.ndarray,
    position: np.ndarray,
    covered: np.ndarray,
    texel_m: float,
    passes: int,
) -> np.ndarray:
    """Edge-aware a-trous filter of baked irradiance (h, w, 3).

    Guided by the baked normal and world position, so light never bleeds
    across a corner, between islands or between surfaces that are far apart
    in the world; uncovered texels neither contribute nor change. Steps 1,
    2, 4 ... texels, processed in bands of rows with a halo.
    """
    result = irradiance.astype(np.float32)
    weight_of = covered.astype(np.float32)
    height = result.shape[0]
    for level in range(passes):
        step = 1 << level
        halo = 2 * step
        out = result.copy()
        for row0 in range(0, height, DENOISE_BAND):
            row1 = min(height, row0 + DENOISE_BAND)
            a, b = max(0, row0 - halo), min(height, row1 + halo)
            band = _atrous(result[a:b], normal[a:b], position[a:b], weight_of[a:b], step, texel_m)
            out[row0:row1] = band[row0 - a : row0 - a + (row1 - row0)]
        result = out
    return result


def _atrous(
    value: np.ndarray,
    normal: np.ndarray,
    position: np.ndarray,
    covered: np.ndarray,
    step: int,
    texel_m: float,
) -> np.ndarray:
    kernel = (1 / 16, 1 / 4, 3 / 8, 1 / 4, 1 / 16)
    sigma2 = 2.0 * (2.5 * texel_m) ** 2 * step
    h, w = value.shape[:2]
    pad = 2 * step

    def padded(a: np.ndarray) -> np.ndarray:
        widths = ((pad, pad), (pad, pad)) + ((0, 0),) * (a.ndim - 2)
        return np.pad(a, widths, mode="edge")

    pv, pn, pp, pc = padded(value), padded(normal), padded(position), padded(covered)
    total = np.zeros_like(value)
    weights = np.zeros((h, w), dtype=np.float32)
    for dy, ky in zip(range(-2, 3), kernel, strict=True):
        for dx, kx in zip(range(-2, 3), kernel, strict=True):
            rows = slice(pad + dy * step, pad + dy * step + h)
            cols = slice(pad + dx * step, pad + dx * step + w)
            dn = np.einsum("ijk,ijk->ij", normal, pn[rows, cols])
            np.clip(dn, 0.0, 1.0, out=dn)
            dn **= 32
            diff = position - pp[rows, cols]
            dp = np.einsum("ijk,ijk->ij", diff, diff)
            wgt = (ky * kx) * pc[rows, cols] * dn * np.exp(-dp / sigma2)
            total += pv[rows, cols] * wgt[..., None]
            weights += wgt
    filtered = total / np.maximum(weights, 1e-6)[..., None]
    keep = (weights > 1e-6) & (covered > 0)
    return np.where(keep[..., None], filtered, value)


def fill_gaps(image: np.ndarray, covered: np.ndarray) -> np.ndarray:
    """Push-pull fill of uncovered texels from covered ones (smooth, for mips
    and compression); covered texels are unchanged."""
    levels = [(image * covered[..., None], covered.astype(np.float32))]
    while min(levels[-1][1].shape) > 1:
        colour, weight = levels[-1]
        h, w = weight.shape
        h2, w2 = (h + 1) // 2, (w + 1) // 2
        c = np.zeros((h2 * 2, w2 * 2, colour.shape[2]), dtype=np.float32)
        k = np.zeros((h2 * 2, w2 * 2), dtype=np.float32)
        c[:h, :w], k[:h, :w] = colour, weight
        c = c.reshape(h2, 2, w2, 2, -1).sum(axis=(1, 3))
        k = k.reshape(h2, 2, w2, 2).sum(axis=(1, 3))
        levels.append((c, k))
    colour, weight = levels[-1]
    filled = colour / np.maximum(weight, 1e-12)[..., None]
    for colour, weight in reversed(levels[:-1]):
        h, w = weight.shape
        up = np.repeat(np.repeat(filled, 2, axis=0), 2, axis=1)[:h, :w]
        own = colour / np.maximum(weight, 1e-12)[..., None]
        blend = np.clip(weight, 0.0, 1.0)[..., None]
        filled = own * blend + up * (1.0 - blend)
    return np.where(covered[..., None], image, filled).astype(np.float32)


# ---------------------------------------------------------------- RGBM

RGBM_MAX_RANGE = 64.0


def rgbm_range(peak: float) -> float:
    """The power of two the encoding spans: at least the peak, at most 64."""
    return float(min(RGBM_MAX_RANGE, 2.0 ** math.ceil(math.log2(max(1.0, peak)))))


def rgbm_encode(radiance: np.ndarray, span: float) -> np.ndarray:
    """Linear HDR RGB (h, w, 3) -> uint8 RGBA, the "rgbm2" encoding.

    decode: m = a^2 * span, rgb = c^2 * m (a, c in 0..1). Both factors are
    squared, so precision follows brightness: dark texels keep fine steps,
    bright fixtures up to `span` never clip. Values above `span` clip.
    """
    value = np.clip(np.nan_to_num(radiance.astype(np.float32)), 0.0, span)
    peak = value.max(axis=2)
    a = np.ceil(np.sqrt(peak / span) * 255.0)
    a = np.clip(a, 1.0, 255.0)
    m = (a / 255.0) ** 2 * span
    c = np.sqrt(value / m[..., None])
    rgb = np.clip(np.round(c * 255.0), 0, 255)
    return np.concatenate([rgb, a[..., None]], axis=2).astype(np.uint8)


def rgbm_decode(rgba: np.ndarray, span: float) -> np.ndarray:
    """uint8 RGBA "rgbm2" -> linear RGB float32 (the runtime shader's maths)."""
    data = rgba.astype(np.float32) / 255.0
    return data[..., :3] ** 2 * (data[..., 3:4] ** 2 * span)
