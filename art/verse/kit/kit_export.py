"""Export kit pieces to FBX for Unreal and write their import records (WP12.2, WP12.3).

    python art/verse/kit/kit_export.py SM_Console_Command SM_Seat_Crew ...
    python art/verse/kit/kit_export.py --missing     # every piece without a record

One headless CPU Blender run exports the whole batch (`kit_export_blender.py`);
the records are built by the same `build_record` as
`scripts/verse/export_unreal.py piece`, into
`unreal/Verse/Art/Import/Kit/<Architecture|Props>/<Name>.import.json`.

The collision block of a piece listed in `kit/collision.py` follows that module
(authored primitives, or none); the material tints of every exported slot are merged
into `kit/material_tints.json`, which `kit/mi_recipes.py` reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ART_ROOT = Path(__file__).resolve().parents[1]
if str(ART_ROOT) not in sys.path:
    sys.path.insert(0, str(ART_ROOT))

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "verse"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "unreal"))

import art_common  # noqa: E402
import blender  # noqa: E402
import export_unreal  # noqa: E402

from kit import collision, tints  # noqa: E402

ENTRY = HERE / "kit_export_blender.py"
LIST_ENTRY = HERE / "kit_list_blender.py"
CACHE = art_common.CACHE_ROOT / "kit"


def piece_names() -> list[str]:
    """Every registered kit piece (asks Blender, which imports the kit)."""
    out = art_common.CACHE_ROOT / "results" / "kit_pieces.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    blender.run(LIST_ENTRY, [str(out)], lock=False, device="cpu", timeout=600)
    return sorted(json.loads(out.read_text(encoding="utf-8")))


def has_record(name: str) -> bool:
    root = art_common.IMPORT_RECORDS / "Kit"
    groups = ("Architecture", "Props")
    return any((root / group / f"{name}.import.json").is_file() for group in groups)


def export(names: list[str], deck: str | None = None) -> int:
    if not names:
        print("[verse] nothing to export")
        return 0
    work = art_common.CACHE_ROOT / "results"
    work.mkdir(parents=True, exist_ok=True)
    names_path = work / "kit_batch.json"
    result_path = work / "kit_batch.result.json"
    names_path.write_text(json.dumps(names), encoding="utf-8")
    result_path.unlink(missing_ok=True)
    args = ["--names", str(names_path), "--out", str(CACHE), "--result", str(result_path)]
    if deck:
        args += ["--deck", deck]
    blender.run(ENTRY, args, lock=False, device="cpu", timeout=3600)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for asset in payload["assets"]:
        record = export_unreal.build_record(asset, None)
        path = export_unreal.record_path(record)
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        record = export_unreal.build_record(asset, previous)
        authored = collision.record_collision(
            asset["name"], record["collision"]["profile"], asset["collision_primitives"]
        )
        if authored is not None:
            record["collision"] = authored
        found.update(asset.get("material_tints") or {})
        art_common.dump_json(path, record)
        print(f"[verse] {asset['name']}: record {art_common.rel(path)}")
    tints.merge(found)
    failed = json.loads(result_path.with_suffix(".failed.json").read_text(encoding="utf-8"))
    for item in failed:
        print(f"[verse] FAILED {item['name']}: {item['error']}", file=sys.stderr)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("names", nargs="*")
    parser.add_argument("--missing", action="store_true", help="every piece without a record")
    parser.add_argument("--deck", help="build this deck first (pieces only it registers)")
    options = parser.parse_args(argv)
    names = list(options.names)
    if options.missing:
        names += [n for n in piece_names() if not has_record(n)]
    return export(sorted(set(names)), options.deck)


if __name__ == "__main__":
    sys.exit(main())
