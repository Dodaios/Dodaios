"""Look-development renders of the cooked crew files, the way the game camera sees them.

Imports the shipped glb files (not the build scene), dresses them like the runtime
does (`look.ts`: tier colours by material name, lit rank tiles, cap per tier), poses
them from their clip files and renders with Cycles through the game camera:
orthographic, 60 degrees below the horizon, on a glossy black deck under overhead
light panels.

    python scripts/verse/blender.py run art/verse/characters/lookdev.py -- \
        [--dir <folder with the glb files>] [--out <folder>] [--ppm 200] [--tag after]

Writes <out>/lookdev_<tag>_front.png and _back.png (figures about 200 px tall at
200 px/m) and <out>/lookdev_<tag>_close.png (the two bareheaded officers and a capped
one at twice the density, for detail).
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy

from characters import common as C
from characters import qa

TIERS = None  # filled from characters.json

# (model, tier, lit tiles, clip, frame); tier None = authored colours
LINEUP = [
    ("SK_Officer_M", "deck", 2, "A_Idle", 40),
    ("SK_Officer_M", "line", 3, "A_Idle", 40),
    ("SK_Officer_M", "command", 5, "A_Idle", 40),
    ("SK_Officer_F", "flag", 6, "A_Idle", 40),
    ("SK_Officer_F", "deck", 2, "A_Idle", 40),
    ("SK_Technician", None, 0, "A_Idle", 40),
    ("SK_Trooper", None, 0, "A_Idle", 40),
    ("SK_Drone_Companion", None, 0, "A_Hover", 20),
    ("SK_Drone_Utility", None, 0, "A_Idle", 20),
]
DETAIL = [
    ("SK_Officer_M", "flag", 6, "A_Idle", 40),
    ("SK_Officer_M", "deck", 2, "A_Idle", 40),
    ("SK_Officer_F", "deck", 2, "A_Idle", 40),
    ("SK_Officer_F", "line", 3, "A_Idle", 40),
]
GEAR = [
    ("SK_Technician", None, 0, "A_Idle", 40),
    ("SK_Trooper", None, 0, "A_Idle", 40),
    ("SK_Drone_Companion", None, 0, "A_Hover", 20),
    ("SK_Drone_Utility", None, 0, "A_Idle", 20),
]
CLOSE = [
    ("SK_Officer_M", "deck", 2, "A_Idle", 40),
    ("SK_Officer_F", "deck", 2, "A_Idle", 40),
    ("SK_Officer_M", "flag", 6, "A_Idle", 40),
    ("SK_Trooper", None, 0, "A_Idle", 40),
]


def _hex(h: str):
    return qa._hex(h)


def _base_factor_inputs(mat):
    """Unlinked colour inputs of the multiply chain feeding Base Color (the factor)."""
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    sock = bsdf.inputs["Base Color"]
    if not sock.is_linked:
        return [sock]
    out = []
    stack = [sock.links[0].from_node]
    while stack:
        n = stack.pop()
        if n.bl_idname == "ShaderNodeMix":
            for name in ("A", "B"):
                for i in n.inputs:
                    if i.name == name and i.type == "RGBA" and i.enabled:
                        if i.is_linked:
                            stack.append(i.links[0].from_node)
                        else:
                            out.append(i)
        elif n.bl_idname == "ShaderNodeMixRGB":
            for i in n.inputs[1:3]:
                if i.is_linked:
                    stack.append(i.links[0].from_node)
                else:
                    out.append(i)
    return out


def tint(mat, hexcol):
    for i in _base_factor_inputs(mat):
        i.default_value = (*_hex(hexcol), 1.0)


def light_tile(mat, hexcol, lit):
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    if lit:
        tint(mat, hexcol)
        bsdf.inputs["Emission Color"].default_value = (*_hex(hexcol), 1.0)
        bsdf.inputs["Emission Strength"].default_value = 0.35
    else:
        tint(mat, CONTRACT["tileUnlit"])
        bsdf.inputs["Emission Strength"].default_value = 0.0


def place(glb_dir: Path, model: str, tier, tiles: int, clip: str, frame: int, x: float, yaw: float):
    entry = next(m for m in CONTRACT["models"] if m["id"] == model)
    before = set(bpy.data.objects)
    acts_before = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(glb_dir / f"{model}.glb"))
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    action = None
    if "skeleton" in entry:
        # clips live in the skeleton's clip file; import, borrow the action, drop the rig
        b2 = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(glb_dir / f"A_Human_{entry['skeleton']}.glb"))
        extra = [o for o in bpy.data.objects if o not in b2]
        acts = [a for a in bpy.data.actions if a not in acts_before]
        action = next((a for a in acts if a.name.split(".")[0] == clip), None)
        for o in extra:
            bpy.data.objects.remove(o, do_unlink=True)
    else:
        acts = [a for a in bpy.data.actions if a not in acts_before]
        action = next((a for a in acts if a.name.split(".")[0] == clip), None)
    if arm.animation_data is None:
        arm.animation_data_create()
    for tr in list(arm.animation_data.nla_tracks):
        arm.animation_data.nla_tracks.remove(tr)
    if action is not None:
        arm.animation_data.action = action
        if hasattr(arm.animation_data, "action_slot") and len(action.slots):
            arm.animation_data.action_slot = action.slots[0]
    arm["frame"] = frame
    arm.location = (x, 0.0, 0.0)
    arm.rotation_mode = "XYZ"
    arm.rotation_euler = (0.0, 0.0, yaw)
    colours = CONTRACT["tiers"][tier] if tier else None
    for o in new:
        if o.type != "MESH":
            continue
        if o.name.split(".")[0] == "Cap" and colours and not colours["cap"]:
            o.hide_render = True
            continue
        for i, m in enumerate(o.data.materials):
            if m is None:
                continue
            mm = m.copy()
            o.data.materials[i] = mm
            base = m.name.split(".")[0]
            if colours and base in ("M_Uniform", "M_Trim", "M_Cap"):
                tint(mm, colours[base])
            if colours and base == "M_Trousers":
                tint(mm, colours.get("M_Trousers", colours["M_Uniform"]))
            if base.startswith("M_RankTile_"):
                k = int(base[-1])
                light_tile(mm, colours["tile"] if colours else "#4d86d9", k <= tiles)
    return arm


def lineup(glb_dir: Path, items, spacing, yaw):
    arms = []
    x = 0.0
    for model, tier, tiles, clip, frame in items:
        if not (glb_dir / f"{model}.glb").is_file():
            continue
        arms.append(place(glb_dir, model, tier, tiles, clip, frame, x, yaw))
        x += spacing if not model.startswith("SK_Drone") else spacing * 0.75
    return arms, x - spacing


def pose_all(arms):
    # one frame for the whole scene; every armature evaluates its own action there
    sc = bpy.context.scene
    for arm in arms:
        ad = arm.animation_data
        if ad and ad.action:
            # shift the action so its wanted frame lands on scene frame 1
            f = int(arm.get("frame", 1))
            tr = ad.nla_tracks.new()
            st = tr.strips.new(ad.action.name, 1 - f + 1, ad.action)
            if hasattr(st, "action_slot") and len(ad.action.slots):
                st.action_slot = ad.action.slots[0]
            ad.action = None
    sc.frame_set(1)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.actions, bpy.data.armatures,
                 bpy.data.images, bpy.data.lights, bpy.data.cameras):
        for it in list(coll):
            coll.remove(it)


def shoot(glb_dir, items, out_png, ppm, yaw, spacing=0.8, height_m=2.1, samples=96, cz=0.82):
    clear()
    qa.stage()
    arms, span = lineup(glb_dir, items, spacing, yaw)
    pose_all(arms)
    width = span + spacing
    qa.camera(span / 2, cz, width, height_m, ppm)
    bpy.context.scene.cycles.samples = samples
    qa.render(out_png)


CONTRACT = {}


def main(argv):
    global CONTRACT
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(C.OUT_DIR))
    ap.add_argument("--out", default=str(C.CACHE / "lookdev"))
    ap.add_argument("--ppm", type=int, default=200)
    ap.add_argument("--tag", default="after")
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--only", default="front,back,close")
    args = ap.parse_args(argv)
    glb_dir = Path(args.dir)
    out = C.ensure_dir(Path(args.out))
    CONTRACT = json.loads((glb_dir / "characters.json").read_text(encoding="utf-8"))
    C.reset_scene()
    bpy.context.scene.render.image_settings.file_format = "PNG"
    shots = set(args.only.split(","))
    if "front" in shots:
        shoot(glb_dir, LINEUP, out / f"lookdev_{args.tag}_front.png", args.ppm, 0.0,
              samples=args.samples)
    if "back" in shots:
        shoot(glb_dir, LINEUP[:7], out / f"lookdev_{args.tag}_back.png", args.ppm, math.pi,
              samples=args.samples)
    if "detail" in shots:
        # inspection only: upper bodies at four times the density
        shoot(glb_dir, DETAIL, out / f"lookdev_{args.tag}_detail.png", args.ppm * 4, 0.0,
              spacing=0.6, height_m=0.75, samples=args.samples, cz=1.25)
    if "detailback" in shots:
        shoot(glb_dir, DETAIL, out / f"lookdev_{args.tag}_detailback.png", args.ppm * 4, math.pi,
              spacing=0.6, height_m=0.75, samples=args.samples, cz=1.25)
    if "gear" in shots:
        shoot(glb_dir, GEAR, out / f"lookdev_{args.tag}_gear.png", args.ppm * 2, 0.0,
              spacing=0.75, height_m=1.25, samples=args.samples)
    if "close" in shots:
        shoot(glb_dir, CLOSE, out / f"lookdev_{args.tag}_close.png", args.ppm * 2, 0.0,
              spacing=0.7, height_m=1.25, samples=args.samples)


if __name__ == "__main__":
    main(sys.argv[1:])
