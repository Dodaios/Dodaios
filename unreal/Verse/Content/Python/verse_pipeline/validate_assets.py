"""`import_art.py validate`: imported assets match their import records (art-pipeline 14).

Checks per static mesh: the asset exists, Nanite matches `nanite.enabled`,
no lightmap UVs are generated, the collision primitive count matches
`collision.primitives` when the record says `authored`, and material slots
carry the slot names of the record. With WP14's editor code in the tree
(art-pipeline 2), skeletal weapons get A14.1 (`weapons.editor.rig.check`),
every static mesh with Nanite on a translucent master fails (6.2), every MI
from a recipe gets the palette bans of 8.3 on its vector parameters and weapon
MIs get A14.2 (`weapons.editor.checks`). Texture settings and LOD screen sizes
join here as their assets land.
"""

from __future__ import annotations

from verse_pipeline import records, wp14_editor


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


def run(only: list[str]) -> dict:
    rig, checks = wp14_editor("rig"), wp14_editor("checks")
    mesh_only = [n for n in only if not n.startswith("MI_")]
    selected = records.select(records.load_all(), mesh_only) if mesh_only or not only else []
    errors = []
    checked = []
    parents = checks.recipe_parents() if checks is not None else {}
    for record in selected:
        if rig is not None and record["kind"] == "skeletal_mesh" and rig.is_weapon(record):
            errors += rig.check(record, rig.facts(record))
            checked.append(record["name"])
            continue
        if record["kind"] not in ("static_mesh", "proxy_mesh"):
            continue
        errors += compare(record, _facts(record))
        if checks is not None:
            errors += checks.translucent_nanite_errors(record, parents)
        checked.append(record["name"])
    if checks is not None:
        mi_errors, mi_checked = checks.check_materials([n for n in only if n.startswith("MI_")])
        errors += mi_errors
        checked += mi_checked
    return {"checked": checked, "errors": errors, "ok": not errors}
