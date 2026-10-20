"""PyInstaller runtime hook: keep a frozen install out of its own program files.

Why this exists
---------------
``dodaios.core.config`` derives ``PROJECT_ROOT`` from ``dodaios/core/config.py``'s
own location. Inside a PyInstaller ``onedir`` bundle that resolves to the
bundled-resources root (``sys._MEIPASS`` = ``<install dir>/_internal``), so
without this hook a natively installed app would keep its ``jarvis.toml`` and
its whole ``data/`` tree INSIDE the installed program directory. Two things
break there:

* an in-place upgrade reinstalls ``_internal/jarvis.toml`` and silently
  discards every setting the user made, and
* an uninstall that removes the program directory takes the user's memory,
  skills and logs with it.

A runtime hook runs before the frozen entry script imports anything from
``jarvis``, which is the only moment where the import-time path constants in
``dodaios.core.config`` can still be steered. It points the two documented
override variables at the per-user application directory and seeds a first-run
``jarvis.toml`` from the copy inside the bundle.

An explicitly exported ``JARVIS_CONFIG`` / ``JARVIS_DATA_DIR`` always wins, so a
maintainer can still run a frozen build against a scratch directory. So does
``DODAIOS_CONFIG`` / ``DODAIOS_DATA_DIR``: a variable written under the
``DODAIOS_`` prefix is moved to its ``JARVIS_`` name first, by the hook's own
copy of ``dodaios.core.env_prefix._adopt`` (``tests/unit/core/test_env_prefix.py``
holds the copy identical).

The per-user directory had an earlier name (``%LOCALAPPDATA%\\Jarvis``,
``~/.jarvis``). While a real directory stands under that name it stays in use.
The desktop app itself (the GUI executable, default instance, no other
instance running) first moves it to the current name with one rename and
leaves a junction or symlink behind. The engine that does it,
``dodaios/core/identity_migration.py``, is shipped by ``dodaios.spec`` as a plain
file so this hook can load it by path. Helpers and the console CLI only
resolve. When the engine cannot be loaded, the hook resolves with an inline
copy of the rule and moves nothing. The config file is never renamed: an
existing ``jarvis.toml`` stays the configuration, a new install gets
``dodaios.toml``.

Standard library only, and no ``jarvis`` import: a failure in a runtime hook
kills a windowed process before any logging exists. ``tests/unit/packaging/
test_frozen_runtime_hook.py`` pins the directory convention below to
``dodaios.core.paths.user_data_dir`` so the duplication cannot drift.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Mirror dodaios.core.branding (tests/unit/core/test_identity_single_source.py).
_WINDOWS_USER_DATA_DIR_NAME = "Dodaios"
_LEGACY_WINDOWS_USER_DATA_DIR_NAMES = ("Jarvis",)
_FALLBACK_USER_DATA_DIR_NAME = ".dodaios-data"
_LEGACY_FALLBACK_USER_DATA_DIR_NAMES = (".jarvis",)
_CONFIG_FILE_NAME = "dodaios.toml"
_LEGACY_CONFIG_FILE_NAMES = ("jarvis.toml",)
# The executables that are the desktop app itself (dodaios.spec GUI_EXE_NAME and
# LEGACY_GUI_EXE_NAMES). Only one of them migrates the data directory.
_GUI_EXE_NAMES = ("DodaiosApp", "PersonalJarvis")
# Single-instance mutexes of a running desktop app, every instance and every
# name (dodaios.core.identity_boot.primary_mutex_names).
_MUTEX_NAMES = (
    "Global\\Dodaios_v1",
    "Global\\Dodaios_v1_dev",
    "Global\\PersonalJarvis_v1",
    "Global\\PersonalJarvis_v1_dev",
)
# Lock files a running primary holds in the data directory
# (dodaios.core.identity_boot.PRIMARY_LOCK_FILES).
_PRIMARY_LOCK_FILES = ("instance.lock", os.path.join("data", "jarvis.lock"))
# The name the bundle ships its default configuration under (dodaios.spec).
_BUNDLED_CONFIG_FILE_NAME = "jarvis.toml"
# Where dodaios.spec puts the migration engine inside the bundle.
_ENGINE_PATH = ("dodaios", "core", "identity_migration.py")
_MIGRATION_WAIT_SECONDS = 2.0
# Carries the hook's one-line migration report to the launcher, which logs it
# once a log sink exists (dodaios.core.identity_boot.HOOK_REPORT_ENV_VAR).
_REPORT_ENV_VAR = "JARVIS_IDENTITY_MIGRATION_REPORT"
# Outcomes of dodaios.core.identity_migration.DirectoryOutcome, by value.
_QUIET_OUTCOMES = ("nothing_to_migrate", "already_linked")
_MOVED_OUTCOMES = ("migrated", "link_restored")
# Mirrors dodaios.core.env_prefix: the prefixes and the adoption itself.
_PREFIXES = (("DODAIOS_", "JARVIS_"), ("DODAIOSCTL_", "JARVISCTL_"))


def _adopt(environ):
    """Move every new-prefix variable to the name the code reads; return the clashing names."""
    clashes = []
    for name in list(environ):
        for new_prefix, old_prefix in _PREFIXES:
            if not name.startswith(new_prefix) or name == new_prefix:
                continue
            value = environ.pop(name)
            old_name = old_prefix + name[len(new_prefix) :]
            if value:
                if environ.get(old_name) not in (None, "", value):
                    clashes.append(name)
                environ[old_name] = value
            elif old_name not in environ:
                environ[old_name] = value
            break
    return clashes


def _load_engine():
    """The migration engine, loaded by file path; ``None`` when it cannot be loaded."""
    import importlib.util

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass).joinpath(*_ENGINE_PATH))
    # A checkout, where packaging/ sits beside dodaios/.
    candidates.append(Path(__file__).resolve().parent.parent.joinpath(*_ENGINE_PATH))
    name = "_dodaios_frozen_identity_migration"
    for path in candidates:
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - any failure falls back to the inline rule
            sys.modules.pop(name, None)
            _warn(f"could not load the migration engine from {path}: {exc}")
            continue
        return module
    return None


def _user_data_dir_pair():
    """``(current, legacy paths)`` of the per-user directory, as in dodaios.core.identity_boot."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        parent = Path(base)
        name, legacy = _WINDOWS_USER_DATA_DIR_NAME, _LEGACY_WINDOWS_USER_DATA_DIR_NAMES
    else:
        parent = Path.home()
        name, legacy = _FALLBACK_USER_DATA_DIR_NAME, _LEGACY_FALLBACK_USER_DATA_DIR_NAMES
    return parent / name, tuple(parent / old for old in legacy)


def _legacy_wins(legacy: Path, current: Path) -> bool:
    """The engine's rule without the engine: a legacy real directory stays in use."""
    import stat

    try:
        metadata = os.lstat(legacy)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        # Cannot be inspected: never taken for absent.
        return True
    reparse = getattr(metadata, "st_file_attributes", 0) & 0x400
    is_link = stat.S_ISLNK(metadata.st_mode) or bool(
        reparse and getattr(metadata, "st_reparse_tag", 0) in (0xA0000003, 0xA000000C)
    )
    if not is_link:
        return stat.S_ISDIR(metadata.st_mode)
    if not os.path.isdir(legacy):
        return False
    try:
        return not os.path.samefile(legacy, current)
    except OSError:
        # The current directory does not exist, so the link leads elsewhere.
        return True


def _resolve_home(engine) -> Path:
    current, legacy = _user_data_dir_pair()
    if engine is not None:
        try:
            return Path(engine.resolve_directory(current, legacy))
        except Exception as exc:  # noqa: BLE001 - falls back to the inline rule
            _warn(f"could not resolve the data directory with the engine: {exc}")
    for old in legacy:
        if _legacy_wins(old, current):
            return old
    return current


def _user_data_dir() -> Path:
    """``%LOCALAPPDATA%\\Dodaios`` on Windows, ``~/.dodaios-data`` everywhere else.

    The directory under its earlier name while that is still a real directory.
    """
    return _resolve_home(_load_engine())


def _resolve_config_file(home: Path) -> Path:
    """A legacy-named config file while it exists, else the current name. Never renamed."""
    for legacy in _LEGACY_CONFIG_FILE_NAMES:
        candidate = home / legacy
        if candidate.is_file():
            return candidate
    return home / _CONFIG_FILE_NAME


def _is_main_instance(engine, legacy_dirs) -> bool:
    """The desktop app, default instance, locked, and no other instance running."""
    executable = Path(sys.executable).stem.casefold()
    if executable not in {name.casefold() for name in _GUI_EXE_NAMES}:
        return False
    if (os.environ.get("JARVIS_INSTANCE") or "").strip().lower() not in ("", "default"):
        return False
    if "--no-lock" in sys.argv[1:]:
        return False
    if sys.platform == "win32":
        return not engine.named_mutex_exists(_MUTEX_NAMES)
    locks = [old / name for old in legacy_dirs for name in _PRIMARY_LOCK_FILES]
    return not engine.lock_file_held(locks)


def _migrate(engine) -> None:
    """Move the legacy data directory when this is the main instance. Never raises."""
    if engine is None:
        return
    current, legacy = _user_data_dir_pair()
    try:
        # The ordinary start: nothing under an earlier name and no unfinished
        # move on record. Two stat calls, and no instance probe at all.
        pending = os.path.lexists(engine.default_lock_path(current)) or any(
            engine.inspect_legacy(old, current) is engine.LegacyState.REAL_DIRECTORY
            for old in legacy
        )
        if not pending or not _is_main_instance(engine, legacy):
            return
        results = [
            engine.migrate_directory(old, current, wait_seconds=_MIGRATION_WAIT_SECONDS)
            for old in legacy
        ]
    except Exception as exc:  # noqa: BLE001 - boot continues where the data is; reported
        _report("WARNING", f"Data directory migration failed ({type(exc).__name__}: {exc}).")
        return
    notable = [r for r in results if r.outcome.value not in _QUIET_OUTCOMES]
    if not notable:
        return
    moved = all(r.outcome.value in _MOVED_OUTCOMES for r in notable)
    text = "; ".join(
        f"{r.legacy} -> {r.current}: {r.outcome.value}, using {r.effective}"
        + (f" ({r.detail})" if r.detail else "")
        for r in notable
    )
    _report("INFO" if moved else "WARNING", f"Data directory migration: {text}")


def _report(level: str, message: str) -> None:
    """Hand the line on to the launcher's log, which does not exist yet, and to stderr."""
    _warn(message)
    try:
        os.environ[_REPORT_ENV_VAR] = f"{level}|{message}"
    except (OSError, ValueError) as exc:
        _warn(f"could not pass the migration report on: {exc}")


def _names_legacy_default(name: str, legacy_dirs, leaf_names) -> bool:
    """True when variable ``name`` holds what this hook exports for a legacy directory.

    An app started by an earlier one (an in-app restart, an update) inherits
    the variables that process's hook exported. A value that only names a
    legacy directory's own default location is derived afresh, so the app
    does not keep the old spelling once the directory has moved.
    """
    value = (os.environ.get(name) or "").strip()
    if not value:
        return False
    wanted = os.path.normcase(os.path.normpath(value))
    return any(
        wanted == os.path.normcase(os.path.normpath(str(old / leaf)))
        for old in legacy_dirs
        for leaf in leaf_names
    )


def _is_set(name: str) -> bool:
    value = os.environ.get(name)
    return bool(value and value.strip())


def _warn(message: str) -> None:
    """Report a hook problem without ever becoming the crash itself."""
    stream = getattr(sys, "stderr", None)
    if stream is None:
        return
    try:
        stream.write(f"[jarvis] {message}\n")
    except (OSError, ValueError, AttributeError):
        # A windowed bundle can hand out a closed or null stream. There is no
        # log file yet at hook time, so an unreportable warning is dropped on
        # purpose rather than killing a boot that still works.
        pass


def _apply() -> None:
    if not (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")):
        return

    try:
        clashes = _adopt(os.environ)
    except (OSError, ValueError) as exc:
        # The operating system refused an environment write. The package runs
        # the same adoption on import and reports it with logging available;
        # the hook only has to keep the process alive until then.
        _warn(f"could not adopt the DODAIOS_ variable names: {exc}")
        clashes = []
    for new_name in clashes:
        _warn(f"{new_name} and its JARVIS_ spelling are set to different values; using {new_name}.")

    engine = _load_engine()
    _migrate(engine)
    home = _resolve_home(engine)
    _current, legacy_dirs = _user_data_dir_pair()
    moved_away = [old for old in legacy_dirs if old != home]
    config_names = (*_LEGACY_CONFIG_FILE_NAMES, _CONFIG_FILE_NAME)
    if _names_legacy_default("JARVIS_CONFIG", moved_away, config_names):
        os.environ.pop("JARVIS_CONFIG", None)
    if _names_legacy_default("JARVIS_DATA_DIR", moved_away, ("data",)):
        os.environ.pop("JARVIS_DATA_DIR", None)

    config_path = _resolve_config_file(home)

    if not _is_set("JARVIS_CONFIG"):
        if not config_path.exists():
            bundled = Path(sys._MEIPASS) / _BUNDLED_CONFIG_FILE_NAME  # noqa: SLF001
            try:
                home.mkdir(parents=True, exist_ok=True)
                if bundled.is_file():
                    shutil.copyfile(bundled, config_path)
            except OSError as exc:
                # Not silence: say it on stderr (a console CLI run shows it) and
                # continue. dodaios.core.config_writer creates the file on first
                # write anyway, so an unseeded config still boots on defaults.
                # A windowed bundle has no stderr yet — ensure_standard_streams()
                # runs later — so writing to it must never become the crash.
                _warn(f"could not seed {config_path}: {exc}")
        os.environ["JARVIS_CONFIG"] = str(config_path)

    if not _is_set("JARVIS_DATA_DIR"):
        os.environ["JARVIS_DATA_DIR"] = str(home / "data")

_apply()
