"""Stairs, railings, catwalks, pillars and bulkhead frames.

* ``SM_Stairs_<w>_H<rise>`` - straight flight descending toward +X from the
  top edge at the origin (Z = 0) to Z = -rise; 0.2 m risers, 0.3 m treads,
  brushed nosings with a thin light inlay, gunmetal cheek walls.
* ``SM_Railing_120`` / ``_240`` - 1.0 m guard rail along X, posts on the
  1.2 m module (offset half a module so tiled rails never double a post).
* ``SM_Catwalk_240`` - 1.2 m wide grated walkway over a void, no rails,
  channel stringers and cross beams below.
* ``SM_Pillar_120`` / ``_Cut`` - 1.2 x 1.2 m chamfered column.
* ``SM_Bulkhead_Frame_Corridor`` - structural ring around a corridor running
  along X; its overhead beam is camera-invisible like every ceiling.
"""

from __future__ import annotations

from lib import kit

from . import corridor, walls

RISER = 0.2
TREAD = 0.3


def build_stairs(width: float, rise: float) -> None:
    """One solid flight (no grooves between treads, so the nav cook sees a
    continuous walkable surface), brushed nosings set 2 mm proud, a thin worn
    hazard band on the walkway before the top edge, gunmetal cheek walls."""
    name = f"SM_Stairs_{round(width * 100)}_H{round(rise * 100):03d}"
    steps = round(rise / RISER)
    hw = width / 2
    run = (steps - 1) * TREAD
    profile = [(0.0, -rise), (0.0, -RISER)]
    for i in range(steps - 1):
        top = -(i + 1) * RISER
        profile += [(i * TREAD, top), ((i + 1) * TREAD, top)]
    profile.append((run, -rise))
    clean = [profile[0]]
    for p in profile[1:]:
        if abs(p[0] - clean[-1][0]) > 1e-6 or abs(p[1] - clean[-1][1]) > 1e-6:
            clean.append(p)
    body = kit.MeshBuilder()
    body.prism_y(clean, -hw + 0.06, hw - 0.06, "M_Floor_GlossBlack")
    body.build(f"{name}_flight", bevel_width=0.003, nav="walk")
    nosing = kit.MeshBuilder()
    for i in range(steps - 1):
        x0, top = i * TREAD, -(i + 1) * RISER
        nosing.box(
            (x0 - 0.002, -hw + 0.06, top - 0.04),
            (x0 + 0.05, hw - 0.06, top + 0.002),
            "M_Trim_BrushedSteel",
        )
    nosing.build(f"{name}_nosing", bevel_width=0.0015, nav="walk")
    from . import floors

    floors.marking(f"{name}_edge", -0.07, -hw + 0.08, -0.01, hw - 0.08, 0.0, hazard=True)
    cheeks = kit.MeshBuilder()
    for sy in (-1, 1):
        y0, y1 = sorted((sy * hw, sy * (hw - 0.06)))
        cheeks.prism_x(
            [(y0, -rise), (y1, -rise), (y1, 0.0), (y0, 0.0)], 0.0, run, "M_Struct_Gunmetal"
        )
    cheeks.build(f"{name}_cheeks", bevel_width=0.006)
    kit.socket("waypoint", "top", kit.facing_matrix((-0.3, 0.0, 0.0), 90.0))
    kit.socket("waypoint", "bottom", kit.facing_matrix((run + 0.4, 0.0, -rise), 90.0))


def build_railing(length: float) -> None:
    name = f"SM_Railing_{round(length * 100)}"
    h = length / 2
    mb = kit.MeshBuilder()
    count = max(1, round(length / kit.MODULE))
    for i in range(count):
        x = -h + (i + 0.5) * length / count
        mb.box((x - 0.025, -0.025, 0.0), (x + 0.025, 0.025, 0.98), "M_Struct_Gunmetal")
        mb.box((x - 0.06, -0.06, 0.0), (x + 0.06, 0.06, 0.012), "M_Struct_Gunmetal")
    mb.build(f"{name}_posts", bevel_width=0.004)
    rails = kit.MeshBuilder()
    rails.tube((-h, 0.0, 1.0), (h, 0.0, 1.0), 0.024, "M_Trim_BrushedSteel", segments=16)
    rails.tube((-h, 0.0, 0.52), (h, 0.0, 0.52), 0.012, "M_Trim_BrushedSteel", segments=12)
    rails.build(f"{name}_rails", bevel_width=0.0)


def build_catwalk() -> None:
    """Grated catwalk segment, 2.4 x 1.2 m, deck at Z = 0."""
    deck = kit.MeshBuilder()
    x = -1.2 + 0.017
    while x < 1.2:
        deck.box((x - 0.002, -0.56, -0.03), (x + 0.002, 0.56, 0.0), "M_Floor_Grating")
        x += 0.034
    y = -0.55
    while y < 0.56:
        deck.box((-1.2, y - 0.003, -0.012), (1.2, y + 0.003, -0.004), "M_Floor_Grating")
        y += 0.1
    deck.build("SM_Catwalk_240_deck", bevel_width=0.0, nav="walk")
    steel = kit.MeshBuilder()
    for sy in (-1, 1):
        y0, y1 = sorted((sy * 0.6, sy * 0.56))
        steel.box((-1.2, y0, -0.22), (1.2, y1, 0.02), "M_Struct_Gunmetal")
        yi0, yi1 = sorted((sy * 0.56, sy * 0.5))
        steel.box((-1.2, yi0, -0.22), (1.2, yi1, -0.2), "M_Struct_Gunmetal")
    for xb in (-0.6, 0.6):
        steel.box((xb - 0.04, -0.56, -0.2), (xb + 0.04, 0.56, -0.04), "M_Struct_Gunmetal")
    steel.build("SM_Catwalk_240_frame", bevel_width=0.005)
    edge = kit.MeshBuilder()
    for sy in (-1, 1):
        y0, y1 = sorted((sy * 0.6, sy * 0.585))
        edge.box((-1.2, y0, 0.0), (1.2, y1, 0.024), "M_Trim_BrushedSteel")
    edge.build("SM_Catwalk_240_kerb", bevel_width=0.003)


def build_pillar(*, cut: bool = False) -> None:
    top = walls.CUT_HEIGHT if cut else walls.HEIGHT
    name = f"SM_Pillar_120{'_Cut' if cut else ''}"
    s, c = 0.6, 0.15
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
    core = kit.MeshBuilder()
    core.prism_z([(x * 0.94, y * 0.94) for x, y in oct_], 0.0, top - 0.02, "M_Struct_Gunmetal")
    core.prism_z([(x * 1.01, y * 1.01) for x, y in oct_], top - 0.02, top, "M_Section_Cap")
    core.prism_z([(x * 1.02, y * 1.02) for x, y in oct_], 0.0, 0.12, "M_Wall_PaintedDark")
    core.build(f"{name}_core", bevel_width=0.01, segments=3)
    panels = kit.MeshBuilder()
    bands = [(0.12, min(1.06, top - 0.02))]
    if not cut:
        bands += [(1.14, 2.78), (3.02, top - 0.04)]
    for z0, z1 in bands:
        mat = "M_Wall_PaintedMid" if z0 > 3 else "M_Wall_PaintedLight"
        for (ax, ay), (bx, by) in (
            (oct_[0], oct_[1]),
            (oct_[2], oct_[3]),
            (oct_[4], oct_[5]),
            (oct_[6], oct_[7]),
        ):
            nx, ny = (ay - by), (bx - ax)
            ln = (nx * nx + ny * ny) ** 0.5
            nx, ny = nx / ln * 0.04, ny / ln * 0.04
            ix, iy = (bx - ax) * 0.02, (by - ay) * 0.02
            quad = [
                (ax + ix, ay + iy),
                (bx - ix, by - iy),
                (bx - ix - nx, by - iy - ny),
                (ax + ix - nx, ay + iy - ny),
            ]
            panels.prism_z(quad, z0 + 0.003, z1 - 0.003, mat)
    panels.build(f"{name}_panels", bevel_width=0.003)
    if not cut:
        kit.emissive_panel(
            f"{name}_strip",
            (0.0, -s - 0.001, 2.9),
            (2 * (s - c) - 0.04, 0.16),
            "M_Light_WallStrip",
            normal="-Y",
        )
    kit.occluder(((-s, -s, 0.0), (s, s, top)))
    if cut:
        with kit.ghost(walls.CUT_HEIGHT):
            build_pillar()


def build_corridor_frame(both_cut: bool = False) -> None:
    """Gunmetal ring proud of a corridor's walls with a low gunmetal sill.
    The near leg is always cut at 1.1 m; ``both_cut`` also cuts the far leg
    (for corridors with walkable space beyond both walls)."""
    name = "SM_Bulkhead_Frame_Corridor" + ("_Cut" if both_cut else "")
    fh, ch, cy = corridor.FLOOR_HALF, corridor.CHAMFER_Y, corridor.CHAMFER_Z
    t = 0.3
    for side, cut in ((1, both_cut), (-1, True)):
        top = corridor.CUT_HEIGHT if cut else corridor.CEILING
        if cut:
            prof = [(0.0, 0.0), (ch, cy), (ch, top), (0.75, top), (0.75, 0.0)]
        else:
            upper = (corridor.UPPER_Y, corridor.CEILING)
            prof = [(0.0, 0.0), (ch, cy), (ch, corridor.TRIM[1]), upper, (0.75, top), (0.75, 0.0)]
        prof = [(side * (fh + y - 0.15), z) for y, z in prof]
        if side < 0:
            prof.reverse()
        mb = kit.MeshBuilder()
        mb.prism_x(prof, -t / 2, t / 2, "M_Struct_Gunmetal")
        mb.build(f"{name}_leg{side + 1}", bevel_width=0.015, segments=3)
        y0, y1 = sorted((side * (fh - 0.15), side * (fh + 0.75)))
        kit.occluder(((-t / 2, y0, 0.0), (t / 2, y1, top)))
    beam = kit.MeshBuilder()
    beam.box(
        (-t / 2, -fh - 0.6, corridor.CEILING - 0.35),
        (t / 2, fh + 0.6, corridor.CEILING),
        "M_Wall_Charcoal",
    )
    kit.hide_from_camera(beam.build(f"{name}_beam", bevel_width=0.015))
    sill = kit.MeshBuilder()
    sill.box((-0.05, -fh, -0.005), (0.05, fh, 0.004), "M_Rubber_Black")
    sill.build(f"{name}_sill", bevel_width=0.003, nav="walk")


for _w in (1.2, 2.4):
    for _r in (0.6, 1.4):
        kit.register_variant(
            f"SM_Stairs_{round(_w * 100)}_H{round(_r * 100):03d}",
            build_stairs,
            dims=((round(_r / RISER) - 1) * TREAD, _w, _r),
            nav="walk",
            width=_w,
            rise=_r,
        )
kit.register_variant("SM_Railing_120", build_railing, dims=(1.2, 0.12, 1.0), length=1.2)
kit.register_variant("SM_Railing_240", build_railing, dims=(2.4, 0.12, 1.0), length=2.4)
kit.register_variant("SM_Catwalk_240", build_catwalk, dims=(2.4, 1.2, 0.24), nav="walk")
kit.register_variant("SM_Pillar_120", build_pillar, dims=(1.2, 1.2, walls.HEIGHT))
kit.register_variant("SM_Pillar_120_Cut", build_pillar, dims=(1.2, 1.2, walls.CUT_HEIGHT), cut=True)
kit.register_variant(
    "SM_Bulkhead_Frame_Corridor",
    build_corridor_frame,
    dims=(0.3, 2 * corridor.OUTER_HALF, corridor.CEILING),
)
kit.register_variant(
    "SM_Bulkhead_Frame_Corridor_Cut",
    build_corridor_frame,
    dims=(0.3, 2 * corridor.OUTER_HALF, corridor.CUT_HEIGHT),
    both_cut=True,
)
