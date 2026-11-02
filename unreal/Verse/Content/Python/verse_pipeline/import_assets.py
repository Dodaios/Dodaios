"""`import_art.py assets`: import every (or the named) import record's export.

Reimports only what changed: an asset whose stored source hash equals the
record's `export.sha256` is skipped (art-pipeline 10.2, LFS quota). The hash
is kept in the asset's metadata tag `VerseExportSha256`.
"""

from __future__ import annotations

from verse_pipeline import import_meshes, records

SHA_TAG = "VerseExportSha256"
SUPPORTED = {"static_mesh", "proxy_mesh", "skeletal_mesh"}


def plan(all_records: list[dict], stored: dict[str, str]) -> list[tuple[dict, str]]:
    """(record, action) with action `import`, `skip` or `unsupported`. Pure."""
    out = []
    for record in all_records:
        if record["kind"] not in SUPPORTED:
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
        if action == "skip":
            report["skipped"].append(name)
            continue
        if action == "unsupported":
            report["errors"].append(f"{name}: kind {record['kind']} has no importer yet")
            continue
        try:
            fbx = records.export_file(record)
            if record["kind"] == "skeletal_mesh":
                asset = import_meshes.import_skeletal(record, fbx, save=False)
            else:
                asset = import_meshes.import_static(record, fbx, save=False)
            unreal.EditorAssetLibrary.set_metadata_tag(asset, SHA_TAG, record["export"]["sha256"])
            if save:
                unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
            report["imported"].append(name)
        except Exception as error:  # report every asset, then fail once
            report["errors"].append(f"{name}: {type(error).__name__}: {error}")
    report["importer"] = used
    report["ok"] = not report["errors"]
    return report
