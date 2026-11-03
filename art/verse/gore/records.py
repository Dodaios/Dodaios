#!/usr/bin/env python3
"""Import records of the gore assets (WP05, art-pipeline 10.3).

    python art/verse/gore/records.py           # bake the masks and write the records
    python art/verse/gore/records.py --check   # fail when a committed record is stale

Writes, owned by WP05 (work-packages 0.2, "Art records"):

    unreal/Verse/Art/Import/Gore/T_Gore_*_M.import.json        mask textures (verse.import/1)

Every mask is own work (``license.kind: "own"``) made with numpy, not Blender,
so ``export.blender`` is ``0.0.0``. The masters, ``MF_Gore_WoundMask`` and the
test material are built in the editor and are not an imported kind, so they
need no record. The ``MI_Gore_*`` instances get ``verse.mi/1`` recipes once
contract change request #1171 (item 3) lets VerseGore's own decal master be a
parent; until then ``spec.INSTANCES`` is their single description.
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


def all_records(cache: Path) -> dict[Path, dict]:
    out: dict[Path, dict] = {}
    for name in spec.TEXTURES:
        record = texture_record(name, cache / f"{name}.png")
        out[ART / "Import" / "Gore" / f"{name}.import.json"] = record
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
