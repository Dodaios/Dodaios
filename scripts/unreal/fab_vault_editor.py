"""Editor side of `fab_migrate.py`: runs inside the Fab vault project (UnrealEditor-Cmd).

Reads `FAB_MIGRATE_ARGS` (JSON: pack, source, only, result, fixture) and:

1. moves the pack folder `/Game/<source>` to `/Game/Verse/External/<pack>` once (rename with
   reference fix-up), so the files keep working when copied into the game's own Content tree;
2. moves any other `/Game/...` package the chosen assets need (Megascans master materials,
   shared textures) to `/Game/Verse/External/_Shared/...`;
3. writes the package closure of the chosen assets (`only` names, or the whole pack) to `result`.

`fixture` builds a tiny test pack (`/Game/TestPack`: a cube mesh and its material) first; the
host's `--self-test` uses it to prove the move and the copy without a real Fab pack.
"""

from __future__ import annotations

import json
import os

import unreal

EXTERNAL = "/Game/Verse/External"


def _eal():
    return unreal.EditorAssetLibrary


def _package(object_path: str) -> str:
    return object_path.split(".", 1)[0]


def build_fixture() -> None:
    eal = _eal()
    if eal.does_directory_exist("/Game/TestPack") or eal.does_directory_exist(
        f"{EXTERNAL}/TestPack"
    ):
        return
    mat = eal.duplicate_asset(
        "/Engine/BasicShapes/BasicShapeMaterial", "/Game/TestPack/Materials/M_TestPaint"
    )
    mesh = eal.duplicate_asset("/Engine/BasicShapes/Cube", "/Game/TestPack/Meshes/SM_TestCube")
    mesh.set_material(0, mat)
    eal.save_directory("/Game/TestPack")


def is_redirector(object_path: str) -> bool:
    data = _eal().find_asset_data(object_path)
    return str(data.asset_class_path.asset_name) == "ObjectRedirector"


def move_folder(source: str, target: str) -> int:
    """Rename every asset under `source` to the same relative path under `target`."""
    eal = _eal()
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    data = []
    for object_path in eal.list_assets(source, recursive=True, include_folder=False):
        package = _package(object_path)
        rel_dir, name = package[len(source) :].rsplit("/", 1)
        asset = eal.load_asset(object_path)
        if asset is None or is_redirector(object_path):
            continue
        data.append(unreal.AssetRenameData(asset, target + rel_dir, name))
    if data and not tools.rename_assets(data):
        raise RuntimeError(f"rename of {source} failed")
    redirectors = [
        eal.load_asset(p)
        for p in eal.list_assets(source, recursive=True, include_folder=False)
        if is_redirector(p)
    ]
    if redirectors:
        tools.fixup_referencers(redirectors)
    eal.save_directory(target)
    return len(data)


def dependencies(registry, package: str) -> list[str]:
    options = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True,
        include_hard_package_references=True,
        include_searchable_names=False,
        include_soft_management_references=False,
        include_hard_management_references=False,
    )
    return [str(p) for p in (registry.get_dependencies(package, options) or [])]


def closure(registry, roots: list[str]) -> tuple[list[str], list[str]]:
    """(packages under /Game/Verse/External, other /Game packages) reachable from `roots`."""
    seen: set[str] = set()
    stack = list(roots)
    inside, outside = [], []
    while stack:
        package = stack.pop()
        if package in seen or not package.startswith("/Game/"):
            continue
        seen.add(package)
        (inside if package.startswith(EXTERNAL + "/") else outside).append(package)
        stack.extend(dependencies(registry, package))
    return sorted(inside), sorted(outside)


def main() -> None:
    args = json.loads(os.environ["FAB_MIGRATE_ARGS"])
    pack, result = args["pack"], args["result"]
    source = "/Game/" + (args.get("source") or pack)
    target = f"{EXTERNAL}/{pack}"
    eal = _eal()
    report: dict = {"ok": False, "pack": pack}
    try:
        if args.get("fixture"):
            build_fixture()
        if eal.does_directory_exist(source) and source != target:
            report["moved"] = move_folder(source, target)
        if not eal.does_directory_exist(target):
            raise RuntimeError(f"{source} not in the vault (add the pack to FabVault first)")
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = eal.list_assets(target, recursive=True, include_folder=False)
        only = set(args.get("only") or [])
        roots = [_package(p) for p in assets if not only or _package(p).rsplit("/", 1)[1] in only]
        missing = sorted(only - {r.rsplit("/", 1)[1] for r in roots})
        if missing:
            raise RuntimeError(f"not in {target}: {missing}")
        inside, outside = closure(registry, roots)
        for package in outside:  # shared dependencies follow the pack into External/_Shared
            rel_dir, name = package[len("/Game") :].rsplit("/", 1)
            asset = eal.load_asset(package)
            if asset is not None:
                unreal.AssetToolsHelpers.get_asset_tools().rename_assets(
                    [unreal.AssetRenameData(asset, f"{EXTERNAL}/_Shared{rel_dir}", name)]
                )
        if outside:
            eal.save_directory(f"{EXTERNAL}/_Shared")
            inside, outside = closure(registry, roots)
        report.update(ok=not outside, packages=inside, outside=outside, roots=sorted(roots))
    except Exception as error:  # the host must see every failure
        report["error"] = f"{type(error).__name__}: {error}"
    with open(result, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    unreal.SystemLibrary.quit_editor()


main()
