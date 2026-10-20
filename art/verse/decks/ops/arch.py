"""Architecture of the Operations deck: floors, walls, the corridor spine,
service chases, hull structure and the ceilings with their light fixtures.

Every wall that has walkable space behind it is built twice: the part below
the 1.1 m section plane is seen by the camera and capped with the section
material; the part above it lives in the ``Ceiling`` collection, which the
cook hides from the camera, so it still bounds the room for light, shadows
and the reflections in the black floors.
"""

from __future__ import annotations

import math

from decks.ops import layout as L
from decks.ops.geo import CUT_H, Mesh, area_light, collection, emitter_h, point_light, tag
from kit.architecture import hull
from lib import kit

M = L.MODULE
CAP = "M_Section_Cap"
PAINT = "M_Wall_PaintedLight"
PAINT_MID = "M_Wall_PaintedMid"
PAINT_DARK = "M_Wall_PaintedDark"
STEEL = "M_Struct_Gunmetal"
RECESS = "M_Recess_Dark"
SKIN = 0.025  # panel skin on visible wall faces

FLOOR_MATS = {
    "mess": "M_Floor_GlossBlack",
    "records": "M_Floor_GlossBlack",
    "simulator": "M_Ops_Floor_Satin",
    "quartermaster": "M_Floor_GlossBlack",
    "quarters": "M_Ops_Floor_Satin",
    "team_a": "M_Ops_Floor_Satin",
    "team_b": "M_Ops_Floor_Satin",
    "lobby": "M_Floor_GlossBlack",
    "storage": "M_Ops_Floor_Satin",
    "medbay": "M_Ops_Floor_SatinGrey",
}


def build(cavities=()) -> None:
    floors()
    hero_wall_body(cavities)
    corridor()
    chases()
    near_wall()
    med_wall()
    side_hulls()
    lift_core()
    ceiling()


# ---------------------------------------------------------------- floors


def floors() -> None:
    base = Mesh()
    # Under the rooms a plain slab; the open hull bays at the deck edges go
    # 2.4 m deep (kit hull bays), so the slab there drops below their tank top.
    base.box(2.4, 93.6, -3.0, L.NEAR_Z + 2.0, -1.4, -0.6, "M_Hull_Structure")
    base.box(-4.8, 100.8, -3.0, 64.8, -3.2, -2.5, "M_Hull_Structure")
    tag(base.build("SM_Ops_HullBase", bevel=0.0), nav="none")
    for rid, r in L.ROOMS.items():
        x0, x1, z0, z1 = r.rect
        m = Mesh()
        if rid == "lobby":
            # The lift shafts are open pits, not floor.
            lx0, lx1, _, lz1 = L.LIFT_CORE
            m.box(x0, lx0, z0, z1, -0.3, 0.0, FLOOR_MATS[rid])
            m.box(lx1, x1, z0, z1, -0.3, 0.0, FLOOR_MATS[rid])
            m.box(lx0, lx1, lz1, z1, -0.3, 0.0, FLOOR_MATS[rid])
        else:
            m.box(x0, x1, z0, z1, -0.3, 0.0, FLOOR_MATS[rid])
        tag(m.build(f"SM_Ops_Floor_{rid}", bevel=0.003), nav="walk", room=rid)
    m = Mesh().box(3.0, 93.0, L.CORR_N, L.CORR_S, -0.3, 0.0, "M_Floor_GlossBlack")
    tag(m.build("SM_Ops_Floor_corridor", bevel=0.003), nav="walk", room="corridor")
    # Door gaps through the med wall belong to the floor of the rooms either side.
    for key, (x, w) in L.DOORS_MED.items():
        m = Mesh().box(
            x - w / 2, x + w / 2, L.MED_WALL[0], L.MED_WALL[1], -0.3, 0.0, "M_Floor_SatinDark"
        )
        tag(m.build(f"SM_Ops_Floor_door_{key}", bevel=0.002), nav="walk", room="medbay")


# ---------------------------------------------------------------- walls


def _panel_face(m: Mesh, x0, x1, z, h0, h1, grid_x0=0.0, seam=0.007, mat=PAINT):
    """Panel skin on a camera-facing wall face at z: 1.2 m panels with real
    seams (gaps over the dark core), a dark kick plate below h0."""
    m.box(x0, x1, z - 0.01, z + 0.012, 0.0, min(h0, h1), PAINT_DARK)
    k0 = math.floor((x0 - grid_x0) / M)
    k1 = math.ceil((x1 - grid_x0) / M)
    for k in range(k0, k1):
        a = max(x0, grid_x0 + k * M + seam / 2)
        b = min(x1, grid_x0 + (k + 1) * M - seam / 2)
        if b - a > 0.02:
            m.box(a, b, z - 0.01, z + SKIN, h0, h1, mat)


def ew_wall(
    name: str,
    x0: float,
    x1: float,
    za: float,
    zb: float,
    holes: list[tuple[float, float]],
    *,
    top: float = L.ROOM_H,
    door_h: float = 2.5,
    face_panels: bool = True,
    upper_lights: bool = True,
) -> None:
    """East-west wall between z = za (north face) and zb (south face, the one
    the camera sees), cut at 1.1 m, with door holes (x spans)."""
    low, up, frame, light, sill = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    for a, b in L.solid_spans(x0, x1, holes):
        low.box(a, b, za, zb - 0.01, 0.0, CUT_H, CAP)
        if face_panels:
            _panel_face(low, a, b, zb, 0.14, CUT_H)
        up.box(a, b, za, zb, CUT_H, top, PAINT_MID)
        if upper_lights:
            # Wall-washer valance (seen only mirrored in the floor).
            up.box(a, b, zb, zb + 0.28, top - 0.42, top - 0.3, STEEL)
            light.quad_h(
                a + 0.1, b - 0.1, zb + 0.04, zb + 0.24, top - 0.425, "M_Light_WallStrip", up=False
            )
            _panel_face(up, a, b, zb, CUT_H + 0.01, top - 0.45)
    for a, b in holes:
        if b <= x0 or a >= x1:
            continue
        up.box(a, b, za, zb, door_h, top, PAINT_MID)
        for xa, xb in ((a - 0.14, a), (b, b + 0.14)):
            frame.box(xa, xb, za - 0.03, zb + 0.04, 0.0, CUT_H + 0.01, STEEL)
            up.box(xa, xb, za - 0.03, zb + 0.04, CUT_H + 0.01, door_h + 0.14, STEEL)
        up.box(a - 0.14, b + 0.14, za - 0.03, zb + 0.04, door_h, door_h + 0.14, STEEL)
        # Threshold plate with the door track (flush: never a nav obstacle).
        sill.box(a, b, za, zb, 0.0005, 0.006, "M_Trim_BrushedSteel")
        sill.box(a, b, (za + zb) / 2 - 0.03, (za + zb) / 2 + 0.03, 0.0005, 0.007, RECESS)
    tag(low.build(f"SM_Ops_Wall_{name}", bevel=0.006), nav="block")
    tag(sill.build(f"SM_Ops_DoorSill_{name}", bevel=0.002), nav="none")
    tag(frame.build(f"SM_Ops_DoorFrame_{name}", bevel=0.008), nav="block")
    up.build(f"SM_Ops_WallUpper_{name}", "Ceiling", bevel=0.0)
    light.build(f"SM_Ops_WallWash_{name}", "Ceiling", bevel=0.0, shadow=False, keep_normals=True)


def ns_wall(name: str, x0: float, x1: float, z0: float, z1: float, top: float = L.ROOM_H):
    """North-south wall: seen edge-on, so only its cut cap matters to the camera."""
    low, up = Mesh(), Mesh()
    low.box(x0, x1, z0, z1, 0.0, CUT_H - 0.012, PAINT)
    low.box(x0 - 0.005, x1 + 0.005, z0, z1, CUT_H - 0.012, CUT_H, CAP)
    up.box(x0, x1, z0, z1, CUT_H, top, PAINT_MID)
    tag(low.build(f"SM_Ops_Wall_{name}", bevel=0.004), nav="block")
    up.build(f"SM_Ops_WallUpper_{name}", "Ceiling", bevel=0.0)


# ---------------------------------------------------------------- hero wall


def hero_wall_body(cavities=()) -> None:
    """The far hull wall's structural mass and cornice. The facade bays in
    front of it are dressed per room by ``facade.py``; ``cavities`` are the
    (x0, x1, h0, h1) openings behind its viewport slits."""
    m = Mesh()
    hz = L.HERO_Z
    xs = [(-2.0, 98.0)]
    # The hull body stops at the room ceiling: above it the camera looks into
    # an open cornice gallery (deck beams, pipe runs, maintenance lamps), so
    # the top edge of the plate is lit ship structure, never a black slab.
    top = L.ROOM_H
    for x0, x1, h0, h1 in cavities:
        m.box(x0, x1, -3.0, hz - 0.12, -0.6, h0 - 0.12, "M_Hull_Structure")
        m.box(x0, x1, -3.0, hz - 0.12, h1 + 0.12, top, "M_Hull_Structure")
        m.box(x0, x1, -3.0, hz - 1.6, h0 - 0.12, h1 + 0.12, "M_Hull_Structure")
    holes = [(x0, x1) for x0, x1, _, _ in cavities]
    for a, b in L.solid_spans(xs[0][0], xs[0][1], holes):
        m.box(a, b, -3.0, hz - 0.12, -0.6, top, "M_Hull_Structure")
    # Cornice: the cut ceiling structure seen from above.
    m.box(-2.0, 98.0, -3.0, hz + 0.32, L.ROOM_H, L.ROOM_H + 0.18, STEEL)
    m.box(-2.0, 98.0, hz + 0.24, hz + 0.32, L.ROOM_H - 0.22, L.ROOM_H, STEEL)
    tag(m.build("SM_Ops_HullFar", bevel=0.01), nav="block")
    _cornice_gallery()


def _cornice_gallery() -> None:
    """Open structure on top of the far hull wall: I-section deck beams every
    2.4 m, pipe runs and a cable tray along the ship, caged maintenance lamps
    on every second beam (every third one red)."""
    hz, base = L.HERO_Z, L.ROOM_H + 0.18
    beams, pipes, lamps = Mesh(), Mesh(), Mesh()
    deck = "M_Hull_Structure"
    for k in range(0, 41):
        x = -0.6 + 2.4 * k
        beams.box(x - 0.025, x + 0.025, -2.6, hz + 0.22, base, L.HULL_H - 0.06, STEEL)
        beams.box(x - 0.13, x + 0.13, -2.6, hz + 0.22, L.HULL_H - 0.06, L.HULL_H, STEEL)
        beams.box(x - 0.11, x + 0.11, -2.6, hz + 0.22, base, base + 0.05, STEEL)
        # Bracket where the beam lands on the cornice face.
        beams.box(x - 0.09, x + 0.09, hz - 0.1, hz + 0.28, base, base + 0.42, deck)
    # Longitudinal stringer and a tread plate for the maintenance crews.
    beams.box(-2.0, 98.0, -0.55, -0.42, base, base + 0.62, STEEL)
    beams.box(-2.0, 98.0, -0.3, 0.3, base, base + 0.02, "M_Floor_Grating")
    runs = (
        (-0.8, 0.11, "M_Hull_Pipe", 0.0),
        (-0.2, 0.06, "M_Trim_BrushedSteel", 0.22),
        (0.62, 0.14, "M_Hull_PipeInsulated", 0.0),
        (1.05, 0.05, "M_Trim_BrushedSteel", 0.3),
        (1.32, 0.07, "M_Hull_Pipe", 0.1),
    )
    for dz, r, mat, lift in runs:
        hh = base + r + 0.04 + lift
        pipes.tube((-2.0, dz, hh), (98.0, dz, hh), r, mat, 16)
    for k in range(0, 41):
        x = -0.6 + 2.4 * k
        # Pipe saddles on every beam.
        pipes.box(x - 0.06, x + 0.06, -0.95, 1.45, base, base + 0.06, STEEL)
    # Supply main along the cornice face.
    pipes.tube(
        (-2.0, 1.85, base + 0.16), (98.0, 1.85, base + 0.16), 0.11, "M_Hull_PipeInsulated", 16
    )
    tag(beams.build("SM_Ops_CorniceBeams", bevel=0.006), nav="none")
    tag(pipes.build("SM_Ops_CornicePipes", bevel=0.0), nav="none")
    k = 0
    cages = Mesh()
    for i in range(1, 41, 2):
        x = -0.6 + 2.4 * i
        red = k % 3 == 2
        mat = "M_Light_Maint_Red" if red else "M_Ops_Light_Maint"
        # Bracket off the beam web, lamp clear of the top flange so it shows.
        cages.box(x + 0.025, x + 0.24, 0.2, 0.3, base + 0.4, base + 0.44, STEEL)
        cages.box(x + 0.13, x + 0.25, 0.1, 0.4, base + 0.27, base + 0.31, STEEL)
        lamps.box(x + 0.145, x + 0.235, 0.13, 0.37, base + 0.31, base + 0.4, mat)
        if red:
            point_light(f"LT_Cornice_{k}", x + 0.5, 0.25, base + 0.36, 5.0, color=(1.0, 0.1, 0.05))
        else:
            point_light(f"LT_Cornice_{k}", x + 0.5, 0.25, base + 0.36, 22.0, kelvin=5000.0)
        k += 1
    tag(cages.build("SM_Ops_CorniceCages", bevel=0.003), nav="none")
    tag(lamps.build("SM_Ops_CorniceLamps", bevel=0.0), nav="none")
    # Dim cool spill from the deck above, so the beams and pipes between the
    # lamps keep their shape (never seen, never mirrored).
    area_light("LT_CorniceSpill", 48.0, 0.9, L.HULL_H + 0.9, 100.0, 3.2, 480.0, kelvin=6000.0)


# ---------------------------------------------------------------- corridor


def _slope_pts(north: bool):
    """Corridor lower wall line: foot on the floor edge, top at the upper wall."""
    if north:
        return (L.CORR_FLOOR[0], 0.0), (L.CORR_FLOOR[0] - L.SLOPE_RUN, L.SLOPE_TOP)
    return (L.CORR_FLOOR[1], 0.0), (L.CORR_FLOOR[1] + L.SLOPE_RUN, L.SLOPE_TOP)


def _on_slope(north: bool, h: float, off: float = 0.0):
    """(z, h) of the slope line at height h, pushed `off` metres out of the wall."""
    (za, _), (zb, hb) = _slope_pts(north)
    z = za + (zb - za) * h / hb
    run, rise = abs(zb - za), hb
    n = math.hypot(run, rise)
    nz, nh = rise / n, run / n  # outward normal (into the corridor, up)
    sign = 1.0 if north else -1.0
    return (z + sign * nz * off, h + nh * off)


def corridor() -> None:
    holes_n = L.door_spans(L.DOORS_NORTH)
    holes_s = L.door_spans(L.DOORS_SOUTH)
    x0, x1 = 3.0, 93.0
    for north, holes in ((True, holes_n), (False, holes_s)):
        side = "N" if north else "S"
        wall_face = L.CORR_N if north else L.CORR_S
        (zf, _), (zt, ht) = _slope_pts(north)
        zc = _on_slope(north, CUT_H)[0]
        ch = 0.9 if north else -0.9
        inner = _on_slope(north, 0.0, -0.022)
        inner_cut = _on_slope(north, CUT_H, -0.022)
        low, up, panels, lights, frames, sill = Mesh(), Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
        for a, b in L.solid_spans(x0, x1, holes):
            # Core: section cap on top, dark behind the panel skin.
            prof = [(wall_face, 0.0), inner, inner_cut, (wall_face, CUT_H)]
            low.prism_x(prof, a, b, RECESS, side_mats={2: CAP})
            if not north:
                _panel_face(panels, a, b, wall_face, 0.14, CUT_H)
            _slope_panels(panels, lights, north, a, b)
            up_prof = [
                (wall_face, CUT_H),
                (zc, CUT_H),
                (zt, ht),
                (zt, L.CHAMFER_LOW),
                (zt + ch, L.CORR_H),
                (zt + ch, L.ROOM_H),
                (wall_face, L.ROOM_H),
            ]
            up.prism_x(up_prof, a, b, PAINT_MID)
            _upper_wall_detail(up, lights, north, a, b)
            if not north:
                # The quarters / ready rooms see this face mirrored too.
                up.box(a, b, wall_face, wall_face + 0.28, L.ROOM_H - 0.42, L.ROOM_H - 0.3, STEEL)
                lights.quad_h(
                    a + 0.1,
                    b - 0.1,
                    wall_face + 0.04,
                    wall_face + 0.24,
                    L.ROOM_H - 0.425,
                    "M_Light_WallStrip",
                    up=False,
                )
                _panel_face(up, a, b, wall_face, CUT_H + 0.01, L.ROOM_H - 0.45)
        for a, b in holes:
            if north:
                zn, zs = wall_face, L.CORR_FLOOR[0]
            else:
                zn, zs = L.CORR_FLOOR[1], wall_face
            up_prof = [
                (wall_face, 2.5),
                (zt, 2.5),
                (zt, L.CHAMFER_LOW),
                (zt + ch, L.CORR_H),
                (zt + ch, L.ROOM_H),
                (wall_face, L.ROOM_H),
            ]
            up.prism_x(up_prof, a, b, PAINT_MID)
            for xa, xb in ((a - 0.16, a), (b, b + 0.16)):
                frames.box(xa, xb, zn - 0.03, zs + 0.03, 0.0, CUT_H + 0.012, STEEL)
                up.box(xa, xb, zn - 0.03, zs + 0.03, CUT_H + 0.012, 2.64, STEEL)
            up.box(a - 0.16, b + 0.16, zn - 0.03, zs + 0.03, 2.5, 2.64, STEEL)
            sill.box(a, b, zn, zs, 0.0005, 0.006, "M_Trim_BrushedSteel")
            zm = (zn + zs) / 2
            sill.box(a, b, zm - 0.03, zm + 0.03, 0.0005, 0.007, RECESS)
            # Door status lamps on the jambs' corridor faces.
            for xa in (a - 0.1, b + 0.04):
                frames.box(
                    xa,
                    xa + 0.06,
                    zs + 0.03,
                    zs + 0.045,
                    0.82,
                    0.9,
                    "M_Indicator_Green" if north else "M_Indicator_Amber",
                )
        tag(low.build(f"SM_Ops_CorridorWall_{side}", bevel=0.004), nav="block")
        tag(panels.build(f"SM_Ops_CorridorPanels_{side}", bevel=0.006), nav="block")
        tag(frames.build(f"SM_Ops_CorridorDoors_{side}", bevel=0.008), nav="block")
        tag(sill.build(f"SM_Ops_CorridorSills_{side}", bevel=0.002), nav="none")
        up.build(f"SM_Ops_CorridorUpper_{side}", "Ceiling", bevel=0.0)
        lights.build(
            f"SM_Ops_CorridorLights_{side}", "Ceiling", bevel=0.0, shadow=False, keep_normals=True
        )
        _visible_slope_lights(north, holes)
        _slope_ribs(north, holes)
    _corridor_ceiling()
    for x in L.BLAST_FRAMES:
        blast_frame(x, closed=False)
    for x in L.END_PORTALS:
        blast_frame(x, closed=True)
    _corridor_markings()


def _slope_panels(panels: Mesh, lights: Mesh, north: bool, a: float, b: float) -> None:
    """Sloped lower wall: 1.2 m panels with real seams, kick strip at the foot."""
    foot0, foot1 = _on_slope(north, 0.0, -0.01), _on_slope(north, 0.13, 0.012)
    kick = [foot0, _on_slope(north, 0.0, 0.012), foot1, _on_slope(north, 0.13, -0.01)]
    panels.prism_x(kick, a, b, PAINT_DARK)
    p0, p1 = _on_slope(north, 0.135, -0.01), _on_slope(north, CUT_H, -0.01)
    q0, q1 = _on_slope(north, 0.135, 0.012), _on_slope(north, CUT_H, 0.012)
    k0, k1 = math.floor(a / M), math.ceil(b / M)
    for k in range(k0, k1):
        pa, pb = max(a, k * M + 0.004), min(b, (k + 1) * M - 0.004)
        if pb - pa < 0.05:
            continue
        panels.prism_x([p0, q0, q1, p1], pa, pb, PAINT, side_mats={2: CAP})


def _slope_ribs(north: bool, holes) -> None:
    """Structural ribs every 4.8 m: steel strips over the sloped lower wall."""
    ribs = Mesh()
    for k in range(1, 20):
        xc = 4.8 * k
        if any(ha - 0.4 < xc < hb + 0.4 for ha, hb in holes):
            continue
        if any(abs(xc - fx) < 1.4 for fx in (*L.BLAST_FRAMES, *L.END_PORTALS)):
            continue
        p = [
            _on_slope(north, 0.0, 0.0),
            _on_slope(north, 0.0, 0.06),
            _on_slope(north, CUT_H, 0.06),
            _on_slope(north, CUT_H, 0.0),
        ]
        ribs.prism_x(p, xc - 0.09, xc + 0.09, STEEL, side_mats={2: CAP})
    tag(ribs.build(f"SM_Ops_SlopeRibs_{'N' if north else 'S'}", bevel=0.01), nav="block")


def _visible_slope_lights(north: bool, holes) -> None:
    """Wall-light columns in the sloped lower walls, one unit per 2.4 m bay:
    a dark recessed housing with three columns of stacked pill lamps (the
    hero-wall motif brought down below the 1.1 m cut)."""
    housing, emit = Mesh(), Mesh()
    pattern = (0.16, 0.08, 0.16, 0.16, 0.08)
    for k in range(2, 39):
        xc = 2.4 * k
        a, b = xc - 0.22, xc + 0.22
        if any(ha - 0.4 < b and hb + 0.4 > a for ha, hb in holes):
            continue
        if any(abs(xc - fx) < 1.2 for fx in (*L.BLAST_FRAMES, *L.END_PORTALS)):
            continue
        s0, s1 = _on_slope(north, 0.18, 0.008), _on_slope(north, 1.04, 0.008)
        t0, t1 = _on_slope(north, 0.18, 0.016), _on_slope(north, 1.04, 0.016)
        housing.prism_x([s0, t0, t1, s1], a, b, RECESS)
        for col, dx in enumerate((-0.11, 0.0, 0.11)):
            hh = 0.24 + (0.06 if col == 1 else 0.0)
            i = col
            while True:
                ln = pattern[i % len(pattern)]
                if hh + ln > 1.0:
                    break
                e0, e1 = _on_slope(north, hh, 0.017), _on_slope(north, hh + ln, 0.017)
                e0b, e1b = _on_slope(north, hh, 0.026), _on_slope(north, hh + ln, 0.026)
                emit.prism_x(
                    [e0, e0b, e1b, e1], xc + dx - 0.022, xc + dx + 0.022, "M_Light_WallStrip"
                )
                hh += ln + 0.05
                i += 1
    side = "N" if north else "S"
    tag(housing.build(f"SM_Ops_SlopeLightHousing_{side}", bevel=0.004), nav="block")
    tag(emit.build(f"SM_Ops_SlopeLight_{side}", bevel=0.012, segments=3), nav="block")


def _upper_wall_detail(up: Mesh, lights: Mesh, north: bool, a: float, b: float) -> None:
    """Upper corridor wall (seen only mirrored): vertical slot-light columns
    every 2.4 m and a continuous strip along the chamfer."""
    (_, _), (zt, ht) = _slope_pts(north)
    face = zt + (0.0 if north else 0.0)
    out = 0.012 if north else -0.012
    for k in range(math.ceil(a / 2.4), math.floor(b / 2.4) + 1):
        xc = 2.4 * k
        if xc - 0.4 < a or xc + 0.4 > b:
            continue
        if any(abs(xc - fx) < 1.2 for fx in (*L.BLAST_FRAMES, *L.END_PORTALS)):
            continue
        zlo, zhi = sorted((face, face + out * 2))
        up.box(xc - 0.3, xc + 0.3, zlo, zhi, ht + 0.2, L.CHAMFER_LOW - 0.15, RECESS)
        for col, dx in enumerate((-0.12, 0.12)):
            for r in range(5):
                hh = ht + 0.35 + r * 0.36 + (0.18 if col else 0.0)
                if hh + 0.26 > L.CHAMFER_LOW - 0.2:
                    continue
                zl, zh = sorted((face + out * 2, face + out * 3))
                lights.box(
                    xc + dx - 0.035, xc + dx + 0.035, zl, zh, hh, hh + 0.26, "M_Light_WallStrip"
                )
    # Chamfer strip.
    zc0 = zt + (0.42 if north else -0.42)
    hc0 = L.CHAMFER_LOW + 0.42
    d = 0.02 if north else -0.02
    e = 0.06 if north else -0.06
    lights.quad(
        [
            (a, zc0 + d, hc0 - 0.03),
            (b, zc0 + d, hc0 - 0.03),
            (b, zc0 + d + e, hc0 + 0.03),
            (a, zc0 + d + e, hc0 + 0.03),
        ],
        "M_Light_WallStrip",
    )


def _corridor_ceiling() -> None:
    zn = L.CORR_FLOOR[0] - L.SLOPE_RUN + 0.9
    zs = L.CORR_FLOOR[1] + L.SLOPE_RUN - 0.9
    slab, bezel = Mesh(), Mesh()
    slab.box(3.0, 93.0, zn - 0.05, zs + 0.05, L.CORR_H, L.CORR_H + 0.3, "M_Ceiling_Panel")
    panels = Mesh()
    for k in range(2, 39):
        xc = 2.4 * k
        if any(abs(xc - fx) < 1.2 for fx in (*L.BLAST_FRAMES, *L.END_PORTALS)):
            continue
        for z0, z1 in ((28.35, 29.25), (30.75, 31.65)):
            bezel.box(xc - 0.88, xc + 0.88, z0 - 0.08, z1 + 0.08, L.CORR_H - 0.03, L.CORR_H, STEEL)
            panels.quad_h(
                xc - 0.8, xc + 0.8, z0, z1, L.CORR_H - 0.032, "M_Ops_Light_Corridor", up=False
            )
        # Ribs between the panels.
        bezel.box(xc + 1.15, xc + 1.25, zn, zs, L.CORR_H - 0.08, L.CORR_H, STEEL)
    slab.build("SM_Ops_CorridorCeiling", "Ceiling", bevel=0.0)
    bezel.build("SM_Ops_CorridorCeilingBezels", "Ceiling", bevel=0.004)
    o = panels.build(
        "SM_Ops_CorridorCeilingLights", "Ceiling", bevel=0.0, shadow=False, keep_normals=True
    )
    o.visible_shadow = False


FRAME_CUT_N = 3.0  # the north jamb faces the camera: it stands above the wall cut
FRAME_CUT_S = CUT_H  # the south jamb has corridor behind it: cut like the wall


def blast_frame(xc: float, closed: bool) -> None:
    """A pressure frame across the corridor in the plane x = xc.

    The section plane cuts it: the north jamb, whose inner face looks at the
    camera, stands to 3.0 m with a dotted line of white lamps; the south jamb
    is cut at 1.1 m like the wall it sits in; the header and everything above
    the cut live in the Ceiling collection (seen only in the floor mirror),
    so the frame never hides a walking crew member.
    """
    d = L.FRAME_DEPTH / 2
    a, b = xc - d, xc + d
    n_face, s_face = L.CORR_N - 0.05, L.CORR_S + 0.05
    north_full = [
        (n_face, 0.0),
        (28.05, 0.0),
        (27.5, 1.1),
        (27.5, 3.0),
        (28.3, 3.8),
        (28.3, 4.45),
        (n_face, 4.45),
    ]
    south_full = [
        (s_face, 0.0),
        (31.95, 0.0),
        (32.5, 1.1),
        (32.5, 3.0),
        (31.7, 3.8),
        (31.7, 4.45),
        (s_face, 4.45),
    ]
    north_low = [
        (n_face, 0.0),
        (28.05, 0.0),
        (27.5, 1.1),
        (27.5, FRAME_CUT_N),
        (n_face, FRAME_CUT_N),
    ]
    south_low = [(s_face, 0.0), (31.95, 0.0), (32.5, FRAME_CUT_S), (s_face, FRAME_CUT_S)]
    north_up = [
        (n_face, FRAME_CUT_N),
        (27.5, FRAME_CUT_N),
        (28.3, 3.8),
        (28.3, 4.45),
        (n_face, 4.45),
    ]
    south_up = [
        (s_face, FRAME_CUT_S),
        (32.5, FRAME_CUT_S),
        (32.5, 3.0),
        (31.7, 3.8),
        (31.7, 4.45),
        (s_face, 4.45),
    ]
    del north_full, south_full
    m, up, trim, lamps = Mesh(), Mesh(), Mesh(), Mesh()
    for prof, cap_edge in ((north_low, 3), (south_low, 2)):
        m.prism_x(prof, a + 0.08, b - 0.08, PAINT, side_mats={cap_edge: CAP})
        m.prism_x(prof, a, a + 0.08, STEEL, side_mats={cap_edge: CAP})
        m.prism_x(prof, b - 0.08, b, STEEL, side_mats={cap_edge: CAP})
    for prof in (north_up, south_up):
        up.prism_x(prof, a, b, PAINT)
    up.box(a, b, 28.3, 31.7, 3.8, 4.45, PAINT)
    # Lit edge: a dotted line of small white lamps up the camera-facing jamb.
    pip = "M_Ops_Light_Pip"
    for dx in (-0.42, 0.42):
        hh = 1.2
        while hh < FRAME_CUT_N - 0.1:
            lamps.box(xc + dx - 0.02, xc + dx + 0.02, 27.49, 27.505, hh, hh + 0.04, pip)
            hh += 0.15
        for k in range(6):
            t = (k + 0.5) / 6
            zz, h2 = 28.05 + (27.5 - 28.05) * t, 1.1 * t
            lamps.box(
                xc + dx - 0.02, xc + dx + 0.02, zz - 0.012, zz + 0.004, h2 - 0.02, h2 + 0.02, pip
            )
    # Retracted-leaf pocket: a dark slot up the jamb face.
    trim.box(xc - 0.05, xc + 0.05, 27.48, 27.5, 0.05, FRAME_CUT_N - 0.02, RECESS)
    haz = Mesh()
    haz.box(xc - 0.05, xc + 0.05, 28.05, 31.95, 0.0005, 0.008, RECESS)
    for s in (-1, 1):
        haz.quad_h(xc + s * 0.14, xc + s * 0.3, 28.1, 31.9, 0.0015, "M_Deck_Hazard")
    if closed:
        leaf, leaf_up = Mesh(), Mesh()
        leaf.box(xc - 0.06, xc + 0.06, n_face, s_face, 0.0, FRAME_CUT_N - 0.01, PAINT_DARK)
        leaf.box(xc - 0.065, xc + 0.065, n_face, s_face, FRAME_CUT_N - 0.01, FRAME_CUT_N, CAP)
        for k in range(7):
            z = 28.2 + k * 0.58
            leaf.box(xc - 0.075, xc + 0.075, z, z + 0.04, 0.0, FRAME_CUT_N - 0.01, STEEL)
        leaf_up.box(xc - 0.06, xc + 0.06, n_face, s_face, FRAME_CUT_N, 4.45, PAINT_DARK)
        tag(leaf.build(f"SM_Ops_BlastDoor_{xc:.0f}", bevel=0.006), nav="block")
        leaf_up.build(f"SM_Ops_BlastDoorUpper_{xc:.0f}", "Ceiling", bevel=0.0)
    tag(m.build(f"SM_Ops_BlastFrame_{xc:.0f}", bevel=0.012), nav="block")
    up.build(f"SM_Ops_BlastFrameUpper_{xc:.0f}", "Ceiling", bevel=0.0)
    tag(trim.build(f"SM_Ops_BlastFrameTrim_{xc:.0f}", bevel=0.004), nav="none")
    lamp_obj = lamps.build(f"SM_Ops_BlastFrameLamps_{xc:.0f}", bevel=0.0, keep_normals=True)
    tag(lamp_obj, nav="none")
    tag(haz.build(f"SM_Ops_BlastHazard_{xc:.0f}", bevel=0.0), nav="none")


def _corridor_markings() -> None:
    """Worn white lane edges and direction chevrons between the frames."""
    paint = Mesh()
    zn, zs = L.CORR_FLOOR[0] + 0.35, L.CORR_FLOOR[1] - 0.35
    stops = sorted((*L.BLAST_FRAMES, *L.END_PORTALS))
    for a, b in zip(stops[:-1], stops[1:], strict=True):
        a, b = a + 1.0, b - 1.0
        for z in (zn, zs):
            paint.quad_h(a, b, z - 0.03, z + 0.03, 0.0015, "M_Deck_Marking_White")
    tag(paint.build("SM_Ops_CorridorMarkings", bevel=0.0), nav="none")


# ---------------------------------------------------------------- chases


def chases() -> None:
    for i, (x0, x1) in enumerate(L.CHASES_NORTH):
        _chase(f"N{i}", x0, x1, L.HERO_Z, L.CORR_N)
    for i, (x0, x1) in enumerate(L.CHASES_SOUTH):
        _chase(f"S{i}", x0, x1, L.CORR_S, L.NEAR_Z)
    _chase("LS", *L.LOBBY_STORE_CHASE, L.CORR_S, L.MED_WALL[0])


def _chase(name: str, x0: float, x1: float, z0: float, z1: float) -> None:
    """Two wall skins with a service trench between them, seen from above."""
    t = L.WALL_T
    ns_wall(f"Chase{name}_W", x0, x0 + t, z0, z1)
    ns_wall(f"Chase{name}_E", x1 - t, x1, z0, z1)
    trench(f"Chase{name}", x0 + t, x1 - t, z0, z1, along="z")


def trench(
    name: str,
    x0: float,
    x1: float,
    z0: float,
    z1: float,
    along: str = "z",
    floor_h: float = -0.55,
    lamp_every: float = 7.2,
) -> None:
    """Service trench: grating floor, frames every 1.2 m, pipe and cable runs,
    dim red maintenance lamps. Never walkable."""
    m, pipes, lamps = Mesh(), Mesh(), Mesh()
    m.box(x0, x1, z0, z1, floor_h - 0.06, floor_h, "M_Floor_Grating")
    w = x1 - x0
    if along == "z":
        n = int((z1 - z0) / M)
        for k in range(n + 1):
            z = z0 + k * (z1 - z0) / max(n, 1)
            m.box(x0, x1, z - 0.04, z + 0.04, floor_h, floor_h + 0.18, STEEL)
            if k % 2 == 0:
                m.box(x0, x0 + 0.06, z - 0.05, z + 0.05, floor_h, 0.95, STEEL)
                m.box(x1 - 0.06, x1, z - 0.05, z + 0.05, floor_h, 0.95, STEEL)
        runs = [
            (x0 + w * 0.22, floor_h + 0.3, min(0.11, w * 0.1), "M_Hull_PipeInsulated"),
            (x0 + w * 0.5, floor_h + 0.22, min(0.07, w * 0.07), "M_Hull_Pipe"),
            (x0 + w * 0.72, floor_h + 0.36, min(0.08, w * 0.08), "M_Hull_Pipe"),
            (x0 + w * 0.36, floor_h + 0.62, 0.035, "M_Trim_BrushedSteel"),
        ]
        for x, hh, r, mat in runs:
            pipes.tube((x, z0, hh), (x, z1, hh), r, mat, 14)
        # Cable tray on the east skin.
        m.box(x1 - 0.32, x1 - 0.06, z0, z1, 0.55, 0.58, "M_Floor_Grating")
        for k in range(int((z1 - z0) / 2.4) + 1):
            z = z0 + 1.2 + k * 2.4
            if z < z1:
                pipes.tube(
                    (x0 + w * 0.22, z - 0.12, floor_h + 0.3),
                    (x0 + w * 0.22, z + 0.12, floor_h + 0.3),
                    min(0.13, w * 0.12),
                    STEEL,
                    14,
                )
        z = z0 + lamp_every / 2
        k = 0
        while z < z1 - 1.0:
            red = k % 3 == 1
            mat = "M_Light_Maint_Red" if red else "M_Ops_Light_Maint"
            lamps.box(x0 + 0.07, x0 + 0.15, z - 0.12, z + 0.12, 0.62, 0.72, mat)
            m.box(x0 + 0.06, x0 + 0.16, z - 0.14, z + 0.14, 0.72, 0.76, STEEL)
            if red:
                point_light(f"LT_{name}_{k}", x0 + 0.3, z, 0.55, 2.5, color=(1.0, 0.1, 0.05))
            else:
                point_light(f"LT_{name}_{k}", x0 + 0.3, z, 0.55, 6.0, kelvin=4000.0)
            z += lamp_every
            k += 1
    else:
        n = int((x1 - x0) / M)
        d = z1 - z0
        for k in range(n + 1):
            x = x0 + k * (x1 - x0) / max(n, 1)
            m.box(x - 0.04, x + 0.04, z0, z1, floor_h, floor_h + 0.18, STEEL)
        for zz, hh, r, mat in (
            (z0 + d * 0.25, floor_h + 0.3, min(0.12, d * 0.1), "M_Hull_PipeInsulated"),
            (z0 + d * 0.55, floor_h + 0.24, min(0.08, d * 0.07), "M_Hull_Pipe"),
            (z0 + d * 0.78, floor_h + 0.34, min(0.07, d * 0.07), "M_Hull_Pipe"),
        ):
            pipes.tube((x0, zz, hh), (x1, zz, hh), r, mat, 14)
        x = x0 + lamp_every / 2
        k = 0
        while x < x1 - 1.0:
            lamps.box(x - 0.12, x + 0.12, z0 + 0.07, z0 + 0.15, 0.62, 0.72, "M_Ops_Light_Maint")
            point_light(f"LT_{name}_{k}", x, z0 + 0.3, 0.5, 5.0, kelvin=4000.0)
            x += lamp_every
            k += 1
    tag(m.build(f"SM_Ops_Trench_{name}", bevel=0.005), nav="none")
    tag(pipes.build(f"SM_Ops_TrenchPipes_{name}", bevel=0.0), nav="none")
    if not lamps.mb.is_empty():
        tag(lamps.build(f"SM_Ops_TrenchLamps_{name}", bevel=0.0), nav="none")


# ---------------------------------------------------------------- other walls


def near_wall() -> None:
    """The near hull wall (z 58..60), cut at 1.1 m: two skins with a service
    gallery between them (frames, pipe runs, caged maintenance lamps), so the
    bottom edge of the plate reads as lit hull structure, not a flat band."""
    z0, z1 = L.NEAR_Z, L.NEAR_Z + 2.0
    t = 0.3
    m = Mesh()
    for za, zb in ((z0, z0 + t), (z1 - t, z1)):
        m.box(2.4, 93.6, za, zb, -0.6, CUT_H - 0.012, PAINT_DARK)
        m.box(2.4, 93.6, za, zb, CUT_H - 0.012, CUT_H, CAP)
    tag(m.build("SM_Ops_Wall_Near", bevel=0.005), nav="block")
    up = Mesh().box(2.4, 93.6, z0, z1, CUT_H, L.ROOM_H, PAINT_MID)
    up.build("SM_Ops_WallUpper_Near", "Ceiling", bevel=0.0)
    _hull_gallery("Near", 2.7, 93.3, z0 + t, z1 - t)


def _hull_gallery(name: str, x0: float, x1: float, z0: float, z1: float) -> None:
    """Service gallery inside a thick hull wall, running along x."""
    fl = -0.55
    m, pipes, lamps = Mesh(), Mesh(), Mesh()
    m.box(x0, x1, z0, z1, fl - 0.06, fl, "M_Floor_Grating")
    m.box(x0, x1, z0, z0 + 0.012, fl, CUT_H - 0.02, PAINT_MID)  # inner skin lining
    for k in range(math.ceil(x0 / 2.4), math.floor(x1 / 2.4) + 1):
        x = 2.4 * k
        # Open ring frame across the gallery: bottom and top chords and two
        # posts, so the lamps light the run beyond each frame too.
        m.box(x - 0.02, x + 0.02, z0, z1, fl, fl + 0.32, STEEL)
        m.box(x - 0.02, x + 0.02, z0, z1, 0.86, CUT_H - 0.04, STEEL)
        m.box(x - 0.1, x + 0.1, z0, z1, CUT_H - 0.08, CUT_H - 0.04, STEEL)
        for za, zb in ((z0, z0 + 0.12), (z1 - 0.12, z1)):
            m.box(x - 0.02, x + 0.02, za, zb, fl, CUT_H - 0.04, STEEL)
    runs = (
        (z0 + 0.32, fl + 0.36, 0.13, "M_Hull_PipeInsulated"),
        (z0 + 0.72, fl + 0.24, 0.08, "M_Hull_Pipe"),
        (z1 - 0.28, fl + 0.4, 0.09, "M_Hull_Pipe"),
        (z0 + 0.6, 0.62, 0.035, "M_Trim_BrushedSteel"),
    )
    for z, hh, r, mat in runs:
        pipes.tube((x0, z, hh), (x1, z, hh), r, mat, 14)
    # Cable tray on the inner skin.
    m.box(x0, x1, z0 + 0.012, z0 + 0.3, 0.42, 0.44, "M_Floor_Grating")
    for i in range(3):
        z = z0 + 0.06 + i * 0.08
        pipes.tube((x0, z, 0.465), (x1, z, 0.465), 0.02, "M_Rubber_Black", 8)
    x, k = x0 + 1.2, 0
    while x < x1 - 1.0:
        red = k % 3 == 2
        mat = "M_Light_Maint_Red" if red else "M_Ops_Light_Maint"
        m.box(x - 0.15, x + 0.15, z0 + 0.012, z0 + 0.1, 0.66, 0.84, STEEL)
        lamps.box(x - 0.12, x + 0.12, z0 + 0.1, z0 + 0.13, 0.69, 0.81, mat)
        if red:
            point_light(f"LT_{name}Gallery_{k}", x, z0 + 0.45, 0.72, 3.0, color=(1.0, 0.1, 0.05))
        else:
            point_light(f"LT_{name}Gallery_{k}", x, z0 + 0.45, 0.72, 14.0, kelvin=5000.0)
        x += 4.8
        k += 1
    tag(m.build(f"SM_Ops_Gallery_{name}", bevel=0.004), nav="none")
    tag(pipes.build(f"SM_Ops_GalleryPipes_{name}", bevel=0.0), nav="none")
    tag(lamps.build(f"SM_Ops_GalleryLamps_{name}", bevel=0.0), nav="none")


def med_wall() -> None:
    holes = L.door_spans(L.DOORS_MED)
    ew_wall("Med", 71.0, 93.0, L.MED_WALL[0], L.MED_WALL[1], holes)


def side_hulls() -> None:
    """Hull structure strips at the deck's west and east edges."""
    ns_wall("HullW_skin", 2.7, 3.0, L.HERO_Z, L.NEAR_Z)
    ns_wall("HullE_skin", 93.0, 93.3, L.HERO_Z, L.NEAR_Z)
    # Open hull framing (kit bays, all below deck level) along both edges and
    # the near edge; a deck-edge coping where the rooms stop.
    with kit.into(collection("Architecture")):
        # Bays stop exactly on the 2.4 m grid so no rib flange (top at deck
        # level) ever lies coplanar under a room floor.
        hull.fill_hull("HullW", (-2.4, 2.4), (-62.4, -L.HERO_Z), lamp_every=3)
        hull.fill_hull("HullE", (93.6, 98.4), (-62.4, -L.HERO_Z), lamp_every=3)
        hull.fill_hull("HullN", (2.4, 93.6), (-62.4, -60.0), lamp_every=3)
    edge = Mesh()
    for xa, xb in ((2.4, 2.7), (93.3, 93.6)):
        edge.box(xa, xb, L.HERO_Z, L.NEAR_Z + 2.0, -0.6, 0.02, STEEL)
    tag(edge.build("SM_Ops_HullEdges", bevel=0.01), nav="none")
    _hull_edge_lamps()


# (facing, rib x, z offset): the open ribs at x = 0 / 96, the deck-edge copings
# at x = 2.4 / 93.6, staggered so the lamps zig-zag every 2.4 m.
_EDGE_RIBS = ((1.0, 0.0, 0.0), (-1.0, 96.0, 0.0), (-1.0, 2.4, 2.4), (1.0, 93.6, 2.4))


def _hull_edge_lamps() -> None:
    """Caged maintenance lamps hung on the first open rib inside each side
    hull strip (x = 0 and x = 96), every 4.8 m along the ship, every third
    one red: they pick the frames, pipe runs and tank top out of the dark."""
    lamps, cages = Mesh(), Mesh()
    k = 0
    z = L.HERO_Z + 1.4
    while z < L.NEAR_Z + 1.6:
        red = k % 3 == 1
        mat = "M_Light_Maint_Red" if red else "M_Ops_Light_Maint"
        for side, rib, dz in _EDGE_RIBS:
            if z + dz > L.NEAR_Z + 1.6:
                continue
            z_ = z + dz
            xa = rib + side * 0.015
            xb = xa + side * 0.07
            cages.box(min(xa, xb), max(xa, xb), z_ - 0.16, z_ + 0.16, -0.62, -0.42, STEEL)
            xc = xb + side * 0.03
            lamps.box(min(xb, xc), max(xb, xc), z_ - 0.12, z_ + 0.12, -0.58, -0.46, mat)
            lx, name = rib + side * 0.35, f"LT_HullEdge_{rib:.0f}_{k}"
            if red:
                point_light(name, lx, z_, -0.5, 6.0, color=(1.0, 0.1, 0.05))
            else:
                point_light(name, lx, z_, -0.5, 34.0, kelvin=5000.0)
        z += 4.8
        k += 1
    tag(cages.build("SM_Ops_HullEdgeCages", bevel=0.004), nav="none")
    tag(lamps.build("SM_Ops_HullEdgeLamps", bevel=0.0), nav="none")


def lift_core() -> None:
    """Turbolift core: the door wall faces the camera, the shafts behind it
    are open to the section so the car roofs show."""
    x0, x1, z0, z1 = L.LIFT_CORE
    top = 3.4
    m, steel, lamps, doors = Mesh(), Mesh(), Mesh(), Mesh()
    for xa, xb in ((x0, x0 + 0.3), (x1 - 0.3, x1)):
        m.box(xa, xb, z0, z1, 0.0, top - 0.015, PAINT_MID)
        m.box(xa - 0.005, xb + 0.005, z0, z1, top - 0.015, top, CAP)
    m.box((x0 + x1) / 2 - 0.15, (x0 + x1) / 2 + 0.15, z0, z1, 0.0, top - 0.015, PAINT_MID)
    m.box((x0 + x1) / 2 - 0.155, (x0 + x1) / 2 + 0.155, z0, z1, top - 0.015, top, CAP)
    # Door wall: solid around the two openings.
    zf = z1 - 0.3
    holes = [(c - L.LIFT_DOOR_W / 2, c + L.LIFT_DOOR_W / 2) for c in L.LIFT_DOORS]
    for a, b in L.solid_spans(x0, x1, holes):
        m.box(a, b, zf, z1 - SKIN, 0.0, top - 0.015, RECESS)
        _panel_face(m, a, b, z1 - SKIN, 0.14, top - 0.015, grid_x0=x0 + 0.2)
    for a, b in holes:
        m.box(a, b, zf, z1 - SKIN, 2.35, top - 0.015, RECESS)
        _panel_face(m, a, b, z1 - SKIN, 2.35, top - 0.015, grid_x0=a)
    m.box(x0, x1, zf, z1 + 0.01, top - 0.015, top, CAP)
    for a, b in holes:
        # Heavy frame, closed leaves meeting in the middle, lit header band.
        steel.box(a - 0.14, a, z1 - 0.02, z1 + 0.06, 0.0, 2.49, STEEL)
        steel.box(b, b + 0.14, z1 - 0.02, z1 + 0.06, 0.0, 2.49, STEEL)
        steel.box(a - 0.14, b + 0.14, z1 - 0.02, z1 + 0.06, 2.35, 2.49, STEEL)
        mid = (a + b) / 2
        doors.box(a, mid - 0.004, z1 - 0.12, z1 - 0.04, 0.0, 2.35, PAINT)
        doors.box(mid + 0.004, b, z1 - 0.12, z1 - 0.04, 0.0, 2.35, PAINT)
        # Light slots at the meeting edge of the leaves.
        for sx in (-0.05, 0.05):
            lamps.box(
                mid + sx - 0.015,
                mid + sx + 0.015,
                z1 - 0.04,
                z1 - 0.03,
                0.6,
                1.8,
                "M_Light_WallStrip",
            )
        for xa, xb in ((a + 0.12, mid - 0.12), (mid + 0.12, b - 0.12)):
            doors.box(xa, xb, z1 - 0.04, z1 - 0.03, 1.0, 1.06, PAINT_DARK)
        lamps.box(mid - 0.3, mid + 0.3, z1 + 0.06, z1 + 0.075, 2.39, 2.45, "M_Light_WallStrip")
        # Lit ring around the door opening.
        for xa, xb in ((a - 0.2, a - 0.15), (b + 0.15, b + 0.2)):
            lamps.box(xa, xb, z1, z1 + 0.015, 0.05, 2.55, "M_Light_WallStrip")
        lamps.box(a - 0.2, b + 0.2, z1, z1 + 0.015, 2.55, 2.6, "M_Light_WallStrip")
        steel.box(a, b, z1 - 0.3, z1 - 0.12, 0.0, 0.01, "M_Trim_BrushedSteel")
    # Wall-light units on the outer piers: columns of pill lamps.
    pills = Mesh()
    pattern = (0.32, 0.16, 0.32, 0.08, 0.32, 0.16)
    for pa, pb in ((x0, holes[0][0] - 0.14), (holes[-1][1] + 0.14, x1)):
        xc = (pa + pb) / 2
        m.box(xc - 0.2, xc + 0.2, z1, z1 + 0.006, 0.3, 2.9, RECESS)
        for col, dx in enumerate((-0.1, 0.0, 0.1)):
            hh = 0.45 + (0.12 if col == 1 else 0.0)
            i = col * 2
            while True:
                ln = pattern[i % len(pattern)]
                if hh + ln > 2.8:
                    break
                pills.box(
                    xc + dx - 0.02,
                    xc + dx + 0.02,
                    z1 + 0.006,
                    z1 + 0.018,
                    hh,
                    hh + ln,
                    "M_Light_WallStrip",
                )
                hh += ln + 0.04
                i += 1
    pills.build("SM_Ops_LiftPills", bevel=0.018, segments=3, keep_normals=True)
    # Call panel between the doors (the lift station).
    cx = (L.LIFT_DOORS[0] + L.LIFT_DOORS[1]) / 2
    steel.box(cx - 0.16, cx + 0.16, z1, z1 + 0.05, 1.05, 1.45, "M_Console_Body")
    lamps.box(cx - 0.1, cx + 0.1, z1 + 0.05, z1 + 0.058, 1.25, 1.38, "M_Screen")
    lamps.box(cx - 0.05, cx - 0.01, z1 + 0.05, z1 + 0.06, 1.12, 1.16, "M_Indicator_Green")
    lamps.box(cx + 0.01, cx + 0.05, z1 + 0.05, z1 + 0.06, 1.12, 1.16, "M_Indicator_Amber")
    # Shaft interiors: car roofs with hoist gear, rails, cables.
    shaft = Mesh()
    xm = (x0 + x1) / 2
    for i, (a, b) in enumerate(((x0 + 0.3, xm - 0.15), (xm + 0.15, x1 - 0.3))):
        za, zb = z0 + 0.3, zf
        shaft.box(a, b, za, zb, -1.0, -0.9, RECESS)
        shaft.box(a + 0.05, b - 0.05, za + 0.05, zb - 0.05, 2.55, 2.62, PAINT_DARK)
        shaft.box(a + 0.1, b - 0.1, za + 0.1, zb - 0.1, 2.62, 2.66, STEEL)
        cxs, czs = (a + b) / 2, (za + zb) / 2
        shaft.box(cxs - 0.35, cxs + 0.35, czs - 0.25, czs + 0.25, 2.66, 2.92, STEEL)
        shaft.cyl(cxs, czs, 0.22, 2.92, 3.02, "M_Trim_BrushedSteel", 20)
        for dx in (-0.08, 0.0, 0.08):
            shaft.tube((cxs + dx, czs, 3.0), (cxs + dx, czs, 4.6), 0.012, "M_Trim_BrushedSteel", 6)
        for xa in (a + 0.02, b - 0.08):
            shaft.box(xa, xa + 0.06, za, zb, -1.0, 4.6, STEEL)
        shaft.box(a + 0.3, a + 0.5, czs - 0.3, czs - 0.1, 2.66, 2.72, "M_Hull_Pipe")
        lamps.box(
            b - 0.3,
            b - 0.22,
            za + 0.1,
            za + 0.16,
            2.66,
            2.7,
            "M_Indicator_Green" if i == 0 else "M_Indicator_Amber",
        )
    tag(m.build("SM_Ops_LiftCore", bevel=0.006), nav="block")
    tag(steel.build("SM_Ops_LiftFrames", bevel=0.008), nav="block")
    tag(doors.build("SM_Ops_LiftDoors", bevel=0.004), nav="block")
    tag(lamps.build("SM_Ops_LiftLamps", bevel=0.0), nav="none")
    tag(shaft.build("SM_Ops_LiftShafts", bevel=0.004), nav="none")


# ---------------------------------------------------------------- ceiling


def ceiling() -> None:
    """One camera-invisible ceiling slab over the rooms (the corridor has its
    own, lower one); the fixtures are dressed per room."""
    m = Mesh()
    # Starts at the hero wall's face so the lamps of the cornice gallery above
    # the hull wall can light it (the cornice seals the rooms below).
    m.box(-2.0, 98.0, L.HERO_Z, 62.0, L.ROOM_H, L.ROOM_H + 0.3, "M_Ceiling_Panel")
    m.build("SM_Ops_Ceiling", "Ceiling", bevel=0.0)


def ceiling_lights(
    name: str,
    rect,
    *,
    pitch_x=2.4,
    pitch_z=2.4,
    size=(1.2, 0.6),
    mat="M_Light_CeilingPanel",
    h=L.ROOM_H,
    skip=None,
    margin=1.2,
) -> None:
    """A grid of diffuser panels with steel bezels across a room's ceiling."""
    x0, x1, z0, z1 = rect
    bez, em = Mesh(), Mesh()
    nx = max(1, int((x1 - x0 - 2 * margin) / pitch_x) + 1)
    nz = max(1, int((z1 - z0 - 2 * margin) / pitch_z) + 1)
    sx = (x1 - x0 - (nx - 1) * pitch_x) / 2
    sz = (z1 - z0 - (nz - 1) * pitch_z) / 2
    for i in range(nx):
        for j in range(nz):
            cx, cz = x0 + sx + i * pitch_x, z0 + sz + j * pitch_z
            if skip and skip(cx, cz):
                continue
            w, d = size
            bez.box(
                cx - w / 2 - 0.06,
                cx + w / 2 + 0.06,
                cz - d / 2 - 0.06,
                cz + d / 2 + 0.06,
                h - 0.03,
                h,
                STEEL,
            )
            em.quad_h(cx - w / 2, cx + w / 2, cz - d / 2, cz + d / 2, h - 0.032, mat, up=False)
    bez.build(f"SM_Ops_CeilBezels_{name}", "Ceiling", bevel=0.004)
    o = em.build(f"SM_Ops_CeilLights_{name}", "Ceiling", bevel=0.0, shadow=False, keep_normals=True)
    if o is not None:
        o.visible_shadow = False


def emitter(name, x0, x1, z0, z1, h, mat, down=True):
    return emitter_h(name, x0, x1, z0, z1, h, mat, down=down)


def ring_luminaire(
    name: str,
    cx: float,
    cz: float,
    r: float = 2.2,
    h: float = L.ROOM_H,
    mat: str = "M_Light_CeilingPanel",
    fins: bool = True,
) -> None:
    """Staff-room luminaire: a diffuser disc framed by a ring of vertical fins
    (camera-invisible; read in the floor reflection and the light it casts).
    ``fins=False`` leaves a plain ring, so its mirror never reads as a spoked
    emblem."""
    import math as _m

    fins_m, em = Mesh(), Mesh()
    fins_m.cyl(cx, cz, r + 0.12, h - 0.08, h, STEEL, 64)
    n = int(2 * _m.pi * r / 0.12)
    for i in range(n if fins else 0):
        t = 2 * _m.pi * i / n
        x, z = cx + (r + 0.05) * _m.cos(t), cz + (r + 0.05) * _m.sin(t)
        fins_m.box(x - 0.025, x + 0.025, z - 0.025, z + 0.025, h - 0.6, h - 0.08, PAINT)
    # A lit annulus (the diffuser band inside the fins): mirrored in the deck
    # it reads as a thin ring, never as a white plate on the floor.
    seg = 72
    for i in range(seg):
        t0, t1 = 2 * _m.pi * i / seg, 2 * _m.pi * (i + 1) / seg
        ri, ro = r - 0.22, r
        em.quad(
            [
                (cx + ro * _m.cos(t0), cz + ro * _m.sin(t0), h - 0.1),
                (cx + ro * _m.cos(t1), cz + ro * _m.sin(t1), h - 0.1),
                (cx + ri * _m.cos(t1), cz + ri * _m.sin(t1), h - 0.1),
                (cx + ri * _m.cos(t0), cz + ri * _m.sin(t0), h - 0.1),
            ],
            mat,
        )
    fins_m.build(f"SM_Ops_RingFins_{name}", "Ceiling", bevel=0.0)
    o = em.build(f"SM_Ops_RingLight_{name}", "Ceiling", bevel=0.0, shadow=False, keep_normals=True)
    o.visible_shadow = False


def linear_lights(
    name: str, strips, mat: str = "M_Light_CeilingPanel", h: float = L.ROOM_H
) -> None:
    """Ceiling light strips: list of (x0, x1, z0, z1) in a steel channel."""
    bez, em = Mesh(), Mesh()
    for x0, x1, z0, z1 in strips:
        bez.box(x0 - 0.05, x1 + 0.05, z0 - 0.05, z1 + 0.05, h - 0.04, h, STEEL)
        em.quad_h(x0, x1, z0, z1, h - 0.042, mat, up=False)
    bez.build(f"SM_Ops_StripBezels_{name}", "Ceiling", bevel=0.004)
    o = em.build(f"SM_Ops_Strips_{name}", "Ceiling", bevel=0.0, shadow=False, keep_normals=True)
    o.visible_shadow = False
