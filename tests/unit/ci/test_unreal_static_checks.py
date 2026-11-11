"""Static checks of the Unreal Verse tree (G0.5 DAG, G0.12 hygiene)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import agent_land

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "unreal" / "Verse" / "Source"


def _load(name: str):
    path = REPO_ROOT / "scripts" / "unreal" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dag = _load("check_build_dag")


# --- Build.cs DAG -------------------------------------------------------------


def test_the_committed_module_graph_is_exactly_the_architecture_table():
    assert dag.check(SOURCE) == []


def _copy_source(tmp_path: Path) -> Path:
    target = tmp_path / "Source"
    shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns("*.cpp", "*.h"))
    return target


def test_an_edge_outside_the_table_fails(tmp_path):
    source = _copy_source(tmp_path)
    build = source / "VerseGore" / "VerseGore.Build.cs"
    build.write_text(
        build.read_text(encoding="utf-8").replace('"VerseCore"', '"VerseCore", "VerseCombat"'),
        encoding="utf-8",
    )
    assert dag.check(source) == [
        "VerseGore -> VerseCombat: edge not allowed by architecture.md section 2"
    ]


def test_a_missing_edge_fails_and_comments_never_count(tmp_path):
    source = _copy_source(tmp_path)
    build = source / "VerseCrew" / "VerseCrew.Build.cs"
    text = build.read_text(encoding="utf-8").replace(', "VerseDecks"', "")
    build.write_text(text + '\n// "VerseDecks" in a comment is no edge\n', encoding="utf-8")
    assert dag.check(source) == [
        "VerseCrew -> VerseDecks: edge listed in architecture.md section 2 is missing"
    ]


def test_an_unknown_module_and_a_missing_build_file_fail(tmp_path):
    source = _copy_source(tmp_path)
    (source / "VerseExtra").mkdir()
    (source / "VerseExtra" / "VerseExtra.Build.cs").write_text("", encoding="utf-8")
    (source / "VerseUI" / "VerseUI.Build.cs").unlink()
    problems = dag.check(source)
    assert any(p.startswith("VerseExtra: not in the architecture table") for p in problems)
    assert "VerseUI: missing VerseUI.Build.cs" in problems


def test_the_committed_engine_modules_are_exactly_the_engine_table():
    assert dag.engine_notes(SOURCE) == []
    for name in dag.ENGINE:
        build_cs = SOURCE / name / f"{name}.Build.cs"
        assert dag.engine_modules_of(build_cs) == dag.ENGINE[name], name


def test_a_dropped_engine_module_fails_and_an_extra_one_is_only_a_note(tmp_path):
    source = _copy_source(tmp_path)
    crew = source / "VerseCrew" / "VerseCrew.Build.cs"
    crew.write_text(
        crew.read_text(encoding="utf-8").replace('"Json", "NavigationSystem"', '"Json"'),
        encoding="utf-8",
    )
    stream = source / "VerseStream" / "VerseStream.Build.cs"
    stream.write_text(
        stream.read_text(encoding="utf-8").replace('"Engine" }', '"Engine", "Json" }'),
        encoding="utf-8",
    )
    assert dag.check(source) == [
        "VerseCrew: engine module NavigationSystem listed in architecture.md section 2"
        " is not linked"
    ]
    assert dag.engine_notes(source) == [
        "VerseStream links engine module Json, which the engine table does not list"
    ]


def test_a_cycle_is_reported():
    assert dag.find_cycle({"A": {"B"}, "B": {"C"}, "C": {"A"}}) == ["A", "B", "C", "A"]
    assert dag.find_cycle({"A": {"B"}, "B": set()}) == []


def test_the_server_target_is_gone_and_only_the_editor_carries_the_harness():
    targets = sorted(p.name for p in SOURCE.glob("*.Target.cs"))
    assert targets == ["Verse.Target.cs", "VerseEditor.Target.cs"]
    assert '"VerseHarness"' not in (SOURCE / "Verse.Target.cs").read_text(encoding="utf-8")
    assert '"VerseHarness"' in (SOURCE / "VerseEditor.Target.cs").read_text(encoding="utf-8")
    # A DeveloperTool module from the .uproject would still build into a Game target.
    project = json.loads((SOURCE.parent / "Verse.uproject").read_text(encoding="utf-8"))
    harness = next(m for m in project["Modules"] if m["Name"] == "VerseHarness")
    assert harness["Type"] == "DeveloperTool"
    assert harness["TargetAllowList"] == ["Editor"]


def test_every_module_ships_a_smoke_test():
    for module in dag.ALLOWED:
        tests = list((SOURCE / module / "Private" / "Tests").glob("*SmokeTest.cpp"))
        assert len(tests) == 1, module
        short = "Primary" if module == "Verse" else module.removeprefix("Verse")
        assert f'"Verse.{short}.Smoke"' in tests[0].read_text(encoding="utf-8")


# --- repo hygiene (architecture 8.4) ------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def test_unreal_binaries_go_to_lfs_and_the_tree_stays_out_of_archives():
    out = _git(
        "check-attr",
        "filter",
        "export-ignore",
        "--",
        "unreal/Verse/Content/Verse/A.uasset",
        "unreal/Verse/Content/Verse/B.umap",
    )
    assert "A.uasset: filter: lfs" in out
    assert "B.umap: filter: lfs" in out
    assert "A.uasset: export-ignore: set" in out
    nested = (REPO_ROOT / "unreal" / "Verse" / ".gitattributes").read_text(encoding="utf-8")
    for banned in (".fbx", ".wav", ".exr", ".glb"):
        assert banned not in nested
    lfsconfig = (REPO_ROOT / ".lfsconfig").read_text(encoding="utf-8")
    assert "fetchexclude = unreal/**" in lfsconfig


def test_the_nested_ignore_keeps_build_output_out_and_build_in():
    lines = (REPO_ROOT / "unreal" / "Verse" / ".gitignore").read_text(encoding="utf-8")
    for entry in ("Binaries/", "Intermediate/", "Saved/", "DerivedDataCache/", ".vs/"):
        assert entry in lines.splitlines()
    rules = [rule for rule in lines.splitlines() if rule and not rule.startswith("#")]
    # Build/ ships; only generated chunk files under it stay ignored after it.
    assert "!Build/" in rules
    assert all(rule.startswith("Build/") for rule in rules[rules.index("!Build/") + 1 :])


def test_the_pre_push_hook_uploads_lfs_objects_only_when_git_lfs_exists():
    hook = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    guard = hook.index("command -v git-lfs")
    call = hook.index('git lfs pre-push "$remote_name" "$remote_url" < "$refs_file"')
    cleanup = hook.index('rm -f "$refs_file"')
    assert guard < call < cleanup


class FakeGit:
    def __init__(self, changed: str, lfs: set[str], *, lfs_push_code: int = 0) -> None:
        self.changed, self.lfs, self.lfs_push_code = changed, lfs, lfs_push_code
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        if cmd[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(cmd, 0, self.changed, "")
        if cmd[:2] == ["git", "check-attr"]:
            paths = cmd[cmd.index("--") + 1 :]
            out = "".join(
                f"{p}\0filter\0{'lfs' if p in self.lfs else 'unspecified'}\0" for p in paths
            )
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:3] == ["git", "lfs", "push"]:
            return subprocess.CompletedProcess(cmd, self.lfs_push_code, "", "")
        return subprocess.CompletedProcess(cmd, 0, "git-lfs/3.7.1", "")


def test_land_pushes_lfs_objects_before_the_branch_when_the_diff_has_lfs_files():
    asset = "unreal/Verse/Content/A.uasset"
    git = FakeGit(f"{asset}\nscripts/x.py\n", {asset})
    assert agent_land.push_lfs_objects("origin", "claude/x", "origin/main", git) is True
    assert ["git", "lfs", "push", "origin", "claude/x"] in git.commands


def test_land_skips_lfs_without_lfs_files_and_stops_when_the_upload_fails():
    plain = FakeGit("scripts/x.py\n", set())
    assert agent_land.push_lfs_objects("origin", "claude/x", "origin/main", plain) is True
    assert all(cmd[:3] != ["git", "lfs", "push"] for cmd in plain.commands)
    failing = FakeGit("a.uasset\n", {"a.uasset"}, lfs_push_code=1)
    assert agent_land.push_lfs_objects("origin", "claude/x", "origin/main", failing) is False
