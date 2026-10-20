"""The bridge's hero wall: slanted forward viewports in heavy mullions.

The wall runs along the far edge of the hall (plan z = 3.6) and turns back
through two 45 degree chamfers. Each run has three parts:

* a vertical sill (0 - 1.1 m): kick plate, light-grey instrument panels on
  the 1.2 m module, vertical light slits under every mullion, a brushed
  ledge officers lean on;
* the window band, leaning back 25 degrees so the camera sees it nearly
  face-on: thick mullions that alternate their slant, so the panes alternate
  between wide-top and wide-bottom trapezoids, rounded inner corners, the
  glass set 0.48 m deep, a dim star field 1.4 m behind the glass;
* the header: panelled band with vents, then a deep beam with a down-light
  that washes the frames.

Heavy leaning piers hide the joints between runs.
"""

from __future__ import annotations

import math

import bpy
from lib import kit, scene
from mathutils import Matrix, Vector

from . import geo
from . import layout as L

LEAN = 25.0
WIN_Y0, WIN_Z0 = 0.35, 1.1  # start of the window band in the run frame
HW = 4.8  # slope length of the window band
RAIL_B, RAIL_T = 0.42, 0.45
MULLION_W = 0.56
SLANT = 0.9
DEPTH = 0.62
GLASS_Y = 0.5
STAR_Y = 1.9
HEADER = 1.3
BEAM = 1.6
FRAME = "M_Wall_PaintedLight"
SILL = "M_Wall_Charcoal"  # hero wall panelling under the windows
STAR_SCALE = 2.0  # star field texture scale (stars a pixel wide at full density)


def scale_texture(obj, factor: float) -> None:
    """Scale an object's object-space texture by ``factor`` in place: the mesh
    shrinks by 1/factor about the world origin and the object scales back."""
    obj.data.transform(Matrix.Scale(1.0 / factor, 4))
    obj.scale = (factor, factor, factor)


def _boundaries_centre(length: float):
    """(x, slant) of every mullion; slant 0 marks the piers at both ends."""
    first = -L.VP_BAYS * L.VP_BAY / 2
    out = []
    for k in range(L.VP_BAYS + 1):
        x = first + k * L.VP_BAY
        if k in (0, L.VP_BAYS):
            out.append((x, 0))
        else:
            out.append((x, 1 if (k - (L.VP_BAYS + 1) // 2) % 2 == 0 else -1))
    return out


def _pane(bnds, k, zr0, zr1):
    (b0, s0), (b1, s1) = bnds[k], bnds[k + 1]
    w, d = MULLION_W, SLANT
    return [
        (b0 - s0 * d / 2 + w / 2, zr0),
        (b1 - s1 * d / 2 - w / 2, zr0),
        (b1 + s1 * d / 2 - w / 2, zr1),
        (b0 + s0 * d / 2 + w / 2, zr1),
    ]


def build_run(name: str, a_plan, b_plan, bnds=None, *, slits: bool = True) -> dict:
    """One straight run of the viewport wall from plan point a to b."""
    seg, length = geo.segment_matrix(a_plan, b_plan)
    x0, x1 = -length / 2, length / 2
    if bnds is None:
        bnds = _boundaries_centre(length)
    _sill(name, seg, x0, x1, bnds, slits)
    lean = geo.lean_matrix(seg, WIN_Y0, WIN_Z0, LEAN)
    _window_band(name, lean, x0, x1, bnds)
    _header(name, lean, x0, x1, bnds)
    _glass_and_stars(name, lean, x0, x1)
    _window_light(name, lean, length)
    # Occluder: the sill block (people stand in front of it).
    geo.matrix_ucx(f"{name}_sill", seg, (x0, -0.25, 0.0), (x1, 0.7, 1.12))
    return {"matrix": seg, "length": length}


# ---------------------------------------------------------------- sill


def _sill(name, seg, x0, x1, bnds, slits: bool) -> None:
    body = kit.MeshBuilder(seg)
    trim = kit.MeshBuilder(seg)
    inst = kit.MeshBuilder(seg)
    lamps = kit.MeshBuilder(seg)
    body.box((x0, 0.03, 0.0), (x1, 0.7, 0.14), "M_Wall_PaintedDark")
    body.box((x0, 0.025, 0.14), (x1, 0.7, 0.98), "M_Recess_Dark")
    n = max(1, round((x1 - x0) / L.M))
    step = (x1 - x0) / n
    slit_x = {round(b, 3) for b, s in bnds if s != 0}
    gap = 0.008
    for i in range(n):
        a, b = x0 + i * step, x0 + (i + 1) * step
        body.box((a + gap / 2, 0.0, 0.15), (b - gap / 2, 0.04, 0.97), SILL)
        mid = (a + b) / 2
        kind = kit.seed_for(name, i) % 7
        if kind in (0, 3):
            _instrument_inset(inst, lamps, mid, step, kit.seed_for(name, "inst", i))
        elif kind == 5:
            # Small access hatch with two fasteners.
            inst.box((mid - 0.3, -0.008, 0.3), (mid + 0.3, 0.0, 0.62), SILL)
            for bx in (mid - 0.24, mid + 0.24):
                inst.box(
                    (bx - 0.012, -0.012, 0.58), (bx + 0.012, -0.008, 0.6), "M_Trim_BrushedSteel"
                )
    # Ledge with a brushed nosing.
    trim.box((x0, -0.2, 0.98), (x1, 0.72, 1.1), FRAME)
    trim.box((x0, -0.235, 0.985), (x1, -0.195, 1.1), "M_Trim_BrushedSteel")
    trim.box((x0, -0.05, 0.94), (x1, 0.02, 0.98), "M_Recess_Dark")
    body.build(f"SM_{name}_sill", bevel_width=0.004)
    trim.build(f"SM_{name}_ledge", bevel_width=0.005)
    inst.build(f"SM_{name}_sill_inst", bevel_width=0.002)
    lamps.build(f"SM_{name}_sill_lamps", bevel_width=0.0)
    if not slits:
        return
    # Light columns under every mullion: three stacked backlit rectangles in
    # a dark reveal (the hero wall motif), mirrored by the black deck.
    reveal = kit.MeshBuilder(seg)
    column = kit.MeshBuilder(seg)
    for bx in sorted(slit_x):
        reveal.box((bx - 0.08, -0.012, 0.18), (bx + 0.08, 0.0, 0.92), "M_Recess_Dark")
        for k in range(3):
            z = 0.22 + k * 0.235
            column.box((bx - 0.035, -0.016, z), (bx + 0.035, -0.012, z + 0.2), "M_Light_Backlit")
    reveal.build(f"SM_{name}_sill_reveals", bevel_width=0.003)
    lit = column.build(f"SM_{name}_sill_columns", bevel_width=0.0, nav="none")
    if lit is not None:
        lit.visible_shadow = False
        lit["light_kind"] = "sill_column"


def _instrument_inset(inst, lamps, mid, step, seed) -> None:
    rng = _rng(seed)
    w = step - 0.34
    inst.box((mid - w / 2, -0.014, 0.36), (mid + w / 2, 0.0, 0.84), "M_Console_Body")
    rows = 3 + rng % 2
    for r in range(rows):
        z = 0.44 + r * 0.1
        cols = 6
        for c in range(cols):
            lx = mid - w / 2 + 0.08 + c * (w - 0.16) / (cols - 1)
            pick = kit.seed_for(seed, r, c) % 11
            if pick < 4:
                mat = "M_Indicator_White" if pick < 3 else "M_Indicator_Red"
                lamps.box((lx - 0.018, -0.02, z), (lx + 0.018, -0.014, z + 0.05), mat)
            else:
                inst.box((lx - 0.018, -0.018, z), (lx + 0.018, -0.014, z + 0.05), "M_Console_Keys")


def _rng(seed: int) -> int:
    return (seed * 2654435761) % 4294967296


def _quad_facing(name, seg, centre, w, h, material):
    """Emitter quad in the run's plane facing the room (local -Y)."""
    x = seg.to_3x3() @ Vector((1, 0, 0))
    z = Vector((0, 0, 1))
    c = Vector(centre)
    corners = [c - x * w / 2 - z * h / 2, c + x * w / 2 - z * h / 2, c + x * w / 2 + z * h / 2]
    corners.append(c - x * w / 2 + z * h / 2)
    obj = kit.mesh_object(name, corners, [(0, 1, 2, 3)], material)
    normal = (corners[1] - corners[0]).cross(corners[2] - corners[1])
    room = seg.to_3x3() @ Vector((0, -1, 0))
    if normal.dot(room) < 0:
        obj.data.flip_normals()
    return obj


# ---------------------------------------------------------------- window band


def _window_band(name, lean, x0, x1, bnds) -> None:
    frame = kit.MeshBuilder(lean)
    face = kit.MeshBuilder(lean)
    zr0, zr1 = RAIL_B, HW - RAIL_T
    # Rails and piers.
    frame.box((x0, 0.0, 0.0), (x1, DEPTH, zr0), FRAME)
    frame.box((x0, 0.0, zr1), (x1, DEPTH, HW), FRAME)
    (bf, _), (bl, _) = bnds[0], bnds[-1]
    frame.box((x0, 0.0, zr0), (bf + MULLION_W / 2, DEPTH, zr1), FRAME)
    frame.box((bl - MULLION_W / 2, 0.0, zr0), (x1, DEPTH, zr1), FRAME)
    # Proud fascia on the rails (double-line frame look), split into 1.2 m
    # plates with 8 mm seams and a pair of fasteners at every joint.
    n = max(1, round((x1 - x0) / L.M))
    step = (x1 - x0) / n
    bolts = kit.MeshBuilder(lean)
    for i in range(n):
        a, b = x0 + i * step + 0.004, x0 + (i + 1) * step - 0.004
        face.box((a, -0.035, 0.06), (b, 0.0, zr0 - 0.1), FRAME)
        face.box((a, -0.035, zr1 + 0.1), (b, 0.0, HW - 0.06), FRAME)
        for zc in (0.12, zr0 - 0.16, zr1 + 0.16, HW - 0.12):
            bolts.box(
                (a + 0.03, -0.041, zc - 0.012),
                (a + 0.054, -0.035, zc + 0.012),
                "M_Trim_BrushedSteel",
            )
    bolts.build(f"SM_{name}_frame_bolts", bevel_width=0.001)
    w, d = MULLION_W, SLANT
    for b, s in bnds[1:-1]:
        poly = [
            (b - s * d / 2 - w / 2, zr0),
            (b - s * d / 2 + w / 2, zr0),
            (b + s * d / 2 + w / 2, zr1),
            (b + s * d / 2 - w / 2, zr1),
        ]
        geo.prism_y(frame, poly, 0.0, DEPTH, FRAME)
        inner = [
            (b - s * d / 2 - w / 2 + 0.13, zr0 - 0.12),
            (b - s * d / 2 + w / 2 - 0.13, zr0 - 0.12),
            (b + s * d / 2 + w / 2 - 0.13, zr1 + 0.12),
            (b + s * d / 2 - w / 2 + 0.13, zr1 + 0.12),
        ]
        geo.prism_y(face, inner, -0.035, 0.0, FRAME)
        inner2 = [
            (b - s * d / 2 - w / 2 + 0.21, zr0 - 0.2),
            (b - s * d / 2 + w / 2 - 0.21, zr0 - 0.2),
            (b + s * d / 2 + w / 2 - 0.21, zr1 + 0.2),
            (b + s * d / 2 - w / 2 + 0.21, zr1 + 0.2),
        ]
        geo.prism_y(face, inner2, -0.065, -0.035, FRAME)
    # Rounded inner corners of every pane, set 2 cm back from the frame face.
    for k in range(len(bnds) - 1):
        bl_, br_, tr_, tl_ = _pane(bnds, k, zr0, zr1)
        for corner, a, b, r in (
            (bl_, br_, tl_, 0.42),
            (br_, tr_, bl_, 0.42),
            (tr_, tl_, br_, 0.32),
            (tl_, bl_, tr_, 0.32),
        ):
            geo.prism_y(frame, geo.fillet(corner, a, b, r), 0.02, DEPTH, FRAME)
    frame.build(f"SM_{name}_frame", bevel_width=0.012, segments=3)
    face.build(f"SM_{name}_fascia", bevel_width=0.008, segments=2)
    # Glass gasket: a dark rubber reveal just in front of the glass.
    gasket = kit.MeshBuilder(lean)
    for k in range(len(bnds) - 1):
        pane = _pane(bnds, k, zr0, zr1)
        outer = pane
        inner = geo.offset_polygon(pane, 0.05)
        for i in range(4):
            quad = [outer[i], outer[(i + 1) % 4], inner[(i + 1) % 4], inner[i]]
            geo.prism_y(gasket, quad, GLASS_Y - 0.03, GLASS_Y, "M_Rubber_Black")
    gasket.build(f"SM_{name}_gasket", bevel_width=0.0)


# ---------------------------------------------------------------- header


def _header(name, lean, x0, x1, bnds) -> None:
    panels = kit.MeshBuilder(lean)
    vents = kit.MeshBuilder(lean)
    lamps = kit.MeshBuilder(lean)
    h0, h1 = HW, HW + HEADER
    panels.box((x0, 0.03, h0), (x1, DEPTH, h1), "M_Recess_Dark")
    n = max(1, round((x1 - x0) / L.M))
    step = (x1 - x0) / n
    for i in range(n):
        a, b = x0 + i * step, x0 + (i + 1) * step
        panels.box((a + 0.004, 0.0, h0 + 0.004), (b - 0.004, 0.05, h1 - 0.004), FRAME)
        k = kit.seed_for(name, "hdr", i) % 9
        mid = (a + b) / 2
        if k in (1, 4, 7):
            for j in range(5):
                z = h0 + 0.35 + j * 0.13
                vents.box((mid - 0.38, -0.012, z), (mid + 0.38, 0.0, z + 0.06), "M_Recess_Dark")
        elif k == 2:
            vents.box(
                (mid - 0.22, -0.016, h0 + 0.5), (mid + 0.22, 0.0, h0 + 0.82), "M_Console_Body"
            )
            lamps.box(
                (mid - 0.16, -0.022, h0 + 0.62), (mid - 0.1, -0.016, h0 + 0.7), "M_Indicator_Red"
            )
            lamps.box(
                (mid - 0.04, -0.022, h0 + 0.62), (mid + 0.02, -0.016, h0 + 0.7), "M_Indicator_White"
            )
    panels.build(f"SM_{name}_header", bevel_width=0.004)
    vents.build(f"SM_{name}_header_vents", bevel_width=0.002)
    lamps.build(f"SM_{name}_header_lamps", bevel_width=0.0)
    # Deep beam over the header; its underside carries a down-light.
    beam = kit.MeshBuilder(lean)
    b0, b1 = h1, h1 + BEAM
    beam.box((x0, -0.45, b0), (x1, 1.2, b1), "M_Wall_PaintedMid")
    beam.box((x0, -0.47, b0 + 0.25), (x1, -0.45, b0 + 0.3), "M_Trim_BrushedSteel")
    beam.box((x0, -0.45, b1 - 0.02), (x1, 1.2, b1), "M_Section_Cap")
    beam.build(f"SM_{name}_beam", bevel_width=0.01, segments=2)
    # Down-light under the beam, one lens per bay (washes the frames).
    cove = kit.MeshBuilder(lean)
    for k in range(len(bnds) - 1):
        c = (bnds[k][0] + bnds[k + 1][0]) / 2
        half = 0.45
        cove.quad(
            [
                (c - half, -0.24, b0 - 0.005),
                (c - half, -0.16, b0 - 0.005),
                (c + half, -0.16, b0 - 0.005),
                (c + half, -0.24, b0 - 0.005),
            ],
            "M_Light_WallStrip",
        )
    obj = cove.build(f"SM_{name}_cove_light", bevel_width=0.0, nav="none")
    down = lean.to_3x3() @ Vector((0, 0, -1))
    poly = obj.data.polygons[0]
    if poly.normal.dot(down) < 0:
        obj.data.flip_normals()
    obj["light_kind"] = "viewport_cove"


# ---------------------------------------------------------------- glass, stars, key


def _glass_and_stars(name, lean, x0, x1) -> None:
    """Star field behind the panes. No glass sheet: at this angle a mirror
    of the walkway would fill the panes and hide the stars."""
    s = kit.MeshBuilder(lean)
    s.quad(
        [
            (x0 - 1.5, STAR_Y, -2.8),
            (x1 + 1.5, STAR_Y, -2.8),
            (x1 + 1.5, STAR_Y, HW + 0.6),
            (x0 - 1.5, STAR_Y, HW + 0.6),
        ],
        "M_Starfield",
    )
    stars = s.build(f"SM_{name}_starfield", bevel_width=0.0, nav="none")
    stars.visible_shadow = False
    stars.visible_diffuse = False
    scale_texture(stars, STAR_SCALE)
    # A dark box behind the glass so the window reads as deep, not as a hole.
    box = kit.MeshBuilder(lean)
    box.box((x0 - 1.5, STAR_Y + 0.02, -2.8), (x1 + 1.5, STAR_Y + 0.3, HW + 0.6), "M_Recess_Dark")
    box.build(f"SM_{name}_window_back", bevel_width=0.0, nav="none")


def _window_light(name, lean, length) -> None:
    """Cool, soft key through the viewports (starlight and the fleet's
    running lights): a large area light just behind the glass."""
    data = bpy.data.lights.new(f"LT_{name}_key", "AREA")
    data.shape = "RECTANGLE"
    data.size = length
    data.size_y = HW - 1.0
    data.energy = 9.0 * length * (HW - 1.0)
    data.use_temperature = True
    data.temperature = 9500.0
    data.spread = math.radians(120.0)
    obj = bpy.data.objects.new(f"LT_{name}_key", data)
    centre = lean @ Vector((0.0, GLASS_Y + 0.3, HW / 2))
    into_room = (lean.to_3x3() @ Vector((0.0, -1.0, -0.35))).normalized()
    up = Vector((0, 0, 1))
    zaxis = -into_room
    xaxis = up.cross(zaxis).normalized()
    yaxis = zaxis.cross(xaxis)
    m = Matrix((xaxis, yaxis, zaxis)).transposed().to_4x4()
    m.translation = centre
    obj.matrix_world = m
    obj.visible_camera = False
    obj.visible_glossy = False
    scene.collection("Lights").objects.link(obj)


# ---------------------------------------------------------------- piers


def build_pier(name: str, point_plan, room_normal_plan, *, red: bool = False) -> None:
    """Heavy leaning pier hiding the joint of two runs."""
    nf = geo.normal_frame(point_plan, room_normal_plan)
    body = kit.MeshBuilder(nf)
    body.prism_z(
        [(-0.95, 1.6), (-0.95, 0.06), (-0.62, -0.3), (0.62, -0.3), (0.95, 0.06), (0.95, 1.6)],
        0.0,
        1.1,
        FRAME,
    )
    lean = geo.lean_matrix(nf, WIN_Y0 - 0.2, WIN_Z0, LEAN)
    upper = kit.MeshBuilder(lean)
    upper.prism_z(
        [(-1.05, 1.8), (-1.05, 0.0), (-0.7, -0.38), (0.7, -0.38), (1.05, 0.0), (1.05, 1.8)],
        0.0,
        HW + HEADER + BEAM,
        FRAME,
        cap_material="M_Section_Cap",
    )
    upper.prism_z(
        [(-0.42, -0.36), (0.42, -0.36), (0.42, -0.42), (-0.42, -0.42)],
        0.6,
        HW - 0.6,
        "M_Wall_PaintedMid",
    )
    body.build(f"SM_{name}_base", bevel_width=0.012, segments=3)
    upper.build(f"SM_{name}_upper", bevel_width=0.014, segments=3)
    if red:
        lamps = kit.MeshBuilder(nf)
        for dx in (-0.2, 0.2):
            lamps.box((dx - 0.035, -0.32, 0.18), (dx + 0.035, -0.29, 0.92), "M_Indicator_Red")
        lamps.build(f"SM_{name}_red", bevel_width=0.0)
    geo.matrix_ucx(f"{name}_pier", nf, (-0.95, -0.3, 0.0), (0.95, 1.6, 2.5))


def build() -> None:
    """The whole forward wall: centre run, chamfer runs and four piers."""
    z = L.VP_FACE_Z
    c0, c1 = L.VP_CENTRE_X
    sx0, sx1 = L.SIDE_WALL_X
    build_run("vp_centre", (c0, z), (c1, z))
    ch = L.CHAMFER
    one_bay = None
    for side, a, b in ((-1, (sx0, z + ch), (c0, z)), (1, (c1, z), (sx1, z + ch))):
        seg_len = math.hypot(b[0] - a[0], b[1] - a[1])
        one_bay = [(-seg_len / 2 + 1.0, 0), (seg_len / 2 - 1.0, 0)]
        build_run(f"vp_chamfer_{'p' if side < 0 else 's'}", a, b, one_bay)
    s2 = math.sqrt(0.5)
    b1 = Vector((s2, s2 + 1.0)).normalized()
    b2 = Vector((s2 + 1.0, s2)).normalized()
    build_pier("vp_pier_p1", (c0, z), (b1.x, b1.y), red=True)
    build_pier("vp_pier_s1", (c1, z), (-b1.x, b1.y), red=True)
    build_pier("vp_pier_p2", (sx0, z + ch), (b2.x, b2.y))
    build_pier("vp_pier_s2", (sx1, z + ch), (-b2.x, b2.y))
