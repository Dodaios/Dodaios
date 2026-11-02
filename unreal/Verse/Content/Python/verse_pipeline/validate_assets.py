"""`import_art.py validate`: imported assets match their import records (art-pipeline 14).

Checks per static mesh: the asset exists, Nanite matches `nanite.enabled`,
no lightmap UVs are generated, the collision primitive count matches
`collision.primitives` when the record says `authored`, and material slots
carry the slot names of the record. Skeletal weapons get A14.1
(`weapons.check`); every MI from a recipe gets the palette bans of
art-pipeline 8.3 on its vector parameters, and weapon MIs get A14.2 (base
colour luminance at most 0.06 linear, no coloured trim). Texture settings and
LOD screen sizes join here as their assets land.
"""

from __future__ import annotations

import sys

from verse_pipeline import REPO_ROOT, materials, records, weapons

#: Linear luminance cap of A14.2 for the base colour of every weapon material.
WEAPON_LUMINANCE_CAP = 0.06
WEAPON_MI_FOLDER = "/Game/Verse/Materials/Instances/Weapons/"
#: The weapon master clamps its tints in the shader (masters.WEAPON_*_CAP).
WEAPON_CAPS = {"BaseTint": (0.0103, 0.0103, 0.0109), "EdgeTint": (0.0437, 0.0497, 0.0630)}


def luminance(rgb) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def weapon_base_colours(parent: str, vectors: dict) -> dict[str, tuple]:
    """The base colours a weapon MI can show, after the clamps of its master. Pure.

    Emissive masters have a black base; glass shows `BaseTint`; the weapon
    master shows `BaseTint` and `EdgeTint`, each clamped per channel.
    """
    name = parent.rsplit(".", 1)[-1]
    if name in ("M_Verse_Emissive", "M_Verse_Screen"):
        return {}
    keys = ("BaseTint", "EdgeTint") if name == "M_Verse_Weapon" else ("BaseTint",)
    out = {}
    for key in keys:
        value = tuple(vectors.get(key, (0.0, 0.0, 0.0, 1.0))[:3])
        if name == "M_Verse_Weapon":
            value = tuple(min(v, c) for v, c in zip(value, WEAPON_CAPS[key], strict=True))
        out[key] = value
    return out


def weapon_colour_errors(name: str, parent: str, vectors: dict) -> list[str]:
    """A14.2 on one weapon MI: base colour luminance and no coloured trim. Pure."""
    errors = []
    for key, rgb in weapon_base_colours(parent, vectors).items():
        lum = luminance(rgb)
        if lum > WEAPON_LUMINANCE_CAP:
            errors.append(f"{name}: {key} luminance {lum:.4f} > {WEAPON_LUMINANCE_CAP}")
        if max(rgb) > 0 and (max(rgb) - min(rgb)) / max(rgb) > 0.35:
            errors.append(f"{name}: {key} is coloured, weapons are black (A14.2)")
    return errors


def _colour_bans():
    path = str(REPO_ROOT / "scripts" / "unreal")
    if path not in sys.path:
        sys.path.insert(0, path)
    import check_art_text

    return check_art_text.colour_bans


def compare(record: dict, facts: dict) -> list[str]:
    """Differences between a record and the facts read from its asset. Pure."""
    name = record["name"]
    if not facts.get("exists"):
        return [f"{name}: asset {record['asset_path']} does not exist"]
    errors = []
    nanite = record.get("nanite")
    if nanite is not None and facts.get("nanite") is not None:
        if bool(facts["nanite"]) != bool(nanite["enabled"]):
            errors.append(f"{name}: nanite {facts['nanite']} != record {nanite['enabled']}")
    if facts.get("lightmap_uvs"):
        errors.append(f"{name}: lightmap UVs are generated (record says none)")
    collision = record.get("collision")
    if collision and collision["source"] == "authored" and "primitives" in facts:
        if facts["primitives"] != collision["primitives"]:
            got, want_count = facts["primitives"], collision["primitives"]
            errors.append(f"{name}: {got} collision primitives, record {want_count}")
    want = [s["slot"] for s in record.get("mesh", {}).get("material_slots", [])]
    if want and facts.get("slots") is not None and sorted(facts["slots"]) != sorted(want):
        errors.append(f"{name}: material slots {facts['slots']} != record {want}")
    return errors


def _facts(record: dict) -> dict:
    import unreal

    lib = unreal.EditorAssetLibrary
    if not lib.does_asset_exist(record["asset_path"]):
        return {"exists": False}
    asset = lib.load_asset(record["asset_path"])
    facts: dict = {"exists": True}
    if isinstance(asset, unreal.StaticMesh):
        settings = asset.get_editor_property("nanite_settings")
        facts["nanite"] = bool(settings.get_editor_property("enabled"))
        build = unreal.StaticMeshEditorSubsystem
        subsystem = unreal.get_editor_subsystem(build)
        facts["primitives"] = int(subsystem.get_simple_collision_count(asset))
        source = asset.get_source_model(0) if hasattr(asset, "get_source_model") else None
        if source is not None:
            facts["lightmap_uvs"] = bool(
                source.get_editor_property("build_settings").get_editor_property(
                    "generate_lightmap_u_vs"
                )
            )
        materials = asset.get_editor_property("static_materials")
        facts["slots"] = [str(m.get_editor_property("material_slot_name")) for m in materials]
    return facts


def _mi_vectors(unreal, mi) -> dict:
    mel = unreal.MaterialEditingLibrary
    out = {}
    for name in mel.get_vector_parameter_names(mi):
        c = mel.get_material_instance_vector_parameter_value(mi, name)
        out[str(name)] = (c.r, c.g, c.b, c.a)
    return out


def check_materials(only: list[str]) -> tuple[list[str], list[str]]:
    """Palette bans (art-pipeline 8.3) on every MI from a recipe, A14.2 on weapon MIs."""
    import unreal

    errors, checked = [], []
    bans = _colour_bans()
    allow = REPO_ROOT / "art" / "verse" / "gold_allowlist.txt"
    gold_ok = set(allow.read_text(encoding="utf-8").split()) if allow.is_file() else set()
    for recipe in materials.load_recipes():
        if only and recipe["name"] not in only:
            continue
        path = materials.instance_path(recipe)
        mi = unreal.load_asset(path)
        if mi is None:
            errors.append(f"{recipe['name']}: {path} does not exist")
            continue
        parent = mi.get_editor_property("parent")
        if parent is None or parent.get_path_name() != recipe["parent"]:
            errors.append(f"{recipe['name']}: parent is not {recipe['parent']}")
        vectors = _mi_vectors(unreal, mi)
        gold = recipe["name"] in gold_ok
        for param, value in sorted(vectors.items()):
            errors += bans(f"{recipe['name']}.{param}", list(value), gold_allowed=gold)
        if path.startswith(WEAPON_MI_FOLDER):
            errors += weapon_colour_errors(recipe["name"], recipe["parent"], vectors)
        checked.append(recipe["name"])
    return errors, checked


def run(only: list[str]) -> dict:
    mesh_only = [n for n in only if not n.startswith("MI_")]
    selected = records.select(records.load_all(), mesh_only)
    errors = []
    checked = []
    for record in selected:
        if record["kind"] == "skeletal_mesh" and weapons.is_weapon(record):
            errors += weapons.check(record, weapons.facts(record))
            checked.append(record["name"])
            continue
        if record["kind"] not in ("static_mesh", "proxy_mesh"):
            continue
        errors += compare(record, _facts(record))
        checked.append(record["name"])
    mi_errors, mi_checked = check_materials([n for n in only if n.startswith("MI_")])
    errors += mi_errors
    return {"checked": checked + mi_checked, "errors": errors, "ok": not errors}
