"""`import_art.py bind`: put each mesh's material instances into its slots.

Imports never create or assign materials (art-pipeline 2): a mesh comes in with
empty slots named after its Blender materials, and its import record lists the
MI for every slot (`mesh.material_slots[].mi`). This command loads each static
or skeletal mesh of the selected records and sets every slot to its MI, so the
kit, the weapons and the characters render with their recipes instead of the
engine's default material. Build the MIs first (`import_art.py materials`).
A slot whose MI does not exist is reported and left as it is.
"""

from __future__ import annotations

from verse_pipeline import records

MESH_KINDS = {"static_mesh", "skeletal_mesh"}


def wanted_slots(record: dict) -> dict[str, str]:
    """Slot name -> MI object path of a record (slots without an MI are left out). Pure."""
    out = {}
    for slot in record.get("mesh", {}).get("material_slots", []):
        if slot.get("mi"):
            out[str(slot["slot"])] = str(slot["mi"])
    return out


def _bind_static(unreal, mesh, wanted: dict[str, str], name: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    changed = False
    materials = list(mesh.get_editor_property("static_materials"))
    for index, entry in enumerate(materials):
        slot = str(entry.get_editor_property("material_slot_name"))
        path = wanted.get(slot)
        if not path:
            continue
        mi = unreal.load_asset(path)
        if mi is None:
            errors.append(f"{name}: slot {slot}: {path} does not exist")
            continue
        if entry.get_editor_property("material_interface") != mi:
            mesh.set_material(index, mi)
            changed = True
    return changed, errors


def _bind_skeletal(unreal, mesh, wanted: dict[str, str], name: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    changed = False
    materials = list(mesh.get_editor_property("materials"))
    for entry in materials:
        slot = str(entry.get_editor_property("material_slot_name"))
        path = wanted.get(slot)
        if not path:
            continue
        mi = unreal.load_asset(path)
        if mi is None:
            errors.append(f"{name}: slot {slot}: {path} does not exist")
            continue
        if entry.get_editor_property("material_interface") != mi:
            entry.set_editor_property("material_interface", mi)
            changed = True
    if changed:
        mesh.set_editor_property("materials", materials)
    return changed, errors


def run(only: list[str], *, save: bool = True) -> dict:
    import unreal

    lib = unreal.EditorAssetLibrary
    report: dict = {"bound": [], "unchanged": [], "errors": []}
    for record in records.select(records.load_all(), only):
        wanted = wanted_slots(record)
        if record["kind"] not in MESH_KINDS or not wanted:
            continue
        name = record["name"]
        path = record["asset_path"]
        if not lib.does_asset_exist(path):
            report["errors"].append(f"{name}: {path} is not imported")
            continue
        mesh = lib.load_asset(path)
        if record["kind"] == "skeletal_mesh":
            changed, errors = _bind_skeletal(unreal, mesh, wanted, name)
        else:
            changed, errors = _bind_static(unreal, mesh, wanted, name)
        report["errors"] += errors
        if changed:
            if save:
                lib.save_loaded_asset(mesh, only_if_is_dirty=False)
            report["bound"].append(name)
        else:
            report["unchanged"].append(name)
    report["ok"] = not report["errors"]
    return report
