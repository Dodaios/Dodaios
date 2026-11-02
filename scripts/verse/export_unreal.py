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
them. `characters` (WP13) builds `SKEL_Verse_Human`, the character meshes and
every clip (`art/verse/characters/rig_fps.py`) and writes their records,
MI recipes and the grip reference; `--only A,B` limits it to named assets.
`deck`, `weapons` and `textures` are reserved for the packages that own
that art (WP11/WP12, WP14) and exit 2 until they land.
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
    chars = sub.add_parser("characters", help="WP13: rig, meshes, clips and their records")
    chars.add_argument("--only", default="")
    chars.add_argument("--no-lock", action="store_true", help="CPU-only run outside the lock")
    for mode in ("weapons", "textures"):
        sub.add_parser(mode, help="reserved")
    options = parser.parse_args(argv)
    try:
        if options.mode == "piece":
            return export_piece(options.name)
        if options.mode == "calib":
            return export_calib()
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
