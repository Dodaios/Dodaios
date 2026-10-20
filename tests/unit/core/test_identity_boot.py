"""``dodaios.core.identity_boot``: where the data directory and config file are.

Why this file matters: the per-user data directory changed its name. An
existing installation still has every memory, skill and log under the earlier
name, and the config file is still ``jarvis.toml``. A wrong answer here is an
app that starts on an empty directory while the user's data sits next to it,
or two processes that move the same directory at once. The tests run on real
directories under ``tmp_path``.
"""

from __future__ import annotations

import ast
import functools
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from dodaios.core import branding, identity_boot, paths
from dodaios.core import config as core_config
from dodaios.core.identity_boot import (
    DirectoryPair,
    may_migrate,
    migrate_at_boot,
    migrate_data_dirs,
    resolve_config_file,
    user_data_dir_pair,
)
from dodaios.core.identity_migration import (
    DirectoryOutcome,
    create_directory_link,
    lock_file_held,
    migrate_directory,
    named_mutex_exists,
)
from dodaios.core.instance import INSTANCE_ENV_VAR

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _fresh_resolution() -> Iterator[None]:
    identity_boot.reset_resolution_cache()
    yield
    identity_boot.reset_resolution_cache()


@pytest.fixture
def local_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A per-user application data root, as on Windows."""
    root = tmp_path / "AppData" / "Local"
    root.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(root))
    monkeypatch.delenv(INSTANCE_ENV_VAR, raising=False)
    monkeypatch.delenv(identity_boot.HOOK_REPORT_ENV_VAR, raising=False)
    return root


@pytest.fixture
def legacy_dir(local_appdata: Path) -> Path:
    """An installation from before the rename, holding real data."""
    directory = local_appdata / branding.LEGACY_WINDOWS_USER_DATA_DIR_NAMES[0]
    (directory / "memory").mkdir(parents=True)
    (directory / "memory" / "notes.txt").write_text("remember this", encoding="utf-8")
    return directory


@pytest.fixture
def current_dir(local_appdata: Path) -> Path:
    return local_appdata / branding.WINDOWS_USER_DATA_DIR_NAME


@pytest.fixture
def linkable(tmp_path: Path) -> None:
    """Skip where this account cannot leave a directory link at all."""
    target = tmp_path / "link-probe-target"
    link = tmp_path / "link-probe"
    target.mkdir()
    try:
        create_directory_link(link, target)
    except OSError as exc:
        pytest.skip(f"this OS account cannot create a directory link: {exc}")
    try:
        os.unlink(link)
    except OSError:
        os.rmdir(link)


def _main_instance(argv: tuple[str, ...] = ()) -> identity_boot.MigrationDecision:
    """The decision for a source launch with no other instance running."""
    return may_migrate(
        argv, frozen=False, mutex_exists=lambda _names: False, lock_held=lambda _paths: False
    )


# ----------------------------------------------------------------------
# Resolution
# ----------------------------------------------------------------------


def test_a_fresh_install_uses_the_current_name(local_appdata: Path, current_dir: Path) -> None:
    assert paths.user_data_dir() == current_dir


def test_the_legacy_directory_wins_while_it_is_a_real_directory(
    legacy_dir: Path, current_dir: Path
) -> None:
    assert paths.user_data_dir() == legacy_dir
    # Even beside a current directory that already exists: nothing is merged,
    # and the data stays where it is.
    current_dir.mkdir()
    identity_boot.reset_resolution_cache()
    assert paths.user_data_dir() == legacy_dir
    assert paths.user_skills_dir() == legacy_dir / "skills"


def test_the_home_directory_fallback_has_its_own_earlier_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".jarvis").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert paths.user_data_dir() == home / ".jarvis"
    (home / ".jarvis").rmdir()
    identity_boot.reset_resolution_cache()
    assert paths.user_data_dir() == home / branding.FALLBACK_USER_DATA_DIR_NAME


@pytest.mark.usefixtures("linkable")
def test_a_link_left_at_the_legacy_path_resolves_to_the_current_directory(
    local_appdata: Path, current_dir: Path
) -> None:
    current_dir.mkdir()
    create_directory_link(local_appdata / "Jarvis", current_dir)
    assert paths.user_data_dir() == current_dir


def test_resolution_is_cached_per_process_until_reset(
    local_appdata: Path, current_dir: Path
) -> None:
    assert paths.user_data_dir() == current_dir
    legacy = local_appdata / "Jarvis"
    legacy.mkdir()
    # A cached answer: a later lookup costs no filesystem access at all.
    assert paths.user_data_dir() == current_dir
    identity_boot.reset_resolution_cache()
    assert paths.user_data_dir() == legacy


def test_resolving_changes_nothing_on_disk(legacy_dir: Path, local_appdata: Path) -> None:
    before = sorted(p.name for p in local_appdata.iterdir())
    paths.user_data_dir()
    paths.desktop_mirror_dir()
    assert sorted(p.name for p in local_appdata.iterdir()) == before


def test_the_desktop_mirror_keeps_a_folder_under_its_earlier_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert paths.desktop_mirror_dir() == home / "Desktop" / "Dodaios-Output"
    (home / "Desktop" / "Jarvis-Output").mkdir(parents=True)
    identity_boot.reset_resolution_cache()
    assert paths.desktop_mirror_dir() == home / "Desktop" / "Jarvis-Output"


def test_the_deliverables_folder_keeps_a_folder_under_its_earlier_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.missions.kontrollierer.deliverable import resolve_deliverables_dir

    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    if os.name == "nt":
        parent, current, legacy = home / "Downloads", "Dodaios-Outputs", "Jarvis-Outputs"
    else:
        parent, current, legacy = home, "dodaios-outputs", "jarvis-outputs"
    (parent / legacy).mkdir()
    assert resolve_deliverables_dir() == parent / legacy
    (parent / legacy).rmdir()
    identity_boot.reset_resolution_cache()
    assert resolve_deliverables_dir() == parent / current


# ----------------------------------------------------------------------
# Migration
# ----------------------------------------------------------------------


@pytest.mark.usefixtures("linkable")
def test_after_migration_both_paths_reach_the_same_files(
    legacy_dir: Path, current_dir: Path
) -> None:
    assert paths.user_data_dir() == legacy_dir

    results = migrate_data_dirs(wait_seconds=0.5)

    assert [result.outcome for result in results] == [DirectoryOutcome.MIGRATED]
    # The cache was cleared: every later lookup sees the move.
    assert paths.user_data_dir() == current_dir
    assert (current_dir / "memory" / "notes.txt").read_text(encoding="utf-8") == "remember this"
    # A process that still spells the old name writes into the same directory.
    (legacy_dir / "memory" / "from-old-spelling.txt").write_text("x", encoding="utf-8")
    assert (current_dir / "memory" / "from-old-spelling.txt").is_file()
    # And a second start has nothing left to do.
    assert [r.outcome for r in migrate_data_dirs(wait_seconds=0.5)] == [
        DirectoryOutcome.ALREADY_LINKED
    ]
    assert identity_boot.describe(migrate_data_dirs(wait_seconds=0.5)) is None


def test_a_refused_rename_keeps_the_legacy_directory_in_use(
    legacy_dir: Path, current_dir: Path
) -> None:
    def refuse(_source: Path, _target: Path) -> None:
        raise PermissionError(13, "a file is open", str(_source))

    refusing = functools.partial(migrate_directory, rename=refuse, retry_delays=())
    results = migrate_data_dirs(wait_seconds=0.5, migrate=refusing)

    assert [result.outcome for result in results] == [DirectoryOutcome.RENAME_FAILED]
    assert not current_dir.exists()
    assert paths.user_data_dir() == legacy_dir
    assert (legacy_dir / "memory" / "notes.txt").is_file()
    report = identity_boot.describe(results)
    assert report is not None and report.level == "WARNING"
    assert "rename_failed" in report.message


def test_a_migration_that_raises_never_stops_the_boot(
    legacy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(identity_boot, "may_migrate", explode)

    report = migrate_at_boot([])

    assert report is not None and report.level == "WARNING"
    assert "disk on fire" in report.message
    assert paths.user_data_dir() == legacy_dir


@pytest.mark.usefixtures("linkable")
def test_the_main_instance_migrates_at_boot(
    legacy_dir: Path, current_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(identity_boot, "may_migrate", lambda argv, **_k: _main_instance(argv))

    report = migrate_at_boot([])

    assert report is not None and report.level == "INFO"
    assert paths.user_data_dir() == current_dir


def test_an_ordinary_start_asks_nothing_and_says_nothing(
    local_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_probe(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("an install with nothing to move probes no instance")

    monkeypatch.setattr(identity_boot, "may_migrate", must_not_probe)
    assert migrate_at_boot([]) is None


# ----------------------------------------------------------------------
# Who may migrate
# ----------------------------------------------------------------------


def test_the_default_instance_with_nothing_running_may_migrate(local_appdata: Path) -> None:
    assert _main_instance()


def test_the_dev_instance_only_resolves(
    legacy_dir: Path, current_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(INSTANCE_ENV_VAR, "dev")
    decision = _main_instance()
    assert not decision and "dev" in decision.reason
    assert migrate_at_boot([]) is None
    assert legacy_dir.is_dir() and not current_dir.exists()


def test_a_no_lock_run_only_resolves(legacy_dir: Path) -> None:
    assert not _main_instance(("--headless", "--no-lock"))


def test_the_frozen_build_leaves_it_to_its_runtime_hook(local_appdata: Path) -> None:
    decision = may_migrate(
        (), frozen=True, mutex_exists=lambda _n: False, lock_held=lambda _p: False
    )
    assert not decision


def test_a_running_primary_on_windows_blocks_the_move(local_appdata: Path) -> None:
    asked: list[tuple[str, ...]] = []

    def running(names: tuple[str, ...]) -> bool:
        asked.append(tuple(names))
        return True

    assert not may_migrate((), frozen=False, platform="win32", mutex_exists=running)
    # Every instance's mutex counts: the dev app shares the data directory.
    assert asked == [identity_boot.primary_mutex_names()]
    assert branding.WINDOWS_MUTEX_NAME in asked[0]
    assert f"{branding.WINDOWS_MUTEX_NAME}_dev" in asked[0]


def test_a_held_lock_file_blocks_the_move_elsewhere(legacy_dir: Path) -> None:
    lock = legacy_dir / "instance.lock"
    lock.write_bytes(b"")
    pairs = (DirectoryPair(legacy_dir.with_name("Dodaios"), (legacy_dir,)),)
    probe = functools.partial(may_migrate, (), frozen=False, platform="linux", pairs=pairs)

    assert probe(lock_held=lock_file_held)
    holder = os.open(lock, os.O_RDWR)
    try:
        _lock(holder, hold=True)
        assert not probe(lock_held=lock_file_held)
        _lock(holder, hold=False)
    finally:
        os.close(holder)
    assert probe(lock_held=lock_file_held)


def _lock(fd: int, *, hold: bool) -> None:
    """Take or drop the lock on ``fd`` the way a running primary holds its lock file."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK if hold else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, (fcntl.LOCK_EX | fcntl.LOCK_NB) if hold else fcntl.LOCK_UN)


def test_probing_a_lock_file_never_creates_one(tmp_path: Path) -> None:
    missing = tmp_path / "Jarvis" / "instance.lock"
    assert lock_file_held([missing]) is False
    assert not missing.exists() and not missing.parent.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="named mutexes are a Windows object")
def test_the_mutex_probe_sees_a_real_mutex_and_creates_none() -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    name = f"Local\\DodaiosIdentityBootTest_{os.getpid()}"
    assert named_mutex_exists([name]) is False
    handle = kernel32.CreateMutexW(None, False, name)
    assert handle
    try:
        assert named_mutex_exists([f"{name}_other", name]) is True
    finally:
        kernel32.CloseHandle(handle)
    # The probe opened, never created: closing the only handle removed it.
    assert named_mutex_exists([name]) is False


def test_only_the_launcher_moves_the_data_directory() -> None:
    """Helpers, the CLI and every other module only resolve.

    The one caller of the migration is the desktop launcher (the frozen build
    has its runtime hook); any other caller would move the directory from a
    process that is not the primary instance.
    """
    callers: list[str] = []
    for path in (_ROOT / "dodaios").rglob("*.py"):
        relative = path.relative_to(_ROOT).as_posix()
        if relative == "dodaios/core/identity_boot.py":
            continue
        source = path.read_text(encoding="utf-8-sig")
        if "migrate_at_boot" not in source and "migrate_directory" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in {"migrate_at_boot", "migrate_data_dirs", "migrate_directory"}:
                    callers.append(relative)
    callers = sorted(set(callers) - {"dodaios/core/identity_migration.py"})
    assert callers == ["dodaios/ui/web/launcher.py"]


def test_the_launcher_migrates_before_it_opens_anything_in_the_data_directory() -> None:
    source = (_ROOT / "dodaios" / "ui" / "web" / "launcher.py").read_text(encoding="utf-8")
    body = source[source.index("def _main(") :]
    migrate = body.index("migrate_at_boot(_raw_argv)")
    assert body.index("_select_instance_early(_raw_argv)") < migrate
    for later in ("ensure_instance_data_dir(", "_install_boot_trace(_raw_argv)", "_parse_args("):
        assert migrate < body.index(later), later


# ----------------------------------------------------------------------
# The runtime hook's report
# ----------------------------------------------------------------------


def test_the_hook_report_is_logged_once_and_not_inherited(
    local_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(identity_boot.HOOK_REPORT_ENV_VAR, "INFO|Data directory migration: moved")
    report = migrate_at_boot([])
    assert report == identity_boot.BootReport("INFO", "Data directory migration: moved")
    assert identity_boot.HOOK_REPORT_ENV_VAR not in os.environ
    assert migrate_at_boot([]) is None


# ----------------------------------------------------------------------
# Paths stored under the old spelling
# ----------------------------------------------------------------------


def test_a_path_inside_the_data_directory_has_every_spelling(
    local_appdata: Path, current_dir: Path
) -> None:
    inside = current_dir / "outputs" / "run-1"
    spellings = identity_boot.data_dir_spellings(inside)
    assert spellings == (inside, local_appdata / "Jarvis" / "outputs" / "run-1")
    old = local_appdata / "Jarvis" / "outputs" / "run-1"
    assert identity_boot.data_dir_spellings(old) == (old, inside)
    assert identity_boot.data_dir_spellings(current_dir) == (current_dir, local_appdata / "Jarvis")
    outside = local_appdata / "Elsewhere" / "file"
    assert identity_boot.data_dir_spellings(outside) == (outside,)
    # A sibling whose name only starts like the data directory is outside it.
    sibling = local_appdata / "Dodaios-Other"
    assert identity_boot.data_dir_spellings(sibling) == (sibling,)


def test_an_id_derived_from_a_path_survives_the_move(
    local_appdata: Path, current_dir: Path
) -> None:
    from dodaios.agentic_ide.library import project_id_for

    old = local_appdata / "Jarvis" / "scratch"
    new = current_dir / "scratch"
    assert identity_boot.stable_data_dir_spelling(new) == old
    assert project_id_for(new) == project_id_for(old)
    assert project_id_for(local_appdata / "Elsewhere") != project_id_for(old)


# ----------------------------------------------------------------------
# The config file
# ----------------------------------------------------------------------


def test_the_legacy_config_file_wins_while_it_exists(tmp_path: Path) -> None:
    assert resolve_config_file(tmp_path) == tmp_path / "dodaios.toml"
    (tmp_path / "dodaios.toml").write_text("", encoding="utf-8")
    assert resolve_config_file(tmp_path) == tmp_path / "dodaios.toml"
    (tmp_path / "jarvis.toml").write_text("", encoding="utf-8")
    assert resolve_config_file(tmp_path) == tmp_path / "jarvis.toml"
    assert core_config.resolve_config_file is resolve_config_file


def test_a_directory_named_like_the_config_file_is_not_one(tmp_path: Path) -> None:
    (tmp_path / "jarvis.toml").mkdir()
    assert resolve_config_file(tmp_path) == tmp_path / "dodaios.toml"


def test_the_config_module_reads_the_resolved_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JARVIS_CONFIG", raising=False)
    assert core_config.DEFAULT_CONFIG_FILE == resolve_config_file(core_config.PROJECT_ROOT)
    assert core_config.resolve_config_path() == core_config.DEFAULT_CONFIG_FILE


def test_the_writer_writes_to_jarvis_toml_when_only_it_exists(tmp_path: Path) -> None:
    from dodaios.core import config_writer

    legacy = tmp_path / "jarvis.toml"
    legacy.write_text('# my settings\n[ui]\ntheme = "light"\n', encoding="utf-8")

    config_writer.set_ui_theme("dark", path=resolve_config_file(tmp_path))

    text = legacy.read_text(encoding="utf-8")
    assert 'theme = "dark"' in text and "# my settings" in text
    assert not (tmp_path / "dodaios.toml").exists()


def test_a_fresh_install_writes_dodaios_toml(tmp_path: Path) -> None:
    from dodaios.core import config_writer

    config_writer.set_ui_theme("dark", path=resolve_config_file(tmp_path))

    assert 'theme = "dark"' in (tmp_path / "dodaios.toml").read_text(encoding="utf-8")
    assert not (tmp_path / "jarvis.toml").exists()


def test_every_config_name_is_listed_legacy_first() -> None:
    assert identity_boot.config_file_names() == ("jarvis.toml", "dodaios.toml")


def test_the_data_directory_pair_follows_branding(local_appdata: Path) -> None:
    pair = user_data_dir_pair()
    assert pair.current == local_appdata / branding.WINDOWS_USER_DATA_DIR_NAME
    assert pair.legacy == tuple(
        local_appdata / name for name in branding.LEGACY_WINDOWS_USER_DATA_DIR_NAMES
    )
