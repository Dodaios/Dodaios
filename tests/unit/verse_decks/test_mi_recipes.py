"""WP12: kit and prop MI recipes in Military-Industrial Noir (art-pipeline 7, 8, 9)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mi_recipes = _load("verse_mi_recipes", ROOT / "art" / "verse" / "kit" / "mi_recipes.py")
check_art_text = _load("verse_check_art_text", ROOT / "scripts" / "unreal" / "check_art_text.py")


def committed():
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(mi_recipes.RECIPES_ROOT.glob("MI_*.mi.json"))
    ]


def test_every_wp12_material_has_an_up_to_date_recipe():
    assert mi_recipes.write_all(check=True) == []
    names = {doc["name"] for doc in committed() if doc["owner"] == "WP12"}
    wanted = {doc["name"] for doc in mi_recipes.recipes()}
    assert names == wanted
    assert len(wanted) >= 40


def test_recipes_never_cover_another_package_folder():
    for doc in mi_recipes.recipes():
        group = mi_recipes.unreal_materials.group_for(doc["replaces"])
        assert group not in mi_recipes.FOREIGN_GROUPS, doc["name"]
    assert "MI_Screen" not in {doc["name"] for doc in mi_recipes.recipes()}


def test_recipes_pass_the_schema_and_the_colour_bans():
    validator = check_art_text._validator(ROOT / "art" / "verse" / "schema" / "mi.schema.json")
    for doc in mi_recipes.recipes():
        assert check_art_text._schema_errors(validator, doc) == [], doc["name"]
        for param, value in doc["vectors"].items():
            assert check_art_text.colour_bans(param, value, gold_allowed=False) == [], doc["name"]


def test_noir_drops_status_green_and_info_blue_from_the_world():
    by_name = {doc["replaces"]: doc for doc in mi_recipes.recipes()}
    green = by_name["M_Indicator_Green"]["vectors"]["EmissiveColor"]
    blue = by_name["M_Indicator_Blue"]["vectors"]["EmissiveColor"]
    assert green[:3] == [round(v, 6) for v in mi_recipes.AMBER]
    assert blue[:3] == [round(v, 6) for v in mi_recipes.WORK_WHITE]
    for doc in mi_recipes.recipes():
        if doc["parent"].endswith("M_Verse_Emissive"):
            r, g, b, _a = doc["vectors"]["EmissiveColor"]
            assert not (g > r and g > b), f"{doc['name']} is green-dominant"
            assert not (b > r * 1.2 and b > g * 1.2), f"{doc['name']} is blue-dominant"


def test_surface_families_are_physical():
    for doc in mi_recipes.recipes():
        scalars = doc["scalars"]
        if "Metallic" in scalars:
            assert 0.0 <= scalars["Metallic"] <= 1.0
            assert 0.0 <= scalars["RoughnessMin"] <= scalars["RoughnessMax"] <= 1.0
