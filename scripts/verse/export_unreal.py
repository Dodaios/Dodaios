"""Export Verse art from the Blender builders to FBX for Unreal (art-pipeline 2).

The only export entry for agents. It runs headless Blender through
`scripts/verse/blender.py` while holding the machine-wide `gpu-heavy.lock`,
writes FBX files into the ignored cache `art/verse/.cache/unreal/` and, for
assets that ship, the committed import records
`unreal/Verse/Art/Import/<Kind>/<Asset>.import.json` (art-pipeline 10.3).

    python scripts/verse/export_unreal.py piece SM_Wall_480
    python scripts/verse/export_unreal.py calib
    python scripts/verse/export_unreal.py weapons [--only SK_Weapon_Graveline,...]
    python scripts/verse/export_unreal.py textures [--only T_Verse_Grade_LUT_M]
    python scripts/verse/export_unreal.py characters [--only A,B] [--no-lock]
    python scripts/verse/export_unreal.py deck <deck> [--zone Z]

`calib` exports the `fbx-ue/1` calibration assets (`kit/calib.py`) into the
cache only; `python scripts/unreal/import_art.py calib` imports and checks
them. `weapons` exports the WP14 arsenal (`art/verse/weapons`) and writes its
records under `unreal/Verse/Art/Import/Weapons/` and `Art/Import/VFX/`.
`textures` bakes the texture sets builders own (today WP14's grade LUT
`T_Verse_Grade_LUT_M`). `characters` (WP13) builds `SKEL_Verse_Human`, the
character meshes and every clip (`art/verse/characters/rig_fps.py`) and writes
their records, MI recipes and the grip reference; `--only A,B` limits it to
named assets. `deck` is reserved for the packages that own that art
(WP11/WP12) and exits 2 until they land.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "unreal"))

import art_common  # noqa: E402
import blender  # noqa: E402

ENTRY = HERE / "_export_unreal_entry.py"
GENERATOR = "export_unreal.py"

#: Reserved modes and the package that owns them (work-packages.md).
RESERVED = {
    "deck": "WP12 (agent decks, hangar day zones) and WP11 (arena zones)",
}

#: Kit module prefix -> (content folder under /Game/Verse/Kit, record folder).
KIT_GROUPS = (
    ("kit.architecture", "Architecture"),
    ("kit.props", "Props"),
)
KIT_OWNER = "WP12"
PROP_SMALL_CM = 30.0
PROP_NANITE_MIN_TRIS = 300


#: WP14's own Blender entry for the `weapons` mode.
WEAPON_ENTRY = HERE.parents[1] / "art" / "verse" / "weapons" / "_export_entry.py"


def _run_blender(mode_args: list[str], label: str) -> dict:
    folder = {"calib": "calib", "weapons": "weapons"}.get(mode_args[0], "kit")
    entry = ENTRY
    if mode_args[0] == "weapons":
        entry, mode_args = WEAPON_ENTRY, mode_args[1:]
    out_dir = art_common.CACHE_ROOT / folder
    result = art_common.CACHE_ROOT / "results" / f"{label}.json"
    result.unlink(missing_ok=True)
    args = [*mode_args, "--out", str(out_dir), "--result", str(result)]
    with art_common.heavy_lock(f"export_unreal {label}"):
        blender.run(entry, args, lock=False, device="cpu", timeout=1800)
    return json.loads(result.read_text(encoding="utf-8"))


def kit_group(module: str) -> str:
    for prefix, group in KIT_GROUPS:
        if module == prefix or module.startswith(prefix + "."):
            return group
    raise ValueError(f"{module}: not a kit module with a content folder")


def collision_profile(group: str, bounds: dict) -> str:
    if group == "Architecture":
        return "Verse_Architecture"
    size = [hi - lo for lo, hi in zip(bounds["min"], bounds["max"], strict=True)]
    return "Verse_PropSmall" if max(size) < PROP_SMALL_CM else "Verse_Prop"


def build_record(asset: dict, previous: dict | None) -> dict:
    """The `verse.import/1` record of an exported kit piece.

    Fields a person or package tuned by hand (nanite error, collision
    profile, lod, licence, owner, budget override) survive a re-export.
    """
    source = asset["source"]
    group = kit_group(source["module"])
    name = asset["name"]
    record = {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": f"/Game/Verse/Kit/{group}/{name}.{name}",
        "kind": "static_mesh",
        "source": {
            "builder": source["builder"],
            "function": source["function"],
            "args": source["args"],
        },
        "export": {
            "format": "fbx",
            "settings_id": asset["settings_id"],
            "file": asset["file"],
            "sha256": asset["sha256"],
            "blender": asset["blender"],
        },
        "mesh": {
            "triangles": asset["triangles"],
            "vertices": asset["vertices"],
            "bounds_cm": asset["bounds_cm"],
            "uv_sets": asset["uv_sets"],
            "material_slots": asset["material_slots"],
        },
        "nanite": {"enabled": group == "Architecture" or asset["triangles"] > PROP_NANITE_MIN_TRIS},
        "collision": {
            "profile": collision_profile(group, asset["bounds_cm"]),
            "source": "authored" if asset["collision_primitives"] else "auto_box",
            "primitives": asset["collision_primitives"],
        },
        "lod": {"mode": "nanite"},
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": KIT_OWNER,
    }
    if asset["sockets"]:
        record["mesh"]["sockets"] = asset["sockets"]
    if not record["nanite"]["enabled"]:
        record["lod"] = {"mode": "single"}
    if previous:
        for key in ("nanite", "collision", "lod", "license", "owner", "budget_override"):
            if key in previous:
                record[key] = previous[key]
        record["collision"]["primitives"] = asset["collision_primitives"]
    return record


def record_path(record: dict) -> Path:
    group = record["asset_path"].split("/")[4]
    return art_common.IMPORT_RECORDS / "Kit" / group / f"{record['name']}.import.json"


def export_piece(name: str) -> int:
    payload = _run_blender(["piece", name], name)
    for asset in payload["assets"]:
        record = build_record(asset, None)
        path = record_path(record)
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        record = build_record(asset, previous)
        changed = art_common.dump_json(path, record)
        state = "updated" if changed else "unchanged"
        print(f"[verse] {name}: record {art_common.rel(path)} {state}")
    return 0


def export_calib() -> int:
    payload = _run_blender(["calib"], "calib")
    summary = art_common.CACHE_ROOT / "calib" / "calib.export.json"
    art_common.dump_json(summary, payload)
    for asset in payload["assets"]:
        print(f"[verse] {asset['name']}: {asset['file']} sha256 {asset['sha256'][:12]}")
    print(f"[verse] calibration export summary: {art_common.rel(summary)}")
    return 0


# --------------------------------------------------------------------------
# Weapons (WP14, art/verse/weapons)
# --------------------------------------------------------------------------

WEAPON_OWNER = "WP14"
WEAPON_RECORDS = art_common.IMPORT_RECORDS / "Weapons"
VFX_CONTENT = "/Game/Verse/VFX/Weapons"


def _weapon_specs():
    sys.path.insert(0, str(art_common.REPO_ROOT / "art" / "verse"))
    from weapons import specs

    return specs


#: Masters whose blend mode is translucent (art-pipeline 7). Nanite renders no
#: translucent material, so a mesh with such a slot gets the glass rule of
#: art-pipeline 6.2: Nanite off, LOD0 plus an automatic 50 % LOD.
TRANSLUCENT_MASTERS = frozenset({"M_Verse_Glass"})
TRANSLUCENT_LOD = {"mode": "auto", "screen_sizes": [1.0, 0.5]}


def _mi_parent(mi_path: str) -> str:
    """The master name of one MI recipe, from `unreal/Verse/Art/Materials/**`."""
    name = mi_path.rsplit(".", 1)[-1]
    root = art_common.REPO_ROOT / "unreal" / "Verse" / "Art" / "Materials"
    for path in root.rglob(f"{name}.mi.json"):
        return json.loads(path.read_text(encoding="utf-8"))["parent"].rsplit(".", 1)[-1]
    return ""


def has_translucent_slot(slots: list[dict], parent_of=_mi_parent) -> bool:
    """True when any material slot's MI has a translucent master."""
    return any(parent_of(slot.get("mi", "")) in TRANSLUCENT_MASTERS for slot in slots)


def weapon_records(asset: dict) -> list[dict]:
    """The `verse.import/1` records of one exported weapon, gadget or VFX mesh."""
    specs = _weapon_specs()
    name = asset["name"]
    is_vfx = name.startswith("SM_Vfx_")
    if is_vfx:
        object_path = f"{VFX_CONTENT}/{name}.{name}"
    else:
        object_path = specs.by_asset(name).object_path
    skeletal = asset["kind"] == "skeletal_mesh"
    translucent = has_translucent_slot(asset["material_slots"])
    source = asset["source"]
    export = {
        "format": "fbx",
        "settings_id": asset["settings_id"],
        "file": asset["file"],
        "sha256": asset["sha256"],
        "blender": asset["blender"],
    }
    mesh = {
        "triangles": asset["triangles"],
        "vertices": asset["vertices"],
        "bounds_cm": asset["bounds_cm"],
        "uv_sets": asset["uv_sets"],
        "material_slots": asset["material_slots"],
    }
    if asset.get("bones"):
        mesh["bones"] = asset["bones"]
    if asset.get("sockets"):
        mesh["sockets"] = asset["sockets"]
    if skeletal or is_vfx:
        collision = {"profile": "Verse_NoCollision", "source": "none", "primitives": 0}
    else:
        primitives = asset["collision_primitives"]
        how = "authored" if primitives else "auto_box"
        collision = {"profile": "Verse_Prop", "source": how, "primitives": max(primitives, 1)}
    record = {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": object_path,
        "kind": asset["kind"],
        "source": {k: source[k] for k in ("builder", "function", "args")},
        "export": export,
        "mesh": mesh,
        "nanite": {
            "enabled": not skeletal
            and not is_vfx
            and not translucent
            and asset["triangles"] > PROP_NANITE_MIN_TRIS
        },
        "collision": collision,
        "lod": {"mode": "single"},
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": WEAPON_OWNER,
    }
    if record["nanite"]["enabled"]:
        record["lod"] = {"mode": "nanite"}
    elif translucent:
        record["lod"] = dict(TRANSLUCENT_LOD)
    out = [record]
    if skeletal:
        spec = specs.by_asset(name)
        out.append(
            {
                "schema": "verse.import/1",
                "name": spec.skeleton,
                "asset_path": spec.skeleton_path,
                "kind": "skeleton",
                "source": record["source"],
                "export": export,
                "mesh": {**mesh, "material_slots": []},
                "lightmap": "none",
                "license": {"kind": "own"},
                "owner": WEAPON_OWNER,
            }
        )
    return out


def weapon_record_path(record: dict) -> Path:
    folder = record["asset_path"].rsplit("/", 1)[0].removeprefix("/Game/Verse/")
    return art_common.IMPORT_RECORDS / folder / f"{record['name']}.import.json"


def export_weapons(only: list[str]) -> int:
    args = ["weapons"]
    for name in only:
        args += ["--only", name]
    payload = _run_blender(args, "weapons")
    for asset in payload["assets"]:
        for record in weapon_records(asset):
            path = weapon_record_path(record)
            changed = art_common.dump_json(path, record)
            state = "updated" if changed else "unchanged"
            tris = record.get("mesh", {}).get("triangles")
            print(f"[verse] {record['name']}: {tris} tris, record {art_common.rel(path)} {state}")
    return 0


# --------------------------------------------------------------------------
# Texture sets baked by builders
# --------------------------------------------------------------------------

#: Texture sets this entry can bake: name -> (Blender script, record fields).
TEXTURE_SETS = {
    "T_Verse_Grade_LUT_M": {
        "script": "art/verse/weapons/look/_blender_lut.py",
        "function": "main",
        "folder": "look",
        "asset_path": "/Game/Verse/PostProcess/T_Verse_Grade_LUT_M.T_Verse_Grade_LUT_M",
        "owner": "WP14",
        "texture": {
            "group": "World",
            "max_size": 1024,
            "srgb": False,
            "compression": "HDR",
            "flip_green": False,
            "channels": {
                "lut": "32",
                "rgb": "Blender AgX display value (sRGB) of the log2 lattice point",
                "layout": "32 slices of 32 x 32 side by side; slice = blue",
            },
        },
    },
}


def texture_record(name: str, file: Path, blender_version: str) -> dict:
    spec = TEXTURE_SETS[name]
    import hashlib

    return {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": spec["asset_path"],
        "kind": "texture",
        "source": {"builder": spec["script"], "function": spec["function"], "args": {}},
        "export": {
            "format": "png",
            "settings_id": "png-ue/1",
            "file": art_common.rel(file),
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            "blender": blender_version,
        },
        "texture": spec["texture"],
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": spec["owner"],
    }


def export_textures(only: list[str]) -> int:
    names = only or list(TEXTURE_SETS)
    for name in names:
        spec = TEXTURE_SETS[name]
        out = art_common.CACHE_ROOT / spec["folder"]
        script = art_common.REPO_ROOT / spec["script"]
        with art_common.heavy_lock(f"export_unreal textures {name}"):
            blender.run(script, ["--out", str(out)], lock=False, device="cpu", timeout=900)
        meta = json.loads((out / "look_bake.json").read_text(encoding="utf-8"))
        version = meta["blender"].split(" ")[0]
        record = texture_record(name, out / f"{name}.png", version)
        folder = spec["asset_path"].rsplit("/", 1)[0].removeprefix("/Game/Verse/")
        path = art_common.IMPORT_RECORDS / folder / f"{name}.import.json"
        state = "updated" if art_common.dump_json(path, record) else "unchanged"
        print(f"[verse] {name}: record {art_common.rel(path)} {state}")
    return 0


CHARACTERS_ENTRY = HERE.parent.parent / "art" / "verse" / "characters" / "rig_fps.py"


def export_characters(only: str, lock: bool = True) -> int:
    """WP13: rig, meshes and clips in one Blender run, then their records.

    The run is CPU only (no render); `--no-lock` skips the machine lock for it.
    """
    out_dir = art_common.CACHE_ROOT / "characters"
    result = art_common.CACHE_ROOT / "results" / "characters.json"
    result.unlink(missing_ok=True)
    args = ["--out", str(out_dir), "--result", str(result)]
    if only:
        args += ["--only", only]
    if lock:
        with art_common.heavy_lock("export_unreal characters"):
            blender.run(CHARACTERS_ENTRY, args, lock=False, device="cpu", timeout=3600)
    else:
        blender.run(CHARACTERS_ENTRY, args, lock=False, device="cpu", timeout=3600)
    payload = json.loads(result.read_text(encoding="utf-8"))
    sys.path.insert(0, str(art_common.REPO_ROOT / "art" / "verse"))
    from characters.fps import records  # noqa: PLC0415 - needs art/verse on sys.path

    changed = records.write_all(
        payload, art_common.PROJECT_DIR, art_common.REPO_ROOT / "art" / "verse"
    )
    for path in changed:
        print(f"[verse] characters: wrote {art_common.rel(Path(path))}")
    print(
        f"[verse] characters: {len(payload['meshes'])} meshes, {len(payload['clips'])} clips,"
        f" {len(changed)} files changed"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    piece = sub.add_parser("piece", help="export one kit master and write its import record")
    piece.add_argument("name")
    sub.add_parser("calib", help="export the fbx-ue/1 calibration assets into the cache")
    deck = sub.add_parser("deck", help="reserved (placement JSON of a deck zone)")
    deck.add_argument("deck")
    deck.add_argument("--zone")
    weapons = sub.add_parser("weapons", help="export the WP14 weapons, gadgets and VFX meshes")
    weapons.add_argument("--only", default="", help="comma-separated asset names")
    textures = sub.add_parser("textures", help="bake texture sets (WP14: T_Verse_Grade_LUT_M)")
    textures.add_argument("--only", default="", help="comma-separated texture names")
    chars = sub.add_parser("characters", help="WP13: rig, meshes, clips and their records")
    chars.add_argument("--only", default="")
    chars.add_argument("--no-lock", action="store_true", help="CPU-only run outside the lock")
    options = parser.parse_args(argv)
    try:
        if options.mode == "piece":
            return export_piece(options.name)
        if options.mode == "calib":
            return export_calib()
        if options.mode == "textures":
            return export_textures([n for n in options.only.split(",") if n])
        if options.mode == "weapons":
            return export_weapons([n for n in options.only.split(",") if n])
        if options.mode == "characters":
            return export_characters(options.only, lock=not options.no_lock)
    except blender.BlenderError as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"export_unreal {options.mode}: not available yet; it lands with {RESERVED[options.mode]}"
        " (docs/verse/unreal/work-packages.md)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
