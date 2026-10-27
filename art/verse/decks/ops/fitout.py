"""Fit-out of the Operations deck: the working clutter of a lived-in deck.

Floor props along the room walls (equipment racks, service cabinets,
workstations with screens and stools), freestanding cargo case stacks, a holo
plinth, flush floor grilles and hatches, and overhead services under the
ceilings (pipe runs, ducts, cable ladders), all from ``kit.props.fitout``.

Floor props stand on the plate (``Props``, nav ``block``) only along walls and
in corners the room's lanes, doorways, sockets and stations leave free; the
nav grid loses those strips and nothing else. Grilles and hatches are flush
inlays (nav ``none``). Overhead services are ceiling ghosts: the plate never
sees them, the eye-level view does.
"""

from __future__ import annotations

from decks.ops import cladding
from decks.ops import layout as L
from kit.architecture import cladding as C
from kit.props import fitout as F
from lib import kit, scene

# Floor props along walls: wall key -> [(kind, u0, u1)]. ``u`` as in the
# wall's frame (plan x on east-west walls, plan z on north-south walls).
RUNS: dict[str, list[tuple[str, float, float]]] = {
    "mess_s": [("cabinet", 11.0, 15.8), ("rack", 16.4, 17.6), ("desk", 18.2, 19.8),
               ("cases", 21.2, 22.4)],
    "records_s": [("rack", 33.4, 34.6), ("desk", 35.2, 36.8), ("desk", 37.2, 38.8),
                  ("desk", 45.2, 46.8), ("desk", 47.2, 48.8), ("rack", 49.4, 50.6)],
    "simulator_w": [("rack", 4.6, 9.4), ("rack", 12.4, 16.0), ("desk", 19.2, 20.8)],
    "simulator_e": [("rack", 4.6, 9.4), ("rack", 12.4, 16.0)],
    "simulator_s": [("cabinet", 53.4, 55.8), ("rack", 69.8, 72.2)],
    "quartermaster_w": [("cabinet", 15.4, 20.2)],
    "quartermaster_e": [("cabinet", 15.4, 20.2)],
    "quartermaster_s": [("rack", 77.6, 80.0), ("desk", 81.6, 83.2)],
    "quarters_s": [("cabinet", 4.0, 9.4), ("rack", 12.6, 17.4), ("cases", 23.4, 24.6),
                   ("cases", 25.0, 26.2), ("rack", 33.4, 36.4)],  # fmt: skip
    "quarters_e": [("rack", 35.0, 37.4), ("desk", 43.8, 45.4), ("cabinet", 52.4, 55.4)],
    "team_a_w": [("rack", 36.2, 38.6), ("desk", 41.4, 43.0)],
    "team_a_e": [("rack", 36.2, 38.6), ("desk", 41.4, 43.0)],
    "team_a_s": [("desk", 39.8, 41.4), ("desk", 50.6, 52.2)],
    "team_b_w": [("rack", 36.2, 38.6), ("desk", 41.4, 43.0)],
    "team_b_e": [("rack", 36.2, 38.6), ("desk", 41.4, 43.0)],
    "team_b_s": [("desk", 55.8, 57.4), ("desk", 66.6, 68.2)],
    "lobby_s": [("cabinet", 71.6, 73.8), ("cabinet", 78.2, 80.4)],
    "storage_s": [("cabinet", 83.4, 85.8), ("rack", 90.0, 92.4)],
    "medbay_w": [("rack", 49.0, 51.4), ("cabinet", 53.4, 56.4)],
    "medbay_e": [("rack", 49.0, 51.4), ("cabinet", 53.4, 56.4)],
    "medbay_s": [("cabinet", 73.0, 77.2), ("cabinet", 82.0, 86.2), ("cabinet", 89.0, 92.0)],
}  # fmt: skip

# Freestanding case stacks: (room, x, z, yaw).
STACKS = (
    ("quartermaster", 80.6, 23.7, 0.0),
    ("quartermaster", 82.0, 23.9, 0.0),
    ("simulator", 71.6, 21.6, 90.0),
    ("storage", 85.6, 34.9, 0.0),
)
HOLO = (("simulator", 55.2, 23.6),)

# Flush floor grilles / hatches: (room, kind, x0, x1, z0, z1).
FLOOR = (
    ("mess", "grille", 16.4, 17.6, 10.2, 10.8),
    ("mess", "grille", 16.4, 17.6, 14.4, 15.0),
    ("mess", "grille", 16.4, 17.6, 18.6, 19.2),
    ("quartermaster", "hatch", 83.4, 84.6, 15.2, 16.4),
    ("medbay", "grille", 81.4, 82.6, 52.3, 52.9),
    ("team_a", "hatch", 40.0, 41.2, 45.0, 46.2),
    ("team_b", "hatch", 56.0, 57.2, 45.0, 46.2),
    ("records", "grille", 41.4, 42.6, 24.6, 25.2),
    ("storage", "hatch", 85.6, 86.8, 41.0, 42.2),
)

# Overhead services per wall: wall key -> kind ("pipes", "duct", "ladder").
OVERHEAD = {
    "mess_w": ("pipes",),
    "mess_e": ("pipes", "duct"),
    "mess_s": ("ladder",),
    "records_w": ("pipes",),
    "records_e": ("pipes", "duct"),
    "records_s": ("ladder",),
    "simulator_w": ("pipes", "duct"),
    "simulator_e": ("pipes",),
    "simulator_s": ("ladder",),
    "quartermaster_w": ("pipes",),
    "quartermaster_e": ("pipes", "duct"),
    "quartermaster_s": ("ladder",),
    "quarters_s": ("pipes",),
    "quarters_e": ("ladder",),
    "quarters_w": ("ladder",),
    "team_a_s": ("pipes",),
    "team_a_w": ("ladder",),
    "team_b_s": ("pipes",),
    "team_b_e": ("ladder",),
    "storage_w": ("ladder",),
    "storage_e": ("pipes",),
    "lobby_s": ("pipes",),
    "medbay_s": ("pipes",),
    "medbay_e": ("ladder",),
}


def reserved() -> dict[str, list[tuple[float, float]]]:
    """Wall spans with floor props in front (the cladding keeps its
    terminals off them)."""
    return {key: [(a, b) for _, a, b in runs] for key, runs in RUNS.items()}


def _floor_runs(walls: dict[str, cladding.Wall]) -> None:
    for key, runs in RUNS.items():
        w = walls[key]
        B = C.Builders().at(w.matrix())
        for i, (kind, a, b) in enumerate(runs):
            seed = ("ops-fit", key, i)
            if kind == "rack":
                F.equipment_rack(B, a, b, seed=seed)
            elif kind == "cabinet":
                F.low_cabinet(B, a, b, seed=seed, h=0.95 if w.room != "quarters" else 0.8)
            elif kind == "desk":
                F.workstation(B, (a + b) / 2, width=b - a, seed=seed)
            elif kind == "cases":
                F.case_stack(B, (a + b) / 2, 0.5, seed)
        B.finish(f"SM_Ops_Fit_{key}", room=w.room, nav="block")


def _freestanding() -> None:
    for i, (rid, x, z, yaw) in enumerate(STACKS):
        B = C.Builders().at(C.place_matrix(x, z, yaw))
        F.case_stack(B, 0.0, 0.0, ("ops-stack", i))
        B.finish(f"SM_Ops_FitStack_{i}", room=rid, nav="block")
    for i, (rid, x, z) in enumerate(HOLO):
        B = C.Builders().at(C.place_matrix(x, z, 0.0))
        F.holo_plinth(B, 0.0, 0.0, seed=("ops-holo", i))
        B.finish(f"SM_Ops_FitHolo_{i}", room=rid, nav="block")


def _floor_inlays() -> None:
    by_room: dict[str, C.Builders] = {}
    for rid, kind, x0, x1, z0, z1 in FLOOR:
        B = by_room.setdefault(rid, C.Builders().at(C.place_matrix(0.0, 0.0, 0.0)))
        # place_matrix(0, 0, 0): u = plan x, v = plan z.
        (F.floor_grille if kind == "grille" else F.floor_hatch)(B, x0, x1, z0, z1)
    for x in (12.0, 31.2, 50.4, 69.6, 88.8):  # corridor service hatches
        if all(abs(x - fx) > 1.6 for fx in (*L.BLAST_FRAMES, *L.END_PORTALS)):
            B = by_room.setdefault("corridor", C.Builders().at(C.place_matrix(0.0, 0.0, 0.0)))
            F.floor_hatch(B, x - 0.6, x + 0.6, L.CORR_Z_MID - 0.3, L.CORR_Z_MID + 0.3)
    for rid, B in by_room.items():
        B.finish(f"SM_Ops_FitFloor_{rid}", room=rid, nav="none")


def _overhead(walls: dict[str, cladding.Wall]) -> None:
    top = L.ROOM_H
    for key, kinds in OVERHEAD.items():
        w = walls[key]
        B = C.Builders().at(w.matrix())
        a, b = w.t0 + 0.3, w.t1 - 0.3
        for kind in kinds:
            if kind == "pipes":
                F.pipe_run(B, a, b, 0.32, 3.86, top)
            elif kind == "duct":
                F.duct_run(B, a, b, 0.85, 1.35, 3.92, 4.28, top)
            elif kind == "ladder":
                F.cable_ladder(B, a, b, 0.25, 0.75, 4.12, top)
        B.finish(f"SM_Ops_Overhead_{key}", room=w.room)


def build() -> dict[str, list[tuple[float, float]]]:
    """Build the fit-out; return the reserved wall spans for the cladding."""
    walls = {w.key: w for w in cladding.walls()}
    with kit.into(scene.collection("Props")):
        _floor_runs(walls)
        _freestanding()
        _floor_inlays()
    with kit.into(scene.collection("Ceiling")), kit.ghost(-1.0):
        _overhead(walls)
    return reserved()
