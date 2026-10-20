"""Viewport window walls and glazed partitions.

``SM_Viewport_480``: a 4.8 m full-height wall module for a far wall (room
face Y = 0 toward -Y). A charcoal sill with a brushed ledge, then two large
panes leaning back 12 degrees between thick gunmetal mullions, each pane
opening chamfered in its corners, a header and a section cap on top.

Behind the glass, inside the module, a plane sloping from the sill back to
the header carries a dim star field: the plate camera looks down at 60
degrees, so every ray through the glass meets that plane before it could
reach the floor or the hull structure behind the wall (BRIEF section 2:
stars only inside the window glass). Adjacent modules' planes meet edge to
edge.

``SM_Viewport_240`` is a single-pane module.
"""

from __future__ import annotations

import math

from lib import kit
from mathutils import Matrix, Vector

from . import walls

LEAN_DEG = 12.0
SILL = 1.0
WIN_H = 2.9  # along the slant
DEPTH = 0.35
MULLION = 0.3
CHAMFER = 0.4
STAR_Y = 1.2


def _wedge(
    mb: kit.MeshBuilder, corner, dx: float, dz: float, y0: float, y1: float, mat: str
) -> None:
    """Triangular corner fill (legs ``dx`` along X and ``dz`` along Z)."""
    cx, cz = corner
    tri = [(cx, cz), (cx + dx, cz), (cx, cz + dz)]
    verts = [Vector((x, y0, z)) for x, z in tri] + [Vector((x, y1, z)) for x, z in tri]
    faces = [(0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)]
    mb._add(verts, faces, mat)


def build_viewport(width: float) -> None:
    name = f"SM_Viewport_{round(width * 100)}"
    hw = width / 2
    lean = Matrix.Translation((0.0, 0.0, SILL)) @ Matrix.Rotation(math.radians(-LEAN_DEG), 4, "X")

    sill = kit.MeshBuilder()
    walls.backing(sill, width, SILL)
    for a, b in walls.module_spans(width):
        sill.box(
            (a + walls.GAP / 2, 0.0, 0.12),
            (b - walls.GAP / 2, walls.PANEL_DEPTH, SILL - 0.08),
            "M_Wall_Charcoal",
        )
    sill.box((-hw, 0.03, 0.0), (hw, walls.THICKNESS, 0.12), "M_Wall_PaintedDark")
    sill.box((-hw, -0.32, SILL - 0.08), (hw, DEPTH, SILL), "M_Trim_BrushedSteel")
    sill.build(f"{name}_sill", bevel_width=0.004)

    frame = kit.MeshBuilder(matrix=lean)
    panes = round(width / 2.4)
    pane_w = width / panes
    for i in range(panes + 1):
        x = -hw + i * pane_w
        x0, x1 = max(-hw, x - MULLION / 2), min(hw, x + MULLION / 2)
        frame.box((x0, 0.0, 0.0), (x1, DEPTH, WIN_H), "M_Wall_Charcoal")
    frame.box((-hw, 0.0, 0.0), (hw, DEPTH, 0.14), "M_Wall_Charcoal")
    frame.box((-hw, 0.0, WIN_H - 0.14), (hw, DEPTH, WIN_H), "M_Wall_Charcoal")
    glass_quads = []
    for i in range(panes):
        a = -hw + i * pane_w + MULLION / 2
        b = -hw + (i + 1) * pane_w - MULLION / 2
        z0, z1 = 0.14, WIN_H - 0.14
        corners = (
            ((a, z0), CHAMFER, CHAMFER),
            ((b, z0), -CHAMFER, CHAMFER),
            ((a, z1), CHAMFER, -CHAMFER),
            ((b, z1), -CHAMFER, -CHAMFER),
        )
        for corner, dx, dz in corners:
            _wedge(frame, corner, dx, dz, 0.0, DEPTH, "M_Wall_Charcoal")
        glass_quads.append([(a, 0.2, z0), (b, 0.2, z0), (b, 0.2, z1), (a, 0.2, z1)])
    frame.build(f"{name}_frame", bevel_width=0.02, segments=3)

    verts, faces = [], []
    for quad in glass_quads:
        n = len(verts)
        verts += [lean @ Vector(v) for v in quad]
        faces.append((n, n + 1, n + 2, n + 3))
    glass = kit.mesh_object(f"{name}_glass", verts, faces, "M_Glass_Viewport")
    glass.visible_shadow = False

    top_z = SILL + WIN_H * math.cos(math.radians(LEAN_DEG))
    top_y = WIN_H * math.sin(math.radians(LEAN_DEG))
    header = kit.MeshBuilder()
    header.box(
        (-hw, top_y - 0.05, top_z - 0.05),
        (hw, STAR_Y + 0.1, walls.HEIGHT - 0.02),
        "M_Wall_Charcoal",
    )
    header.box(
        (-hw, top_y - 0.07, top_z - 0.08), (hw, top_y + 0.1, top_z - 0.03), "M_Trim_BrushedSteel"
    )
    walls.section_cap(header, width, walls.HEIGHT, thickness=STAR_Y + 0.1)
    header.box((-hw, STAR_Y + 0.02, 0.0), (hw, STAR_Y + 0.1, walls.HEIGHT), "M_Recess_Dark")
    header.build(f"{name}_header", bevel_width=0.004)

    stars = kit.mesh_object(
        f"{name}_stars",
        [(-hw, 0.45, 0.0), (hw, 0.45, 0.0), (hw, STAR_Y, top_z + 0.2), (-hw, STAR_Y, top_z + 0.2)],
        [(0, 1, 2, 3)],
        "M_Starfield",
    )
    stars.visible_shadow = False
    stars.visible_diffuse = False
    for i, (sx, mat) in enumerate(
        ((-hw + 0.25, "M_Indicator_Red"), (hw - 0.25, "M_Indicator_White"))
    ):
        kit.emissive_panel(
            f"{name}_ledge_lamp{i}", (sx, -0.2, SILL + 0.001), (0.1, 0.03), mat, normal="Z"
        )
    kit.occluder(((-hw, -0.32, 0.0), (hw, STAR_Y + 0.1, walls.HEIGHT)))


GLASS_SILL = 0.9
GLASS_HEAD = 3.6


def build_glass_partition(width: float, *, cut: bool = False) -> None:
    """Glazed partition (control rooms, offices): charcoal base to 0.9 m,
    clear glass between gunmetal mullions on the 1.2 m module, charcoal
    header from 3.6 m. Room face Y = 0 toward -Y, 0.2 m thick. Usually runs
    along the camera axis (rot 90) where it is seen edge-on at full height."""
    name = f"SM_GlassPartition_{round(width * 100)}{'_Cut' if cut else ''}"
    hw, t = width / 2, 0.2
    top = walls.CUT_HEIGHT if cut else walls.HEIGHT
    frame = kit.MeshBuilder()
    frame.box((-hw, 0.0, 0.0), (hw, t, GLASS_SILL), "M_Wall_Charcoal")
    frame.box((-hw, -0.01, GLASS_SILL - 0.05), (hw, t + 0.01, GLASS_SILL), "M_Trim_BrushedSteel")
    for a, b in walls.module_spans(width):
        for x in (a, b):
            x0, x1 = max(-hw, x - 0.04), min(hw, x + 0.04)
            mullion = ((x0, 0.02, GLASS_SILL), (x1, t - 0.02, min(GLASS_HEAD, top)))
            frame.box(*mullion, "M_Struct_Gunmetal")
    if not cut:
        frame.box((-hw, 0.0, GLASS_HEAD), (hw, t, top - 0.02), "M_Wall_Charcoal")
    walls.section_cap(frame, width, top, thickness=t)
    frame.build(f"{name}_frame", bevel_width=0.004)
    glass_top = min(GLASS_HEAD, top - 0.02)
    if glass_top > GLASS_SILL:
        y = t / 2
        quad = [(-hw, y, GLASS_SILL), (hw, y, GLASS_SILL), (hw, y, glass_top), (-hw, y, glass_top)]
        glass = kit.mesh_object(f"{name}_glass", quad, [(0, 1, 2, 3)], "M_Glass_Clear")
        if glass is not None:
            glass.visible_shadow = False
    kit.occluder(((-hw, 0.0, 0.0), (hw, t, GLASS_SILL)))
    if cut:
        with kit.ghost(walls.CUT_HEIGHT):
            build_glass_partition(width)


kit.register_variant(
    "SM_Viewport_480", build_viewport, dims=(4.8, STAR_Y + 0.1, walls.HEIGHT), width=4.8
)
kit.register_variant(
    "SM_Viewport_240", build_viewport, dims=(2.4, STAR_Y + 0.1, walls.HEIGHT), width=2.4
)
for _w in (1.2, 2.4, 4.8):
    _cm = round(_w * 100)
    kit.register_variant(
        f"SM_GlassPartition_{_cm}", build_glass_partition, dims=(_w, 0.2, walls.HEIGHT), width=_w
    )
    kit.register_variant(
        f"SM_GlassPartition_{_cm}_Cut",
        build_glass_partition,
        dims=(_w, 0.2, walls.CUT_HEIGHT),
        width=_w,
        cut=True,
    )
