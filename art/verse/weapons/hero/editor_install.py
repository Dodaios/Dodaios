"""Install the hero Graveline's baked skin, optic glass and reticle (headless editor).

`python art/verse/weapons/hero/install_hero.py` runs this file through
`-ExecutePythonScript`. It loads `T_Weapon_GravelineHero_BC/_ORM/_N` (imported from
their records by `import_art.py assets`), keeps them resident and builds:

- `MI_Weapon_GravelineHero` on `M_Verse_Character` (the baked skin),
- `MI_Weapon_OpticHero` on `M_Verse_Glass` (clear coated window),
- `MI_Weapon_ReticleHero` on `M_Verse_Emissive` (red ring and dot),

then puts them on the mesh slots of `SK_Weapon_GravelineHero` when it exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import unreal as u

TEXTURES = "/Game/Verse/Weapons/GravelineHero/Textures"
INSTANCES = "/Game/Verse/Materials/Instances/Weapons"
MASTERS = "/Game/Verse/Materials/Master"
MESH = "/Game/Verse/Weapons/GravelineHero/SK_Weapon_GravelineHero.SK_Weapon_GravelineHero"
STEM = "T_Weapon_GravelineHero"
REPORT: dict = {"imported": [], "instances": [], "errors": []}


def _master(name: str):
    return u.load_asset(f"{MASTERS}/{name}.{name}")


def _instance(name: str, master: str):
    mel = u.MaterialEditingLibrary
    path = f"{INSTANCES}/{name}.{name}"
    mi = u.load_asset(path) or u.AssetToolsHelpers.get_asset_tools().create_asset(
        name, INSTANCES, u.MaterialInstanceConstant, u.MaterialInstanceConstantFactoryNew()
    )
    mel.set_material_instance_parent(mi, _master(master))
    mel.clear_all_material_instance_parameters(mi)
    return mi


def _save(asset, name: str) -> None:
    u.MaterialEditingLibrary.update_material_instance(asset)
    u.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
    REPORT["instances"].append(name)


def load_textures() -> dict:
    """The maps `import_art.py assets` imported from their records; kept fully resident."""
    textures = {}
    for kind in ("BC", "ORM", "N"):
        name = f"{STEM}_{kind}"
        tex = u.load_asset(f"{TEXTURES}/{name}.{name}")
        if tex is None:
            REPORT.setdefault("notes", []).append(f"texture {name} not imported yet")
            continue
        # The viewmodel is drawn pulled towards the eye, so the streamer judges it far away and
        # picks blurred mips (the black optic read brown). Three maps always resident.
        tex.set_editor_property("never_stream", True)
        u.EditorAssetLibrary.save_loaded_asset(tex, only_if_is_dirty=False)
        textures[kind] = tex
        REPORT["imported"].append(name)
    return textures


def build_instances(textures: dict) -> None:
    mel = u.MaterialEditingLibrary
    skin = _instance("MI_Weapon_GravelineHero", "M_Verse_Character")
    for param, kind in (("BaseColorMap", "BC"), ("ORMMap", "ORM"), ("NormalMap", "N")):
        if kind in textures:
            mel.set_material_instance_texture_parameter_value(skin, param, textures[kind])
    mel.set_material_instance_vector_parameter_value(skin, "BaseTint", u.LinearColor(1, 1, 1, 1))
    mel.set_material_instance_scalar_parameter_value(skin, "RoughnessScale", 1.0)
    mel.set_material_instance_scalar_parameter_value(skin, "Roughness", 1.0)
    mel.set_material_instance_scalar_parameter_value(skin, "Metallic", 1.0)
    _save(skin, "MI_Weapon_GravelineHero")

    glass = _instance("MI_Weapon_OpticHero", "M_Verse_Glass")
    mel.set_material_instance_vector_parameter_value(
        glass, "BaseTint", u.LinearColor(0.06, 0.075, 0.08, 1)
    )
    mel.set_material_instance_scalar_parameter_value(glass, "Opacity", 0.1)
    mel.set_material_instance_scalar_parameter_value(glass, "Roughness", 0.02)
    _save(glass, "MI_Weapon_OpticHero")

    reticle = _instance("MI_Weapon_ReticleHero", "M_Verse_Emissive")
    mel.set_material_instance_vector_parameter_value(
        reticle, "EmissiveColor", u.LinearColor(1.0, 0.06, 0.03, 1)
    )
    mel.set_material_instance_scalar_parameter_value(reticle, "EmissiveNits", 60.0)
    _save(reticle, "MI_Weapon_ReticleHero")


def bind_slots() -> None:
    mesh = u.load_asset(MESH)
    if mesh is None:
        REPORT["notes"] = ["mesh not imported yet: slots not bound"]
        return
    by_slot = {
        "M_Weapon_GravelineHero": "MI_Weapon_GravelineHero",
        "M_Weapon_Optic": "MI_Weapon_OpticHero",
        "M_Weapon_Reticle": "MI_Weapon_ReticleHero",
    }
    slots = list(mesh.get_editor_property("materials"))
    for slot in slots:
        imported = str(slot.get_editor_property("imported_material_slot_name"))
        key = next((k for k in by_slot if imported.startswith(k)), None)
        if key is None:
            REPORT["errors"].append(f"slot {imported} has no instance")
            continue
        name = by_slot[key]
        slot.set_editor_property("material_slot_name", key)
        slot.set_editor_property("material_interface", u.load_asset(f"{INSTANCES}/{name}.{name}"))
    mesh.set_editor_property("materials", slots)
    u.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)
    REPORT["slots"] = [str(s.get_editor_property("material_slot_name")) for s in slots]


def main() -> None:
    try:
        textures = load_textures()
        build_instances(textures)
        bind_slots()
    except Exception as error:  # report, never hang the editor
        import traceback

        REPORT["errors"].append(f"{type(error).__name__}: {error}")
        REPORT["traceback"] = traceback.format_exc()
    REPORT["ok"] = not REPORT["errors"]
    target = os.environ.get("VERSE_PIPELINE_RESULT")
    if target:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(json.dumps(REPORT, indent=2) + "\n", encoding="utf-8")
    print(f"[hero_install] ok={REPORT['ok']} {REPORT}")


main()
