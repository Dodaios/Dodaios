"""Hull structure around the bridge: every metre of the plate outside the
rooms is ship, never void (BRIEF section 2).

* Behind the viewport wall and its chamfers: the deck-head structure above
  the windows, a dark plated roof with ribs, longitudinal ducts and service
  lamps (seen above the header beam).
* Along the sides and aft: the kit's open hull bays below deck level.
"""

from __future__ import annotations

from lib import kit

from . import layout as L

ROOF_Z = 8.25


def _roof_polygon() -> list[tuple[float, float]]:
    # Plan region north of the leaning walls' top edges (z 0 at the centre
    # run, the 45 degree line x + z = 6.9 behind each chamfer).
    return L.poly(
        [
            (-3.0, -9.0),
            (75.0, -9.0),
            (75.0, 9.9),
            (L.WIDTH - 6.9, 0.0),
            (6.9, 0.0),
            (-3.0, 9.9),
        ]
    )


def build_roof() -> None:
    plate = kit.MeshBuilder()
    plate.prism_z(_roof_polygon(), ROOF_Z - 0.35, ROOF_Z, "M_Hull_Structure")
    plate.build("SM_roof_plate", bevel_width=0.0, nav="none")
    ribs = kit.MeshBuilder()
    ducts = kit.MeshBuilder()
    x = -2.4
    while x <= 74.4:
        # Plan depth the roof reaches at this x: behind the chamfers it runs
        # forward to the 45 degree line, elsewhere it stops at the beam.
        reach = 0.6
        if x < 6.9:
            reach = min(9.9, 6.9 - x)
        elif x > L.WIDTH - 6.9:
            reach = min(9.9, x - (L.WIDTH - 6.9))
        reach = max(0.6, reach - 0.25)
        ribs.box((x - 0.12, -reach, ROOF_Z), (x + 0.12, 9.0, ROOF_Z + 0.32), "M_Hull_Structure")
        ribs.box(
            (x - 0.2, -reach, ROOF_Z + 0.32), (x + 0.2, 9.0, ROOF_Z + 0.36), "M_Hull_Structure"
        )
        x += 2.4
    # Cross girders and cable trays in the two corner pockets.
    for zc in (2.4, 4.8, 7.2):
        span = 6.9 - zc - 0.3
        if span <= -3.0:
            continue
        for x0, x1 in ((-3.0, span), (L.WIDTH - span, L.WIDTH + 3.0)):
            ribs.box(
                (x0, -zc - 0.15, ROOF_Z + 0.1), (x1, -zc + 0.15, ROOF_Z + 0.42), "M_Hull_Structure"
            )
            ducts.box(
                (x0, -zc - 0.55, ROOF_Z + 0.02), (x1, -zc - 0.25, ROOF_Z + 0.06), "M_Floor_Grating"
            )
    for k, (y, r, mat) in enumerate(
        (
            (1.1, 0.32, "M_Hull_PipeInsulated"),
            (2.0, 0.18, "M_Hull_Pipe"),
            (2.6, 0.22, "M_Hull_Pipe"),
            (4.2, 0.45, "M_Hull_PipeInsulated"),
            (5.6, 0.14, "M_Hull_Pipe"),
        )
    ):
        ducts.tube((-3.0, y, ROOF_Z + 0.4 + r), (75.0, y, ROOF_Z + 0.4 + r), r, mat, segments=20)
        xx = 1.2 + k * 0.6
        while xx < 72.0:
            ducts.tube(
                (xx - 0.06, y, ROOF_Z + 0.4 + r),
                (xx + 0.06, y, ROOF_Z + 0.4 + r),
                r + 0.04,
                "M_Struct_Gunmetal",
                segments=20,
            )
            xx += 4.8
    ribs.build("SM_roof_ribs", bevel_width=0.01, nav="none")
    ducts.build("SM_roof_ducts", bevel_width=0.0, nav="none")
    # Work lamps (cold white) and red accents in the corner pockets.
    for i, (x, z, mat) in enumerate(
        (
            (0.6, 3.6, "M_Light_CeilingPanel"),
            (L.WIDTH - 0.6, 3.6, "M_Light_CeilingPanel"),
            (2.4, 1.2, "M_Light_Maint_Red"),
            (L.WIDTH - 2.4, 1.2, "M_Light_Maint_Red"),
            (-1.2, 7.8, "M_Light_Maint_Red"),
            (L.WIDTH + 1.2, 7.8, "M_Light_Maint_Red"),
        )
    ):
        kit.emissive_panel(
            f"SM_roof_corner_lamp_{i}",
            (x, -z, ROOF_Z + 0.37),
            (0.3, 0.12),
            mat,
            normal="Z",
            nav="none",
        )
    for i, x in enumerate((6.0, 22.8, 36.0, 49.2, 66.0)):
        kit.emissive_panel(
            f"SM_roof_lamp_{i}",
            (x, 3.3, ROOF_Z + 0.37),
            (0.3, 0.12),
            "M_Light_Maint_Red" if i % 2 else "M_Light_Maint_Amber",
            normal="Z",
        )


def build_hull(use_kit: bool) -> None:
    if not use_kit:
        return
    from kit.architecture import hull

    # Port and starboard strips outside the side walls, full depth.
    xl = L.SIDE_WALL_X[0] - L.SIDE_WALL_T
    xr = L.SIDE_WALL_X[1] + L.SIDE_WALL_T
    hull.fill_hull("hull_p", (-2.4, xl - 0.01), (-L.DEPTH - 2.4, 0.0))
    hull.fill_hull("hull_s", (xr + 0.01, 74.4), (-L.DEPTH - 2.4, 0.0))
    # Aft strip below the plate's bottom edge.
    hull.fill_hull("hull_aft", (xl, xr), (-L.DEPTH - 2.4, -L.AFT_WALL_Z[1] - 0.01))


def build(use_kit: bool) -> None:
    build_roof()
    build_hull(use_kit)
