"""Procedural gore mask textures for the Unreal Verse (WP05, own work).

Every texture is generated from a seed, so the bake is reproducible and the
PNG sources are never committed (art-pipeline 6.4): ``build.py`` writes them
to ``art/verse/.cache/gore/`` and the editor step imports them as
``/Game/Verse/Gore/T_Gore_*_M``.

Channel use (``_M`` masks, sRGB off):
    R  coverage (decal opacity)
    G  thickness (darker, glossier where blood is thick)
    B  unused, 0

Shapes:
    spatter  a directional burst: a dense core, elongated drops and satellite
             droplets with tails flying toward +U (the decal's roll points it
             along the bolt), four seeds
    drip     a small round drip with a few satellites (floor below a wound)
    pool     a large irregular pool with a thick centre and a soft rim
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

SIZE = 512
POOL_SIZE = 1024
SPATTER_SEEDS = (11, 23, 37, 53)


def _grid(size: int) -> tuple[np.ndarray, np.ndarray]:
    axis = (np.arange(size, dtype=np.float32) + 0.5) / size * 2.0 - 1.0
    return np.meshgrid(axis, axis, indexing="xy")


def _value_noise(size: int, cells: int, rng: np.random.Generator) -> np.ndarray:
    """Smooth value noise in [0, 1] (bicubic-free: smoothstep-blended lattice)."""
    lattice = rng.random((cells + 1, cells + 1), dtype=np.float32)
    coords = np.linspace(0.0, cells, size, endpoint=False, dtype=np.float32)
    i = np.floor(coords).astype(np.int32)
    f = coords - i
    f = f * f * (3.0 - 2.0 * f)
    x0, x1 = i, np.minimum(i + 1, cells)
    top = lattice[np.ix_(x0, x0)] * (1 - f)[None, :] + lattice[np.ix_(x0, x1)] * f[None, :]
    bottom = lattice[np.ix_(x1, x0)] * (1 - f)[None, :] + lattice[np.ix_(x1, x1)] * f[None, :]
    return top * (1 - f)[:, None] + bottom * f[:, None]


def _fbm(size: int, rng: np.random.Generator, octaves: int = 4, base: int = 4) -> np.ndarray:
    total = np.zeros((size, size), dtype=np.float32)
    amplitude, weight = 1.0, 0.0
    for octave in range(octaves):
        total += amplitude * _value_noise(size, base * 2**octave, rng)
        weight += amplitude
        amplitude *= 0.5
    return total / weight


def _blob(
    x: np.ndarray, y: np.ndarray, cx: float, cy: float, rx: float, ry: float, angle: float
) -> np.ndarray:
    """Signed field > 0 inside an ellipse (1 at the centre)."""
    c, s = math.cos(angle), math.sin(angle)
    dx, dy = x - cx, y - cy
    u = (dx * c + dy * s) / rx
    v = (-dx * s + dy * c) / ry
    return 1.0 - (u * u + v * v)


def _soft(field: np.ndarray, edge: float = 0.08) -> np.ndarray:
    return np.clip(field / edge, 0.0, 1.0)


def spatter(seed: int, size: int = SIZE) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x, y = _grid(size)
    noise = _fbm(size, rng)
    field = np.full((size, size), -1.0, dtype=np.float32)
    thick = np.zeros((size, size), dtype=np.float32)

    # Core: a few overlapping lobes left of centre.
    for _ in range(rng.integers(3, 6)):
        cx, cy = rng.uniform(-0.45, -0.15), rng.uniform(-0.15, 0.15)
        r = rng.uniform(0.14, 0.26)
        lobe = _blob(x, y, cx, cy, r * rng.uniform(1.0, 1.5), r, rng.uniform(-0.4, 0.4))
        field = np.maximum(field, lobe)
        thick = np.maximum(thick, np.clip(lobe, 0.0, 1.0))

    # Elongated drops fanning toward +U, with tails.
    for _ in range(rng.integers(18, 30)):
        angle = rng.normal(0.0, 0.35)
        dist = rng.uniform(0.25, 0.9)
        cx, cy = -0.3 + math.cos(angle) * dist, math.sin(angle) * dist
        r = rng.uniform(0.012, 0.05) * (1.15 - dist * 0.6)
        stretch = 1.5 + dist * 3.0
        drop = _blob(x, y, cx, cy, r * stretch, r, angle)
        back = r * stretch * 1.4
        tail = _blob(x, y, cx - math.cos(angle) * back, cy - math.sin(angle) * back,
                     r * stretch * 1.6, r * 0.35, angle)
        field = np.maximum(field, np.maximum(drop, tail * 0.9))
        thick = np.maximum(thick, np.clip(drop, 0.0, 1.0) * 0.8)

    # Fine mist.
    for _ in range(rng.integers(60, 110)):
        angle = rng.normal(0.0, 0.6)
        dist = rng.uniform(0.2, 0.98)
        cx, cy = -0.3 + math.cos(angle) * dist, math.sin(angle) * dist
        r = rng.uniform(0.003, 0.011)
        field = np.maximum(field, _blob(x, y, cx, cy, r * 1.3, r, angle))

    field = field + (noise - 0.5) * 0.25
    coverage = _soft(field, 0.06)
    thickness = np.clip(thick * 0.8 + (noise - 0.5) * 0.3, 0.0, 1.0) * coverage
    # Fade out at the square's border so no decal shows a straight edge.
    border = np.clip((1.0 - np.maximum(np.abs(x), np.abs(y))) / 0.06, 0.0, 1.0)
    return np.stack([coverage * border, thickness * border, np.zeros_like(coverage)], axis=-1)


def drip(seed: int = 71, size: int = SIZE) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x, y = _grid(size)
    noise = _fbm(size, rng)
    field = _blob(x, y, 0.0, 0.0, 0.42, 0.38, rng.uniform(0, math.pi))
    for _ in range(9):
        a, d = rng.uniform(0, 2 * math.pi), rng.uniform(0.5, 0.85)
        r = rng.uniform(0.03, 0.08)
        satellite = _blob(x, y, math.cos(a) * d, math.sin(a) * d, r, r, 0.0)
        field = np.maximum(field, satellite)
    field = field + (noise - 0.5) * 0.3
    coverage = _soft(field, 0.05)
    thickness = np.clip(_blob(x, y, 0.0, 0.0, 0.35, 0.3, 0.0), 0.0, 1.0) * coverage
    return np.stack([coverage, thickness, np.zeros_like(coverage)], axis=-1)


def pool(seed: int = 97, size: int = POOL_SIZE) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x, y = _grid(size)
    noise = _fbm(size, rng, octaves=5, base=3)
    radius = np.sqrt(x * x + y * y)
    angle = np.arctan2(y, x)
    wobble = 0.0
    for k in range(2, 7):
        phase = rng.uniform(0, 2 * math.pi)
        wobble = wobble + rng.uniform(0.02, 0.06) / k * np.sin(k * angle + phase)
    field = (0.78 + wobble) - radius + (noise - 0.5) * 0.18
    for _ in range(4):   # lobes where the blood ran
        a = rng.uniform(0, 2 * math.pi)
        lobe = _blob(x, y, math.cos(a) * 0.55, math.sin(a) * 0.55, 0.28, 0.17, a)
        field = np.maximum(field, lobe * 0.3)
    coverage = _soft(field, 0.03)
    thickness = np.clip(1.0 - radius / 0.8, 0.0, 1.0) ** 0.6 * coverage
    return np.stack([coverage, thickness, np.zeros_like(coverage)], axis=-1)


def all_textures() -> dict[str, np.ndarray]:
    textures = {
        f"T_Gore_Spatter_{index}_M": spatter(seed) for index, seed in enumerate(SPATTER_SEEDS)
    }
    textures["T_Gore_Drip_M"] = drip()
    textures["T_Gore_Pool_M"] = pool()
    return textures


def write_png(path: Path, image: np.ndarray) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    data = (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    Image.fromarray(data, mode="RGB").save(path, optimize=True)


def bake(out_dir: Path) -> list[Path]:
    paths = []
    for name, image in all_textures().items():
        path = out_dir / f"{name}.png"
        write_png(path, image)
        paths.append(path)
    return paths
