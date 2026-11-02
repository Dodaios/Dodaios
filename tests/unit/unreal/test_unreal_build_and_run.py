"""build.py, test.py, screenshot.py and smoke.py of scripts/unreal (G0.6).

Pure logic: the engine is a fake folder, every process call is recorded, and
the lock is a stand-in, so nothing here starts Unreal.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from scripts.unreal import _common as common
from scripts.unreal import build, screenshot, smoke, with_lock
from scripts.unreal import test as automation


@pytest.fixture
def engine(tmp_path, monkeypatch):
    root = tmp_path / "UE_5.7"
    for path in (common.build_bat(root), common.run_uat_bat(root), common.editor_cmd(root)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    monkeypatch.setenv(common.ENGINE_ENV, str(root))
    return root


def _env(engine: Path) -> dict[str, str]:
    return {common.ENGINE_ENV: str(engine)}


@pytest.fixture
def worktree(tmp_path):
    tree = tmp_path / "wt"
    project = common.project_file(tree)
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    return tree


class _Lock:
    taken: list[str] = []

    def __init__(self, label, command=None):
        self.label = label

    def __enter__(self):
        _Lock.taken.append(self.label)
        return self

    def __exit__(self, *exc):
        return None


@pytest.fixture(autouse=True)
def _reset_lock():
    _Lock.taken = []


# --- build.py ----------------------------------------------------------------


def test_the_editor_build_is_the_plan_command(engine, worktree):
    command = build.command_for("editor", engine, common.project_file(worktree))
    assert command[:4] == [str(common.build_bat(engine)), "VerseEditor", "Win64", "Development"]
    assert f"-Project={common.project_file(worktree)}" in command
    assert "-WaitMutex" in command
    assert "-NoHotReloadFromIDE" in command
    assert "-MaxParallelActions=10" in command


def test_game_and_linux_targets(engine, worktree):
    project = common.project_file(worktree)
    assert build.command_for("game", engine, project)[1:4] == ["Verse", "Win64", "Development"]
    assert build.command_for("linux", engine, project)[1:4] == ["Verse", "Linux", "Development"]


def test_builds_run_under_the_lock_one_per_target_and_stop_at_the_first_failure(
    engine, worktree, monkeypatch
):
    monkeypatch.setattr(common, "free_gb", lambda _p: 500.0)
    calls = []

    def runner(command, *, label, cwd):
        calls.append((command[1], label))
        return 1 if command[1] == "VerseEditor" else 0

    code = build.build(["editor", "game"], worktree=worktree, env=_env(engine), runner=runner)
    assert code == 1
    assert [c[0] for c in calls] == ["VerseEditor"], "the game build never started"
    assert calls[0][1].startswith("build editor")
    assert build.build(["game"], worktree=worktree, env=_env(engine), runner=runner) == 0


def test_the_linux_build_needs_the_cross_toolchain(engine, worktree, monkeypatch):
    monkeypatch.setattr(common, "free_gb", lambda _p: 500.0)
    with pytest.raises(common.UnrealScriptError, match="LINUX_MULTIARCH_ROOT"):
        build.build(["linux"], worktree=worktree, env=_env(engine), runner=lambda *a, **k: 0)


def test_a_build_refuses_to_start_below_forty_gigabytes_free(engine, worktree, monkeypatch):
    monkeypatch.setattr(common, "free_gb", lambda _p: 39.0)
    ran = []
    with pytest.raises(common.UnrealScriptError, match="40 GB"):
        build.build(["editor"], worktree=worktree, env=_env(engine),
                    runner=lambda *a, **k: ran.append(1))
    assert not ran


def test_a_build_without_an_engine_says_so(tmp_path, worktree, monkeypatch):
    monkeypatch.setenv(common.ENGINE_ENV, str(tmp_path / "nowhere"))
    with pytest.raises(common.UnrealScriptError, match="no Unreal install"):
        build.build(["editor"], worktree=worktree, runner=lambda *a, **k: 0)


def test_clean_removes_only_the_worktree_build_output(tmp_path):
    tree = tmp_path / "wt"
    project = tree / "unreal" / "Verse"
    keep = [project / "Source", project / "Content", project / "DerivedDataCache"]
    drop = [project / name for name in common.BUILD_OUTPUT_DIRS]
    drop.append(project / "Plugins" / "Thing" / "Intermediate")
    for folder in keep + drop:
        folder.mkdir(parents=True)
        (folder / "f.txt").write_text("x", encoding="utf-8")
    removed = build.clean(tree)
    assert sorted(removed) == sorted(drop)
    assert all(not p.exists() for p in drop)
    assert all(p.exists() for p in keep)


def test_clean_runs_on_its_own():
    with pytest.raises(SystemExit):
        build.main(["clean", "editor"])


# --- test.py -----------------------------------------------------------------


def test_filters_split_on_plus_and_reject_odd_characters():
    assert automation.split_filter("Verse.Combat+Verse.Contract") == [
        "Verse.Combat", "Verse.Contract"]
    for bad in ("", "+", "Verse;Quit", "Verse Combat"):
        with pytest.raises(common.UnrealScriptError):
            automation.split_filter(bad)


def test_jobs_never_exceed_four_headless_processes():
    parts = [f"Verse.M{i}" for i in range(9)]
    groups = automation.shard(parts, 8)
    assert len(groups) == 4
    assert sorted(p for g in groups for p in g) == sorted(parts)
    assert automation.shard(parts[:2], 4) == [["Verse.M0"], ["Verse.M1"]]


def test_the_headless_command_is_the_plan_command(engine, tmp_path):
    command = automation.command_for(engine, Path("P.uproject"), "Verse.Core", tmp_path,
                                     tmp_path / "run.log")
    assert command[0] == str(common.editor_cmd(engine))
    assert "-ExecCmds=Automation RunTests Verse.Core; Quit" in command
    assert "-TestExit=Automation Test Queue Empty" in command
    for flag in ("-unattended", "-nullrhi", "-nosound", "-nosplash", "-NoP4", "-stdout"):
        assert flag in command
    assert f"-ReportExportPath={tmp_path}" in command


def _report(folder: Path, tests: list[tuple[str, str]]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"tests": [{"fullTestPath": name, "state": state} for name, state in tests]}
    # Unreal writes the report with a byte-order mark.
    (folder / "index.json").write_text(json.dumps(payload), encoding="utf-8-sig")


def _result(tmp_path, code=0) -> automation.RunResult:
    return automation.RunResult("f", code, tmp_path, tmp_path / "run.log")


def test_a_clean_report_passes(tmp_path):
    _report(tmp_path, [("Verse.Core.Smoke", "Success"), ("Verse.Contract.Enum", "Success")])
    result = automation.evaluate(_result(tmp_path), ["Verse.Core", "Verse.Contract"])
    assert result.ok and result.passed == 2


@pytest.mark.parametrize(
    ("tests", "parts", "code", "log", "field"),
    [
        ([("Verse.Core.A", "Fail")], ["Verse.Core"], 0, "", "failed"),
        ([("Verse.Core.A", "NotRun")], ["Verse.Core"], 0, "", "not_run"),
        ([("Verse.Core.A", "Success")], ["Verse.Core", "Verse.Nothing"], 0, "", "unmatched"),
        ([("Verse.Core.A", "Success")], ["Verse.Core"], 0, "Ensure condition failed", "log_hits"),
        ([("Verse.Core.A", "Success")], ["Verse.Core"], 0, "Fatal error: boom", "log_hits"),
        ([("Verse.Core.A", "Success")], ["Verse.Core"], 3, "", "problems"),
    ],
)
def test_every_failure_kind_fails_the_run(tmp_path, tests, parts, code, log, field):
    _report(tmp_path, tests)
    (tmp_path / "run.log").write_text(log, encoding="utf-8")
    result = automation.evaluate(_result(tmp_path, code), parts)
    assert not result.ok
    assert getattr(result, field)


def test_a_missing_report_fails(tmp_path):
    result = automation.evaluate(_result(tmp_path), ["Verse.Core"])
    assert not result.ok and "index.json" in result.problems[0]


def test_run_tests_holds_the_lock_once_and_writes_one_report_per_job(engine, worktree):
    commands = []

    def runner(command, *, cwd, timeout):
        commands.append(command)
        report = Path(next(a for a in command if a.startswith("-ReportExportPath="))
                      .split("=", 1)[1])
        exec_cmd = next(a for a in command if a.startswith("-ExecCmds="))
        names = exec_cmd.split("RunTests ", 1)[1].split(";")[0].split("+")
        _report(report, [(f"{n}.Case", "Success") for n in names])
        return common.Completed(0)

    results = automation.run_tests("Verse.Core+Verse.Contract", jobs=2, worktree=worktree,
                                   runner=runner, lock_factory=_Lock, stamp="t")
    assert len(_Lock.taken) == 1
    assert len(commands) == 2
    assert all(r.ok for r in results)
    assert automation.summarize(results) == 0
    assert results[0].report_dir == worktree / "unreal" / "Verse" / "Saved" / "Automation" / "t-0"


# --- screenshot.py -----------------------------------------------------------


def test_screenshots_render_off_screen_without_nullrhi_into_the_proof_folder(
    engine, worktree, monkeypatch
):
    monkeypatch.setattr(common, "current_branch", lambda _w: "claude/verse-wp10-1-shots")
    commands = []

    def runner(command, *, cwd, timeout):
        commands.append(command)
        report = Path(next(a for a in command if a.startswith("-ReportExportPath="))
                      .split("=", 1)[1])
        _report(report, [("Verse.Visual.Hangar.Bay", "Success")])
        return common.Completed(0)

    results = screenshot.capture("Verse.Visual.Hangar", worktree=worktree, runner=runner,
                                 lock_factory=_Lock, stamp="s")
    command = commands[0]
    assert "-nullrhi" not in command
    for flag in ("-game", "-d3d12", "-windowed", "-ResX=1920", "-ResY=1080", "-WinX=-32000"):
        assert flag in command
    proof = worktree / "unreal" / "Verse" / "Saved" / "Harness" / "proof"
    assert results[0].report_dir == proof / "claude-verse-wp10-1-shots" / "s-0"
    assert "Screenshots" not in results[0].report_dir.parts


def test_only_visual_suites_are_captured(worktree):
    with pytest.raises(common.UnrealScriptError, match="Verse.Visual"):
        screenshot.capture("Verse.Core", worktree=worktree)


# --- smoke.py ----------------------------------------------------------------


class _Bridge:
    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _smoke_setup(worktree, tmp_path, log_text, game_code=0, package_code=0):
    fake_bridge = tmp_path / "fake_bridge.py"
    fake_bridge.write_text("", encoding="utf-8")
    exe = smoke.archive_dir(worktree) / "Windows" / "Verse.exe"
    seen: dict = {"commands": [], "bridge": _Bridge()}

    def runner(command, *, cwd, env=None, timeout=None):
        seen["commands"].append(command)
        if command[1] == "BuildCookRun":
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("", encoding="utf-8")
            return common.Completed(package_code)
        seen["token"] = env[smoke.TOKEN_ENV]
        log = Path(next(a for a in command if a.startswith("-abslog=")).split("=", 1)[1])
        log.write_text(log_text, encoding="utf-8")
        return common.Completed(game_code)

    def popen(command, cwd=None):
        seen["bridge_command"] = command
        return seen["bridge"]

    kwargs = dict(worktree=worktree, runner=runner, popen=popen, lock_factory=_Lock,
                  fake_bridge=fake_bridge)
    return seen, kwargs


ALL_STAGES = "".join(f"LogVerse: VerseSmoke: stage {s} OK\n" for s in smoke.DEFAULT_STAGES)


def test_a_full_smoke_run_passes(engine, worktree, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "free_gb", lambda _p: 500.0)
    seen, kwargs = _smoke_setup(worktree, tmp_path, ALL_STAGES)
    assert smoke.smoke(**kwargs) == []
    package, game = seen["commands"]
    assert "-iostore" in package and "-pak" in package and "-nocompileeditor" in package
    assert "-VerseSmoke=boot,hangar,arena30s" in game
    assert seen["bridge_command"][-2:] == ["--token", seen["token"]]
    assert len(seen["token"]) == 32
    assert seen["bridge"].terminated
    assert len(_Lock.taken) == 1


def test_smoke_reports_missing_stages_crashes_and_exit_codes(engine, worktree, tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(common, "free_gb", lambda _p: 500.0)
    log = "VerseSmoke: stage boot OK\nFatal error: [File:x]\n"
    _seen, kwargs = _smoke_setup(worktree, tmp_path, log, game_code=3)
    problems = smoke.smoke(nullrhi=True, **kwargs)
    assert "Verse.exe exited with 3" in problems
    assert "stage hangar not reported OK" in problems
    assert any(p.startswith("log: Fatal error") for p in problems)


def test_a_failed_package_stops_the_smoke_run(engine, worktree, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "free_gb", lambda _p: 500.0)
    seen, kwargs = _smoke_setup(worktree, tmp_path, ALL_STAGES, package_code=1)
    assert smoke.smoke(**kwargs) == ["BuildCookRun exited with 1"]
    assert len(seen["commands"]) == 1


def test_smoke_needs_the_fake_bridge(engine, worktree, tmp_path):
    with pytest.raises(common.UnrealScriptError, match="G0.11"):
        smoke.smoke(worktree=worktree, fake_bridge=tmp_path / "missing.py")


def test_the_game_command_adds_nullrhi_only_when_asked(tmp_path):
    exe, log = tmp_path / "Verse.exe", tmp_path / "log.txt"
    assert "-nullrhi" not in smoke.game_command(exe, ["boot"], log, nullrhi=False)
    assert "-nullrhi" in smoke.game_command(exe, ["boot"], log, nullrhi=True)


def test_the_real_lock_class_fits_the_factory_signature(tmp_path):
    with contextlib.ExitStack() as stack:
        lock = with_lock.MachineLock("label", "command", directory=tmp_path)
        stack.enter_context(lock)
        assert lock.holder_path.exists()
