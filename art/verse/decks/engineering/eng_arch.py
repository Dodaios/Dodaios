"""Engineering deck architecture: slabs, hull, walls, partition, ceilings.

Bespoke deck geometry built from the shared materials; kit pieces replace
parts of it as kit-artist ships them.
"""

from __future__ import annotations

import eng_common as c
from eng_common import Geo, build_into
from lib import kit, scene

FLOOR_GLOSS = "M_Floor_GlossBlack"
FLOOR_SATIN = "M_Floor_SatinDark"
CAP = "M_Section_Cap"
HULL = "M_Hull_Structure"
WALL_LIGHT = "M_Wall_PaintedLight"
WALL_MID = "M_Wall_PaintedMid"
WALL_DARK = "M_Wall_PaintedDark"
GUNMETAL = "M_Struct_Gunmetal"
RECESS = "M_Recess_Dark"

# Occluder boxes (three x0, x1, z0, z1, y0, y1) collected while building walls.
OCCLUDER_BOXES: list[tuple[str, tuple[float, float, float, float, float, float]]] = []


def _occlude(name: str, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float) -> None:
    OCCLUDER_BOXES.append((f"{name}_{len(OCCLUDER_BOXES):02d}", (x0, x1, z0, z1, y0, y1)))


# ---------------------------------------------------------------- floors


def floors() -> None:
    hull = Geo()
    if c.KIT_REACTOR:
        # Only under the rooms: the deck edges are open hull bays.
        hull.plate_with_square_hole(c.WEST_HULL_X[1] - 0.3, c.EAST_HULL_X[0] + 0.3,
                                    c.FAR_WALL_Z - 0.3, c.SOUTH_HULL_Z[0] + 0.3,
                                    c.HULL_BOTTOM, -c.SLAB_T, c.COLLAR_HALF, HULL)  # fmt: skip
    else:
        hull.plate_with_hole(
            -2.0, c.DECK_W + 2.0, -6.0, c.DECK_D + 2.0, c.HULL_BOTTOM, -c.SLAB_T,
            c.SHAFT_WALL_R, HULL, half=15.0,
        )  # fmt: skip
    obj = build_into("Architecture", hull, "SM_Eng_UnderDeck", bevel_width=0.0)
    kit.tag(obj, nav="none")

    # Control room and lobby: black mirror deck (ART_DIRECTION 3); the hall,
    # gallery and bay are working floors in the kit's dark satin plate.
    gloss = Geo()
    x0, x1, z0, z1 = c.CONTROL
    gloss.slab3(x0, c.PARTITION_X[1], z0, c.CONTROL_SOUTH_Z[1], -c.SLAB_T, 0.0, FLOOR_GLOSS)
    x0, x1, z0, z1 = c.LOBBY
    gloss.slab3(x0, x1, c.CONTROL_SOUTH_Z[1], z1, -c.SLAB_T, 0.0, FLOOR_GLOSS)
    obj = build_into("Architecture", gloss, "SM_Eng_FloorControl", bevel_width=0.0)
    kit.tag(obj, nav="walk")

    satin = Geo()
    x0, x1, z0, z1 = c.HALL
    if c.KIT_REACTOR:
        satin.plate_with_square_hole(x0, x1, z0, c.GALLERY_NORTH_Z[1], -c.SLAB_T, 0.0,
                                     c.COLLAR_HALF, FLOOR_SATIN)  # fmt: skip
    else:
        satin.plate_with_hole(
            x0, x1, z0, c.GALLERY_NORTH_Z[1], -c.SLAB_T, 0.0, c.SHAFT_R, FLOOR_SATIN, half=14.0
        )
    x0, x1, z0, z1 = c.GALLERY
    satin.slab3(c.PARTITION_X[1], x1, c.GALLERY_NORTH_Z[1], z1, -c.SLAB_T, 0.0, FLOOR_SATIN)
    x0, x1, z0, z1 = c.BAY
    satin.slab3(c.LOBBY_BAY_X[0], c.BAY_GALLERY_X[1], c.CONTROL_SOUTH_Z[1], z1,
                -c.SLAB_T, 0.0, FLOOR_SATIN)  # fmt: skip
    obj = build_into("Architecture", satin, "SM_Eng_FloorHall", bevel_width=0.0)
    kit.tag(obj, nav="walk")


# ---------------------------------------------------------------- hull + walls


def hull_walls() -> None:
    if c.KIT_ARCH:
        _hull_walls_kit()
        return
    _hull_walls_blockout()


def _hull_walls_kit() -> None:
    """Thin room walls on the deck edges; hull bays (eng_hull) fill outside.

    The far wall is the deck's hero wall: 12 m kit modules with lit-panel
    columns across the whole width, on a dark backing whose top carries a
    row of hull bays (the strip the plate shows above the wall).
    """
    import eng_hull

    eng_hull.register_variants()
    w_in, e_out = c.WEST_HULL_X[1] - 0.3, c.EAST_HULL_X[0] + 0.3
    n_out, s_out = c.FAR_WALL_Z - 0.3, c.SOUTH_HULL_Z[0] + 0.3
    bay = 2.4
    far = Geo()
    far.slab3(w_in - 2 * bay - 2.4, e_out + 2 * bay + 2.4, -8.0, n_out, c.HULL_BOTTOM,
              c.HALL_H - bay, WALL_DARK, CAP)  # fmt: skip
    hero_x1 = c.WEST_HULL_X[1] + 2.4 * 33  # 1.2 m modules up to just short of the east wall
    far.slab3(hero_x1, c.EAST_HULL_X[0], n_out, c.FAR_WALL_Z, c.HULL_BOTTOM, c.HALL_H,
              WALL_DARK, CAP)  # fmt: skip
    _occlude("far_hull", w_in, e_out, -8.0, c.FAR_WALL_Z, c.HULL_BOTTOM, c.HALL_H)
    obj = build_into("Architecture", far, "SM_Eng_FarHull")
    kit.tag(obj, nav="block")
    kit_wall_run("EngHero", c.WEST_HULL_X[1], hero_x1, c.FAR_WALL_Z, cut=False,
                 variant=eng_hull.WALL_H1200)  # fmt: skip

    edge = Geo()
    bottom = -2.4  # the walls close the hull bays' sides down to their tank tops
    edge.slab3(w_in, c.WEST_HULL_X[1], n_out, s_out, bottom, c.CONTROL_H, WALL_DARK, CAP)
    _occlude("west_wall", w_in, c.WEST_HULL_X[1], n_out, s_out, bottom, c.CONTROL_H)
    edge.slab3(c.EAST_HULL_X[0], e_out, n_out, c.GALLERY_NORTH_Z[1], bottom, c.HALL_H,
               WALL_DARK, CAP)  # fmt: skip
    edge.slab3(c.EAST_HULL_X[0], e_out, c.GALLERY_NORTH_Z[1], s_out, bottom, c.GALLERY_H,
               WALL_DARK, CAP)  # fmt: skip
    _occlude("east_wall", c.EAST_HULL_X[0], e_out, n_out, c.GALLERY_NORTH_Z[1], bottom, c.HALL_H)
    _occlude("east_wall", c.EAST_HULL_X[0], e_out, c.GALLERY_NORTH_Z[1], s_out, bottom,
             c.GALLERY_H)  # fmt: skip
    edge.slab3(w_in, e_out, c.SOUTH_HULL_Z[0], s_out, bottom, c.CUT_H, WALL_DARK, CAP)
    _occlude("south_wall", w_in, e_out, c.SOUTH_HULL_Z[0], s_out, bottom, c.CUT_H)
    obj = build_into("Architecture", edge, "SM_Eng_EdgeWalls")
    kit.tag(obj, nav="block")
    eng_hull.build()


def _hull_walls_blockout() -> None:
    far = Geo()
    # Far hull wall: full height across the deck; backing block fills the
    # plate margin above and behind it.
    # The control-room stretch takes kit wall modules (0.3 m deep) on its face.
    skin = c.FAR_WALL_Z - 0.3
    far.slab3(-2.0, c.DECK_W + 2.0, -6.0, skin, c.HULL_BOTTOM, c.HALL_H, WALL_DARK, CAP)
    far.slab3(c.PARTITION_X[0], c.DECK_W + 2.0, skin, c.FAR_WALL_Z, c.HULL_BOTTOM, c.HALL_H,
              WALL_DARK, CAP)  # fmt: skip
    if not c.KIT_ARCH:
        far.slab3(-2.0, c.PARTITION_X[0], skin, c.FAR_WALL_Z, c.HULL_BOTTOM, c.HALL_H,
                  WALL_DARK, CAP)  # fmt: skip
    _occlude("far_hull", -2.0, c.DECK_W + 2.0, -6.0, c.FAR_WALL_Z, c.HULL_BOTTOM, c.HALL_H)
    obj = build_into("Architecture", far, "SM_Eng_FarHull")
    kit.tag(obj, nav="block")

    sides = Geo()
    wx0, wx1 = c.WEST_HULL_X
    sides.slab3(-2.0, wx1, c.FAR_WALL_Z, c.DECK_D + 2.0, c.HULL_BOTTOM, c.CONTROL_H, HULL, CAP)
    _occlude("west_hull", -2.0, wx1, c.FAR_WALL_Z, c.DECK_D + 2.0, c.HULL_BOTTOM, c.CONTROL_H)
    ex0, ex1 = c.EAST_HULL_X
    sides.slab3(ex0, c.DECK_W + 2.0, c.FAR_WALL_Z, c.GALLERY_NORTH_Z[1],
                c.HULL_BOTTOM, c.HALL_H, HULL, CAP)  # fmt: skip
    sides.slab3(ex0, c.DECK_W + 2.0, c.GALLERY_NORTH_Z[1], c.DECK_D + 2.0,
                c.HULL_BOTTOM, c.GALLERY_H, HULL, CAP)  # fmt: skip
    _occlude("east_hull", ex0, c.DECK_W + 2.0, c.FAR_WALL_Z, c.GALLERY_NORTH_Z[1],
             c.HULL_BOTTOM, c.HALL_H)  # fmt: skip
    _occlude("east_hull", ex0, c.DECK_W + 2.0, c.GALLERY_NORTH_Z[1], c.DECK_D + 2.0,
             c.HULL_BOTTOM, c.GALLERY_H)  # fmt: skip
    obj = build_into("Architecture", sides, "SM_Eng_SideHull")
    kit.tag(obj, nav="block")

    ribs = Geo()
    # Section through the hull: frames every 2.4 m across the cut hull tops.
    z = c.FAR_WALL_Z + 1.2
    while z < c.DECK_D + 2.0:
        ribs.box3(-2.0, c.WEST_HULL_X[1] - 0.25, z - 0.14, z + 0.14, c.CONTROL_H,
                  c.CONTROL_H + 0.12, GUNMETAL)  # fmt: skip
        top = c.HALL_H if z < c.GALLERY_NORTH_Z[1] else c.GALLERY_H
        ribs.box3(c.EAST_HULL_X[0] + 0.25, c.DECK_W + 2.0, z - 0.14, z + 0.14, top, top + 0.12,
                  GUNMETAL)  # fmt: skip
        z += 2.4
    x = 1.2
    while x < c.DECK_W + 2.0:
        ribs.box3(x - 0.14, x + 0.14, c.SOUTH_HULL_Z[0] + 0.25, c.DECK_D + 2.0, c.CUT_H,
                  c.CUT_H + 0.12, GUNMETAL)  # fmt: skip
        ribs.box3(x - 0.14, x + 0.14, -6.0, c.FAR_WALL_Z - 0.25, c.HALL_H, c.HALL_H + 0.12,
                  GUNMETAL)  # fmt: skip
        x += 2.4
    obj = build_into("Architecture", ribs, "SM_Eng_HullFrames", bevel_width=0.01)
    kit.tag(obj, nav="none")

    south = Geo()
    sz0, sz1 = c.SOUTH_HULL_Z
    south.slab3(-2.0, c.DECK_W + 2.0, sz0, sz1 + 2.0, c.HULL_BOTTOM, c.CUT_H, HULL, CAP)
    _occlude("south_hull", -2.0, c.DECK_W + 2.0, sz0, sz1 + 2.0, c.HULL_BOTTOM, c.CUT_H)
    obj = build_into("Architecture", south, "SM_Eng_SouthHull")
    kit.tag(obj, nav="block")


def _cut_wall_x(geo: Geo, x0: float, x1: float, z0: float, z1: float, doors: list[float]) -> None:
    """East-west wall cut at 1.1 m, with door gaps centred on `doors` (x)."""
    edges = [x0]
    for d in sorted(doors):
        edges += [d - c.DOOR_W / 2, d + c.DOOR_W / 2]
    edges.append(x1)
    for a, b in zip(edges[0::2], edges[1::2], strict=True):
        if b - a > 0.05:
            geo.slab3(a, b, z0, z1, 0.0, c.CUT_H, WALL_LIGHT, CAP)
            _occlude("wall_x", a, b, z0, z1, 0.0, c.CUT_H)


def _cut_wall_z(
    geo: Geo, x0: float, x1: float, z0: float, z1: float, height: float, doors: list[float]
) -> None:
    """North-south wall (seen edge-on) with door gaps centred on `doors` (z)."""
    edges = [z0]
    for d in sorted(doors):
        edges += [d - c.DOOR_W / 2, d + c.DOOR_W / 2]
    edges.append(z1)
    for a, b in zip(edges[0::2], edges[1::2], strict=True):
        if b - a > 0.05:
            geo.slab3(x0, x1, a, b, 0.0, height, WALL_LIGHT, CAP)
            _occlude("wall_z", x0, x1, a, b, 0.0, height)


def kit_wall_run(
    prefix: str, x0: float, x1: float, z_face: float, *, cut: bool,
    inserts: list[tuple[float, float, str, str | None]] = (), variant: str = "",
) -> None:  # fmt: skip
    """Tile kit wall modules along x with their room face at z_face (facing +z).

    `inserts` are (x_from, x_to, piece, id) spans taken by doors or lifts; the
    gaps between them are filled with 4.8 / 2.4 / 1.2 m modules.
    """
    spans, cursor = [], x0
    for a, bb, piece, pid in sorted(inserts):
        spans.append((cursor, a, None, None))
        spans.append((a, bb, piece, pid))
        cursor = bb
    spans.append((cursor, x1, None, None))
    suffix = "_Cut" if cut else variant
    n = 0
    with kit.into(scene.collection("Architecture")):
        for a, bb, piece, pid in spans:
            if piece is not None:  # "" keeps the span free for bespoke geometry
                if piece:
                    kit.place(piece, c.b((a + bb) / 2, z_face), 0.0, id=pid or f"{prefix}_{n:02d}")
                    n += 1
                continue
            x = a
            while bb - x > 0.05:
                for w in (4.8, 2.4, 1.2):
                    if bb - x >= w - 1e-6:
                        break
                kit.place(f"SM_Wall_{round(w * 100)}{suffix}", c.b(x + w / 2, z_face), 0.0,
                          id=f"{prefix}_{n:02d}")  # fmt: skip
                n += 1
                x += w


def interior_walls() -> None:
    walls = Geo()
    if c.KIT_ARCH:
        face = c.CONTROL_SOUTH_Z[1]
        door = "SM_BlastDoor_240_Cut"
        lx0, lx1 = c.LIFT_CORE_X
        kit_wall_run("EngWallCtrlS", lx1, c.PARTITION_X[0], face, cut=True, inserts=[
            (c.DOOR_CONTROL_LOBBY - 1.8, c.DOOR_CONTROL_LOBBY + 1.8, door, "control_lobby"),
            (c.DOOR_CONTROL_BAY - 1.8, c.DOOR_CONTROL_BAY + 1.8, door, "control_bay"),
        ])  # fmt: skip
        kit_wall_run("EngLiftCore", lx0, lx1, face, cut=False, inserts=[
            (c.LIFT_X - 1.2, c.LIFT_X + 1.2, "SM_Turbolift_Door", "main"),
        ])  # fmt: skip
        walls.slab3(lx0, lx1, c.LIFT_CORE_Z[0], face - 0.29, 0.0, c.CONTROL_H, WALL_DARK, CAP)
        _occlude("lift_core", lx0, lx1, c.LIFT_CORE_Z[0], face - 0.29, 0.0, c.CONTROL_H)
        kit_wall_run("EngWallGalN", c.PARTITION_X[1], c.EAST_HULL_X[0] + 0.2,
                     c.GALLERY_NORTH_Z[1], cut=True, inserts=[
            (x - 1.8, x + 1.8, door, f"gallery_{i + 1}") for i, x in enumerate(c.GALLERY_OPENINGS)
        ])  # fmt: skip
    else:
        z0, z1 = c.CONTROL_SOUTH_Z
        _cut_wall_x(walls, c.WEST_HULL_X[1], c.PARTITION_X[1], z0, z1,
                    [c.DOOR_CONTROL_LOBBY, c.DOOR_CONTROL_BAY])  # fmt: skip
        z0, z1 = c.GALLERY_NORTH_Z
        _cut_wall_x(walls, c.PARTITION_X[1], c.EAST_HULL_X[0], z0, z1, list(c.GALLERY_OPENINGS))
    x0, x1 = c.LOBBY_BAY_X
    _cut_wall_z(walls, x0, x1, c.CONTROL_SOUTH_Z[1], c.SOUTH_HULL_Z[0], c.LOBBY_H,
                [c.DOOR_LOBBY_BAY])  # fmt: skip
    x0, x1 = c.BAY_GALLERY_X
    _cut_wall_z(walls, x0, x1, c.CONTROL_SOUTH_Z[0], c.SOUTH_HULL_Z[0], c.GALLERY_H,
                [c.DOOR_BAY_GALLERY])  # fmt: skip
    obj = build_into("Architecture", walls, "SM_Eng_Walls")
    kit.tag(obj, nav="block")
    if not c.KIT_ARCH:
        _door_frames()


def _door_frames() -> None:
    frames = Geo()
    jamb = 0.16
    for x in (c.DOOR_CONTROL_LOBBY, c.DOOR_CONTROL_BAY):
        z0, z1 = c.CONTROL_SOUTH_Z
        for side in (-1, 1):
            xa = x + side * c.DOOR_W / 2
            frames.box3(min(xa, xa - side * jamb), max(xa, xa - side * jamb), z0 - 0.06,
                        z1 + 0.06, 0.0, c.CUT_H + 0.04, GUNMETAL)  # fmt: skip
    for x in c.GALLERY_OPENINGS:
        z0, z1 = c.GALLERY_NORTH_Z
        for side in (-1, 1):
            xa = x + side * c.DOOR_W / 2
            frames.box3(min(xa, xa - side * jamb), max(xa, xa - side * jamb), z0 - 0.06,
                        z1 + 0.06, 0.0, c.CUT_H + 0.04, GUNMETAL)  # fmt: skip
    obj = build_into("Architecture", frames, "SM_Eng_DoorFrames", bevel_width=0.008)
    kit.tag(obj, nav="block")


# ---------------------------------------------------------------- glass partition


def partition() -> None:
    """Glass partition between the control room and the reactor hall (edge-on)."""
    x0, x1 = c.PARTITION_X
    z_start, z_end = c.FAR_WALL_Z, c.CONTROL_SOUTH_Z[0]
    door = (c.DOOR_PARTITION - c.DOOR_W / 2, c.DOOR_PARTITION + c.DOOR_W / 2)
    frame = Geo()
    glass = Geo()
    xm = (x0 + x1) / 2
    # Sill and head rails, broken at the door.
    for za, zb in ((z_start, door[0]), (door[1], z_end)):
        frame.box3(x0 + 0.2, x1 - 0.2, za, zb, 0.0, 0.42, WALL_DARK)
        _occlude("partition_sill", x0 + 0.2, x1 - 0.2, za, zb, 0.0, 0.42)
        frame.box3(x0 + 0.3, x1 - 0.3, za, zb, c.CONTROL_H - 0.35, c.CONTROL_H, GUNMETAL)
        glass.box3(xm - 0.012, xm + 0.012, za, zb, 0.42, c.CONTROL_H - 0.35, "M_Glass_Viewport")
    # Mullions every module; heavier posts at the door.
    z = z_start
    while z <= z_end + 1e-6:
        inside_door = door[0] + 0.05 < z < door[1] - 0.05
        if not inside_door:
            frame.box3(xm - 0.07, xm + 0.07, z - 0.06, z + 0.06, 0.0, c.CONTROL_H, GUNMETAL)
        z += c.MODULE
    for zd in door:
        frame.box3(x0 + 0.15, x1 - 0.15, zd - 0.12, zd + 0.12, 0.0, c.CONTROL_H, GUNMETAL)
    frame.box3(x0 + 0.15, x1 - 0.15, door[0], door[1], 2.7, c.CONTROL_H, WALL_DARK)
    obj = build_into("Architecture", frame, "SM_Eng_PartitionFrame", bevel_width=0.006)
    kit.tag(obj, nav="block")
    obj = build_into("Architecture", glass, "SM_Eng_PartitionGlass", bevel_width=0.0)
    kit.tag(obj, nav="block")


# ---------------------------------------------------------------- ceilings + lights


def _ceiling_slab(geo: Geo, x0, x1, z0, z1, height) -> None:
    geo.box3(x0, x1, z0, z1, height, height + 0.25, "M_Ceiling_Panel")


def _kit_ceiling(room: str, x0: float, x1: float, z0: float, z1: float, height: float,
                 pitch=(2.4, 2.4)) -> None:  # fmt: skip
    from kit.architecture import ceiling

    with kit.into(scene.collection("Ceiling")):
        ceiling.fill_ceiling(room, (x0, x1), (-z1, -z0), height, pitch=pitch)


def _panel_ceiling(
    room: str, x0: float, x1: float, z0: float, z1: float, height: float,
    panels: list[tuple[float, float]],
) -> None:  # fmt: skip
    """Ceiling slab with kit diffuser panels (1.2 x 0.6) at the given (x, z)."""
    from kit.architecture import ceiling

    with kit.into(scene.collection("Ceiling")):
        ceiling.ceiling_slab(f"CEIL_{room}", [(x0, -z1), (x1, -z1), (x1, -z0), (x0, -z0)], height)
        for i, (x, z) in enumerate(panels):
            ceiling.light_panel(f"LGT_{room}_{i:02d}", (x, -z, height))


def _strip_ceiling(
    room: str, x0: float, x1: float, z0: float, z1: float, height: float,
    strips: list[tuple[float, float, float]], width: float = 0.3,
) -> None:  # fmt: skip
    """Ceiling slab with long linear diffusers (x_from, x_to, z): they mirror in
    the black deck as long light lines instead of a grid of tiles."""
    from kit.architecture import ceiling

    with kit.into(scene.collection("Ceiling")):
        ceiling.ceiling_slab(f"CEIL_{room}", [(x0, -z1), (x1, -z1), (x1, -z0), (x0, -z0)], height)
        for i, (a, bb, z) in enumerate(strips):
            centre = ((a + bb) / 2, -z, height)
            ceiling.light_panel(f"LGT_{room}_{i:02d}", centre, (bb - a, width))


def ceilings() -> None:
    geo = Geo()
    if c.KIT_ARCH:
        # Rows of ceiling panels over the aisles between the terminal rows:
        # mirrored crisply in the black deck, dark between (contrast first).
        xs = [4.4 + 2.4 * i for i in range(11)]
        rows = (7.2, 18.6, 27.0, 35.4)
        panels = [(x, z) for z in rows for x in xs]
        _panel_ceiling("control", c.WEST_HULL_X[1], c.PARTITION_X[0], c.FAR_WALL_Z,
                       c.CONTROL_SOUTH_Z[0], c.CONTROL_H, panels)  # fmt: skip
        gal = [(36.6 + 2.4 * i, z) for i in range(19) for z in (41.4, 47.4)]
        _panel_ceiling("gallery", c.GALLERY[0], c.EAST_HULL_X[0], c.GALLERY_NORTH_Z[1],
                       c.SOUTH_HULL_Z[0], c.GALLERY_H, gal)  # fmt: skip
        lobby = [(x, z) for x in (4.4, 6.8, 9.2, 11.6) for z in (45.2, 49.4)]
        _panel_ceiling("lobby", c.WEST_HULL_X[1], c.LOBBY_BAY_X[0], c.CONTROL_SOUTH_Z[1],
                       c.SOUTH_HULL_Z[0], c.LOBBY_H, lobby)  # fmt: skip
        bay = [(x, z) for x in (18.8, 21.2, 23.6, 26.0, 28.4) for z in (45.2, 49.4)]
        _panel_ceiling("bay", c.LOBBY_BAY_X[1], c.BAY_GALLERY_X[0], c.CONTROL_SOUTH_Z[1],
                       c.SOUTH_HULL_Z[0], c.BAY_H, bay)  # fmt: skip
    else:
        _ceiling_slab(geo, c.WEST_HULL_X[1], c.PARTITION_X[1], c.FAR_WALL_Z,
                      c.CONTROL_SOUTH_Z[1], c.CONTROL_H)  # fmt: skip
    hall = Geo()
    hall.plate_with_hole(c.PARTITION_X[1], c.EAST_HULL_X[0], c.FAR_WALL_Z, c.GALLERY_NORTH_Z[1],
                         c.HALL_H, c.HALL_H + 0.3, c.SHAFT_R + 1.0, "M_Ceiling_Panel",
                         half=15.0)  # fmt: skip
    if not c.KIT_ARCH:
        _ceiling_slab(geo, c.PARTITION_X[1], c.EAST_HULL_X[0], c.GALLERY_NORTH_Z[0],
                      c.SOUTH_HULL_Z[0], c.GALLERY_H)  # fmt: skip
        _ceiling_slab(geo, c.WEST_HULL_X[1], c.LOBBY_BAY_X[1], c.CONTROL_SOUTH_Z[0],
                      c.SOUTH_HULL_Z[0], c.LOBBY_H)  # fmt: skip
        _ceiling_slab(geo, c.LOBBY_BAY_X[0], c.BAY_GALLERY_X[1], c.CONTROL_SOUTH_Z[0],
                      c.SOUTH_HULL_Z[0], c.BAY_H)  # fmt: skip
    for g, name in ((geo, "SM_Eng_Ceilings"), (hall, "SM_Eng_HallCeiling")):
        obj = build_into("Ceiling", g, name, bevel_width=0.0)
        if obj is None:
            continue
        kit.hide_from_camera(obj)
        kit.tag(obj, nav="none")


def _panel_light(name: str, x: float, z: float, height: float, size, power: float, kelvin: float):
    """Ceiling fixture: area light plus its diffuser face (camera-invisible)."""
    scene.add_area_light(name, c.b(x, z, height - 0.03), size, power, kelvin)
    with kit.into(scene.collection("Ceiling")):
        face = kit.emissive_panel(
            f"SM_{name}", c.b(x, z, height - 0.02), size, "M_Light_CeilingPanel",
            normal="-Z", camera_visible=False,
        )  # fmt: skip
    face.visible_shadow = False
    kit.tag(face, nav="none")


def ceiling_lights() -> None:
    if not c.KIT_ARCH:
        _room_lights()
    _hall_lights()


def _room_lights() -> None:
    # Control room: troffer rows between the terminal rows and over the
    # master console; the room stays dim enough that the screens read.
    rows_z = (6.6, 10.8, 19.2, 27.6, 36.0)
    for ri, z in enumerate(rows_z):
        for ci, x in enumerate((5.0, 9.8, 14.6, 19.4, 24.2, 29.0)):
            _panel_light(f"LT_Ctrl_{ri}_{ci}", x, z, c.CONTROL_H, (1.2, 0.3), 32.0, 6500.0)
    # Conduit gallery: one line down the middle.
    for i, x in enumerate(range(37, 82, 5)):
        _panel_light(f"LT_Gallery_{i}", float(x), 45.2, c.GALLERY_H, (1.2, 0.3), 26.0, 6000.0)
    # Lift lobby and maintenance bay.
    for i, (x, z) in enumerate(((5.0, 46.0), (11.0, 46.0), (5.0, 50.0), (11.0, 50.0))):
        _panel_light(f"LT_Lobby_{i}", x, z, c.LOBBY_H, (1.2, 0.3), 30.0, 6500.0)
    for i, (x, z) in enumerate(((19.4, 45.6), (24.2, 45.6), (29.0, 45.6), (24.2, 50.0))):
        _panel_light(f"LT_Bay_{i}", x, z, c.BAY_H, (1.2, 0.3), 26.0, 6000.0)


def _hall_lights() -> None:
    # Reactor hall: linear high-bay rows over the walkways around the shaft;
    # dim and cool, so the core stays the key light.
    n = 0
    for z in (5.4, 36.4):
        for x in (36.6, 41.4, 46.2, 61.8, 66.6, 71.4, 76.2, 80.4):
            _panel_light(f"LT_Hall_{n}", x, z, c.HALL_H, (2.4, 0.35), 70.0, 5600.0)
            n += 1
    for x in (36.6, 77.4):
        for z in (12.0, 16.8, 27.2, 32.0):
            _panel_light(f"LT_Hall_{n}", x, z, c.HALL_H, (0.35, 2.4), 70.0, 5600.0)
            n += 1


def build() -> None:
    floors()
    hull_walls()
    interior_walls()
    partition()
    ceilings()
    ceiling_lights()
