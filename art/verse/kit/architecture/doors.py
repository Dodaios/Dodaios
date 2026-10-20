"""Blast doors and turbolift doors.

Piece space as for walls: the door sits in a wall running along X, room face
at Y = 0 toward -Y, floor at Z = 0, centred on X.

* ``SM_BlastDoor_240`` (+ ``_Closed``, ``_Cut``, ``_Cut_Closed``): 3.6 m wide
  heavy frame with chamfered jambs around a 2.4 x 3.0 m opening. Open doors
  show only the leaf edges in the jamb pockets. Cut variants stop at 1.1 m
  with a section cap (BRIEF section 5). ``SOCKET_door`` at the threshold.
* ``SM_Turbolift_Door`` - a 2.4 m full-height wall module with a lift alcove,
  lit surround and call lamp; sockets ``lift`` (at the doors, facing the
  camera) and ``spawn`` (1.2 m in front).
* ``SM_Turbolift_Lobby_480`` - two lifts side by side.
"""

from __future__ import annotations

from lib import kit

from . import walls

OPENING_W = 2.4
OPENING_H = 3.0
FRAME_W = 0.6
FRAME_FRONT = -0.15  # frame stands proud of the wall face
FRAME_BACK = 0.45
LEAF_T = 0.08


def _jamb(sign: int, top: float) -> list[tuple[float, float]]:
    """Top-view polygon of one jamb, its inner face chamfered toward the room."""
    o, i = OPENING_W / 2, OPENING_W / 2
    pts = [
        (o + FRAME_W, FRAME_FRONT),
        (i + 0.2, FRAME_FRONT),
        (i, FRAME_FRONT + 0.2),
        (i, FRAME_BACK),
        (o + FRAME_W, FRAME_BACK),
    ]
    pts = [(sign * x, y) for x, y in pts]
    return pts if sign > 0 else list(reversed(pts))


def build_blast_door(*, closed: bool = False, cut: bool = False) -> None:
    name = "SM_BlastDoor_240" + ("_Cut" if cut else "") + ("_Closed" if closed else "")
    top = walls.CUT_HEIGHT if cut else walls.HEIGHT
    hw = OPENING_W / 2
    frame = kit.MeshBuilder()
    for sign in (-1, 1):
        frame.prism_z(_jamb(sign, top), 0.0, top - 0.02, "M_Struct_Gunmetal")
        poly = _jamb(sign, top)
        frame.prism_z(poly, top - 0.02, top, "M_Section_Cap")
    if not cut:
        frame.box(
            (-hw - FRAME_W, FRAME_FRONT, OPENING_H),
            (hw + FRAME_W, FRAME_BACK, top - 0.02),
            "M_Struct_Gunmetal",
        )
        frame.box(
            (-hw - FRAME_W, FRAME_FRONT, top - 0.02),
            (hw + FRAME_W, FRAME_BACK, top),
            "M_Section_Cap",
        )
    frame.build(f"{name}_frame", bevel_width=0.012, segments=3)

    trim = kit.MeshBuilder()
    trim.box((-hw, FRAME_FRONT + 0.05, -0.004), (hw, FRAME_BACK, 0.006), "M_Struct_Gunmetal")
    for sign in (-1, 1):
        x = sign * (hw + 0.1)
        trim.box(
            (x - 0.006, FRAME_FRONT - 0.004, 0.25),
            (x + 0.006, FRAME_FRONT + 0.004, min(top, OPENING_H) - 0.2),
            "M_Recess_Dark",
        )
    trim.build(f"{name}_trim", bevel_width=0.002, nav="walk")

    leaves = kit.MeshBuilder()
    leaf_top = min(top, OPENING_H) - (0.02 if cut else 0.0)
    y0, y1 = 0.15, 0.15 + LEAF_T
    for sign in (-1, 1):
        if closed:
            a, b = 0.0, hw + 0.06
        else:
            a, b = hw - 0.06, 2 * hw + 0.06
        x0, x1 = sorted((sign * a, sign * b))
        leaves.box((x0 + 0.002, y0, 0.01), (x1 - 0.002, y1, leaf_top), "M_Wall_PaintedDark")
        if closed:
            for z in (0.9, 2.0):
                if z < leaf_top - 0.1:
                    leaves.box(
                        (x0 + 0.1, y0 - 0.02, z), (x1 - 0.1, y0, z + 0.08), "M_Trim_BrushedSteel"
                    )
    if cut:
        leaves.box(
            (-hw, y0 - 0.002, leaf_top), (hw, y1 + 0.002, leaf_top + 0.02), "M_Section_Cap"
        ) if closed else None
    leaves.build(f"{name}_leaves", bevel_width=0.006)

    if not cut:
        for sign, mat in (
            (-1, "M_Indicator_Red" if closed else "M_Indicator_Green"),
            (1, "M_Indicator_White"),
        ):
            kit.emissive_panel(
                f"{name}_lamp{sign + 1}",
                (sign * (hw + 0.3), FRAME_FRONT - 0.002, 2.3),
                (0.08, 0.05),
                mat,
                normal="-Y",
            )

    kit.socket(
        "door",
        "",
        kit.facing_matrix((0.0, 0.15, 0.0), 0.0),
        width=OPENING_W,
        height=OPENING_H,
        state="closed" if closed else "open",
    )
    for sign in (-1, 1):
        x0, x1 = sorted((sign * hw, sign * (hw + FRAME_W)))
        kit.occluder(((x0, FRAME_FRONT, 0.0), (x1, FRAME_BACK, top)))
    if not cut:
        kit.occluder(((-hw, FRAME_FRONT, OPENING_H), (hw, FRAME_BACK, top)))
    if closed:
        kit.occluder(((-hw, y0, 0.0), (hw, y1, leaf_top)))

    if cut:
        with kit.ghost(walls.CUT_HEIGHT):
            build_blast_door(closed=closed)


LIFT_W = 1.5
LIFT_H = 2.6


def build_turbolift_door() -> None:
    """Lift alcove in a full-height wall module (2.4 m)."""
    name = "SM_Turbolift_Door"
    w = 2.4
    hw, lw = w / 2, LIFT_W / 2
    body = kit.MeshBuilder()
    walls.backing(body, w, walls.HEIGHT, y0=0.29)
    walls.panel_row(body, w, walls.UPPER[0], walls.UPPER[1] - 0.02, "M_Wall_PaintedMid")
    walls.section_cap(body, w, walls.HEIGHT)
    body.build(f"{name}_wall", bevel_width=0.003)
    walls.light_strip(name, w, *walls.STRIP)

    surround = kit.MeshBuilder()
    # Heavy surround with chamfered reveal, proud of the wall plane.
    outer = 0.36
    for sign in (-1, 1):
        pts = [(lw + outer, -0.12), (lw + 0.12, -0.12), (lw, 0.0), (lw, 0.3), (lw + outer, 0.3)]
        pts = [(sign * x, y) for x, y in pts]
        surround.prism_z(
            pts if sign > 0 else list(reversed(pts)), 0.0, LIFT_H + outer, "M_Struct_Gunmetal"
        )
    surround.box((-lw, -0.12, LIFT_H), (lw, 0.3, LIFT_H + outer), "M_Struct_Gunmetal")
    # Side fill panels between the surround and the module edges.
    for sign in (-1, 1):
        x0, x1 = sorted((sign * (lw + outer), sign * hw))
        surround.box(
            (x0 + 0.003, 0.0, 0.12),
            (x1 - 0.003, walls.PANEL_DEPTH, walls.MAIN[1]),
            "M_Wall_PaintedLight",
        )
        surround.box((x0, 0.035, 0.0), (x1, 0.3, 0.12), "M_Wall_PaintedDark")
    surround.box(
        (-hw, 0.0, LIFT_H + outer), (hw, walls.PANEL_DEPTH, walls.MAIN[1]), "M_Wall_PaintedLight"
    )
    surround.build(f"{name}_surround", bevel_width=0.01, segments=3)

    leaves = kit.MeshBuilder()
    for sign in (-1, 1):
        x0, x1 = sorted((sign * 0.003, sign * lw))
        leaves.box((x0, 0.22, 0.01), (x1, 0.28, LIFT_H), "M_Trim_BrushedSteel")
        leaves.box((x0 + sign * 0.0 + 0.08, 0.215, 1.0), (x1 - 0.08, 0.22, 1.06), "M_Recess_Dark")
    leaves.box((-lw, 0.0, -0.002), (lw, 0.3, 0.01), "M_Trim_BrushedSteel")
    leaves.build(f"{name}_leaves", bevel_width=0.004)
    # Lit reveal: a thin opal strip around the opening, set into the chamfer.
    for sign in (-1, 1):
        kit.emissive_panel(
            f"{name}_reveal{sign + 1}",
            (sign * (lw + 0.055), -0.06, LIFT_H / 2),
            (0.025, LIFT_H - 0.1),
            "M_Light_WallStrip",
            normal="-Y",
        )
    kit.emissive_panel(
        f"{name}_reveal_top",
        (0.0, -0.121, LIFT_H + 0.2),
        (LIFT_W, 0.03),
        "M_Light_WallStrip",
        normal="-Y",
    )
    panel = kit.MeshBuilder()
    panel.box((lw + 0.42, -0.03, 1.3), (lw + 0.58, 0.0, 1.55), "M_Console_Body")
    panel.build(f"{name}_callpanel", bevel_width=0.004)
    kit.emissive_panel(
        f"{name}_call", (lw + 0.5, -0.031, 1.48), (0.06, 0.04), "M_Indicator_Amber", normal="-Y"
    )
    kit.emissive_panel(
        f"{name}_ready", (lw + 0.5, -0.031, 1.4), (0.06, 0.04), "M_Indicator_Green", normal="-Y"
    )

    kit.socket("lift", "", kit.facing_matrix((0.0, -0.25, 0.0), 0.0), width=LIFT_W, height=LIFT_H)
    kit.socket("spawn", "", kit.facing_matrix((0.0, -1.2, 0.0), 0.0))
    kit.occluder(((-hw, -0.12, 0.0), (hw, 0.3, walls.HEIGHT)))


def build_lobby() -> None:
    """Two lifts side by side (4.8 m)."""
    kit.place("SM_Turbolift_Door", (-1.2, 0.0, 0.0), 0.0, id="a")
    kit.place("SM_Turbolift_Door", (1.2, 0.0, 0.0), 0.0, id="b")


for _cut in (False, True):
    for _closed in (False, True):
        _n = "SM_BlastDoor_240" + ("_Cut" if _cut else "") + ("_Closed" if _closed else "")
        _h = walls.CUT_HEIGHT if _cut else walls.HEIGHT
        kit.register_variant(_n, build_blast_door, dims=(3.6, 0.6, _h), closed=_closed, cut=_cut)
kit.register_variant("SM_Turbolift_Door", build_turbolift_door, dims=(2.4, 0.42, walls.HEIGHT))
kit.register_variant("SM_Turbolift_Lobby_480", build_lobby, dims=(4.8, 0.42, walls.HEIGHT))
