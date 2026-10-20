"""Hero vignette: the visual benchmark of the whole production.

A 19.2 x 12.9 m slice of the ship through the fixed plate camera, built only
from kit pieces the way a deck builder would:

* top: the bridge's far wall (charcoal hero wall with light columns, full
  height), hull framing behind it;
* middle: a slice of the bridge with a sunken crew pit (stations, stairs,
  railing, pale coping, light bars between the console bays);
* left: a corridor running toward the camera (walls seen edge-on), closed by
  the far wall, hull framing beside it;
* bottom: the chamfered corridor along the ship (both walls cut at 1.1 m),
  a T-junction with bulkhead pilasters, a blast door into the bridge and a
  structural frame.

Run through the pipeline runner (it takes the GPU lock)::

    python scripts/verse/blender.py run art/verse/lookdev/hero_vignette.py \
        --out art/verse/.cache/lookdev/hero.png --ppm 64 --samples 128 \
        [--crop 0.2,0.25,0.86,0.81 --ppm 96] [--exposure 0.0] [--blend path]

``--crop`` takes fractions of the full frame (x0, y0, x1, y1; origin bottom
left) and renders only that region, e.g. a native-density (96 px/m) crop.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from kit.architecture import (  # noqa: F401
    ceiling,
    corridor,
    doors,
    floors,
    hull,
    pit,
    structure,
    walls,
    windows,
)
from lib import kit
from lib import scene as deck

BOUNDS = deck.Bounds(x_min=-9.6, y_min=-6.6, x_max=9.6, y_max=6.3, z_min=0.0, z_max=4.5)
X0, X1 = BOUNDS.x_min, BOUNDS.x_max
Y_FAR_WALL = 5.7  # room face of the bridge's far wall
Y_CORRIDOR = -3.9  # centre line of the corridor along the ship
X_SIDE = -4.8  # centre line of the corridor toward the camera
X_DOOR = 4.8  # blast door from the corridor into the bridge
Y_PIT = 2.4  # centre line of the crew pit
HALL_X0 = X_SIDE + corridor.OUTER_HALF  # -2.1: the side corridor's outer wall face

FH = corridor.FLOOR_HALF
Y_CORR_NEAR, Y_CORR_FAR = Y_CORRIDOR - FH, Y_CORRIDOR + FH  # floor edges
Y_HALL0 = Y_CORR_FAR + corridor.BODY_Y  # -1.2: bridge floor starts here


def arch():
    return kit.into(deck.collection("Architecture"))


def build_far_wall() -> None:
    with arch():
        for x, piece in (
            (-4.8, "SM_Wall_480"),
            (0.0, "SM_Wall_480"),
            (4.8, "SM_Viewport_480"),
            (8.4, "SM_Viewport_240"),
        ):
            kit.place(piece, (x, Y_FAR_WALL, 0.0), 0.0, room="bridge")


def build_corridor_along_ship() -> None:
    gaps = ((X_SIDE - 2.4, X_SIDE + 2.4), (X_DOOR - 2.4, X_DOOR + 2.4))
    with arch():
        floors.fill_rect("FLR_corridor", X0, BOUNDS.y_min, X1, Y_HALL0, room="corridor")
        for i in range(8):
            x = X0 + 1.2 + i * 2.4
            kit.place("SM_CorridorWall_240_Cut", (x, Y_CORR_NEAR, 0.0), 180.0, room="corridor")
            if not any(a < x < b for a, b in gaps):
                kit.place("SM_CorridorWall_240_Cut", (x, Y_CORR_FAR, 0.0), 0.0, room="corridor")
        y_pil = Y_CORR_FAR + corridor.BODY_Y / 2
        for xc in (X_SIDE, X_DOOR):
            for sx in (-1, 1):
                kit.place("SM_Bulkhead_Pilaster_Cut", (xc + sx * 2.25, y_pil, 0.0), 0.0)
        kit.place(
            "SM_BlastDoor_240_Cut",
            (X_DOOR, Y_CORR_FAR + corridor.CHAMFER_Y, 0.0),
            0.0,
            room="corridor",
            id="door_bridge",
        )
        kit.place("SM_Bulkhead_Frame_Corridor_Cut", (0.0, Y_CORRIDOR, 0.0), 0.0, room="corridor")
    with kit.into(deck.collection("Ceiling")):
        y0 = Y_CORR_NEAR - corridor.UPPER_Y - 0.05
        y1 = Y_CORR_FAR + corridor.UPPER_Y + 0.05
        ceiling.ceiling_slab(
            "CEIL_corridor", [(X0, y0), (X1, y0), (X1, y1), (X0, y1)], corridor.CEILING
        )
        for i in range(8):
            ceiling.light_panel(
                f"LGT_corridor_{i}", (X0 + 1.2 + i * 2.4, Y_CORRIDOR, corridor.CEILING), (0.6, 2.4)
            )
    kit.room(
        "corridor",
        "Ship corridor",
        [(X0, Y_CORR_NEAR), (X1, Y_CORR_NEAR), (X1, Y_CORR_FAR), (X0, Y_CORR_FAR)],
    )


def build_side_corridor() -> None:
    with arch():
        for y in (Y_HALL0 + 1.2, Y_HALL0 + 3.6, Y_HALL0 + 6.0):
            kit.place("SM_Corridor_240_Full", (X_SIDE, y, 0.0), 90.0, room="corridor_side")


def build_bridge() -> None:
    hw = pit.PIT_WIDTH / 2
    near, far = Y_PIT - hw - pit.WALL_T, Y_PIT + hw + pit.WALL_T
    with arch():
        for x in (3.6, 6.0, 8.4):
            kit.place("SM_CrewPit_240", (x, Y_PIT, 0.0), 0.0, room="bridge")
        kit.place("SM_Stairs_120_H140", (0.6, Y_PIT, 0.0), 0.0, room="bridge")
        kit.place("SM_PitWall_120", (2.4, Y_PIT - 1.2, -pit.PIT_DEPTH), 90.0, room="bridge")
        kit.place("SM_PitWall_120", (2.4, Y_PIT + 1.2, -pit.PIT_DEPTH), 90.0, room="bridge")
        floors.fill_rect("FLR_bridge_front", HALL_X0, Y_HALL0, X1, near, room="bridge")
        floors.fill_rect("FLR_bridge_back", HALL_X0, far, X1, Y_FAR_WALL, room="bridge")
        floors.fill_rect("FLR_bridge_left", HALL_X0, near, 0.6, far, room="bridge")
        floors.fill_rect("FLR_bridge_stair_l", 0.6, near, 2.1, Y_PIT - 0.6, room="bridge")
        floors.fill_rect("FLR_bridge_stair_r", 0.6, Y_PIT + 0.6, 2.1, far, room="bridge")
        floors.inlay_strip(
            "INL_bridge_pit_edge", (HALL_X0 + 0.5, near - 0.45), (X1, near - 0.45), width=0.04
        )
        floors.marking("MRK_pit_edge", 2.4, near - 0.16, X1, near - 0.1, hazard=True)
    with kit.into(deck.collection("Ceiling")):
        ceiling.fill_ceiling(
            "bridge",
            (HALL_X0, X1),
            (Y_HALL0, Y_FAR_WALL),
            z=4.5,
            pitch=(1.2, 1.8),
            size=(1.0, 0.36),
        )
    kit.room(
        "bridge",
        "Command bridge",
        [(HALL_X0, Y_HALL0), (X1, Y_HALL0), (X1, Y_FAR_WALL), (HALL_X0, Y_FAR_WALL)],
    )


def build_hull() -> None:
    with arch():
        hull.fill_hull("HULL_w", (X0, X_SIDE - corridor.OUTER_HALF), (Y_HALL0, Y_FAR_WALL + 0.3))
        hull.fill_hull("HULL_n", (X0, X1), (Y_FAR_WALL + walls.THICKNESS, 9.6))
        # Framing all around the slice so the frame edges never show a void.
        hull.fill_hull("HULL_s", (X0 - 2.4, X1 + 2.4), (BOUNDS.y_min - 2.4, BOUNDS.y_min))
        hull.fill_hull("HULL_e", (X1, X1 + 2.4), (BOUNDS.y_min, 9.6))
        hull.fill_hull("HULL_x", (X0 - 2.4, X0), (BOUNDS.y_min, 9.6))


def build() -> bpy.types.Scene:
    scene = deck.new_deck("lookdev_hero", BOUNDS, name="Lookdev hero vignette")
    build_far_wall()
    build_corridor_along_ship()
    build_side_corridor()
    build_bridge()
    build_hull()
    return scene


def configure(scene, ppm: int, samples: int, exposure: float, crop) -> None:
    camera = scene.camera
    deck.apply_frame(scene, camera, deck.frame_for(BOUNDS, ppm, margin=0.0))
    scene.cycles.samples = samples
    scene.cycles.adaptive_threshold = 0.02
    scene.view_settings.exposure = exposure
    if crop:
        x0, y0, x1, y1 = crop
        scene.render.use_border = True
        scene.render.use_crop_to_border = True
        scene.render.border_min_x, scene.render.border_min_y = x0, y0
        scene.render.border_max_x, scene.render.border_max_y = x1, y1


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ppm", type=int, default=64)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--exposure", type=float, default=0.0)
    parser.add_argument("--crop", type=lambda s: [float(v) for v in s.split(",")], default=None)
    parser.add_argument("--blend", type=Path, default=None)
    args = parser.parse_args(argv)
    scene = build()
    configure(scene, args.ppm, args.samples, args.exposure, args.crop)
    if args.blend:
        args.blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.blend.resolve()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.out.resolve())
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"[lookdev] wrote {args.out} {scene.render.resolution_x}x{scene.render.resolution_y}")


if __name__ == "__main__":
    main(sys.argv[1:])
