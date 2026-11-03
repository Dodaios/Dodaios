"""A 2.5D grid nav graph of the arena walk surfaces (numpy and scipy only).

The Unreal navmesh is built from the real collision (destruction.md 6.1);
this grid is the design-time stand-in the layout is checked against: the
same body (0.3 m radius, 1.8 m tall, 0.5 m step), the same walk surfaces,
and a graph whose shortest paths approximate navmesh path lengths to within
a cell. A11.1 and A11.2 read it, and so does the flow tool.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from . import layout as L

CELL_M = 0.5
RADIUS_M = 0.3
HEIGHT_M = 1.8
STEP_M = 0.5
MERGE_M = 0.3  # two surfaces closer than this in one column are one floor
EYE_M = 1.65


@dataclass
class NavGraph:
    xs: np.ndarray  # node x (plan m)
    zs: np.ndarray  # node z
    hs: np.ndarray  # node floor height
    matrix: csr_matrix  # symmetric, edge weight = 3D step length
    labels: np.ndarray  # connected component per node
    cell: float

    @property
    def count(self) -> int:
        return int(self.xs.shape[0])

    def islands(self) -> list[int]:
        """Node count per connected component, largest first."""
        return sorted(np.bincount(self.labels).tolist(), reverse=True)

    def level_of(self, h: float) -> str:
        for name, lo, hi in L.LEVEL_BANDS:
            if lo <= h < hi:
                return name
        return "other"

    def level_shares(self) -> dict[str, float]:
        names = [self.level_of(float(h)) for h in self.hs]
        total = len(names)
        return {name: names.count(name) / total for name, _, _ in L.LEVEL_BANDS}

    def area_m2(self) -> float:
        return self.count * self.cell * self.cell

    def extent(self) -> tuple[float, float, float, float]:
        half = self.cell / 2
        return (
            float(self.xs.min()) - half,
            float(self.xs.max()) + half,
            float(self.zs.min()) - half,
            float(self.zs.max()) + half,
        )

    def nearest(self, x: float, z: float, h: float) -> int:
        d = (self.xs - x) ** 2 + (self.zs - z) ** 2 + (2.0 * (self.hs - h)) ** 2
        return int(np.argmin(d))

    def eyes(self) -> np.ndarray:
        return np.stack([self.xs, self.zs, self.hs + EYE_M], axis=1)

    def distances_from(self, sources: list[int]) -> np.ndarray:
        return dijkstra(self.matrix, directed=False, indices=sources)

    def path(self, source: int, target: int) -> list[int]:
        _, pred = dijkstra(self.matrix, directed=False, indices=source, return_predecessors=True)
        if pred[target] < 0 and target != source:
            return []
        out = [target]
        while out[-1] != source:
            out.append(int(pred[out[-1]]))
        return out[::-1]


def _surfaces_at(x: float, z: float, walks: list, ramps: list) -> list[float]:
    heights = [b.h1 for b in walks if b.x0 <= x <= b.x1 and b.z0 <= z <= b.z1]
    heights += [r.height_at(x, z) for r in ramps if r.x0 <= x <= r.x1 and r.z0 <= z <= r.z1]
    heights.sort(reverse=True)
    merged: list[float] = []
    for h in heights:
        if not merged or merged[-1] - h > MERGE_M:
            merged.append(h)
    return merged


def _blocked(x: float, z: float, h: float, solids: list, ramps: list) -> bool:
    lo, hi = h + 0.05, h + HEIGHT_M
    r = RADIUS_M
    for b in solids:
        if b.walk and b.h1 <= h + STEP_M:
            continue  # a walk surface a body can step onto is floor, not a wall
        if b.x0 - r < x < b.x1 + r and b.z0 - r < z < b.z1 + r and b.h0 < hi and b.h1 > lo:
            return True
    for ramp in ramps:
        if ramp.x0 < x < ramp.x1 and ramp.z0 < z < ramp.z1:
            rh = ramp.height_at(x, z)
            if lo < rh < hi:
                return True
    return False


def build(layout: L.Layout, cell: float = CELL_M, bounds=L.ARENA) -> NavGraph:
    """Nodes on every walk surface inside `bounds`, linked to their 8 neighbours."""
    x0, x1, z0, z1 = bounds
    walks = [b for b in layout.boxes if b.walk]
    solids = [b for b in layout.boxes if b.solid and not b.walk]
    # Walk boxes are solid for every surface but their own top.
    solids_all = solids + walks
    ramps = layout.ramps
    nx, nz = int(round((x1 - x0) / cell)), int(round((z1 - z0) / cell))
    columns: dict[tuple[int, int], list[tuple[float, int]]] = {}
    xs, zs, hs = [], [], []
    for ix in range(nx):
        x = x0 + (ix + 0.5) * cell
        for iz in range(nz):
            z = z0 + (iz + 0.5) * cell
            for h in _surfaces_at(x, z, walks, ramps):
                if _blocked(x, z, h, solids_all, ramps):
                    continue
                columns.setdefault((ix, iz), []).append((h, len(xs)))
                xs.append(x)
                zs.append(z)
                hs.append(h)
    rows, cols, weights = [], [], []

    def link(a: tuple[int, int], b: tuple[int, int], horiz: float) -> None:
        for ha, na in columns.get(a, ()):
            for hb, nb in columns.get(b, ()):
                if abs(ha - hb) <= STEP_M:
                    rows.append(na)
                    cols.append(nb)
                    weights.append(math.hypot(horiz, ha - hb))

    def has_floor(c: tuple[int, int], h: float) -> bool:
        return any(abs(hc - h) <= STEP_M for hc, _ in columns.get(c, ()))

    for (ix, iz), nodes in columns.items():
        link((ix, iz), (ix + 1, iz), cell)
        link((ix, iz), (ix, iz + 1), cell)
        for dx in (-1, 1):
            # A diagonal step needs both orthogonal cells free: no corner cutting.
            a, b, d = (ix + dx, iz), (ix, iz + 1), (ix + dx, iz + 1)
            for h, n in nodes:
                if not (has_floor(a, h) and has_floor(b, h)):
                    continue
                for hd, nd in columns.get(d, ()):
                    if abs(hd - h) <= STEP_M:
                        rows.append(n)
                        cols.append(nd)
                        weights.append(math.hypot(cell * math.sqrt(2.0), hd - h))
    count = len(xs)
    matrix = csr_matrix((weights, (rows, cols)), shape=(count, count))
    matrix = matrix.maximum(matrix.T)
    _, labels = connected_components(matrix, directed=False)
    return NavGraph(np.array(xs), np.array(zs), np.array(hs), matrix.tocsr(), labels, cell)
