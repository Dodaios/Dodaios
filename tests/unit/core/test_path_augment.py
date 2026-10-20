"""Tests for dodaios.core.path_augment — the GUI-PATH augmentation.

The bug class under guard: a GUI-launched process (macOS launchd, Windows tray
relaunch) starts with a minimal PATH, so every ``shutil.which``-based CLI probe
reports an installed claude/codex/gemini as missing. ``ensure_cli_paths`` must
append existing well-known install dirs — and ONLY missing ones, keeping the
user's PATH order authoritative.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from dodaios.core import path_augment


@pytest.fixture()
def fake_install_dir(tmp_path, monkeypatch):
    """A pretend CLI install dir + a candidate list pinned to it."""
    cli_dir = tmp_path / "cli-bin"
    cli_dir.mkdir()
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(
        path_augment, "candidate_dirs", lambda: [str(cli_dir), str(missing)]
    )
    return cli_dir


def test_appends_existing_dir_and_skips_missing(fake_install_dir, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    added = path_augment.ensure_cli_paths()
    assert added == [str(fake_install_dir)]
    parts = os.environ["PATH"].split(os.pathsep)
    # Existing entries keep priority — the new dir is appended, never prepended.
    assert parts[0] == "/usr/bin"
    assert str(fake_install_dir) in parts


def test_idempotent_second_call_adds_nothing(fake_install_dir, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    assert path_augment.ensure_cli_paths()
    before = os.environ["PATH"]
    assert path_augment.ensure_cli_paths() == []
    assert os.environ["PATH"] == before


def test_dir_already_on_path_is_not_duplicated(fake_install_dir, monkeypatch):
    monkeypatch.setenv("PATH", str(fake_install_dir))
    assert path_augment.ensure_cli_paths() == []
    assert os.environ["PATH"] == str(fake_install_dir)


def test_empty_path_still_works(fake_install_dir, monkeypatch):
    monkeypatch.setenv("PATH", "")
    added = path_augment.ensure_cli_paths()
    assert added == [str(fake_install_dir)]
    assert os.environ["PATH"] == str(fake_install_dir)


def test_candidates_are_platform_appropriate():
    dirs = path_augment.candidate_dirs()
    assert dirs, "candidate list must never be empty on a supported platform"
    if sys.platform == "win32":
        assert any("WinGet" in d for d in dirs)
        assert any(d.endswith("npm") for d in dirs)
        assert any(d.endswith("nodejs") for d in dirs)
        # Claude Code's native installer (install.ps1 -> ~/.local/bin) and the
        # `claude install` migration dir (~/.claude/local) — a working terminal
        # `claude` was reported "not installed" without them (2026-07-18
        # Windows test machine).
        assert any(d.endswith(os.path.join(".local", "bin")) for d in dirs)
        assert any(d.endswith(os.path.join(".claude", "local")) for d in dirs)
    else:
        assert "/usr/local/bin" in dirs
        assert "/opt/homebrew/bin" in dirs  # Apple-Silicon Homebrew
        assert any(d.endswith(os.path.join(".local", "bin")) for d in dirs)


def test_windows_candidates_cover_official_antigravity_installer(
    tmp_path, monkeypatch
):
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    dirs = path_augment._windows_candidates()

    assert str(local / "agy" / "bin") in dirs


def test_windows_candidates_find_the_installers_private_git_last(tmp_path, monkeypatch):
    """install.ps1 puts MinGit here on a machine without Git; the updater needs it."""
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    dirs = path_augment._windows_candidates()

    private_git = str(local / "Dodaios" / "tools" / "git" / "cmd")
    assert private_git in dirs
    assert dirs[-1] == private_git


def test_windows_candidates_refresh_node_installer_paths(tmp_path, monkeypatch):
    """A GUI already running during Node installation must find the runtime.

    npm puts the Codex shim in APPDATA, but that shim still invokes node.exe.
    The official machine-wide and user-scoped Node install locations therefore
    both belong in the refreshed GUI PATH.
    """
    program_files = tmp_path / "Program Files"
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    dirs = path_augment._windows_candidates()

    assert str(program_files / "nodejs") in dirs
    assert str(local / "Programs" / "nodejs") in dirs


def test_windows_candidates_keep_64_bit_node_visible_to_32_bit_process(
    tmp_path, monkeypatch
):
    program_files_x86 = tmp_path / "Program Files (x86)"
    program_files_64 = tmp_path / "Program Files"
    monkeypatch.setenv("ProgramFiles", str(program_files_x86))
    monkeypatch.setenv("ProgramFiles(x86)", str(program_files_x86))
    monkeypatch.setenv("ProgramW6432", str(program_files_64))

    dirs = path_augment._windows_candidates()

    assert str(program_files_64 / "nodejs") in dirs
    assert dirs.count(str(program_files_x86 / "nodejs")) == 1


def test_resolve_node_executable_finds_well_known_windows_install(
    tmp_path, monkeypatch
):
    program_files = tmp_path / "Program Files"
    node_exe = program_files / "nodejs" / "node.exe"
    node_exe.parent.mkdir(parents=True)
    node_exe.write_bytes(b"MZ")

    monkeypatch.setattr(path_augment, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    assert os.path.normcase(path_augment.resolve_node_executable() or "") == (
        os.path.normcase(str(node_exe))
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX candidate shape")
def test_posix_candidates_cover_the_mac_report(monkeypatch):
    """The 2026-07-18 Mac symptom: claude installed via npm/native installer,
    app blind to it. The curated list must cover both install families."""
    dirs = path_augment.candidate_dirs()
    assert any(d.endswith(os.path.join(".claude", "local")) for d in dirs)
    assert any(d.endswith(os.path.join(".npm-global", "bin")) for d in dirs)


# ---- PATH budget (BUG-233, GitHub issue #574) ------------------------------
#
# Windows cannot start ANY program from a process whose PATH no longer fits its
# search-path string: every spawn fails with WinError 8, "not enough memory".
# The app appends folders to its own PATH, so it must never be the one that
# crosses the line, and it must recover when it is started past it.


@pytest.fixture()
def path_budget(tmp_path, monkeypatch):
    """A PATH budget of about three test folders, on every OS."""
    budget = 3 * (len(str(tmp_path)) + 8)
    monkeypatch.setattr(path_augment, "_path_budget", lambda: budget)
    monkeypatch.setattr(path_augment, "_settled_overflow", None)
    return budget


def _real_dirs(tmp_path, count: int) -> list[str]:
    dirs = []
    for index in range(count):
        folder = tmp_path / f"d{index}"
        folder.mkdir()
        dirs.append(str(folder))
    return dirs


def _dirs_filling(tmp_path, budget: int) -> list[str]:
    """Real folders whose joined PATH is as long as ``budget`` allows."""
    dirs: list[str] = []
    for folder in _real_dirs(tmp_path, 40):
        if len(os.pathsep.join([*dirs, folder])) > budget:
            break
        dirs.append(folder)
    return dirs


def test_only_windows_has_a_path_budget(monkeypatch):
    monkeypatch.setattr(path_augment, "sys", SimpleNamespace(platform="win32"))
    assert path_augment._path_budget() == path_augment._WINDOWS_PATH_BUDGET
    # Room for the application directory and the system directories Windows
    # puts in front of PATH when it builds the 32,767-character search path.
    assert path_augment._WINDOWS_PATH_BUDGET <= 32_767 - 1_000
    for platform in ("linux", "darwin"):
        monkeypatch.setattr(path_augment.sys, "platform", platform)
        assert path_augment._path_budget() is None


def test_fitting_entries_come_back_untouched():
    entries = ["a", "", "a", "missing-folder"]
    assert path_augment.fit_path_entries(entries, 100) is entries


def test_repeats_and_blanks_go_before_anything_else(tmp_path):
    first, second = _real_dirs(tmp_path, 2)
    ghost = str(tmp_path / "ghost")
    entries = [first, "", second, first, ghost, second]
    budget = len(os.pathsep.join([first, second, ghost]))

    assert path_augment.fit_path_entries(entries, budget) == [first, second, ghost]


def test_missing_folders_go_before_real_ones(tmp_path):
    first, second = _real_dirs(tmp_path, 2)
    ghost = str(tmp_path / "ghost")
    budget = len(os.pathsep.join([first, second]))

    assert path_augment.fit_path_entries([first, ghost, second], budget) == [first, second]


def test_real_folders_are_given_up_from_the_end(tmp_path):
    dirs = _real_dirs(tmp_path, 4)
    budget = len(os.pathsep.join(dirs[:2]))

    assert path_augment.fit_path_entries(dirs, budget) == dirs[:2]


def test_an_oversized_path_is_repaired_and_still_gains_the_cli_dir(
    tmp_path, monkeypatch, path_budget
):
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    monkeypatch.setattr(path_augment, "candidate_dirs", lambda: [str(cli_dir)])
    (real,) = _real_dirs(tmp_path, 1)
    bloated = os.pathsep.join([real] * 40)
    assert len(bloated) > path_budget
    monkeypatch.setenv("PATH", bloated)

    assert path_augment.ensure_cli_paths() == [str(cli_dir)]
    assert os.environ["PATH"].split(os.pathsep) == [real, str(cli_dir)]


def test_an_oversized_path_is_repaired_with_nothing_to_add(
    tmp_path, monkeypatch, path_budget
):
    monkeypatch.setattr(path_augment, "candidate_dirs", lambda: [])
    (real,) = _real_dirs(tmp_path, 1)
    monkeypatch.setenv("PATH", os.pathsep.join([real] * 40))

    assert path_augment.ensure_cli_paths() == []
    assert os.environ["PATH"] == real


def test_a_cli_dir_that_does_not_fit_is_left_out(tmp_path, monkeypatch, path_budget):
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    monkeypatch.setattr(path_augment, "candidate_dirs", lambda: [str(cli_dir)])
    full = os.pathsep.join(_dirs_filling(tmp_path, path_budget))
    assert len(full) + len(os.pathsep) + len(str(cli_dir)) > path_budget
    monkeypatch.setenv("PATH", full)

    assert path_augment.ensure_cli_paths() == []
    assert os.environ["PATH"] == full


def test_a_settled_overflow_is_not_probed_again(tmp_path, monkeypatch, path_budget):
    """Status probes ask constantly; the same dead end must cost nothing twice."""
    full = os.pathsep.join(_dirs_filling(tmp_path, path_budget))
    extra = str(tmp_path / "d39")
    monkeypatch.setenv("PATH", full)

    assert path_augment._store_path(full, [extra]) == []
    fits: list[str] = []
    real_fit = path_augment.fit_path_entries
    monkeypatch.setattr(
        path_augment,
        "fit_path_entries",
        lambda entries, budget: fits.append("fit") or real_fit(entries, budget),
    )
    assert path_augment._store_path(full, [extra]) == []
    assert fits == []
    assert os.environ["PATH"] == full


def test_the_persistent_path_refresh_respects_the_budget(
    tmp_path, monkeypatch, path_budget
):
    (real,) = _real_dirs(tmp_path, 1)
    monkeypatch.setenv("PATH", real)
    registered = []
    for index in range(30):
        folder = tmp_path / f"r{index}"
        folder.mkdir()
        registered.append(str(folder))

    added = path_augment.refresh_from_persistent_path(lambda: [";".join(registered)])

    assert added == registered[: len(added)]
    assert added != registered
    assert len(os.environ["PATH"]) <= path_budget
    assert os.environ["PATH"].split(os.pathsep) == [real, *added]


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows search-path limit")
def test_a_process_past_the_windows_limit_can_spawn_again():
    """The whole failure, for real: WinError 8 first, a working spawn after."""
    import subprocess
    import textwrap

    from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

    script = textwrap.dedent(
        """
        import os, subprocess, sys
        from dodaios.core import path_augment

        base = os.environ["PATH"]
        repeat = ";" + os.path.dirname(sys.executable)
        os.environ["PATH"] = base + repeat * ((32_740 - len(base)) // len(repeat))
        argv = [sys.executable, "-c", "print('spawned')"]
        try:
            subprocess.run(argv, capture_output=True)
            print("before=ok")
        except OSError as exc:
            print(f"before={exc.winerror}")
        path_augment.ensure_cli_paths()
        after = subprocess.run(argv, capture_output=True, text=True)
        print(f"after={after.stdout.strip()} length={len(os.environ['PATH'])}")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert "before=8" in result.stdout, result.stdout + result.stderr
    assert "after=spawned" in result.stdout, result.stdout + result.stderr
