"""``packaging/pyinstaller_rthook_frozen.py`` — the frozen path redirection.

Why this file matters: the hook is what stops a natively installed app from
keeping the user's ``jarvis.toml`` and whole data tree inside its own program
directory, where an upgrade would overwrite the settings and an uninstall would
delete the memory. It cannot import ``jarvis`` (a runtime-hook exception kills a
windowed process before any logging exists), so it re-states the app-directory
convention — and the first test below is what stops that copy from drifting.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from dodaios.core.paths import user_data_dir

HOOK_PATH = Path(__file__).resolve().parents[3] / "packaging" / "pyinstaller_rthook_frozen.py"

# The hook moves DODAIOS_ variables to their JARVIS_ names on the real environment.
pytestmark = pytest.mark.usefixtures("prefixed_environment_restored")


def _load_hook() -> ModuleType:
    """Import the hook as a module. Its top-level ``_apply()`` is a no-op here.

    The hook returns immediately when ``sys.frozen`` is absent, which it is
    under pytest, so importing it has no side effects.
    """
    spec = importlib.util.spec_from_file_location("jarvis_rthook_frozen", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook() -> ModuleType:
    return _load_hook()


@pytest.fixture
def frozen_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Pretend to be a PyInstaller bundle with a per-user app directory."""
    meipass = tmp_path / "bundle" / "_internal"
    meipass.mkdir(parents=True)
    home = tmp_path / "AppData" / "Local"
    home.mkdir(parents=True)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.delenv("JARVIS_CONFIG", raising=False)
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)
    monkeypatch.delenv("JARVIS_INSTANCE", raising=False)
    # Not the desktop app's executable: these tests are about the paths, and a
    # helper process never moves a directory.
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bundle" / "helper"))
    return meipass, home / "Dodaios"


def test_hook_directory_matches_jarvis_core_paths(
    hook: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The hook duplicates the convention on purpose; this is the gate that keeps
    # the duplicate honest. If dodaios.core.paths ever moves the app directory,
    # this fails instead of the frozen app quietly writing to the old place.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert hook._user_data_dir() == user_data_dir()

    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert hook._user_data_dir() == user_data_dir()


def test_apply_points_config_and_data_at_the_user_directory(
    hook: ModuleType, frozen_bundle: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    meipass, home = frozen_bundle
    (meipass / "jarvis.toml").write_text("[app]\nname = 'bundled'\n", encoding="utf-8")

    hook._apply()

    import os

    # A fresh install writes its config under the current name.
    assert Path(os.environ["JARVIS_CONFIG"]) == home / "dodaios.toml"
    assert Path(os.environ["JARVIS_DATA_DIR"]) == home / "data"
    # First run seeds the config from the copy inside the bundle, so the app
    # starts on the shipped defaults instead of an empty file.
    assert (home / "dodaios.toml").read_text(encoding="utf-8") == ("[app]\nname = 'bundled'\n")
    assert not (home / "jarvis.toml").exists()


def test_apply_never_overwrites_an_existing_user_config(
    hook: ModuleType, frozen_bundle: tuple[Path, Path]
) -> None:
    meipass, home = frozen_bundle
    (meipass / "jarvis.toml").write_text("bundled\n", encoding="utf-8")
    home.mkdir(parents=True)
    (home / "jarvis.toml").write_text("the user's own settings\n", encoding="utf-8")

    hook._apply()

    import os

    # This is the whole point: an in-place upgrade reinstalls the bundled file
    # and must not touch what the user configured. The file under its earlier
    # name stays the configuration; nothing is renamed or seeded beside it.
    assert (home / "jarvis.toml").read_text(encoding="utf-8") == ("the user's own settings\n")
    assert Path(os.environ["JARVIS_CONFIG"]) == home / "jarvis.toml"
    assert not (home / "dodaios.toml").exists()


def test_apply_respects_an_explicit_override(
    hook: ModuleType, frozen_bundle: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    meipass, home = frozen_bundle
    (meipass / "jarvis.toml").write_text("bundled\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", "D:/scratch/jarvis.toml")
    monkeypatch.setenv("JARVIS_DATA_DIR", "D:/scratch/data")

    hook._apply()

    import os

    assert os.environ["JARVIS_CONFIG"] == "D:/scratch/jarvis.toml"
    assert os.environ["JARVIS_DATA_DIR"] == "D:/scratch/data"
    # No seeding happens for an overridden path.
    assert not (home / "jarvis.toml").exists()


def test_apply_does_nothing_outside_a_frozen_bundle(
    hook: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.delenv("JARVIS_CONFIG", raising=False)
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)

    hook._apply()

    import os

    # A dev checkout keeps resolving its own paths; the hook is inert there.
    assert "JARVIS_CONFIG" not in os.environ
    assert "JARVIS_DATA_DIR" not in os.environ


def test_apply_still_sets_the_path_when_seeding_fails(
    hook: ModuleType, frozen_bundle: tuple[Path, Path]
) -> None:
    meipass, home = frozen_bundle
    # No jarvis.toml inside the bundle: nothing to copy, but the app must still
    # be pointed at the writable location (config_writer creates the file).
    hook._apply()

    import os

    assert Path(os.environ["JARVIS_CONFIG"]) == home / "dodaios.toml"
    assert not (home / "dodaios.toml").exists()


# ---------------------------------------------------------------------------
# The data directory under its earlier name
# ---------------------------------------------------------------------------


@pytest.fixture
def legacy_home(frozen_bundle: tuple[Path, Path]) -> Path:
    """An installation from before the rename: data and jarvis.toml under the old name."""
    _meipass, home = frozen_bundle
    legacy = home.with_name("Jarvis")
    (legacy / "data").mkdir(parents=True)
    (legacy / "data" / "memory.db").write_bytes(b"memories")
    (legacy / "jarvis.toml").write_text("the user's own settings\n", encoding="utf-8")
    return legacy


@pytest.fixture(params=["DodaiosApp.exe", "PersonalJarvis.exe"])
def desktop_app(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook: ModuleType,
    frozen_bundle: tuple[Path, Path],
) -> ModuleType:
    """Run the hook as the desktop app's executable, with no other instance running.

    Under its current name and its earlier one: the bundle ships both, and a
    pinned taskbar button or a logon task of an earlier release starts the
    earlier file.
    """
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bundle" / request.param))
    monkeypatch.setattr(sys, "argv", [sys.executable])
    # A name no live app holds: the real one may be running on this machine.
    monkeypatch.setattr(hook, "_MUTEX_NAMES", (f"Local\\HookTestNoSuchMutex_{os.getpid()}",))
    monkeypatch.delenv(hook._REPORT_ENV_VAR, raising=False)
    return hook


def _can_link(tmp_path: Path) -> bool:
    target = tmp_path / "probe-target"
    target.mkdir()
    engine = _load_hook()._load_engine()
    try:
        engine.create_directory_link(tmp_path / "probe-link", target)
    except OSError:
        return False
    return True


def test_a_helper_resolves_the_legacy_directory_and_moves_nothing(
    hook: ModuleType, frozen_bundle: tuple[Path, Path], legacy_home: Path
) -> None:
    _meipass, home = frozen_bundle

    hook._apply()

    assert Path(os.environ["JARVIS_DATA_DIR"]) == legacy_home / "data"
    assert Path(os.environ["JARVIS_CONFIG"]) == legacy_home / "jarvis.toml"
    assert not home.exists()


def test_the_desktop_app_moves_the_legacy_directory_and_keeps_jarvis_toml(
    desktop_app: ModuleType, frozen_bundle: tuple[Path, Path], legacy_home: Path, tmp_path: Path
) -> None:
    if not _can_link(tmp_path):
        pytest.skip("this OS account cannot create a directory link")
    _meipass, home = frozen_bundle

    desktop_app._apply()

    assert Path(os.environ["JARVIS_DATA_DIR"]) == home / "data"
    # The config file moved with its directory and kept its name.
    assert Path(os.environ["JARVIS_CONFIG"]) == home / "jarvis.toml"
    assert (home / "jarvis.toml").read_text(encoding="utf-8") == "the user's own settings\n"
    assert not (home / "dodaios.toml").exists()
    # The old path still reaches the same files.
    assert (legacy_home / "data" / "memory.db").read_bytes() == b"memories"
    assert os.environ[desktop_app._REPORT_ENV_VAR].startswith("INFO|Data directory migration")


def test_a_dev_instance_of_the_desktop_app_only_resolves(
    desktop_app: ModuleType,
    frozen_bundle: tuple[Path, Path],
    legacy_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _meipass, home = frozen_bundle
    monkeypatch.setenv("JARVIS_INSTANCE", "dev")

    desktop_app._apply()

    assert Path(os.environ["JARVIS_DATA_DIR"]) == legacy_home / "data"
    assert not home.exists()


def test_a_running_primary_keeps_the_desktop_app_from_moving_it(
    desktop_app: ModuleType,
    frozen_bundle: tuple[Path, Path],
    legacy_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _meipass, home = frozen_bundle
    engine = desktop_app._load_engine()
    monkeypatch.setattr(engine, "named_mutex_exists", lambda _names: True)
    monkeypatch.setattr(engine, "lock_file_held", lambda _paths: True)
    monkeypatch.setattr(desktop_app, "_load_engine", lambda: engine)

    desktop_app._apply()

    assert Path(os.environ["JARVIS_DATA_DIR"]) == legacy_home / "data"
    assert not home.exists()


def test_values_an_earlier_process_exported_follow_the_move(
    desktop_app: ModuleType,
    frozen_bundle: tuple[Path, Path],
    legacy_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if not _can_link(tmp_path):
        pytest.skip("this OS account cannot create a directory link")
    _meipass, home = frozen_bundle
    # What the hook of the version before exported, inherited by a restart.
    monkeypatch.setenv("JARVIS_DATA_DIR", str(legacy_home / "data"))
    monkeypatch.setenv("JARVIS_CONFIG", str(legacy_home / "jarvis.toml"))

    desktop_app._apply()

    assert Path(os.environ["JARVIS_DATA_DIR"]) == home / "data"
    assert Path(os.environ["JARVIS_CONFIG"]) == home / "jarvis.toml"


def test_without_the_engine_the_legacy_directory_still_wins(
    hook: ModuleType,
    frozen_bundle: tuple[Path, Path],
    legacy_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _meipass, home = frozen_bundle
    monkeypatch.setattr(hook, "_load_engine", lambda: None)

    hook._apply()

    assert Path(os.environ["JARVIS_DATA_DIR"]) == legacy_home / "data"
    assert not home.exists()
    assert hook._user_data_dir() == legacy_home
