#!/usr/bin/env python3
"""Pull Fab / Megascans assets from the Fab vault into a worktree's git-ignored External folder.

The vault is a separate, empty UE 5.7 project outside every git tree
(`C:/demo/fab-vault/FabVault.uproject`); the user adds Fab packs to it from the Epic launcher
("Add to Project"). Their licence forbids public redistribution, so they never enter the repo:
this script copies the chosen packages into `unreal/Verse/Content/Verse/External/` of each
target checkout (git-ignored; packaged builds cook it, as `/Game/Verse` is always cooked).

    python scripts/unreal/fab_migrate.py --pack Warehouse --only SM_Barrel_A,SM_Pallet_B \\
        --target C:/demo/wt/hangar-aaa --target C:/demo/play
    python scripts/unreal/fab_migrate.py --pack Warehouse --source Megascans/Warehouse ...
    python scripts/unreal/fab_migrate.py --self-test --target <worktree>

1. The vault editor (headless, under the machine lock) moves `/Game/<source>` to
   `/Game/Verse/External/<pack>` once, with reference fix-up, and moves shared dependencies
   (Megascans master materials) to `/Game/Verse/External/_Shared/` (`fab_vault_editor.py`).
2. It reports the package closure of the chosen assets (`--only` names, or the whole pack).
3. This script copies those packages' files (`.uasset`, `.umap`, `.uexp`, `.ubulk`, `.uptnl`)
   into every `--target`. Re-running is safe: files are overwritten in place.

The game uses an External mesh only where `unreal/Verse/Data/arena/external_swaps.json` names it
and the mesh loads; a checkout without External content (CI, other clones) keeps the CC0 props.
Write one provenance row per pack in `art/verse/LICENSES.md` (licence name and Fab URL).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_VAULT = Path("C:/demo/fab-vault/FabVault.uproject")
ENGINE = Path(os.environ.get("DODAIOS_UE_ROOT", "C:/Program Files/Epic Games/UE_5.7"))
EDITOR_CMD = ENGINE / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
EDITOR_SIDE = HERE / "fab_vault_editor.py"
SUFFIXES = (".uasset", ".umap", ".uexp", ".ubulk", ".uptnl")
EXTERNAL_PREFIX = "/Game/Verse/External/"
TIMEOUT_S = 3600


def package_files(content: Path, package: str) -> list[Path]:
    """Files of one `/Game/...` package under a project's Content folder."""
    base = content / package[len("/Game/") :]
    return [base.with_suffix(s) for s in SUFFIXES if base.with_suffix(s).is_file()]


def copy_packages(vault_content: Path, packages: list[str], target_root: Path) -> int:
    """Copy each package's files to `<target>/unreal/Verse/Content/...`; returns the file count."""
    content = target_root / "unreal" / "Verse" / "Content"
    copied = 0
    for package in packages:
        if not package.startswith(EXTERNAL_PREFIX):
            raise ValueError(f"{package} is outside {EXTERNAL_PREFIX}; refusing to copy it")
        for source in package_files(vault_content, package):
            destination = content / source.relative_to(vault_content)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied += 1
    return copied


def run_vault(vault: Path, args: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        result = Path(tmp) / "result.json"
        env = dict(os.environ, FAB_MIGRATE_ARGS=json.dumps({**args, "result": str(result)}))
        command = [
            sys.executable,
            str(HERE / "with_lock.py"),
            "--label",
            f"fab migrate {args['pack']}",
            "--",
            str(EDITOR_CMD),
            str(vault),
            f"-ExecutePythonScript={EDITOR_SIDE}",
            "-unattended",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-NoP4",
        ]
        subprocess.run(command, env=env, timeout=TIMEOUT_S, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        if not result.is_file():
            return {"ok": False, "error": "the vault editor wrote no result"}
        return json.loads(result.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", help="folder name under /Game/Verse/External/")
    parser.add_argument("--source", default="", help="pack folder in the vault (default: --pack)")
    parser.add_argument("--only", default="", help="comma-separated asset names (default: all)")
    parser.add_argument("--target", action="append", default=[], help="checkout root(s)")
    parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    parser.add_argument("--self-test", action="store_true", help="migrate a built test pack")
    options = parser.parse_args(argv)
    if options.self_test:
        options.pack, options.source = "TestPack", "TestPack"
    if not options.pack:
        parser.error("--pack is required")
    targets = [Path(t) for t in options.target] or [REPO]
    vault = Path(options.vault)
    if not vault.is_file():
        print(f"[fab] no vault at {vault}", file=sys.stderr)
        return 1
    report = run_vault(
        vault,
        {
            "pack": options.pack,
            "source": options.source,
            "only": [s for s in options.only.split(",") if s],
            "fixture": options.self_test,
        },
    )
    if not report.get("ok"):
        print(f"[fab] vault step failed: {report.get('error') or report}", file=sys.stderr)
        return 1
    vault_content = vault.parent / "Content"
    for target in targets:
        count = copy_packages(vault_content, report["packages"], target)
        print(
            f"[fab] {options.pack}: {len(report['packages'])} packages, {count} files -> {target}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
