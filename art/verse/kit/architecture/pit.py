"""Bridge crew pits, console stations and the command walkway.

The pit is a sunken trench 1.4 m below the walkway (LEVELS.md). Consoles stand
against the pit's far wall (+Y) with their screens facing the camera (-Y);
the crew sits on the camera side of each console and is seen over the
shoulder (BRIEF section 5). The first 0.81 m of pit floor behind the near
retaining wall is hidden from the 60 degree camera, so seats sit beyond it.

Pieces (piece space: X along the row, Z = 0 at walkway level unless noted):

* ``SM_PitWall_120`` / ``_240`` - retaining wall, floor at Z = 0 of the
  piece (place it at the pit floor height); room face Y = 0 toward -Y,
  brushed coping and a down-light strip under the walkway edge.
* ``SM_Console_Pit`` - console, origin at its back-bottom centre, front -Y.
* ``SM_Seat_Crew`` - swivel seat, origin on the floor, facing -Y.
* ``SM_ConsoleStation`` - console + seat + sockets ``screen``, ``seat``,
  ``stand`` (origin = console back-bottom centre).
* ``SM_CrewPit_240`` / ``_RailFar`` - a 2.4 m slice of a pit: floor, both
  retaining walls, two stations, a railing on the near (or far) walkway edge.
* ``SM_CommandWalkway_240`` - 2.4 m x 4.8 m walkway slice with edge light
  inlays and a brushed nosing on both edges (place rot 90 for a walkway
  that runs along the camera axis).
"""

from __future__ import annotations

import math

from lib import kit
from mathutils import Vector

from . import floors, walls

PIT_DEPTH = 1.4
PIT_WIDTH = 3.6
WALL_T = 0.3
SCREEN_TILT_DEG = 28.0
SEAT_Y = -1.18  # seat centre relative to the console back
STAND_Y = -1.75


# ----------------------------------------------------------------- pit wall


def build_pit_wall(width: float) -> None:
    """Retaining wall of a crew pit, its top flush with the walkway: charcoal
    panels, a vertical light bar at every module seam (they show between the
    console bays), a pale coping and a down-light strip under the edge."""
    name = f"SM_PitWall_{round(width * 100)}"
    d = PIT_DEPTH
    body = kit.MeshBuilder()
    walls.backing(body, width, d)
    body.box((-width / 2, 0.035, 0.0), (width / 2, WALL_T, 0.1), "M_Wall_PaintedDark")
    for a, b in walls.module_spans(width):
        body.box((a + 0.035, 0.0, 0.1), (b - 0.035, walls.PANEL_DEPTH, d - 0.2), "M_Wall_Charcoal")
    body.build(f"{name}_body", bevel_width=0.003)
    bars = kit.MeshBuilder()
    for a, _b in walls.module_spans(width):
        bars.box((a - 0.03, -0.004, 0.14), (a + 0.03, 0.02, d - 0.24), "M_Struct_Gunmetal")
    bars.build(f"{name}_bar_frames", bevel_width=0.003)
    quads, faces = [], []
    for a, _b in walls.module_spans(width):
        n = len(quads)
        quads += [
            (a - 0.012, -0.005, 0.18),
            (a + 0.012, -0.005, 0.18),
            (a + 0.012, -0.005, d - 0.28),
            (a - 0.012, -0.005, d - 0.28),
        ]
        faces.append((n, n + 1, n + 2, n + 3))
    kit.mesh_object(f"{name}_bars", quads, faces, "M_Light_Backlit")
    coping = kit.MeshBuilder()
    coping.box((-width / 2, -0.06, d - 0.07), (width / 2, WALL_T, d), "M_Wall_PaintedLight")
    coping.box((-width / 2, -0.055, d - 0.085), (width / 2, 0.0, d - 0.07), "M_Rubber_Black")
    coping.build(f"{name}_coping", bevel_width=0.008, segments=3)
    housing = kit.MeshBuilder()
    housing.box((-width / 2, 0.0, d - 0.2), (width / 2, 0.04, d - 0.185), "M_Trim_BrushedSteel")
    housing.box((-width / 2, 0.06, d - 0.185), (width / 2, 0.08, d - 0.085), "M_Recess_Dark")
    housing.build(f"{name}_strip_housing", bevel_width=0.002)
    kit.emissive_panel(
        f"{name}_strip",
        (0.0, 0.03, d - 0.135),
        (width - 0.002, 0.06),
        "M_Light_WallStrip",
        normal="-Y",
    )
    kit.occluder(((-width / 2, 0.0, 0.0), (width / 2, WALL_T, d)))


# ------------------------------------------------------------------ console


CONSOLE_W = 1.1
# Side profile (y, z): back at y = 0, front toward -y.
CONSOLE_PROFILE = [
    (0.0, 0.0), (0.0, 1.16), (-0.24, 1.16), (-0.4, 0.84), (-0.78, 0.76), (-0.78, 0.72),
    (-0.46, 0.64), (-0.46, 0.1), (-0.5, 0.1), (-0.5, 0.0),
]  # fmt: skip


def _console_screen_quad(w: float) -> tuple[list[Vector], Vector, float]:
    top, bot = Vector((0.0, -0.255, 1.12)), Vector((0.0, -0.385, 0.875))
    inset = (top - bot).normalized()
    normal = Vector((0.0, -(top - bot).z, (top - bot).y)).normalized()
    if normal.y > 0:
        normal = -normal
    a, b = bot + inset * 0.012 + normal * 0.004, top - inset * 0.012 + normal * 0.004
    half = w / 2
    quad = [
        Vector((-half, a.y, a.z)),
        Vector((half, a.y, a.z)),
        Vector((half, b.y, b.z)),
        Vector((-half, b.y, b.z)),
    ]
    return quad, normal, (top - bot).length - 0.024


def build_console() -> None:
    """Crew console: dark carcass, mid-grey desk, keys, angled screen, lamps."""
    w = CONSOLE_W
    body = kit.MeshBuilder()
    body.prism_x(CONSOLE_PROFILE, -w / 2, w / 2, "M_Console_Body")
    body.box((-w / 2 - 0.01, -0.53, 0.0), (w / 2 + 0.01, 0.0, 0.05), "M_Rubber_Black")
    body.build("SM_Console_Pit_body", bevel_width=0.008, segments=3)

    deck = kit.MeshBuilder()
    # Desk top plate following the desk slope (0.78 -> 0.4 m out from the back).
    p0, p1 = (-0.775, 0.763), (-0.405, 0.843)
    deck.prism_x(
        [p0, p1, (p1[0], p1[1] + 0.012), (p0[0], p0[1] + 0.012)],
        -w / 2 + 0.03,
        w / 2 - 0.03,
        "M_Console_Deck",
    )
    deck.build("SM_Console_Pit_deck", bevel_width=0.003)
    keys = kit.MeshBuilder()
    k0, k1 = (-0.7, 0.7815), (-0.47, 0.8315)
    keys.prism_x(
        [k0, k1, (k1[0], k1[1] + 0.01), (k0[0], k0[1] + 0.01)], -0.42, 0.42, "M_Console_Keys"
    )
    keys.build("SM_Console_Pit_keys", bevel_width=0.0015)

    quad, normal, height = _console_screen_quad(w - 0.16)
    frame = kit.MeshBuilder()
    frame.quad(
        [
            v - normal * 0.002 + Vector((s * 0.03, 0, 0))
            for v, s in zip(quad, (-1, 1, 1, -1), strict=True)
        ],
        "M_Recess_Dark",
    )
    frame.build("SM_Console_Pit_bezel", bevel_width=0.0)
    kit.mesh_object("SM_Console_Pit_screen", quad, [(0, 1, 2, 3)], "M_Screen")
    center = sum(quad, Vector()) / 4
    kit.socket(
        "screen",
        "",
        kit.screen_matrix(center, tilt_deg=SCREEN_TILT_DEG),
        size_w=w - 0.16,
        size_h=height,
    )
    lamps = kit.MeshBuilder()
    for i, mat in enumerate(
        ("M_Indicator_Green", "M_Indicator_Green", "M_Indicator_Amber", "M_Indicator_Red")
    ):
        x = -w / 2 + 0.1 + i * 0.05
        lamps.box((x - 0.012, -0.243, 1.135), (x + 0.012, -0.228, 1.15), mat)
    lamps.build("SM_Console_Pit_lamps", bevel_width=0.0)
    kit.emissive_panel(
        "SM_Console_Pit_redtrim",
        (0.0, -0.2, 1.1605),
        (w - 0.06, 0.008),
        "M_Light_RedTrim",
        normal="Z",
    )
    kit.occluder(((-w / 2, -0.78, 0.0), (w / 2, 0.0, 1.16)))


# --------------------------------------------------------------------- seat


def build_seat() -> None:
    """Crew swivel seat facing -Y (rotate 180 to face a console)."""
    frame = kit.MeshBuilder()
    frame.prism_z(
        [(math.cos(a) * 0.24, math.sin(a) * 0.24) for a in _ring(16)],
        0.0,
        0.03,
        "M_Struct_Gunmetal",
    )
    frame.tube((0, 0, 0.03), (0, 0, 0.42), 0.04, "M_Trim_BrushedSteel", segments=16)
    frame.box((-0.23, -0.22, 0.4), (0.23, 0.22, 0.43), "M_Struct_Gunmetal")
    frame.box((-0.03, 0.2, 0.43), (0.03, 0.25, 0.62), "M_Struct_Gunmetal")
    for sx in (-1, 1):
        frame.box(
            (sx * 0.25 - 0.025, -0.15, 0.58), (sx * 0.25 + 0.025, 0.14, 0.62), "M_Struct_Gunmetal"
        )
        frame.box(
            (sx * 0.25 - 0.015, 0.06, 0.43), (sx * 0.25 + 0.015, 0.1, 0.58), "M_Struct_Gunmetal"
        )
    frame.build("SM_Seat_Crew_frame", bevel_width=0.006)
    pad = kit.MeshBuilder()
    pad.box((-0.22, -0.23, 0.43), (0.22, 0.2, 0.51), "M_Seat_Upholstery")
    back = kit.MeshBuilder(matrix=_tilt_back(0.24, 0.55, 12.0))
    back.box((-0.21, -0.04, 0.0), (0.21, 0.04, 0.5), "M_Seat_Upholstery")
    pad.build("SM_Seat_Crew_pad", bevel_width=0.025, segments=4)
    back.build("SM_Seat_Crew_back", bevel_width=0.025, segments=4)


def _ring(n: int) -> list[float]:
    return [2 * math.pi * i / n for i in range(n)]


def _tilt_back(y: float, z: float, deg: float):
    from mathutils import Matrix

    return Matrix.Translation((0.0, y, z)) @ Matrix.Rotation(math.radians(-deg), 4, "X")


# ------------------------------------------------------------------ station


def build_station() -> None:
    """Console with its seat and the sockets the runtime needs."""
    kit.place("SM_Console_Pit", (0.0, 0.0, 0.0), 0.0, id="_con")
    kit.place("SM_Seat_Crew", (0.0, SEAT_Y, 0.0), 180.0, id="_seat")
    kit.socket("seat", "", kit.facing_matrix((0.0, SEAT_Y, 0.0), 180.0), seat_h=0.5)
    kit.socket("stand", "", kit.facing_matrix((0.0, STAND_Y, 0.0), 180.0))


# ---------------------------------------------------------------- pit slice


def build_pit_slice(rail: str = "near") -> None:
    """2.4 m slice of a crew pit with two stations."""
    name = "SM_CrewPit_240" + ("_RailFar" if rail == "far" else "")
    half_w = PIT_WIDTH / 2
    d = PIT_DEPTH
    floors.fill_rect(f"{name}_floor", -1.2, -half_w, 1.2, half_w, -d, nav="walk")
    kit.place("SM_PitWall_240", (0.0, half_w, -d), 0.0, id=f"{name}_far")
    kit.place("SM_PitWall_240", (0.0, -half_w, -d), 180.0, id=f"{name}_near")
    for i, x in enumerate((-0.6, 0.6)):
        kit.place("SM_ConsoleStation", (x, half_w, -d), 0.0, id=f"st{i + 1}")
    y_rail = -half_w - 0.12 if rail == "near" else half_w + 0.12
    kit.place("SM_Railing_240", (0.0, y_rail, 0.0), 0.0, id=f"{name}_rail")


# ----------------------------------------------------------------- walkway


def build_walkway() -> None:
    """Command walkway slice: gloss deck, edge inlays, brushed nosings."""
    half = 2.4
    floors.fill_rect("SM_CommandWalkway_240_deck", -1.2, -half, 1.2, half, 0.0, nav="walk")
    nosing = kit.MeshBuilder()
    for sy in (-1, 1):
        y = sy * half
        nosing.box(
            (-1.2, min(y, y - sy * 0.05), -0.06),
            (1.2, max(y, y - sy * 0.05), 0.002),
            "M_Trim_BrushedSteel",
        )
    nosing.build("SM_CommandWalkway_240_nosing", bevel_width=0.003, nav="walk")
    for sy in (-1, 1):
        floors.inlay_strip(
            f"SM_CommandWalkway_240_inlay{sy + 1}",
            (-1.2, sy * (half - 0.25)),
            (1.2, sy * (half - 0.25)),
        )


kit.register_variant("SM_PitWall_120", build_pit_wall, dims=(1.2, WALL_T, PIT_DEPTH), width=1.2)
kit.register_variant("SM_PitWall_240", build_pit_wall, dims=(2.4, WALL_T, PIT_DEPTH), width=2.4)
kit.register_variant("SM_Console_Pit", build_console, dims=(CONSOLE_W, 0.78, 1.16))
kit.register_variant("SM_Seat_Crew", build_seat, dims=(0.5, 0.5, 1.05))
kit.register_variant("SM_ConsoleStation", build_station, dims=(CONSOLE_W, 2.0, 1.16))
kit.register_variant(
    "SM_CrewPit_240", build_pit_slice, dims=(2.4, PIT_WIDTH + 0.6, PIT_DEPTH), nav="walk"
)
kit.register_variant(
    "SM_CrewPit_240_RailFar",
    build_pit_slice,
    dims=(2.4, PIT_WIDTH + 0.6, PIT_DEPTH),
    nav="walk",
    rail="far",
)
kit.register_variant("SM_CommandWalkway_240", build_walkway, dims=(2.4, 4.8, 0.12), nav="walk")
