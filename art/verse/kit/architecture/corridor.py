"""Corridor modules with the chamfered fleet profile.

Cross-section (one side, Y measured outward from the floor edge, Z up)::

    z 3.60  ______ ceiling plane (section cap on top of the wall)
           /       upper chamfer, mid grey, leans back over the walkway
    z 2.85 |  ---- brushed trim band
           |       vertical panels, light grey, seams on the 1.2 m module
    z 1.08 |  ==== recessed opal light strip, shining across the floor
    z 0.95  \\
             \\     lower chamfer, light grey (the walkway narrows at the deck)
    z 0.10    |    dark kick plate
    z 0.00    +--- floor edge (Y = 0)

Floor clear width 3.6 m, width at mid height 4.8 m, outer width 6.0 m,
ceiling 3.6 m. Pieces run along X and are centred.

* ``SM_CorridorWall_<cm>`` / ``_Cut`` - one wall (room side faces -Y).
* ``SM_Corridor_<cm>`` - floor + far wall (full) + near wall (cut at 1.1 m) +
  ceiling with transverse light panels: for corridors running along X.
* ``SM_Corridor_<cm>_Full`` - both walls full height: for corridors running
  along the camera axis (place with rot 90; their walls are seen edge-on).
* ``SM_Corridor_Junction`` - 6 x 6 m crossing with four bulkhead pilasters.
* ``SM_Bulkhead_Pilaster`` / ``_Cut`` - 0.9 x 0.9 m structural column.
"""

from __future__ import annotations

import math

from lib import kit

from . import ceiling

FLOOR_HALF = 1.8  # half the clear floor width
CHAMFER_Y, CHAMFER_Z = 0.6, 0.95
STRIP_TOP = 1.08
PANEL_SPLIT = 1.92
TRIM = (2.75, 2.85)
UPPER_Y = 0.25
CEILING = 3.6
BODY_Y = 0.9  # wall body depth from the floor edge
CUT_HEIGHT = 1.1
GAP = 0.006
SKIN = 0.04  # panel thickness
LENGTHS = (2.4, 4.8)
OUTER_HALF = FLOOR_HALF + BODY_Y  # 2.7 -> 5.4 m outer, 6.0 m with pilasters


def _slab(
    mb: kit.MeshBuilder, p0, p1, x0: float, x1: float, material: str, t: float = SKIN
) -> None:
    """Panel slab between two profile points, thickened toward the wall body."""
    dy, dz = p1[0] - p0[0], p1[1] - p0[1]
    n = math.hypot(dy, dz)
    ny, nz = dz / n, -dy / n  # points into the wall body (+Y side)
    prof = [p0, p1, (p1[0] + ny * t, p1[1] + nz * t), (p0[0] + ny * t, p0[1] + nz * t)]
    mb.prism_x(prof, x0, x1, material)


def _modules(length: float) -> list[tuple[float, float]]:
    count = max(1, round(length / kit.MODULE))
    step = length / count
    return [(-length / 2 + i * step, -length / 2 + (i + 1) * step) for i in range(count)]


def build_corridor_wall(length: float, *, cut: bool = False) -> None:
    """One chamfered corridor wall (room face toward -Y, floor edge at Y=0)."""
    name = f"SM_CorridorWall_{round(length * 100)}{'_Cut' if cut else ''}"
    top = CUT_HEIGHT if cut else CEILING
    x0, x1 = -length / 2, length / 2

    body = kit.MeshBuilder()
    if cut:
        prof = [
            (0.03, 0.0),
            (0.03, 0.1),
            (CHAMFER_Y + 0.03, CHAMFER_Z),
            (CHAMFER_Y + 0.03, top),
            (BODY_Y, top),
            (BODY_Y, 0.0),
        ]
    else:
        prof = [
            (0.03, 0.0), (0.03, 0.1), (CHAMFER_Y + 0.03, CHAMFER_Z), (CHAMFER_Y + 0.03, TRIM[1]),
            (UPPER_Y + 0.03, CEILING), (BODY_Y, CEILING), (BODY_Y, 0.0),
        ]  # fmt: skip
    body.prism_x(prof, x0, x1, "M_Recess_Dark")
    body.box((x0, 0.0, 0.0), (x1, 0.035, 0.1), "M_Wall_PaintedDark")
    cap_y0 = CHAMFER_Y - 0.004 if cut else UPPER_Y - 0.004
    body.box((x0, cap_y0, top - 0.02), (x1, BODY_Y, top), "M_Section_Cap")
    body.build(f"{name}_body", bevel_width=0.003)

    panels = kit.MeshBuilder()
    for a, b in _modules(length):
        a, b = a + GAP / 2, b - GAP / 2
        _slab(
            panels, (0.0, 0.1 + GAP), (CHAMFER_Y, CHAMFER_Z - GAP / 2), a, b, "M_Wall_PaintedDark"
        )
        if not cut:
            _slab(
                panels,
                (CHAMFER_Y, STRIP_TOP + GAP / 2),
                (CHAMFER_Y, PANEL_SPLIT - GAP / 2),
                a,
                b,
                "M_Wall_PaintedMid",
            )
            _slab(
                panels,
                (CHAMFER_Y, PANEL_SPLIT + GAP / 2),
                (CHAMFER_Y, TRIM[0] - GAP / 2),
                a,
                b,
                "M_Wall_PaintedMid",
            )
            _slab(
                panels,
                (CHAMFER_Y, TRIM[1] + GAP / 2),
                (UPPER_Y, CEILING - 0.02),
                a,
                b,
                "M_Wall_PaintedMid",
            )
    if not cut:
        _slab(
            panels,
            (CHAMFER_Y - 0.004, TRIM[0]),
            (CHAMFER_Y - 0.004, TRIM[1]),
            x0,
            x1,
            "M_Trim_BrushedSteel",
            0.05,
        )
    panels.build(f"{name}_panels", bevel_width=0.003)

    # Light strip housing between the chamfer and the vertical panels.
    lips = kit.MeshBuilder()
    lips.box(
        (x0, CHAMFER_Y - 0.004, CHAMFER_Z),
        (x1, CHAMFER_Y + 0.04, CHAMFER_Z + 0.02),
        "M_Trim_BrushedSteel",
    )
    if not cut:
        lips.box(
            (x0, CHAMFER_Y - 0.004, STRIP_TOP - 0.02),
            (x1, CHAMFER_Y + 0.04, STRIP_TOP),
            "M_Trim_BrushedSteel",
        )
    lips.build(f"{name}_lips", bevel_width=0.002)
    strip_top = min(STRIP_TOP - 0.02, top - 0.025)
    kit.emissive_panel(
        f"{name}_strip",
        (0.0, CHAMFER_Y + 0.02, (CHAMFER_Z + 0.02 + strip_top) / 2),
        (length - 0.002, strip_top - CHAMFER_Z - 0.02),
        "M_Light_WallStrip",
        normal="-Y",
    )
    kit.occluder(((x0, 0.0, 0.0), (x1, BODY_Y, top)))
    if cut:
        with kit.ghost(CUT_HEIGHT):
            build_corridor_wall(length)


def build_corridor(length: float, *, full: bool = False) -> None:
    """A complete corridor slice: floor, two walls, ceiling and lights."""
    tag = f"{round(length * 100)}"
    name = f"SM_Corridor_{tag}{'_Full' if full else ''}"
    x0, x1 = -length / 2, length / 2
    floor = kit.MeshBuilder()
    floor.box((x0, -OUTER_HALF, -0.12), (x1, OUTER_HALF, 0.0), "M_Floor_GlossBlack")
    floor.build(f"{name}_floor", bevel_width=0.0, nav="walk")
    kit.place(f"SM_CorridorWall_{tag}", (0.0, FLOOR_HALF, 0.0), 0.0, id=f"{name}_far")
    near = f"SM_CorridorWall_{tag}" if full else f"SM_CorridorWall_{tag}_Cut"
    kit.place(near, (0.0, -FLOOR_HALF, 0.0), 180.0, id=f"{name}_near")
    hy = FLOOR_HALF + UPPER_Y + 0.05
    ceiling.ceiling_slab(f"{name}_ceiling", [(x0, -hy), (x1, -hy), (x1, hy), (x0, hy)], CEILING)
    count = max(1, round(length / 2.4))
    for i in range(count):
        cx = x0 + (i + 0.5) * length / count
        ceiling.light_panel(f"{name}_lgt_{i}", (cx, 0.0, CEILING), size=(0.6, 2.4))


def build_pilaster(*, cut: bool = False) -> None:
    """Heavy bulkhead column at corridor junctions and door jambs."""
    top = CUT_HEIGHT if cut else CEILING
    name = f"SM_Bulkhead_Pilaster{'_Cut' if cut else ''}"
    s = 0.45
    c = 0.12  # corner chamfer
    oct_ = [
        (-s + c, -s),
        (s - c, -s),
        (s, -s + c),
        (s, s - c),
        (s - c, s),
        (-s + c, s),
        (-s, s - c),
        (-s, -s + c),
    ]
    mb = kit.MeshBuilder()
    mb.prism_z(oct_, 0.14, top - 0.02, "M_Struct_Gunmetal")
    mb.prism_z([(x * 1.06, y * 1.06) for x, y in oct_], 0.0, 0.14, "M_Wall_PaintedDark")
    mb.prism_z([(x * 1.01, y * 1.01) for x, y in oct_], top - 0.02, top, "M_Section_Cap")
    if not cut:
        mb.box((-0.2, -s - 0.01, 2.2), (0.2, -s + 0.02, 2.24), "M_Trim_BrushedSteel")
    mb.build(f"{name}_column", bevel_width=0.01, segments=3)
    # Recessed seam groove down the faces seen by the camera.
    groove = kit.MeshBuilder()
    groove.box((-0.012, -s - 0.003, 0.2), (0.012, -s + 0.01, top - 0.08), "M_Recess_Dark")
    groove.build(f"{name}_groove", bevel_width=0.0)
    if not cut:
        lamp = kit.MeshBuilder()
        lamp.box((-0.05, -s - 0.02, 1.62), (0.05, -s + 0.01, 1.7), "M_Struct_Gunmetal")
        lamp.build(f"{name}_lamp_housing", bevel_width=0.003)
        kit.emissive_panel(
            f"{name}_lamp", (0.0, -s - 0.021, 1.66), (0.07, 0.05), "M_Indicator_Red", normal="-Y"
        )
    kit.occluder(((-s, -s, 0.0), (s, s, top)))
    if cut:
        with kit.ghost(CUT_HEIGHT):
            build_pilaster()


def build_junction() -> None:
    """6 x 6 m corridor crossing: floor, four pilasters, ceiling grid."""
    h = 3.0
    floor = kit.MeshBuilder()
    floor.box((-h, -h, -0.12), (h, h, 0.0), "M_Floor_GlossBlack")
    floor.build("SM_Corridor_Junction_floor", bevel_width=0.0, nav="walk")
    p = FLOOR_HALF + 0.45
    for sx in (-1, 1):
        kit.place(
            "SM_Bulkhead_Pilaster", (sx * p, p, 0.0), 0.0, id=f"SM_Corridor_Junction_pf{sx + 1}"
        )
        kit.place(
            "SM_Bulkhead_Pilaster_Cut",
            (sx * p, -p, 0.0),
            0.0,
            id=f"SM_Corridor_Junction_pn{sx + 1}",
        )
    ceiling.ceiling_slab(
        "SM_Corridor_Junction_ceiling", [(-h, -h), (h, -h), (h, h), (-h, h)], CEILING
    )
    for i, (cx, cy) in enumerate(((-0.9, -0.9), (0.9, -0.9), (-0.9, 0.9), (0.9, 0.9))):
        ceiling.light_panel(f"SM_Corridor_Junction_lgt_{i}", (cx, cy, CEILING), size=(1.2, 1.2))


for _l in LENGTHS:
    _t = round(_l * 100)
    kit.register_variant(
        f"SM_CorridorWall_{_t}", build_corridor_wall, dims=(_l, BODY_Y, CEILING), length=_l
    )
    kit.register_variant(
        f"SM_CorridorWall_{_t}_Cut",
        build_corridor_wall,
        dims=(_l, BODY_Y, CUT_HEIGHT),
        length=_l,
        cut=True,
    )
    kit.register_variant(
        f"SM_Corridor_{_t}",
        build_corridor,
        dims=(_l, 2 * OUTER_HALF, CEILING),
        nav="walk",
        length=_l,
    )
    kit.register_variant(
        f"SM_Corridor_{_t}_Full",
        build_corridor,
        dims=(_l, 2 * OUTER_HALF, CEILING),
        nav="walk",
        length=_l,
        full=True,
    )
kit.register_variant("SM_Bulkhead_Pilaster", build_pilaster, dims=(0.9, 0.9, CEILING))
kit.register_variant(
    "SM_Bulkhead_Pilaster_Cut", build_pilaster, dims=(0.9, 0.9, CUT_HEIGHT), cut=True
)
kit.register_variant("SM_Corridor_Junction", build_junction, dims=(6.0, 6.0, CEILING), nav="walk")
