"""Blender (and three.js) space to Unreal space (contracts/art-pipeline.md 4.1).

Pure Python, no bpy: the exporter, the placement validator, pytest and the
editor-side calibration all import it. The twin C++ conversion lives in
VerseCore; both are checked against ``unreal/Verse/Art/space_vectors.json``.

Blender: Z up, X = bow, metres, right-handed.
Unreal:  Z up, X forward, Y right, centimetres, left-handed.

The mapping is the mirror across the XZ plane plus metres to centimetres:
``(x, y, z) m -> (100 x, -100 y, 100 z) cm``. A rotation R becomes M R M with
M = diag(1, -1, 1), which for a quaternion (w, x, y, z) is (w, -x, y, -z);
Unreal stores quaternions as [x, y, z, w].
"""

from __future__ import annotations

import math
from collections.abc import Sequence

CM_PER_M = 100.0

Vec3 = Sequence[float]


def location_to_ue(location_m: Vec3) -> list[float]:
    """Blender location in metres -> Unreal location in centimetres."""
    x, y, z = (float(v) for v in location_m)
    return [_clean(CM_PER_M * x), _clean(-CM_PER_M * y), _clean(CM_PER_M * z)]


def location_from_ue(location_cm: Vec3) -> list[float]:
    x, y, z = (float(v) for v in location_cm)
    return [_clean(x / CM_PER_M), _clean(-y / CM_PER_M), _clean(z / CM_PER_M)]


def direction_to_ue(direction: Vec3) -> list[float]:
    """Unit-free direction (normals, axes): mirrored, not scaled."""
    x, y, z = (float(v) for v in direction)
    return [_clean(x), _clean(-y), _clean(z)]


def quat_to_ue(quat_wxyz: Sequence[float]) -> list[float]:
    """Blender quaternion (w, x, y, z) -> Unreal [x, y, z, w], normalised, w >= 0."""
    w, x, y, z = (float(v) for v in quat_wxyz)
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0.0:
        raise ValueError("zero quaternion")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    out = [-x, y, -z, w]
    if out[3] < 0.0:  # q and -q are the same rotation; keep one canonical sign
        out = [-v for v in out]
    return [_clean(v) for v in out]


def quat_from_ue(quat_xyzw: Sequence[float]) -> list[float]:
    x, y, z, w = (float(v) for v in quat_xyzw)
    return [_clean(w), _clean(-x), _clean(y), _clean(-z)]


def yaw_to_ue(rot_z_deg: float) -> float:
    """Blender rotation about Z (counter-clockwise from above) -> Unreal yaw."""
    return _clean(-float(rot_z_deg))


def scale_to_ue(scale: Vec3) -> list[float]:
    """Scale is unchanged by the mirror (it is applied in local space)."""
    return [float(v) for v in scale]


def three_to_ue(location_m: Vec3) -> list[float]:
    """three.js (x, y, z) m, Y up -> Unreal cm (three.js z = -Blender y)."""
    x, y, z = (float(v) for v in location_m)
    return [_clean(CM_PER_M * x), _clean(CM_PER_M * z), _clean(CM_PER_M * y)]


def yaw_quat_wxyz(rot_z_deg: float) -> list[float]:
    """Blender quaternion (w, x, y, z) of a rotation about +Z."""
    half = math.radians(float(rot_z_deg)) / 2.0
    return [math.cos(half), 0.0, 0.0, math.sin(half)]


def rotate_vector_xyzw(quat_xyzw: Sequence[float], vector: Vec3) -> list[float]:
    """Rotate ``vector`` by an [x, y, z, w] quaternion (q v q*), as FQuat does."""
    qx, qy, qz, qw = (float(v) for v in quat_xyzw)
    vx, vy, vz = (float(v) for v in vector)
    # t = 2 * cross(q.xyz, v); v' = v + w t + cross(q.xyz, t)
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return [
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    ]


def rotate_vector_wxyz(quat_wxyz: Sequence[float], vector: Vec3) -> list[float]:
    w, x, y, z = quat_wxyz
    return rotate_vector_xyzw([x, y, z, w], vector)


def bounds_to_ue(min_m: Vec3, max_m: Vec3) -> tuple[list[float], list[float]]:
    """Blender box (metres) -> Unreal box (cm) with min <= max on every axis."""
    a = location_to_ue(min_m)
    b = location_to_ue(max_m)
    pairs = list(zip(a, b, strict=True))
    return [min(p) for p in pairs], [max(p) for p in pairs]


def _clean(value: float) -> float:
    """Drop the sign of zero and float noise below 1e-12 so JSON stays stable."""
    if abs(value) < 1e-12:
        return 0.0
    return value
