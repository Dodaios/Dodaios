"""CC0 texture sets of the Unreal hangar arena (WP11, arena.md 9.2).

Downloads the Poly Haven maps below into the git-ignored cache through
`lib.textures.ensure` (MD5 check, one append-only row per file in
`art/verse/LICENSES.md`), converts them to PNG at 2K and writes one
`verse.import/1` texture record per map under
`unreal/Verse/Art/Import/Textures/Arena/`. Every record cites its ledger row
(`license.kind: "ledger"`). Import with
`python scripts/unreal/import_art.py assets --only T_Arena_...`.

    python art/verse/decks/hangar/unreal_arena/textures.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

VERSE = Path(__file__).resolve().parents[3]
REPO = VERSE.parents[1]
if str(VERSE) not in sys.path:
    sys.path.insert(0, str(VERSE))

from lib import textures  # noqa: E402

#: Set name -> Poly Haven asset (all CC0).
SETS: dict[str, str] = {
    "Deck": "hangar_concrete_floor",
    "Panel": "metal_plate_02",
    "Concrete": "painted_concrete_02",
    "Paint": "rusty_painted_metal",
    "Tread": "metal_plate",
    "Slab": "concrete_slab_wall_02",
    "Cladding": "factory_wall",
    "Grate": "metal_grate_rusty",
}
#: Map key -> (suffix, sRGB, compression, flip green).
MAPS: dict[str, tuple[str, bool, str, bool]] = {
    "Diffuse": ("BC", True, "Default", False),
    "arm": ("ORM", False, "Masks", False),
    "nor_gl": ("N", False, "Normalmap", True),
}
OUT = VERSE / ".cache" / "unreal" / "textures" / "arena"
RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import" / "Textures" / "Arena"
MAX_SIZE = 2048
#: Sets whose colour map is stored as luminance, so the arena MI's tint picks the paint colour.
LUMINANCE = {"Panel", "Paint", "Tread", "Cladding", "Grate"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png(source: Path, target: Path, luminance: bool = False) -> Path:
    from PIL import Image

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = image.convert("L").convert("RGB") if luminance else image.convert("RGB")
        if max(image.size) > MAX_SIZE:
            image = image.resize((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)
        image.save(target, optimize=True)
    return target


def record(name: str, set_name: str, asset: str, key: str, png: Path, ledger: str) -> dict:
    suffix, srgb, compression, flip = MAPS[key]
    return {
        "asset_path": f"/Game/Verse/Textures/Arena/{name}.{name}",
        "export": {
            "blender": "0.0.0",
            "file": png.relative_to(REPO).as_posix(),
            "format": "png",
            "settings_id": "png-ue/1",
            "sha256": _sha256(png),
        },
        "kind": "texture",
        "license": {"kind": "ledger", "ledger_sha256": [ledger]},
        "lightmap": "none",
        "name": name,
        "owner": "WP11",
        "schema": "verse.import/1",
        "source": {
            "args": {"asset": asset, "map": key, "set": set_name},
            "builder": "art/verse/decks/hangar/unreal_arena/textures.py",
            "function": "main",
        },
        "texture": {
            "compression": compression,
            "flip_green": flip,
            "group": "WorldNormalMap" if suffix == "N" else "World",
            "max_size": MAX_SIZE,
            "srgb": srgb,
        },
    }


def main() -> int:
    RECORDS.mkdir(parents=True, exist_ok=True)
    for set_name, asset in SETS.items():
        paths = textures.ensure(asset, list(MAPS), res="2k")
        for key, source in paths.items():
            name = f"T_Arena_{set_name}_{MAPS[key][0]}"
            grey = key == "Diffuse" and set_name in LUMINANCE
            png = _png(source, OUT / f"{name}.png", luminance=grey)
            doc = record(name, set_name, asset, key, png, _sha256(source))
            text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
            (RECORDS / f"{name}.import.json").write_bytes(text.encode("utf-8"))
            print(f"[verse] {name} <- {asset} {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
