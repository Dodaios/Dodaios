"""`import_art.py assets`: import every (or the named) import record's export.

Reimports only what changed: an asset whose stored source hash equals the
record's `export.sha256` is skipped (art-pipeline 10.2, LFS quota). The hash
is kept in the asset's metadata tag `VerseExportSha256`.
"""

from __future__ import annotations

from verse_pipeline import import_meshes, records, wp14_editor

SHA_TAG = "VerseExportSha256"
SUPPORTED = {"static_mesh", "proxy_mesh", "skeletal_mesh", "texture"}
#: Kinds the importer creates together with another record's asset (art-pipeline 2).
WITH_MESH = {"skeleton"}
#: Kinds their owner's builder creates in the editor; nothing to import (art-pipeline 10.3).
EDITOR_BUILT = {"material", "material_function"}


def plan(all_records: list[dict], stored: dict[str, str]) -> list[tuple[dict, str]]:
    """(record, action): `import`, `skip`, `with_mesh`, `editor_built` or `unsupported`. Pure."""
    out = []
    for record in all_records:
        if record["kind"] in WITH_MESH:
            out.append((record, "with_mesh"))
        elif record["kind"] in EDITOR_BUILT:
            out.append((record, "editor_built"))
        elif record["kind"] not in SUPPORTED:
            out.append((record, "unsupported"))
        elif stored.get(record["asset_path"]) == record["export"]["sha256"]:
            out.append((record, "skip"))
        else:
            out.append((record, "import"))
    return out


def _stored_hashes(all_records: list[dict]) -> dict[str, str]:
    import unreal

    lib = unreal.EditorAssetLibrary
    out = {}
    for record in all_records:
        path = record["asset_path"]
        if record["kind"] in SUPPORTED and lib.does_asset_exist(path):
            asset = lib.load_asset(path)
            value = lib.get_metadata_tag(asset, SHA_TAG)
            if value:
                out[path] = str(value)
    return out


def run(only: list[str], *, save: bool = True) -> dict:
    import unreal

    selected = records.select(records.load_all(), only)
    steps = plan(selected, _stored_hashes(selected))
    report = {"imported": [], "skipped": [], "errors": []}
    used = import_meshes.use_importer()
    finish = wp14_editor("rig")
    for record, action in steps:
        name = record["name"]
        if action in ("skip", "with_mesh", "editor_built"):
            report["skipped"].append(name)
            continue
        if action == "unsupported":
            report["errors"].append(f"{name}: kind {record['kind']} has no importer yet")
            continue
        try:
            source = records.export_file(record)
            if record["kind"] == "texture":
                from verse_pipeline import import_textures

                if not hasattr(import_textures, "import_texture"):
                    raise NotImplementedError(import_textures.OWNER_NOTE)
                asset = import_textures.import_texture(record, source, save=False)
            elif record["kind"] == "skeletal_mesh":
                asset = import_meshes.import_skeletal(record, source, save=False)
            else:
                asset = import_meshes.import_static(record, source, save=False)
            if finish is not None and finish.is_wp14(record):
                report["errors"] += list(finish.finish_import(record, asset))
            unreal.EditorAssetLibrary.set_metadata_tag(asset, SHA_TAG, record["export"]["sha256"])
            if save:
                unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
                if record["kind"] == "skeletal_mesh":
                    skeleton = asset.get_editor_property("skeleton")
                    if skeleton is not None:
                        unreal.EditorAssetLibrary.save_loaded_asset(
                            skeleton, only_if_is_dirty=False
                        )
            report["imported"].append(name)
        except Exception as error:  # report every asset, then fail once
            report["errors"].append(f"{name}: {type(error).__name__}: {error}")
    report["importer"] = used
    report["ok"] = not report["errors"]
    return report
