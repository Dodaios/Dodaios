"""MI recipes (`verse.mi/1`) for the kit and prop materials (WP12.2, WP12.3, WP12.8).

Pure Python, no bpy. Every Blender material of `art/verse/lib/materials.py` that
lands in a WP12 instance folder (`lib/unreal_materials.py`, contracts/art-pipeline.md
9: every group except Screens, Weapons and Characters) becomes one recipe
`unreal/Verse/Art/Materials/MI_<Name>.mi.json` on a WP14 master. The numbers are a
first Military-Industrial Noir pass (art-pipeline 8): the Blender viewport colour
is the base tint, roughness and metal follow the material family, and the two
accent hues the Noir palette drops from the world are remapped:

* status green indicators become amber (`#F2A33A`),
* info blue indicators become work-light white (`#D9DDE0`).

`verse_pipeline.materials` builds the `.uasset` from these recipes once WP14's
masters exist; until then the recipes are the reviewed text.

    python art/verse/kit/mi_recipes.py            # write every recipe
    python art/verse/kit/mi_recipes.py --check    # exit 1 when one is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ART_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ART_ROOT.parents[1]
if str(ART_ROOT) not in sys.path:
    sys.path.insert(0, str(ART_ROOT))

from lib import unreal_materials  # noqa: E402

MATERIALS_PY = ART_ROOT / "lib" / "materials.py"
RECIPES_ROOT = REPO_ROOT / "unreal" / "Verse" / "Art" / "Materials"
OWNER = "WP12"
#: Instance groups other packages own (art-pipeline 9).
FOREIGN_GROUPS = {"Screens": "WP16", "Weapons": "WP14", "Characters": "WP13"}

MASTER = "/Game/Verse/Materials/Master/{0}.{0}"
_DECL = re.compile(
    r'@material\("(?P<name>M_[A-Za-z0-9_]+)"(?:,\s*viewport=\((?P<rgb>[^)]*)\))?\)'
)

#: Accent remaps of the Noir palette (linear RGB of the sRGB hex in the docstring).
AMBER = (0.887923, 0.366253, 0.042311)
WORK_WHITE = (0.693872, 0.723055, 0.745404)
REMAP = {"M_Indicator_Green": AMBER, "M_Indicator_Blue": WORK_WHITE}

#: Family prefix (after `M_`) -> (roughness min, roughness max, metallic).
SURFACE_FAMILIES = (
    ("Trim_Chrome", 0.08, 0.2, 1.0),
    ("Trim_", 0.25, 0.45, 1.0),
    ("Struct_", 0.35, 0.65, 0.85),
    ("Hull_", 0.45, 0.8, 0.7),
    ("Floor_GlossBlack", 0.12, 0.35, 0.0),
    ("Floor_Grating", 0.4, 0.7, 0.9),
    ("Floor_", 0.3, 0.6, 0.0),
    ("Rubber_", 0.75, 0.95, 0.0),
    ("Lacquer_", 0.1, 0.3, 0.0),
    ("Plastic_", 0.35, 0.6, 0.0),
    ("Fabric_", 0.8, 0.95, 0.0),
    ("Seat_", 0.6, 0.85, 0.0),
    ("Console_", 0.35, 0.6, 0.2),
    ("Wall_", 0.45, 0.75, 0.0),
)
DEFAULT_SURFACE = (0.45, 0.75, 0.0)
EMISSIVE_PREFIXES = ("Light_", "Emit_", "Indicator_")
#: Emissive luminance in nits: panels light rooms, indicators and lamps are small practicals.
EMISSIVE_NITS = {"Light_": 1200.0, "Emit_": 400.0, "Indicator_": 60.0}


def declared_materials(source: Path = MATERIALS_PY) -> dict[str, tuple[float, float, float]]:
    """Blender material name -> viewport colour (linear), read from the library's decorators."""
    out = {}
    for match in _DECL.finditer(source.read_text(encoding="utf-8")):
        rgb = match["rgb"]
        values = tuple(float(v) for v in rgb.split(",")) if rgb else (0.5, 0.5, 0.5)
        out[match["name"]] = values[:3]
    return out


def _family(short: str) -> tuple[float, float, float]:
    for prefix, rmin, rmax, metal in SURFACE_FAMILIES:
        if short.startswith(prefix):
            return rmin, rmax, metal
    return DEFAULT_SURFACE


def _rgba(rgb) -> list[float]:
    return [round(float(c), 6) for c in rgb] + [1.0]


def recipe(blender_name: str, rgb: tuple[float, float, float]) -> dict:
    short = blender_name[2:]
    name = unreal_materials.instance_name(blender_name)
    rgb = REMAP.get(blender_name, rgb)
    doc = {
        "schema": "verse.mi/1",
        "name": name,
        "owner": OWNER,
        "replaces": blender_name,
        "scalars": {},
        "vectors": {},
        "textures": {},
        "switches": {},
    }
    if short.startswith(EMISSIVE_PREFIXES):
        prefix = next(p for p in EMISSIVE_PREFIXES if short.startswith(p))
        doc["parent"] = MASTER.format("M_Verse_Emissive")
        doc["vectors"]["EmissiveColor"] = _rgba(rgb)
        doc["scalars"]["EmissiveNits"] = EMISSIVE_NITS[prefix]
    elif short.startswith("Glass_"):
        doc["parent"] = MASTER.format("M_Verse_Glass")
        doc["vectors"]["BaseTint"] = _rgba(rgb)
        doc["scalars"]["Opacity"] = 0.18
        doc["scalars"]["RoughnessMin"] = 0.02
        doc["scalars"]["RoughnessMax"] = 0.08
    elif short.startswith("Floor_"):
        rmin, rmax, metal = _family(short)
        doc["parent"] = MASTER.format("M_Verse_Floor")
        doc["vectors"]["BaseTint"] = _rgba(rgb)
        doc["scalars"].update(RoughnessMin=rmin, RoughnessMax=rmax, Metallic=metal, Wear=0.35)
    else:
        rmin, rmax, metal = _family(short)
        doc["parent"] = MASTER.format("M_Verse_Surface")
        doc["vectors"]["BaseTint"] = _rgba(rgb)
        doc["scalars"].update(
            RoughnessMin=rmin, RoughnessMax=rmax, Metallic=metal, EdgeWear=0.4, Grime=0.3
        )
        doc["switches"]["UseTriplanar"] = False
    return doc


def recipes() -> list[dict]:
    out = []
    for blender_name, rgb in sorted(declared_materials().items()):
        if unreal_materials.group_for(blender_name) in FOREIGN_GROUPS:
            continue
        out.append(recipe(blender_name, rgb))
    return out


def recipe_path(doc: dict) -> Path:
    return RECIPES_ROOT / f"{doc['name']}.mi.json"


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_all(*, check: bool = False) -> list[str]:
    stale = []
    for doc in recipes():
        path = recipe_path(doc)
        text = dumps(doc)
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(path.relative_to(REPO_ROOT).as_posix())
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args(argv)
    stale = write_all(check=options.check)
    for path in stale:
        print(f"[verse] {'stale' if options.check else 'wrote'} {path}")
    return 1 if options.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
