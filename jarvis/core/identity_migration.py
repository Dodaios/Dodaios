"""Carry an installation's persistent identity from a legacy name to the current one.

A persistent identifier (``jarvis.core.branding``) names things an existing
installation already owns: its data directory, its install directory, the
credential-store service its keys are filed under. Changing such a name is only
safe together with a migration that keeps every file and every credential
reachable, under the old name as well as the new one. This module is that
migration. It is inert on its own: nothing here runs until a caller hands it a
legacy name and a current name.

The rules it enforces:

* **A legacy directory wins while it still holds the data.** A process that only
  needs to know where its files live calls :func:`resolve_directory` and never
  moves anything. Helper processes only ever resolve.
* **A directory moves by one atomic rename, or not at all.** Nothing is ever
  copied and deleted, merged or overwritten. When the rename is refused (a file
  is open, the target is on another volume, access is denied) everything stays
  where it was, and running from the legacy location is a permanently valid
  state, not a degraded one.
* **The legacy path keeps working.** After the rename a link is left at the
  legacy path (a directory junction on Windows, which needs no privilege; a
  symlink elsewhere), so code that still spells the old name reads and writes
  the same files.
* **One migrator at a time.** The move is serialized by an OS lock on a small
  journal file that sits *beside* the current directory, so it is outside both
  directories and unaffected by the rename.
* **The journal is the memory of a move.** The migrator records which
  directory it moves, by filesystem identity, and that the rename went through.
  While that journal exists, a directory at the current path with that identity
  is proof it came from the legacy path: a crash between the rename and the
  link is finished on the next start, a fresh install is never mistaken for
  one, and a directory that something recreates at the legacy path afterwards
  cannot hide the moved data.
* **Credentials are copied, never moved.** :func:`migrate_keyring` copies each
  known entry to the current service unless that already holds a value, leaves
  every legacy entry in place as the way back, and records a marker so it runs
  once.

Standard library only and no ``jarvis`` import: the frozen runtime hook has to
load this file by path before anything from the package exists. For the same
reason there is no ``from __future__ import annotations``: with string
annotations ``dataclasses`` looks the module up in ``sys.modules``, where a file
loaded by path need not be.
"""

import enum
import errno
import json
import logging
import os
import stat
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

PathLike = str | os.PathLike[str]

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# IO_REPARSE_TAG_MOUNT_POINT (a junction) and IO_REPARSE_TAG_SYMLINK. Every
# other reparse tag (cloud-sync placeholder, deduplicated volume) marks an
# ordinary directory that merely carries a reparse point.
_LINK_REPARSE_TAGS = frozenset({0xA0000003, 0xA000000C})
_WINDOWS_PATH_PREFIXES = ("\\\\?\\", "\\??\\")
# ERROR_NOT_SAME_DEVICE; ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION,
# ERROR_LOCK_VIOLATION.
_WINERROR_CROSS_DEVICE = 17
_WINERRORS_IN_USE = frozenset({5, 32, 33})

# Pauses before another try when a step is refused because something else has
# the directory open. A virus scanner or an indexer looking at files an
# installer has just written lets go within moments; a real lock outlasts this
# and the legacy directory simply stays in use.
TRANSIENT_RETRY_DELAYS: tuple[float, ...] = (0.05, 0.15, 0.3)

_JOURNAL_MAX_BYTES = 65536
_LOCK_OPEN_ATTEMPTS = 3
_LOCK_POLL_SECONDS = 0.05


# ----------------------------------------------------------------------
# Directory resolution
# ----------------------------------------------------------------------


class LegacyState(enum.Enum):
    """What sits at a legacy path, seen from the current path."""

    ABSENT = "absent"
    REAL_DIRECTORY = "real_directory"
    LINK_TO_CURRENT = "link_to_current"
    # A live link to some other directory: the user redirected their data
    # themselves, so the legacy path is still where it is reached from.
    FOREIGN_LINK = "foreign_link"
    DANGLING_LINK = "dangling_link"
    NOT_A_DIRECTORY = "not_a_directory"
    # Something is there but cannot be looked at (access denied, I/O error).
    # It is never taken for absent: starting on an empty directory while the
    # data sits behind a momentary error would split the installation in two.
    UNREADABLE = "unreadable"


def _strip_windows_prefix(path: str) -> str:
    if sys.platform == "win32":
        for prefix in _WINDOWS_PATH_PREFIXES:
            if path.startswith(prefix):
                return path[len(prefix) :]
    return path


def _normalized(path: PathLike) -> str:
    text = _strip_windows_prefix(os.fspath(path))
    return os.path.normcase(os.path.normpath(os.path.abspath(text)))


def _is_link(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    if not getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT:
        return False
    return getattr(metadata, "st_reparse_tag", 0) in _LINK_REPARSE_TAGS


def _exists(path: PathLike) -> bool:
    """True unless the path is provably free. An unreadable path counts as taken."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        # Nothing there, which is what the caller hopes for.
        return False
    except OSError as exc:
        log.warning("Path %s cannot be inspected (%s); treating it as occupied.", path, exc)
    return True


def _link_points_at(link: str, target: str) -> bool:
    try:
        raw = _strip_windows_prefix(os.readlink(link))
    except OSError:
        # An unreadable link target is not provably ours, so it is not ours.
        return False
    if not os.path.isabs(raw):
        raw = os.path.join(os.path.dirname(os.path.abspath(link)), raw)
    if _normalized(raw) == _normalized(target):
        return True
    try:
        # Catches a differently spelled route to the same directory (case,
        # short names, a relative hop) that the text comparison cannot see.
        return os.path.samefile(link, target)
    except OSError:
        # One side is missing; the text comparison above already settled it.
        return False


def inspect_legacy(legacy: PathLike, current: PathLike) -> LegacyState:
    """Classify ``legacy`` relative to ``current``. Reads only, never raises."""
    legacy_text = os.fspath(legacy)
    try:
        metadata = os.lstat(legacy_text)
    except (FileNotFoundError, NotADirectoryError):
        # Nothing there: the ordinary state of a fresh install.
        return LegacyState.ABSENT
    except OSError as exc:
        log.warning("Legacy path %s cannot be inspected (%s).", legacy_text, exc)
        return LegacyState.UNREADABLE
    if _is_link(metadata):
        if _link_points_at(legacy_text, os.fspath(current)):
            return LegacyState.LINK_TO_CURRENT
        if os.path.isdir(legacy_text):
            return LegacyState.FOREIGN_LINK
        if os.path.exists(legacy_text):
            return LegacyState.NOT_A_DIRECTORY
        return LegacyState.DANGLING_LINK
    if stat.S_ISDIR(metadata.st_mode):
        return LegacyState.REAL_DIRECTORY
    return LegacyState.NOT_A_DIRECTORY


def default_lock_path(current: PathLike) -> Path:
    """The journal and lock file for migrations into ``current``.

    A sibling of the current directory: outside the directory that moves and
    outside the one it becomes, so the rename cannot carry it away, and derived
    from the current path alone so every process agrees on it.
    """
    current_path = Path(os.path.abspath(current))
    return current_path.with_name(f".{current_path.name.lstrip('.')}.identity-migration")


def _parse_journal(raw: bytes, source: PathLike) -> dict[str, object] | None:
    if not raw.strip():
        return None
    try:
        journal = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        log.warning("Ignoring an unreadable migration journal at %s (%s).", source, exc)
        return None
    return journal if isinstance(journal, dict) else None


def _peek_journal(path: PathLike) -> dict[str, object] | None:
    """Read the journal without the lock, for a process that only resolves."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(_JOURNAL_MAX_BYTES)
    except OSError:
        # No journal, which is the normal case, or a migrator holds it this
        # instant and Windows keeps other readers out of a locked file.
        return None
    return _parse_journal(raw, path)


def _names_pair(journal: dict[str, object] | None, legacy: PathLike, current: PathLike) -> bool:
    if journal is None:
        return False
    return _normalized(str(journal.get("legacy", ""))) == _normalized(legacy) and _normalized(
        str(journal.get("current", ""))
    ) == _normalized(current)


def _proves_move(journal: dict[str, object] | None, legacy: PathLike, current: PathLike) -> bool:
    """True when the journal shows that ``current`` is the directory moved from ``legacy``.

    Two facts together: the migrator recorded that its rename went through, and
    the directory now at the current path still has the filesystem identity
    that was recorded before it. The identity alone is not enough, because a
    filesystem hands a freed identity to the next directory it creates. A
    filesystem without stable identities proves nothing, and nothing is then
    assumed.
    """
    if journal is None or not _names_pair(journal, legacy, current):
        return False
    if journal.get("renamed") is not True:
        return False
    try:
        metadata = os.lstat(current)
    except OSError:
        # No readable directory at the current path, so nothing is proven.
        return False
    if not stat.S_ISDIR(metadata.st_mode) or _is_link(metadata):
        return False
    inode = journal.get("inode")
    return bool(inode) and (metadata.st_dev, metadata.st_ino) == (journal.get("device"), inode)


def resolve_directory(
    current: PathLike,
    legacy_paths: Sequence[PathLike] = (),
    *,
    lock_path: PathLike | None = None,
) -> Path:
    """Return the directory to use: the first legacy path that still holds the data.

    A legacy path wins while it is a real directory (or the user's own link to
    one, or something that cannot be inspected). A legacy path that is absent,
    dangling, or already a link to ``current`` loses, and ``current`` is
    returned. The one exception is a directory that appeared at the legacy path
    *after* the data was moved away from it, which the migration journal
    proves; ``lock_path`` names that journal when the migrator was given one.

    It reads the filesystem and changes nothing, so any process may call it at
    any time.
    """
    for legacy in legacy_paths:
        state = inspect_legacy(legacy, current)
        if state in (LegacyState.FOREIGN_LINK, LegacyState.UNREADABLE):
            return Path(legacy)
        if state is LegacyState.REAL_DIRECTORY:
            journal_path = default_lock_path(current) if lock_path is None else lock_path
            if not _proves_move(_peek_journal(journal_path), legacy, current):
                return Path(legacy)
    return Path(current)


# ----------------------------------------------------------------------
# Directory migration
# ----------------------------------------------------------------------


class DirectoryOutcome(enum.Enum):
    """What :func:`migrate_directory` did. Every value is a valid end state."""

    # No legacy directory: a fresh install, or the two paths are the same.
    NOTHING_TO_MIGRATE = "nothing_to_migrate"
    # The legacy path already is a link to the current directory.
    ALREADY_LINKED = "already_linked"
    # Renamed, and a link now stands at the legacy path.
    MIGRATED = "migrated"
    # Renamed, but no link could be left at the legacy path. The data is at
    # the current path; the link is attempted again on the next call.
    MIGRATED_WITHOUT_LINK = "migrated_without_link"
    # An earlier call renamed and never left the link; this call created it.
    LINK_RESTORED = "link_restored"
    # An earlier call renamed, and something has since created a directory with
    # content at the legacy path. The moved data at the current path stays in
    # use; the newer directory is left exactly as it is.
    LEGACY_RECREATED = "legacy_recreated"
    # Something already exists at the current path. Nothing is merged or
    # overwritten; the legacy directory stays in use.
    BOTH_EXIST = "both_exist"
    # The legacy path is a foreign link, a dangling link or a file.
    LEGACY_NOT_A_DIRECTORY = "legacy_not_a_directory"
    # The legacy path cannot be inspected. Nothing moved; it stays in use.
    LEGACY_UNREADABLE = "legacy_unreadable"
    # The rename was refused. Nothing moved; the legacy directory stays in use.
    RENAME_FAILED = "rename_failed"
    # Another process is migrating right now. This one only resolves, and what
    # it resolved is a snapshot taken while that migration was under way.
    LOCK_BUSY = "lock_busy"
    # The journal file could not be opened, locked, read or written. Nothing
    # moved.
    LOCK_UNAVAILABLE = "lock_unavailable"


class RenameFailure(enum.Enum):
    """Why a rename was refused."""

    IN_USE_OR_DENIED = "in_use_or_denied"
    CROSS_DEVICE = "cross_device"
    DESTINATION_EXISTS = "destination_exists"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class DirectoryMigration:
    """The full account of one :func:`migrate_directory` call."""

    outcome: DirectoryOutcome
    legacy: Path
    current: Path
    # The directory to use from here on, as resolve_directory() gives it.
    effective: Path
    # What stands at the legacy path after the call.
    legacy_state: LegacyState
    rename_failure: RenameFailure | None = None
    # The underlying error text, when there was one.
    detail: str = ""


def create_directory_link(link: PathLike, target: PathLike) -> None:
    """Make ``link`` an alias of the directory ``target``. Raises ``OSError``.

    Windows gets a directory junction, the one link an unprivileged account may
    create; it is made in-process, so no console flashes and no path has to
    survive a command line. Every other OS gets a symlink. Either way the link
    appears at ``link`` in one step and never replaces anything.
    """
    link_text = os.path.abspath(link)
    target_text = os.path.abspath(target)
    if os.path.lexists(link_text):
        raise FileExistsError(errno.EEXIST, "a link cannot replace an existing path", link_text)
    if sys.platform != "win32":
        os.symlink(target_text, link_text, target_is_directory=True)
        return
    try:
        import _winapi  # noqa: PLC0415 - CPython-internal, Windows-only

        create_junction = _winapi.CreateJunction
    except (ImportError, AttributeError) as exc:
        raise OSError(errno.ENOSYS, "this Python cannot create a directory junction") from exc
    # A junction is a directory first and a link second. Made in place, the
    # link path would for a moment be an empty real directory, which outranks
    # the current one. It is built under a staging name and renamed instead.
    name = os.path.basename(link_text).lstrip(".")
    staging = os.path.join(os.path.dirname(link_text), f".{name}.identity-link")
    _remove_staged_link(staging)
    try:
        create_junction(target_text, staging)
        os.rename(staging, link_text)
    except OSError:
        _remove_staged_link(staging)
        raise


def _remove_staged_link(staging: str) -> None:
    """Drop a leftover staging junction. rmdir cannot remove anything that holds data."""
    try:
        os.rmdir(staging)
    except FileNotFoundError:
        # Nothing was left behind, which is the usual case.
        return
    except OSError as exc:
        log.debug("Staging link %s not removed (%s).", staging, exc)


def _try_lock(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415 - Windows-only

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415 - POSIX-only

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        contended = isinstance(exc, BlockingIOError | PermissionError)
        if contended or exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            # Expected contention: another process holds the lock.
            return False
        raise
    return True


def _unlock(fd: int) -> None:
    """Release explicitly on Windows, which may otherwise unlock a while after close."""
    if sys.platform != "win32":
        # POSIX: closing the descriptor releases the lock at once.
        return
    try:
        import msvcrt  # noqa: PLC0415 - Windows-only

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError as exc:
        log.debug("Explicit unlock of the migration journal failed (%s).", exc)


def _unlink(path: str) -> bool:
    try:
        os.unlink(path)
    except FileNotFoundError:
        # Already gone, which is the state that was asked for.
        return True
    except OSError as exc:
        # Windows refuses to delete a file that is open, ours included. The
        # caller tries once more after closing it; a file that then stays
        # belongs to a process that opened it in between.
        log.debug("Journal %s not removed yet (%s).", path, exc)
        return False
    return True


def _open_journal(path: str) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    for delay in (*TRANSIENT_RETRY_DELAYS, None):
        try:
            return os.open(path, flags, 0o600)
        except PermissionError:
            # Windows: a journal that was deleted while a scanner still had it
            # open lingers, unopenable, until that handle closes. A journal
            # that does not exist and cannot be created is a real refusal.
            if delay is None or not os.path.lexists(path):
                raise
            time.sleep(delay)
    raise AssertionError("unreachable: the last attempt returns or raises")


class _MigrationLock:
    """The held OS lock on the journal file, and the journal it guards.

    The lock belongs to the open descriptor, so a crashed holder releases it.
    Only the holder writes the journal.
    """

    def __init__(self, path: str, fd: int) -> None:
        self._path = path
        self._fd = fd

    @classmethod
    def acquire(cls, path: PathLike) -> "_MigrationLock | None":
        """Take the lock without waiting. ``None`` when another process holds it."""
        text = os.fspath(path)
        os.makedirs(os.path.dirname(text), exist_ok=True)
        for _ in range(_LOCK_OPEN_ATTEMPTS):
            fd = _open_journal(text)
            try:
                if not _try_lock(fd):
                    os.close(fd)
                    return None
                # A finished migrator deletes the journal. If that happened
                # after this open, the lock is on a file nobody else can see
                # and guards nothing: take the one that is published now.
                published = os.path.samestat(os.fstat(fd), os.stat(text))
            except FileNotFoundError:
                # The journal was deleted under this descriptor: open it anew.
                published = False
            except BaseException:
                os.close(fd)
                raise
            if published:
                return cls(text, fd)
            os.close(fd)
        # Other migrators kept finishing in between, which is contention.
        return None

    def read_journal(self) -> dict[str, object] | None:
        os.lseek(self._fd, 0, os.SEEK_SET)
        return _parse_journal(os.read(self._fd, _JOURNAL_MAX_BYTES), self._path)

    def write_journal(self, journal: dict[str, object]) -> None:
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.ftruncate(self._fd, 0)
        os.write(self._fd, json.dumps(journal).encode("utf-8"))
        os.fsync(self._fd)

    def release(self, *, remove: bool) -> None:
        fd, self._fd = self._fd, -1
        removed = False
        if remove:
            try:
                # Emptied first: Windows cannot delete the file while a process
                # that just lost the lock still has it open, and a journal that
                # outlives the move must not read as an unfinished one.
                os.ftruncate(fd, 0)
            except OSError as exc:
                log.debug("Migration journal %s not emptied (%s).", self._path, exc)
            # POSIX deletes the journal while the lock is still held, so nobody
            # can take over a file that is about to vanish.
            removed = _unlink(self._path)
        _unlock(fd)
        try:
            os.close(fd)
        except OSError as exc:
            log.debug("Closing the migration journal %s failed (%s).", self._path, exc)
        if remove and not removed:
            _unlink(self._path)


def _acquire(path: Path, wait_seconds: float) -> _MigrationLock | None:
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        lock = _MigrationLock.acquire(path)
        if lock is not None or time.monotonic() >= deadline:
            return lock
        time.sleep(_LOCK_POLL_SECONDS)


def _remove_if_empty(legacy: Path, current: Path) -> bool:
    """Take back an empty directory that appeared at the legacy path."""
    if inspect_legacy(legacy, current) is not LegacyState.REAL_DIRECTORY:
        return False
    try:
        os.rmdir(legacy)
    except OSError:
        # Not empty, so it holds data and stays; nothing was removed.
        return False
    return True


def _retrying(step: Callable[[], None], retry_delays: Sequence[float]) -> None:
    """Run ``step``; try again after each delay while the refusal looks transient."""
    for delay in (*retry_delays, None):
        try:
            step()
            return
        except OSError as exc:
            transient = _classify_rename_failure(exc) is RenameFailure.IN_USE_OR_DENIED
            if delay is None or not transient:
                raise
            log.debug("Refused (%s); trying again in %.2f s.", exc, delay)
            time.sleep(delay)


def _classify_rename_failure(exc: OSError) -> RenameFailure:
    winerror = getattr(exc, "winerror", None)
    if exc.errno == errno.EXDEV or winerror == _WINERROR_CROSS_DEVICE:
        return RenameFailure.CROSS_DEVICE
    if isinstance(exc, FileExistsError) or exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
        return RenameFailure.DESTINATION_EXISTS
    in_use = exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY)
    if isinstance(exc, PermissionError) or in_use or winerror in _WINERRORS_IN_USE:
        return RenameFailure.IN_USE_OR_DENIED
    return RenameFailure.OTHER


def _settled_outcome(state: LegacyState, current_exists: bool) -> DirectoryOutcome | None:
    """The outcome a state already implies, or ``None`` when a move is due."""
    if state is LegacyState.ABSENT:
        return DirectoryOutcome.NOTHING_TO_MIGRATE
    if state is LegacyState.LINK_TO_CURRENT:
        return DirectoryOutcome.ALREADY_LINKED
    if state is LegacyState.UNREADABLE:
        return DirectoryOutcome.LEGACY_UNREADABLE
    if state is not LegacyState.REAL_DIRECTORY:
        return DirectoryOutcome.LEGACY_NOT_A_DIRECTORY
    return DirectoryOutcome.BOTH_EXIST if current_exists else None


@dataclass(frozen=True, slots=True)
class _Step:
    """One locked pass: its outcome and whether the journal may be deleted."""

    outcome: DirectoryOutcome
    remove_journal: bool
    rename_failure: RenameFailure | None = None
    detail: str = ""


def _leave_link(
    legacy: Path,
    current: Path,
    make_link: Callable[[Path, Path], None],
    retry_delays: Sequence[float],
    *,
    linked: DirectoryOutcome,
) -> _Step:
    """Put the link at the legacy path. The journal stays until it stands."""
    error = ""
    for attempt in range(2):
        try:
            _retrying(lambda: make_link(legacy, current), retry_delays)
        except OSError as exc:
            # Kept for the result and logged below, once the state is known.
            error = f"{type(exc).__name__}: {exc}"
        if inspect_legacy(legacy, current) is LegacyState.LINK_TO_CURRENT:
            return _Step(linked, remove_journal=True)
        # A process that resolved a moment before the rename may have created
        # the legacy directory afresh. While it is still empty it can make way.
        if attempt == 0 and _remove_if_empty(legacy, current):
            continue
        break
    detail = error or "the link was created but does not lead to the current directory"
    log.warning(
        "Moved %s to %s but could not leave a link at the old path (%s).", legacy, current, detail
    )
    return _Step(DirectoryOutcome.MIGRATED_WITHOUT_LINK, remove_journal=False, detail=detail)


def _migrate_locked(
    lock: _MigrationLock,
    legacy: Path,
    current: Path,
    rename: Callable[[Path, Path], None],
    make_link: Callable[[Path, Path], None],
    retry_delays: Sequence[float],
) -> _Step:
    # Everything is read again under the lock: the state seen before taking it
    # may be the one another migrator has just finished changing.
    state = inspect_legacy(legacy, current)
    try:
        journal = lock.read_journal()
    except OSError as exc:
        log.warning("Migration journal for %s cannot be read (%s).", current, exc)
        return _Step(DirectoryOutcome.LOCK_UNAVAILABLE, remove_journal=False, detail=str(exc))
    # An earlier call renamed this very directory and did not finish.
    moved = _proves_move(journal, legacy, current)
    # A journal for another legacy path is that migration's to finish.
    disposable = journal is None or _names_pair(journal, legacy, current)

    if state is LegacyState.UNREADABLE:
        return _Step(DirectoryOutcome.LEGACY_UNREADABLE, remove_journal=journal is None)
    if moved and state is LegacyState.ABSENT:
        return _leave_link(
            legacy, current, make_link, retry_delays, linked=DirectoryOutcome.LINK_RESTORED
        )
    if moved and state is LegacyState.REAL_DIRECTORY:
        if _remove_if_empty(legacy, current):
            return _leave_link(
                legacy, current, make_link, retry_delays, linked=DirectoryOutcome.LINK_RESTORED
            )
        # The journal is the only record that the data is at the current path
        # and not in this newer directory, so it stays.
        return _Step(DirectoryOutcome.LEGACY_RECREATED, remove_journal=False)
    settled = _settled_outcome(state, _exists(current))
    if settled is not None:
        return _Step(settled, remove_journal=disposable)

    # Nothing exists at the current path, so whatever the journal still says
    # describes a move that never happened; this one replaces it.
    try:
        moving = os.lstat(legacy)
        intent: dict[str, object] = {
            "legacy": os.fspath(legacy),
            "current": os.fspath(current),
            "device": moving.st_dev,
            "inode": moving.st_ino,
        }
        lock.write_journal(intent)
    except OSError as exc:
        # Without a journal a crash after the rename could not be finished, so
        # the rename is not attempted.
        log.warning("Migration journal for %s could not be written (%s).", current, exc)
        return _Step(DirectoryOutcome.LOCK_UNAVAILABLE, remove_journal=True, detail=str(exc))
    renamed = intent | {"renamed": True}
    try:
        _retrying(lambda: rename(legacy, current), retry_delays)
    except OSError as exc:
        # A network filesystem can report a failure for a rename that went
        # through. The directory itself is asked before anything is concluded.
        if not _proves_move(renamed, legacy, current):
            failure = _classify_rename_failure(exc)
            log.warning(
                "Could not rename %s to %s (%s: %s); it stays in use where it is.",
                legacy,
                current,
                failure.value,
                exc,
            )
            return _Step(
                DirectoryOutcome.RENAME_FAILED,
                remove_journal=True,
                rename_failure=failure,
                detail=f"{type(exc).__name__}: {exc}",
            )
    log.info("Renamed %s to %s.", legacy, current)
    try:
        lock.write_journal(renamed)
    except OSError as exc:
        # The link is still attempted below. Only a later start can no longer
        # tell that this directory was moved, and will leave it without one.
        log.warning("Migration journal for %s could not record the rename (%s).", current, exc)
    return _leave_link(legacy, current, make_link, retry_delays, linked=DirectoryOutcome.MIGRATED)


def migrate_directory(
    legacy: PathLike,
    current: PathLike,
    *,
    lock_path: PathLike | None = None,
    wait_seconds: float = 0.0,
    retry_delays: Sequence[float] = TRANSIENT_RETRY_DELAYS,
    rename: Callable[[Path, Path], None] = os.rename,
    make_link: Callable[[Path, Path], None] = create_directory_link,
) -> DirectoryMigration:
    """Move ``legacy`` to ``current`` and leave a link behind. Never loses data.

    Only the primary instance calls this, once, before anything opens a file in
    either directory. It renames when ``legacy`` is a real directory and nothing
    exists at ``current``; in every other case it changes nothing and says why.
    A refused rename leaves the legacy directory in use, for good if need be.

    ``wait_seconds`` is how long to wait for another migrator instead of
    returning ``LOCK_BUSY`` at once; a caller that goes on to create
    directories should wait, so it never resolves in the instant between that
    migrator's rename and its link. ``retry_delays`` are the pauses before a
    step that was refused as "in use" is tried again; pass ``()`` for a single
    attempt. ``rename`` and ``make_link`` are seams for the two filesystem
    steps; both must raise ``OSError`` on failure.
    """
    legacy_path = Path(os.path.abspath(legacy))
    current_path = Path(os.path.abspath(current))
    if lock_path is None:
        journal_path = default_lock_path(current_path)
    else:
        journal_path = Path(os.path.abspath(lock_path))

    def report(
        outcome: DirectoryOutcome,
        *,
        rename_failure: RenameFailure | None = None,
        detail: str = "",
    ) -> DirectoryMigration:
        effective = resolve_directory(current_path, [legacy_path], lock_path=journal_path)
        if outcome in (DirectoryOutcome.MIGRATED_WITHOUT_LINK, DirectoryOutcome.LEGACY_RECREATED):
            # This call knows where the data is, whatever stands at the legacy
            # path and whether or not the filesystem can prove it later.
            effective = current_path
        return DirectoryMigration(
            outcome=outcome,
            legacy=legacy_path,
            current=current_path,
            effective=effective,
            legacy_state=inspect_legacy(legacy_path, current_path),
            rename_failure=rename_failure,
            detail=detail,
        )

    if _normalized(legacy_path) == _normalized(current_path):
        return report(DirectoryOutcome.NOTHING_TO_MIGRATE, detail="legacy and current are one path")

    # The common start: nothing to move and no unfinished move on record. It
    # costs a few stat calls and never creates the journal. The reads are not
    # one snapshot, so the answer only counts when no migrator can have been
    # at work in between: the current path is read before the legacy one, no
    # journal exists, and the legacy path still looks the same afterwards.
    current_exists = _exists(current_path)
    state = inspect_legacy(legacy_path, current_path)
    settled = _settled_outcome(state, current_exists)
    quiet = not os.path.lexists(journal_path)
    if settled is not None and quiet and inspect_legacy(legacy_path, current_path) is state:
        return report(settled)

    try:
        lock = _acquire(journal_path, wait_seconds)
    except OSError as exc:
        log.warning("Migration journal %s is unavailable (%s).", journal_path, exc)
        return report(DirectoryOutcome.LOCK_UNAVAILABLE, detail=f"{type(exc).__name__}: {exc}")
    if lock is None:
        # Whatever was seen above was seen while another migrator was at work,
        # so it is not reported as settled.
        return report(DirectoryOutcome.LOCK_BUSY)

    # An exception that escapes the locked pass is treated like a crash: the
    # journal stays, so the next call can finish what this one started.
    remove_journal = False
    try:
        step = _migrate_locked(lock, legacy_path, current_path, rename, make_link, retry_delays)
        remove_journal = step.remove_journal
    finally:
        lock.release(remove=remove_journal)
    return report(step.outcome, rename_failure=step.rename_failure, detail=step.detail)


# ----------------------------------------------------------------------
# Keyring migration
# ----------------------------------------------------------------------


class KeyringBackend(Protocol):
    """The credential-store calls the migration needs.

    The names match the ``keyring`` package and the arguments are positional,
    so that module, one of its backends, or a wrapper around either satisfies
    it as is. ``delete_password`` is never called here (legacy entries are the
    way back); it is part of the shape because the uninstall path clears both
    services through it.
    """

    def get_password(self, service: str, key: str, /) -> str | None: ...

    def set_password(self, service: str, key: str, value: str, /) -> None: ...

    def delete_password(self, service: str, key: str, /) -> None: ...


class KeyringOutcome(enum.Enum):
    """What :func:`migrate_keyring` did."""

    # Every present legacy entry is now reachable under the current service.
    MIGRATED = "migrated"
    # The marker was already there; nothing else was read.
    ALREADY_MIGRATED = "already_migrated"
    # Some entries could not be read, written or read back. No marker: the
    # next call retries them, and skips the ones that made it.
    INCOMPLETE = "incomplete"
    # The credential store did not answer at all. Nothing was changed.
    UNAVAILABLE = "unavailable"
    # Legacy and current are the same service.
    NOT_NEEDED = "not_needed"


@dataclass(frozen=True, slots=True)
class KeyringMigration:
    """The full account of one :func:`migrate_keyring` call. Key names only."""

    outcome: KeyringOutcome
    legacy_service: str
    current_service: str
    # Copied from the legacy service by this call.
    copied: tuple[str, ...] = ()
    # Left alone because the current service already had a value.
    kept: tuple[str, ...] = ()
    # Could not be read, written or read back.
    failed: tuple[str, ...] = ()
    marker_written: bool = False


def keyring_marker_key(legacy_service: str) -> str:
    """The entry in the current service that says ``legacy_service`` was migrated."""
    return f"__migrated_from__{legacy_service}"


def migrate_keyring(
    backend: KeyringBackend,
    *,
    legacy_service: str,
    current_service: str,
    keys: Iterable[str],
) -> KeyringMigration:
    """Copy every known legacy credential to the current service, once.

    ``keys`` is the complete list of entries the product ever stores; an entry
    that is not listed is not migrated, because a credential store cannot be
    enumerated portably. A value already present under the current service is
    never overwritten, and no legacy entry is deleted. Every copy is read back,
    so a store that accepts a write and keeps nothing is not taken for done.

    Error texts from the store never reach a log line or the result: a backend
    may quote the value it refused.
    """

    def report(outcome: KeyringOutcome) -> KeyringMigration:
        return KeyringMigration(outcome, legacy_service, current_service)

    if legacy_service == current_service:
        return report(KeyringOutcome.NOT_NEEDED)
    marker = keyring_marker_key(legacy_service)
    try:
        if backend.get_password(current_service, marker):
            return report(KeyringOutcome.ALREADY_MIGRATED)
    except Exception as exc:  # noqa: BLE001 - backend error types are not importable here
        log.warning(
            "Credential store unavailable (%s); keys stay under %s.",
            type(exc).__name__,
            legacy_service,
        )
        return report(KeyringOutcome.UNAVAILABLE)

    copied: list[str] = []
    kept: list[str] = []
    failed: list[str] = []
    for key in dict.fromkeys(keys):
        try:
            value = backend.get_password(legacy_service, key)
            if not value:
                continue
            if backend.get_password(current_service, key):
                kept.append(key)
                continue
            backend.set_password(current_service, key, value)
            persisted = backend.get_password(current_service, key) == value
        except Exception as exc:  # noqa: BLE001 - backend error types are not importable here
            log.warning("Credential %s was not migrated (%s).", key, type(exc).__name__)
            failed.append(key)
            continue
        if persisted:
            copied.append(key)
        else:
            log.warning("Credential %s did not persist under %s.", key, current_service)
            failed.append(key)

    marker_written = False
    if not failed:
        try:
            backend.set_password(current_service, marker, "1")
            marker_written = bool(backend.get_password(current_service, marker))
        except Exception as exc:  # noqa: BLE001 - backend error types are not importable here
            # Harmless: the next call finds every value in place and only
            # writes the marker.
            log.warning("Credential migration marker was not written (%s).", type(exc).__name__)
    return KeyringMigration(
        outcome=KeyringOutcome.MIGRATED if marker_written else KeyringOutcome.INCOMPLETE,
        legacy_service=legacy_service,
        current_service=current_service,
        copied=tuple(copied),
        kept=tuple(kept),
        failed=tuple(failed),
        marker_written=marker_written,
    )


__all__ = [
    "DirectoryMigration",
    "DirectoryOutcome",
    "KeyringBackend",
    "KeyringMigration",
    "KeyringOutcome",
    "LegacyState",
    "RenameFailure",
    "TRANSIENT_RETRY_DELAYS",
    "create_directory_link",
    "default_lock_path",
    "inspect_legacy",
    "keyring_marker_key",
    "migrate_directory",
    "migrate_keyring",
    "resolve_directory",
]
