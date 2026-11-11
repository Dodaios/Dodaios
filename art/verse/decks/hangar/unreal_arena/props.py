"""Scanned hero props of the Unreal hangar (arena.md 9.2, art direction in 9.3).

Poly Haven models (CC0, https://polyhaven.com) go through the same pipeline as
the kit: each glTF and its maps are downloaded once into the git-ignored cache
(MD5 checked, one append-only row per file in `art/verse/LICENSES.md`), Blender
exports every mesh as FBX under `fbx-ue/1`, and this script writes the
`verse.import/1` records of the meshes and their texture maps plus one
`verse.mi/1` recipe per material (`M_Verse_Surface` on UVs).

    python art/verse/decks/hangar/unreal_arena/props.py            # all props
    python art/verse/decks/hangar/unreal_arena/props.py --only overhead_crane
    python scripts/unreal/import_art.py assets --only <names it prints>
    python scripts/unreal/import_art.py materials --only <MI names it prints>
    python scripts/unreal/import_art.py bind --only <SM names it prints>

Maps: the colour map is stored with the model's ambient occlusion multiplied in
(the master reads no AO), the arm map is the master's ORM, and the metallic
scalar of each MI is the mean of the arm map's blue channel (the master's
metallic is one scalar per instance).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

VERSE = Path(__file__).resolve().parents[3]
REPO = VERSE.parents[1]
if str(VERSE) not in sys.path:
    sys.path.insert(0, str(VERSE))

from lib import textures  # noqa: E402

CACHE = VERSE / ".cache" / "models"
FBX_OUT = VERSE / ".cache" / "unreal" / "props"
PNG_OUT = VERSE / ".cache" / "unreal" / "textures" / "props"
MESH_RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import" / "Kit" / "Props"
TEX_RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import" / "Textures" / "Props"
MI_RECIPES = REPO / "unreal" / "Verse" / "Art" / "Materials" / "HangarProps"
BLENDER_SIDE = Path(__file__).with_name("props_blender.py")
BUILDER = "art/verse/decks/hangar/unreal_arena/props.py"


@dataclass(frozen=True)
class Prop:
    """One Poly Haven model: its id, the mesh name prefix and the map resolution.

    `pieces` splits a modular set: mesh suffix -> glTF object names (empty: the whole file).
    """

    asset: str
    name: str
    res: str = "1k"
    pieces: dict[str, tuple[str, ...]] = field(default_factory=dict)
    scale: float = 1.0


#: The hangar's scanned props. Names are `SM_Hangar_<Name>` (kit props folder, owner WP12).
PROPS: tuple[Prop, ...] = (
    # Hall structure and services.
    Prop(
        "overhead_crane",
        "Crane",
        "1k",
        {
            "Bridge": ("overhead_crane",),
            "Rails": ("overhead_crane_rails",),
            "Winch": ("overhead_crane_winch",),
        },
    ),
    Prop(
        "modular_industrial_pipes_01",
        "Pipes",
        "1k",
        {f"P{i}": (f"modular_industrial_pipes_01_pipe0{i}",) for i in range(1, 9)},
    ),
    Prop(
        "modular_airduct_rectangular_01",
        "Duct",
        "1k",
        {
            k: (f"modular_airduct_rectangular_01_{v}",)
            for k, v in {
                "Single": "single_01",
                "Double": "double_01",
                "Corner": "corner_01",
                "Bend": "bend_01",
                "Vent": "vent_01",
                "Brace": "brace_01",
            }.items()
        },
    ),
    Prop(
        "modular_electric_cables",
        "Cables",
        "1k",
        {
            "Long": ("cable_straight_long",),
            "Double": ("cable_double_alt_long",),
            "Curve": ("cable_scurve_1",),
            "Mount": ("cable_mount",),
        },
    ),
    Prop(
        "mounted_fluorescent_lights",
        "Fluorescent",
        "1k",
        {"A": ("mounted_fluorescent_lights_a",), "B": ("mounted_fluorescent_lights_b",)},
    ),
    Prop("hanging_industrial_lamp", "HangLamp", "1k"),
    Prop("industrial_wall_lamp", "WallLamp", "1k"),
    Prop("security_light", "Floodlight", "1k"),
    Prop("utility_box_01", "UtilityBox", "1k"),
    Prop("power_box_01", "PowerBox", "1k"),
    Prop("exterior_aircon_unit", "AirUnit", "1k", {"": ("exterior_aircon_unit_rusted",)}),
    Prop("rollershutter_door", "Shutter", "1k", {"": ("rollershutter_door",)}),
    Prop("korean_fire_extinguisher_01", "Extinguisher", "1k"),
    Prop("fire_alarm", "FireAlarm", "1k"),
    Prop("security_camera_01", "Camera", "1k"),
    Prop("ladder_sectioned_01", "Ladder", "1k"),
    # Ground equipment.
    Prop("portable_generator", "Generator", "1k"),
    Prop("old_military_compressor", "Compressor", "1k"),
    Prop("portable_welding_cart", "WeldCart", "1k"),
    Prop("tool_cart", "ToolTrolley", "1k"),
    Prop("industrial_storage_cart", "StoreCart", "1k"),
    Prop("hand_truck", "HandTruck", "1k"),
    Prop("steel_frame_shelves_01", "Shelves", "1k", scale=0.1),
    Prop("worn_metal_rack", "MetalRack", "1k"),
    Prop("metal_tool_chest", "ToolChest", "1k"),
    Prop("concrete_road_barrier", "JerseyBarrier", "1k"),
    Prop("old_tyre", "Tyre", "1k"),
    # Cargo and consumables.
    Prop("Barrel_01", "Drum", "1k"),
    Prop("Barrel_02", "DrumB", "1k"),
    Prop("barrel_03", "DrumC", "1k"),
    Prop("metal_jerrycan", "Jerrycan", "1k"),
    Prop("propane_tank", "GasBottle", "1k"),
    Prop("wooden_military_crate", "MilCrate", "1k"),
    Prop(
        "old_military_crate",
        "MilCrateB",
        "1k",
        {
            "": tuple(f"old_military_crate_{p}_a" for p in ("lid", "loop", "latch", "cloth"))
            + ("old_military_crate_a",)
        },
    ),
    Prop("ammo_box", "AmmoCan", "1k"),
    Prop("plastic_crate_03", "PlasticCrate", "1k"),
    Prop("cardboard_box_01", "Carton", "1k"),
    Prop("metal_toolbox", "Toolbox", "1k"),
    Prop(
        "metal_trash_can",
        "Bin",
        "1k",
        {
            "": (
                "metal_trash_can",
                "metal_trash_can_lid",
                "metal_trash_can_handle_left",
                "metal_trash_can_handle_right",
            )
        },
    ),
)

#: Props seen at arm's length or smaller: 512 px maps keep the repo inside its LFS budget.
SMALL = frozenset(
    {
        "Extinguisher",
        "FireAlarm",
        "Camera",
        "Cables",
        "WallLamp",
        "Floodlight",
        "Fluorescent",
        "Jerrycan",
        "GasBottle",
        "AmmoCan",
        "PlasticCrate",
        "Carton",
        "Toolbox",
        "Tyre",
        "PowerBox",
        "HandTruck",
        "ToolChest",
        "Ladder",
        "HangLamp",
        "DrumB",
        "DrumC",
    }
)

MAPS = {
    # key in the glTF image names -> (suffix, sRGB, compression, flip green, group)
    "diff": ("BC", True, "Default", False, "World"),
    "arm": ("ORM", False, "Masks", False, "World"),
    "nor_gl": ("N", False, "Normalmap", True, "WorldNormalMap"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pascal(text: str) -> str:
    return "".join(
        part[:1].upper() + part[1:] for part in text.replace("-", "_").split("_") if part
    )


def download(prop: Prop) -> Path:
    """The glTF of `prop` and every file it includes, in the cache; returns the .gltf path."""
    listing = textures._files(prop.asset)  # noqa: SLF001 - same cache and ledger as the textures
    entry = listing["gltf"][prop.res]["gltf"]
    folder = CACHE / prop.asset / prop.res
    gltf = folder / entry["url"].rsplit("/", 1)[-1]
    items = [(gltf, entry)] + [(folder / rel, sub) for rel, sub in entry.get("include", {}).items()]
    for destination, item in items:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            textures._download(item, destination)  # noqa: SLF001
        textures._record(prop.asset, destination, item["url"])  # noqa: SLF001
    return gltf


def ledger_row_hash(path: Path) -> str:
    """The ledger row of a downloaded file is keyed by the file's SHA-256."""
    return _sha256(path)


def blender_export(jobs: list[dict], result: Path) -> list[dict]:
    spec = result.with_suffix(".jobs.json")
    spec.write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "verse" / "blender.py"),
        "run",
        "--no-lock",
        str(BLENDER_SIDE),
        "--jobs",
        str(spec),
        "--out",
        str(FBX_OUT),
        "--result",
        str(result),
    ]
    subprocess.run(cmd, check=True, cwd=REPO)
    return json.loads(result.read_text(encoding="utf-8"))


def texture_png(
    source: Path, target: Path, kind: str, size: int, ao: Path | None
) -> tuple[Path, float]:
    """Write the cooked map; returns (png, mean of blue) where blue is the arm map's metal."""
    from PIL import Image, ImageChops

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = image.convert("RGB")
        if max(image.size) > size:
            image = image.resize((size, size), Image.Resampling.LANCZOS)
        blue = 0.0
        if kind == "arm":
            stat = image.getchannel("B").resize((64, 64))
            hist = stat.histogram()
            blue = sum(i * n for i, n in enumerate(hist)) / (64 * 64 * 255.0)
        if kind == "diff" and ao is not None:
            with Image.open(ao) as arm:
                occlusion = arm.convert("RGB").getchannel("R").resize(image.size)
                # 70 % of the scanned occlusion: crevices read, open faces stay at their colour.
                occlusion = occlusion.point(lambda v: int(255 - (255 - v) * 0.7))
                image = ImageChops.multiply(
                    image, Image.merge("RGB", (occlusion, occlusion, occlusion))
                )
        image.save(target, optimize=True)
    return target, blue


def texture_record(
    name: str, png: Path, kind: str, size: int, ledger: list[str], asset: str
) -> dict:
    suffix, srgb, compression, flip, group = MAPS[kind]
    return {
        "asset_path": f"/Game/Verse/Textures/Props/{name}.{name}",
        "export": {
            "blender": "0.0.0",
            "file": png.relative_to(REPO).as_posix(),
            "format": "png",
            "settings_id": "png-ue/1",
            "sha256": _sha256(png),
        },
        "kind": "texture",
        "license": {"kind": "ledger", "ledger_sha256": ledger},
        "lightmap": "none",
        "name": name,
        "owner": "WP11",
        "schema": "verse.import/1",
        "source": {"args": {"asset": asset, "map": kind}, "builder": BUILDER, "function": "main"},
        "texture": {
            "compression": compression,
            "flip_green": flip,
            "group": group,
            "max_size": size,
            "srgb": srgb,
        },
    }


#: Materials without a scanned texture set (lamp glass, gauge glass): kit MIs instead.
LAMP_GLASS = "/Game/Verse/Materials/Instances/Props/MI_Arena_LampWarm.MI_Arena_LampWarm"
CLEAR_GLASS = "/Game/Verse/Materials/Instances/Glass/MI_Glass_Clear.MI_Glass_Clear"
PLAIN_METAL = "/Game/Verse/Materials/Instances/Metal/MI_Struct_Gunmetal.MI_Struct_Gunmetal"
LAMPS = ("lamp", "light", "fluorescent")


def fallback_mi(original: str, asset: str) -> str:
    if "glass" in original.lower() or "bulb" in original.lower():
        return LAMP_GLASS if any(k in asset for k in LAMPS) else CLEAR_GLASS
    return PLAIN_METAL


def mesh_record(result: dict, ledger: list[str], asset: str) -> dict:
    name = result["name"]
    return {
        "asset_path": f"/Game/Verse/Kit/Props/{name}.{name}",
        "collision": {"primitives": 0, "profile": "Verse_NoCollision", "source": "none"},
        "export": {
            "blender": result["blender"],
            "file": result["file"],
            "format": "fbx",
            "settings_id": result["settings_id"],
            "sha256": result["sha256"],
        },
        "kind": "static_mesh",
        "license": {"kind": "ledger", "ledger_sha256": ledger},
        "lightmap": "none",
        "lod": {"mode": "nanite"},
        "mesh": {
            "bounds_cm": result["bounds_cm"],
            "material_slots": result["material_slots"],
            "triangles": result["triangles"],
            "uv_sets": result["uv_sets"],
            "vertices": result["vertices"],
        },
        "name": name,
        "nanite": {"enabled": True},
        "owner": "WP12",
        "schema": "verse.import/1",
        "source": {"args": {"asset": asset}, "builder": BUILDER, "function": "main"},
    }


def mi_recipe(mi: str, tex: dict[str, str], metallic: float) -> dict:
    return {
        "name": mi,
        "owner": "WP11",
        "parent": "/Game/Verse/Materials/Master/M_Verse_Surface.M_Verse_Surface",
        "replaces": "M_" + mi[3:],
        "scalars": {
            "EdgeWear": 0.0,
            "GrimeAmount": 0.0,
            "Metallic": round(metallic, 3),
            "NoiseScale": 0.6,
            "RoughnessMax": 1.0,
            "RoughnessMin": 1.0,
        },
        "schema": "verse.mi/1",
        "switches": {"UseTextureSet": True, "UseTriplanar": False},
        "textures": {f"Set1_{k}": f"/Game/Verse/Textures/Props/{v}.{v}" for k, v in tex.items()},
        "vectors": {"BaseTint": [1.0, 1.0, 1.0, 1.0]},
    }


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="comma-separated Poly Haven ids")
    args = parser.parse_args(argv)
    only = {s for s in args.only.split(",") if s}
    props = [p for p in PROPS if not only or p.asset in only]

    jobs = []
    for prop in props:
        gltf = download(prop)
        jobs.append(
            {
                "asset": prop.asset,
                "name": f"SM_Hangar_{prop.name}",
                "gltf": str(gltf),
                "pieces": {k: list(v) for k, v in prop.pieces.items()},
                "scale": prop.scale,
            }
        )
        print(f"[verse] downloaded {prop.asset} ({prop.res})")
    results = blender_export(jobs, CACHE / "props_result.json")

    by_asset = {p.asset: p for p in props}
    names = {"assets": [], "materials": [], "meshes": []}
    for job in results:
        prop = by_asset[job["asset"]]
        size = 512 if prop.name in SMALL else 1024
        folder = CACHE / prop.asset / prop.res
        files = [
            p
            for p in folder.rglob("*")
            if p.is_file() and p.suffix in (".gltf", ".bin", ".jpg", ".png")
        ]
        ledger = sorted({ledger_row_hash(p) for p in files})
        for material in job["materials"]:
            # material: {"slot": "M_Hangar_Crane_1", "maps": {kind: image path}}
            mi = "MI_" + material["slot"][2:]
            tex_names: dict[str, str] = {}
            metallic = 0.0
            maps = {k: Path(v) for k, v in material["maps"].items()}
            for kind, source in sorted(maps.items()):
                suffix = MAPS[kind][0]
                tname = f"T_{material['slot'][2:]}_{suffix}"
                # Occlusion, roughness and metal vary slowly: half the colour map's size.
                map_size = size // 2 if kind == "arm" else size
                png, blue = texture_png(
                    source, PNG_OUT / f"{tname}.png", kind, map_size, maps.get("arm")
                )
                if kind == "arm":
                    metallic = blue
                _write(
                    TEX_RECORDS / f"{tname}.import.json",
                    texture_record(tname, png, kind, map_size, [_sha256(source)], prop.asset),
                )
                tex_names[suffix] = tname
                names["assets"].append(tname)
            _write(MI_RECIPES / f"{mi}.mi.json", mi_recipe(mi, tex_names, metallic))
            names["materials"].append(mi)
        for mesh in job["meshes"]:
            for slot in mesh["material_slots"]:
                if slot["slot"] in job["fallbacks"]:
                    slot["mi"] = fallback_mi(job["fallbacks"][slot["slot"]], prop.asset)
            _write(
                MESH_RECORDS / f"{mesh['name']}.import.json", mesh_record(mesh, ledger, prop.asset)
            )
            names["assets"].append(mesh["name"])
            names["meshes"].append(mesh["name"])
            print(f"[verse] {mesh['name']}: {mesh['triangles']} tris, bounds {mesh['bounds_cm']}")
    print("ASSETS=" + ",".join(names["assets"]))
    print("MATERIALS=" + ",".join(names["materials"]))
    print("MESHES=" + ",".join(names["meshes"]))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
