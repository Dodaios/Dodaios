"""MI recipes (`verse.mi/1`) for the kit, prop, deck and space materials (WP12.2-12.9).

Pure Python, no bpy. One recipe `unreal/Verse/Art/Materials/MI_<Name>.mi.json` per
material instance WP12 owns (art-pipeline 7, 9: every instance group except Screens,
Weapons and Characters):

* every material of `art/verse/lib/materials.py` in a WP12 group, tinted from its
  declared viewport colour;
* every other material a WP12 import record puts in a slot (the decks' own materials such
  as `M_Ops_Light_Corridor`, the props' stand-ins `M_PropsInd_*` and `M_Fabric_Linen`),
  tinted from what the export read off its Principled BSDF (`kit/material_tints.json`);
* the space view's instances (`SPACE`).

The numbers are a first Military-Industrial Noir pass (art-pipeline 8): roughness and
metal follow the material family, and the two accent hues the Noir palette drops from
the world are remapped:

* status green indicators become amber (`#F2A33A`),
* info blue indicators become work-light white (`#D9DDE0`).

Parameter names are those of the WP14 masters (`MASTER_PARAMS`); `verse_pipeline.materials`
refuses a recipe with a parameter its parent lacks. It builds the `.uasset` from these
recipes once WP14's masters exist; until then the recipes are the reviewed text.

    python art/verse/kit/mi_recipes.py            # write every recipe
    python art/verse/kit/mi_recipes.py --check    # exit 1 when one is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

ART_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ART_ROOT.parents[1]
if str(ART_ROOT) not in sys.path:
    sys.path.insert(0, str(ART_ROOT))

from lib import unreal_materials  # noqa: E402

from kit import tints as tint_file  # noqa: E402

MATERIALS_PY = ART_ROOT / "lib" / "materials.py"
RECIPES_ROOT = REPO_ROOT / "unreal" / "Verse" / "Art" / "Materials"
IMPORT_ROOT = REPO_ROOT / "unreal" / "Verse" / "Art" / "Import"
#: Import record folders whose assets WP12 owns (art-pipeline 9).
RECORD_FOLDERS = ("Kit", "Decks")
OWNER = "WP12"
#: Instance groups other packages own (art-pipeline 9).
FOREIGN_GROUPS = {"Screens": "WP16", "Weapons": "WP14", "Characters": "WP13"}

MASTER = "/Game/Verse/Materials/Master/{0}.{0}"
#: Parameters of the WP14 masters a WP12 recipe may set, by group.
MASTER_PARAMS = {
    "M_Verse_Surface": {
        "scalars": {"RoughnessMin", "RoughnessMax", "Metallic", "EdgeWear", "GrimeAmount"},
        "vectors": {"BaseTint"},
        "switches": {"UseTriplanar"},
        "textures": set(),
    },
    "M_Verse_Floor": {
        "scalars": {"RoughnessMin", "RoughnessMax", "WearAmount"},
        "vectors": {"BaseTint"},
        "switches": set(),
        "textures": set(),
    },
    "M_Verse_Emissive": {
        "scalars": {"EmissiveNits"},
        "vectors": {"EmissiveColor"},
        "switches": set(),
        "textures": set(),
    },
    "M_Verse_Glass": {
        "scalars": {"Opacity", "Roughness", "EmissiveNits"},
        "vectors": {"BaseTint", "EmissiveColor"},
        "switches": set(),
        "textures": set(),
    },
    "M_Verse_Screen": {
        "scalars": {"EmissiveNits", "Roughness"},
        "vectors": {"ScreenTint"},
        "switches": set(),
        "textures": {"ScreenTexture"},
    },
    "M_Verse_Space": {
        "scalars": {"StarScale", "Planet", "SpaceGain"},
        "vectors": set(),
        "switches": set(),
        "textures": {"DayMap", "NightMap", "CloudMap", "ReliefMap", "StarMap"},
    },
}

_DECL = re.compile(r'@material\("(?P<name>M_[A-Za-z0-9_]+)"(?:,\s*viewport=\((?P<rgb>[^)]*)\))?\)')

#: Accent remaps of the Noir palette (linear RGB of the sRGB hex in the docstring).
AMBER = (0.887923, 0.366253, 0.042311)
WORK_WHITE = (0.693872, 0.723055, 0.745404)
REMAP = {"M_Indicator_Green": AMBER, "M_Indicator_Blue": WORK_WHITE}

#: Area prefixes of builder-local material names, dropped before the family is chosen.
AREA_PREFIXES = ("Ops_", "Hangar_", "Eng_", "Bridge_", "PropsInd_", "Reactor_")
#: Family prefix (after `M_` and an area prefix) -> (roughness min, roughness max, metallic).
SURFACE_FAMILIES = (
    ("Trim_Chrome", 0.08, 0.2, 1.0),
    ("Trim_", 0.25, 0.45, 1.0),
    ("Struct_", 0.35, 0.65, 0.85),
    ("Hull_", 0.45, 0.8, 0.7),
    ("Metal_", 0.3, 0.55, 1.0),
    ("Floor_Grating", 0.4, 0.7, 0.9),
    ("Grating", 0.4, 0.7, 0.9),
    ("Tread", 0.4, 0.7, 0.9),
    ("Floor_GlossBlack", 0.12, 0.35, 0.0),
    ("Floor_", 0.3, 0.6, 0.0),
    ("Rubber_", 0.75, 0.95, 0.0),
    ("Lacquer_", 0.1, 0.3, 0.0),
    ("Plastic_", 0.35, 0.6, 0.0),
    ("Fabric_", 0.8, 0.95, 0.0),
    ("Seat_", 0.6, 0.85, 0.0),
    ("Console_", 0.35, 0.6, 0.2),
    ("Container", 0.45, 0.75, 0.3),
    ("Stencil", 0.5, 0.8, 0.0),
    ("Paint_", 0.4, 0.7, 0.0),
    ("Wall_", 0.45, 0.75, 0.0),
    ("Table_", 0.3, 0.55, 0.0),
)
DEFAULT_SURFACE = (0.45, 0.75, 0.0)
EMISSIVE_PREFIXES = ("Light_", "Emit_", "Indicator_", "Lamp", "Core", "Starfield", "Sign")
#: Emissive luminance in nits: panels light rooms, indicators and lamps are small practicals.
EMISSIVE_NITS = {"Light_": 1200.0, "Emit_": 400.0, "Indicator_": 60.0}
DEFAULT_EMISSIVE_NITS = 400.0
#: Emission strength (Blender W/m2 or strength) above which a material counts as a light.
EMISSIVE_STRENGTH = 0.5
GLASS_PREFIXES = ("Glass_", "Glass", "Haze", "Field")
GLASS_OPACITY = 0.18

#: The space view's instances (WP12.9): the view of `engine/realtime/spaceView.ts`, drawn per
#: pixel by `M_Verse_Space` from the same images (`kit/props/space/space_textures.py`).
#: `MI_Space_Earth` is the whole view; `MI_Space_Stars` the stars alone (`planet` 0).
SPACE_TEXTURES = "/Game/Verse/Kit/Space/{0}.{0}"
SPACE_MAPS = {
    "DayMap": SPACE_TEXTURES.format("T_Space_EarthDay_BC"),
    "NightMap": SPACE_TEXTURES.format("T_Space_EarthNight_E"),
    "CloudMap": SPACE_TEXTURES.format("T_Space_EarthClouds_M"),
    "ReliefMap": SPACE_TEXTURES.format("T_Space_EarthRelief_M"),
    "StarMap": SPACE_TEXTURES.format("T_Space_Stars_E"),
}
SPACE_VIEW = {
    "parent": "M_Verse_Space",
    "scalars": {"StarScale": 4.0, "Planet": 1.0, "SpaceGain": 1.0},
    "textures": SPACE_MAPS,
}
SPACE = {
    "MI_Space_Earth": {**SPACE_VIEW, "replaces": "M_Space_Earth"},
    "MI_Space_Stars": {
        **SPACE_VIEW,
        "replaces": "M_Space_Stars",
        "scalars": {**SPACE_VIEW["scalars"], "Planet": 0.0},
    },
    # The decks' star cards behind the viewports: three.js hides them and draws space there
    # (`realtimeScene.ts`, "Starfield"); here they draw it themselves.
    "MI_Starfield": {**SPACE_VIEW, "replaces": "M_Starfield"},
    "MI_Ops_Starfield": {**SPACE_VIEW, "replaces": "M_Ops_Starfield"},
}


def declared_materials(source: Path = MATERIALS_PY) -> dict[str, tuple[float, float, float]]:
    """Blender material name -> viewport colour (linear), read from the library's decorators."""
    out = {}
    for match in _DECL.finditer(source.read_text(encoding="utf-8")):
        rgb = match["rgb"]
        values = tuple(float(v) for v in rgb.split(",")) if rgb else (0.5, 0.5, 0.5)
        out[match["name"]] = values[:3]
    return out


def foreign_recipes(root: Path = RECIPES_ROOT) -> set[str]:
    """Names of committed MI recipes another package owns (for example the hangar's WP11 props)."""
    names: set[str] = set()
    for path in root.rglob("MI_*.mi.json") if root.is_dir() else []:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("owner") != OWNER:
            names.add(doc["name"])
    return names


def referenced_materials(root: Path = IMPORT_ROOT) -> dict[str, str]:
    """MI object path -> Blender slot name, for every slot of every WP12 import record.

    Slots whose MI is another package's committed recipe are left to that package.
    """
    out: dict[str, str] = {}
    foreign = foreign_recipes()
    for folder in RECORD_FOLDERS:
        for path in sorted((root / folder).rglob("*.import.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("owner") != OWNER:
                continue
            for slot in record.get("mesh", {}).get("material_slots", []):
                if mi_name(slot["mi"]) not in foreign:
                    out.setdefault(slot["mi"], slot["slot"])
    return out


def mi_name(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def group_of(path: str) -> str:
    """Instance group folder of an MI object path."""
    return path.split("/Instances/", 1)[1].split("/", 1)[0] if "/Instances/" in path else ""


def _short(blender_name: str) -> str:
    short = blender_name[2:] if blender_name.startswith("M_") else blender_name
    for prefix in AREA_PREFIXES:
        if short.startswith(prefix):
            return short[len(prefix) :]
    return short


def _family(short: str) -> tuple[float, float, float]:
    for prefix, rmin, rmax, metal in SURFACE_FAMILIES:
        if short.startswith(prefix):
            return rmin, rmax, metal
    return DEFAULT_SURFACE


def _rgba(rgb) -> list[float]:
    return [round(float(c), 6) for c in rgb[:3]] + [1.0]


def _doc(name: str, blender_name: str, parent: str) -> dict:
    return {
        "schema": "verse.mi/1",
        "name": name,
        "owner": OWNER,
        "replaces": blender_name,
        "parent": MASTER.format(parent),
        "scalars": {},
        "vectors": {},
        "textures": {},
        "switches": {},
    }


def recipe(blender_name: str, rgb, tint: Mapping | None = None) -> dict:
    """The recipe of one Blender material; `tint` is its `material_tints.json` entry, if any."""
    short = _short(blender_name)
    try:
        name = unreal_materials.instance_name(blender_name)
    except ValueError:  # a slot name that is not a Verse material name; `recipes` renames it
        name = f"MI_{short}"
    tint = dict(tint or {})
    rgb = REMAP.get(blender_name, rgb)
    emission = tint.get("emission") or [0.0, 0.0, 0.0]
    strength = float(tint.get("strength", 0.0)) if max(emission) > 0.0 else 0.0
    glassy = float(tint.get("transmission", 0.0)) > 0.5 or float(tint.get("alpha", 1.0)) < 0.6
    if short.startswith(EMISSIVE_PREFIXES) or strength > EMISSIVE_STRENGTH:
        doc = _doc(name, blender_name, "M_Verse_Emissive")
        prefix = next((p for p in EMISSIVE_NITS if short.startswith(p)), None)
        colour = emission if strength > EMISSIVE_STRENGTH and blender_name not in REMAP else rgb
        doc["vectors"]["EmissiveColor"] = _rgba(colour)
        doc["scalars"]["EmissiveNits"] = EMISSIVE_NITS.get(prefix, DEFAULT_EMISSIVE_NITS)
    elif short.startswith(GLASS_PREFIXES) or glassy:
        doc = _doc(name, blender_name, "M_Verse_Glass")
        doc["vectors"]["BaseTint"] = _rgba(rgb)
        doc["scalars"]["Opacity"] = GLASS_OPACITY
        doc["scalars"]["Roughness"] = 0.05
    elif short.startswith("Floor_") and not short.startswith("Floor_Grating"):
        rmin, rmax, _metal = _family(short)
        doc = _doc(name, blender_name, "M_Verse_Floor")
        doc["vectors"]["BaseTint"] = _rgba(rgb)
        doc["scalars"].update(RoughnessMin=rmin, RoughnessMax=rmax, WearAmount=0.35)
    else:
        rmin, rmax, metal = _family(short)
        if "metallic" in tint and tint.get("source") == "bsdf":
            metal = round(float(tint["metallic"]), 3)
        doc = _doc(name, blender_name, "M_Verse_Surface")
        doc["vectors"]["BaseTint"] = _rgba(rgb)
        doc["scalars"].update(
            RoughnessMin=rmin, RoughnessMax=rmax, Metallic=metal, EdgeWear=0.4, GrimeAmount=0.3
        )
        doc["switches"]["UseTriplanar"] = False
    return doc


def _check_art_text():
    scripts = REPO_ROOT / "scripts" / "unreal"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import check_art_text  # noqa: PLC0415 - scripts/unreal is not a package

    return check_art_text


def _rendered_ban(rgba: list[float]) -> bool:
    """The rendered-pixel rule of art-pipeline 8.3 on a colour seen directly (lights, glass)."""
    import colorsys  # noqa: PLC0415

    srgb = [min(1.0, _check_art_text()._srgb(c)) for c in rgba[:3]]  # noqa: SLF001
    hue, sat, value = colorsys.rgb_to_hsv(*srgb)
    return 160.0 <= hue * 360.0 <= 330.0 and sat > 0.25 and value > 0.08


def noir(param: str, rgba: list[float], *, gold_allowed: bool = False) -> list[float]:
    """`rgba` pulled toward grey until the art-pipeline 8.3 bans pass (the gate's own test).

    Colours a camera sees directly (emissive and glass tints) also keep clear of the
    rendered-pixel rule, so a lamp never shows up as a banned pixel in a reference view.
    """
    bans = _check_art_text().colour_bans
    direct = "emissive" in param.lower() or "tint" in param.lower()
    light = "emissive" in param.lower()

    def bad(c: list[float]) -> bool:
        if bans(param, c, gold_allowed=gold_allowed) or (direct and _rendered_ban(c)):
            return True
        # A light is never green- or blue-dominant (info blue and status green leave the world).
        r, g, b = c[:3]
        return light and ((g > r * 1.02 and g > b * 1.02) or (b > r * 1.2 and b > g * 1.2))

    out = list(rgba)
    for _ in range(60):
        if not bad(out):
            return [round(v, 6) for v in out]
        grey = 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
        out = [grey + (c - grey) * 0.85 for c in out[:3]] + out[3:]
    grey = round(0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2], 6)
    return [grey, grey, grey] + [round(v, 6) for v in out[3:]]


def space_recipes() -> list[dict]:
    out = []
    for name, spec in sorted(SPACE.items()):
        doc = _doc(name, spec["replaces"], spec["parent"])
        for key in ("scalars", "vectors", "textures"):
            doc[key] = dict(spec.get(key, {}))
        out.append(doc)
    return out


def recipes(
    declared: Mapping[str, tuple] | None = None,
    referenced: Mapping[str, str] | None = None,
    tints: Mapping[str, Mapping] | None = None,
) -> list[dict]:
    """Every WP12 recipe, sorted by name."""
    declared = declared_materials() if declared is None else declared
    referenced = referenced_materials() if referenced is None else referenced
    tints = tint_file.load() if tints is None else tints
    wanted: dict[str, str] = {}
    for blender_name in declared:
        name = unreal_materials.instance_name(blender_name)
        if unreal_materials.group_for(blender_name) not in FOREIGN_GROUPS and name not in SPACE:
            wanted[name] = blender_name
    for path, slot in referenced.items():
        if group_of(path) in FOREIGN_GROUPS or mi_name(path) in SPACE:
            continue
        wanted.setdefault(mi_name(path), slot)
    out = []
    for name, blender_name in sorted(wanted.items()):
        tint = tints.get(blender_name)
        if blender_name in declared:
            rgb = declared[blender_name]
        elif tint is not None:
            rgb = tint["base"]
        else:
            rgb = (0.05, 0.05, 0.05)
        doc = recipe(blender_name, rgb, tint)
        doc["name"] = name
        doc["vectors"] = {k: noir(k, v) for k, v in doc["vectors"].items()}
        out.append(doc)
    out += space_recipes()
    return sorted(out, key=lambda d: d["name"])


def unknown_parameters(doc: Mapping) -> list[str]:
    """Parameters a recipe sets that its WP14 parent does not have."""
    parent = doc["parent"].rsplit(".", 1)[-1]
    known = MASTER_PARAMS.get(parent)
    if known is None:
        return [f"parent {parent}"]
    return [
        f"{group}.{param}"
        for group in ("scalars", "vectors", "textures", "switches")
        for param in doc[group]
        if param not in known[group]
    ]


def recipe_path(doc: dict) -> Path:
    return RECIPES_ROOT / f"{doc['name']}.mi.json"


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_all(*, check: bool = False, docs: Iterable[dict] | None = None) -> list[str]:
    stale = []
    for doc in recipes() if docs is None else docs:
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
