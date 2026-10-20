"""The two sunken crew pits either side of the command walkway.

Each pit (1.4 m deep) reads in three lit bands toward the camera:

1. the forward systems wall: instrument banks lining the pit's far wall and
   its chamfer, lit by a down-light hidden under the coping;
2. row 1: a rack wall of instruments with a long console desk in front of
   it, four crew stations (kit consoles with chairs) set into the desk;
3. row 2: the same, further aft.

Crew sit on the camera side of their consoles facing the viewports and are
seen over the shoulder. Stairs come down from the walkway rim into the two
aisles behind the crew. Seat sockets are numbered from the walkway outward,
row 1 first: ``pit_p_1`` .. ``pit_p_8`` and ``pit_s_1`` .. ``pit_s_8``.
"""

from __future__ import annotations

from lib import kit
from mathutils import Vector

from . import geo, panels
from . import layout as L

BANK_DEPTH = 0.5
RACK_H = 1.55
DESK_H = 0.76
DESK_D = 0.84
# Four console rows per pit (plan z of each rack face); rows 2 and 3 are the
# crew rows, rows 1 and 4 are unmanned instrument banks.
ROW_RACK_Z = (10.8, 15.6, 20.4, 25.2)
MANNED = (False, True, True, False)
# Rack height and whether the row has a desk run in front of it.
ROW_RACK_H = (1.95, 1.55, 1.55, 1.2)
ROW_DESK = (False, True, True, True)
ROW_X_INNER = 28.2  # port; starboard mirrored
SEAT_X = (11.1, 15.9, 20.7, 25.5)  # port console centres, outer to inner
STAIR_Z = (19.1, 23.9)
CONSOLE = "SM_Console_CrewPit"
CONSOLE_B = "SM_Console_CrewPitB"


def _side_name(side: int) -> str:
    return "p" if side < 0 else "s"


def _sx(x: float, side: int) -> float:
    return x if side < 0 else L.mirror_x(x)


def _edges(side: int):
    """Pit outline edges with the pit on the right of travel, classified."""
    pts = L.pit_outline(side)
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        if abs(a[0] - b[0]) < 1e-6 and a[0] in L.SIDE_WALL_X:
            kind = "side"
        elif abs(a[1] - b[1]) < 1e-6:
            kind = "forward" if abs(a[1] - L.FORWARD_EDGE_Z) < 1e-6 else "aft"
        elif abs(a[0] - b[0]) < 1e-6:
            kind = "inner"
        else:
            kind = "chamfer"
        out.append((kind, a, b))
    return out


def build_floor(side: int) -> None:
    n = _side_name(side)
    mb = kit.MeshBuilder()
    mb.prism_z(L.poly(L.pit_outline(side)), L.PIT_Z - 0.25, L.PIT_Z, "M_Floor_GlossBlack")
    mb.build(f"SM_pit_{n}_floor", bevel_width=0.0, nav="walk", room=f"pit_{n}")


def build_copings(side: int) -> None:
    """Light-grey coping on every open pit edge, with a hidden down-light."""
    n = _side_name(side)
    for kind, a, b in _edges(side):
        if kind == "side":
            continue
        seg, length = geo.segment_matrix(a, b)
        x0, x1 = -length / 2, length / 2
        mb = kit.MeshBuilder(seg)
        ext = 0.3 if kind in ("chamfer",) else 0.0
        # Coping (style bible 2.10): 0.3 m brushed lip, 5 cm upstand, open at
        # the stair heads on the walkway side.
        spans = [(x0 - ext, x1 + ext)]
        if kind == "inner":
            d = (Vector(L.XY(*b)) - Vector(L.XY(*a))).normalized()
            mid = (Vector(L.XY(*a)) + Vector(L.XY(*b))) / 2
            cuts = sorted((Vector(L.XY(a[0], z)) - mid).dot(d) for z in STAIR_Z)
            spans = []
            start = x0
            for c in cuts:
                spans.append((start, c - 1.2))
                start = c + 1.2
            spans.append((start, x1))
        for sa, sb in spans:
            mb.box((sa, -0.03, -0.17), (sb, 0.3, 0.0), "M_Wall_PaintedMid")
            mb.box((sa, -0.035, 0.0), (sb, 0.3, 0.05), "M_Trim_BrushedSteel")
            mb.box((sa, -0.04, -0.012), (sb, -0.03, 0.0), "M_Recess_Dark")
        mb.build(f"SM_pit_{n}_coping_{kind}", bevel_width=0.006, nav="walk")
        rim = kit.MeshBuilder(seg)
        for sa, sb in spans:
            rim.quad(
                [
                    (sa + 0.05, 0.03, 0.0505),
                    (sb - 0.05, 0.03, 0.0505),
                    (sb - 0.05, 0.045, 0.0505),
                    (sa + 0.05, 0.045, 0.0505),
                ],
                "M_Light_FloorInlay",
            )
        lit = rim.build(f"SM_pit_{n}_rim_light_{kind}", bevel_width=0.0, nav="walk")
        lit.visible_shadow = False
        lit["light_kind"] = "pit_rim"
        if kind in ("forward", "chamfer", "inner"):
            centre = seg @ Vector((0.0, -0.015, -0.175))
            w = length - 0.4
            xa = seg.to_3x3() @ Vector((1, 0, 0))
            ya = seg.to_3x3() @ Vector((0, 1, 0))
            c = Vector(centre)
            corners = [c - xa * w / 2 - ya * 0.02, c + xa * w / 2 - ya * 0.02]
            corners += [c + xa * w / 2 + ya * 0.02, c - xa * w / 2 + ya * 0.02]
            obj = kit.mesh_object(
                f"SM_pit_{n}_downlight_{kind}",
                corners,
                [(0, 1, 2, 3)],
                "M_Light_WallStrip",
                nav="none",
            )
            normal = (corners[1] - corners[0]).cross(corners[2] - corners[1])
            if normal.z > 0:
                obj.data.flip_normals()
            obj["light_kind"] = "pit_downlight"


def build_systems_wall(side: int) -> None:
    """Instrument banks lining the pit's forward wall and chamfer."""
    n = _side_name(side)
    for kind, a, b in _edges(side):
        if kind not in ("forward", "chamfer"):
            continue
        seg, length = geo.segment_matrix(a, b)
        x0 = -length / 2
        count = max(1, round(length / L.M))
        step = length / count
        carcass = kit.MeshBuilder(seg)
        mbs = panels.builders()
        for m in (mbs["body"], mbs["keys"], mbs["lamps"]):
            m.matrix = seg
        top = -0.19
        h = top - L.PIT_Z
        carcass.box((x0, -BANK_DEPTH, L.PIT_Z), (-x0, 0.0, L.PIT_Z + 0.12), "M_Wall_PaintedDark")
        for i in range(count):
            a_x, b_x = x0 + i * step, x0 + (i + 1) * step
            carcass.box(
                (a_x + 0.006, -BANK_DEPTH + 0.02, L.PIT_Z + 0.12),
                (b_x - 0.006, 0.0, top),
                "M_Console_Body",
            )
            carcass.box(
                (a_x - 0.01, -BANK_DEPTH - 0.004, L.PIT_Z + 0.12),
                (a_x + 0.01, -BANK_DEPTH + 0.03, top),
                "M_Struct_Gunmetal",
            )
            cx = (a_x + b_x) / 2
            fz = L.PIT_Z + 0.12 + (h - 0.12) / 2
            frame = geo.panel_frame((cx, -BANK_DEPTH + 0.02, fz))
            style = panels.style_for((n, kind), i)
            panels.face(mbs, frame, step - 0.06, h - 0.2, style, (n, kind, i))
        # Vertical light bars between every two 0.6 m bays (style bible 2.10):
        # three stacked backlit rectangles in a dark reveal.
        bars = kit.MeshBuilder(seg)
        reveal = kit.MeshBuilder(seg)
        zc = L.PIT_Z + 0.12 + (h - 0.12) / 2
        for i in range(count + 1):
            bx = x0 + i * step
            if kind == "chamfer" and i in (0, count):
                continue
            reveal.box(
                (bx - 0.045, -BANK_DEPTH - 0.012, zc - 0.5),
                (bx + 0.045, -BANK_DEPTH + 0.03, zc + 0.5),
                "M_Recess_Dark",
            )
            for k in (-1, 0, 1):
                zz = zc + k * 0.31
                bars.box(
                    (bx - 0.025, -BANK_DEPTH - 0.016, zz - 0.14),
                    (bx + 0.025, -BANK_DEPTH - 0.01, zz + 0.14),
                    "M_Light_Backlit",
                )
        reveal.build(f"SM_pit_{n}_syswall_{kind}_reveals", bevel_width=0.003)
        lit = bars.build(f"SM_pit_{n}_syswall_{kind}_bars", bevel_width=0.0, nav="none")
        lit.visible_shadow = False
        if kind == "forward":
            # Red angled light slabs at the pit's forward corners.
            slab = kit.MeshBuilder(seg)
            for end in (x0 + 0.5, -x0 - 0.5):
                with geo.xform(
                    slab,
                    geo.tr(end, -BANK_DEPTH - 0.02, zc)
                    @ geo.panel_frame((0, 0, 0))
                    @ geo.tr(rz_deg=35.0),
                ):
                    slab.box((-0.075, -0.45, 0.0), (0.075, 0.45, 0.012), "M_Light_RedTrim")
            red = slab.build(f"SM_pit_{n}_red_slabs", bevel_width=0.0, nav="none")
            red.visible_shadow = False
        carcass.build(f"SM_pit_{n}_syswall_{kind}", bevel_width=0.004)
        panels.finish(mbs, f"SM_pit_{n}_syswall_{kind}")
        geo.matrix_ucx(f"pit_{n}_syswall_{kind}", seg, (x0, -BANK_DEPTH, L.PIT_Z), (-x0, 0.0, top))


def _console_back_offset(name: str) -> float:
    """Distance from a kit console's origin to its back face (local +Y)."""
    master = kit.build_master(name)
    ys = []
    for obj in master.all_objects:
        if obj.type != "MESH":
            continue
        for v in obj.data.vertices:
            ys.append((obj.matrix_basis @ v.co).y)
    return max(ys) if ys else 0.42


def _row_x_outer(rack_z: float) -> float:
    """Outer end of a row: clear of the chamfer and the side wall."""
    (cx0, cz0), (cx1, cz1) = L.PIT_CHAMFER
    k = (cx0 - cx1) / (cz1 - cz0)  # chamfer: x = cx0 - k * (z - cz0)
    x_chamfer = cx0 - k * (rack_z - 0.6 - cz0)
    return max(L.SIDE_WALL_X[0] + 1.2, round((x_chamfer + 0.7) / 0.6) * 0.6)


def build_rows(side: int, use_kit: bool) -> list[dict]:
    """Four rows: rack wall + desk run each; the two crew rows carry four
    crew stations (kit consoles with chairs) set into the desk."""
    n = _side_name(side)
    seats = []
    back = _console_back_offset(CONSOLE) if use_kit else DESK_D
    crew_row = 0
    for r, rack_z in enumerate(ROW_RACK_Z):
        x_lo, x_hi = sorted((_sx(_row_x_outer(rack_z), side), _sx(ROW_X_INNER, side)))
        _rack_wall(f"pit_{n}_r{r + 1}", x_lo, x_hi, rack_z, side, ROW_RACK_H[r])
        consoles = [_sx(x, side) for x in SEAT_X] if MANNED[r] else []
        if ROW_DESK[r]:
            _desk_runs(f"pit_{n}_r{r + 1}", x_lo, x_hi, rack_z, consoles)
        if not MANNED[r]:
            continue
        # Numbering: from the walkway outward, front crew row first.
        order = sorted(consoles, key=lambda x: abs(x - L.AXIS_X))
        for k, cx in enumerate(order):
            num = crew_row * 4 + k + 1
            sid = f"pit_{n}_{num}"
            if use_kit:
                piece = CONSOLE if (num % 2) else CONSOLE_B
                kit.place(
                    piece,
                    L.P(cx, rack_z + back, L.PIT_Z),
                    0.0,
                    room=f"pit_{n}",
                    id=sid,
                    row=crew_row + 1,
                    order=num,
                )
            _station_pad(sid, cx, rack_z)
            seats.append({"id": sid, "x": cx, "z": rack_z + 1.2, "row": crew_row + 1})
        crew_row += 1
    return seats


def _station_pad(sid: str, cx: float, rack_z: float) -> None:
    """Dark deck plate under one crew station, brushed edge and a pair of
    flush marker lamps at its aisle edge: each station reads on its own."""
    x0, x1 = cx - 0.62, cx + 0.62
    y0, y1 = -(rack_z + 2.0), -rack_z
    z = L.PIT_Z
    pad = kit.MeshBuilder()
    pad.box((x0, y0, z), (x1, y1, z + 0.012), "M_Floor_SatinDark")
    for a, b in (
        ((x0 - 0.02, y0 - 0.02), (x1 + 0.02, y0)),
        ((x0 - 0.02, y0), (x0, y1)),
        ((x1, y0), (x1 + 0.02, y1)),
    ):
        pad.box((a[0], a[1], z), (b[0], b[1], z + 0.014), "M_Trim_BrushedSteel")
    pad.build(f"SM_{sid}_pad", bevel_width=0.002, nav="walk")
    lamps = kit.MeshBuilder()
    for dx in (-0.12, 0.12):
        lamps.quad(
            [
                (cx + dx - 0.06, y0 + 0.05, z + 0.0145),
                (cx + dx + 0.06, y0 + 0.05, z + 0.0145),
                (cx + dx + 0.06, y0 + 0.08, z + 0.0145),
                (cx + dx - 0.06, y0 + 0.08, z + 0.0145),
            ],
            "M_Light_FloorInlay",
        )
    obj = lamps.build(f"SM_{sid}_pad_lamps", bevel_width=0.0, nav="walk")
    obj.visible_shadow = False


def build_ledges(side: int) -> None:
    """Stepped pit walls: a ledge half-way down along the walkway and hull
    sides, brushed nosing and a thin lit edge (reads the 1.4 m depth)."""
    n = _side_name(side)
    inner = L.RIM_X[0] if side < 0 else L.RIM_X[1]
    outer = L.SIDE_WALL_X[0] if side < 0 else L.SIDE_WALL_X[1]
    d = -1 if side < 0 else 1  # direction from the inner wall into the pit
    spans_inner = []
    z0 = L.FORWARD_EDGE_Z
    for zc in STAIR_Z:
        spans_inner.append((z0, zc - 1.25))
        z0 = zc + 1.25
    spans_inner.append((z0, L.AFT_EDGE_Z))
    (_, _), (_, cz1) = L.PIT_CHAMFER
    runs = [(inner, d, a, b) for a, b in spans_inner] + [(outer, -d, cz1 + 0.6, L.AFT_EDGE_Z)]
    body = kit.MeshBuilder()
    nose = kit.MeshBuilder()
    lit = kit.MeshBuilder()
    w, top = 0.42, L.PIT_Z + 0.7
    for wall_x, into, za, zb in runs:
        xa, xb = sorted((wall_x, wall_x + into * w))
        edge = wall_x + into * w
        body.box((xa, -zb, L.PIT_Z), (xb, -za, top - 0.04), "M_Wall_PaintedDark")
        ea, eb = sorted((edge, edge - into * 0.06))
        nose.box((ea, -zb, top - 0.04), (eb, -za, top), "M_Trim_BrushedSteel")
        na, nb = sorted((wall_x, edge - into * 0.06))
        nose.box((na, -zb, top - 0.04), (nb, -za, top - 0.01), "M_Wall_PaintedMid")
        la, lb = sorted((edge - into * 0.075, edge - into * 0.09))
        lit.quad(
            [
                (la, -zb + 0.05, top - 0.0095),
                (lb, -zb + 0.05, top - 0.0095),
                (lb, -za - 0.05, top - 0.0095),
                (la, -za - 0.05, top - 0.0095),
            ],
            "M_Light_FloorInlay",
        )
    body.build(f"SM_pit_{n}_ledges", bevel_width=0.004, nav="block")
    nose.build(f"SM_pit_{n}_ledge_nosing", bevel_width=0.003, nav="block")
    obj = lit.build(f"SM_pit_{n}_ledge_light", bevel_width=0.0, nav="none")
    obj.visible_shadow = False


def _rack_wall(
    name: str, x_lo: float, x_hi: float, rack_z: float, side: int, rack_h: float = RACK_H
) -> None:
    """Instrument rack wall facing the camera (the crew's forward view)."""
    count = max(1, round((x_hi - x_lo) / L.M))
    step = (x_hi - x_lo) / count
    z0, z1 = L.PIT_Z, L.PIT_Z + rack_h
    carcass = kit.MeshBuilder()
    top = kit.MeshBuilder()
    mbs = panels.builders()
    yf = -rack_z  # Blender Y of the rack face
    carcass.box((x_lo, yf, z0), (x_hi, yf + BANK_DEPTH, z0 + 0.1), "M_Wall_PaintedDark")
    for i in range(count):
        a, b = x_lo + i * step, x_lo + (i + 1) * step
        carcass.box(
            (a + 0.005, yf + 0.015, z0 + 0.1), (b - 0.005, yf + BANK_DEPTH, z1), "M_Console_Body"
        )
        carcass.box(
            (a - 0.012, yf - 0.006, z0 + 0.1), (a + 0.012, yf + 0.03, z1), "M_Struct_Gunmetal"
        )
        cx = (a + b) / 2
        frame = geo.panel_frame((cx, yf + 0.015, z0 + 0.1 + (rack_h - 0.1) / 2))
        style = panels.style_for((name, side), i)
        panels.face(mbs, frame, step - 0.06, rack_h - 0.22, style, (name, i))
        # Top: perforated vent plate between brushed rails (seen from above).
        top.box(
            (a + 0.04, yf + 0.06, z1),
            (b - 0.04, yf + BANK_DEPTH - 0.06, z1 + 0.01),
            "M_Floor_Grating",
        )
    carcass.box(
        (x_hi - 0.012, yf - 0.006, z0 + 0.1), (x_hi + 0.012, yf + 0.03, z1), "M_Struct_Gunmetal"
    )
    top.box((x_lo, yf, z1), (x_hi, yf + 0.05, z1 + 0.02), "M_Trim_BrushedSteel")
    top.box(
        (x_lo, yf + BANK_DEPTH - 0.05, z1),
        (x_hi, yf + BANK_DEPTH, z1 + 0.02),
        "M_Trim_BrushedSteel",
    )
    carcass.build(f"SM_{name}_rack", bevel_width=0.004)
    top.build(f"SM_{name}_rack_top", bevel_width=0.002)
    panels.finish(mbs, f"SM_{name}_rack")
    geo.box_ucx(f"{name}_rack", (x_lo, yf, z0), (x_hi, yf + BANK_DEPTH, z1 + 0.02))


def _desk_runs(name: str, x_lo: float, x_hi: float, rack_z: float, consoles: list[float]) -> None:
    """Unmanned desk modules between the crew consoles."""
    half = 0.46 + 0.62  # clear gap either side: every crew station reads on its own
    cuts = sorted(consoles)
    spans = []
    start = x_lo
    for cx in cuts:
        spans.append((start, cx - half))
        start = cx + half
    spans.append((start, x_hi))
    body = kit.MeshBuilder()
    deck = kit.MeshBuilder()
    mbs = panels.builders()
    yb = -rack_z  # desk back against the rack face
    yf = yb - DESK_D
    z0 = L.PIT_Z
    for j, (a, b) in enumerate(spans):
        if b - a < 0.3:
            continue
        body.box((a, yf + 0.3, z0), (b, yb, z0 + DESK_H - 0.04), "M_Console_Body")
        body.box((a, yf + 0.26, z0), (b, yf + 0.32, z0 + 0.08), "M_Recess_Dark")
        deck.box((a, yf - 0.02, z0 + DESK_H - 0.04), (b, yb, z0 + DESK_H), "M_Console_Deck")
        deck.box(
            (a, yf - 0.035, z0 + DESK_H - 0.05),
            (b, yf - 0.015, z0 + DESK_H + 0.005),
            "M_Rubber_Black",
        )
        # Sloped instrument riser at the back of the desk.
        deck.prism_x(
            [
                (yb - 0.38, z0 + DESK_H),
                (yb, z0 + DESK_H),
                (yb, z0 + DESK_H + 0.3),
                (yb - 0.12, z0 + DESK_H + 0.3),
            ],
            a + 0.01,
            b - 0.01,
            "M_Console_Body",
        )
        count = max(1, round((b - a) / 0.6))
        step = (b - a) / count
        for i in range(count):
            cx = a + (i + 0.5) * step
            frame = geo.panel_frame((cx, yb - 0.25, z0 + DESK_H + 0.15), 52.0)
            style = ("matrix", "slats", "blank", "legend2")[kit.seed_for(name, j, i) % 4]
            if step > 0.4:
                panels.face(
                    mbs,
                    frame,
                    step - 0.08,
                    0.3,
                    style if style != "legend2" else "matrix",
                    (name, j, i),
                )
    body.build(f"SM_{name}_desk", bevel_width=0.006)
    deck.build(f"SM_{name}_desk_top", bevel_width=0.004)
    panels.finish(mbs, f"SM_{name}_desk_inst")
    geo.box_ucx(f"{name}_desk", (x_lo, yf, z0), (x_hi, yb, z0 + DESK_H + 0.3))


def build_stairs(side: int, use_kit: bool) -> list[str]:
    n = _side_name(side)
    rim = L.RIM_X[0] if side < 0 else L.RIM_X[1]
    ids = []
    for k, z in enumerate(STAIR_Z):
        sid = f"step_{n}_{k + 1}"
        if use_kit:
            kit.place(
                "SM_Stairs_240_H140",
                L.P(rim, z, 0.0),
                180.0 if side < 0 else 0.0,
                room=f"pit_{n}",
                id=sid,
            )
        ids.append(sid)
    return ids


def build_railings(side: int, use_kit: bool, enabled: bool = False) -> None:
    """Guard rails on the forward, chamfer and aft pit edges. Off by default:
    the reference pits are railing-poor (style bible 2.8)."""
    if not use_kit or not enabled:
        return
    n = _side_name(side)
    for kind, a, b in _edges(side):
        if kind not in ("forward", "aft", "chamfer"):
            continue
        seg, length = geo.segment_matrix(a, b)
        count = int(length // 2.4)
        rest = length - count * 2.4
        x = -length / 2 + rest / 2
        for i in range(count):
            p = seg @ Vector((x + 1.2, 0.2, 0.0))
            yaw = seg.to_euler().z
            import math

            kit.place(
                "SM_Railing_240",
                (p.x, p.y, 0.0),
                math.degrees(yaw),
                id=f"rail_{n}_{kind}_{i:02d}",
                nav="block",
            )
            x += 2.4


def build(side: int, use_kit: bool) -> dict:
    build_floor(side)
    build_ledges(side)
    build_copings(side)
    build_systems_wall(side)
    seats = build_rows(side, use_kit)
    stairs = build_stairs(side, use_kit)
    build_railings(side, use_kit)
    return {"seats": seats, "stairs": stairs}
