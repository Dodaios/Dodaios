"""The engineering deck above its section cut: what the plate never shows but
the eye-level view must (BRIEF section 5, docs/verse/realtime.md).

All of it is built as ceiling ghosts: invisible to the plate camera and to
shadow rays, it closes the rooms for floor reflections and probes, and the
realtime export turns it into normal walls.

- Near hull wall: cut at 1.1 m along the lobby, bay and gallery; closed up
  to the room ceilings with the 1.2 m panelling of the walls below the cut.
- Reactor hall (12 m) over its lower neighbours: the hall-side skin above
  the gallery wall (4.5 m) and above the glass partition of the control
  room run on up to the hall ceiling.
- Lobby | bay and control | bay: the 0.6 m and 0.3 m slits between a lower
  wall top and the taller bay ceiling.
- The hall ceiling's ring opening over the reactor shaft: a ribbed collar
  rising 4 m into an exhaust plenum with a dark cap.
- Door heads over the full-height door slots of the lobby | bay and
  bay | gallery walls.

`cladding()` is ordinary Architecture: the plain walls the plate sees only
edge-on (the west hull wall, lobby | bay, bay | gallery) get the deck's dark
panelling with a rail, a recessed top and thin light strips, so at eye level
they are no longer flat light-grey slabs. It is the fallback without the
kits: with them, ``eng_fitout`` clads those walls (and the near wall) in the
engine-room language instead.
"""

from __future__ import annotations

import eng_common as c
from eng_common import Geo, build_into
from lib import kit

WALL_DARK = "M_Wall_PaintedDark"
CHARCOAL = "M_Wall_Charcoal"
STRIP = "M_Light_WallStrip"
STRIP_EVERY = 4  # a vertical light strip after every this many 1.2 m panels
DOOR_HEAD = 2.7
GUNMETAL = "M_Struct_Gunmetal"
RECESS = "M_Recess_Dark"
HULL = "M_Hull_Structure"
CEILING = "M_Ceiling_Panel"
PANEL_INSET = 0.02  # panels stand this far proud of the wall face
PLENUM_H = 4.0  # height of the exhaust plenum over the shaft opening
OPENING_R = c.SHAFT_R + 1.0  # radius of the hall ceiling's opening


def _panel_mat(i: int) -> str:
    """Panels alternate dark paint and charcoal enamel, so a long run reads
    as panelling (and catches the light differently), never as one slab."""
    return CHARCOAL if i % 3 == 1 else WALL_DARK


def _panels_x(geo: Geo, x0: float, x1: float, z_face: float, y0: float, y1: float,
              toward: int, lights: Geo | None = None) -> None:  # fmt: skip
    """1.2 m panels on a wall face at three z = `z_face` facing `toward` (+1/-1 in z);
    with `lights`, a thin vertical light strip every `STRIP_EVERY` panels."""
    n = max(1, round((x1 - x0) / c.MODULE))
    step = (x1 - x0) / n
    za, zb = sorted((z_face, z_face + toward * PANEL_INSET))
    for i in range(n):
        a, b = x0 + i * step, x0 + (i + 1) * step
        geo.box3(a + 0.008, b - 0.008, za, zb, y0 + 0.02, y1 - 0.02, _panel_mat(i))
        if lights is not None and i > 0 and i % STRIP_EVERY == 0:
            la, lb = sorted((z_face, z_face + toward * (PANEL_INSET + 0.006)))
            lights.box3(a - 0.02, a + 0.02, la, lb, y0 + 0.25, y1 - 0.25, STRIP)


def _panels_z(geo: Geo, z0: float, z1: float, x_face: float, y0: float, y1: float,
              toward: int, lights: Geo | None = None) -> None:  # fmt: skip
    """1.2 m panels on a wall face at three x = `x_face` facing `toward` (+1/-1 in x);
    with `lights`, a thin vertical light strip every `STRIP_EVERY` panels."""
    n = max(1, round((z1 - z0) / c.MODULE))
    step = (z1 - z0) / n
    xa, xb = sorted((x_face, x_face + toward * PANEL_INSET))
    for i in range(n):
        a, b = z0 + i * step, z0 + (i + 1) * step
        geo.box3(xa, xb, a + 0.008, b - 0.008, y0 + 0.02, y1 - 0.02, _panel_mat(i))
        if lights is not None and i > 0 and i % STRIP_EVERY == 0:
            la, lb = sorted((x_face, x_face + toward * (PANEL_INSET + 0.006)))
            lights.box3(la, lb, a - 0.02, a + 0.02, y0 + 0.25, y1 - 0.25, STRIP)


def near_wall(faces_too: bool = True) -> None:
    """The near hull wall above the cut, room face at z = SOUTH_HULL_Z[0] facing -z.

    Without `faces_too` only the wall body is built (eng_fitout clads it)."""
    z_face, z_back = c.SOUTH_HULL_Z[0], c.SOUTH_HULL_Z[0] + 0.3
    x_in, x_out = c.WEST_HULL_X[1] - 0.3, c.EAST_HULL_X[0] + 0.3
    top = max(c.GALLERY_H, c.BAY_H, c.LOBBY_H) + 0.1
    body, faces, lights = Geo(), Geo(), Geo()
    body.box3(x_in, x_out, z_face, z_back, c.CUT_H, top, WALL_DARK)
    rooms = (
        (c.LOBBY[0], c.LOBBY[1], c.LOBBY_H),
        (c.BAY[0], c.BAY[1], c.BAY_H),
        (c.GALLERY[0], c.GALLERY[1], c.GALLERY_H),
    )
    for x0, x1, height in rooms:
        # A gunmetal rail at the cut line ties the panels to the wall below.
        faces.box3(x0, x1, z_face - 0.04, z_face, c.CUT_H, c.CUT_H + 0.12, GUNMETAL)
        _panels_x(faces, x0, x1, z_face, c.CUT_H + 0.12, height - 0.35, -1, lights)
        faces.box3(x0, x1, z_face - 0.03, z_face, height - 0.35, height, RECESS)
    build_into("Ceiling", body, "SM_Eng_NearWallUpper", bevel_width=0.004)
    if not faces_too:
        return
    build_into("Ceiling", faces, "SM_Eng_NearWallUpperFaces", bevel_width=0.003)
    build_into("Ceiling", lights, "SM_Eng_NearWallUpperStrips", bevel_width=0.0)


def hall_skins() -> None:
    """The reactor hall's walls above its lower neighbours, up to the hall ceiling."""
    body, faces = Geo(), Geo()
    # Over the gallery wall: hall face at z = GALLERY_NORTH_Z[0], facing -z.
    z_face, z_back = c.GALLERY_NORTH_Z
    x0, x1 = c.PARTITION_X[1], c.EAST_HULL_X[0]
    y0 = c.CONTROL_H - 0.1  # the kit wall's ghost ends at its 4.5 m height
    body.box3(x0, x1, z_face, z_back, y0, c.HALL_H, WALL_DARK)
    faces.box3(x0, x1, z_face - 0.05, z_face, y0, y0 + 0.3, GUNMETAL)
    _panels_x(faces, x0, x1, z_face, y0 + 0.3, c.HALL_H - 0.6, -1)
    faces.box3(x0, x1, z_face - 0.03, z_face, c.HALL_H - 0.6, c.HALL_H, RECESS)
    # Over the glass partition: hall face at x = PARTITION_X[1], facing +x.
    xa, xb = c.PARTITION_X
    z0, z1 = c.FAR_WALL_Z, c.GALLERY_NORTH_Z[1]
    body.box3(xa, xb, z0, z1, c.CONTROL_H, c.HALL_H, WALL_DARK)
    faces.box3(xb, xb + 0.05, z0, z1, c.CONTROL_H, c.CONTROL_H + 0.3, GUNMETAL)
    _panels_z(faces, z0, z1, xb, c.CONTROL_H + 0.3, c.HALL_H - 0.6, 1)
    faces.box3(xb, xb + 0.03, z0, z1, c.HALL_H - 0.6, c.HALL_H, RECESS)
    build_into("Ceiling", body, "SM_Eng_HallSkins", bevel_width=0.004)
    build_into("Ceiling", faces, "SM_Eng_HallSkinFaces", bevel_width=0.003)


def slits() -> None:
    """Close the gaps between lower wall tops and the bay's taller ceiling."""
    geo = Geo()
    xa, xb = c.LOBBY_BAY_X
    geo.box3(xa, xb, c.CONTROL_SOUTH_Z[1], c.SOUTH_HULL_Z[0], c.LOBBY_H - 0.1, c.BAY_H + 0.1,
             WALL_DARK)  # fmt: skip
    za, zb = c.CONTROL_SOUTH_Z
    geo.box3(c.LOBBY_BAY_X[0], c.BAY_GALLERY_X[0], za, zb, c.CONTROL_H - 0.1, c.BAY_H + 0.1,
             WALL_DARK)  # fmt: skip
    build_into("Ceiling", geo, "SM_Eng_WallTops", bevel_width=0.0)


def shaft_plenum() -> None:
    """A ribbed collar over the ceiling's ring opening and a dark plenum cap."""
    geo = Geo()
    top = c.HALL_H + PLENUM_H
    geo.sector(OPENING_R, OPENING_R + 0.4, c.HALL_H, top, HULL, segments=96)
    for k in range(24):
        a = k * 15.0
        geo.sector(OPENING_R - 0.35, OPENING_R, c.HALL_H + 0.2, top, GUNMETAL,
                   a0=a - 0.9, a1=a + 0.9, segments=2)  # fmt: skip
    for y in (c.HALL_H + 0.3, c.HALL_H + 2.0, top - 0.4):
        geo.sector(OPENING_R - 0.45, OPENING_R, y, y + 0.22, GUNMETAL, segments=96)
    geo.sector(0.0, OPENING_R + 0.4, top, top + 0.3, CEILING, segments=96)
    geo.sector(0.0, c.CORE_R + 1.5, top - 0.6, top, RECESS, segments=64)
    build_into("Ceiling", geo, "SM_Eng_ShaftPlenum", bevel_width=0.0)


def _door_gaps(z0: float, z1: float, doors: list[float]) -> list[tuple[float, float]]:
    """The wall spans between door slots (`_cut_wall_z`'s gaps) along z."""
    edges = [z0]
    for d in sorted(doors):
        edges += [d - c.DOOR_W / 2, d + c.DOOR_W / 2]
    edges.append(z1)
    return [(a, b) for a, b in zip(edges[0::2], edges[1::2], strict=True) if b - a > 0.05]


# The full-height north-south walls: (x range, z range, height, door centres on z).
Z_WALLS = (
    (c.LOBBY_BAY_X, (c.CONTROL_SOUTH_Z[1], c.SOUTH_HULL_Z[0]), c.LOBBY_H, [c.DOOR_LOBBY_BAY]),
    (c.BAY_GALLERY_X, (c.CONTROL_SOUTH_Z[0], c.SOUTH_HULL_Z[0]), c.GALLERY_H,
     [c.DOOR_BAY_GALLERY]),
)  # fmt: skip


def door_heads() -> None:
    """Heads over the door slots of the full-height walls, from the door
    height up to the wall top, with a gunmetal lintel and jambs."""
    body, trim = Geo(), Geo()
    for (xa, xb), _, height, doors in Z_WALLS:
        for d in doors:
            a, b = d - c.DOOR_W / 2, d + c.DOOR_W / 2
            body.box3(xa, xb, a, b, DOOR_HEAD, height, WALL_DARK)
            trim.box3(xa - 0.06, xb + 0.06, a - 0.16, b + 0.16, DOOR_HEAD - 0.12, DOOR_HEAD,
                      GUNMETAL)  # fmt: skip
            for z in (a, b - 0.16):
                trim.box3(xa - 0.06, xb + 0.06, z, z + 0.16, c.CUT_H, DOOR_HEAD, GUNMETAL)
    build_into("Ceiling", body, "SM_Eng_DoorHeads", bevel_width=0.004)
    build_into("Ceiling", trim, "SM_Eng_DoorHeadTrim", bevel_width=0.006)


def _clad_z(faces: Geo, lights: Geo, x_face: float, toward: int, z0: float, z1: float,
            height: float) -> None:  # fmt: skip
    """Kick plate, lower panels, rail, upper panels with strips and a recessed
    top on a wall face at x = `x_face` facing `toward`."""
    xa, xb = sorted((x_face, x_face + toward * 0.03))
    faces.box3(xa, xb, z0, z1, 0.0, 0.15, RECESS)
    _panels_z(faces, z0, z1, x_face, 0.15, c.CUT_H, toward)
    xa, xb = sorted((x_face, x_face + toward * 0.05))
    faces.box3(xa, xb, z0, z1, c.CUT_H, c.CUT_H + 0.12, GUNMETAL)
    _panels_z(faces, z0, z1, x_face, c.CUT_H + 0.12, height - 0.35, toward, lights)
    xa, xb = sorted((x_face, x_face + toward * 0.03))
    faces.box3(xa, xb, z0, z1, height - 0.35, height, RECESS)


def cladding() -> None:
    """Panelling on the plain walls the plate sees only edge-on (Architecture)."""
    faces, lights = Geo(), Geo()
    # West hull wall: control room and lobby (the lift core lies between them).
    x_face = c.WEST_HULL_X[1]
    _clad_z(faces, lights, x_face, 1, c.FAR_WALL_Z + 0.3, c.LIFT_CORE_Z[0], c.CONTROL_H)
    _clad_z(faces, lights, x_face, 1, c.CONTROL_SOUTH_Z[1], c.SOUTH_HULL_Z[0], c.LOBBY_H)
    # Both faces of the lobby | bay and bay | gallery walls, around their doors.
    for (xa, xb), (z0, z1), height, doors in Z_WALLS:
        for a, b in _door_gaps(z0, z1, doors):
            _clad_z(faces, lights, xa, -1, a, b, height)
            _clad_z(faces, lights, xb, 1, a, b, height)
    obj = build_into("Architecture", faces, "SM_Eng_WallCladding", bevel_width=0.003)
    kit.tag(obj, nav="none")
    obj = build_into("Architecture", lights, "SM_Eng_WallCladdingStrips", bevel_width=0.0)
    kit.tag(obj, nav="none")


def build(fitout: bool = False) -> None:
    """With `fitout`, eng_fitout dresses the room walls in place of
    `cladding()` and the near wall's plain panels."""
    if not fitout:
        cladding()
    with kit.ghost(c.CUT_H):
        near_wall(faces_too=not fitout)
        hall_skins()
        slits()
        shaft_plenum()
        door_heads()
