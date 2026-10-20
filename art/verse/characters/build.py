"""Build every crew character, the shared clips and characters.json.

Run from the worktree root:
    python scripts/verse/blender.py run --no-lock art/verse/characters/build.py [--only a,b]
QA renders (Cycles, takes the GPU lock):
    python scripts/verse/blender.py run art/verse/characters/build.py --qa

Outputs (dodaios/ui/web/frontend/public/verse/characters/):
    SK_Officer_M.glb, SK_Officer_F.glb, SK_Technician.glb, SK_Trooper.glb
    A_Human_M.glb, A_Human_F.glb (skeleton + all clips), characters.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

from characters import anim as A
from characters import common as C
from characters import crew
from characters import looks as LK
from characters import looks_gear as LG
from characters import outfits as O
from characters import paint as PT
from characters import posing as P

CHARACTERS = {
    # id: (variant, builder name, kind)
    "SK_Officer_M": ("M", "build_officer", "officer"),
    "SK_Officer_F": ("F", "build_officer", "officer"),
    "SK_Technician": ("M", "build_technician", "technician"),
    "SK_Trooper": ("M", "build_trooper", "trooper"),
}

# Atlas painters per model kind.
PAINTERS = {"officer": LK.officer, "technician": LG.technician, "trooper": LG.trooper}

# Reference colours per rank tier (sRGB hex). The runtime tints by material name.
TIERS = {
    "deck": {
        "M_Uniform": "#3b3f47",
        "M_Trousers": "#3b3f47",
        "M_Trim": "#5a5f68",
        "M_Cap": "#3b3f47",
        "tile": "#a9adb2",
        "cap": False,
    },
    "line": {
        "M_Uniform": "#5e6253",
        "M_Trousers": "#5e6253",
        "M_Trim": "#50544a",
        "M_Cap": "#5e6253",
        "tile": "#4d86d9",
        "cap": True,
    },
    "command": {
        "M_Uniform": "#17181a",
        "M_Trousers": "#17181a",
        "M_Trim": "#0f1012",
        "M_Cap": "#17181a",
        "tile": "#e3242b",
        "cap": True,
    },
    "flag": {
        "M_Uniform": "#e4e1d8",
        "M_Trousers": "#17181a",
        "M_Trim": "#d6d3c9",
        "M_Cap": "#e4e1d8",
        "tile": "#c8a24a",
        "cap": True,
    },
}
TILE_UNLIT = "#2a2d31"

# Per-model default colours for shared slot names (the glb material keeps the slot name).
DEFAULTS = {
    # Gunner black, lifted a touch so the suit's seams, harness and pads still read at
    # the close game camera under dim room light.
    "SK_Technician": {"M_Uniform": "#1f2124", "M_Trim": "#34373c"},
}


def _srgb_to_linear(h: str):
    h = h.lstrip("#")
    c = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def apply_defaults(cid: str, objs):
    """Set the model's default colours on its own material copies ('M_X@cid')."""
    for name, col in DEFAULTS.get(cid, {}).items():
        rgba = (*_srgb_to_linear(col), 1.0)
        for o in objs:
            for i, m in enumerate(o.data.materials):
                if m is None or m.name.split("@")[0] != name:
                    continue
                if not m.name.endswith(f"@{cid}"):
                    own = bpy.data.materials.get(f"{name}@{cid}")
                    if own is None:
                        own = m.copy()
                        own.name = f"{name}@{cid}"
                    o.data.materials[i] = own
                    m = own
                PT.set_factor(m, rgba)


slot_names = PT.export_names


# WebP quality of the atlases inside the glb files (base colour and normal map).
IMAGE_QUALITY = 90


def export_glb(path: Path, objects, animations: bool):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objects:
        o.hide_set(False)
        o.hide_viewport = False
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=False,
        export_animations=animations,
        export_animation_mode="ACTIONS",
        export_force_sampling=True,
        export_optimize_animation_size=True,
        export_def_bones=True,
        export_skins=True,
        export_morph=False,
        export_materials="EXPORT",
        export_vertex_color="ACTIVE",
        export_cameras=False,
        export_lights=False,
        export_image_format="WEBP",
        export_image_quality=IMAGE_QUALITY,
        export_extras=False,
        export_anim_slide_to_zero=True,
    )
    return path.stat().st_size


def rank_plate_socket(plate):
    """Plate centre and facing in three.js model space (rest pose), parent bone Chest."""
    vs = [v.co for v in plate.data.vertices]
    c = sum(vs, Vector()) / len(vs)
    big = max(plate.data.polygons, key=lambda p: p.area)
    n = big.normal if big.normal.y < 0 else -big.normal
    return {
        "bone": "Chest",
        "position": [round(c.x, 4), round(c.z, 4), round(-c.y, 4)],
        "normal": [round(n.x, 4), round(n.z, 4), round(-n.y, 4)],
    }


def mesh_info(objs):
    mats, tris = [], 0
    for o in objs:
        if o.type != "MESH":
            continue
        tris += C.tri_count(o)
        for m in o.data.materials:
            if m and m.name not in mats:
                mats.append(m.name)
    return mats, tris


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--no-clips", action="store_true")
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--qa-contact", action="store_true", help="QA contact sheets only")
    args = ap.parse_args(argv)
    C.reset_scene()
    O.make_materials()
    out = C.ensure_dir(C.OUT_DIR)
    only = [s for s in args.only.split(",") if s] or list(CHARACTERS)
    ctxs: dict[str, O.Ctx] = {}
    built = {}
    entries = []
    for cid in only:
        variant, builder, kind = CHARACTERS[cid]
        fn = getattr(O, builder, None) or getattr(crew, builder)
        ctx = ctxs.get(variant) or ctxs.setdefault(variant, O.Ctx(variant))
        ctx.hi, ctx.look = None, {}  # set by the builder for its own garment
        objs = fn(ctx)
        for o in objs:
            o.name = o.name.split(".")[0]
            o.data.name = o.name
        PT.texture(
            cid,
            objs,
            PAINTERS[kind](ctx),
            hi=getattr(ctx, "hi", None),
            weight=LK.density(ctx),
            debug_dir=C.CACHE / "atlas",
        )
        apply_defaults(cid, objs)
        with slot_names(cid):
            size = export_glb(out / f"{cid}.glb", [ctx.arm] + objs, animations=False)
            mats, tris = mesh_info(objs)
        built[cid] = (ctx, objs)
        print(f"[characters] {cid}: {tris} tris, {size} bytes, materials {mats}")
        entries.append(
            {
                "id": cid,
                "kind": kind,
                "url": f"verse/characters/{cid}.glb",
                "skeleton": variant,
                "clips": f"verse/characters/A_Human_{variant}.glb",
                "meshes": [o.name for o in objs],
                "materials": mats,
                "height": C.VARIANTS[variant]["height"],
                "triangles": tris,
                "bytes": size,
                "defaults": DEFAULTS.get(cid, {}),
            }
        )
        plate = next((o for o in objs if o.name == "RankPlate"), None)
        if plate is not None:
            entries[-1]["rankPlate"] = rank_plate_socket(plate)
        for o in objs:
            o.name = f"{cid}:{o.name}"
            o.data.name = o.name
    clip_info = {}
    if not args.no_clips:
        for variant, ctx in sorted(ctxs.items()):
            body = A.Body(ctx.rig)
            acts = []
            for name, (fn, loop) in A.CLIPS.items():
                poses = fn(body)
                acts.append(P.write_action(ctx.rig, name, poses))
                clip_info[name] = {"loop": loop, "seconds": round((len(poses) - 1) / C.FPS, 4)}
            P.stash_actions(ctx.arm, acts)
            size = export_glb(out / f"A_Human_{variant}.glb", [ctx.arm], animations=True)
            print(f"[characters] A_Human_{variant}: {size} bytes")
            ctx.walk_speed = A.walk_stride(body) / (A.WALK_FRAMES / C.FPS)
            ctx.arm.animation_data.action = None
            for tr in list(ctx.arm.animation_data.nla_tracks):
                ctx.arm.animation_data.nla_tracks.remove(tr)
            # The exporter's ACTIONS mode takes every compatible action in the file:
            # drop this variant's clips before the next variant is exported.
            for act, _slot in acts:
                bpy.data.actions.remove(act)
    write_manifest(out, entries, clip_info, ctxs)
    if args.qa or args.qa_contact:
        from characters import qa

        qa.contact_sheet(built, ctxs, full=not args.qa_contact)


def write_manifest(out: Path, entries, clip_info, ctxs):
    path = out / "characters.json"
    old = {}
    if path.is_file():
        old = json.loads(path.read_text(encoding="utf-8"))
    models = {m["id"]: m for m in old.get("models", [])}
    for e in entries:
        models[e["id"]] = e
    drones = C.CACHE / "drones_manifest.json"
    if drones.is_file():
        d = json.loads(drones.read_text(encoding="utf-8"))
        for e in d if isinstance(d, list) else d.values() if "id" not in d else [d]:
            if isinstance(e, dict) and "id" in e:
                if e["id"] == "SK_Drone_Companion":
                    e = dict(e, kind="companion")
                models[e["id"]] = e
    skeletons = dict(old.get("skeletons", {}))
    for v, ctx in ctxs.items():
        skeletons[v] = {
            "height": C.VARIANTS[v]["height"],
            "clips": f"verse/characters/A_Human_{v}.glb",
            "walkSpeed": round(getattr(ctx, "walk_speed", 0.0), 4)
            or skeletons.get(v, {}).get("walkSpeed"),
            "bones": ctx.bones,
        }
    manifest = {
        "version": 1,
        "units": "metres, three.js axes (Y up), characters face +Z, origin on the floor",
        "fps": C.FPS,
        "seatHeight": C.SEAT_HEIGHT,
        "deskHeight": C.DESK_HEIGHT,
        "standDeskHeight": C.STAND_DESK_HEIGHT,
        "conventions": {
            "standing": "feet on the floor around the origin",
            "seat": "A_Sit_*: buttocks on a seat surface seatHeight above the root; seat "
            "centre 0.06 m in front of the root; keyboard deskHeight high, 0.40 m "
            "in front of the root",
            "standDesk": "A_Stand_Type: hands on a surface standDeskHeight high, 0.36 m in "
            "front of the root",
            "bunk": "A_Sleep: root on the mattress top surface; lying on the back, head "
            "towards -Z, feet towards +Z",
            "walk": "A_Walk is in place; move the root at the skeleton's walkSpeed (m/s)",
            "tinting": "clone materials per character, set color by material name; "
            "M_RankTile_n: set emissive colour (and emissiveIntensity) to light a "
            "tile; mesh 'Cap' is the toggleable cap",
        },
        "clips": clip_info or old.get("clips", {}),
        "skeletons": skeletons,
        "tiers": TIERS,
        "tileUnlit": TILE_UNLIT,
        "models": [models[k] for k in sorted(models)],
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[characters] wrote {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
