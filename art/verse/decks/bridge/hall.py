"""Bridge hall at deck level: the I-shaped upper deck around the pits, the
command walkway, the side hull walls, the commander's station and the
strategy holo-table."""

from __future__ import annotations

import math

from lib import kit
from mathutils import Vector

from . import geo, panels
from . import layout as L

HOLO_Z = 13.2
COMMAND_Z = 8.4


def build_deck() -> None:
    """Upper deck as one solid down to the pit floor: its sides are the pit walls."""
    mb = kit.MeshBuilder()
    mb.prism_z(
        L.poly(L.upper_deck_outline()),
        L.PIT_Z - 0.25,
        0.0,
        "M_Wall_PaintedDark",
        cap_material="M_Floor_GlossBlack",
    )
    mb.build("SM_bridge_deck", bevel_width=0.0, nav="walk", room="bridge")
    # The deck edge hides the pit floor right behind it (people in the pits).
    geo.prism_ucx("bridge_deck", L.poly(L.upper_deck_outline()), L.PIT_Z, 0.0)


def build_walkway() -> None:
    """Flush 2-lamp white markers every 2.4 m along both walkway edges
    (style bible 2.11), each pair in a brushed frame."""
    frame = kit.MeshBuilder()
    lens = kit.MeshBuilder()
    z = L.FORWARD_EDGE_Z + 1.2
    while z < L.BULKHEAD_Z[0]:
        for x in L.WALKWAY_X:
            frame.box(
                (x - 0.04, -z - 0.24, -0.02), (x + 0.04, -z + 0.24, 0.0006), "M_Trim_BrushedSteel"
            )
            for dz in (-0.125, 0.125):
                zc = z + dz
                lens.quad(
                    [
                        (x - 0.02, -zc - 0.075, 0.0012),
                        (x + 0.02, -zc - 0.075, 0.0012),
                        (x + 0.02, -zc + 0.075, 0.0012),
                        (x - 0.02, -zc + 0.075, 0.0012),
                    ],
                    "M_Light_FloorInlay",
                )
        z += 2.4
    frame.build("SM_walkway_marker_frames", bevel_width=0.002, nav="walk")
    light = lens.build("SM_walkway_marker_lamps", bevel_width=0.0, nav="walk")
    light.visible_shadow = False
    light["light_kind"] = "walkway_marker"
    # Commander's floor mark: a brushed ring where the commander stands.
    cx, cy = L.XY(L.AXIS_X, COMMAND_Z)
    ring = kit.MeshBuilder()
    outer = geo.ellipse(cx, cy, 0.62, 0.62, 64)
    inner = geo.ellipse(cx, cy, 0.56, 0.56, 64)
    for i in range(len(outer)):
        j = (i + 1) % len(outer)
        ring._add(  # noqa: SLF001
            [
                Vector((*outer[i], 0.0015)),
                Vector((*outer[j], 0.0015)),
                Vector((*inner[j], 0.0015)),
                Vector((*inner[i], 0.0015)),
            ],
            [(0, 1, 2, 3)],
            "M_Trim_BrushedSteel",
        )
    ring.build("SM_command_floor_mark", bevel_width=0.0, nav="walk")


def build_side_walls() -> None:
    """Full-height side hull walls (seen edge-on), stepping down aft."""
    for name, (x0, x1) in (
        ("p", (L.SIDE_WALL_X[0] - L.SIDE_WALL_T, L.SIDE_WALL_X[0])),
        ("s", (L.SIDE_WALL_X[1], L.SIDE_WALL_X[1] + L.SIDE_WALL_T)),
    ):
        mb = kit.MeshBuilder()
        z_start = L.VP_FACE_Z + L.CHAMFER
        mb.box(
            (x0, -L.BULKHEAD_Z[1], L.PIT_Z - 0.25),
            (x1, -z_start, L.HALL_CEILING),
            "M_Wall_PaintedLight",
        )
        mb.box(
            (x0, -L.AFT_WALL_Z[1], 0.0),
            (x1, -L.BULKHEAD_Z[1], L.ROOM_CEILING),
            "M_Wall_PaintedLight",
        )
        mb.build(f"SM_sidewall_{name}", bevel_width=0.01)
        cap = kit.MeshBuilder()
        cap.box(
            (x0 - 0.01, -L.BULKHEAD_Z[1], L.HALL_CEILING),
            (x1 + 0.01, -z_start, L.HALL_CEILING + 0.02),
            "M_Section_Cap",
        )
        cap.box(
            (x0 - 0.01, -L.AFT_WALL_Z[1], L.ROOM_CEILING),
            (x1 + 0.01, -L.BULKHEAD_Z[1], L.ROOM_CEILING + 0.02),
            "M_Section_Cap",
        )
        cap.box(
            (x0, -L.BULKHEAD_Z[1] - 0.02, L.ROOM_CEILING),
            (x1, -L.BULKHEAD_Z[1], L.HALL_CEILING),
            "M_Section_Cap",
        )
        cap.box(
            (x0, -L.AFT_WALL_Z[1] - 0.02, 0.0),
            (x1, -L.AFT_WALL_Z[1], L.ROOM_CEILING),
            "M_Section_Cap",
        )
        cap.build(f"SM_sidewall_{name}_cap", bevel_width=0.0)
        geo.box_ucx(f"sidewall_{name}", (x0, -L.AFT_WALL_Z[1], 0.0), (x1, -z_start, L.HALL_CEILING))


def build_command_station(use_kit: bool) -> None:
    """The commander's station at the head of the walkway (kind agents_list)."""
    if use_kit:
        kit.place(
            "SM_Console_Command",
            L.P(L.AXIS_X, COMMAND_Z - 0.35, 0.0),
            0.0,
            room="bridge",
            id="command",
            station="command",
            station_kind="agents_list",
        )
        return
    mb = kit.MeshBuilder()
    mb.box(
        (L.AXIS_X - 1.2, -COMMAND_Z + 0.6, 0.0),
        (L.AXIS_X + 1.2, -COMMAND_Z + 1.2, 1.1),
        "M_Console_Body",
    )
    mb.build("SM_command_placeholder", bevel_width=0.01)
    kit.socket(
        "station",
        "command",
        kit.facing_matrix(L.P(L.AXIS_X, COMMAND_Z), 180.0),
        station_kind="agents_list",
        room="bridge",
    )


def build_holo_table(use_kit: bool = False) -> None:
    if use_kit:
        from kit.props.command import place_without_station

        place_without_station(
            "SM_Table_HoloStrategy", L.P(L.AXIS_X, HOLO_Z), 0.0, room="bridge", id="strategy"
        )
        return
    _holo_table_bespoke()


def _holo_table_bespoke() -> None:
    """Strategy holo-table: octagonal pedestal with a recessed emitter well."""
    cx, cy = L.XY(L.AXIS_X, HOLO_Z)
    r_top, r_base = 1.3, 0.95
    oct_top = [
        (
            cx + r_top * math.cos(math.radians(22.5 + 45 * i)),
            cy + r_top * math.sin(math.radians(22.5 + 45 * i)),
        )
        for i in range(8)
    ]
    oct_mid = geo.offset_polygon(oct_top, 0.1)
    oct_base = [
        (
            cx + r_base * math.cos(math.radians(22.5 + 45 * i)),
            cy + r_base * math.sin(math.radians(22.5 + 45 * i)),
        )
        for i in range(8)
    ]
    body = kit.MeshBuilder()
    body.prism_z(oct_base, 0.0, 0.12, "M_Struct_Gunmetal")
    body.prism_z(geo.offset_polygon(oct_base, 0.08), 0.12, 0.72, "M_Console_Body")
    body.prism_z(oct_top, 0.72, 0.9, "M_Console_Body")
    body.build("SM_holo_strategy_body", bevel_width=0.012, segments=3, nav="block", room="bridge")
    rim = kit.MeshBuilder()
    rim.prism_z(oct_top, 0.9, 0.93, "M_Trim_BrushedSteel")
    rim.build("SM_holo_strategy_rim", bevel_width=0.004)
    deck = kit.MeshBuilder()
    deck.prism_z(oct_mid, 0.93, 0.94, "M_Console_Deck")
    deck.build("SM_holo_strategy_deck", bevel_width=0.002)
    # Emitter well: dark glass disc with a lit ring and lens.
    well = kit.MeshBuilder()
    ring = geo.ellipse(cx, cy, 0.9, 0.9, 64)
    well.prism_z(ring, 0.94, 0.945, "M_Recess_Dark")
    well.build("SM_holo_strategy_well", bevel_width=0.0)
    grid = kit.MeshBuilder()
    for k in range(16):  # fine radial grid etched into the disc
        a = 2 * math.pi * k / 16
        d = Vector((math.cos(a), math.sin(a), 0.0))
        n = Vector((-d.y, d.x, 0.0)) * 0.004
        p0 = Vector((cx, cy, 0.9455)) + d * 0.16
        p1 = Vector((cx, cy, 0.9455)) + d * 0.86
        grid.quad([p0 - n, p1 - n, p1 + n, p0 + n], "M_Trim_BrushedSteel")
    for r in (0.3, 0.55, 0.8):
        pts = geo.ellipse(cx, cy, r, r, 96)
        for k in range(len(pts)):
            a0, a1 = Vector((*pts[k], 0.9456)), Vector((*pts[(k + 1) % len(pts)], 0.9456))
            n = (a1 - a0).normalized().cross(Vector((0, 0, 1))) * 0.003
            grid.quad([a0 - n, a1 - n, a1 + n, a0 + n], "M_Trim_BrushedSteel")
    grid.build("SM_holo_strategy_grid", bevel_width=0.0)
    lamps = kit.MeshBuilder()
    for i in range(48):
        a = 2 * math.pi * i / 48
        p = Vector((cx + 0.97 * math.cos(a), cy + 0.97 * math.sin(a), 0.945))
        lamps.box_c(p, (0.022, 0.022, 0.006), "M_Indicator_Blue" if i % 6 else "M_Indicator_White")
    lamps.tube((cx, cy, 0.94), (cx, cy, 0.99), 0.12, "M_Indicator_Blue", segments=24)
    lamp_obj = lamps.build("SM_holo_strategy_emitters", bevel_width=0.0)
    lamp_obj.visible_shadow = False
    # Instrument faces on the camera-facing facets.
    mbs = panels.builders()
    for i in (4, 5, 6):  # facets facing -Y (toward the camera)
        a = math.radians(22.5 + 45 * i + 22.5)
        nx, ny = math.cos(a), math.sin(a)
        p = (cx + 0.86 * nx, cy + 0.86 * ny, 0.42)
        yaw = math.degrees(math.atan2(ny, nx)) + 90.0
        frame = geo.tr(*p, rz_deg=yaw) @ geo.panel_frame((0, 0, 0))
        style = {4: "slats", 5: "matrix", 6: "slats"}[i]
        panels.face(mbs, frame, 0.58, 0.4, style, ("holo", i))
    panels.finish(mbs, "SM_holo_strategy_inst")
    geo.prism_ucx("holo_strategy", oct_top, 0.0, 0.94)
    kit.socket(
        "holo",
        "strategy",
        kit.socket_matrix((cx, cy, 0.95), (0, 0, 1), (0, 1, 0)),
        radius=0.9,
        height=1.8,
        room="bridge",
    )
