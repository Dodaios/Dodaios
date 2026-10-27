"""Wall cladding and overhead structure of the Main Hangar, seen at eye level.

From the shoulder camera the hangar read as an empty grey shed: the side hull
walls were smooth light panels, the near wall over the front band a flat grey
field. This module dresses them in the ship's wall language with the kit's
``kit.architecture.cladding`` (the bridge's wall-detail level, PR #910; reused
by the operations deck, PR #1023) and adds the flight deck's overhead
structure:

* Side hull walls (x 2.5 and 97.5): a hall wall from the deck up to 6 m
  (plinth with louvres, charcoal panels with seams and insets, light columns
  between gunmetal ribs on the ceiling girders' 7.2 m rhythm, a rail with a
  conduit bundle), the service cabinets on the wall as openings; above it
  three tiers of dark 2.4 m panels with insets, louvres and tall light
  columns in alternate bays, a crane runway beam, a fuel main and a cable
  ladder.
* Near wall over the front band (plan z 46, facing the hall): the same hall
  wall from the band ceiling up, the flight control windows over the booth,
  dark upper tiers with light columns, and a blast-door header with hazard
  chevrons and warning lamps along the band's open edge.
* Front band rooms: wall terminals, status boards, junction boxes and
  section sign plates on the near hull wall.
* Two overhead bridge cranes across the whole hall on runway beams, each with
  a trolley, hoist cables and a hook block.

Everything is a ceiling ghost (``kit.ghost``): invisible to the plate camera
and to shadow rays, nav ``none``, no occluders, so the plate, the nav grid
and the occluders keep their shape. The plate sees the side walls edge-on and
the near wall's hall face from behind, so nothing it shows changes.
"""

from __future__ import annotations

import hangar_arch as A
import hangar_layout as L
from kit.architecture import cladding as C
from kit.props import fitout as F
from lib import kit, materials, scene

HAZARD = "M_Hangar_HazardPaint"
GLASS = "M_Glass_Viewport"

GIRDERS = [3.6 + 7.2 * i for i in range(7)]  # ceiling girders over the hall (plan z)
SKIN_POSTS = [2.4 + 7.2 * i for i in range(14)]  # near-wall frames (plan x)
SIDE_TOP = 6.0  # top of the hall-wall dressing on the side walls
BAND_CEILING = 4.7
SKIN_BASE = 9.6  # top of the hall-wall dressing on the near wall
TIERS = ((6.0, 9.6), (9.9, 15.0), (15.3, A.CEILING_H - 1.6))
RUNWAY_H = 15.6  # crane runway beam (top of rail)
CRANES = ((15.6, 23.0, 9.0), (33.0, 16.0, 7.2))  # (plan z, trolley x, hook height)
WINDOW = (3.2, 23.2, 5.9, 7.7)  # flight control windows over the booth: x0, x1, h0, h1


@materials.material(HAZARD, viewport=(0.32, 0.2, 0.012))
def _hazard_paint(g) -> None:
    """Opaque yellow/black hazard chevrons on steel (kerbs, beams, rigs).

    The floor decal material ``M_Deck_Hazard`` wears through to transparency
    and is left out of the realtime export; this one is solid paint, so the
    stripes show at eye level too."""
    pos = g.coord("world", per_instance=False)
    x, y, z = g.separate(pos)
    stripe = g.math("GREATER_THAN", g.math("FRACT", g.math("DIVIDE", g.add(x, y, z), 0.32)), 0.5)
    paint = g.mix_color(stripe, (0.34, 0.21, 0.012), (0.014, 0.014, 0.015))
    _keep, scuff, grime = materials.paint_wear(g, pos)
    paint = g.mix_color(g.add(g.mul(scuff, 0.45), g.mul(grime, 0.12)), paint, (0.05, 0.05, 0.052))
    bsdf = g.principled(
        Base_Color=paint,
        Roughness=g.add(0.42, g.mul(scuff, 0.2), g.mul(grime, 0.08)),
        Normal=g.bump(g.mul(scuff, -0.3), 0.1, 0.001),
    )
    g.output(bsdf.outputs[0])


# ---------------------------------------------------------------- side walls


def side_cabinets(side: str) -> tuple[float, ...]:
    """Plan z of the service cabinets left on a side wall (the others made
    room for racks and the fuel manifolds, hangar_fitout.py)."""
    return L.SIDE_CABINETS[side]


def _tiers(B: C.Builders, seed, edges, *, lit_from: int) -> None:
    """Dark upper tiers between frames: 2.4 m panels (some inset, a few mid
    grey), a louvre now and then, a tall light column in alternate bays."""
    for bi, (a, b) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        a, b = a + 0.45, b - 0.45
        if b - a < 1.0:
            continue
        cu = round(((a + b) / 2) / 0.3) * 0.3
        lit = (bi + lit_from) % 2 == 0 and b - a > 3.0
        holes = [(cu - 0.3, cu + 0.3)] if lit else []
        for ti, (h0, h1) in enumerate(TIERS):
            rows = max(1, round((h1 - h0) / 2.4))
            rh = (h1 - h0) / rows
            for sa, sb in C.subtract(a, b, holes):
                for i, (m0, m1) in enumerate(C.modules(sa, sb, 2.4)):
                    for j in range(rows):
                        z0, z1 = h0 + j * rh, h0 + (j + 1) * rh
                        r = C.seed01(seed, "t", bi, ti, sa, i, j)
                        mat = C.MID if r < 0.12 else C.CHARCOAL if r < 0.45 else C.DARK
                        C.panel(B, m0, m1, z0, z1, mat, inset=0.3 < r < 0.7)
                        if r > 0.9 and m1 - m0 > 1.2 and z1 - z0 > 1.0:
                            C.louvre(B, (m0 + m1) / 2, z0 + 0.25, w=0.9, h=0.45)
            if lit:
                C.light_column(B, cu, h0 + 0.1, h1 - 0.1, (seed, "col", bi, ti))
        C.box(B.flat, a, b, 0.0, C.BACK, TIERS[0][0], TIERS[-1][1], C.RECESS)


def side_wall(side: str) -> None:
    x_face, sign = (L.SIDE_T, 1) if side == "W" else (L.WIDTH - L.SIDE_T, -1)
    B = C.Builders().at(C.run_matrix("z", x_face, sign))
    seed = ("hangar", "side", side)
    t0, t1 = L.WALL_FACE_Z + 0.1, L.FRONT_Z - 0.1
    openings = [C.Opening(z - 0.62, z + 0.62, 2.15) for z in side_cabinets(side)]
    ribs = [g for g in GIRDERS if t0 < g < t1]
    nb = len(ribs) + 1
    C.hall_wall(
        B,
        seed,
        t0,
        t1,
        top=SIDE_TOP,
        ribs=ribs,
        lit_bays={i for i in range(nb) if i % 2 == (0 if side == "W" else 1)},
        red_ribs={i for i in range(len(ribs)) if i % 3 == 1},
        openings=openings,
    )
    _tiers(B, seed, [t0, *GIRDERS, t1], lit_from=1 if side == "W" else 0)
    # Status boards and sign plates over the cabinets.
    for k, z in enumerate(side_cabinets(side)):
        if k % 2 == 0:
            C.status_panel(B, z, 3.5, seed=(seed, k))
    for k, z in enumerate((12.0, 26.4, 40.8)):
        C.sign_plate(B, z, 4.6, f"4-{(1 if side == 'W' else 5) + k:02d}", ch=0.2)
    # Fuel main and cable ladder above the racks, on wall brackets.
    mains = ((0.0, 0.11, C.PIPE_INS), (0.26, 0.08, C.PIPE), (0.46, 0.05, C.PIPE))
    F.pipe_run(B, t0 + 0.2, t1 - 0.2, 0.3, 4.75, 5.15, pipes=mains)
    F.cable_ladder(B, t0 + 0.2, t1 - 0.2, 0.2, 0.8, 5.55, 5.9)
    u = t0 + 1.2
    while u < t1 - 0.5:
        C.box(B.struct, u - 0.04, u + 0.04, C.BACK, 0.9, 5.1, 5.18, C.GUNMETAL)
        C.box(B.struct, u - 0.04, u + 0.04, C.BACK, 0.9, 5.9, 5.98, C.GUNMETAL)
        u += 2.4
    # Crane runway: a deep box beam on brackets at every frame.
    C.box(B.struct, t0, t1, 0.3, 1.1, RUNWAY_H - 1.2, RUNWAY_H - 0.1, C.GUNMETAL)
    C.box(B.struct, t0, t1, 0.6, 0.8, RUNWAY_H - 0.1, RUNWAY_H, C.STEEL)
    C.box(B.flat, t0, t1, 1.1, 1.104, RUNWAY_H - 1.0, RUNWAY_H - 0.85, HAZARD)
    for g in GIRDERS:
        B.struct.prism_x(
            [(C.BACK, RUNWAY_H - 3.2), (0.3, RUNWAY_H - 3.2), (1.1, RUNWAY_H - 1.2),
             (C.BACK, RUNWAY_H - 1.2)],
            g - 0.2, g + 0.2, C.GUNMETAL,
        )  # fmt: skip
    B.finish(f"SM_Hangar_Clad_side_{side}", room="flight_deck")


# ---------------------------------------------------------------- near wall


def flight_control_windows(B: C.Builders) -> None:
    """A glazed bay over the booth: lit consoles and crew stations behind
    gunmetal mullions (the hall's view into flight control)."""
    x0, x1, h0, h1 = WINDOW
    d = 0.55
    C.box(B.flat, x0, x1, 0.0, 0.05, h0, h1, C.RECESS)  # back of the room
    C.box(B.struct, x0 - 0.2, x1 + 0.2, 0.0, d + 0.1, h0 - 0.35, h0, C.GUNMETAL)
    C.box(B.struct, x0 - 0.2, x1 + 0.2, 0.0, d + 0.1, h1, h1 + 0.3, C.GUNMETAL)
    C.box(B.struct, x0 - 0.2, x1 + 0.2, d + 0.1, d + 0.12, h0 - 0.2, h0 - 0.12, C.STEEL)
    for xs in (x0 - 0.2, x1):
        C.box(B.struct, xs, xs + 0.2, 0.0, d + 0.1, h0, h1, C.GUNMETAL)
    C.box(B.lamps, x0, x1, 0.12, 0.42, h1 - 0.03, h1, C.BACKLIT)  # ceiling light
    u = x0 + 0.4
    k = 0
    while u < x1 - 0.8:
        C.box(B.panels, u, u + 1.6, 0.06, 0.4, h0, h0 + 0.55, C.BODY)  # console run
        C.box(B.lamps, u + 0.15, u + 0.75, 0.06, 0.064, h0 + 0.6, h0 + 0.95, C.SCREEN)
        C.box(B.lamps, u + 0.85, u + 1.45, 0.06, 0.064, h0 + 0.6, h0 + 0.95, C.SCREEN)
        pip = "M_Indicator_Amber" if k % 3 == 1 else "M_Indicator_Green"
        C.box(B.lamps, u + 0.1, u + 0.16, 0.4, 0.404, h0 + 0.45, h0 + 0.5, pip)
        u += 2.0
        k += 1
    m = x0
    while m <= x1 + 1e-6:
        C.box(B.struct, m - 0.06, m + 0.06, d - 0.04, d + 0.06, h0, h1, C.STEEL)
        m += (x1 - x0) / 8
    C.box(B.flat, x0, x1, d - 0.012, d - 0.004, h0, h1, GLASS)


def near_wall_skin() -> None:
    """The hall face of the near wall above the front band (plan z 46)."""
    B = C.Builders().at(C.run_matrix("x", L.FRONT_Z, -1))
    seed = ("hangar", "skin")
    t0, t1 = L.SIDE_T + 0.1, L.WIDTH - L.SIDE_T - 0.1
    ribs = [x for x in SKIN_POSTS if t0 + 0.5 < x < t1 - 0.5]
    nb = len(ribs) + 1
    bands = C.Bands(cornice=0.3)
    C.hall_wall(
        B,
        seed,
        t0,
        t1,
        top=SKIN_BASE,
        ribs=ribs,
        floor=BAND_CEILING,
        bands=bands,
        lit_bays={i for i in range(nb) if i % 2 == 1 and i > 3},
        red_ribs={i for i in range(len(ribs)) if i % 4 == 2},
    )
    flight_control_windows(B)
    edges = [t0, *ribs, t1]
    for bi, (a, b) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        a, b = a + 0.45, b - 0.45
        lit = bi % 2 == 0 and b - a > 3.0
        cu = round(((a + b) / 2) / 0.3) * 0.3
        holes = [(cu - 0.3, cu + 0.3)] if lit else []
        for ti, (h0, h1) in enumerate(TIERS[1:]):
            rows = max(1, round((h1 - h0) / 2.4))
            rh = (h1 - h0) / rows
            for sa, sb in C.subtract(a, b, holes):
                for i, (m0, m1) in enumerate(C.modules(sa, sb, 2.4)):
                    for j in range(rows):
                        z0, z1 = h0 + j * rh, h0 + (j + 1) * rh
                        r = C.seed01(seed, "t", bi, ti, sa, i, j)
                        mat = C.MID if r < 0.12 else C.CHARCOAL if r < 0.45 else C.DARK
                        C.panel(B, m0, m1, z0, z1, mat, inset=0.3 < r < 0.7)
            if lit:
                C.light_column(B, cu, h0 + 0.1, h1 - 0.1, (seed, "col", bi, ti))
        C.box(B.flat, a, b, 0.0, C.BACK, TIERS[1][0], TIERS[-1][1], C.RECESS)
    # Blast-door header along the band's open edge: a deep beam under the
    # band ceiling with hazard chevrons, retracted door leaves and red lamps.
    C.box(B.struct, t0, t1, 0.0, 0.62, 3.95, BAND_CEILING, C.GUNMETAL)
    C.box(B.flat, t0, t1, 0.62, 0.635, 4.05, 4.5, HAZARD)
    C.box(B.flat, t0, t1, 0.1, 0.52, 3.93, 3.95, C.RECESS)  # leaf slot
    for x in SKIN_POSTS:
        if t0 < x < t1:
            C.box(B.struct, x - 0.32, x + 0.32, 0.0, 0.7, 3.6, BAND_CEILING, C.GUNMETAL)
            C.box(B.lamps, x - 0.08, x + 0.08, 0.7, 0.705, 3.75, 3.85, C.RED)
    B.finish("SM_Hangar_Clad_skin", room="flight_deck")


# ---------------------------------------------------------------- front band


# Fittings on the near hull wall per room: (room, kind, x, height)
BAND_FITTINGS = (
    ("crew_bay", "sign", 32.6, 3.7, "4-21"),
    ("crew_bay", "status", 26.4, 1.95, ""),
    ("crew_bay", "jbox", 38.8, 1.9, ""),
    ("crew_bay", "status", 33.8, 1.95, ""),
    ("arrivals", "sign", 51.0, 3.7, "4-22"),
    ("arrivals", "terminal", 48.6, 1.15, ""),
    ("arrivals", "terminal", 53.4, 1.15, ""),
    ("arrivals", "status", 44.0, 2.4, ""),
    ("arrivals", "status", 57.6, 2.4, ""),
    ("lift_lobby", "sign", 70.0, 3.7, "4-23"),
    ("lift_lobby", "jbox", 66.6, 1.4, ""),
    ("lift_lobby", "status", 73.4, 1.6, ""),
    ("armoury", "sign", 87.2, 3.7, "4-24"),
    ("armoury", "status", 79.8, 2.4, ""),
    ("armoury", "jbox", 94.8, 1.9, ""),
)


def band_fittings() -> None:
    nz0 = L.NEAR_WALL_Z[0] - 0.02  # in front of the upper wall's panels
    by_room: dict[str, C.Builders] = {}
    for i, (room, kind, x, h, code) in enumerate(BAND_FITTINGS):
        B = by_room.setdefault(room, C.Builders().at(C.run_matrix("x", nz0, -1)))
        seed = ("hangar", "band", i)
        if kind == "sign":
            C.sign_plate(B, x, h, code, ch=0.16)
        elif kind == "status":
            C.status_panel(B, x, h, seed=seed)
        elif kind == "jbox":
            C.junction_box(B, x, h, seed=seed)
            C.conduit_drop(B, x, h + 0.5, 4.4, n=2)
        elif kind == "terminal":
            C.wall_terminal(B, x, h, seed=seed)
            C.conduit_drop(B, x + 0.42, h, 4.4, n=1)
    for room, B in by_room.items():
        B.finish(f"SM_Hangar_Clad_band_{room}", room=room)


# ---------------------------------------------------------------- cranes


def bridge_crane(B: C.Builders, k: int, zc: float, tx: float, hook: float) -> None:
    """Overhead bridge crane across the hall: twin box girders on end trucks
    running on the side walls' runway beams, a trolley with a hoist drum, two
    hoist cables and a hook block. Frame: u = plan x, v = plan z."""
    x0, x1 = L.SIDE_T + 0.4, L.WIDTH - L.SIDE_T - 0.4
    h0 = RUNWAY_H + 0.05
    for dz in (-0.75, 0.75):
        C.box(B.struct, x0 + 0.6, x1 - 0.6, zc + dz - 0.28, zc + dz + 0.28, h0 + 0.2, h0 + 1.5,
              C.GUNMETAL)  # fmt: skip
        C.box(B.struct, x0 + 0.6, x1 - 0.6, zc + dz - 0.34, zc + dz + 0.34, h0 + 1.5, h0 + 1.58,
              C.STEEL)  # fmt: skip
        x = x0 + 2.4
        while x < x1 - 2.0:  # stiffener plates
            C.box(B.struct, x - 0.03, x + 0.03, zc + dz - 0.3, zc + dz + 0.3, h0 + 0.2, h0 + 1.5,
                  C.STEEL)  # fmt: skip
            x += 2.4
    for xe, s in ((x0, 1), (x1, -1)):  # end trucks with hazard ends and wheels
        a, b = sorted((xe, xe + s * 1.4))
        C.box(B.struct, a, b, zc - 1.7, zc + 1.7, h0, h0 + 0.9, C.GUNMETAL)
        C.box(B.flat, a, b, zc - 1.72, zc - 1.7, h0 + 0.1, h0 + 0.8, HAZARD)
        C.box(B.flat, a, b, zc + 1.7, zc + 1.72, h0 + 0.1, h0 + 0.8, HAZARD)
        for dz in (-1.3, 1.3):
            B.pipes.tube((xe + s * 0.35, zc + dz, h0 + 0.05), (xe + s * 0.05, zc + dz, h0 + 0.05),
                         0.3, C.STEEL, 16)  # fmt: skip
        lamp = "M_Indicator_Amber" if k % 2 == 0 else "M_Indicator_Red"
        C.box(B.lamps, a + 0.5, b - 0.5, zc - 0.1, zc + 0.1, h0 + 0.9, h0 + 1.0, lamp)
    # Trolley on the girders, hoist drum between them.
    ht = h0 + 1.58
    C.box(B.struct, tx - 1.3, tx + 1.3, zc - 1.2, zc + 1.2, ht, ht + 0.7, C.MID)
    C.box(B.flat, tx - 1.32, tx + 1.32, zc - 1.22, zc + 1.22, ht + 0.7, ht + 0.74, C.STEEL)
    C.box(B.flat, tx - 1.3, tx + 1.3, zc - 1.21, zc - 1.2, ht + 0.1, ht + 0.3, HAZARD)
    B.pipes.tube((tx - 0.9, zc, h0 + 0.6), (tx + 0.9, zc, h0 + 0.6), 0.36, C.GUNMETAL, 20)
    C.box(B.lamps, tx - 0.1, tx + 0.1, zc - 0.1, zc + 0.1, ht + 0.74, ht + 0.84,
          "M_Indicator_Amber")  # fmt: skip
    for dx in (-0.25, 0.25):  # hoist cables
        B.pipes.tube((tx + dx, zc, h0 + 0.3), (tx + dx, zc, hook + 0.35), 0.02, C.STEEL, 6)
    # Hook block: sheave housing, hazard cheeks, the hook.
    C.box(B.struct, tx - 0.4, tx + 0.4, zc - 0.22, zc + 0.22, hook - 0.1, hook + 0.45, C.GUNMETAL)
    C.box(B.flat, tx - 0.41, tx + 0.41, zc - 0.23, zc + 0.23, hook + 0.05, hook + 0.3, HAZARD)
    B.pipes.tube((tx, zc, hook - 0.1), (tx, zc, hook - 0.4), 0.06, C.STEEL, 10)
    B.pipes.tube((tx, zc - 0.05, hook - 0.45), (tx, zc + 0.05, hook - 0.45), 0.17, C.STEEL, 16)
    if k == 1:
        # A lifting beam on slings, waiting over the stores.
        C.box(B.struct, tx - 1.8, tx + 1.8, zc - 0.12, zc + 0.12, hook - 1.6, hook - 1.3, HAZARD)
        for dx in (-1.6, 1.6):
            B.pipes.tube((tx, zc, hook - 0.5), (tx + dx, zc, hook - 1.3), 0.02, C.STEEL, 6)
            B.pipes.tube((tx + dx, zc, hook - 1.6), (tx + dx, zc, hook - 2.4), 0.02, C.STEEL, 6)
            B.pipes.tube((tx + dx, zc - 0.05, hook - 2.5), (tx + dx, zc + 0.05, hook - 2.5), 0.09,
                         C.STEEL, 10)  # fmt: skip


def cranes() -> None:
    B = C.Builders().at(C.place_matrix(0.0, 0.0, 0.0))
    for k, (zc, tx, hook) in enumerate(CRANES):
        bridge_crane(B, k, zc, tx, hook)
    B.finish("SM_Hangar_Cranes", room="flight_deck")


def build() -> None:
    with kit.into(scene.collection("Ceiling")):
        with kit.ghost(-1.0):
            side_wall("W")
            side_wall("E")
            near_wall_skin()
            band_fittings()
            cranes()
