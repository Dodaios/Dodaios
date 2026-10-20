"""Aft of the bridge: the cut-away bulkhead with its doors and the two lift
shafts, the briefing room, the turbolift lobby and the commander's ready
room. Everything east-west here is cut at 1.1 m (BRIEF section 5)."""

from __future__ import annotations

import math
import re

from lib import kit
from mathutils import Vector

from . import geo, panels
from . import layout as L

PANEL = "M_Wall_PaintedLight"
TABLE_C = (15.9, 38.4)
TABLE_R = (4.5, 1.55)
DESK_C = (56.4, 36.6)
CASE_C = (63.0, 39.0)


def _lacquer_finish(mb, name, **kw):
    """Piano-black lacquer through the props library (falls back to gloss deck)."""
    try:
        from kit.props.command import _base as pc

        return pc.finish(mb, name, **kw)
    except Exception as error:  # noqa: BLE001 - optional dependency
        print(f"[deck-bridge] lacquer fallback: {error}")
        mb.materials = [
            "M_Console_Body" if m == "M_Lacquer_BlackGloss" else m for m in mb.materials
        ]
        return mb.build(name, **kw)


# ---------------------------------------------------------------- floors


def build_floors() -> None:
    z0, z1 = L.BULKHEAD_Z
    # Floor through the bulkhead only where the doors are; elsewhere the
    # bulkhead is a double skin with a service cavity open to the camera.
    spans = [L.BRIEF_DOOR_X, L.MAIN_DOOR_X, L.READY_DOOR_X]
    mb = kit.MeshBuilder()
    for a, b in spans:
        mb.prism_z(L.rect(a, z0, b, z1), -0.3, 0.0, "M_Floor_GlossBlack")
    mb.build("SM_bulkhead_floor", bevel_width=0.0, nav="walk")
    for room, (x0, x1), mat in (
        ("briefing", L.BRIEFING_X, "M_Floor_GlossBlack"),
        ("lobby", L.LOBBY_X, "M_Floor_GlossBlack"),
        ("ready", L.READY_X, "M_Floor_GlossBlack"),
    ):
        f = kit.MeshBuilder()
        f.prism_z(L.rect(x0, L.ROOMS_Z[0], x1, L.ROOMS_Z[1]), -0.3, 0.0, mat)
        f.build(f"SM_{room}_floor", bevel_width=0.0, nav="walk", room=room)


# ---------------------------------------------------------------- walls


def _cut_wall(name: str, x0: float, x1: float, z_far: float, z_near: float, *, face_panels: bool):
    """East-west wall cut at 1.1 m with a hatched section cap; panelled on its
    camera-facing (+z) side when ``face_panels``."""
    mb = kit.MeshBuilder()
    y_far, y_near = -z_far, -z_near
    mb.box((x0, y_near + 0.03, 0.0), (x1, y_far, L.CUT_H - 0.02), "M_Wall_PaintedMid")
    mb.box((x0, y_near, 0.0), (x1, y_near + 0.035, 0.12), "M_Wall_PaintedDark")
    if face_panels:
        n = max(1, round((x1 - x0) / L.M))
        step = (x1 - x0) / n
        for i in range(n):
            a, b = x0 + i * step, x0 + (i + 1) * step
            mb.box((a + 0.004, y_near, 0.13), (b - 0.004, y_near + 0.04, L.CUT_H - 0.05), PANEL)
        mb.box(
            (x0, y_near - 0.006, L.CUT_H - 0.06),
            (x1, y_near + 0.04, L.CUT_H - 0.02),
            "M_Trim_BrushedSteel",
        )
    mb.build(f"SM_{name}", bevel_width=0.004)
    cap = kit.MeshBuilder()
    cap.box((x0, y_near - 0.006, L.CUT_H - 0.02), (x1, y_far, L.CUT_H), "M_Section_Cap")
    cap.build(f"SM_{name}_cap", bevel_width=0.0)
    geo.box_ucx(name, (x0, y_near, 0.0), (x1, y_far, L.CUT_H))


def _jamb(name: str, x: float, z_far: float, z_near: float, side: int) -> None:
    """Gunmetal door jamb at an opening edge (cut with the wall)."""
    mb = kit.MeshBuilder()
    x0, x1 = sorted((x, x + side * 0.22))
    mb.box((x0, -z_near - 0.05, 0.0), (x1, -z_far + 0.05, L.CUT_H + 0.02), "M_Struct_Gunmetal")
    mb.box(
        (x0 - 0.002, -z_near - 0.052, L.CUT_H),
        (x1 + 0.002, -z_far + 0.052, L.CUT_H + 0.025),
        "M_Section_Cap",
    )
    # Door leaf parked in its pocket: a slim dark edge with a rubber seal.
    lx = x + side * 0.12
    mb.box(
        (lx - 0.03, -(z_far + z_near) / 2 - 0.05, 0.0),
        (lx + 0.03, -(z_far + z_near) / 2 + 0.05, L.CUT_H - 0.02),
        "M_Rubber_Black",
    )
    mb.build(f"SM_{name}", bevel_width=0.006)
    _lit_edge(f"{name}_lamps", x + side * 0.12, -z_near - 0.052, side)


def _lit_edge(name: str, x: float, y: float, side: int, z0: float = 0.15) -> None:
    """Dotted line of small white lamps up an opening's inner edge, facing the
    camera (style bible 2.3, lit variant for command areas)."""
    mb = kit.MeshBuilder()
    z = z0
    while z < L.CUT_H - 0.08:
        xa, xb = sorted((x + side * 0.03, x + side * 0.07))
        mb.box((xa, y - 0.006, z), (xb, y + 0.002, z + 0.015 * 2.5), "M_Indicator_White")
        z += 0.15
    obj = mb.build(f"SM_{name}", bevel_width=0.0, nav="none")
    obj.visible_shadow = False


def _threshold(name: str, x0: float, x1: float, z_far: float, z_near: float) -> None:
    mb = kit.MeshBuilder()
    mb.box((x0, -z_near - 0.1, -0.02), (x1, -z_far + 0.1, 0.004), "M_Trim_BrushedSteel")
    for i in range(int((x1 - x0) / 0.12)):
        x = x0 + 0.06 + i * 0.12
        mb.box(
            (x - 0.015, -z_near - 0.05, 0.004), (x + 0.015, -z_far + 0.05, 0.007), "M_Rubber_Black"
        )
    mb.build(f"SM_{name}", bevel_width=0.002, nav="walk")


def build_bulkhead() -> None:
    zf, zn = L.BULKHEAD_Z
    x_lo, x_hi = L.SIDE_WALL_X[0] - L.SIDE_WALL_T, L.SIDE_WALL_X[1] + L.SIDE_WALL_T
    solids = [
        (x_lo, L.BRIEF_DOOR_X[0]),
        (L.BRIEF_DOOR_X[1], L.LIFT_P_X[0]),
        (L.LIFT_P_X[1], L.MAIN_DOOR_X[0]),
        (L.MAIN_DOOR_X[1], L.LIFT_S_X[0]),
        (L.LIFT_S_X[1], L.READY_DOOR_X[0]),
        (L.READY_DOOR_X[1], x_hi),
    ]
    for i, (a, b) in enumerate(solids):
        if b - a < 2.0:
            _cut_wall(f"bulkhead_{i}", a, b, zf, zn, face_panels=True)
            continue
        skin = 0.3
        _cut_wall(f"bulkhead_{i}_n", a, b, zf, zf + skin, face_panels=False)
        _cut_wall(f"bulkhead_{i}_s", a, b, zn - skin, zn, face_panels=True)
        _service_cavity(f"bulkhead_{i}", a, b, zf + skin, zn - skin)
    for name, (a, b) in (
        ("brief", L.BRIEF_DOOR_X),
        ("main", L.MAIN_DOOR_X),
        ("ready", L.READY_DOOR_X),
    ):
        _jamb(f"door_{name}_jamb_a", a, zf, zn, 1)
        _jamb(f"door_{name}_jamb_b", b, zf, zn, -1)
        _threshold(f"door_{name}_threshold", a + 0.22, b - 0.22, zf, zn)
        kit.socket(
            "door",
            name,
            kit.facing_matrix(L.P((a + b) / 2, (zf + zn) / 2), 0.0),
            width=round(b - a - 0.44, 3),
        )
    _lift("lift_p", L.LIFT_P_X, car=True)
    _lift("lift_s", L.LIFT_S_X, car=False)


def _service_cavity(name: str, x0: float, x1: float, z_far: float, z_near: float) -> None:
    """Inside the bulkhead: frames on the 2.4 m grid, pipe runs, a cable tray
    and dim service lamps, cut open by the section plane at 1.1 m."""
    y_far, y_near = -z_far, -z_near
    depth = z_near - z_far
    base = kit.MeshBuilder()
    base.box((x0, y_near, -0.9), (x1, y_far, -0.8), "M_Hull_Structure")
    base.build(f"SM_{name}_cavity_base", bevel_width=0.0, nav="none")
    frames = kit.MeshBuilder()
    x = math.ceil(x0 / 2.4) * 2.4
    while x < x1 - 0.1:
        frames.box((x - 0.015, y_near, -0.8), (x + 0.015, y_far, 0.92), "M_Hull_Structure")
        frames.box((x - 0.09, y_near, 0.9), (x + 0.09, y_far, 0.94), "M_Hull_Structure")
        frames.box((x - 0.09, y_near, -0.8), (x + 0.09, y_far, -0.76), "M_Hull_Structure")
        x += 2.4
    frames.build(f"SM_{name}_cavity_frames", bevel_width=0.004, nav="none")
    pipes = kit.MeshBuilder()
    runs = (
        (0.28, 0.55, 0.11, "M_Hull_PipeInsulated"),
        (0.62, 0.12, 0.17, "M_Hull_Pipe"),
        (1.05, 0.62, 0.07, "M_Hull_Pipe"),
        (1.3, -0.25, 0.22, "M_Hull_PipeInsulated"),
        (1.5, 0.66, 0.06, "M_Hull_Pipe"),
    )
    for dz, h, r, mat in runs:
        if dz + r > depth - 0.05:
            continue
        y = y_far - dz
        pipes.tube((x0, y, h), (x1, y, h), r, mat, segments=18)
        fx = math.ceil(x0 / 2.4) * 2.4 + 1.2
        while fx < x1 - 0.2:
            pipes.tube(
                (fx - 0.05, y, h), (fx + 0.05, y, h), r + 0.03, "M_Struct_Gunmetal", segments=18
            )
            fx += 2.4
    pipes.build(f"SM_{name}_cavity_pipes", bevel_width=0.0, nav="none")
    tray = kit.MeshBuilder()
    tray.box((x0, y_near + 0.04, 0.32), (x1, y_near + 0.34, 0.34), "M_Floor_Grating")
    tray.box((x0, y_near + 0.04, 0.34), (x1, y_near + 0.055, 0.4), "M_Struct_Gunmetal")
    tray.box((x0, y_near + 0.325, 0.34), (x1, y_near + 0.34, 0.4), "M_Struct_Gunmetal")
    for k in range(6):
        yy = y_near + 0.08 + k * 0.04
        tray.tube((x0, yy, 0.36), (x1, yy, 0.36), 0.014, "M_Rubber_Black", segments=8)
    tray.build(f"SM_{name}_cavity_tray", bevel_width=0.002, nav="none")
    lx = math.ceil(x0 / 4.8) * 4.8 + 2.4
    k = 0
    while lx < x1 - 0.5:
        kit.emissive_panel(
            f"SM_{name}_cavity_lamp_{k}",
            (lx, y_far - 0.02, 0.5),
            (0.18, 0.08),
            "M_Light_Maint_Red" if k % 3 == 1 else "M_Light_Maint_Amber",
            normal="-Y",
            nav="none",
        )
        lx += 7.2
        k += 1


def _lift(name: str, xr, *, car: bool) -> None:
    """Lift shaft inside the bulkhead, its doors on the lobby (+z) side."""
    zf, zn = L.BULKHEAD_Z
    x0, x1 = xr
    t = 0.18
    walls = kit.MeshBuilder()
    walls.box((x0, -zn + 0.0, 0.0 if car else -6.0), (x0 + t, -zf, L.CUT_H), "M_Wall_PaintedMid")
    walls.box((x1 - t, -zn + 0.0, 0.0 if car else -6.0), (x1, -zf, L.CUT_H), "M_Wall_PaintedMid")
    walls.box((x0, -zf - t, 0.0 if car else -6.0), (x1, -zf, L.CUT_H), "M_Wall_PaintedMid")
    walls.build(f"SM_{name}_shaft", bevel_width=0.004)
    cap = kit.MeshBuilder()
    for a, b, c, d in ((x0, x0 + t, -zn, -zf), (x1 - t, x1, -zn, -zf), (x0, x1, -zf - t, -zf)):
        cap.box((a, c, L.CUT_H - 0.02), (b, d, L.CUT_H), "M_Section_Cap")
    cap.build(f"SM_{name}_cap", bevel_width=0.0)
    # Door frame on the lobby side.
    frame = kit.MeshBuilder()
    frame.box(
        (x0 - 0.06, -zn - 0.08, 0.0), (x0 + 0.32, -zn + 0.12, L.CUT_H + 0.02), "M_Struct_Gunmetal"
    )
    frame.box(
        (x1 - 0.32, -zn - 0.08, 0.0), (x1 + 0.06, -zn + 0.12, L.CUT_H + 0.02), "M_Struct_Gunmetal"
    )
    frame.build(f"SM_{name}_frame", bevel_width=0.008)
    _lit_edge(f"{name}_edge_a", x0 + 0.2, -zn - 0.08, 1)
    _lit_edge(f"{name}_edge_b", x1 - 0.2, -zn - 0.08, -1)
    lamps = kit.MeshBuilder()
    mat = "M_Indicator_Green" if car else "M_Indicator_Amber"
    for x in (x0 + 0.13, x1 - 0.13):
        lamps.box((x - 0.04, -zn - 0.085, 0.82), (x + 0.04, -zn - 0.078, 0.98), mat)
    lamps.build(f"SM_{name}_lamps", bevel_width=0.0).visible_shadow = False
    xi0, xi1 = x0 + t, x1 - t
    if car:
        floor = kit.MeshBuilder()
        floor.box((xi0, -zn + 0.02, -0.25), (xi1, -zf - t, 0.0), "M_Floor_GlossBlack")
        floor.build(f"SM_{name}_car_floor", bevel_width=0.0, nav="walk", room="lobby")
        ring = kit.MeshBuilder()
        cx, cy = (xi0 + xi1) / 2, -(zf + zn) / 2
        for i in range(32):
            a = 2 * math.pi * i / 32
            ring.box_c(
                (cx + 0.6 * math.cos(a), cy + 0.6 * math.sin(a), 0.002),
                (0.05, 0.05, 0.004),
                "M_Indicator_White",
            )
        ring.build(f"SM_{name}_car_ring", bevel_width=0.0, nav="walk").visible_shadow = False
        rail = kit.MeshBuilder()
        rail.tube(
            (xi0 + 0.06, -zf - t - 0.06, 0.95),
            (xi1 - 0.06, -zf - t - 0.06, 0.95),
            0.025,
            "M_Trim_Chrome",
        )
        rail.build(f"SM_{name}_car_rail", bevel_width=0.0)
        kit.socket(
            "lift",
            "main",
            kit.facing_matrix((cx, cy, 0.0), 0.0),
            station="lift",
            room="lobby",
            decks="all",
        )
    else:
        # Empty shaft: guide rails down into the dark, a dim lamp far below.
        shaft = kit.MeshBuilder()
        shaft.box((xi0, -zn + 0.1, -6.2), (xi1, -zf - t, -6.0), "M_Hull_Structure")
        for x in (xi0 + 0.08, xi1 - 0.08):
            shaft.box(
                (x - 0.03, -zf - t - 0.12, -6.0),
                (x + 0.03, -zf - t, L.CUT_H - 0.05),
                "M_Trim_BrushedSteel",
            )
        shaft.box((xi0, -zn + 0.06, -6.0), (xi1, -zn + 0.1, 0.0), "M_Hull_Structure")
        shaft.build(f"SM_{name}_void", bevel_width=0.004, nav="none")
        kit.emissive_panel(
            f"SM_{name}_void_lamp",
            ((xi0 + xi1) / 2, -zf - t - 0.01, -4.5),
            (0.3, 0.12),
            "M_Light_Maint_Amber",
            normal="-Y",
            nav="none",
        )
        leaves = kit.MeshBuilder()
        mid = (x0 + x1) / 2
        for a, b in ((x0 + 0.3, mid - 0.004), (mid + 0.004, x1 - 0.3)):
            leaves.box((a, -zn - 0.03, 0.0), (b, -zn + 0.06, L.CUT_H - 0.03), "M_Wall_PaintedDark")
        leaves.box(
            (x0 + 0.3, -zn - 0.034, L.CUT_H - 0.035),
            (x1 - 0.3, -zn + 0.064, L.CUT_H - 0.02),
            "M_Section_Cap",
        )
        leaves.build(f"SM_{name}_leaves", bevel_width=0.004)
    geo.box_ucx(f"{name}_frame", (x0 - 0.06, -zn - 0.08, 0.0), (x1 + 0.06, -zn + 0.12, L.CUT_H))
    kit.socket(
        "door",
        name,
        kit.facing_matrix(((x0 + x1) / 2, -zn, 0.0), 0.0),
        width=round(x1 - x0 - 0.6, 3),
        room="lobby",
    )


def build_aft_wall_and_chases() -> None:
    zf, zn = L.AFT_WALL_Z
    x_lo, x_hi = L.SIDE_WALL_X[0] - L.SIDE_WALL_T, L.SIDE_WALL_X[1] + L.SIDE_WALL_T
    _cut_wall("aftwall", x_lo, x_hi, zf, zn, face_panels=False)
    # Service chases between the rooms: two thin walls with risers inside.
    for name, (a, b) in (
        ("chase_p", (L.BRIEFING_X[1], L.LOBBY_X[0])),
        ("chase_s", (L.LOBBY_X[1], L.READY_X[0])),
    ):
        w = kit.MeshBuilder()
        for x0, x1 in ((a, a + 0.3), (b - 0.3, b)):
            w.box((x0, -L.ROOMS_Z[1], 0.0), (x1, -L.ROOMS_Z[0], L.ROOM_CEILING), PANEL)
        w.build(f"SM_{name}_walls", bevel_width=0.006)
        cap = kit.MeshBuilder()
        for x0, x1 in ((a, a + 0.3), (b - 0.3, b)):
            cap.box(
                (x0 - 0.004, -L.ROOMS_Z[1], L.ROOM_CEILING),
                (x1 + 0.004, -L.ROOMS_Z[0], L.ROOM_CEILING + 0.02),
                "M_Section_Cap",
            )
            cap.box(
                (x0, -L.ROOMS_Z[1] - 0.02, 0.0),
                (x1, -L.ROOMS_Z[1], L.ROOM_CEILING),
                "M_Section_Cap",
            )
        cap.build(f"SM_{name}_cap", bevel_width=0.0)
        pipes = kit.MeshBuilder()
        inner0, inner1 = a + 0.3, b - 0.3
        base = kit.MeshBuilder()
        base.box((inner0, -L.ROOMS_Z[1], -1.5), (inner1, -L.ROOMS_Z[0], -1.4), "M_Hull_Structure")
        base.build(f"SM_{name}_base", bevel_width=0.0, nav="none")
        z = L.ROOMS_Z[0] + 0.5
        k = 0
        while z < L.ROOMS_Z[1] - 0.4:
            r = (0.09, 0.14, 0.07, 0.11)[k % 4]
            x = inner0 + 0.35 + (k % 3) * 0.55
            mat = "M_Hull_PipeInsulated" if k % 3 == 1 else "M_Hull_Pipe"
            pipes.tube((x, -z, -1.4), (x, -z, L.ROOM_CEILING - 0.3), r, mat, segments=16)
            pipes.tube(
                (x, -z, L.ROOM_CEILING - 0.6),
                (x, -z, L.ROOM_CEILING - 0.52),
                r + 0.03,
                "M_Struct_Gunmetal",
                segments=16,
            )
            z += 0.9
            k += 1
        pipes.box(
            (inner1 - 0.45, -L.ROOMS_Z[1] + 0.2, -1.4),
            (inner1 - 0.1, -L.ROOMS_Z[0] - 0.2, 2.6),
            "M_Floor_Grating",
        )
        pipes.build(f"SM_{name}_risers", bevel_width=0.003, nav="none")
        kit.emissive_panel(
            f"SM_{name}_lamp",
            ((inner0 + inner1) / 2, -(L.ROOMS_Z[0] + L.ROOMS_Z[1]) / 2, 2.4),
            (0.25, 0.1),
            "M_Light_Maint_Amber",
            normal="Z",
            nav="none",
        )


# ---------------------------------------------------------------- briefing room


def build_briefing(use_kit: bool) -> None:
    if use_kit:
        _briefing_kit()
        return
    _briefing_bespoke(use_kit)


def _briefing_kit() -> None:
    """Kit conference table (12 chairs, projector, station) renamed to the
    LEVELS contract: SOCKET_seat_brief_<n>, SOCKET_holo_briefing."""
    import bpy

    cx, cz = TABLE_C
    kit.place(
        "SM_Table_Briefing",
        L.P(cx, cz),
        0.0,
        room="briefing",
        id="briefing",
        station="briefing",
        station_kind="team",
    )
    for obj in list(bpy.data.objects):
        m = re.match(r"^SOCKET_seat_briefing__0*(\d+)$", obj.name)
        if m:
            obj.name = f"SOCKET_seat_brief_{int(m.group(1))}"
    _briefing_credenza()
    for k, x in enumerate((4.8, 27.0), start=1):
        kit.place(
            "SM_Console_Standing",
            L.P(x, L.ROOMS_Z[0] + 0.45),
            0.0,
            room="briefing",
            id=f"brief_console_{k}",
        )


def _briefing_bespoke(use_kit: bool) -> None:
    cx, cz = TABLE_C
    bx, by = L.XY(cx, cz)
    rx, ry = TABLE_R
    top_outline = geo.superellipse(bx, by, rx, ry, p=4.0, n=96)
    top = kit.MeshBuilder()
    top.prism_z(top_outline, 0.70, 0.76, "M_Lacquer_BlackGloss")
    _lacquer_finish(top, "SM_brief_table_top", bevel_width=0.012, segments=3)
    edge = kit.MeshBuilder()
    edge.prism_z(
        geo.superellipse(bx, by, rx - 0.04, ry - 0.04, p=4.0, n=96),
        0.66,
        0.70,
        "M_Trim_BrushedSteel",
    )
    edge.build("SM_brief_table_edge", bevel_width=0.003)
    base = kit.MeshBuilder()
    for dx in (-2.4, 2.4):
        base.prism_z(geo.rounded_rect(bx + dx, by, 1.2, 0.7, 0.2), 0.0, 0.66, "M_Console_Body")
        base.prism_z(geo.rounded_rect(bx + dx, by, 1.4, 0.9, 0.25), 0.0, 0.05, "M_Struct_Gunmetal")
    base.build("SM_brief_table_base", bevel_width=0.008, nav="block")
    # Briefing projector: black gloss hemisphere on a short brushed collar.
    collar = kit.MeshBuilder()
    collar.prism_z(geo.ellipse(bx, by, 0.36, 0.36, 48), 0.76, 0.8, "M_Trim_BrushedSteel")
    collar.build("SM_brief_holo_collar", bevel_width=0.004)
    dome = kit.MeshBuilder()
    rings, segs, r = 8, 40, 0.3
    verts = []
    for i in range(rings + 1):
        phi = (math.pi / 2) * i / rings
        for j in range(segs):
            th = 2 * math.pi * j / segs
            verts.append(
                Vector(
                    (
                        bx + r * math.cos(phi) * math.cos(th),
                        by + r * math.cos(phi) * math.sin(th),
                        0.8 + r * math.sin(phi),
                    )
                )
            )
    faces = []
    for i in range(rings):
        for j in range(segs):
            a, b = i * segs + j, i * segs + (j + 1) % segs
            faces.append((a, b, b + segs, a + segs))
    dome._add(verts, faces, "M_Lacquer_BlackGloss", smooth=True)  # noqa: SLF001
    _lacquer_finish(dome, "SM_brief_holo_dome", bevel_width=0.0)
    lamps = kit.MeshBuilder()
    for i in range(24):
        a = 2 * math.pi * i / 24
        lamps.box_c(
            (bx + 0.355 * math.cos(a), by + 0.355 * math.sin(a), 0.79),
            (0.018, 0.018, 0.012),
            "M_Indicator_White" if i % 4 else "M_Indicator_Blue",
        )
    lamps.build("SM_brief_holo_lamps", bevel_width=0.0).visible_shadow = False
    geo.prism_ucx("brief_table", top_outline[::6], 0.0, 0.77)
    kit.socket(
        "holo",
        "briefing",
        kit.socket_matrix((bx, by, 1.1), (0, 0, 1), (0, 1, 0)),
        station="briefing",
        radius=0.9,
        height=1.2,
        room="briefing",
    )
    # Twelve chairs, six per long side; the commander stands at the east head.
    xs = [cx + d for d in (-3.25, -1.95, -0.65, 0.65, 1.95, 3.25)]
    n = 0
    for side, z in ((-1, cz - ry - 0.42), (1, cz + ry + 0.42)):
        for x in xs:
            n += 1
            sid = f"brief_{n}"
            yaw = 180.0 if side < 0 else 0.0  # north row faces the camera
            if use_kit:
                kit.place(
                    "SM_Chair_Conference",
                    L.P(x, z),
                    yaw,
                    room="briefing",
                    id=sid,
                    station="briefing",
                )
            else:
                kit.socket(
                    "seat",
                    sid,
                    kit.facing_matrix(L.P(x, z), 0.0 if side < 0 else 180.0),
                    station="briefing",
                    room="briefing",
                )
    kit.socket(
        "station",
        "briefing",
        kit.facing_matrix(L.P(cx + rx + 0.75, cz), -90.0),
        station_kind="team",
        room="briefing",
    )
    _briefing_credenza()
    if use_kit:
        for k, x in enumerate((4.8, 27.0), start=1):
            kit.place(
                "SM_Console_Standing",
                L.P(x, L.ROOMS_Z[0] + 0.45),
                0.0,
                room="briefing",
                id=f"brief_console_{k}",
            )


def _briefing_credenza() -> None:
    """Low display credenza on the far (bulkhead) wall: the room's wall screens."""
    zf = L.ROOMS_Z[0]
    x0, x1 = 6.0, 22.8
    body = kit.MeshBuilder()
    yb = -zf
    body.box((x0, yb - 0.55, 0.0), (x1, yb, 0.82), "M_Console_Body")
    body.box((x0 - 0.02, yb - 0.57, 0.0), (x1 + 0.02, yb - 0.5, 0.1), "M_Recess_Dark")
    body.prism_x(
        [(yb - 0.55, 0.82), (yb, 0.82), (yb, 1.06), (yb - 0.2, 1.06)], x0, x1, "M_Console_Body"
    )
    body.build("SM_brief_credenza", bevel_width=0.006)
    mbs = panels.builders()
    for i, sx in enumerate((8.4, 14.4, 20.4)):
        frame = geo.panel_frame((sx, yb - 0.4, 0.95), 62.0)
        panels.face(mbs, frame, 1.9, 0.34, "blank", ("cred", i))
        kit.socket(
            "screen",
            f"brief_wall_{i + 1}",
            frame @ geo.tr(0, 0, 0.03),
            size_w=1.7,
            size_h=0.26,
            station="briefing",
            room="briefing",
        )
    scr = kit.MeshBuilder()
    for sx in (8.4, 14.4, 20.4):
        with geo.xform(scr, geo.panel_frame((sx, yb - 0.4, 0.95), 62.0)):
            scr.box((-0.85, -0.13, 0.022), (0.85, 0.13, 0.026), "M_Screen")
    scr.build("SM_brief_credenza_screens", bevel_width=0.0)
    panels.finish(mbs, "SM_brief_credenza_inst")
    geo.box_ucx("brief_credenza", (x0, yb - 0.57, 0.0), (x1, yb, 1.06))


# ---------------------------------------------------------------- lobby


def build_lobby() -> None:
    cx, cz = L.AXIS_X, 38.4
    bx, by = L.XY(cx, cz)
    ring = kit.MeshBuilder()
    for r_out, r_in in ((2.4, 2.34),):
        outer = geo.ellipse(bx, by, r_out, r_out, 128)
        inner = geo.ellipse(bx, by, r_in, r_in, 128)
        for i in range(len(outer)):
            j = (i + 1) % len(outer)
            ring._add(
                [
                    Vector((*outer[i], 0.002)),
                    Vector((*outer[j], 0.002)),
                    Vector((*inner[j], 0.002)),
                    Vector((*inner[i], 0.002)),
                ],
                [(0, 1, 2, 3)],
                "M_Trim_BrushedSteel",
            )
    ring.build("SM_lobby_rings", bevel_width=0.0, nav="walk")
    lamps = kit.MeshBuilder()
    for i in range(24):
        a = 2 * math.pi * (i + 0.5) / 24
        lamps.box_c(
            (bx + 2.2 * math.cos(a), by + 2.2 * math.sin(a), 0.002),
            (0.04, 0.04, 0.004),
            "M_Indicator_White",
        )
    lamps.build("SM_lobby_ring_lamps", bevel_width=0.0, nav="walk").visible_shadow = False
    kit.socket("spawn", "commander", kit.facing_matrix(L.P(cx, 36.6), 180.0), room="lobby")
    kit.socket(
        "station",
        "lift",
        kit.facing_matrix(L.P(sum(L.LIFT_P_X) / 2, L.BULKHEAD_Z[1] + 1.0), 180.0),
        station_kind="lift",
        room="lobby",
    )
    # Two sentry posts flanking the bridge entrance.
    for name, x in (("p", L.MAIN_DOOR_X[0] - 0.9), ("s", L.MAIN_DOOR_X[1] + 0.9)):
        kit.socket(
            "stand",
            f"lobby_sentry_{name}",
            kit.facing_matrix(L.P(x, L.BULKHEAD_Z[1] + 0.7), 0.0),
            room="lobby",
        )


# ---------------------------------------------------------------- ready room


def build_ready(use_kit: bool) -> None:
    if use_kit:
        _ready_kit()
        return
    _ready_bespoke(use_kit)


def _ready_kit() -> None:
    """Kit commander's desk (station service_record) and display case."""
    cx, cz = DESK_C
    kit.place(
        "SM_Desk_Commander",
        L.P(cx, cz - 0.3),
        0.0,
        room="ready",
        id="ready_room",
        station="ready_room",
        station_kind="service_record",
    )
    for k, dx in enumerate((-0.8, 0.8)):
        kit.place(
            "SM_Chair_Conference",
            L.P(cx + dx, cz + 1.25),
            0.0,
            room="ready",
            id=f"ready_guest_{k + 1}",
        )
    kit.place("SM_Case_Display", L.P(*CASE_C), 0.0, room="ready", id="ready_case")
    _ready_viewport()
    _ready_credenza()
    _ready_lounge()


def _ready_bespoke(use_kit: bool) -> None:
    cx, cz = DESK_C
    bx, by = L.XY(cx, cz)
    desk = kit.MeshBuilder()
    desk.prism_z(geo.rounded_rect(bx, by, 2.8, 1.1, 0.12), 0.72, 0.77, "M_Lacquer_BlackGloss")
    _lacquer_finish(desk, "SM_ready_desk_top", bevel_width=0.01, segments=3)
    body = kit.MeshBuilder()
    body.box((bx - 1.3, by - 0.45, 0.0), (bx + 1.3, by - 0.38, 0.72), "M_Console_Body")
    for dx in (-1.25, 1.25):
        body.box(
            (bx + dx - 0.05, by - 0.5, 0.0), (bx + dx + 0.05, by + 0.5, 0.72), "M_Struct_Gunmetal"
        )
    body.box((bx - 1.3, by - 0.5, 0.36), (bx + 1.3, by - 0.47, 0.4), "M_Trim_BrushedSteel")
    body.build("SM_ready_desk_body", bevel_width=0.006, nav="block")
    # Flat desk display (faces up: readable from the chair and the camera).
    scr = kit.MeshBuilder()
    scr.box((bx - 0.55, by - 0.1, 0.77), (bx + 0.55, by + 0.38, 0.775), "M_Screen")
    scr.box((bx - 0.58, by - 0.13, 0.765), (bx + 0.58, by + 0.41, 0.772), "M_Console_Body")
    scr.build("SM_ready_desk_display", bevel_width=0.002)
    kit.socket(
        "screen",
        "ready",
        kit.socket_matrix((bx, by + 0.14, 0.777), (0, 0, 1), (0, -1, 0)),
        size_w=1.1,
        size_h=0.48,
        station="ready_room",
        room="ready",
    )
    geo.box_ucx("ready_desk", (bx - 1.4, by - 0.55, 0.0), (bx + 1.4, by + 0.55, 0.78))
    chair_z = cz - 1.0
    if use_kit:
        kit.place(
            "SM_Chair_Commander",
            L.P(cx, chair_z),
            180.0,
            room="ready",
            id="ready",
            station="ready_room",
        )
    kit.socket(
        "station",
        "ready_room",
        kit.facing_matrix(L.P(cx, cz + 1.3), 180.0),
        station_kind="service_record",
        room="ready",
    )
    # Visitors' chairs on the camera side of the desk.
    if use_kit:
        for k, dx in enumerate((-0.8, 0.8)):
            kit.place(
                "SM_Chair_Conference",
                L.P(cx + dx, cz + 1.05),
                0.0,
                room="ready",
                id=f"ready_guest_{k + 1}",
            )
    _display_case()
    _ready_viewport()
    _ready_credenza()
    _ready_lounge()


def _display_case() -> None:
    """Glass case with a model of the ship on a plinth."""
    cx, cz = CASE_C
    bx, by = L.XY(cx, cz)
    plinth = kit.MeshBuilder()
    plinth.box((bx - 0.75, by - 0.45, 0.0), (bx + 0.75, by + 0.45, 0.9), "M_Console_Body")
    plinth.box((bx - 0.78, by - 0.48, 0.9), (bx + 0.78, by + 0.48, 0.94), "M_Trim_BrushedSteel")
    plinth.box((bx - 0.6, by - 0.461, 0.3), (bx + 0.6, by - 0.45, 0.36), "M_Trim_BrushedSteel")
    plinth.build("SM_ready_case_plinth", bevel_width=0.006, nav="block")
    glass = kit.MeshBuilder()
    glass.box((bx - 0.72, by - 0.42, 0.94), (bx + 0.72, by + 0.42, 1.6), "M_Glass_Viewport")
    g = glass.build("SM_ready_case_glass", bevel_width=0.0)
    g.visible_shadow = False
    frame = kit.MeshBuilder()
    for sx in (-1, 1):
        for sy in (-1, 1):
            frame.box(
                (bx + sx * 0.72 - 0.015, by + sy * 0.42 - 0.015, 0.94),
                (bx + sx * 0.72 + 0.015, by + sy * 0.42 + 0.015, 1.62),
                "M_Trim_BrushedSteel",
            )
    frame.box((bx - 0.735, by - 0.435, 1.6), (bx + 0.735, by + 0.435, 1.63), "M_Trim_BrushedSteel")
    frame.build("SM_ready_case_frame", bevel_width=0.002)
    model = kit.MeshBuilder()
    model.tube((bx, by, 0.94), (bx, by, 1.08), 0.015, "M_Trim_Chrome", segments=10)
    wedge = [(bx - 0.5, by - 0.17), (bx + 0.55, by), (bx - 0.5, by + 0.17)]
    model.prism_z(wedge, 1.08, 1.14, "M_Wall_PaintedLight")
    model.prism_z(
        [(bx - 0.5, by - 0.12), (bx + 0.2, by), (bx - 0.5, by + 0.12)],
        1.14,
        1.17,
        "M_Wall_PaintedLight",
    )
    model.box((bx - 0.42, by - 0.06, 1.17), (bx - 0.28, by + 0.06, 1.24), "M_Wall_PaintedLight")
    model.build("SM_ready_case_model", bevel_width=0.003)
    light = kit.emissive_panel(
        "SM_ready_case_light", (bx, by, 1.595), (1.3, 0.7), "M_Light_FloorInlay", normal="-Z"
    )
    light.visible_camera = False
    geo.box_ucx("ready_case", (bx - 0.78, by - 0.48, 0.0), (bx + 0.78, by + 0.48, 1.63))


def _ready_viewport() -> None:
    """Corner hull wall with two slit viewports (3.6 m, hides nothing walkable)."""
    a, b = (L.READY_X[1] - 3.6, L.ROOMS_Z[0]), (L.READY_X[1], L.ROOMS_Z[0] + 3.6)
    seg, length = geo.segment_matrix(a, b)
    wall = kit.MeshBuilder(seg)
    x0, x1 = -length / 2, length / 2
    slits = (-0.9, 0.9)
    sw = 0.42
    z0, z1 = 0.5, 3.0
    wall.box((x0 - 0.3, 0.0, 0.0), (x1 + 0.3, 0.6, 0.15), "M_Wall_PaintedDark")
    edges = [x0 - 0.3]
    for s in slits:
        edges += [s - sw / 2, s + sw / 2]
    edges.append(x1 + 0.3)
    for i in range(0, len(edges), 2):
        wall.box((edges[i], 0.0, 0.15), (edges[i + 1], 0.6, L.ROOM_CEILING), PANEL)
    for s in slits:
        wall.box((s - sw / 2, 0.0, 0.15), (s + sw / 2, 0.6, z0), PANEL)
        wall.box((s - sw / 2, 0.0, z1), (s + sw / 2, 0.6, L.ROOM_CEILING), PANEL)
        wall.box(
            (s - sw / 2 - 0.06, -0.04, z0 - 0.06),
            (s + sw / 2 + 0.06, 0.0, z0),
            "M_Trim_BrushedSteel",
        )
    wall.box(
        (x0 - 0.3, -0.004, L.ROOM_CEILING - 0.02), (x1 + 0.3, 0.6, L.ROOM_CEILING), "M_Section_Cap"
    )
    wall.build("SM_ready_viewport_wall", bevel_width=0.006)
    stars = kit.MeshBuilder(seg)
    for s in slits:
        stars.quad(
            [
                (s - 0.5, 0.62, z0 - 1.4),
                (s + 0.5, 0.62, z0 - 1.4),
                (s + 0.5, 0.62, z1 + 0.2),
                (s - 0.5, 0.62, z1 + 0.2),
            ],
            "M_Starfield",
        )
    st = stars.build("SM_ready_viewport_stars", bevel_width=0.0, nav="none")
    st.visible_shadow = False
    st.visible_diffuse = False
    from .viewport import STAR_SCALE, scale_texture

    scale_texture(st, STAR_SCALE)
    geo.matrix_ucx("ready_viewport", seg, (x0 - 0.3, 0.0, 0.0), (x1 + 0.3, 0.6, L.ROOM_CEILING))
    # Solid hull corner behind the slits (never an empty pocket of floor).
    off = 0.64 * 2**0.5
    corner = L.poly([(a[0] + off, a[1]), (b[0], a[1]), (b[0], b[1] - off)])
    block = kit.MeshBuilder()
    block.prism_z(corner, -0.3, L.ROOM_CEILING, "M_Hull_Structure", cap_material="M_Section_Cap")
    block.build("SM_ready_hull_corner", bevel_width=0.0, nav="block")


def _ready_credenza() -> None:
    zf = L.ROOMS_Z[0]
    x0, x1 = 50.4, 62.4
    yb = -zf
    mb = kit.MeshBuilder()
    mb.box((x0, yb - 0.5, 0.0), (x1, yb, 0.85), "M_Console_Body")
    mb.box((x0, yb - 0.52, 0.0), (x1, yb - 0.46, 0.09), "M_Recess_Dark")
    n = 5
    for i in range(n):
        a = x0 + i * (x1 - x0) / n
        b = a + (x1 - x0) / n
        mb.box((a + 0.01, yb - 0.505, 0.12), (b - 0.01, yb - 0.49, 0.8), "M_Wall_PaintedDark")
        mb.box(
            ((a + b) / 2 - 0.12, yb - 0.52, 0.66),
            ((a + b) / 2 + 0.12, yb - 0.505, 0.68),
            "M_Trim_BrushedSteel",
        )
    mb.box((x0 - 0.01, yb - 0.51, 0.85), (x1 + 0.01, yb, 0.88), "M_Lacquer_BlackGloss")
    _lacquer_finish(mb, "SM_ready_credenza", bevel_width=0.005)
    geo.box_ucx("ready_credenza", (x0, yb - 0.52, 0.0), (x1, yb, 0.88))


def build(use_kit: bool) -> None:
    build_floors()
    build_bulkhead()
    build_aft_wall_and_chases()
    build_briefing(use_kit)
    build_lobby()
    build_ready(use_kit)


def _ready_lounge() -> None:
    """Visitors' corner: a low sofa facing the room, a lacquer coffee table
    and a matte rug, west of the desk."""
    cx, cz = 48.6, 39.0
    bx, by = L.XY(cx, cz)
    rug = kit.MeshBuilder()
    rug.box((bx - 2.4, by - 1.8, 0.0), (bx + 2.4, by + 1.8, 0.012), "M_Rubber_Black")
    rug.build("SM_ready_rug", bevel_width=0.004, nav="walk")
    sofa = kit.MeshBuilder()
    sy = by + 1.15  # north side, facing the camera
    sofa.box((bx - 1.3, sy - 0.45, 0.012), (bx + 1.3, sy + 0.45, 0.2), "M_Struct_Gunmetal")
    sofa.box((bx - 1.25, sy - 0.42, 0.2), (bx + 1.25, sy + 0.1, 0.42), "M_Seat_Upholstery")
    sofa.box((bx - 1.25, sy + 0.1, 0.2), (bx + 1.25, sy + 0.42, 0.78), "M_Seat_Upholstery")
    for dx in (-1.3, 1.3):
        sofa.box(
            (bx + dx - 0.14, sy - 0.42, 0.2), (bx + dx + 0.14, sy + 0.42, 0.58), "M_Seat_Upholstery"
        )
    sofa.build("SM_ready_sofa", bevel_width=0.03, segments=3, nav="block")
    seams = kit.MeshBuilder()
    for dx in (-0.42, 0.42):
        seams.box(
            (bx + dx - 0.006, sy - 0.425, 0.3), (bx + dx + 0.006, sy + 0.1, 0.425), "M_Rubber_Black"
        )
    seams.build("SM_ready_sofa_seams", bevel_width=0.0)
    table = kit.MeshBuilder()
    table.prism_z(geo.rounded_rect(bx, by - 0.1, 1.5, 0.8, 0.1), 0.36, 0.4, "M_Lacquer_BlackGloss")
    _lacquer_finish(table, "SM_ready_coffee_top", bevel_width=0.006, segments=2)
    legs = kit.MeshBuilder()
    legs.prism_z(geo.rounded_rect(bx, by - 0.1, 1.2, 0.5, 0.08), 0.012, 0.36, "M_Console_Body")
    legs.build("SM_ready_coffee_base", bevel_width=0.004, nav="block")
    geo.box_ucx("ready_sofa", (bx - 1.45, sy - 0.45, 0.0), (bx + 1.45, sy + 0.45, 0.78))
    kit.socket(
        "seat", "ready_sofa_1", kit.facing_matrix((bx - 0.6, sy - 0.1, 0.42), 0.0), room="ready"
    )
    kit.socket(
        "seat", "ready_sofa_2", kit.facing_matrix((bx + 0.6, sy - 0.1, 0.42), 0.0), room="ready"
    )
