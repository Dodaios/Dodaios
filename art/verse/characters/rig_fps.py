"""Build `SKEL_Verse_Human`, the FPS character meshes and every clip; export FBX (WP13).

Blender entry (art-pipeline 12). Agents run it only through
`python scripts/verse/export_unreal.py characters`, which writes the import
records from the result file. Directly (headless Blender, no lock needed):

    python scripts/verse/blender.py run --no-lock art/verse/characters/rig_fps.py \
        --out art/verse/.cache/unreal/characters --result <file.json> [--only A,B]
        [--no-clips] [--no-meshes]

Steps per body variant: the crew body and skeleton (`outfits.Ctx`), the FPS
armature on the same landmarks (`fps/rig.py`), the weapon grips calibrated
on it (`fps/clips.Fps`), then each uniform's garments (the crew builders)
rebound to the FPS bones with at most 8 influences. Clips are authored once
on the male skeleton, the reference pose of `SKEL_Verse_Human`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

from characters import build as CB
from characters import common as C
from characters import crew
from characters import outfits as O
from characters.fps import catalogue as K
from characters.fps import clips as CL
from characters.fps import export as EX
from characters.fps import rig as R
from characters.fps import skeleton as S
from characters.fps import solver as SV

#: Linear colours per uniform and Blender slot that differ from the crew look
#: (the opponent is black with sparse red, README "Look"; never cyan or violet).
UNIFORM_COLOURS = {
    "Commander": {k: v for k, v in CB.TIERS["command"].items() if k.startswith("M_")},
    # The unit mark is dull brass here: brand gold stays on the allow-listed accents.
    "Crew": {**CB.DEFAULTS["SK_Technician"], "M_Mark": "#7a5f2e"},
    "Opponent": {
        "M_Armor": "#141517",
        "M_Undersuit": "#0e0f10",
        "M_Helmet": "#0b0b0c",
        "M_Visor": "#060607",
        "M_Accent": "#6a1512",
        "M_Glow": "#a32118",
        "M_Boots": "#0b0b0c",
        "M_Gloves": "#101112",
        "M_Belt": "#0f1011",
        "M_ChestBox": "#17181a",
        "M_Mark": "#5c4a24",
    },
}
#: Clips rendered by --qa and the clip fractions shown.
QA_CLIPS = {
    "A_Crouch_Move_R": (0.0, 0.5),
    "A_Stand_Move_BL": (0.0, 0.5),
    "A_Prone_Move_F": (0.0, 0.5),
    "A_Rifle_Equip": (0.0, 0.5),
    "A_Pistol_Reload_Empty": (0.3, 0.75),
    "A_Hit_Torso_Front": (0.2,),
    "A_Death_Left": (1.0,),
    "A_Jump_Start": (1.0,),
    "A_Land": (0.25,),
    "A_Prone_Enter": (0.5,),
    "A_Crew_Bunk": (0.0,),
    "A_Crew_Walk": (0.0,),
    "A_Stand_Idle": (0.0,),
    "A_Rifle_Idle": (0.0,),
    "A_Rifle_ADS": (0.0,),
    "A_Rifle_Reload_Tactical": (0.0, 0.22, 0.45, 0.7, 0.95),
    "A_Pistol_ADS": (0.0,),
    "A_Stand_Move_F": (0.0, 0.25, 0.5),
    "A_Crouch_Move_FL": (0.0, 0.5),
    "A_Sprint_F": (0.0, 0.5),
    "A_Prone_Idle": (0.0,),
    "A_Slide": (0.4,),
    "A_Mantle_High": (0.0, 0.4, 0.7, 1.0),
    "A_Finisher_Attacker": (0.0, 0.1, 0.36, 0.72, 0.8, 1.0),
    "A_Finisher_Victim": (0.0, 0.1, 0.36, 0.72, 1.0),
    "A_Knife_Strike": (0.0, 0.21),
    "A_Death_Front": (1.0,),
    "A_Death_Back": (1.0,),
    "A_Crew_Sit_Type": (0.0,),
    "A_Stand_Lean_L": (0.0,),
}
#: Garment objects the crew build hides (nobody wears the cap, `build.TIERS`).
HIDDEN = {"Cap"}


def _srgb_hex(h: str) -> list[float]:
    return [round(x, 5) for x in CB._srgb_to_linear(h)] + [1.0]


def _material_values(mat, uniform: str) -> dict:
    base = C_strip(mat.name)
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    colour = list(bsdf.inputs["Base Color"].default_value) if bsdf else [0.2, 0.2, 0.2, 1.0]
    rough = float(bsdf.inputs["Roughness"].default_value) if bsdf else 0.6
    metal = float(bsdf.inputs["Metallic"].default_value) if bsdf else 0.0
    override = UNIFORM_COLOURS.get(uniform, {}).get(base)
    if override:
        colour = _srgb_hex(override)
    return {
        "slot": base,
        "mi": mi_path(uniform, base),
        "base_color": [round(float(c), 5) for c in colour[:3]] + [1.0],
        "roughness": round(rough, 4),
        "metallic": round(metal, 4),
    }


def C_strip(name: str) -> str:  # noqa: N802 - keeps the "M_" prefix visible at call sites
    return name.split("@")[0].split(".")[0]


def mi_name(uniform: str, slot: str) -> str:
    return f"MI_Character_{uniform}_{slot[2:] if slot.startswith('M_') else slot}"


def mi_path(uniform: str, slot: str) -> str:
    mi = mi_name(uniform, slot)
    return f"/Game/Verse/Materials/Instances/Characters/{mi}.{mi}"


class Variant:
    def __init__(self, v: str):
        self.ctx = O.Ctx(v)
        self.arm = R.build_armature(self.ctx, f"FPS_{v}")
        self.fps = CL.Fps(self.ctx)
        rest_r = self.arm.data.bones["Hand_R"].matrix_local.copy()
        rest_l = self.arm.data.bones["Hand_L"].matrix_local.copy()
        R.set_bone_matrix(self.arm, "Weapon_R", rest_r @ self.fps.grip)
        R.set_bone_matrix(self.arm, "Weapon_L", rest_l @ self.fps.knife_grip)
        self.rig = SV.FpsRig(self.ctx.rig, self.arm)
        self.wmap = R.WeightMap(self.ctx, self.arm)
        self.meshes: dict = {}
        problems = EX.bone_check(self.arm) + [
            f"bone {n} shorter than 5 mm" for n in R.bone_lengths_ok(self.arm)
        ]
        if problems:
            raise RuntimeError(f"FPS rig {v}: " + "; ".join(problems))


def build_mesh(var: Variant, spec: K.MeshSpec, out: Path) -> dict:
    ctx = var.ctx
    builder = K.UNIFORMS[spec.uniform][0]
    fn = getattr(O, builder, None) or getattr(crew, builder)
    ctx.hi, ctx.look = None, {}
    ctx.export_arm = None
    objs = [o for o in fn(ctx) if o.type == "MESH"]
    keep = [o for o in objs if o.name.split(".")[0] not in HIDDEN]
    worst = 0
    for o in keep:
        worst = max(worst, R.rebind(o, var.arm, var.wmap))
    copies = []
    for o in keep:
        c = o.copy()
        c.data = o.data.copy()
        C.link(c)
        copies.append(c)
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    with bpy.context.temp_override(
        active_object=copies[0], selected_objects=copies, selected_editable_objects=copies
    ):
        bpy.ops.object.join()
    # A copy of a crew garment object does not deform (some state of the crew
    # build travels with the object); a new object on the joined data does.
    data = copies[0].data
    names = [vg.name for vg in copies[0].vertex_groups]
    bpy.data.objects.remove(copies[0], do_unlink=True)
    joined = bpy.data.objects.new(f"JOIN_{spec.name}", data)
    C.link(joined)
    if len(joined.vertex_groups) != len(names):
        for name in names[len(joined.vertex_groups) :]:
            joined.vertex_groups.new(name=name)
    joined.parent = var.arm
    joined.modifiers.new("Armature", "ARMATURE").object = var.arm
    slots = []
    seen = set()
    for m in joined.data.materials:
        if m is None:
            continue
        base = C_strip(m.name)
        if base in seen:
            continue
        seen.add(base)
        slots.append(_material_values(m, spec.uniform))
    entry = EX.export_mesh(spec.name, var.arm, joined, out, slots)
    entry.update(
        uniform=spec.uniform,
        variant=spec.variant,
        height_m=K.VARIANTS[spec.variant],
        rebind_max_influences=worst,
    )
    var.meshes[spec.name] = joined
    for o in objs + [joined]:
        o.name = f"{spec.name}:{o.name}"
        o.hide_set(True)
        o.hide_render = True
    return entry


def ue_vector_cm(v) -> list[float]:
    """A vector in a bone's Blender local frame (m) -> the same bone's Unreal local frame (cm).

    Measured on the imported `SKEL_Verse_Human` (Verse.Anim.OffHandIK): the
    FBX conversion keeps local X and Z and flips local Y, so in Unreal a
    root-like frame such as `Weapon_R` has +Z forward (the barrel), -Y up and
    +X towards the character's left. Not the world mapping of art-pipeline 4.1.
    """
    return [round(v[0] * 100.0, 3) + 0.0, round(-v[1] * 100.0, 3) + 0.0, round(v[2] * 100.0, 3) + 0.0]


def grips(var: Variant) -> dict:
    out = {}
    for cls, m in var.fps.support.items():
        out[cls] = {"support_cm": ue_vector_cm(m.translation)}
    return out


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="rig_fps")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--result", type=Path, required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--no-clips", action="store_true")
    ap.add_argument("--no-meshes", action="store_true")
    ap.add_argument("--qa", type=Path, help="render workbench contact sheets into this folder")
    args = ap.parse_args(argv)
    only = {s for s in args.only.split(",") if s}
    C.reset_scene()
    O.make_materials()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    meshes = [] if args.no_meshes else [m for m in K.MESHES if not only or m.name in only]
    clips = [] if args.no_clips else [c for c in K.CLIPS if not only or c.name in only]
    needed = sorted({m.variant for m in meshes} | ({"M"} if clips else set()))
    variants = {v: Variant(v) for v in needed}
    result = {"skeleton": S.SKELETON, "meshes": [], "clips": [], "grips": {}, "rig": {}}
    for v, var in variants.items():
        result["rig"][v] = {
            "bones": [b.name for b in var.arm.data.bones],
            "parents": {b.name: (b.parent.name if b.parent else None) for b in var.arm.data.bones},
        }
    for spec in meshes:
        entry = build_mesh(variants[spec.variant], spec, out / "meshes")
        if args.qa:
            from characters.fps import qa

            var = variants[spec.variant]
            qa.turnaround(var.meshes[spec.name], args.qa.resolve(), spec.name)
        print(
            f"[verse] {spec.name}: {entry['triangles']} tris, "
            f"max {entry['max_influences']} influences"
        )
        result["meshes"].append(entry)
    if clips:
        var = variants["M"]
        result["grips"] = grips(var)
        for clip in clips:
            poses, curves = CL.author(var.fps, clip)
            entry = EX.export_clip(var.rig, clip, poses, curves, out / "clips")
            group = clip.group.split("/")
            if (
                group[0] == "Weapons"
                and group[1] in var.fps.support
                and (clip.name.endswith("_Idle") or clip.name.endswith("_ADS"))
            ):
                entry["offhand_error_cm"] = round(
                    EX.offhand_error_cm(var.rig, var.fps, poses, group[1]), 4
                )
            result["clips"].append(entry)
            print(f"[verse] {clip.name}: {entry['frames']} frames")
            if args.qa and clip.name in QA_CLIPS and K.SKELETON_SOURCE in var.meshes:
                from characters.fps import qa

                mesh = var.meshes[K.SKELETON_SOURCE]
                n = len(poses) - 1
                picks = sorted({round(n * k) for k in QA_CLIPS[clip.name]})
                qa.pose_strip(var.rig, mesh, poses, clip, args.qa.resolve(), picks)
                if clip.name in ("A_Rifle_Idle", "A_Rifle_ADS", "A_Pistol_ADS"):
                    qa.first_person(var.rig, mesh, poses, clip, args.qa.resolve())
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[verse] rig_fps: {len(result['meshes'])} meshes, {len(result['clips'])} clips")


main(sys.argv[1:])
