"""Export Verse art from the Blender builders to FBX for Unreal (art-pipeline 2).

The only export entry for agents. It runs headless Blender through
`scripts/verse/blender.py` while holding the machine-wide `gpu-heavy.lock`,
writes FBX files into the ignored cache `art/verse/.cache/unreal/` and, for
assets that ship, the committed import records
`unreal/Verse/Art/Import/<Kind>/<Asset>.import.json` (art-pipeline 10.3).

    python scripts/verse/export_unreal.py piece SM_Wall_480
    python scripts/verse/export_unreal.py calib
    python scripts/verse/export_unreal.py {deck <deck> [--zone Z] | characters | weapons | textures}

`calib` exports the `fbx-ue/1` calibration assets (`kit/calib.py`) into the
cache only; `python scripts/unreal/import_art.py calib` imports and checks
them. `deck`, `characters`, `weapons` and `textures` are reserved for the
packages that own that art (WP11/WP12, WP13, WP14) and exit 2 until they
land.
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
    "characters": "WP13",
    "weapons": "WP14",
    "textures": "the package that creates the texture set",
}

#: Kit module prefix -> (content folder under /Game/Verse/Kit, record folder).
KIT_GROUPS = (
    ("kit.architecture", "Architecture"),
    ("kit.props", "Props"),
)
KIT_OWNER = "WP12"
PROP_SMALL_CM = 30.0
PROP_NANITE_MIN_TRIS = 300


def _run_blender(mode_args: list[str], label: str) -> dict:
    out_dir = art_common.CACHE_ROOT / ("calib" if mode_args[0] == "calib" else "kit")
    result = art_common.CACHE_ROOT / "results" / f"{label}.json"
    result.unlink(missing_ok=True)
    args = [*mode_args, "--out", str(out_dir), "--result", str(result)]
    with art_common.heavy_lock(f"export_unreal {label}"):
        blender.run(ENTRY, args, lock=False, device="cpu", timeout=1800)
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
    for mode in ("characters", "weapons", "textures"):
        sub.add_parser(mode, help="reserved")
    options = parser.parse_args(argv)
    try:
        if options.mode == "piece":
            return export_piece(options.name)
        if options.mode == "calib":
            return export_calib()
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
