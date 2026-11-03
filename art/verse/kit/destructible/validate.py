"""Builder-side validator of destructible pieces (contracts/destruction.md 9).

The same checks as the editor validator `UVerseDestructibleValidator`
(`unreal/Verse/Source/VerseDestruction/Private/Validation/`): every shell is
closed and manifold after welding coincident positions, no zero-area faces,
and the median inward ray distance from faces facing along the piece's
thickness axis matches the material's reference thickness within 10 %.
Pure Python; the cook step and pytest run it before any export.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from .geometry import Mesh, Vec3, cross, dot, length, scale, sub

TOLERANCE = 0.10


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    thickness_m: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors


def _weld(mesh: Mesh) -> list[int]:
    grid: dict[tuple[int, int, int], int] = {}
    out = []
    for v in mesh.verts:
        key = (round(v[0] * 1e5), round(v[1] * 1e5), round(v[2] * 1e5))  # 0.01 mm
        out.append(grid.setdefault(key, len(grid)))
    return out


def check_closed(mesh: Mesh) -> Report:
    report = Report()
    if not mesh.faces:
        report.errors.append("no faces")
        return report
    weld = _weld(mesh)
    directed: Counter[tuple[int, int]] = Counter()
    degenerate = 0
    for a, b, c in mesh.triangles():
        va, vb, vc = weld[a], weld[b], weld[c]
        area = length(cross(sub(mesh.verts[b], mesh.verts[a]), sub(mesh.verts[c], mesh.verts[a])))
        if len({va, vb, vc}) < 3 or area < 1e-12:
            degenerate += 1
            continue
        for e in ((va, vb), (vb, vc), (vc, va)):
            directed[e] += 1
    if degenerate:
        report.errors.append(f"{degenerate} zero-area faces")
    open_edges = sum(1 for (a, b) in directed if (b, a) not in directed)
    bad = sum(1 for (a, b), n in directed.items() if n > 1 or directed.get((b, a), n) != n)
    if open_edges:
        report.errors.append(
            f"not watertight: {open_edges} open edges (one-sided shell or double plane)"
        )
    if bad:
        report.errors.append(f"not manifold: {bad} edges shared inconsistently")
    return report


def _ray_triangle(origin: Vec3, d: Vec3, a: Vec3, b: Vec3, c: Vec3) -> float | None:
    e1, e2 = sub(b, a), sub(c, a)
    p = cross(d, e2)
    det = dot(e1, p)
    if abs(det) < 1e-15:
        return None
    inv = 1.0 / det
    s = sub(origin, a)
    u = dot(s, p) * inv
    if u < -1e-9 or u > 1 + 1e-9:
        return None
    q = cross(s, e1)
    v = dot(d, q) * inv
    if v < -1e-9 or u + v > 1 + 1e-9:
        return None
    t = dot(e2, q) * inv
    return t if t > 1e-6 else None


def measure_thickness(mesh: Mesh, axis: Vec3) -> float:
    """Area-weighted median inward ray distance from faces facing along +-axis, metres."""
    tris = [(mesh.verts[a], mesh.verts[b], mesh.verts[c]) for a, b, c in mesh.triangles()]
    samples: list[tuple[float, float]] = []
    for ti, (a, b, c) in enumerate(tris):
        n = cross(sub(b, a), sub(c, a))
        area = length(n) / 2
        if area < 1e-12:
            continue
        n = scale(n, 1.0 / (2 * area))
        if abs(dot(n, axis)) < 0.95:
            continue
        centroid = scale((a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2]), 1 / 3)
        best = None
        for sign in (-1.0, 1.0):
            d = scale(n, sign)
            origin = (
                centroid[0] + d[0] * 1e-5,
                centroid[1] + d[1] * 1e-5,
                centroid[2] + d[2] * 1e-5,
            )
            for tj, (p, q, r) in enumerate(tris):
                if tj == ti:
                    continue
                t = _ray_triangle(origin, d, p, q, r)
                if t is not None and (best is None or t < best):
                    best = t
            if best is not None:
                best += 1e-5
                break
        if best is not None:
            samples.append((best, area))
    if not samples:
        return 0.0
    samples.sort()
    total = sum(w for _, w in samples)
    acc = 0.0
    for d, w in samples:
        acc += w
        if acc >= total / 2:
            return d
    return samples[-1][0]


def check_solid(shells: Sequence[Mesh], axis: Vec3, ref_thickness_m: float) -> Report:
    """Every shell closed; the whole piece's thickness within 10 % of the reference (0 = skip)."""
    report = Report()
    for k, shell in enumerate(shells):
        for err in check_closed(shell).errors:
            report.errors.append(f"shell {k}: {err}")
    if ref_thickness_m > 0:
        from .geometry import merge

        report.thickness_m = measure_thickness(merge(shells), axis)
        if report.thickness_m <= 0:
            report.errors.append("thickness not measurable (no inward hit)")
        elif abs(report.thickness_m - ref_thickness_m) > ref_thickness_m * TOLERANCE:
            report.errors.append(
                f"thickness {report.thickness_m * 100:.3f} cm, the material wants "
                f"{ref_thickness_m * 100:.3f} cm +-10 %"
            )
    return report
