"""Set dressing of the engineering deck from the props-industrial kit.

Reactor hall far wall (machinery bays between heat-exchanger stacks, a
service gantry above), the conduit gallery (floor-to-ceiling power conduits,
coolant pipe runs, junction cabinets, cable trays) and the maintenance bay
(tool racks, the utility drone dock). Every prop sits where its function
puts it: pipes along walls, conduits rising to the ceiling, the dock at a wall.
"""

from __future__ import annotations

import bpy
import eng_common as c
from eng_common import Geo, b, build_into
from lib import kit, scene

GUNMETAL = "M_Struct_Gunmetal"
LAGGED = "M_Hull_PipeInsulated"
PIPE = "M_Hull_Pipe"
STRIP = "M_Light_WallStrip"
HAZARD = "M_Deck_Hazard"
WALL_DARK = "M_Wall_PaintedDark"

AXIS_X = c.SHAFT_C[0]  # the far wall composes symmetrically about the shaft
STACK_X = (35.4, 41.4, 66.6, 72.6, 78.6)
MACHINERY = ((48.2, "SM_Eng_WallMachinery_A", 1.0), (54.0, "SM_Eng_WallMachinery_B", 1.0),
             (59.8, "SM_Eng_WallMachinery_A", 1.0))  # fmt: skip
SLOT_X = (38.4, 44.0, 64.0, 69.6, 75.6, 81.0)
GANTRY_Y = 7.6
CONDUIT_X = (36.6, 41.4, 46.2, 51.0, 55.8, 60.6, 65.4, 70.2, 75.0, 79.8)  # near-side risers
CONDUIT_Z = 50.9
CONDUIT_H = c.GALLERY_H


def _register_variants() -> None:
    from kit.props.industrial import engineering

    if "SM_Eng_PowerConduit_Gallery" not in kit.registry():
        kit.register_variant(
            "SM_Eng_PowerConduit_Gallery", engineering.build_power_conduit,
            dims=(1.2, 1.2, CONDUIT_H), height=CONDUIT_H,
        )  # fmt: skip
        kit.register_variant(
            "SM_Eng_PowerConduit_GalleryTriple", engineering.build_power_conduit,
            dims=(2.4, 1.2, CONDUIT_H), height=CONDUIT_H, tubes=3,
        )  # fmt: skip


# ---------------------------------------------------------------- far wall


def far_wall() -> None:
    z = c.FAR_WALL_Z
    stacks = Geo()
    for x in STACK_X:
        stacks.cylinder(x, z + 1.35, 1.25, 0.0, c.HALL_H - 0.4, LAGGED, 48)
        for y in (0.6, 3.6, 6.6, 9.6):
            stacks.cylinder(x, z + 1.35, 1.35, y, y + 0.3, GUNMETAL, 48)
        stacks.box3(x - 1.5, x + 1.5, z, z + 2.8, 0.0, 0.5, GUNMETAL)  # plinth
        stacks.box3(x - 0.25, x + 0.25, z, z + 0.5, 0.5, c.HALL_H - 0.4, GUNMETAL)  # spine
    obj = build_into("Props", stacks, "SM_Eng_HeatStacks", bevel_width=0.01)
    kit.tag(obj, nav="block")

    with kit.into(scene.collection("Props")):
        for i, (x, piece, flip) in enumerate(MACHINERY):
            kit.place(piece, b(x, z), 0.0, id=f"EngWallMach_{i}", room="reactor",
                      scale=(flip, 1.0, 1.0))  # fmt: skip

    x0, x1 = c.PARTITION_X[1], c.EAST_HULL_X[0]
    lines = Geo()
    for y, r, dz in ((8.7, 0.3, 0.5), (9.4, 0.22, 0.45)):
        lines.tube(b(x0, z + dz, y), b(x1, z + dz, y), r, LAGGED if r > 0.25 else PIPE, 20)
    for y, r, dz in ((1.3, 0.3, 0.42), (2.0, 0.22, 0.38)):
        for xa, xb in ((x0, 45.4), (62.6, x1)):
            lines.tube(b(xa, z + dz, y), b(xb, z + dz, y), r, PIPE, 20)
    build_into("Props", lines, "SM_Eng_CoolantLines", bevel_width=0.0)

    gantry = Geo()
    gantry.box3(x0, x1, z, z + 1.4, GANTRY_Y, GANTRY_Y + 0.15, "M_Floor_Grating")
    x = x0
    while x <= x1:
        gantry.box3(x - 0.04, x + 0.04, z + 1.3, z + 1.38, GANTRY_Y + 0.15, GANTRY_Y + 1.2,
                    GUNMETAL)  # fmt: skip
        gantry.box3(x - 0.05, x + 0.05, z, z + 1.4, GANTRY_Y - 0.35, GANTRY_Y, GUNMETAL)
        x += 1.2
    gantry.box3(x0, x1, z + 1.3, z + 1.38, GANTRY_Y + 1.12, GANTRY_Y + 1.2, GUNMETAL)
    gantry.box3(x0, x1, z + 1.3, z + 1.38, GANTRY_Y + 0.62, GANTRY_Y + 0.68, GUNMETAL)
    obj = build_into("Props", gantry, "SM_Eng_WallGantry", bevel_width=0.004)
    kit.tag(obj, nav="none")

    lamps = Geo()
    x = x0 + 1.2
    while x < x1:
        lamps.box3(x - 0.08, x + 0.08, z + 1.4, z + 1.5, GANTRY_Y - 0.3, GANTRY_Y - 0.18,
                   "M_Light_Maint_Red")  # fmt: skip
        x += 4.8
    build_into("Props", lamps, "SM_Eng_WallMaintLamps", bevel_width=0.0)


# ---------------------------------------------------------------- gallery


def gallery() -> None:
    _register_variants()
    zf = c.GALLERY_NORTH_Z[1]
    with kit.into(scene.collection("Props")):
        # Coolant runs along the north side, broken at each opening from the hall.
        edges = [c.PARTITION_X[1] + 1.2]
        for xo in c.GALLERY_OPENINGS:
            edges += [xo - 1.8, xo + 1.8]
        edges.append(c.EAST_HULL_X[0])
        n = 0
        for a, bb in zip(edges[0::2], edges[1::2], strict=True):
            x = a
            while bb - x >= 4.8 - 1e-6:
                kit.place("SM_Eng_CoolantPipes", b(x + 2.4, zf + 0.75), 0.0, room="gallery",
                          id=f"EngGalPipes_{n:02d}")  # fmt: skip
                n += 1
                x += 4.8
            if bb - x >= 1.2 - 1e-6:
                kit.place("SM_Eng_JunctionCabinet", b(x + 0.6, zf), 0.0, room="gallery",
                          id=f"EngGalCab_{n:02d}")  # fmt: skip
                n += 1
        # Floor-to-ceiling power conduits on the near side, cable trays between.
        for i, x in enumerate(CONDUIT_X):
            triple = i % 3 == 1
            piece = "SM_Eng_PowerConduit_GalleryTriple" if triple else "SM_Eng_PowerConduit_Gallery"
            kit.place(piece, b(x, CONDUIT_Z), 0.0, room="gallery", id=f"EngGalConduit_{i}")
        for k, (xa, xb) in enumerate(zip(CONDUIT_X[:-1], CONDUIT_X[1:], strict=True)):
            kit.place("SM_Eng_CableTray_Floor", b((xa + xb) / 2, CONDUIT_Z - 0.2), 0.0,
                      room="gallery", id=f"EngGalTray_{k:02d}")  # fmt: skip
    lagged = Geo()
    x0, x1 = c.PARTITION_X[1] + 1.2, c.EAST_HULL_X[0]
    lagged.tube(b(x0, 51.75, 0.55), b(x1, 51.75, 0.55), 0.38, LAGGED, 24)
    x = x0 + 1.2
    while x < x1:
        lagged.box3(x - 0.12, x + 0.12, 51.3, 52.0, 0.0, 0.25, GUNMETAL)
        x += 2.4
    obj = build_into("Props", lagged, "SM_Eng_GalleryMain", bevel_width=0.0)
    kit.tag(obj, nav="block")


# ---------------------------------------------------------------- maintenance bay


def bay() -> None:
    xe = c.BAY_GALLERY_X[0]
    zn = c.CONTROL_SOUTH_Z[1]
    with kit.into(scene.collection("Props")):
        # Tool racks on the north wall, facing the room (and the camera).
        for i, x in enumerate((17.0, 27.4, 29.9)):
            kit.place("SM_Eng_ToolRack", b(x, zn), 0.0, room="bay", id=f"EngBayRack_{i}")
        # Spares on pallets and crate stacks along the near wall.
        for i, x in enumerate((17.4, 20.0)):
            kit.place("SM_Hangar_CrateStack", b(x, 51.4), 0.0, room="bay", id=f"EngBayCrates_{i}")
        for i, x in enumerate((22.8, 24.2)):
            kit.place("SM_Hangar_Pallet_Loaded", b(x, 51.1), 0.0, room="bay",
                      id=f"EngBayPallet_{i}")  # fmt: skip
        # Dock mast sits 0.55-0.95 m behind its pad centre: back it onto the wall.
        kit.place("SM_Eng_DroneDock", b(xe - 0.97, 49.8), -90.0, room="bay", id="EngDroneDock")
    dock = bpy.data.objects.get("SOCKET_spawn_EngDroneDock__drone")
    if dock is not None:
        dock.name = "SOCKET_spawn_drone"
    bench = Geo()
    z0 = c.CONTROL_SOUTH_Z[1]
    bench.box3(18.5, 21.0, z0 + 0.1, z0 + 0.9, 0.0, 0.9, "M_Console_Body")
    bench.box3(18.45, 21.05, z0 + 0.05, z0 + 0.95, 0.9, 0.95, "M_Trim_BrushedSteel")
    obj = build_into("Props", bench, "SM_Eng_BayBench", bevel_width=0.006)
    kit.tag(obj, nav="block")
    if c.KIT_ARCH:
        from kit.architecture import floors

        with kit.into(scene.collection("Props")):
            # Thin worn parking box around the drone's pad.
            x0, x1, z0, z1 = xe - 2.3, xe - 0.1, 48.7, 50.9
            for i, (a, bb, c0, c1) in enumerate(
                ((x0, x1, z0, z0 + 0.06), (x0, x1, z1 - 0.06, z1), (x0, x0 + 0.06, z0, z1))
            ):
                floors.marking(f"SM_Eng_DockBox_{i}", a, -c1, bb, -c0)


def markings() -> None:
    """Worn walkway lines: the gallery lane, and the straight walk from the
    control-room glass door to the west catwalk and the core."""
    if not c.KIT_ARCH:
        return
    from kit.architecture import floors

    with kit.into(scene.collection("Props")):
        for i, z in enumerate((42.0, 48.4)):
            floors.marking(f"SM_Eng_GalleryLane_{i}", 35.4, -z - 0.05, 81.4, -z + 0.05)
        x0, x1 = c.PARTITION_X[1] + 0.3, c.SHAFT_C[0] - c.COLLAR_HALF - 0.1
        for i, dz in enumerate((-1.1, 1.1)):
            z = c.DOOR_PARTITION + dz
            floors.marking(f"SM_Eng_CatwalkLane_{i}", x0, -z - 0.05, x1, -z + 0.05)


def build() -> None:
    far_wall()
    gallery()
    bay()
    markings()
