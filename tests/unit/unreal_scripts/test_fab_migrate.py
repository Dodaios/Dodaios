"""scripts/unreal/fab_migrate.py: Fab vault packages into the git-ignored External folder."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "unreal"))

import fab_migrate  # noqa: E402


def _package(content: Path, rel: str, suffixes=(".uasset", ".uexp")) -> None:
    for suffix in suffixes:
        path = content / (rel + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def test_copy_packages_keeps_paths_and_companion_files(tmp_path):
    vault = tmp_path / "vault" / "Content"
    _package(vault, "Verse/External/Pack/Meshes/SM_A")
    _package(vault, "Verse/External/_Shared/Materials/M_B", (".uasset",))
    target = tmp_path / "wt"
    count = fab_migrate.copy_packages(
        vault,
        ["/Game/Verse/External/Pack/Meshes/SM_A", "/Game/Verse/External/_Shared/Materials/M_B"],
        target,
    )
    assert count == 3
    content = target / "unreal" / "Verse" / "Content" / "Verse" / "External"
    assert (content / "Pack" / "Meshes" / "SM_A.uexp").is_file()
    assert (content / "_Shared" / "Materials" / "M_B.uasset").is_file()


def test_copy_packages_refuses_anything_outside_external(tmp_path):
    with pytest.raises(ValueError):
        fab_migrate.copy_packages(tmp_path, ["/Game/Verse/Kit/Props/SM_A"], tmp_path / "wt")


def test_external_folders_are_git_ignored():
    for path in (
        "unreal/Verse/Content/Verse/External/Pack/SM_A.uasset",
        "unreal/Verse/Art/External/a.fbx",
        "art/verse/External/a.png",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=REPO, check=False, capture_output=True
        )
        assert result.returncode == 0, path


def test_external_swaps_file_names_only_external_meshes():
    doc = json.loads((REPO / "unreal/Verse/Data/arena/external_swaps.json").read_text("utf-8"))
    assert doc["schema"] == "verse.external_swaps/1"
    for kit, entry in doc["swaps"].items():
        assert kit.startswith("SM_"), kit
        assert entry["mesh"].startswith("/Game/Verse/External/"), kit
