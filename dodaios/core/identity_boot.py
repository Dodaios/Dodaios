"""Find, and at the primary instance's start move, the directories named by persistent identity.

``dodaios.core.branding`` names the per-user data directory and the config
file. Their names changed once, and an existing installation still has its
data under the earlier name. Two things follow, and this module holds both:

* **Resolution, everywhere.** Any process (helpers, the CLI, the desktop app)
  asks :func:`user_data_dir_pair` / :func:`resolve_pair` where a directory is.
  The legacy directory wins while it is a real directory, not a link; otherwise
  the current name is used. The answer costs a few ``stat`` calls (AP-26) and
  is cached per process; :func:`reset_resolution_cache` clears it.
* **Migration, once, by the primary instance only.** :func:`migrate_at_boot`
  runs in the source launcher right after the instance is chosen and before
  anything opens a file in the data directory. It moves the legacy directory
  with one rename and leaves a junction (Windows) or symlink behind
  (``dodaios.core.identity_migration``); nothing is ever copied and deleted. A
  refused rename leaves everything where it was and the app runs from the
  legacy directory, which stays a fully valid state.
  The frozen build does the same in its runtime hook
  (``packaging/pyinstaller_rthook_frozen.py``), which cannot import the package.

The config file is never renamed: :func:`resolve_config_file` keeps an existing
legacy file in use for good, and only an installation that has none gets the
current name.

Standard library plus ``dodaios.core.branding`` / ``instance`` /
``identity_migration``, all import-light: the launcher imports this before the
config graph.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dodaios.core.branding import (
    CONFIG_FILE_NAME,
    FALLBACK_USER_DATA_DIR_NAME,
    LEGACY_CONFIG_FILE_NAMES,
    LEGACY_FALLBACK_USER_DATA_DIR_NAMES,
    LEGACY_WINDOWS_MUTEX_NAMES,
    LEGACY_WINDOWS_USER_DATA_DIR_NAMES,
    WINDOWS_MUTEX_NAME,
    WINDOWS_USER_DATA_DIR_NAME,
)
from dodaios.core.identity_migration import (
    DirectoryMigration,
    DirectoryOutcome,
    LegacyState,
    default_lock_path,
    inspect_legacy,
    lock_file_held,
    migrate_directory,
    named_mutex_exists,
    resolve_directory,
)
from dodaios.core.instance import (
    DEFAULT_INSTANCE_NAME,
    INSTANCE_ENV_VAR,
    KNOWN_INSTANCE_NAMES,
    InstanceNameError,
    normalize_instance_name,
)

log = logging.getLogger(__name__)

#: How long the primary waits for another migrator before it only resolves. A
#: caller that goes on to create directories must not resolve in the instant
#: between that migrator's rename and its link.
MIGRATION_WAIT_SECONDS = 2.0

#: The variable the frozen runtime hook leaves its one-line report in
#: (``level|message``); the launcher logs it once a sink exists.
HOOK_REPORT_ENV_VAR = "JARVIS_IDENTITY_MIGRATION_REPORT"

#: Lock files a running primary of any release holds inside the data
#: directory: the POSIX single-instance claim (``dodaios.ui.shell.single_instance``)
#: and the launcher lock of a frozen build, whose runtime data sits in ``data/``.
PRIMARY_LOCK_FILES: tuple[str, ...] = ("instance.lock", os.path.join("data", "jarvis.lock"))

#: Outcomes that are the ordinary start, not worth a log line.
_QUIET_OUTCOMES = frozenset({DirectoryOutcome.NOTHING_TO_MIGRATE, DirectoryOutcome.ALREADY_LINKED})


@dataclass(frozen=True, slots=True)
class DirectoryPair:
    """A directory under its current name and the earlier names it may still have."""

    current: Path
    legacy: tuple[Path, ...] = ()


def named_pair(parent: Path, name: str, legacy_names: Sequence[str]) -> DirectoryPair:
    """``parent/name`` with ``parent/<legacy>`` for each earlier name."""
    return DirectoryPair(parent / name, tuple(parent / legacy for legacy in legacy_names))


def user_data_dir_pair(environ: Mapping[str, str] | None = None) -> DirectoryPair:
    """The per-user data directory: ``%LOCALAPPDATA%\\Dodaios`` or ``~/.dodaios-data``.

    An exported-but-empty ``LOCALAPPDATA`` is not a directory, so it falls back
    to the home directory like an absent one.
    """
    source = os.environ if environ is None else environ
    base = source.get("LOCALAPPDATA")
    if base:
        return named_pair(
            Path(base), WINDOWS_USER_DATA_DIR_NAME, LEGACY_WINDOWS_USER_DATA_DIR_NAMES
        )
    return named_pair(Path.home(), FALLBACK_USER_DATA_DIR_NAME, LEGACY_FALLBACK_USER_DATA_DIR_NAMES)


def data_dir_pairs(environ: Mapping[str, str] | None = None) -> tuple[DirectoryPair, ...]:
    """Every directory the primary instance moves to its current name at boot.

    Only the data directory. Folders a person opens themselves (the Desktop
    output mirror, the deliverables folder) are resolved, never moved: a link
    left behind on the Desktop would show the same folder twice.
    """
    return (user_data_dir_pair(environ),)


# ----------------------------------------------------------------------
# Resolution
# ----------------------------------------------------------------------

_cache_lock = threading.Lock()
_resolved: dict[DirectoryPair, Path] = {}


def resolve_pair(pair: DirectoryPair) -> Path:
    """The directory to use for ``pair``: a legacy one while it is a real directory.

    Read-only and cached per process by the exact paths asked about, so a test
    that points ``LOCALAPPDATA`` or the home directory elsewhere gets a fresh
    answer without clearing anything.
    """
    with _cache_lock:
        cached = _resolved.get(pair)
    if cached is not None:
        return cached
    resolved = resolve_directory(pair.current, pair.legacy) if pair.legacy else pair.current
    with _cache_lock:
        _resolved[pair] = resolved
    return resolved


def reset_resolution_cache() -> None:
    """Forget every resolved directory; the next call reads the filesystem again."""
    with _cache_lock:
        _resolved.clear()


def resolve_named_dir(parent: Path, name: str, legacy_names: Sequence[str]) -> Path:
    """Resolve ``parent/name`` against its earlier names (see :func:`resolve_pair`)."""
    return resolve_pair(named_pair(parent, name, legacy_names))


def data_dir_spellings(path: str | os.PathLike[str]) -> tuple[Path, ...]:
    """``path`` under every name the per-user data directory has had.

    ``(path,)`` when it lies outside the data directory; otherwise ``path``
    first, then the same location under each other name. Purely lexical (no
    filesystem access): a path stored before the move spells the old name, one
    computed after it the new one, and after the move both reach the same file
    through the link left behind. Text comparisons of paths that may come from
    either side compare against every spelling.
    """
    pair = user_data_dir_pair()
    absolute = os.path.abspath(os.fspath(path))
    folded = os.path.normcase(absolute)
    roots = (pair.current, *pair.legacy)
    for root in roots:
        root_text = os.path.abspath(os.fspath(root))
        root_folded = os.path.normcase(root_text)
        if folded != root_folded and not folded.startswith(root_folded.rstrip(os.sep) + os.sep):
            continue
        rest = absolute[len(root_text) :].lstrip("\\/")
        spellings = [Path(absolute)]
        for other in roots:
            if other != root:
                other_root = Path(os.path.abspath(os.fspath(other)))
                spellings.append(other_root / rest if rest else other_root)
        return tuple(spellings)
    return (Path(absolute),)


def stable_data_dir_spelling(path: str | os.PathLike[str]) -> Path:
    """``path`` spelled under the data directory's earliest name when it lies inside it.

    For identifiers derived from a path (a hash, a key): one computed after the
    move then equals one stored before it. Outside the data directory the
    path is returned unchanged (made absolute).
    """
    pair = user_data_dir_pair()
    spellings = data_dir_spellings(path)
    if len(spellings) == 1 or not pair.legacy:
        return spellings[0]
    earliest = os.path.normcase(os.path.abspath(os.fspath(pair.legacy[-1])))
    for spelling in spellings:
        folded = os.path.normcase(str(spelling))
        if folded == earliest or folded.startswith(earliest.rstrip(os.sep) + os.sep):
            return spelling
    return spellings[0]


def resolve_config_file(root: str | os.PathLike[str]) -> Path:
    """The config file in ``root``: a legacy-named file while it exists, else the current name.

    The file is never renamed. An installation that has a ``jarvis.toml`` keeps
    it as its configuration; one that has none (a fresh install) gets
    ``dodaios.toml``. One ``stat`` per legacy name.
    """
    folder = Path(root)
    for legacy in LEGACY_CONFIG_FILE_NAMES:
        candidate = folder / legacy
        if candidate.is_file():
            return candidate
    return folder / CONFIG_FILE_NAME


def config_file_names() -> tuple[str, ...]:
    """Every name the config file may have, in the order :func:`resolve_config_file` tries."""
    return (*LEGACY_CONFIG_FILE_NAMES, CONFIG_FILE_NAME)


# ----------------------------------------------------------------------
# Migration at boot
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MigrationDecision:
    """Whether this process may move directories, and why (for the log)."""

    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def primary_mutex_names() -> tuple[str, ...]:
    """Mutex names a running desktop app of this or an earlier release holds.

    Every instance counts, the dev app included: it shares the per-user data
    directory with the default app.
    """
    names: list[str] = []
    for base in (WINDOWS_MUTEX_NAME, *LEGACY_WINDOWS_MUTEX_NAMES):
        names.append(base)
        names.extend(
            f"{base}_{name}" for name in KNOWN_INSTANCE_NAMES if name != DEFAULT_INSTANCE_NAME
        )
    return tuple(names)


def primary_lock_files(pairs: Sequence[DirectoryPair]) -> tuple[Path, ...]:
    """The primary-instance lock files inside every legacy directory of ``pairs``."""
    return tuple(
        legacy / name for pair in pairs for legacy in pair.legacy for name in PRIMARY_LOCK_FILES
    )


def migration_pending(pairs: Sequence[DirectoryPair]) -> bool:
    """True when a legacy directory still holds data, or a move is unfinished.

    The ordinary start answers False with a couple of ``stat`` calls and no
    instance probe (AP-26).
    """
    for pair in pairs:
        if pair.legacy and os.path.lexists(default_lock_path(pair.current)):
            return True
        for legacy in pair.legacy:
            if inspect_legacy(legacy, pair.current) is LegacyState.REAL_DIRECTORY:
                return True
    return False


def may_migrate(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    platform: str | None = None,
    pairs: Sequence[DirectoryPair] | None = None,
    mutex_exists: Callable[[Sequence[str]], bool] = named_mutex_exists,
    lock_held: Callable[[Sequence[Path]], bool] = lock_file_held,
) -> MigrationDecision:
    """True only for the main instance: default instance, with the lock, nothing else running.

    The main instance is the default instance started without ``--no-lock``,
    and no primary is running: on Windows no single-instance mutex exists
    under any name it has had; elsewhere nobody holds a lock file in a legacy
    directory (the file is opened, never created). A frozen build answers
    False here because its runtime hook already made the same decision before
    the package was importable.
    """
    source = os.environ if environ is None else environ
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        return MigrationDecision(False, "frozen build: the runtime hook migrates")
    try:
        instance = normalize_instance_name(source.get(INSTANCE_ENV_VAR))
    except InstanceNameError:
        # The launcher reports the bad name and exits; here it only means no move.
        return MigrationDecision(False, f"unknown {INSTANCE_ENV_VAR}")
    if instance != DEFAULT_INSTANCE_NAME:
        return MigrationDecision(False, f"instance {instance!r} only resolves")
    if "--no-lock" in argv:
        return MigrationDecision(False, "--no-lock run only resolves")
    os_name = sys.platform if platform is None else platform
    if os_name == "win32":
        if mutex_exists(primary_mutex_names()):
            return MigrationDecision(False, "a primary instance is running")
        return MigrationDecision(True, "no primary instance holds the mutex")
    checked = data_dir_pairs(source) if pairs is None else pairs
    if lock_held(primary_lock_files(checked)):
        return MigrationDecision(False, "a primary instance holds its lock file")
    return MigrationDecision(True, "no primary instance holds a lock file")


def migrate_data_dirs(
    pairs: Sequence[DirectoryPair] | None = None,
    *,
    wait_seconds: float = MIGRATION_WAIT_SECONDS,
    migrate: Callable[..., DirectoryMigration] = migrate_directory,
) -> tuple[DirectoryMigration, ...]:
    """Move every legacy directory of ``pairs`` to its current name. Never raises ``OSError``.

    The caller has established that it is the main instance. The resolution
    cache is cleared afterwards, so every later lookup sees the result.
    """
    results: list[DirectoryMigration] = []
    try:
        for pair in data_dir_pairs() if pairs is None else pairs:
            for legacy in pair.legacy:
                results.append(migrate(legacy, pair.current, wait_seconds=wait_seconds))
    finally:
        reset_resolution_cache()
    return tuple(results)


#: Outcomes after which the data is under the current name.
_MOVED_OUTCOMES = frozenset({DirectoryOutcome.MIGRATED, DirectoryOutcome.LINK_RESTORED})


@dataclass(frozen=True, slots=True)
class BootReport:
    """The one log line a boot migration leaves, and its level."""

    level: str
    message: str


def describe(results: Sequence[DirectoryMigration]) -> BootReport | None:
    """One log line for what the migration did, or ``None`` for an ordinary start.

    INFO when everything that was found moved, WARNING when something stayed
    under its earlier name (it is still in use there, which works, but the
    reason belongs in the log).
    """
    notable = [result for result in results if result.outcome not in _QUIET_OUTCOMES]
    if not notable:
        return None
    parts = []
    for result in notable:
        text = (
            f"{result.legacy} -> {result.current}: {result.outcome.value}, using {result.effective}"
        )
        if result.detail:
            text += f" ({result.detail})"
        parts.append(text)
    moved = all(result.outcome in _MOVED_OUTCOMES for result in notable)
    return BootReport(
        "INFO" if moved else "WARNING", "Data directory migration: " + "; ".join(parts)
    )


def take_hook_report(environ: MutableMapping[str, str] | None = None) -> BootReport | None:
    """The report the frozen runtime hook left in the environment, removed from it.

    Removed so that no child process inherits it and logs it a second time.
    """
    source = os.environ if environ is None else environ
    raw = source.pop(HOOK_REPORT_ENV_VAR, None)
    if not raw:
        return None
    level, separator, message = raw.partition("|")
    if not separator or level not in ("INFO", "WARNING") or not message:
        return BootReport("WARNING", raw)
    return BootReport(level, message)


def migrate_at_boot(argv: Sequence[str]) -> BootReport | None:
    """The launcher's hook: migrate when this is the main instance, else only resolve.

    Returns the line to log once the log sink exists (this runs before it),
    or ``None`` when there is nothing to say. In a frozen build that is the
    runtime hook's report. No exception escapes: a failed migration leaves the
    app running from the legacy directory.
    """
    hook_report = take_hook_report()
    if hook_report is not None:
        return hook_report
    try:
        pairs = data_dir_pairs()
        if not migration_pending(pairs):
            return None
        decision = may_migrate(argv, pairs=pairs)
        if not decision:
            log.debug("Data directory migration skipped: %s.", decision.reason)
            return None
        return describe(migrate_data_dirs(pairs))
    except Exception as exc:  # noqa: BLE001 - boot continues at the legacy path; reported
        log.warning("Data directory migration failed; continuing where the data is.", exc_info=True)
        reset_resolution_cache()
        return BootReport(
            "WARNING",
            f"Data directory migration failed ({type(exc).__name__}: {exc}); "
            "running from the directory that holds the data now.",
        )


__all__ = [
    "HOOK_REPORT_ENV_VAR",
    "MIGRATION_WAIT_SECONDS",
    "PRIMARY_LOCK_FILES",
    "BootReport",
    "DirectoryPair",
    "MigrationDecision",
    "config_file_names",
    "data_dir_pairs",
    "data_dir_spellings",
    "describe",
    "may_migrate",
    "migrate_at_boot",
    "migrate_data_dirs",
    "migration_pending",
    "named_pair",
    "primary_lock_files",
    "primary_mutex_names",
    "reset_resolution_cache",
    "resolve_config_file",
    "resolve_named_dir",
    "resolve_pair",
    "stable_data_dir_spelling",
    "take_hook_report",
    "user_data_dir_pair",
]
