#!/usr/bin/env python3
"""Import records and MI recipes of the gore assets (WP05, art-pipeline 7 and 10.3).

    python art/verse/gore/records.py           # bake the masks and write the records
    python art/verse/gore/records.py --check   # fail when a committed record is stale

Writes, owned by WP05 (work-packages 0.2, "Art records"):

    unreal/Verse/Art/Import/Gore/T_Gore_*_M.import.json        mask textures (verse.import/1)
    unreal/Verse/Art/Import/Gore/M_Gore_*.import.json          masters and MF_Gore_WoundMask
    unreal/Verse/Art/Import/Test/WP05/M_Gore_TestBody.import.json
    unreal/Verse/Art/Materials/Gore/MI_Gore_*.mi.json          decal instances (verse.mi/1)

Every asset is own work (``license.kind: "own"``). The masks come from numpy,
not Blender, so ``export.blender`` is ``0.0.0``. Masters and the material
function are built in the editor and have no export file; their records use
the kinds ``material`` and ``material_function`` (the change request for
these additive schema values is issue #1171).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

import spec  # noqa: E402

CACHE = REPO / "art" / "verse" / ".cache" / "unreal" / "gore"
ART = REPO / "unreal" / "Verse" / "Art"
BUILDER = "art/verse/gore/unreal_assets.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def texture_record(name: str, png: Path) -> dict:
    return {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": spec.asset_path(spec.GORE, name),
        "kind": "texture",
        "source": {"builder": "art/verse/gore/textures.py", "function": "all_textures", "args": {}},
        "export": {
            "format": "png",
            "settings_id": "png-ue/1",
            "file": png.relative_to(REPO).as_posix(),
            "sha256": _sha256(png),
            "blender": "0.0.0",
        },
        "lightmap": "none",
        "texture": {
            "group": "World",
            "max_size": spec.TEXTURES[name],
            "srgb": False,
            "compression": "Masks",
            "flip_green": False,
            "channels": dict(spec.TEXTURE_CHANNELS),
        },
        "license": {"kind": "own"},
        "owner": spec.OWNER,
    }


def material_record(name: str) -> dict:
    folder, kind, function, use = spec.MATERIALS[name]
    return {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": spec.asset_path(folder, name),
        "kind": kind,
        "source": {"builder": BUILDER, "function": function, "args": {"use": use}},
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": spec.OWNER,
    }


def instance_recipe(name: str) -> dict:
    texture, scalars = spec.INSTANCES[name]
    return {
        "schema": "verse.mi/1",
        "name": name,
        "parent": spec.asset_path(spec.GORE, "M_Gore_Decal"),
        "scalars": dict(sorted(scalars.items())),
        "vectors": {},
        "textures": {"Mask": spec.asset_path(spec.GORE, texture)},
        "switches": {},
        "owner": spec.OWNER,
        "replaces": None,
    }


def all_records(cache: Path) -> dict[Path, dict]:
    out: dict[Path, dict] = {}
    for name in spec.TEXTURES:
        record = texture_record(name, cache / f"{name}.png")
        out[ART / "Import" / "Gore" / f"{name}.import.json"] = record
    for name, (folder, _kind, _function, _use) in spec.MATERIALS.items():
        sub = Path("Gore") if folder == spec.GORE else Path("Test") / "WP05"
        out[ART / "Import" / sub / f"{name}.import.json"] = material_record(name)
    for name in spec.INSTANCES:
        out[ART / "Materials" / "Gore" / f"{name}.mi.json"] = instance_recipe(name)
    return out


def render(record: dict) -> str:
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    options = parser.parse_args(argv)

    import textures

    textures.bake(CACHE)
    stale = []
    for path, record in all_records(CACHE).items():
        text = render(record)
        if options.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.relative_to(REPO).as_posix())
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    if stale:
        print("[gore] stale records:\n  " + "\n  ".join(stale))
        return 1
    print("[gore] records " + ("current" if options.check else "written"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
