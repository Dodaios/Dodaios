"""Material instances from `verse.mi/1` recipes (art-pipeline 7).

`python scripts/unreal/import_art.py materials [--only MI_A,MI_B]` creates or
updates each `MI_<Name>` from `unreal/Verse/Art/Materials/**/MI_<Name>.mi.json`
in the instance group folder of `art/verse/lib/unreal_materials.py`
(`MI_Weapon_*` -> `/Game/Verse/Materials/Instances/Weapons/`).

Rules beyond the schema, documented with the masters in
`art/verse/style-unreal.md`:

* Every parameter of a recipe must exist on the parent (a typo fails).
* `switches.UseHoleMask = true` also sets the instance's blend mode
  override to Masked (the opaque masters ignore the opacity mask otherwise).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import MI_RECIPES, REPO_ROOT


def _unreal_materials():
    path = str(REPO_ROOT / "art" / "verse")
    if path not in sys.path:
        sys.path.insert(0, path)
    from lib import unreal_materials

    return unreal_materials


def load_recipes(root: Path = MI_RECIPES) -> list[dict]:
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.rglob("*.mi.json")):
        recipe = json.loads(path.read_text(encoding="utf-8"))
        recipe["_path"] = str(path)
        out.append(recipe)
    return out


def instance_path(recipe: dict) -> str:
    """Object path of the MI a recipe describes (group folder by name prefix). Pure."""
    name = recipe["name"]
    return _unreal_materials().instance_path("M_" + name[3:])


def select(recipes: list[dict], only: list[str]) -> list[dict]:
    if not only:
        return recipes
    by_name = {r["name"]: r for r in recipes}
    missing = [n for n in only if n not in by_name]
    if missing:
        raise KeyError(f"no MI recipe for {', '.join(missing)}")
    return [by_name[n] for n in only]


def _create(unreal, path: str, parent):
    lib = unreal.EditorAssetLibrary
    package = path.rsplit(".", 1)[0]
    if lib.does_asset_exist(package):
        mi = lib.load_asset(package)
    else:
        folder, name = package.rsplit("/", 1)
        factory = unreal.MaterialInstanceConstantFactoryNew()
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        mi = tools.create_asset(name, folder, unreal.MaterialInstanceConstant, factory)
    unreal.MaterialEditingLibrary.set_material_instance_parent(mi, parent)
    return mi


def _parameter_names(unreal, parent) -> dict[str, set[str]]:
    mel = unreal.MaterialEditingLibrary
    return {
        "scalars": {str(n) for n in mel.get_scalar_parameter_names(parent)},
        "vectors": {str(n) for n in mel.get_vector_parameter_names(parent)},
        "textures": {str(n) for n in mel.get_texture_parameter_names(parent)},
        "switches": {str(n) for n in mel.get_static_switch_parameter_names(parent)},
    }


def apply(unreal, recipe: dict, *, save: bool) -> list[str]:
    mel = unreal.MaterialEditingLibrary
    name = recipe["name"]
    parent = unreal.load_asset(recipe["parent"])
    if parent is None:
        return [f"{name}: parent {recipe['parent']} does not exist (build the masters first)"]
    known = _parameter_names(unreal, parent)
    errors = []
    for group in ("scalars", "vectors", "textures", "switches"):
        for param in recipe[group]:
            if param not in known[group]:
                errors.append(
                    f"{name}: {group[:-1]} {param} is not a parameter of {recipe['parent']}"
                )
    if errors:
        return errors
    mi = _create(unreal, instance_path(recipe), parent)
    mel.clear_all_material_instance_parameters(mi)
    for param, value in recipe["scalars"].items():
        mel.set_material_instance_scalar_parameter_value(mi, param, float(value))
    for param, value in recipe["vectors"].items():
        mel.set_material_instance_vector_parameter_value(mi, param, unreal.LinearColor(*value))
    for param, value in recipe["textures"].items():
        texture = unreal.load_asset(value)
        if texture is None:
            errors.append(f"{name}: texture {value} does not exist")
            continue
        mel.set_material_instance_texture_parameter_value(mi, param, texture)
    for param, value in recipe["switches"].items():
        mel.set_material_instance_static_switch_parameter_value(mi, param, bool(value))
    overrides = mi.get_editor_property("base_property_overrides")
    masked = bool(recipe["switches"].get("UseHoleMask", False))
    overrides.set_editor_property("override_blend_mode", masked)
    overrides.set_editor_property(
        "blend_mode", unreal.BlendMode.BLEND_MASKED if masked else unreal.BlendMode.BLEND_OPAQUE
    )
    mi.set_editor_property("base_property_overrides", overrides)
    unreal.EditorAssetLibrary.set_metadata_tag(mi, "VerseRecipeOwner", recipe["owner"])
    mel.update_material_instance(mi)
    if save and not errors:
        unreal.EditorAssetLibrary.save_loaded_asset(mi, only_if_is_dirty=False)
    return errors


def run(only: list[str], *, save: bool = True) -> dict:
    import unreal

    recipes = select(load_recipes(), only)
    report = {"applied": [], "errors": []}
    for recipe in recipes:
        errors = apply(unreal, recipe, save=save)
        report["errors"] += errors
        if not errors:
            report["applied"].append(recipe["name"])
    report["ok"] = not report["errors"]
    return report
