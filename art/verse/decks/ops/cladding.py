"""Wall cladding of the Operations deck, seen at eye level.

The plate camera sees the deck's room walls only as 1.1 m section caps or
edge-on, so they were built as plain slabs; at eye level they were large flat
grey fields. This module dresses every room wall and the corridor's upper
walls in the ship's language with the kit's ``kit.architecture.cladding``
(the bridge's wall-detail level, PR #910):

* Rooms (charcoal hall walls): plinth with louvres, 0.6 m panels with seams
  and insets, light columns in alternate bays between gunmetal ribs with dash
  lamps (every third rib a red strip), a rail with a conduit bundle, an upper
  field and a recessed cornice; wall terminals, status boards, junction boxes
  with conduit drops and section sign plates in the bays the floor props
  leave free.
* Medical bay: the light-grey secondary panelling (room_wall).
* Corridor: the plain upper wall between the slot-light columns gets inset
  panels, a louvre, a conduit pair under the chamfer, and every few bays a
  sign plate, status board or terminal.

Everything is a ceiling ghost (``kit.ghost``): invisible to the plate camera
and to shadow rays, nav ``none``, no occluders, so the plate, the nav grid
and the occluders keep their shape. Faces the plate does see (the room side
of the corridor's south wall and the med wall's south face) are clipped at
the 1.1 m section.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from decks.ops import layout as L
from decks.ops.geo import CUT_H
from kit.architecture import cladding as C
from lib import kit, scene

DOOR_HEAD = 2.5
FRAME = 0.16  # door frame width either side of an opening


@dataclass
class Wall:
    """One room wall face: plan line, room side, span and openings."""

    key: str
    room: str
    axis: str  # "x": face at plan z = fixed (u = x); "z": face at plan x = fixed (u = z)
    fixed: float
    sign: int  # the room's side along the other axis
    t0: float
    t1: float
    doors: list[tuple[float, float]] = field(default_factory=list)  # (u0, u1)
    style: str = "hall"  # "hall" (charcoal) or "room" (light grey)
    clip: float = -1.0  # ghost clip height: CUT_H for faces the plate sees
    lit: int = 2  # every n-th bay gets a light column

    def matrix(self):
        return C.run_matrix(self.axis, self.fixed, self.sign)


def _doors(doors: dict[str, tuple[float, float]], x0: float, x1: float):
    out = []
    for x, w in doors.values():
        a, b = x - w / 2 - FRAME, x + w / 2 + FRAME
        if b > x0 and a < x1:
            out.append((a, b))
    return sorted(out)


def walls() -> list[Wall]:
    """Every dressed room wall (the far hull wall has its own facade)."""
    out: list[Wall] = []
    trim = 0.2  # keep corner pieces from colliding
    for rid in ("mess", "records", "simulator", "quartermaster"):
        x0, x1, z0, z1 = L.ROOMS[rid].rect
        out.append(Wall(f"{rid}_s", rid, "x", z1, -1, x0 + trim, x1 - trim,
                        _doors(L.DOORS_NORTH, x0, x1)))  # fmt: skip
        out.append(Wall(f"{rid}_w", rid, "z", x0, 1, z0 + 0.5, z1 - trim))
        out.append(Wall(f"{rid}_e", rid, "z", x1, -1, z0 + 0.5, z1 - trim))
    for rid in ("quarters", "team_a", "team_b", "medbay", "storage", "lobby"):
        x0, x1, z0, z1 = L.ROOMS[rid].rect
        style = "room" if rid == "medbay" else "hall"
        lit = 3 if rid == "quarters" else 2
        if rid == "medbay":
            north = Wall(f"{rid}_n", rid, "x", z0, 1, x0 + trim, x1 - trim,
                         _doors(L.DOORS_MED, x0, x1), style, CUT_H)  # fmt: skip
        elif rid == "lobby":
            north = None  # the lift core and its two doors take the whole face
        else:
            north = Wall(f"{rid}_n", rid, "x", z0, 1, x0 + trim, x1 - trim,
                         _doors(L.DOORS_SOUTH, x0, x1), style, CUT_H, lit)  # fmt: skip
        if north is not None:
            out.append(north)
        south_doors = _doors(L.DOORS_MED, x0, x1) if rid in ("lobby", "storage") else []
        out.append(Wall(f"{rid}_s", rid, "x", z1, -1, x0 + trim, x1 - trim, south_doors, style,
                        lit=lit))  # fmt: skip
        out.append(Wall(f"{rid}_w", rid, "z", x0, 1, z0 + trim, z1 - trim, style=style, lit=lit))
        out.append(Wall(f"{rid}_e", rid, "z", x1, -1, z0 + trim, z1 - trim, style=style, lit=lit))
    # The washroom partition's east face (the berths' side).
    out.append(Wall("quarters_wash", "quarters", "z", 11.3, 1, L.CORR_S + 0.2, 48.0 - 0.1, lit=3))
    return out


def _codes(w: Wall) -> str:
    """Section code for a wall's sign plates: deck, room number, wall."""
    rooms = list(L.ROOMS)
    n = rooms.index(w.room) + 1
    side = {"n": 1, "e": 2, "s": 3, "w": 4}.get(w.key.rsplit("_", 1)[-1], 5)
    return f"2-{n:02d}-{side}"


def dress_wall(w: Wall, reserved: list[tuple[float, float]]) -> None:
    """Clad one wall; ``reserved`` u spans have floor props in front of them
    (no terminals or boxes at their height there)."""
    B = C.Builders().at(w.matrix())
    seed = ("ops", w.key)
    openings = [C.Opening(a, b, DOOR_HEAD) for a, b in w.doors]
    mid = (w.t0 + w.t1) / 2
    ribs = C.rib_stations(w.t0, w.t1, 4.8, origin=mid + 2.4)
    ribs = [r for r in ribs if not any(a - 0.5 < r < b + 0.5 for a, b in w.doors)]
    if w.style == "room":
        C.room_wall(B, seed, w.t0, w.t1, top=L.ROOM_H, pilasters=ribs, openings=openings,
                    base_from=0.0 if w.clip < 0 else CUT_H - 0.1)  # fmt: skip
        bays = [(a, b) for a, b in zip([w.t0, *ribs], [*ribs, w.t1], strict=True)]
    else:
        nb = len(ribs) + 1
        lit = {i for i in range(nb) if i % w.lit == 1}
        red = {i for i in range(len(ribs)) if i % 3 == 1}
        bays = C.hall_wall(B, seed, w.t0, w.t1, top=L.ROOM_H, ribs=ribs, lit_bays=lit,
                           red_ribs=red, openings=openings)  # fmt: skip
    _fittings(B, w, bays, reserved, seed)
    B.finish(f"SM_Ops_Clad_{w.key}", room=w.room)


def _fittings(B: C.Builders, w: Wall, bays, reserved, seed) -> None:
    """Terminals, status boards, junction boxes and sign plates in the bays."""
    code = _codes(w)
    signed = False
    for bi, (a, b) in enumerate(bays):
        if b - a < 1.6:
            continue
        cu = (a + b) / 2
        blocked = any(ra - 0.4 < cu < rb + 0.4 for ra, rb in reserved) or any(
            da - 0.6 < cu < db + 0.6 for da, db in w.doors
        )
        lit = w.style == "hall" and bi % w.lit == 1 and b - a > 1.8
        off = 0.0 if not lit else 0.75  # beside the light column
        r = C.seed01(seed, "fit", bi)
        if not signed and not lit and b - a > 2.0:
            C.sign_plate(B, cu, 2.62, code)
            signed = True
        if blocked:
            if r < 0.5:
                C.status_panel(B, cu + off + 0.2, 1.95, seed=(seed, bi))
            continue
        if r < 0.35:
            C.wall_terminal(B, cu + off, 1.0, seed=(seed, bi))
            C.conduit_drop(B, cu + off + 0.42, 1.0, 2.73, n=1)
        elif r < 0.65:
            C.junction_box(B, cu + off - 0.1, 1.35, seed=(seed, bi))
            C.conduit_drop(B, cu + off - 0.1, 1.85, 2.73, n=2)
        elif r < 0.9:
            C.status_panel(B, cu + off, 1.3, seed=(seed, bi))
        if b - a > 3.0 and not lit:
            # A second fitting in a wide bay.
            du = (b - a) * 0.3 * (1 if r < 0.5 else -1)
            if C.seed01(seed, "fit2", bi) < 0.5:
                C.status_panel(B, cu + du, 1.5, seed=(seed, bi, 2))
            else:
                C.junction_box(B, cu + du, 0.55, w=0.5, h=0.4, seed=(seed, bi, 2))
                C.conduit_drop(B, cu + du, 0.95, 2.73, n=2)


# ---------------------------------------------------------------- corridor


def corridor_upper() -> None:
    """The corridor's upper walls (plan z 27.0 north, 33.0 south; 1.2 m to
    the chamfer at 3.3 m) between the slot-light columns every 2.4 m."""
    import math

    zt = {True: L.CORR_FLOOR[0] - L.SLOPE_RUN, False: L.CORR_FLOOR[1] + L.SLOPE_RUN}
    h0, h1 = L.SLOPE_TOP, L.CHAMFER_LOW
    stops = (*L.BLAST_FRAMES, *L.END_PORTALS)
    for north in (True, False):
        doors = L.door_spans(L.DOORS_NORTH if north else L.DOORS_SOUTH)
        B = C.Builders().at(C.run_matrix("x", zt[north], 1 if north else -1))
        seed = ("ops", "corr", north)
        for k in range(math.ceil(3.0 / 2.4), math.floor(93.0 / 2.4)):
            a, b = 2.4 * k + 0.3, 2.4 * (k + 1) - 0.3  # between two columns
            if any(fx - 1.5 < b and fx + 1.5 > a for fx in stops):
                continue
            if any(da - 0.2 < b and db + 0.2 > a for da, db in doors):
                continue
            cu = (a + b) / 2
            r = C.seed01(seed, k)
            C.box(B.flat, a, b, 0.0, C.BACK, h0 + 0.1, h1 - 0.08, C.RECESS)
            # Gunmetal pilasters beside the light columns.
            for p0, p1 in ((a, a + 0.07), (b - 0.07, b)):
                C.box(B.struct, p0, p1, C.BACK, 0.07, h0 + 0.1, h1 - 0.08, C.GUNMETAL)
            a2, b2 = a + 0.07, b - 0.07
            bands = ((h0 + 0.1, h0 + 0.36), (h0 + 0.36, 2.12), (2.32, 2.86), (2.86, h1 - 0.08))
            for m0, m1 in C.modules(a2, b2, 0.88):
                C.panel(B, m0, m1, *bands[0], C.DARK, inset=False, v=0.03)
                light = C.seed01(seed, k, m0) < 0.7
                C.panel(B, m0, m1, *bands[1], C.MID if light else C.CHARCOAL, inset=True, v=0.04)
                C.panel(B, m0, m1, *bands[2], C.CHARCOAL, inset=r < 0.5, v=0.035)
                C.panel(B, m0, m1, *bands[3], C.DARK, inset=False, v=0.03)
            # Rail between the light and the dark field, with a conduit pair.
            C.box(B.struct, a2, b2, C.BACK, 0.07, 2.12, 2.32, C.GUNMETAL)
            C.box(B.struct, a2, b2, C.BACK, 0.075, 2.3, 2.32, C.STEEL)
            for dv, hh, rr in ((0.1, 2.18, 0.028), (0.1, 2.26, 0.02)):
                B.pipes.tube((a2, dv, hh), (b2, dv, hh), rr, C.PIPE, 8)
            # Conduit pair under the chamfer.
            for dv, rr in ((0.06, 0.03), (0.13, 0.022)):
                B.pipes.tube((a, dv, h1 - 0.22), (b, dv, h1 - 0.22), rr, C.PIPE, 8)
            C.box(B.struct, cu - 0.03, cu + 0.03, C.BACK, 0.17, h1 - 0.32, h1 - 0.12, C.GUNMETAL)
            if k % 5 == 2:
                C.sign_plate(B, cu, 2.78, f"2-{k:02d}", ch=0.14)
            elif k % 5 == 4:
                C.status_panel(B, cu - 0.3, 1.45, seed=(seed, k))
                C.junction_box(B, cu + 0.35, 1.5, seed=(seed, k))
            elif r > 0.55:
                C.louvre(B, cu, h0 + 0.13, w=0.9, h=0.2)
            elif r < 0.2:
                C.wall_terminal(B, cu, 1.3, seed=(seed, k))
        B.finish(f"SM_Ops_Clad_corridor_{'n' if north else 's'}", room="corridor")


def corridor_slopes() -> None:
    """Dark inset vent plates in the middle of every sloped lower-wall panel
    of the corridor, between the pill-lamp units (eye level only)."""
    from decks.ops.arch import _on_slope
    from decks.ops.geo import Mesh

    stops = (*L.BLAST_FRAMES, *L.END_PORTALS)
    for north in (True, False):
        holes = L.door_spans(L.DOORS_NORTH if north else L.DOORS_SOUTH)
        plates, slats = Mesh(), Mesh()
        for j in range(3, 77):
            a, b = 1.2 * j + 0.34, 1.2 * (j + 1) - 0.34
            if any(ha - 0.5 < b and hb + 0.5 > a for ha, hb in holes):
                continue
            if any(fx - 1.5 < b and fx + 1.5 > a for fx in stops):
                continue
            if any(abs(4.8 * k - (a + b) / 2) < 0.45 for k in range(21)):
                continue  # structural rib
            lo, hi = 0.3, 0.98
            p = [_on_slope(north, lo, 0.01), _on_slope(north, lo, 0.022),
                 _on_slope(north, hi, 0.022), _on_slope(north, hi, 0.01)]  # fmt: skip
            plates.prism_x(p, a, b, C.CHARCOAL)
            hh = lo + 0.08
            while hh < hi - 0.1:
                h2 = hh + 0.035
                s = [_on_slope(north, hh, 0.021), _on_slope(north, hh, 0.03),
                     _on_slope(north, h2, 0.03), _on_slope(north, h2, 0.021)]  # fmt: skip
                slats.prism_x(s, a + 0.05, b - 0.05, C.GUNMETAL)
                hh += 0.075
        side = "n" if north else "s"
        for m, name in ((plates, "plates"), (slats, "slats")):
            o = m.build(f"SM_Ops_Clad_slope_{side}_{name}", "Ceiling", bevel=0.0, camera=False,
                        shadow=False)  # fmt: skip
            if o is not None:
                o["room"] = "corridor"


def build(reserved: dict[str, list[tuple[float, float]]] | None = None) -> None:
    reserved = reserved or {}
    with kit.into(scene.collection("Ceiling")):
        for w in walls():
            with kit.ghost(w.clip):
                dress_wall(w, reserved.get(w.key, []))
        with kit.ghost(CUT_H):
            corridor_upper()
        with kit.ghost(-1.0):
            corridor_slopes()
