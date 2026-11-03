"""`import_art.py assets`: import every (or the named) import record's export.

Reimports only what changed: an asset whose stored source hash equals the
record's `export.sha256` is skipped (art-pipeline 10.2, LFS quota). The hash
is kept in the asset's metadata tag `VerseExportSha256`.
"""

from __future__ import annotations

from verse_pipeline import art_on_path, import_meshes, records

art_on_path()
from weapons.editor import rig as weapons  # noqa: E402  (WP14 import finish)

SHA_TAG = "VerseExportSha256"
SUPPORTED = {"static_mesh", "proxy_mesh", "skeletal_mesh", "texture"}
#: Kinds the importer creates together with another record's asset.
WITH_MESH = {"skeleton"}


def plan(all_records: list[dict], stored: dict[str, str]) -> list[tuple[dict, str]]:
    """(record, action) with action `import`, `skip` or `unsupported`. Pure."""
    out = []
    for record in all_records:
        if record["kind"] in WITH_MESH:
            out.append((record, "with_mesh"))
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
        if lib.does_asset_exist(path):
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
    for record, action in steps:
        name = record["name"]
        if action in ("skip", "with_mesh"):
            report["skipped"].append(name)
            continue
        if action == "unsupported":
            report["errors"].append(f"{name}: kind {record['kind']} has no importer yet")
            continue
        try:
            fbx = records.export_file(record)
            if record["kind"] == "texture":
                from verse_pipeline import import_textures

                asset = import_textures.import_texture(record, fbx, save=False)
            elif record["kind"] == "skeletal_mesh":
                asset = import_meshes.import_skeletal(record, fbx, save=False)
            else:
                asset = import_meshes.import_static(record, fbx, save=False)
            if weapons.is_wp14(record):
                for line in weapons.finish_import(record, asset):
                    report["errors"].append(line)
            unreal.EditorAssetLibrary.set_metadata_tag(asset, SHA_TAG, record["export"]["sha256"])
            if save:
                unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
                if record["kind"] == "skeletal_mesh":
                    skel = asset.get_editor_property("skeleton")
                    if skel is not None:
                        unreal.EditorAssetLibrary.save_loaded_asset(skel, only_if_is_dirty=False)
            report["imported"].append(name)
        except Exception as error:  # report every asset, then fail once
            report["errors"].append(f"{name}: {type(error).__name__}: {error}")
    report["importer"] = used
    report["ok"] = not report["errors"]
    return report
