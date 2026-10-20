"""Reactor shaft assembly for the engineering deck (deck 3).

A circular shaft cut through the deck: a square floor collar with the hole and
its kerb, the shaft wall falling ~60 m into haze (the far inner wall is the
hero surface the 60-degree camera looks into), the hot core column rising from
below, a control ring around it and narrow catwalks without railings.

Piece-local frame: the shaft centre is the origin, the deck floor top is Z = 0,
+Y points away from the camera. Use :func:`place_reactor` to drop the whole
assembly; the pieces are also registered on their own.
"""

from __future__ import annotations

import math

from lib import kit as K
from mathutils import Vector

from . import _geo as G
from ._mats import m

SHAFT_RADIUS = 13.0
SHAFT_DEPTH = 64.0  # modelled depth; haze hides everything below ~45 m
CORE_RADIUS = 3.0
RING_INNER = 5.0
RING_OUTER = 6.5
CATWALK_WIDTH = 1.2
COLLAR_SIZE = 31.2  # 26 modules; leave this square open in the deck floor
BAYS = 32  # wall ribs around the shaft
RING_PITCH = 4.8  # shaft wall girder rhythm
BIG_RING_PITCH = 14.4
CATWALK_ANGLES = (90.0, 0.0, 270.0, 180.0)  # far (N), east, near (S), west


def _wall_radius(radius: float) -> float:
    return radius + 0.9


# --------------------------------------------------------------------------
# Collar: deck plate with the hole, kerb, rim plates, markings
# --------------------------------------------------------------------------


def build_collar(
    radius: float = SHAFT_RADIUS, size: float = COLLAR_SIZE, floor_role: str = "floor_engineering"
) -> None:
    """Square deck collar with the shaft hole, kerb lamps and rim plating.

    ``floor_role`` must match the hall floor around it (engineering deck:
    M_Floor_SatinDark) so the 31.2 m square leaves no seam in the plate.
    """
    half = size / 2
    mb = K.MeshBuilder()
    seg = 128  # a multiple of 8, so the square's corners get their own rays
    inner = radius + 2.4  # floor proper starts outside the rim band
    inner_pts, outer_pts = [], []
    for i in range(seg):
        a = math.tau * i / seg
        c, s = math.cos(a), math.sin(a)
        t = half / max(abs(c), abs(s))
        inner_pts.append((inner * c, inner * s))
        outer_pts.append((c * t, s * t))
    # closed 0.4 m slab: top faces up (the nav cook needs up-facing walk hits)
    G.slab_between(mb, inner_pts, outer_pts, -0.4, 0.0, m(floor_role))
    mb.build("SM_Reactor_Collar_floor", bevel_width=0.0, nav="walk")

    rim = K.MeshBuilder()
    plates = 48
    for i in range(plates):
        a0 = 360.0 * i / plates + 0.08
        a1 = 360.0 * (i + 1) / plates - 0.08
        G.ring(
            rim,
            radius + 0.36,
            inner - 0.01,
            -0.12,
            -0.004,
            m("tread" if i % 3 else "dark_steel"),
            4,
            a0,
            a1,
        )
        if i % 2 == 0:  # bolt strip on every second plate seam
            for k in range(3):
                r = radius + 0.7 + k * 0.6
                x, y, _ = G.polar(r, a0 + 0.4)
                rim.box((x - 0.03, y - 0.03, -0.004), (x + 0.03, y + 0.03, 0.006), m("dark_steel"))
    # kerb: chamfered steel lip at the edge of the drop, flush at the catwalks
    kerb = [
        (radius, -1.2),
        (radius + 0.36, -1.2),
        (radius + 0.36, 0.0),
        (radius + 0.3, 0.12),
        (radius + 0.06, 0.12),
        (radius, 0.06),
    ]
    flush = [(radius, -1.2), (radius + 0.36, -1.2), (radius + 0.36, 0.0), (radius, 0.0)]
    gap = math.degrees(math.asin((CATWALK_WIDTH / 2 + 0.15) / radius))
    for a0, a1 in _arcs_between(CATWALK_ANGLES, gap):
        G.lathe(rim, kerb, m("gunmetal"), max(4, int((a1 - a0) / 2)), a0, a1, closed=True)
    for ca in CATWALK_ANGLES:
        G.lathe(rim, flush, m("gunmetal"), 2, ca - gap, ca + gap, closed=True)
    rim.build("SM_Reactor_Collar_rim", bevel_width=0.012, nav="walk")

    lamps = K.MeshBuilder()  # sparse recessed kerb lamps (every 11.25 deg)
    for i in range(32):
        a = 360.0 * (i + 0.5) / 32
        if _near_catwalk(a, radius + 0.2, 1.0):
            continue
        with G.xf(lamps, G.Rz(a)):
            lamps.box((radius + 0.1, -0.04, 0.112), (radius + 0.15, 0.04, 0.121), m("lamp_dim"))
    lamps.build("SM_Reactor_Collar_lamps", bevel_width=0.0, nav="none")

    paint = K.MeshBuilder()  # thin worn hazard band and one keep-clear line
    G.annulus(paint, radius + 0.42, radius + 0.62, -0.003, m("hazard"), 192)
    G.annulus(paint, inner + 0.3, inner + 0.4, 0.001, m("stencil_white"), 192)
    paint.build("SM_Reactor_Collar_paint", bevel_width=0.0, nav="none")


def _arcs_between(angles, gap):
    """Angular arcs (deg) between sorted ``angles`` leaving ``gap`` on each side."""
    a = sorted(x % 360.0 for x in angles)
    return [
        (a[i] + gap, (a[(i + 1) % len(a)] + (360.0 if i == len(a) - 1 else 0.0)) - gap)
        for i in range(len(a))
    ]


def _near_catwalk(angle_deg: float, r: float, half_width: float) -> bool:
    for ca in CATWALK_ANGLES:
        d = math.radians((angle_deg - ca + 180.0) % 360.0 - 180.0)
        if abs(math.sin(d)) * r < half_width + 0.3 and math.cos(d) > 0:
            return True
    return False


# --------------------------------------------------------------------------
# Shaft wall
# --------------------------------------------------------------------------


def _wall_frame(angle_deg: float, r_wall: float):
    """Bay frame: wall surface at local y = 0 facing -Y (toward the core)."""
    return G.Rz(angle_deg) @ G.T(r_wall, 0.0, 0.0) @ G.Rz(-90.0)


def _bolts(mb, x0, x1, z0, z1, y, material, pitch=0.45):
    """Bolt heads along the four edges of a plate (face toward -Y at ``y``)."""
    nx = max(2, int((x1 - x0) / pitch))
    nz = max(2, int((z1 - z0) / pitch))
    pts = [(x0 + (x1 - x0) * i / nx, z) for i in range(nx + 1) for z in (z0, z1)]
    pts += [(x, z0 + (z1 - z0) * j / nz) for j in range(1, nz) for x in (x0, x1)]
    for x, z in pts:
        mb.box((x - 0.022, y - 0.018, z - 0.022), (x + 0.022, y, z + 0.022), material)


def _panel(mb, decals, kind: str, w: float, z0: float, z1: float, rnd) -> None:
    """One wall bay cell, built in the bay frame (face at y = 0, toward -Y)."""
    hw = w / 2
    dark, steel, metal = m("panel_dark"), m("dark_steel"), m("gunmetal")
    if kind == "plate":
        split = z0 + (z1 - z0) * rnd.choice((0.35, 0.5, 0.62))
        for a, b in ((z0, split), (split, z1)):  # two plates per bay
            mb.box((-hw + 0.02, -0.06, a + 0.01), (hw - 0.02, 0.0, b - 0.01), dark)
            _bolts(mb, -hw + 0.12, hw - 0.12, a + 0.1, b - 0.1, -0.06, steel)
        if rnd.random() < 0.5:  # inspection hatch
            hz = split + 0.35
            mb.box((-0.45, -0.1, hz), (0.45, -0.06, hz + 0.9), metal)
            mb.box((0.25, -0.13, hz + 0.38), (0.35, -0.1, hz + 0.52), steel)
        if rnd.random() < 0.45:
            letter, num, sub = rnd.choice("ABCDR"), rnd.randrange(1, 40), rnd.randrange(1, 9)
            code = f"{letter}{num:02d}-{sub}"
            G.text(
                decals,
                code,
                0.2,
                m("stencil_white"),
                G.on_face((-hw + 0.55, -0.062, split - 0.3), "-Y"),
            )
        if rnd.random() < 0.3:
            with G.xf(decals, G.on_face((hw - 0.5, -0.062, z1 - 0.45), "-Y")):
                decals.quad(
                    [(-0.22, -0.12, 0), (0.22, -0.12, 0), (0.22, 0.12, 0), (-0.22, 0.12, 0)],
                    m("hazard"),
                )
    elif kind == "vent":
        mb.box((-hw, -0.04, z0), (hw, 0.0, z1), steel)
        G.grille(
            mb,
            (-hw + 0.25, -0.12, z0 + 0.4),
            (hw - 0.25, -0.04, z1 - 0.4),
            metal,
            slats=int((z1 - z0) / 0.25),
            frame_material=steel,
        )
        _bolts(mb, -hw + 0.12, hw - 0.12, z0 + 0.15, z1 - 0.15, -0.04, metal, 0.6)
    elif kind == "pipes":
        mb.box((-hw, -0.04, z0), (hw, 0.0, z1), m("void_black"))
        n = 3 + rnd.randrange(2)
        for i in range(n):
            x = -hw + (i + 0.5) * w / n
            mb.tube((x, -0.3, z0), (x, -0.3, z1), 0.16, metal, 14, caps=False)
            for zc in (z0 + 1.1, z1 - 1.4):  # flanges
                mb.tube((x, -0.3, zc), (x, -0.3, zc + 0.1), 0.2, steel, 14)
        for zc in (z0 + 0.6, z1 - 0.6):
            mb.box((-hw, -0.52, zc - 0.08), (hw, -0.08, zc + 0.08), steel)
    elif kind == "machine":
        mb.box((-hw, -0.06, z0), (hw, 0.0, z1), dark)
        _bolts(mb, -hw + 0.12, hw - 0.12, z0 + 0.12, z1 - 0.12, -0.06, steel, 0.6)
        bw, bh = min(1.4, w - 0.4), 1.5
        zc = (z0 + z1) / 2
        G.chamfer_box(mb, (-bw / 2, -0.55, zc - bh / 2), (bw / 2, -0.06, zc + bh / 2), 0.08, metal)
        mb.box(
            (-bw / 2 + 0.1, -0.6, zc + bh / 2 - 0.3),
            (-bw / 2 + 0.22, -0.55, zc + bh / 2 - 0.2),
            m("lamp_red" if rnd.random() < 0.3 else "lamp_green"),
        )
        G.grille(mb, (-bw / 2 + 0.3, -0.6, zc - 0.5), (bw / 2 - 0.1, -0.55, zc + 0.2), steel, 6)
        for sx in (-1, 1):  # feed conduits into the box
            x = sx * (bw / 2 - 0.2)
            mb.tube((x, -0.3, zc + bh / 2), (x, -0.3, z1), 0.06, steel, 10)
    else:  # recess: a dark service opening with a heavy frame
        mb.box((-hw, -0.02, z0 + 0.3), (hw, 0.0, z1 - 0.3), m("void_black"))
        mb.box((-hw, -0.16, z0), (hw, 0.0, z0 + 0.3), dark)
        mb.box((-hw, -0.16, z1 - 0.3), (hw, 0.0, z1), dark)
        mb.box((-hw, -0.16, z0 + 0.3), (-hw + 0.2, 0.0, z1 - 0.3), dark)
        mb.box((hw - 0.2, -0.16, z0 + 0.3), (hw, 0.0, z1 - 0.3), dark)
        for zz in (z0 + 0.9, z0 + 1.7, z0 + 2.5):  # ladder rungs inside
            if zz < z1 - 0.4:
                mb.tube((-0.3, -0.12, zz), (0.3, -0.12, zz), 0.02, metal, 8)
        if rnd.random() < 0.5:
            mb.box((-0.3, -0.18, z1 - 0.26), (0.3, -0.16, z1 - 0.2), m("lamp_white"))


PANEL_KINDS = ("plate", "plate", "plate", "vent", "machine", "pipes", "recess")


def _torus(mb, r_major, z, r_minor, material, segments=160):
    prof = [
        (r_major + r_minor * math.cos(t), z + r_minor * math.sin(t))
        for t in (2 * math.pi * i / 8 for i in range(8))
    ]
    G.lathe(mb, prof, material, segments, closed=True)


def _flood_light(name: str, matrix) -> None:
    """Real spot light behind a girder flood fixture, aimed down the wall."""
    import bpy

    data = bpy.data.lights.new(name, "SPOT")
    data.energy = 320.0
    data.spot_size = math.radians(115.0)
    data.spot_blend = 0.85
    data.shadow_soft_size = 0.15
    data.color = (0.82, 0.9, 1.0)
    ob = bpy.data.objects.new(name, data)
    ob.matrix_world = matrix
    ob.visible_camera = False
    K.link(ob)


def build_shaft(radius: float = SHAFT_RADIUS, depth: float = SHAFT_DEPTH) -> None:
    """Shaft wall: ribs, girder rings, varied bays, pipe runs, lamps, big rings."""
    rw = _wall_radius(radius)
    seg = 160
    wall = K.MeshBuilder()
    decals = K.MeshBuilder()
    # top lip under the collar kerb and the wall skin behind the bays
    G.ring(wall, radius + 0.36, rw + 0.3, -2.0, -1.2, m("gunmetal"), seg)
    G.ring(wall, rw, rw + 0.3, -depth, -2.0, m("panel_dark"), seg)
    bay = 360.0 / BAYS
    chord = 2 * rw * math.sin(math.radians(bay / 2)) - 0.36
    rows = int((depth - 2.0) // RING_PITCH)
    for b in range(BAYS):
        with G.xf(wall, _wall_frame(b * bay, rw)):  # rib
            wall.box((-0.16, -0.7, -depth), (0.16, -0.6, -2.0), m("gunmetal"))
            wall.box((-0.05, -0.6, -depth), (0.05, 0.0, -2.0), m("gunmetal"))
        frame = _wall_frame((b + 0.5) * bay, rw)
        with G.xf(wall, frame), G.xf(decals, frame):
            for k in range(rows):
                z1 = -2.0 - k * RING_PITCH - 0.5
                z0 = z1 - RING_PITCH + 0.5
                rnd = G.rng("shaft", radius, b, k)
                kind = PANEL_KINDS[rnd.randrange(len(PANEL_KINDS))]
                if b % 8 == 3:
                    kind = "pipes"
                _panel(wall, decals, kind, chord, z0, z1, rnd)
    for k in range(rows + 1):
        z = -2.0 - k * RING_PITCH
        G.ring(wall, radius + 0.1, rw, z - 0.5, z, m("gunmetal"), seg)
        G.ring(wall, radius + 0.04, radius + 0.16, z - 0.62, z - 0.5, m("dark_steel"), seg)
        if k < rows:  # two service pipes ringing the shaft under each girder
            _torus(wall, rw - 0.22, z - 0.95, 0.09, m("gunmetal"))
            _torus(wall, rw - 0.45, z - 1.05, 0.06, m("dark_steel"))
            for b in range(0, BAYS, 2):
                with G.xf(wall, _wall_frame((b + 0.5) * bay, rw)):
                    wall.box((-0.05, -0.55, z - 1.2), (0.05, 0.0, z - 0.85), m("dark_steel"))
    big = int(depth // BIG_RING_PITCH)
    for k in range(1, big + 1):
        z = -k * BIG_RING_PITCH + 0.4
        G.lathe(
            wall,
            [
                (radius - 1.1, z - 0.9),
                (rw, z - 1.4),
                (rw, z),
                (radius - 1.1, z),
                (radius - 1.2, z - 0.1),
                (radius - 1.2, z - 0.8),
            ],
            m("gunmetal"),
            seg,
            closed=True,
        )
    wall.build("SM_Reactor_Shaft_wall", bevel_width=0.015, nav="none")  # far below the deck
    decals.build("SM_Reactor_Shaft_decals", bevel_width=0.0, nav="none")

    lamps = K.MeshBuilder()
    for k in range(rows + 1):
        z = -2.0 - k * RING_PITCH - 0.62
        for b in range(BAYS):
            if (b + k) % 4:
                continue
            red = (b + 2 * k) % 8 == 0
            frame = _wall_frame((b + 0.5) * bay, rw)
            with G.xf(lamps, frame):
                lamps.box(
                    (-0.35, -0.82, z - 0.02),
                    (0.35, -0.74, z + 0.0),
                    m("lamp_red") if red else m("lamp_flood"),
                )
            if not red:
                _flood_light(
                    f"SM_Reactor_Shaft_flood_{k:02d}_{b:02d}",
                    frame @ G.T(0.0, -0.78, z - 0.06) @ G.Rx(17.5),
                )
    for k in range(1, big + 1):
        z = -k * BIG_RING_PITCH + 0.4
        for i in range(16):  # small descending light rings
            with G.xf(lamps, G.Rz(360.0 * (i + 0.5) / 16 + 7.0 * k)):
                lamps.box(
                    (radius - 1.0, -0.05, z),
                    (radius - 0.9, 0.05, z + 0.025),
                    m("lamp_maint_red") if i % 4 == 0 else m("lamp_dim"),
                )
    lamps.build("SM_Reactor_Shaft_lamps", bevel_width=0.0, nav="none")


# --------------------------------------------------------------------------
# Core column
# --------------------------------------------------------------------------


def build_core(depth: float = SHAFT_DEPTH, radius: float = CORE_RADIUS) -> None:
    """Hot core column with containment bands, spars and a capped head.

    Seen from above the head must not read as an emblem (no spokes, no cog
    teeth): the aperture is a parallel-bar grate and the clamps are four heavy
    coil housings on the diagonals.
    """
    hot = K.MeshBuilder()
    G.tube_z(hot, radius - 0.45, -depth, 0.9, m("core_hot"), 64)
    G.annulus(hot, 0.0, 1.95, 1.18, m("core_hot"), 48)
    hot.build("SM_Reactor_Core_plasma", bevel_width=0.0, nav="none")

    cage = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    n_bands = int(depth // 2.4) + 1
    for k in range(n_bands):
        z = 0.2 - k * 2.4
        G.ring(cage, radius - 0.5, radius + 0.05, z - 0.55, z, metal, 64)
        G.ring(cage, radius + 0.05, radius + 0.12, z - 0.45, z - 0.1, steel, 64)
        for i in range(8):
            with G.xf(cage, G.Rz(45.0 * i + (22.5 if k % 2 else 0.0))):
                cage.box((radius + 0.05, -0.3, z - 0.5), (radius + 0.3, 0.3, z - 0.05), steel)
    for i in range(8):
        with G.xf(cage, G.Rz(360.0 * i / 8 + 22.5)):
            cage.box((radius - 0.3, -0.12, -depth), (radius + 0.02, 0.12, 0.6), metal)
    # containment head: stepped collar with a recessed aperture
    G.lathe(
        cage,
        [
            (radius - 0.5, 0.3),
            (radius + 0.3, 0.3),
            (radius + 0.75, 0.75),
            (radius + 0.75, 1.45),
            (radius + 0.45, 1.75),
            (2.3, 1.75),
            (2.3, 1.95),
            (2.0, 1.95),
            (1.9, 1.2),
            (radius - 0.5, 1.1),
        ],
        metal,
        96,
        closed=True,
    )
    G.ring(cage, 2.55, 2.68, 1.75, 1.82, steel, 96)  # two raised seam bands
    G.ring(cage, 3.25, 3.38, 1.75, 1.82, steel, 96)
    for x in [-1.65 + 0.3 * i for i in range(12)]:  # parallel-bar grate
        half = math.sqrt(max(1.9**2 - x * x, 0.0))
        cage.box((x - 0.035, -half, 1.32), (x + 0.035, half, 1.55), steel)
    cage.box((-1.9, -0.08, 1.55), (1.9, 0.08, 1.62), metal)  # one carrier beam
    for i in range(4):  # coil housings on the diagonals with feed rods
        with G.xf(cage, G.Rz(90.0 * i + 45.0)):
            G.chamfer_box(
                cage, (radius + 0.55, -0.55, 0.3), (radius + 1.25, 0.55, 1.65), 0.14, steel
            )
            for zz in (0.6, 0.95, 1.3):
                cage.box((radius + 1.25, -0.5, zz), (radius + 1.29, 0.5, zz + 0.12), metal)
            cage.box((radius + 1.29, -0.05, 1.45), (radius + 1.31, 0.05, 1.55), m("lamp_amber"))
            cage.tube((radius + 0.9, 0.0, 1.65), (radius + 0.7, 0.0, 3.1), 0.07, metal, 10)
            cage.box((radius + 0.61, -0.09, 3.1), (radius + 0.79, 0.09, 3.2), m("lamp_red"))
    cage.build("SM_Reactor_Core_cage", bevel_width=0.012, nav="block")
    K.occluder(
        ((-radius - 1.3, -radius - 1.3, -2.0), (radius + 1.3, radius + 1.3, 2.0)), nav="block"
    )


# --------------------------------------------------------------------------
# Control ring, catwalks, haze
# --------------------------------------------------------------------------


def build_control_ring(radius: float = SHAFT_RADIUS) -> None:
    """Control ring (r 5-6.5) with plating, kerbs, lamps, consoles and struts."""
    rw = _wall_radius(radius)
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    plates = 48
    for i in range(plates):
        # seams sit half a plate off the catwalk axes (0/90/180/270), so no nav
        # sample on a catwalk axis can drop through a seam gap
        a0 = 360.0 * (i + 0.5) / plates + 0.06
        a1 = 360.0 * (i + 1.5) / plates - 0.06
        G.ring(mb, RING_INNER + 0.12, RING_OUTER - 0.12, -0.08, 0.0, m("tread"), 3, a0, a1)
    G.ring(mb, RING_INNER + 0.2, RING_OUTER - 0.2, -0.3, -0.08, metal, 96)
    G.lathe(
        mb,
        [
            (RING_INNER, -1.3),
            (RING_INNER + 0.12, -1.3),
            (RING_INNER + 0.12, 0.1),
            (RING_INNER, 0.1),
        ],
        metal,
        96,
        closed=True,
    )
    G.lathe(
        mb,
        [
            (RING_OUTER - 0.12, -1.3),
            (RING_OUTER, -1.3),
            (RING_OUTER, 0.0),
            (RING_OUTER - 0.12, 0.0),
        ],
        metal,
        96,
        closed=True,
    )
    G.ring(mb, RING_INNER + 0.3, RING_OUTER - 0.3, -1.3, -1.1, metal, 96)
    for i in range(24):  # stiffeners in the box girder
        with G.xf(mb, G.Rz(15.0 * i)):
            mb.box((RING_INNER + 0.12, -0.04, -1.1), (RING_OUTER - 0.12, 0.04, -0.3), steel)
    mb.build("SM_Reactor_Ring_body", bevel_width=0.01, nav="walk")
    # struts down to the shaft wall: own object so their tops never read as floor
    struts = K.MeshBuilder()
    for i in range(4):
        a = 90.0 * i + 45.0
        p0 = Vector(G.polar(5.75, a, -1.2))
        p1 = Vector(G.polar(rw - 0.05, a, -11.0))
        G.ibeam(struts, p0, p1, 0.55, 0.4, metal, up=(0, 0, 1))
        with G.xf(struts, G.Rz(a)):
            struts.box((rw - 0.9, -0.5, -11.8), (rw - 0.02, 0.5, -10.4), steel)
    struts.build("SM_Reactor_Ring_struts", bevel_width=0.01, nav="block")

    lamps = K.MeshBuilder()  # sparse recessed edge lamps: the core stays the bright thing
    for i in range(18):
        a = 360.0 * (i + 0.5) / 18
        with G.xf(lamps, G.Rz(a)):
            lamps.box(
                (RING_INNER + 0.04, -0.035, 0.103), (RING_INNER + 0.08, 0.035, 0.108), m("lamp_dim")
            )
            if not _near_catwalk(a + 10.0, RING_OUTER, 0.6):
                with G.xf(lamps, G.Rz(10.0)):
                    lamps.box(
                        (RING_OUTER - 0.08, -0.035, -0.004),
                        (RING_OUTER - 0.04, 0.035, 0.002),
                        m("lamp_dim"),
                    )
    paint = K.MeshBuilder()  # hairline hazard paint at both plate edges
    G.annulus(paint, RING_INNER + 0.14, RING_INNER + 0.18, 0.001, m("hazard"), 144)
    G.annulus(paint, RING_OUTER - 0.18, RING_OUTER - 0.14, 0.001, m("hazard"), 144)
    paint.build("SM_Reactor_Ring_paint", bevel_width=0.0, nav="none")
    lamps.build("SM_Reactor_Ring_lamps", bevel_width=0.0, nav="none")

    landings = K.MeshBuilder()  # flat tread plates bridging ring and catwalk ends
    for a in CATWALK_ANGLES:
        with G.xf(landings, G.Rz(a)):
            landings.box(
                (RING_OUTER - 0.55, -0.66, -0.02), (RING_OUTER + 0.4, 0.66, 0.008), m("tread")
            )
    landings.build("SM_Reactor_Ring_landings", bevel_width=0.004, nav="walk")

    cons = K.MeshBuilder()
    for i, a in enumerate((45.0, 135.0, 225.0, 315.0)):
        _ring_console(cons, a, i + 1)
    cons.build("SM_Reactor_Ring_consoles", bevel_width=0.008, nav="block")


def _ring_console(mb, angle: float, n: int) -> None:
    """Console hung off the ring's outer edge (over the void), screen facing
    the core, so the full 1.4 m ring stays walkable past it."""
    metal, steel = m("gunmetal"), m("dark_steel")
    r = RING_OUTER + 0.24
    frame = G.Rz(angle) @ G.T(r, 0.0, 0.0) @ G.Rz(-90.0)  # local -Y faces the core
    with G.xf(mb, frame):
        G.chamfer_box(mb, (-0.5, -0.2, 0.0), (0.5, 0.22, 0.8), 0.06, metal)
        mb.box((-0.4, -0.3, -0.55), (0.4, 0.2, -0.04), steel)  # bracket below the lip top
        G.wedge_x(mb, [(-0.32, 0.8), (0.22, 0.8), (0.22, 1.1), (-0.2, 0.95)], -0.52, 0.52, steel)
        mb.quad(
            [(-0.44, -0.27, 0.86), (0.44, -0.27, 0.86), (0.44, 0.15, 1.06), (-0.44, 0.15, 1.06)],
            m("screen_dim"),
        )
        mb.box((-0.46, 0.22, 0.2), (-0.38, 0.24, 0.3), m("lamp_green"))
    centre = Vector(G.polar(r, angle, 0.0))
    inward = -centre.normalized()
    screen_n = inward * math.cos(math.radians(62)) + Vector((0, 0, math.sin(math.radians(62))))
    K.socket(
        "screen",
        f"ring_{n}",
        K.socket_matrix(centre + inward * 0.06 + Vector((0, 0, 0.97)), screen_n),
        size_w=0.88,
        size_h=0.46,
    )
    stand = Vector(G.polar(r - 0.75, angle, 0.0))
    # stand/spawn/waypoint sockets: +Z up, the person faces local -Y (lib.scene)
    K.socket("stand", f"ring_{n}", K.socket_matrix(stand, (0, 0, 1), up=tuple(inward)))
    _oriented_occluder(frame, (-0.52, -0.36, -0.55), (0.52, 0.24, 1.1))


def _oriented_occluder(frame, lo, hi) -> None:
    """UCX box in a rotated frame (an axis-aligned bbox of a 45-degree console
    would cover a metre of the ring and hide people standing there)."""
    import bpy

    corners = [
        Vector((x, y, z)) for z in (lo[2], hi[2]) for y in (lo[1], hi[1]) for x in (lo[0], hi[0])
    ]
    verts = [frame @ c for c in corners]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    proxy = K.mesh_object("_tmp_ucx_console", verts, faces, m("dark_steel"))
    K.occluder(proxy, nav="block")
    bpy.data.objects.remove(proxy, do_unlink=True)


def build_catwalk(
    length: float = SHAFT_RADIUS - RING_OUTER + 0.2, width: float = CATWALK_WIDTH
) -> None:
    """Narrow catwalk without railings along local +Y (origin at the ring end)."""
    mb = K.MeshBuilder()
    hw = width / 2
    metal, steel = m("gunmetal"), m("dark_steel")
    n = max(1, round(length / 1.2))
    step = length / n
    for i in range(n):
        mb.box(
            (-hw + 0.04, i * step + 0.005, -0.07),
            (hw - 0.04, (i + 1) * step - 0.005, 0.0),
            m("tread"),
        )
    for sx in (-1, 1):
        x0 = sx * hw
        mb.box((min(x0, x0 - sx * 0.1), 0.0, -0.45), (max(x0, x0 - sx * 0.1), length, 0.02), metal)
        mb.box(
            (min(x0, x0 - sx * 0.04), 0.0, -0.45), (max(x0, x0 - sx * 0.35), length, -0.4), metal
        )
    for i in range(n + 1):
        y = min(max(i * step, 0.06), length - 0.06)
        mb.box((-hw + 0.1, y - 0.05, -0.4), (hw - 0.1, y + 0.05, -0.07), metal)
    mb.tube((-hw + 0.25, 0.0, -0.3), (-hw + 0.25, length, -0.3), 0.07, steel, 10)
    mb.build("SM_Reactor_Catwalk_body", bevel_width=0.006, nav="walk")
    lamps = K.MeshBuilder()  # one dim lamp per 1.2 m, alternating sides
    for i in range(n):
        y = (i + 0.5) * step
        x = hw if i % 2 else -hw - 0.012
        lamps.box((x, y - 0.04, -0.06), (x + 0.012, y + 0.04, -0.035), m("lamp_dim"))
    lamps.build("SM_Reactor_Catwalk_lamps", bevel_width=0.0, nav="none")
    paint = K.MeshBuilder()  # worn hazard hairlines along both edges
    for sx in (-1, 1):
        x0, x1 = sorted((sx * (hw - 0.07), sx * (hw - 0.1)))
        paint.quad(
            [
                (x0, 0.05, 0.001),
                (x1, 0.05, 0.001),
                (x1, length - 0.05, 0.001),
                (x0, length - 0.05, 0.001),
            ],
            m("hazard"),
        )
    paint.build("SM_Reactor_Catwalk_paint", bevel_width=0.0, nav="none")
    K.socket("waypoint", "end", K.socket_matrix((0.0, length - 0.6, 0.0)))
    K.socket("waypoint", "start", K.socket_matrix((0.0, 0.6, 0.0)))


def build_haze(radius: float = SHAFT_RADIUS, depth: float = SHAFT_DEPTH) -> None:
    """Haze volume filling the shaft (density rises with depth)."""
    mb = K.MeshBuilder()
    G.tube_z(mb, radius + 0.8, -depth, -0.6, m("haze"), 48)
    obj = mb.build("SM_Reactor_Haze", bevel_width=0.0, nav="none")
    obj.visible_shadow = False


# --------------------------------------------------------------------------
# Registration and assembly
# --------------------------------------------------------------------------

K.register_variant(
    "SM_Reactor_Collar", build_collar, dims=(COLLAR_SIZE, COLLAR_SIZE, 1.3), nav="walk"
)
K.register_variant("SM_Reactor_Shaft", build_shaft, dims=(28.4, 28.4, SHAFT_DEPTH), nav="block")
K.register_variant("SM_Reactor_Core", build_core, dims=(8.4, 8.4, SHAFT_DEPTH + 3.3), nav="block")
K.register_variant("SM_Reactor_ControlRing", build_control_ring, dims=(13.0, 13.0, 1.4), nav="walk")
K.register_variant("SM_Reactor_Catwalk", build_catwalk, dims=(1.2, 6.7, 0.47), nav="walk")
K.register_variant("SM_Reactor_Haze", build_haze, dims=(29.6, 29.6, SHAFT_DEPTH), nav="none")


def ensure_radius(radius: float) -> dict[str, str]:
    """Register (once) the radius-dependent pieces for a non-default shaft."""
    if abs(radius - SHAFT_RADIUS) < 1e-6:
        return {k: f"SM_Reactor_{k}" for k in ("Collar", "Shaft", "ControlRing", "Catwalk", "Haze")}
    tag = f"R{radius:g}".replace(".", "p")
    names = {}
    for key, fn, kw in (
        (
            "Collar",
            build_collar,
            {"radius": radius, "size": math.ceil((2 * radius + 4.8) / 1.2) * 1.2},
        ),
        ("Shaft", build_shaft, {"radius": radius}),
        ("ControlRing", build_control_ring, {"radius": radius}),
        ("Catwalk", build_catwalk, {"length": radius - RING_OUTER + 0.2}),
        ("Haze", build_haze, {"radius": radius}),
    ):
        name = f"SM_Reactor_{key}_{tag}"
        if name not in K.registry():
            K.register_variant(
                name,
                fn,
                nav="walk" if key in ("Collar", "ControlRing", "Catwalk") else "block",
                **kw,
            )
        names[key] = name
    return names


def place_reactor(
    location=(0.0, 0.0, 0.0),
    room: str = "reactor",
    radius: float = SHAFT_RADIUS,
    catwalks=CATWALK_ANGLES,
    prefix: str = "reactor",
):
    """Place the full shaft assembly centred at ``location`` (Blender axes)."""
    names = ensure_radius(radius)
    x, y, z = location
    out = [
        K.place(names["Collar"], location, room=room, id=f"{prefix}_collar"),
        K.place(names["Shaft"], location, room=room, id=f"{prefix}_shaft"),
        K.place("SM_Reactor_Core", location, room=room, id=f"{prefix}_core"),
        K.place(names["ControlRing"], location, room=room, id=f"{prefix}_ring"),
        K.place(names["Haze"], location, room=room, id=f"{prefix}_haze"),
    ]
    for i, a in enumerate(catwalks):
        px, py, _ = G.polar(RING_OUTER - 0.1, a)
        out.append(
            K.place(
                names["Catwalk"],
                (x + px, y + py, z),
                a - 90.0,
                room=room,
                id=f"{prefix}_catwalk_{i + 1}",
            )
        )
    return out


LOOKDEV = {
    # shown in the reactor vignette (lookdev.py --vignette reactor)
    "SM_Reactor_Haze": {"skip": True},
    "SM_Reactor_Shaft": {"skip": True},
    "SM_Reactor_Collar": {"skip": True},
    "SM_Reactor_Core": {
        "frame": (-5.0, 5.0, -6.5, 4.0),
        "floor": False,
        "focus": (0.0, 0.0, 1.8),
        "crop_size": (3.0, 1.9),
    },
    "SM_Reactor_ControlRing": {"floor": False, "focus": (4.3, 4.3, 0.6), "crop_size": (3.0, 1.9)},
    "SM_Reactor_Catwalk": {"floor": False, "focus": (0.0, 3.0, 0.0), "crop_size": (2.6, 1.6)},
}
