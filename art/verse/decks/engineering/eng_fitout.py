"""Engine-room fit-out of the engineering deck, seen at eye level.

The control room, lobby, maintenance bay and conduit gallery read empty and
grey from the shoulder camera: big smooth walls, bare floors. This module
turns them into a heavy industrial deck with the shared kits
(``kit.architecture.cladding``, ``kit.props.fitout``):

* Walls: every plain room wall gets the hall cladding (plinth with louvres,
  0.6 m panels, light columns between gunmetal ribs, a rail with a conduit
  bundle, a recessed cornice) plus wall terminals, status boards, junction
  boxes with conduit drops, static heat vents and section plates. These are
  ceiling ghosts: the plate, the nav grid and the occluders keep their shape.
* Floor: equipment racks, power cabinets, wall pipe manifolds, valve
  clusters, coolant tanks, tool racks and case stacks stand along the walls
  (``Props``, nav ``block``) only where the room's lanes, doorways, sockets
  and stations leave room. Grilles, hatches and hazard threshold bands are
  flush inlays (nav ``none``).
* Overhead (ghosts): pipe runs, ducts and cable ladders under the ceilings, a
  gantry crane over the bay and a maintenance gantry on its near wall.

The Reactor Shaft hall is the duel arena (combat/arenaReactor.ts): nothing
here touches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import eng_common as c
from kit.architecture import cladding as C
from kit.props import fitout as F
from lib import kit, scene

FRAME = 0.16  # door frame width either side of a door slot
TRIM = 0.2  # keep corner pieces from colliding


@dataclass
class Wall:
    """One room wall face: plan line, room side, span, openings."""

    key: str
    room: str
    axis: str  # "x": face at plan z = fixed (u = x); "z": face at plan x = fixed (u = z)
    fixed: float
    sign: int  # the room's side along the other plan axis
    t0: float
    t1: float
    top: float  # room ceiling height
    doors: list[tuple[float, float, float]] = field(default_factory=list)  # (u0, u1, head)
    clad: bool = True  # False: the kit wall already carries its own face

    def matrix(self):
        return C.run_matrix(self.axis, self.fixed, self.sign)

    def plan(self, u: float, v: float) -> tuple[float, float]:
        """Plan (x, z) of wall-frame (u, v)."""
        if self.axis == "x":
            return u, self.fixed + self.sign * v
        return self.fixed + self.sign * v, u

    def yaw(self) -> float:
        """Kit yaw that faces a piece into the room."""
        if self.axis == "x":
            return 0.0 if self.sign > 0 else 180.0
        return 90.0 if self.sign > 0 else -90.0


def _slot(centre: float, width: float = c.DOOR_W, head: float = 2.7):
    return (centre - width / 2 - FRAME, centre + width / 2 + FRAME, head)


def _blast(centre: float, top: float):
    """A kit blast door: its frame takes the full wall height."""
    return (centre - 1.8, centre + 1.8, top)


def walls() -> list[Wall]:
    zc, zl = c.CONTROL_SOUTH_Z
    hull_n = c.SOUTH_HULL_Z[0]
    return [
        # Engineering control room: the west hull wall and the lobby/bay wall.
        Wall(
            "ctrl_w",
            "control",
            "z",
            c.WEST_HULL_X[1],
            1,
            c.FAR_WALL_Z + 0.3,
            c.LIFT_CORE_Z[0] - TRIM,
            c.CONTROL_H,
        ),  # fmt: skip
        Wall(
            "ctrl_s",
            "control",
            "x",
            zc,
            -1,
            c.LIFT_CORE_X[1] + TRIM,
            c.PARTITION_X[0] - TRIM,
            c.CONTROL_H,
            [_blast(c.DOOR_CONTROL_LOBBY, c.CONTROL_H), _blast(c.DOOR_CONTROL_BAY, c.CONTROL_H)],
        ),  # fmt: skip
        # Turbolift lobby.
        Wall("lobby_w", "lobby", "z", c.WEST_HULL_X[1], 1, zl + TRIM, hull_n - TRIM, c.LOBBY_H),
        Wall(
            "lobby_s",
            "lobby",
            "x",
            hull_n,
            -1,
            c.WEST_HULL_X[1] + TRIM,
            c.LOBBY_BAY_X[0] - TRIM,
            c.LOBBY_H,
        ),  # fmt: skip
        Wall(
            "lobby_e",
            "lobby",
            "z",
            c.LOBBY_BAY_X[0],
            -1,
            zl + TRIM,
            hull_n - TRIM,
            c.LOBBY_H,
            [_slot(c.DOOR_LOBBY_BAY)],
        ),  # fmt: skip
        # Maintenance bay (its north wall is a kit wall with light columns).
        Wall(
            "bay_w",
            "bay",
            "z",
            c.LOBBY_BAY_X[1],
            1,
            zl + TRIM,
            hull_n - TRIM,
            c.BAY_H,
            [_slot(c.DOOR_LOBBY_BAY)],
        ),  # fmt: skip
        Wall(
            "bay_e",
            "bay",
            "z",
            c.BAY_GALLERY_X[0],
            -1,
            zl + TRIM,
            hull_n - TRIM,
            c.BAY_H,
            [_slot(c.DOOR_BAY_GALLERY)],
        ),  # fmt: skip
        Wall(
            "bay_s",
            "bay",
            "x",
            hull_n,
            -1,
            c.LOBBY_BAY_X[1] + TRIM,
            c.BAY_GALLERY_X[0] - TRIM,
            c.BAY_H,
        ),  # fmt: skip
        Wall(
            "bay_n",
            "bay",
            "x",
            zl,
            1,
            c.LOBBY_BAY_X[1] + TRIM,
            c.BAY_GALLERY_X[0] - TRIM,
            c.BAY_H,
            [_blast(c.DOOR_CONTROL_BAY, c.BAY_H)],
            clad=False,
        ),  # fmt: skip
        # Power conduit gallery (its north wall is a kit wall with light columns).
        Wall(
            "gal_w",
            "gallery",
            "z",
            c.BAY_GALLERY_X[1],
            1,
            c.CONTROL_SOUTH_Z[0] + TRIM,
            hull_n - TRIM,
            c.GALLERY_H,
            [_slot(c.DOOR_BAY_GALLERY)],
        ),  # fmt: skip
        Wall(
            "gal_e",
            "gallery",
            "z",
            c.EAST_HULL_X[0],
            -1,
            c.GALLERY_NORTH_Z[1] + TRIM,
            hull_n - TRIM,
            c.GALLERY_H,
        ),  # fmt: skip
        Wall(
            "gal_s",
            "gallery",
            "x",
            hull_n,
            -1,
            c.BAY_GALLERY_X[1] + TRIM,
            c.EAST_HULL_X[0] - TRIM,
            c.GALLERY_H,
        ),  # fmt: skip
        Wall(
            "gal_n",
            "gallery",
            "x",
            c.GALLERY_NORTH_Z[1],
            1,
            c.PARTITION_X[1] + TRIM,
            c.EAST_HULL_X[0] - TRIM,
            c.GALLERY_H,
            [_blast(x, c.GALLERY_H) for x in c.GALLERY_OPENINGS],
            clad=False,
        ),  # fmt: skip
    ]


# ---------------------------------------------------------------- floor props

# Floor props along walls: wall key -> [(kind, u0, u1)], ``u`` in the wall's
# frame (plan z on north-south walls, plan x on east-west walls).
RUNS: dict[str, list[tuple[str, float, float]]] = {
    "ctrl_w": [("rack", 3.2, 6.8), ("manifold", 8.0, 11.2), ("rack", 12.6, 15.0),
               ("cabinet", 16.6, 20.2), ("valves", 21.6, 22.8), ("rack", 24.4, 28.0),
               ("manifold", 29.4, 32.6), ("cabinet", 34.0, 37.6)],
    "ctrl_s": [("cabinet", 7.2, 9.8), ("rack", 14.6, 17.0), ("manifold", 17.6, 20.6),
               ("cases", 25.4, 26.6), ("rack", 27.4, 31.0)],
    "lobby_w": [("cabinet", 45.4, 47.8), ("rack", 49.4, 51.6)],
    "lobby_s": [("valves", 4.4, 5.6), ("manifold", 6.4, 9.6), ("cases", 11.6, 12.8)],
    "lobby_e": [("rack", 42.0, 44.4), ("cabinet", 49.2, 51.6)],
    "bay_w": [("rack", 42.2, 44.6), ("tank", 49.0, 50.2)],
    "bay_e": [("rack", 41.8, 44.2)],
    "bay_s": [("toolrack", 26.0, 28.48)],
    "gal_w": [("rack", 41.8, 44.2), ("valves", 48.6, 49.8)],
    "gal_e": [("tank", 40.4, 43.2), ("cabinet", 46.6, 49.6)],
}  # fmt: skip

# The gallery's near side: props in front of the conduit row (plan z 50.3),
# in the gaps between the floor-to-ceiling conduits: (kind, x).
GALLERY_NEAR_Z = 50.3
GALLERY_NEAR = (
    ("valves", 39.0), ("tank", 43.8), ("cabinet", 48.6), ("valves", 53.4), ("tank", 58.2),
    ("cabinet", 63.0), ("valves", 67.8), ("tank", 72.6), ("cabinet", 77.4),
)  # fmt: skip

# Freestanding: (room, kind, x, z, yaw).
FREESTANDING = (
    ("bay", "cases", 28.0, 43.0, 0.0),
    ("bay", "toolcart", 24.2, 43.3, 0.0),
)

# Flush inlays: (room, kind, x0, x1, z0, z1); kind grille, hatch or hazard.
_GAL_GRILLES = tuple(
    ("gallery", "grille", x - 0.6, x + 0.6, 44.9, 45.5) for x in (43.2, 48.0, 62.4, 67.2, 76.8)
)
FLOOR = (
    ("control", "hatch", 3.8, 5.0, 9.6, 10.8),
    ("control", "grille", 3.8, 5.0, 18.3, 18.9),
    ("control", "grille", 3.8, 5.0, 26.7, 27.3),
    ("control", "hatch", 3.8, 5.0, 33.0, 34.2),
    ("lobby", "grille", 7.8, 9.0, 49.8, 50.4),
    ("bay", "hatch", 21.8, 23.0, 46.2, 47.4),
    ("bay", "grille", 27.6, 28.8, 49.4, 50.0),
    *_GAL_GRILLES,
    # Hazard bands at the thresholds of the doors (both sides).
    ("control", "hazard", c.DOOR_CONTROL_LOBBY - 1.2, c.DOOR_CONTROL_LOBBY + 1.2, 40.62, 40.86),
    ("control", "hazard", c.DOOR_CONTROL_BAY - 1.2, c.DOOR_CONTROL_BAY + 1.2, 40.62, 40.86),
    ("lobby", "hazard", c.DOOR_CONTROL_LOBBY - 1.2, c.DOOR_CONTROL_LOBBY + 1.2, 41.64, 41.88),
    ("bay", "hazard", c.DOOR_CONTROL_BAY - 1.2, c.DOOR_CONTROL_BAY + 1.2, 41.64, 41.88),
    ("lobby", "hazard", 14.3, 14.54, c.DOOR_LOBBY_BAY - 1.2, c.DOOR_LOBBY_BAY + 1.2),
    ("bay", "hazard", 15.46, 15.7, c.DOOR_LOBBY_BAY - 1.2, c.DOOR_LOBBY_BAY + 1.2),
    ("bay", "hazard", 31.7, 31.94, c.DOOR_BAY_GALLERY - 1.2, c.DOOR_BAY_GALLERY + 1.2),
    ("gallery", "hazard", 34.06, 34.3, c.DOOR_BAY_GALLERY - 1.2, c.DOOR_BAY_GALLERY + 1.2),
    *(("gallery", "hazard", x - 1.2, x + 1.2, 38.62, 38.86) for x in c.GALLERY_OPENINGS),
)

# Overhead services per wall: wall key -> kinds ("pipes", "duct", "ladder").
OVERHEAD = {
    "ctrl_w": ("ladder",),
    "ctrl_s": ("pipes",),
    "lobby_s": ("pipes",),
    "lobby_w": ("ladder",),
    "bay_w": ("pipes",),
    "gal_n": ("pipes",),
    "gal_e": ("pipes",),
}
OVERHEAD_H = {"control": 3.85, "lobby": 3.55, "bay": 3.95, "gallery": 4.05}

# The bay's maintenance gantry on its near wall (u = plan x) and its ladder.
BAY_GANTRY = (16.0, 25.9)
BAY_GANTRY_H = 2.75
BAY_LADDER_X = 25.5


# Wall spans the deck's existing props already stand in front of
# (eng_dressing: bay crates and pallets, tool racks and bench, drone dock).
EXISTING: dict[str, list[tuple[float, float]]] = {
    "bay_s": [(16.0, 25.2)],
    "bay_n": [(15.6, 21.1), (26.1, 31.2)],
    "bay_e": [(48.5, 51.0)],
}


def reserved() -> dict[str, list[tuple[float, float]]]:
    """Wall spans with props in front (no light columns or fittings there)."""
    out = {key: [(a, b) for _, a, b in runs] for key, runs in RUNS.items()}
    for key, spans in EXISTING.items():
        out.setdefault(key, []).extend(spans)
    out["bay_s"].append((BAY_LADDER_X - 0.5, BAY_LADDER_X + 0.5))
    return out


def _floor_runs(by_key: dict[str, Wall]) -> None:
    for key, runs in RUNS.items():
        w = by_key[key]
        B = C.Builders().at(w.matrix())
        for i, (kind, a, b) in enumerate(runs):
            seed = ("eng-fit", key, i)
            mid = (a + b) / 2
            if kind == "rack":
                F.equipment_rack(B, a, b, seed=seed, h=2.2)
            elif kind == "cabinet":
                F.low_cabinet(B, a, b, seed=seed, h=1.05)
            elif kind == "cases":
                F.case_stack(B, mid, 0.5, seed)
            elif kind == "manifold":
                F.pipe_manifold(B, a, b, drops=max(2, round((b - a) / 0.8)), seed=seed)
            elif kind == "tank":
                n = max(1, round((b - a) / 1.4))
                step = (b - a) / n
                for k in range(n):
                    F.coolant_tank(B, a + step * (k + 0.5), 0.68, r=0.5, h=2.6, seed=(seed, k))
            elif kind in ("valves", "toolrack"):
                piece = "SM_Eng_ValveCluster" if kind == "valves" else "SM_Eng_ToolRack"
                depth = 0.42 if kind == "valves" else 0.0
                x, z = w.plan(mid, depth)
                kit.place(piece, c.b(x, z), w.yaw(), room=w.room, id=f"EngFit_{key}_{i}")
        B.finish(f"SM_Eng_Fit_{key}", room=w.room, nav="block")


def _gallery_near() -> None:
    B = None
    for i, (kind, x) in enumerate(GALLERY_NEAR):
        seed = ("eng-gal-near", i)
        if kind == "valves":
            kit.place("SM_Eng_ValveCluster", c.b(x, GALLERY_NEAR_Z - 0.42), 180.0, room="gallery",
                      id=f"EngFit_galnear_{i}")  # fmt: skip
            continue
        B = C.Builders().at(C.place_matrix(x, GALLERY_NEAR_Z, 180.0))
        if kind == "tank":
            F.coolant_tank(B, -0.65, 0.66, r=0.5, h=2.8, seed=seed)
            F.coolant_tank(B, 0.65, 0.66, r=0.5, h=2.8, seed=(seed, 1))
        else:
            F.low_cabinet(B, -0.9, 0.9, seed=seed, h=1.05)
        B.finish(f"SM_Eng_FitGalNear_{i}", room="gallery", nav="block")


def _freestanding() -> None:
    for i, (rid, kind, x, z, yaw) in enumerate(FREESTANDING):
        if kind == "toolcart":
            kit.place("SM_Hangar_ToolCart", c.b(x, z), yaw, room=rid, id=f"EngFit_cart_{i}")
            continue
        B = C.Builders().at(C.place_matrix(x, z, yaw))
        F.case_stack(B, 0.0, 0.0, ("eng-stack", i))
        B.finish(f"SM_Eng_FitStack_{i}", room=rid, nav="block")
    # The bay gantry's access ladder stands on the floor.
    w = Wall("bay_s", "bay", "x", c.SOUTH_HULL_Z[0], -1, 0.0, 0.0, c.BAY_H)
    B = C.Builders().at(w.matrix())
    F.gantry_ladder(B, BAY_LADDER_X, h=BAY_GANTRY_H)
    B.finish("SM_Eng_FitBayLadder", room="bay", nav="block")


def _floor_inlays() -> None:
    by_room: dict[str, C.Builders] = {}
    for rid, kind, x0, x1, z0, z1 in FLOOR:
        # place_matrix(0, 0, 0): u = plan x, v = plan z.
        B = by_room.setdefault(rid, C.Builders().at(C.place_matrix(0.0, 0.0, 0.0)))
        if kind == "grille":
            F.floor_grille(B, x0, x1, z0, z1)
        elif kind == "hatch":
            F.floor_hatch(B, x0, x1, z0, z1)
        else:
            F.hazard_band(B, x0, x1, z0, z1)
    for rid, B in by_room.items():
        B.finish(f"SM_Eng_FitFloor_{rid}", room=rid, nav="none")


# ---------------------------------------------------------------- overhead (ghosts)


def _overhead(by_key: dict[str, Wall]) -> None:
    for key, kinds in OVERHEAD.items():
        w = by_key[key]
        B = C.Builders().at(w.matrix())
        h = OVERHEAD_H[w.room]
        # Runs stop short of the full-height door frames.
        for a, b in C.subtract(w.t0 + 0.3, w.t1 - 0.3, [(d0 - 0.3, d1 + 0.3) for d0, d1, hd
                                                          in w.doors if hd > h - 0.4]):  # fmt: skip
            if b - a < 1.0:
                continue
            for kind in kinds:
                if kind == "pipes":
                    F.pipe_run(B, a, b, 0.3, h - 0.2, w.top)
                elif kind == "duct":
                    F.duct_run(B, a, b, 0.85, 1.35, h - 0.1, h + 0.3, w.top)
                elif kind == "ladder":
                    F.cable_ladder(B, a, b, 0.3, 0.8, h, w.top)
        B.finish(f"SM_Eng_Overhead_{key}", room=w.room)
    # Gallery: a cable ladder down the middle and a duct over the near side,
    # between the two rows of ceiling panels. place_matrix(0, 0, 0): u = x, v = z.
    x0, x1 = c.BAY_GALLERY_X[1] + 0.5, c.EAST_HULL_X[0] - 0.8
    B = C.Builders().at(C.place_matrix(0.0, 0.0, 0.0))
    F.cable_ladder(B, x0, x1, 44.1, 44.65, 4.2, c.GALLERY_H, cables=5)
    F.duct_run(B, x0, x1, 48.85, 49.5, 3.95, 4.35, c.GALLERY_H)
    B.finish("SM_Eng_Overhead_gallery", room="gallery")
    # Bay: gantry crane over the floor, maintenance gantry on the near wall.
    B = C.Builders().at(C.place_matrix(0.0, 0.0, 0.0))
    F.gantry_crane(B, c.LOBBY_BAY_X[1] + 1.0, c.BAY_GALLERY_X[0] - 0.4, 42.6, 50.2, 4.15,
                   c.BAY_H, at=0.55, hook=3.0)  # fmt: skip
    B.finish("SM_Eng_Overhead_baycrane", room="bay")
    w = by_key["bay_s"]
    B = C.Builders().at(w.matrix())
    F.maintenance_gantry(B, *BAY_GANTRY, h=BAY_GANTRY_H)
    B.finish("SM_Eng_Overhead_baygantry", room="bay")


# ---------------------------------------------------------------- walls (ghosts)


def _code(w: Wall) -> str:
    rooms = ("control", "reactor", "gallery", "lobby", "bay")
    side = {"n": 1, "e": 2, "s": 3, "w": 4}[w.key.rsplit("_", 1)[-1]]
    return f"3-{rooms.index(w.room) + 1:02d}-{side}"


def dress_wall(w: Wall, reserved: list[tuple[float, float]]) -> None:
    """Clad one wall; ``reserved`` u spans have floor props in front of them."""
    B = C.Builders().at(w.matrix())
    seed = ("eng", w.key)
    door_spans = [(a, b) for a, b, _ in w.doors]
    mid = (w.t0 + w.t1) / 2
    ribs = C.rib_stations(w.t0, w.t1, 4.8, origin=mid + 2.4)
    ribs = [r for r in ribs if not any(a - 0.5 < r < b + 0.5 for a, b in door_spans)]
    edges = [w.t0, *ribs, w.t1]
    bays = list(zip(edges[:-1], edges[1:], strict=True))

    def free(a: float, b: float) -> bool:
        cu = (a + b) / 2
        return not any(ra - 0.6 < cu < rb + 0.6 for ra, rb in reserved)

    if w.clad:
        lit = {i for i, (a, b) in enumerate(bays) if i % 2 == 1 and free(a, b)}
        red = {i for i in range(len(ribs)) if i % 3 == 1}
        openings = [C.Opening(a, b, head) for a, b, head in w.doors]
        bays = C.hall_wall(B, seed, w.t0, w.t1, top=w.top, ribs=ribs, lit_bays=lit,
                           red_ribs=red, openings=openings)  # fmt: skip
    else:
        lit = set()
    _fittings(B, w, bays, lit, reserved, seed)
    B.finish(f"SM_Eng_Clad_{w.key}", room=w.room)


def _fittings(B: C.Builders, w: Wall, bays, lit, reserved, seed) -> None:
    """Terminals, status boards, junction boxes, heat vents and section plates."""
    signed = False
    doors = [(a, b) for a, b, _ in w.doors]
    for bi, (a, b) in enumerate(bays):
        if b - a < 1.6:
            continue
        cu = (a + b) / 2
        blocked = any(ra - 0.4 < cu < rb + 0.4 for ra, rb in reserved)
        if any(da - 0.7 < cu < db + 0.7 for da, db in doors):
            continue
        off = 0.75 if bi in lit else 0.0  # beside the light column
        r = C.seed01(seed, "fit", bi)
        if w.clad and not signed and bi not in lit and b - a > 2.0:
            C.sign_plate(B, cu, 2.62, _code(w))
            signed = True
        if blocked:
            continue  # a floor prop stands in front: it carries the detail
        if not w.clad:
            # A kit wall: only small fittings above its lower field.
            if r < 0.5:
                C.status_panel(B, cu + off, 1.9, seed=(seed, bi))
            continue
        if r < 0.3:
            C.wall_terminal(B, cu + off, 1.0, seed=(seed, bi))
            C.conduit_drop(B, cu + off + 0.42, 1.0, 2.73, n=1)
        elif r < 0.55:
            C.junction_box(B, cu + off - 0.1, 1.35, seed=(seed, bi))
            C.conduit_drop(B, cu + off - 0.1, 1.85, 2.73, n=2)
        elif r < 0.8:
            F.heat_vent(B, cu + off, 0.45, w=0.9, h=0.6)
            C.status_panel(B, cu + off, 1.45, seed=(seed, bi))
        else:
            C.status_panel(B, cu + off, 1.3, seed=(seed, bi))
        if b - a > 3.0 and bi not in lit:
            du = (b - a) * 0.3 * (1 if r < 0.5 else -1)
            if C.seed01(seed, "fit2", bi) < 0.5:
                F.heat_vent(B, cu + du, 0.45, w=0.6, h=0.45)
            else:
                C.junction_box(B, cu + du, 0.55, w=0.5, h=0.4, seed=(seed, bi, 2))
                C.conduit_drop(B, cu + du, 0.95, 2.73, n=2)


def build() -> None:
    all_walls = walls()
    by_key = {w.key: w for w in all_walls}
    res = reserved()
    with kit.into(scene.collection("Props")):
        _floor_runs(by_key)
        _gallery_near()
        _freestanding()
        _floor_inlays()
    with kit.into(scene.collection("Ceiling")):
        for w in all_walls:
            with kit.ghost(-1.0 if w.clad else c.CUT_H):
                dress_wall(w, res.get(w.key, []))
        with kit.ghost(-1.0):
            _overhead(by_key)
