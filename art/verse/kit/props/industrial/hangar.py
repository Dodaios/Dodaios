"""Hangar props (deck 4): cargo, fuel lines, tow tug, gantry crane, blast
doors, the launch well, deck markings and racks.

Piece-local frame: centred on X, deck at Z = 0, -Y toward the camera.
The blast door is wall-like (face toward -Y, body toward +Y, like the
architecture kit); the racks stand with their back on a wall plane at Y = 0
and their body toward -Y (into the room).
"""

from __future__ import annotations

from lib import kit as K
from mathutils import Vector

from . import _geo as G
from ._mats import m

# --------------------------------------------------------------------------
# Cargo containers
# --------------------------------------------------------------------------

CONTAINERS = {
    # name: (length X, depth Y, height Z, paint role, code)
    "SM_Hangar_Container_L_Charcoal": (6.0, 2.4, 2.6, "container_charcoal", "FLT 4410 7"),
    "SM_Hangar_Container_L_Olive": (6.0, 2.4, 2.6, "container_olive", "FLT 2086 3"),
    "SM_Hangar_Container_L_Grey": (6.0, 2.4, 2.6, "container_grey", "FLT 0571 2"),
    "SM_Hangar_Container_M_Gunmetal": (3.6, 2.4, 2.4, "container_gunmetal", "FLT 1193 5"),
    "SM_Hangar_Container_M_Charcoal": (3.6, 2.4, 2.4, "container_charcoal", "FLT 3307 1"),
    "SM_Hangar_Container_S_Grey": (2.4, 1.6, 1.6, "container_grey", "SPR 48"),
    "SM_Hangar_Container_S_Charcoal": (2.4, 1.6, 1.6, "container_charcoal", "SPR 12"),
}


def build_container(length, depth, height, paint, code):
    """Corrugated cargo container with corner posts, castings and door end."""
    mb = K.MeshBuilder()
    p, steel = m(paint), m("dark_steel")
    hl, hd = length / 2, depth / 2
    post = 0.16 if height > 2.0 else 0.11
    rail = 0.14 if height > 2.0 else 0.1
    # inner box (recessed walls)
    mb.box((-hl + 0.04, -hd + 0.05, rail), (hl - 0.04, hd - 0.05, height - rail), p)
    # corrugation on the long sides and the closed end
    pitch = 0.28 if height > 2.0 else 0.2
    n = int((length - 2 * post) / pitch)
    for i in range(n):
        x = -hl + post + (i + 0.5) * (length - 2 * post) / n
        for sy in (-1, 1):
            y0 = sy * (hd - 0.05)
            mb.box(
                (x - pitch * 0.26, min(y0, y0 + sy * 0.045), rail),
                (x + pitch * 0.26, max(y0, y0 + sy * 0.045), height - rail),
                p,
            )
    k = int((depth - 2 * post) / pitch)
    for i in range(k):
        y = -hd + post + (i + 0.5) * (depth - 2 * post) / k
        mb.box((-hl, y - pitch * 0.26, rail), (-hl + 0.06, y + pitch * 0.26, height - rail), p)
    # roof: shallow ribs
    for i in range(int(length / 0.6)):
        x = -hl + 0.3 + i * 0.6
        mb.box((x - 0.12, -hd + post, height - 0.03), (x + 0.12, hd - post, height - 0.005), p)
    # frame: posts, rails, castings
    for sx in (-1, 1):
        for sy in (-1, 1):
            x0, y0 = sx * hl, sy * hd
            mb.box(
                (min(x0, x0 - sx * post), min(y0, y0 - sy * post), 0.0),
                (max(x0, x0 - sx * post), max(y0, y0 - sy * post), height),
                p,
            )
            for z0 in (0.0, height - 0.12):
                mb.box(
                    (min(x0, x0 - sx * 0.18), min(y0, y0 - sy * 0.18), z0),
                    (max(x0, x0 - sx * 0.18), max(y0, y0 - sy * 0.18), z0 + 0.12),
                    steel,
                )
    for z0, z1 in ((0.0, rail), (height - rail, height)):
        for sy in (-1, 1):
            y0 = sy * hd
            mb.box((-hl, min(y0, y0 - sy * 0.1), z0), (hl, max(y0, y0 - sy * 0.1), z1), p)
        for sx in (-1, 1):
            x0 = sx * hl
            mb.box((min(x0, x0 - sx * 0.1), -hd, z0), (max(x0, x0 - sx * 0.1), hd, z1), p)
    # door end (+X): two leaves with locking bars
    x_door = hl - 0.02
    mb.box((x_door - 0.04, -hd + post, rail), (x_door, hd - post, height - rail), p)
    for y in (-hd * 0.7, -hd * 0.25, hd * 0.25, hd * 0.7):
        mb.tube(
            (x_door + 0.04, y, rail + 0.05),
            (x_door + 0.04, y, height - rail - 0.05),
            0.025,
            m("gunmetal"),
            8,
        )
        mb.box(
            (x_door, y - 0.03, height * 0.45), (x_door + 0.1, y + 0.03, height * 0.5), m("gunmetal")
        )
    mb.box((x_door - 0.01, -0.006, rail), (x_door + 0.015, 0.006, height - rail), steel)
    mb.build("SM_container_body", bevel_width=0.008)
    _container_stencils(length, depth, height, code)
    K.occluder(((-hl, -hd, 0.0), (hl, hd, height)), nav="block")


def _container_stencils(length, depth, height, code):
    mb = K.MeshBuilder()
    hl, hd = length / 2, depth / 2
    white = m("stencil_white")
    big = 0.42 if height > 2.0 else 0.26
    face = G.on_face((-hl * 0.35, -hd + 0.003, height * 0.62), "-Y")
    G.text(mb, code, big, white, face)
    small = G.on_face((-hl * 0.35, -hd + 0.003, height * 0.62 - big * 1.1), "-Y")
    G.text(
        mb,
        "MAX GROSS 24000 KG   TARE 2210 KG" if height > 2.0 else "NET 900 KG",
        big * 0.3,
        white,
        small,
    )
    stripe = G.on_face((hl * 0.55, -hd + 0.003, height * 0.5), "-Y")
    with G.xf(mb, stripe):
        mb.quad(
            [
                (-0.06, -height * 0.35, 0),
                (0.06, -height * 0.35, 0),
                (0.06, height * 0.35, 0),
                (-0.06, height * 0.35, 0),
            ],
            m("stencil_red"),
        )
    G.text(
        mb,
        code.split()[-2] if " " in code else code,
        big * 1.6,
        white,
        G.T(0.0, 0.0, height + 0.002) @ G.Rz(0.0),
    )
    mb.build("SM_container_stencils", bevel_width=0.0, nav="none")


for _name, (_l, _d, _h, _paint, _code) in CONTAINERS.items():
    K.register_variant(
        _name,
        build_container,
        dims=(_l, _d, _h),
        length=_l,
        depth=_d,
        height=_h,
        paint=_paint,
        code=_code,
    )


# --------------------------------------------------------------------------
# Crates and pallets
# --------------------------------------------------------------------------


def _crate(mb, cx, cy, cz, w, d, h, rnd, paint="container_charcoal"):
    """Armoured ribbed crate (handles, latches, ribs) at centre-bottom (cx, cy, cz)."""
    p, metal = m(paint), m("gunmetal")
    G.chamfer_box(mb, (cx - w / 2, cy - d / 2, cz), (cx + w / 2, cy + d / 2, cz + h), 0.05, p)
    G.chamfer_box(
        mb,
        (cx - w / 2 - 0.015, cy - d / 2 - 0.015, cz + h - 0.09),
        (cx + w / 2 + 0.015, cy + d / 2 + 0.015, cz + h - 0.03),
        0.05,
        p,
    )
    G.chamfer_box(
        mb,
        (cx - w / 2 - 0.015, cy - d / 2 - 0.015, cz + 0.02),
        (cx + w / 2 + 0.015, cy + d / 2 + 0.015, cz + 0.08),
        0.05,
        p,
    )
    for sx in (-1, 1):  # handles on the short ends
        x = cx + sx * (w / 2 + 0.02)
        mb.box((x - 0.02, cy - 0.12, cz + h * 0.62), (x + 0.02, cy + 0.12, cz + h * 0.66), metal)
    for sx in (-0.3, 0.3):  # latches on the -Y face
        x = cx + sx * w
        mb.box(
            (x - 0.04, cy - d / 2 - 0.03, cz + h - 0.2), (x + 0.04, cy - d / 2, cz + h - 0.1), metal
        )
    if rnd.random() < 0.5:
        mb.box(
            (cx - w * 0.3, cy - d * 0.3, cz + h), (cx + w * 0.3, cy + d * 0.3, cz + h + 0.012), p
        )


def build_crate(w=1.2, d=0.8, h=0.8, label="A-17", paint="container_charcoal"):
    """Single armoured crate with a stencil."""
    mb = K.MeshBuilder()
    _crate(mb, 0.0, 0.0, 0.0, w, d, h, G.rng("crate", w, d, h), paint)
    mb.build("SM_crate_body", bevel_width=0.006)
    st = K.MeshBuilder()
    G.text(
        st,
        label,
        h * 0.18,
        m("stencil_white"),
        G.on_face((-w * 0.2, -d / 2 - 0.016, h * 0.45), "-Y"),
    )
    st.build("SM_crate_stencil", bevel_width=0.0, nav="none")
    K.occluder(((-w / 2, -d / 2, 0.0), (w / 2, d / 2, h)), nav="block")


def build_crate_stack(seed="stack_a"):
    """Ordered stack of crates on a 2.4 x 1.2 footprint (dressing)."""
    rnd = G.rng("crate_stack", seed)
    mb = K.MeshBuilder()
    layout = [
        (-0.6, 0.0, 0.0, 1.2, 0.8, 0.8),
        (0.6, 0.0, 0.0, 1.2, 0.8, 0.8),
        (-0.6, 0.0, 0.8, 1.2, 0.8, 0.8),
        (0.55, 0.05, 0.8, 0.8, 0.6, 0.5),
    ]
    if rnd.random() < 0.5:
        layout.append((-0.6, 0.05, 1.6, 0.8, 0.6, 0.5))
    for x, y, z, w, d, h in layout:
        _crate(mb, x, y, z, w, d, h, rnd)
    mb.build("SM_cratestack_body", bevel_width=0.006)
    K.occluder(((-1.2, -0.42, 0.0), (1.2, 0.42, 2.1)), nav="block")


def build_pallet(loaded=False):
    """Steel pallet, optionally loaded with strapped cases."""
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    for x in (-0.55, 0.0, 0.55):
        mb.box((x - 0.05, -0.6, 0.0), (x + 0.05, 0.6, 0.1), steel)
    for i in range(7):
        y = -0.6 + 0.06 + i * 0.18
        mb.box((-0.6, y - 0.05, 0.1), (0.6, y + 0.05, 0.14), metal)
    h = 0.14
    if loaded:
        rnd = G.rng("pallet")
        for x, y, w, d, hh in (
            (-0.3, -0.3, 0.58, 0.58, 0.5),
            (0.3, -0.3, 0.58, 0.58, 0.5),
            (-0.3, 0.3, 0.58, 0.58, 0.5),
            (0.3, 0.3, 0.58, 0.58, 0.5),
            (0.0, 0.0, 0.9, 0.9, 0.42),
        ):
            z = h if hh == 0.5 else h + 0.5
            _crate(mb, x, y, z, w, d, hh, rnd, "container_gunmetal")
        for x in (-0.25, 0.25):  # straps
            mb.box((x - 0.025, -0.62, h), (x + 0.025, 0.62, h + 0.93), m("rubber"))
        h += 0.92
    mb.build("SM_pallet_body", bevel_width=0.005)
    K.occluder(((-0.6, -0.6, 0.0), (0.6, 0.6, h)), nav="block")


K.register_variant("SM_Hangar_Crate_A", build_crate, dims=(1.2, 0.8, 0.8))
K.register_variant(
    "SM_Hangar_Crate_B",
    build_crate,
    dims=(0.8, 0.6, 0.5),
    w=0.8,
    d=0.6,
    h=0.5,
    label="B-04",
    paint="container_gunmetal",
)
K.register_variant("SM_Hangar_CrateStack", build_crate_stack, dims=(2.4, 0.84, 2.1))
K.register_variant("SM_Hangar_Pallet", build_pallet, dims=(1.2, 1.2, 0.14))
K.register_variant("SM_Hangar_Pallet_Loaded", build_pallet, dims=(1.2, 1.2, 1.06), loaded=True)


# --------------------------------------------------------------------------
# Fuel and power lines
# --------------------------------------------------------------------------


def _hose(mb, pts, r=0.07, couplings=()):
    smooth = G.catmull_rom(pts, 10)
    G.sweep(mb, [Vector((p.x, p.y, r)) for p in smooth], r, m("rubber"), 12)
    for c in couplings:
        a = Vector((*c[:2], r))
        b = Vector((*c[2:4], r))
        d = (b - a).normalized()
        mb.tube(a - d * 0.18, a + d * 0.18, r * 1.45, m("gunmetal"), 14)
        mb.tube(a - d * 0.05, a + d * 0.05, r * 1.75, m("dark_steel"), 14)


def _y_at(points, x):
    """Linear interpolation of a polyline's y at ``x`` (points sorted by x)."""
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:], strict=True):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[0][1] if x < points[0][0] else points[-1][1]


def build_fuel_line(shape="straight"):
    """Pair of floor hoses (fuel + power) with couplings and cable guards."""
    mb = K.MeshBuilder()
    if shape == "straight":
        a = [(-3.0, -0.12), (-1.0, -0.1), (1.0, -0.14), (3.0, -0.12)]
        b = [(-3.0, 0.14), (-1.0, 0.18), (1.0, 0.12), (3.0, 0.14)]
        guards = (-1.5, 1.5)
    else:  # gentle S across 6.0 x 2.4
        a = [(-3.0, -1.0), (-1.5, -0.95), (0.0, 0.0), (1.5, 0.95), (3.0, 1.0)]
        b = [(-3.0, -0.74), (-1.5, -0.68), (0.0, 0.26), (1.5, 1.22), (3.0, 1.26)]
        guards = (-2.2,)
    _hose(mb, [Vector((*p, 0)) for p in a], 0.075, couplings=[(*a[1], *a[2])])
    _hose(mb, [Vector((*p, 0)) for p in b], 0.05)
    for gx in guards:  # cable protector ramp over both hoses
        y_mid = 0.5 * (_y_at(a, gx) + _y_at(b, gx))
        with G.xf(mb, G.T(0.0, y_mid, 0.0)):
            G.wedge_x(
                mb,
                [(-0.55, 0.0), (-0.3, 0.17), (0.3, 0.17), (0.55, 0.0)],
                gx - 0.3,
                gx + 0.3,
                m("hazard"),
            )
    mb.build("SM_fuelline_body", bevel_width=0.004, nav="none")


def build_fuel_port():
    """Flush floor hatch with a fuel coupling, valve wheel and hose stub."""
    mb = K.MeshBuilder()
    steel, metal = m("dark_steel"), m("gunmetal")
    mb.box((-0.6, -0.6, -0.02), (0.6, 0.6, 0.004), steel)
    mb.box((-0.5, -0.5, 0.004), (0.5, 0.5, 0.01), metal)
    with G.xf(mb, G.T(0.15, 0.1, 0.0)):
        G.lathe(mb, [(0.0, 0.32), (0.16, 0.32), (0.18, 0.2), (0.13, 0.0)], metal, 20)
        G.lathe(mb, [(0.2, 0.36), (0.24, 0.36), (0.24, 0.4), (0.2, 0.4)], steel, 24, closed=True)
    mb.tube((-0.25, -0.25, 0.01), (-0.25, -0.25, 0.42), 0.04, metal, 10)
    with G.xf(mb, G.T(-0.25, -0.25, 0.44)):
        G.ring(mb, 0.15, 0.18, -0.02, 0.02, m("stencil_red"), 24)
        for i in range(3):
            with G.xf(mb, G.Rz(120.0 * i)):
                mb.box((0.0, -0.012, -0.012), (0.16, 0.012, 0.012), metal)
    _hose(
        mb,
        [
            Vector((0.15, 0.1, 0)),
            Vector((0.5, 0.6, 0)),
            Vector((1.2, 1.0, 0)),
            Vector((2.4, 1.1, 0)),
        ],
        0.075,
    )
    mb.build("SM_fuelport_body", bevel_width=0.004)
    paint = K.MeshBuilder()
    G.text(paint, "FUEL 3", 0.12, m("stencil_amber"), G.T(0.0, -0.45, 0.012))
    paint.build("SM_fuelport_paint", bevel_width=0.0, nav="none")
    K.occluder(((-0.3, -0.35, 0.0), (0.4, 0.35, 0.45)), nav="block")


K.register_variant("SM_Hangar_FuelLine", build_fuel_line, dims=(6.0, 0.6, 0.15), nav="none")
K.register_variant(
    "SM_Hangar_FuelLine_S", build_fuel_line, dims=(6.0, 2.6, 0.15), nav="none", shape="s"
)
K.register_variant("SM_Hangar_FuelPort", build_fuel_port, dims=(1.2, 1.2, 0.45))


# --------------------------------------------------------------------------
# Tow tug (drone-driven)
# --------------------------------------------------------------------------


def build_tow_tug():
    """Low autonomous tow tug with sensor head, hitch and amber beacon."""
    mb = K.MeshBuilder()
    body, steel, metal = m("container_grey"), m("dark_steel"), m("gunmetal")
    G.chamfer_box(mb, (-1.5, -0.8, 0.28), (1.5, 0.8, 0.85), 0.25, body)
    G.chamfer_box(mb, (-1.35, -0.7, 0.85), (0.6, 0.7, 1.05), 0.2, body)
    G.chamfer_box(mb, (0.6, -0.55, 0.85), (1.35, 0.55, 1.25), 0.18, steel)
    G.lathe(mb, [(0.0, 1.55), (0.22, 1.5), (0.3, 1.38), (0.3, 1.25)], metal, 24)
    mb.box((0.85, -0.3, 1.32), (1.37, 0.3, 1.4), m("glass_dark"))
    for sx in (-1.05, 1.05):
        for sy in (-1, 1):
            y0 = sy * 0.8
            mb.tube((sx, y0, 0.32), (sx, y0 + sy * 0.18, 0.32), 0.3, m("rubber"), 20)
            mb.tube((sx, y0 + sy * 0.17, 0.32), (sx, y0 + sy * 0.19, 0.32), 0.17, metal, 16)
    mb.box((-1.5, -0.12, 0.38), (-2.1, 0.12, 0.5), steel)
    mb.tube((-2.1, 0.0, 0.3), (-2.1, 0.0, 0.62), 0.08, metal, 12)
    for k in range(5):  # ballast plates on the deck
        x = -1.2 + k * 0.32
        mb.box((x, -0.62, 1.05), (x + 0.26, 0.62, 1.1), steel)
    mb.build("SM_towtug_body", bevel_width=0.008)
    lamps = K.MeshBuilder()
    G.tube_z(lamps, 0.06, 1.55, 1.68, m("lamp_amber"), 12)
    for sy in (-0.45, 0.45):
        lamps.box((1.5, sy - 0.08, 0.6), (1.51, sy + 0.08, 0.68), m("lamp_white"))
        lamps.box((-1.51, sy - 0.06, 0.6), (-1.5, sy + 0.06, 0.66), m("lamp_red"))
    lamps.build("SM_towtug_lamps", bevel_width=0.0, nav="none")
    st = K.MeshBuilder()
    G.text(st, "TUG 03", 0.16, m("stencil_dark"), G.on_face((-0.3, -0.801, 0.6), "-Y"))
    st.build("SM_towtug_stencil", bevel_width=0.0, nav="none")
    K.occluder(((-2.2, -0.98, 0.0), (1.5, 0.98, 1.7)), nav="block")
    K.socket("spawn", "drone", K.socket_matrix((0.0, -1.6, 0.0), (0, 0, 1), up=(-1, 0, 0)))


K.register_variant("SM_Hangar_TowTug", build_tow_tug, dims=(3.7, 1.96, 1.68))


# --------------------------------------------------------------------------
# Gantry crane
# --------------------------------------------------------------------------


def build_gantry_column(height=12.0):
    """Lattice gantry column with base plate and crane-rail bracket."""
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    s = 0.55
    mb.box((-0.8, -0.8, 0.0), (0.8, 0.8, 0.12), steel)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * s, sy * s
            mb.box((x - 0.09, y - 0.09, 0.12), (x + 0.09, y + 0.09, height), metal)
            mb.box(
                (sx * 0.7 - 0.05, sy * 0.7 - 0.05, 0.12),
                (sx * 0.7 + 0.05, sy * 0.7 + 0.05, 0.2),
                steel,
            )
    step = 1.2
    n = int((height - 0.6) / step)
    for i in range(n):
        z0 = 0.4 + i * step
        z1 = z0 + step
        for a in range(4):
            with G.xf(mb, G.Rz(90.0 * a)):
                G.beam(
                    mb, (-s, -s, z0), (s, -s, z1) if i % 2 == 0 else (s, -s, z0), 0.07, 0.07, metal
                )
                mb.box((-s, -s - 0.04, z1 - 0.04), (s, -s + 0.04, z1 + 0.04), metal)
    mb.box((-0.75, -0.75, height), (0.75, 0.75, height + 0.3), steel)
    mb.box((-0.35, -1.6, height + 0.3), (0.35, 1.6, height + 0.9), metal)
    mb.box((-0.08, -1.6, height + 0.9), (0.08, 1.6, height + 1.05), steel)
    mb.build("SM_gantrycol_body", bevel_width=0.006)
    lamps = K.MeshBuilder()
    lamps.box((-0.1, -0.86, height + 0.1), (0.1, -0.75, height + 0.22), m("lamp_red"))
    lamps.build("SM_gantrycol_lamps", bevel_width=0.0, nav="none")
    K.occluder(((-0.65, -0.65, 0.0), (0.65, 0.65, height + 1.05)), nav="block")


def build_gantry_bridge(span=24.0, height=12.0, hook_drop=5.0):
    """Crane bridge girder spanning X with a hoist trolley and hook block."""
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    hs = span / 2
    for sy in (-0.5, 0.5):
        G.ibeam(mb, (-hs, sy, height + 0.5), (hs, sy, height + 0.5), 1.0, 0.45, metal, up=(0, 0, 1))
    for i in range(int(span / 2.4) + 1):
        x = -hs + i * 2.4
        mb.box((x - 0.06, -0.5, height + 0.05), (x + 0.06, 0.5, height + 0.95), steel)
    for sx in (-1, 1):
        mb.box((sx * hs - 0.6, -1.6, height + 0.9), (sx * hs + 0.6, 1.6, height + 1.4), steel)
    G.chamfer_box(
        mb, (-1.0, -0.9, height + 1.0), (1.0, 0.9, height + 1.7), 0.15, m("container_grey")
    )
    for sx in (-0.15, 0.15):
        mb.tube((sx, 0.0, height), (sx, 0.0, height - hook_drop), 0.018, metal, 6)
    G.chamfer_box(
        mb,
        (-0.35, -0.25, height - hook_drop - 0.7),
        (0.35, 0.25, height - hook_drop),
        0.1,
        m("hazard"),
    )
    mb.tube(
        (0.0, 0.0, height - hook_drop - 0.7), (0.0, 0.0, height - hook_drop - 1.0), 0.06, metal, 10
    )
    mb.build("SM_gantrybridge_body", bevel_width=0.008, nav="none")


K.register_variant("SM_Hangar_GantryColumn", build_gantry_column, dims=(1.6, 3.2, 13.05))
K.register_variant(
    "SM_Hangar_GantryBridge", build_gantry_bridge, dims=(25.2, 3.2, 13.7), nav="none"
)


# --------------------------------------------------------------------------
# Blast doors (hangar hero wall)
# --------------------------------------------------------------------------


def build_blast_door(width=36.0, height=16.0, label="04"):
    """Two massive blast-door leaves in a pressure frame (face at Y=0, -Y)."""
    mb = K.MeshBuilder()
    panel, dark, metal, steel = m("panel_light"), m("panel_dark"), m("gunmetal"), m("dark_steel")
    hw = width / 2
    fw = 2.4  # frame width
    # pressure frame with chamfered inner corners
    G.prism_z_any(
        mb, [(-hw - fw, -0.9), (-hw, -0.9), (-hw, 0.6), (-hw - fw, 0.6)], 0.0, height + fw, panel
    )
    G.prism_z_any(
        mb, [(hw, -0.9), (hw + fw, -0.9), (hw + fw, 0.6), (hw, 0.6)], 0.0, height + fw, panel
    )
    mb.box((-hw, -0.9, height), (hw, 0.6, height + fw), panel)
    for sx in (-1, 1):  # chamfered upper corners of the opening
        poly = [(sx * hw, height), (sx * (hw - 1.8), height), (sx * hw, height - 1.8)]
        verts = [Vector((x, y, z)) for x, z in poly for y in (-0.9, 0.6)]
        mb._add(verts, [(0, 2, 4), (1, 5, 3), (0, 1, 3, 2), (2, 3, 5, 4), (4, 5, 1, 0)], panel)
    # frame relief: recessed lights and ribs
    for sx in (-1, 1):
        x0 = sx * (hw + fw / 2)
        for k in range(int(height / 2.4)):
            z = 1.2 + k * 2.4
            mb.box((x0 - 0.7, -1.0, z - 0.9), (x0 + 0.7, -0.9, z + 0.9), dark)
    # leaves (recessed 0.6 behind the frame face)
    for sx in (-1, 1):
        xa, xb = sorted((0.0, sx * hw))
        mb.box((xa, -0.3, 0.0), (xb, 0.4, height), steel)
        rows = int(height / 1.2)
        for r in range(rows):  # horizontal ribs
            z = 0.6 + r * 1.2
            mb.box((xa + 0.2, -0.55, z - 0.16), (xb - 0.2, -0.3, z + 0.16), metal)
        for c in range(int(hw / 4.8) + 1):  # vertical stiffeners
            x = sx * (0.9 + c * 4.8)
            if abs(x) > hw - 0.4:
                continue
            mb.box((x - 0.3, -0.75, 0.0), (x + 0.3, -0.3, height), dark)
        x_edge = sx * 0.02
        mb.box(
            (min(x_edge, sx * 0.9), -0.8, 0.0), (max(x_edge, sx * 0.9), -0.3, height), m("hazard")
        )
    mb.box((-0.02, -0.82, 0.0), (0.02, -0.3, height), m("rubber"))
    mb.build("SM_blastdoor_body", bevel_width=0.02)
    lamps = K.MeshBuilder()
    # continuous light band in the frame's inner edge (sides and top): the
    # glowing pressure frame reads at plate scale, small tiles do not
    for sx in (-1, 1):
        xa, xb = sorted((sx * (hw + 0.25), sx * (hw + 0.55)))
        lamps.box((xa, -0.92, 0.3), (xb, -0.9, height - 0.3), m("lamp_band"))
    lamps.box((-hw + 1.6, -0.92, height + 0.25), (hw - 1.6, -0.9, height + 0.55), m("lamp_band"))
    for sx in (-1, 1):
        G.tube_z(
            lamps, 0.22, height + fw, height + fw + 0.35, m("lamp_red"), 16, x=sx * (hw + 1), y=-0.3
        )
    lamps.build("SM_blastdoor_lamps", bevel_width=0.0, nav="none")
    st = K.MeshBuilder()  # one bay number, small worn stencil (no large words)
    G.text(st, label, 1.4, m("stencil_white"), G.on_face((-hw / 2, -0.56, height * 0.62), "-Y"))
    st.build("SM_blastdoor_stencil", bevel_width=0.0, nav="none")
    K.occluder(((-hw - fw, -1.0, 0.0), (hw + fw, 0.6, height + fw)), nav="block")


K.register_variant("SM_Hangar_BlastDoor", build_blast_door, dims=(40.8, 1.6, 18.4))
K.register_variant("SM_Hangar_BlastDoor_56", build_blast_door, dims=(56.0, 1.6, 18.4), width=51.2)


# --------------------------------------------------------------------------
# Launch well
# --------------------------------------------------------------------------


def _well_outline(length, width, chamfer, grow=0.0):
    hl, hw, c = length / 2 + grow, width / 2 + grow, chamfer + grow * 0.414
    return [
        (-hl + c, -hw),
        (hl - c, -hw),
        (hl, -hw + c),
        (hl, hw - c),
        (hl - c, hw),
        (-hl + c, hw),
        (-hl, hw - c),
        (-hl, -hw + c),
    ]


def build_launch_well(length=30.0, width=12.0, depth=10.0):
    """Recessed launch opening: rim, lit walls, blue containment field, void."""
    mb = K.MeshBuilder()
    dark, metal, steel = m("panel_dark"), m("gunmetal"), m("dark_steel")
    inner = _well_outline(length, width, 2.4)
    outer = _well_outline(length, width, 2.4, 1.2)
    n = len(inner)
    # rim band (top at 0) between outer and inner outline
    rim = K.MeshBuilder()  # closed slab so its top faces up for the nav cook
    G.slab_between(rim, inner, outer, -0.3, 0.0, steel)
    rim.build("SM_launchwell_rim", bevel_width=0.0, nav="walk")  # crew may walk the rim
    # walls: each edge of the inner outline drops to -depth
    for i in range(n):
        a, b = Vector((*inner[i], 0.0)), Vector((*inner[(i + 1) % n], 0.0))
        mb._add(
            [a, b, b + Vector((0, 0, -depth)), a + Vector((0, 0, -depth))], [(0, 1, 2, 3)], dark
        )
        edge = b - a
        L = edge.length
        t = edge.normalized()
        nrm = Vector((-t.y, t.x, 0.0))  # points into the well (outline is CCW)
        ribs = max(1, int(L / 2.4))
        for k in range(ribs + 1):
            p = a + t * (k * L / ribs)
            G.beam(
                mb,
                p + nrm * 0.15 + Vector((0, 0, -depth)),
                p + nrm * 0.15 + Vector((0, 0, -0.3)),
                0.3,
                0.3,
                metal,
                up=tuple(nrm),
            )
        for z in (-2.4, -4.8, -7.2):
            G.beam(
                mb,
                a + nrm * 0.1 + Vector((0, 0, z)),
                b + nrm * 0.1 + Vector((0, 0, z)),
                0.2,
                0.25,
                metal,
                up=(0, 0, 1),
            )
    # field projector rail just below the rim, where the field plane sits
    for i in range(n):
        a, b = Vector((*inner[i], 0.0)), Vector((*inner[(i + 1) % n], 0.0))
        t = (b - a).normalized()
        nrm = Vector((-t.y, t.x, 0.0))
        G.beam(
            mb,
            a + nrm * 0.2 + Vector((0, 0, -0.5)),
            b + nrm * 0.2 + Vector((0, 0, -0.5)),
            0.4,
            0.22,
            metal,
            up=(0, 0, 1),
        )
    mb._add([Vector((x, y, -depth)) for x, y in inner], [tuple(range(n))], m("void_black"))
    mb.build("SM_launchwell_body", bevel_width=0.012)

    field = K.MeshBuilder()
    field._add([Vector((x, y, -0.45)) for x, y in inner], [tuple(range(n))], m("field_blue"))
    field.build("SM_launchwell_field", bevel_width=0.0, nav="none")

    lamps = K.MeshBuilder()
    for i in range(n):
        a, b = Vector((*inner[i], 0.0)), Vector((*inner[(i + 1) % n], 0.0))
        edge = b - a
        L = edge.length
        t = edge.normalized()
        nrm = Vector((-t.y, t.x, 0.0))  # into the well
        k = max(1, int(L / 2.4))
        for j in range(k):  # small descending light rings (one lamp per bay and level)
            p = a + t * ((j + 0.5) * L / k) + nrm * 0.02
            for zc in (-2.3, -4.7, -7.1):
                q0 = p + t * -0.15 + Vector((0, 0, zc - 0.04))
                q1 = p + t * 0.15 + Vector((0, 0, zc - 0.04))
                q2 = p + t * 0.15 + Vector((0, 0, zc + 0.04))
                q3 = p + t * -0.15 + Vector((0, 0, zc + 0.04))
                lamps.quad([q0, q1, q2, q3], m("lamp_dim"))
        # flush rim light strip around the opening
        lamps.quad(
            [
                a - nrm * 0.25 + Vector((0, 0, 0.002)),
                b - nrm * 0.25 + Vector((0, 0, 0.002)),
                b - nrm * 0.12 + Vector((0, 0, 0.002)),
                a - nrm * 0.12 + Vector((0, 0, 0.002)),
            ],
            m("lamp_white"),
        )
    lamps.build("SM_launchwell_lamps", bevel_width=0.0, nav="none")

    paint = K.MeshBuilder()
    hazard_out = _well_outline(length, width, 2.4, 1.2 + 0.3)  # thin worn band
    verts = [Vector((x, y, 0.0015)) for x, y in hazard_out] + [
        Vector((x, y, 0.0015)) for x, y in outer
    ]
    paint._add(verts, [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)], m("hazard"))
    paint.build("SM_launchwell_paint", bevel_width=0.0, nav="none")


K.register_variant("SM_Hangar_LaunchWell", build_launch_well, dims=(32.4, 14.4, 10.0))


# --------------------------------------------------------------------------
# Deck markings (flat decals)
# --------------------------------------------------------------------------

Z_PAINT = 0.0015


def build_marking_pad(radius=9.0, label="07"):
    """Landing pad: segmented ring, ticks, centre cross and pad number."""
    mb = K.MeshBuilder()
    white, red = m("stencil_white"), m("stencil_red")
    for i in range(24):
        a0 = 15.0 * i + 1.5
        G.annulus(mb, radius - 0.3, radius, Z_PAINT, white, 4, a0, a0 + 12.0)
    G.annulus(mb, radius - 0.75, radius - 0.6, Z_PAINT, white, 96)
    for a in (0.0, 90.0, 180.0, 270.0):
        p0 = G.polar(radius - 1.6, a)
        p1 = G.polar(radius + 0.6, a)
        G.stripe_quad(mb, p0, p1, 0.3, Z_PAINT, white)
    G.stripe_quad(mb, (-1.2, 0.0), (1.2, 0.0), 0.25, Z_PAINT, red)
    G.stripe_quad(mb, (0.0, -1.2), (0.0, 1.2), 0.25, Z_PAINT, red)
    G.text(mb, label, 2.2, white, G.T(0.0, -radius + 2.6, Z_PAINT))
    G.text(mb, label, 2.2, white, G.T(0.0, radius - 2.6, Z_PAINT) @ G.Rz(180.0))
    mb.build("SM_marking_pad", bevel_width=0.0, nav="none")


def build_marking_lane(length=12.0, dashed=True):
    """Lane line (dashed or solid), 0.15 m wide, along X."""
    mb = K.MeshBuilder()
    if dashed:
        n = int(length / 1.2)
        for i in range(n):
            if i % 2 == 0:
                x0 = -length / 2 + i * 1.2
                G.stripe_quad(mb, (x0, 0.0), (x0 + 1.2, 0.0), 0.15, Z_PAINT, m("stencil_white"))
    else:
        G.stripe_quad(mb, (-length / 2, 0.0), (length / 2, 0.0), 0.15, Z_PAINT, m("stencil_white"))
    mb.build("SM_marking_lane", bevel_width=0.0, nav="none")


def build_marking_chevrons(count=3):
    """Row of chevrons pointing +Y (direction of travel), 2.4 m wide."""
    mb = K.MeshBuilder()
    for i in range(count):
        y = i * 1.2 - (count - 1) * 0.6
        G.stripe_quad(mb, (-1.2, y - 0.6), (0.0, y), 0.3, Z_PAINT, m("stencil_white"))
        G.stripe_quad(mb, (0.0, y), (1.2, y - 0.6), 0.3, Z_PAINT, m("stencil_white"))
    mb.build("SM_marking_chevrons", bevel_width=0.0, nav="none")


def build_marking_hatch(w=4.8, d=2.4):
    """Hatched keep-clear rectangle (red border with diagonal hatching)."""
    mb = K.MeshBuilder()
    red = m("stencil_red")
    hw, hd = w / 2, d / 2
    for p0, p1 in (
        ((-hw, -hd), (hw, -hd)),
        ((hw, -hd), (hw, hd)),
        ((hw, hd), (-hw, hd)),
        ((-hw, hd), (-hw, -hd)),
    ):
        G.stripe_quad(mb, p0, p1, 0.15, Z_PAINT, red)
    x = -hw - d
    while x < hw:
        a = Vector((x, -hd))
        b = Vector((x + d, hd))
        if a.x < -hw:
            a = Vector((-hw, -hd + (-hw - a.x)))
        if b.x > hw:
            b = Vector((hw, hd - (b.x - hw)))
        if (b - a).length > 0.2:
            G.stripe_quad(mb, a, b, 0.12, Z_PAINT, red)
        x += 0.6
    mb.build("SM_marking_hatch", bevel_width=0.0, nav="none")


def build_marking_number(label="B4", size=3.0):
    mb = K.MeshBuilder()
    G.text(mb, label, size, m("stencil_white"), G.T(0.0, 0.0, Z_PAINT))
    mb.build("SM_marking_number", bevel_width=0.0, nav="none")


K.register_variant("SM_Hangar_Marking_Pad", build_marking_pad, dims=(18.6, 18.6, 0.0), nav="none")
K.register_variant(
    "SM_Hangar_Marking_LaneDashed", build_marking_lane, dims=(12.0, 0.15, 0.0), nav="none"
)
K.register_variant(
    "SM_Hangar_Marking_LaneSolid",
    build_marking_lane,
    dims=(12.0, 0.15, 0.0),
    nav="none",
    dashed=False,
)
K.register_variant(
    "SM_Hangar_Marking_Chevrons", build_marking_chevrons, dims=(2.7, 3.0, 0.0), nav="none"
)
K.register_variant(
    "SM_Hangar_Marking_Hatch", build_marking_hatch, dims=(4.95, 2.55, 0.0), nav="none"
)
K.register_variant(
    "SM_Hangar_Marking_BayNumber", build_marking_number, dims=(4.0, 3.0, 0.0), nav="none"
)


# --------------------------------------------------------------------------
# Racks (armour, storage)
# --------------------------------------------------------------------------


def _armour_set(mb, x, y, z):
    """Generic armour shell on a stand: torso plates, shoulder guards, helmet."""
    shell, dark, metal = m("panel_light"), m("panel_dark"), m("gunmetal")
    mb.tube((x, y, z), (x, y, z + 1.1), 0.03, metal, 8)
    with G.xf(mb, G.T(x, y, z + 1.05)):
        G.lathe(
            mb,
            [
                (0.0, 0.0),
                (0.16, 0.02),
                (0.2, 0.18),
                (0.21, 0.4),
                (0.17, 0.52),
                (0.08, 0.56),
                (0.0, 0.56),
            ],
            shell,
            16,
        )
        mb.box((-0.12, -0.215, 0.12), (0.12, -0.19, 0.36), dark)
        for sx in (-1, 1):
            with G.xf(mb, G.T(sx * 0.25, 0.0, 0.46) @ G.Ry(sx * 25.0)):
                G.chamfer_box(mb, (-0.09, -0.12, -0.03), (0.09, 0.12, 0.03), 0.04, shell)
    with G.xf(mb, G.T(x, y, z + 1.86)):
        G.lathe(
            mb,
            [(0.0, 0.3), (0.1, 0.29), (0.15, 0.22), (0.16, 0.08), (0.14, 0.0), (0.0, 0.0)],
            shell,
            16,
        )
        mb.box((-0.11, -0.16, 0.11), (0.11, -0.13, 0.17), m("glass_dark"))


def build_armour_rack(count=4):
    """Wall rack holding generic armour sets, with a parts shelf."""
    mb = K.MeshBuilder(G.T(0.0, -0.68, 0.0))  # back on the wall plane
    metal, steel = m("gunmetal"), m("dark_steel")
    width = count * 0.6
    hw = width / 2
    mb.box((-hw - 0.05, 0.6, 0.0), (hw + 0.05, 0.68, 2.3), m("panel_dark"))
    for sx in (-1, 1):
        mb.box((sx * hw - 0.04, 0.0, 0.0), (sx * hw + 0.04, 0.68, 2.3), metal)
    mb.box((-hw, 0.0, 0.0), (hw, 0.68, 0.1), steel)
    mb.box((-hw, 0.1, 2.15), (hw, 0.68, 2.2), metal)
    for i in range(count):
        _armour_set(mb, -hw + 0.3 + i * 0.6, 0.32, 0.1)
    mb.build("SM_armourrack_body", bevel_width=0.004)
    lamps = K.MeshBuilder(G.T(0.0, -0.68, 0.0))
    lamps.box((-hw + 0.1, 0.1, 2.14), (hw - 0.1, 0.4, 2.15), m("lamp_white"))
    lamps.build("SM_armourrack_lamps", bevel_width=0.0, nav="none")
    K.occluder(((-hw - 0.05, -0.68, 0.0), (hw + 0.05, 0.0, 2.3)), nav="block")


def build_storage_rack(bays=2, levels=3):
    """Pallet racking 2.4 m per bay with crates on every level."""
    mb = K.MeshBuilder(G.T(0.0, -1.2, 0.0))  # back on the wall plane
    metal, steel = m("gunmetal"), m("dark_steel")
    width = bays * 2.4
    hw = width / 2
    height = levels * 1.4 + 0.4
    rnd = G.rng("storage_rack", bays, levels)
    for b in range(bays + 1):
        x = -hw + b * 2.4
        for y in (0.08, 1.12):
            mb.box((x - 0.05, y - 0.05, 0.0), (x + 0.05, y + 0.05, height), metal)
        for k in range(int(height / 0.6)):
            G.beam(mb, (x, 0.08, 0.3 + k * 0.6), (x, 1.12, 0.6 + k * 0.6), 0.03, 0.03, steel)
    for lv in range(levels):
        z = 0.15 + lv * 1.4
        for y in (0.08, 1.12):
            mb.box((-hw, y - 0.06, z - 0.12), (hw, y + 0.06, z), m("stencil_amber"))
        for b in range(bays):
            x0 = -hw + b * 2.4 + 1.2
            if rnd.random() < 0.15:
                continue
            for sx in (-0.6, 0.6):
                if rnd.random() < 0.25:
                    continue
                w, d, h = rnd.choice(((1.0, 0.8, 0.8), (0.9, 0.9, 1.0), (1.0, 0.7, 0.6)))
                _crate(
                    mb,
                    x0 + sx,
                    0.6,
                    z,
                    w,
                    d,
                    h,
                    rnd,
                    rnd.choice(("container_charcoal", "container_gunmetal", "container_olive")),
                )
    mb.build("SM_storagerack_body", bevel_width=0.005)
    K.occluder(((-hw - 0.05, -1.2, 0.0), (hw + 0.05, 0.0, height)), nav="block")


K.register_variant("SM_Hangar_ArmourRack", build_armour_rack, dims=(2.5, 0.68, 2.3))
K.register_variant("SM_Hangar_StorageRack", build_storage_rack, dims=(4.9, 1.2, 4.6))


# --------------------------------------------------------------------------
# Lookdev hints and the hangar vignette
# --------------------------------------------------------------------------

LOOKDEV = {
    "SM_Hangar_BlastDoor": {"focus": (0.0, -0.8, 8.0), "crop_size": (4.0, 2.6), "max_px": 2400},
    "SM_Hangar_LaunchWell": {
        "floor": False,  # the lookdev floor would cover the opening
        "focus": (12.0, -6.0, -0.5),
        "crop_size": (4.0, 2.6),
        "max_px": 2400,
    },
    "SM_Hangar_Marking_Pad": {"focus": (0.0, -8.0, 0.0), "crop_size": (4.0, 2.6)},
    "SM_Hangar_GantryBridge": {"skip": True},
}


def place_hangar_vignette(collection):
    """Hangar slice: blast doors, launch well, shuttle on its pad, cargo rows,
    tug, fuel lines and markings. Returns the plate frame (u0, u1, v0, v1)."""
    deck = "flight_deck"
    with K.into(collection):
        K.place("SM_Hangar_BlastDoor", (0.0, 40.0, 0.0), room=deck)
        for x in (-23.0, 23.0):
            K.place("SM_Hangar_GantryColumn", (x, 36.5, 0.0), room=deck)
        K.place("SM_Hangar_LaunchWell", (0.0, 27.0, 0.0), room=deck)
        K.place("SM_Hangar_LandingPad", (0.0, 5.0, 0.0), room=deck)
        K.place("SM_Hangar_Shuttle", (0.0, 5.0, 0.0), room=deck)
        K.place("SM_Hangar_Marking_Chevrons", (0.0, -12.5, 0.0), 180.0, room=deck)
        for x in (-11.0, 11.0):
            K.place("SM_Hangar_Marking_LaneDashed", (x, 5.0, 0.0), 90.0, room=deck)
        cargo = (
            ("SM_Hangar_Container_L_Charcoal", -19.0, 14.0),
            ("SM_Hangar_Container_L_Olive", -19.0, 10.6),
            ("SM_Hangar_Container_L_Grey", -19.0, 7.2),
            ("SM_Hangar_Container_M_Gunmetal", -20.2, 3.8),
            ("SM_Hangar_Container_M_Charcoal", -20.2, 0.4),
            ("SM_Hangar_Container_S_Grey", -15.4, 3.8),
            ("SM_Hangar_Container_S_Charcoal", -15.4, 0.6),
        )
        for name, x, y in cargo:
            K.place(name, (x, y, 0.0), room=deck)
        K.place("SM_Hangar_CrateStack", (-14.8, 10.6, 0.0), room=deck)
        K.place("SM_Hangar_Pallet_Loaded", (-14.6, 14.0, 0.0), room=deck)
        K.place("SM_Hangar_Pallet", (-13.0, 14.0, 0.0), room=deck)
        K.place("SM_Hangar_Crate_A", (-14.4, -3.0, 0.0), 8.0, room=deck)
        K.place("SM_Hangar_Crate_B", (-13.2, -3.4, 0.0), -5.0, room=deck)
        K.place("SM_Hangar_TowTug", (8.0, -6.5, 0.0), 160.0, room=deck)
        K.place("SM_Hangar_FuelHydrant", (7.6, 1.0, 0.0), room=deck)
        K.place("SM_Hangar_FuelCart", (9.6, 6.0, 0.0), 90.0, room=deck)
        K.place("SM_Hangar_ToolCart", (-3.0, -9.5, 0.0), 15.0, room=deck)
        from . import hangar_service

        hangar_service.build_hose(
            "LD_hose_fuel", [(7.2, 0.7), (6.2, 0.0), (4.6, -0.4), (3.6, -0.5, 1.55)], room=deck
        )
        for x in (-11.0, 11.0):
            for y in (-8.0, 0.0, 8.0, 16.0):
                K.place("SM_Hangar_FloorLight", (x, y, 0.0), room=deck)
        K.place("SM_Hangar_Marking_Hatch", (17.0, 12.0, 0.0), 90.0, room=deck)
        K.place("SM_Hangar_StorageRack", (20.5, 2.0, 0.0), -90.0, room=deck)
        K.place("SM_Hangar_StorageRack", (20.5, 7.2, 0.0), -90.0, room=deck)
        K.place("SM_Hangar_ArmourRack", (20.6, -3.0, 0.0), -90.0, room=deck)
    return -25.0, 25.0, -14.0, 44.0
