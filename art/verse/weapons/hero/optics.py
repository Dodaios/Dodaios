"""Sights for the hero weapons, built to the proportions of real optics (bpy).

Every sight is an original design that follows the measured layout of a real
class of optic, never one product:

- `open_reflex`: an open reflex (red dot) sight. Real ones of this class have a
  window of about 33 x 24 mm, a thin D-shaped hood with a 3 mm wall, one coated
  glass pane leaning back a few degrees, a low rear housing that stays below the
  line of sight, a rotary brightness dial and a rail clamp with two cross bolts;
  80 to 100 mm long overall.

Weapon space as in `weapons/specs.py` (metres, +X to the muzzle, +Z up, +Y left).
Each builder returns the sight point: the centre of the glass, where the dot is.
"""

from __future__ import annotations

import math

import bmesh
from mathutils import Matrix, Vector

from . import kit

#: Open reflex sight, metres.
REFLEX_LENGTH = 0.092
REFLEX_WIDTH = 0.033
WINDOW_W = 0.033
WINDOW_H = 0.024
HOOD_WALL = 0.0028
HOOD_DEPTH = 0.03
CLAMP_H = 0.0105
FLOOR_H = 0.004  # body floor between the clamp and the window
LENS_TILT_DEG = 7.0


def _d_profile(width: float, height: float, radius: float, steps: int = 8):
    """Closed (y, z) loop of a D shape: flat bottom, straight sides, rounded top corners."""
    hw = width / 2
    pts = [(-hw, 0.0), (hw, 0.0)]
    for i in range(steps + 1):  # top right corner
        a = math.radians(0 + 90 * i / steps)
        pts.append((hw - radius + radius * math.cos(a), height - radius + radius * math.sin(a)))
    for i in range(steps + 1):  # top left corner
        a = math.radians(90 + 90 * i / steps)
        pts.append((-hw + radius + radius * math.cos(a), height - radius + radius * math.sin(a)))
    return pts


def profile_prism(name, profile, x0, x1, z0, material, bone="Root", bevel=0.0008):
    """Extrude a (y, z) loop along +X from x0 to x1, lifted by z0."""
    bm = bmesh.new()
    ring0 = [bm.verts.new((x0, y, z + z0)) for y, z in profile]
    ring1 = [bm.verts.new((x1, y, z + z0)) for y, z in profile]
    n = len(profile)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((ring0[i], ring0[j], ring1[j], ring1[i]))
    bm.faces.new(list(reversed(ring0)))
    bm.faces.new(ring1)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return kit.finish(kit._object(name, bm, material, bone), bevel, 2, 30.0)


def curved_pane(name, centre, width, height, bulge, tilt_deg, material, bone="Root", rows=10):
    """A thin glass pane facing +X, slightly domed towards -X, leaning back by `tilt_deg`."""
    bm = bmesh.new()
    cols = rows
    grid = []
    for r in range(rows + 1):
        row = []
        for c in range(cols + 1):
            y = -width / 2 + width * c / cols
            z = -height / 2 + height * r / rows
            d = 1.0 - (2 * y / width) ** 2 - (2 * z / height) ** 2 * 0.5
            row.append(bm.verts.new((-bulge * max(d, 0.0), y, z)))
        grid.append(row)
    for r in range(rows):
        for c in range(cols):
            bm.faces.new((grid[r][c], grid[r][c + 1], grid[r + 1][c + 1], grid[r + 1][c]))
    bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=0.0012)
    rot = Matrix.Rotation(math.radians(-tilt_deg), 4, "Y")
    bmesh.ops.transform(bm, matrix=Matrix.Translation(Vector(centre)) @ rot, verts=bm.verts)
    return kit.finish(kit._object(name, bm, material, bone), 0.0)


def _cross_bolt(name, x, z, y_face, material):
    """Hex-socket cap screw head on a side face (`y_face` < 0: right side)."""
    sign = 1.0 if y_face > 0 else -1.0
    head = kit.cylinder_axis(
        f"{name}Head", (x, y_face + sign * 0.0012, z), 0.0034, 0.0024, "Y", material, sides=24
    )
    hexa = kit.cylinder_axis(
        f"{name}Hex", (x, y_face + sign * 0.0024, z), 0.0016, 0.003, "Y", None, sides=6, bevel=0.0
    )
    hexa.modifiers.clear()
    kit.cut(head, hexa)
    return head


def open_reflex(m: dict, x0: float, rail_z: float, prefix: str = "Reflex") -> tuple:
    """Open reflex sight from `x0` (rear) along +X, standing on the rail top `rail_z`."""
    a, s, p = m["anodised"], m["steel"], m["polymer"]
    w = REFLEX_WIDTH
    hw = w / 2
    # Rail clamp: a block over the rail with two jaws reaching down its sides.
    kit.box(
        f"{prefix}Clamp",
        (x0 + 0.004, -hw, rail_z),
        (x0 + 0.074, hw, rail_z + CLAMP_H),
        a,
        bevel=0.0012,
    )
    for side, y0, y1 in (("L", 0.0105, 0.0135), ("R", -0.0135, -0.0105)):
        kit.box(
            f"{prefix}Jaw{side}",
            (x0 + 0.004, y0, rail_z - 0.006),
            (x0 + 0.074, y1, rail_z + 0.001),
            a,
            bevel=0.0008,
        )
    for k, x in enumerate((x0 + 0.018, x0 + 0.058)):
        _cross_bolt(f"{prefix}Bolt{k}", x, rail_z + 0.0045, -hw, s)
    # Body floor under the window and the rear housing.
    floor_z = rail_z + CLAMP_H
    kit.box(
        f"{prefix}Floor",
        (x0, -hw, floor_z),
        (x0 + REFLEX_LENGTH, hw, floor_z + FLOOR_H),
        a,
        bevel=0.0015,
    )
    win_z0 = floor_z + FLOOR_H  # bottom of the window
    # Rear housing: low on the line of sight, a raised battery and emitter block on the right.
    kit.box(f"{prefix}RearLow", (x0, -hw, win_z0), (x0 + 0.03, hw, win_z0 + 0.003), a, bevel=0.0012)
    block = kit.box(
        f"{prefix}Block",
        (x0, -hw, win_z0),
        (x0 + 0.05, -0.0125, win_z0 + 0.009),
        a,
        bevel=0.0018,
        segments=3,
    )
    roof = kit.box(
        f"{prefix}BlockRoofCut",
        (x0 + 0.032, -0.05, win_z0 + 0.006),
        (x0 + 0.09, 0.05, win_z0 + 0.04),
        None,
        rot=(0, 30, 0),
        pivot=(x0 + 0.034, 0, win_z0 + 0.009),
    )
    roof.modifiers.clear()
    kit.cut(block, roof)
    for k in range(3):  # cooling ribs on the block roof
        x = x0 + 0.006 + k * 0.007
        kit.box(
            f"{prefix}Rib{k}",
            (x, -hw + 0.002, win_z0 + 0.009),
            (x + 0.0035, -0.0135, win_z0 + 0.0112),
            a,
            bevel=0.0006,
        )
    # Brightness dial on the right of the block, knurled rim.
    dial_c = (x0 + 0.038, -hw - 0.003, win_z0 + 0.006)
    kit.cylinder_axis(f"{prefix}Dial", dial_c, 0.0082, 0.006, "Y", a, sides=40)
    for k in range(24):
        ang = 2 * math.pi * k / 24
        cx = dial_c[0] + 0.0082 * math.cos(ang)
        cz = dial_c[2] + 0.0082 * math.sin(ang)
        kit.box(
            f"{prefix}Knurl{k:02d}",
            (cx - 0.0006, dial_c[1] - 0.0028, cz - 0.0006),
            (cx + 0.0006, dial_c[1] + 0.0028, cz + 0.0006),
            a,
            bevel=0.0,
        )
    kit.cylinder_axis(
        f"{prefix}DialCap",
        (dial_c[0], dial_c[1] - 0.0032, dial_c[2]),
        0.0045,
        0.0008,
        "Y",
        s,
        sides=24,
    )
    # Battery cap on the left, windage and elevation screws.
    kit.cylinder_axis(
        f"{prefix}Battery", (x0 + 0.02, hw + 0.002, win_z0 + 0.002), 0.0062, 0.004, "Y", a, sides=24
    )
    kit.cylinder_axis(
        f"{prefix}Windage",
        (x0 + 0.062, -hw - 0.0005, win_z0 - 0.002),
        0.0022,
        0.0015,
        "Y",
        s,
        sides=16,
    )
    kit.cylinder_axis(
        f"{prefix}Elevation", (x0 + 0.082, 0.0, win_z0 + 0.0002), 0.0022, 0.0015, "Z", s, sides=16
    )
    # Hood: thin D-shaped tube around the window, its front edge leaning back.
    hx0 = x0 + REFLEX_LENGTH - HOOD_DEPTH
    hx1 = x0 + REFLEX_LENGTH
    outer = _d_profile(WINDOW_W + 2 * HOOD_WALL, WINDOW_H + HOOD_WALL, 0.009)
    inner = _d_profile(WINDOW_W, WINDOW_H, 0.0072)
    hood = profile_prism(f"{prefix}Hood", outer, hx0, hx1, win_z0, a, bevel=0.0007)
    hole = profile_prism(
        f"{prefix}HoodHole",
        [(y, z - 0.002) for y, z in inner],
        hx0 - 0.01,
        hx1 + 0.01,
        win_z0,
        None,
    )
    hole.modifiers.clear()
    kit.cut(hood, hole)
    lean = kit.box(
        f"{prefix}HoodLean",
        (hx1 - 0.004, -0.05, win_z0 + 0.004),
        (hx1 + 0.03, 0.05, win_z0 + 0.06),
        None,
        rot=(0, -14, 0),
        pivot=(hx1, 0, win_z0 + 0.004),
    )
    lean.modifiers.clear()
    kit.cut(hood, lean)
    # Glass: one coated pane inside the hood, leaning back, and the red dot on it.
    lens_x = hx0 + 0.011
    sight_z = win_z0 + WINDOW_H * 0.48
    curved_pane(
        f"{prefix}Lens",
        (lens_x, 0.0, sight_z),
        WINDOW_W - 0.0006,
        WINDOW_H - 0.0006,
        0.0012,
        LENS_TILT_DEG,
        m["glass"],
    )
    kit.cylinder_axis(
        f"{prefix}Dot",
        (lens_x - 0.0012, 0.0, sight_z),
        0.00045,
        0.0002,
        "X",
        m["reticle"],
        sides=16,
        bevel=0.0,
    )
    # The emitter window on the block's front face, aimed at the glass.
    kit.box(
        f"{prefix}Emitter",
        (x0 + 0.0502, -0.0158, win_z0 + 0.003),
        (x0 + 0.0508, -0.0135, win_z0 + 0.007),
        p,
        bevel=0.0,
    )
    return (lens_x, 0.0, sight_z)
