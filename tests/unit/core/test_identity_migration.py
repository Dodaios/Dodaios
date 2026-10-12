"""``jarvis.core.identity_migration`` — moving an install to a new name without losing it.

Why this file matters: the engine is what will carry a real person's data
directory, install directory and stored credentials from one product name to
the next. Every failure mode here is somebody's memory, settings or API keys
appearing to vanish. The tests run on the real filesystem with a synthetic name
pair, and inject a failure only where the operating system cannot be made to
produce it on demand (a cross-volume rename, a crash between two steps).
"""

from __future__ import annotations

import ast
import errno
import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from jarvis.core import identity_migration as engine
from jarvis.core.identity_migration import (
    DirectoryOutcome,
    KeyringOutcome,
    LegacyState,
    RenameFailure,
    create_directory_link,
    default_lock_path,
    inspect_legacy,
    keyring_marker_key,
    migrate_directory,
    migrate_keyring,
    resolve_directory,
)
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS
from tests.fakes.fake_keyring_backend import FakeKeyringBackend

MODULE_PATH = Path(engine.__file__).resolve()

# A synthetic pair. The legacy name carries a space on purpose: real install
# and data directories have had one.
LEGACY_NAME = "Old Name"
CURRENT_NAME = "NewName"

_FILES = {
    "settings.toml": b"voice = true\n",
    "data/store.db": b"\x00\x01binary\xff",
    "data/nested/deep/note.txt": b"caf\xc3\xa9 \xe2\x98\x83",
}


def _populate(directory: Path) -> dict[str, bytes]:
    for relative, content in _FILES.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(_FILES)


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _names(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


def _remove_link(link: Path) -> None:
    """Drop a link, never its target: a symlink unlinks, a junction is an rmdir."""
    try:
        os.unlink(link)
    except OSError:
        os.rmdir(link)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """The parent both directories live in, like a user profile."""
    root = tmp_path / "home"
    root.mkdir()
    return root


@pytest.fixture
def legacy(home: Path) -> Path:
    return home / LEGACY_NAME


@pytest.fixture
def current(home: Path) -> Path:
    return home / CURRENT_NAME


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
    _remove_link(link)


@pytest.fixture
def symlinkable(tmp_path: Path) -> None:
    """Skip where the OS refuses an unprivileged directory symlink."""
    target = tmp_path / "symlink-probe-target"
    link = tmp_path / "symlink-probe"
    target.mkdir()
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"this OS account cannot create a directory symlink: {exc}")
    _remove_link(link)


@pytest.fixture
def junction() -> Callable[[Path, Path], None]:
    """The raw junction call, skipped where the platform has none."""
    try:
        import _winapi

        create = _winapi.CreateJunction  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        pytest.skip("this platform has no directory junctions")

    def make(link: Path, target: Path) -> None:
        create(str(target), str(link))

    return make


# ----------------------------------------------------------------------
# Resolution rule
# ----------------------------------------------------------------------


def test_absent_legacy_resolves_to_current(legacy: Path, current: Path) -> None:
    assert inspect_legacy(legacy, current) is LegacyState.ABSENT
    assert resolve_directory(current, [legacy]) == current


def test_no_legacy_paths_resolves_to_current(current: Path) -> None:
    assert resolve_directory(current) == current


@pytest.mark.parametrize("current_exists", [False, True])
def test_real_legacy_directory_wins(legacy: Path, current: Path, current_exists: bool) -> None:
    _populate(legacy)
    if current_exists:
        _populate(current)

    assert inspect_legacy(legacy, current) is LegacyState.REAL_DIRECTORY
    assert resolve_directory(current, [legacy]) == legacy


def test_a_file_at_the_legacy_path_does_not_win(legacy: Path, current: Path) -> None:
    legacy.write_text("not a directory", encoding="utf-8")

    assert inspect_legacy(legacy, current) is LegacyState.NOT_A_DIRECTORY
    assert resolve_directory(current, [legacy]) == current


@pytest.mark.usefixtures("linkable")
def test_link_to_current_resolves_to_current(legacy: Path, current: Path) -> None:
    _populate(current)
    create_directory_link(legacy, current)

    assert inspect_legacy(legacy, current) is LegacyState.LINK_TO_CURRENT
    assert resolve_directory(current, [legacy]) == current


@pytest.mark.usefixtures("linkable")
def test_link_to_a_not_yet_created_current_resolves_to_current(legacy: Path, current: Path) -> None:
    current.mkdir()
    create_directory_link(legacy, current)
    current.rmdir()

    assert inspect_legacy(legacy, current) is LegacyState.LINK_TO_CURRENT
    assert resolve_directory(current, [legacy]) == current


@pytest.mark.usefixtures("linkable")
def test_dangling_link_elsewhere_resolves_to_current(
    home: Path, legacy: Path, current: Path
) -> None:
    gone = home / "gone"
    gone.mkdir()
    create_directory_link(legacy, gone)
    gone.rmdir()

    assert inspect_legacy(legacy, current) is LegacyState.DANGLING_LINK
    assert resolve_directory(current, [legacy]) == current


@pytest.mark.usefixtures("linkable")
def test_users_own_link_to_another_directory_wins(home: Path, legacy: Path, current: Path) -> None:
    """A redirect the user set up themselves is where their data is reached."""
    elsewhere = home / "second-disk"
    _populate(elsewhere)
    create_directory_link(legacy, elsewhere)

    assert inspect_legacy(legacy, current) is LegacyState.FOREIGN_LINK
    assert resolve_directory(current, [legacy]) == legacy


@pytest.mark.usefixtures("symlinkable")
@pytest.mark.parametrize("relative", [False, True])
def test_a_symlink_to_current_is_recognized(legacy: Path, current: Path, relative: bool) -> None:
    current.mkdir()
    os.symlink(CURRENT_NAME if relative else current, legacy, target_is_directory=True)

    assert inspect_legacy(legacy, current) is LegacyState.LINK_TO_CURRENT
    assert resolve_directory(current, [legacy]) == current


def test_a_junction_to_current_is_recognized(
    legacy: Path, current: Path, junction: Callable[[Path, Path], None]
) -> None:
    current.mkdir()
    junction(legacy, current)

    assert inspect_legacy(legacy, current) is LegacyState.LINK_TO_CURRENT
    assert resolve_directory(current, [legacy]) == current


@pytest.mark.usefixtures("linkable")
def test_legacy_paths_are_tried_in_order(home: Path, current: Path) -> None:
    oldest = home / "Oldest"
    older = home / "Older"
    absent = home / "Never Existed"
    _populate(current)
    create_directory_link(older, current)

    assert resolve_directory(current, [absent, older]) == current
    _populate(oldest)
    assert resolve_directory(current, [absent, older, oldest]) == oldest
    _remove_link(older)
    older.mkdir()
    assert resolve_directory(current, [absent, older, oldest]) == older


def test_resolving_changes_nothing_on_disk(home: Path, legacy: Path, current: Path) -> None:
    _populate(legacy)
    before = (_names(home), _snapshot(legacy))

    resolve_directory(current, [legacy])
    inspect_legacy(legacy, current)

    assert (_names(home), _snapshot(legacy)) == before


# ----------------------------------------------------------------------
# Directory migration: the move
# ----------------------------------------------------------------------


@pytest.mark.usefixtures("linkable")
def test_moves_the_directory_and_leaves_a_link(home: Path, legacy: Path, current: Path) -> None:
    files = _populate(legacy)

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.MIGRATED
    assert result.legacy == legacy
    assert result.current == current
    assert result.effective == current
    assert result.legacy_state is LegacyState.LINK_TO_CURRENT
    assert result.rename_failure is None
    assert _snapshot(current) == files
    assert not os.path.islink(current) and current.is_dir()
    assert os.path.samefile(legacy, current)
    # Nothing else is left behind: no journal, no lock file, no copy.
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


@pytest.mark.usefixtures("linkable")
def test_second_run_does_nothing(home: Path, legacy: Path, current: Path) -> None:
    files = _populate(legacy)
    migrate_directory(legacy, current)
    renames: list[tuple[Path, Path]] = []

    result = migrate_directory(
        legacy, current, rename=lambda source, target: renames.append((source, target))
    )

    assert result.outcome is DirectoryOutcome.ALREADY_LINKED
    assert result.effective == current
    assert renames == []
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


@pytest.mark.usefixtures("linkable")
def test_old_and_new_path_see_the_same_files(legacy: Path, current: Path) -> None:
    _populate(legacy)
    migrate_directory(legacy, current)

    # Code that still spells the old name writes; the new name reads it.
    (legacy / "data" / "written-through-old.txt").write_text("old path", encoding="utf-8")
    assert (current / "data" / "written-through-old.txt").read_text(encoding="utf-8") == "old path"
    # And the other way round, including a directory created through the link.
    (current / "fresh").mkdir()
    (current / "fresh" / "written-through-new.txt").write_text("new path", encoding="utf-8")
    assert (legacy / "fresh" / "written-through-new.txt").read_text(encoding="utf-8") == "new path"
    assert _snapshot(legacy) == _snapshot(current)


def test_no_legacy_directory_is_a_no_op(home: Path, legacy: Path, current: Path) -> None:
    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.NOTHING_TO_MIGRATE
    assert result.effective == current
    assert _names(home) == []


def test_a_fresh_install_is_not_mistaken_for_an_interrupted_move(
    home: Path, legacy: Path, current: Path
) -> None:
    """No legacy directory and no journal: no link may appear at the old name."""
    files = _populate(current)

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.NOTHING_TO_MIGRATE
    assert _names(home) == [CURRENT_NAME]
    assert _snapshot(current) == files


def test_identical_paths_are_a_no_op(home: Path, current: Path) -> None:
    files = _populate(current)

    result = migrate_directory(current, home / "." / CURRENT_NAME)

    assert result.outcome is DirectoryOutcome.NOTHING_TO_MIGRATE
    assert _snapshot(current) == files
    assert _names(home) == [CURRENT_NAME]


# ----------------------------------------------------------------------
# Directory migration: never merge, never overwrite
# ----------------------------------------------------------------------


@pytest.mark.parametrize("current_kind", ["populated", "empty", "file"])
def test_both_existing_is_left_alone(
    home: Path, legacy: Path, current: Path, current_kind: str
) -> None:
    files = _populate(legacy)
    if current_kind == "populated":
        current.mkdir()
        (current / "other.txt").write_text("belongs to the new install", encoding="utf-8")
    elif current_kind == "empty":
        current.mkdir()
    else:
        current.write_text("a file", encoding="utf-8")
    current_before = _snapshot(current) if current.is_dir() else current.read_bytes()
    renames: list[tuple[Path, Path]] = []

    result = migrate_directory(
        legacy, current, rename=lambda source, target: renames.append((source, target))
    )

    assert result.outcome is DirectoryOutcome.BOTH_EXIST
    assert result.effective == legacy
    assert result.legacy_state is LegacyState.REAL_DIRECTORY
    assert renames == []
    assert _snapshot(legacy) == files
    assert (_snapshot(current) if current.is_dir() else current.read_bytes()) == current_before
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


@pytest.mark.usefixtures("linkable")
def test_users_own_link_is_not_migrated(home: Path, legacy: Path, current: Path) -> None:
    elsewhere = home / "second-disk"
    files = _populate(elsewhere)
    create_directory_link(legacy, elsewhere)

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.LEGACY_NOT_A_DIRECTORY
    assert result.legacy_state is LegacyState.FOREIGN_LINK
    assert result.effective == legacy
    assert not current.exists()
    assert os.path.samefile(legacy, elsewhere)
    assert _snapshot(elsewhere) == files


def test_a_file_at_the_legacy_path_is_not_migrated(legacy: Path, current: Path) -> None:
    legacy.write_text("not a directory", encoding="utf-8")

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.LEGACY_NOT_A_DIRECTORY
    assert result.effective == current
    assert legacy.read_text(encoding="utf-8") == "not a directory"
    assert not current.exists()


def _hide_from_lstat(monkeypatch: pytest.MonkeyPatch, hidden: Path) -> None:
    """Make one path uninspectable, the way a denied or failing volume does."""
    real_lstat = os.lstat

    def lstat(path: str | os.PathLike[str], *args: object, **kwargs: object) -> os.stat_result:
        if os.path.abspath(path) == os.path.abspath(hidden):
            raise PermissionError(errno.EACCES, "access denied", os.fspath(path))
        return real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(engine.os, "lstat", lstat)


def test_an_uninspectable_legacy_path_is_not_taken_for_absent(
    monkeypatch: pytest.MonkeyPatch, home: Path, legacy: Path, current: Path
) -> None:
    """Starting on an empty directory behind a momentary error would split the install."""
    files = _populate(legacy)
    _hide_from_lstat(monkeypatch, legacy)

    assert inspect_legacy(legacy, current) is LegacyState.UNREADABLE
    assert resolve_directory(current, [legacy]) == legacy
    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.LEGACY_UNREADABLE
    assert result.effective == legacy
    monkeypatch.undo()
    assert _snapshot(legacy) == files
    assert _names(home) == [LEGACY_NAME]


def test_an_uninspectable_current_path_counts_as_occupied(
    monkeypatch: pytest.MonkeyPatch, home: Path, legacy: Path, current: Path
) -> None:
    files = _populate(legacy)
    _hide_from_lstat(monkeypatch, current)
    renames: list[tuple[Path, Path]] = []

    result = migrate_directory(
        legacy, current, rename=lambda source, target: renames.append((source, target))
    )

    assert result.outcome is DirectoryOutcome.BOTH_EXIST
    assert result.effective == legacy
    assert renames == []
    monkeypatch.undo()
    assert _snapshot(legacy) == files
    assert _names(home) == [LEGACY_NAME]


# ----------------------------------------------------------------------
# Directory migration: a refused rename
# ----------------------------------------------------------------------


def _refuse(error: OSError) -> Callable[[Path, Path], None]:
    def rename(source: Path, target: Path) -> None:
        raise error

    return rename


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermissionError(errno.EACCES, "a file inside is open"), RenameFailure.IN_USE_OR_DENIED),
        (OSError(errno.EBUSY, "device or resource busy"), RenameFailure.IN_USE_OR_DENIED),
        (OSError(errno.EXDEV, "target is on another volume"), RenameFailure.CROSS_DEVICE),
        (FileExistsError(errno.EEXIST, "target appeared"), RenameFailure.DESTINATION_EXISTS),
        (OSError(errno.ENOTEMPTY, "target not empty"), RenameFailure.DESTINATION_EXISTS),
        (OSError(errno.EIO, "input/output error"), RenameFailure.OTHER),
    ],
)
def test_refused_rename_leaves_everything_untouched(
    home: Path, legacy: Path, current: Path, error: OSError, expected: RenameFailure
) -> None:
    files = _populate(legacy)

    result = migrate_directory(legacy, current, rename=_refuse(error), retry_delays=())

    assert result.outcome is DirectoryOutcome.RENAME_FAILED
    assert result.rename_failure is expected
    assert result.detail
    # The app keeps running at the legacy location: nothing was copied, and
    # nothing (not even the journal) is left next to it.
    assert result.effective == legacy
    assert result.legacy_state is LegacyState.REAL_DIRECTORY
    assert _snapshot(legacy) == files
    assert _names(home) == [LEGACY_NAME]


class _FlakyRename:
    """A real rename that is refused a number of times first."""

    def __init__(self, refusals: int, error: OSError) -> None:
        self.refusals = refusals
        self.error = error
        self.calls = 0

    def __call__(self, source: Path, target: Path) -> None:
        self.calls += 1
        if self.calls <= self.refusals:
            raise self.error
        os.rename(source, target)


@pytest.mark.usefixtures("linkable")
def test_a_momentary_refusal_is_retried_within_the_same_call(
    home: Path, legacy: Path, current: Path
) -> None:
    """A scanner looking at freshly written files lets go within moments."""
    files = _populate(legacy)
    rename = _FlakyRename(2, PermissionError(errno.EACCES, "a scanner has it open"))

    result = migrate_directory(legacy, current, rename=rename, retry_delays=(0.0, 0.0))

    assert result.outcome is DirectoryOutcome.MIGRATED
    assert rename.calls == 3
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


def test_a_lasting_refusal_gives_up_after_the_retries(legacy: Path, current: Path) -> None:
    _populate(legacy)
    rename = _FlakyRename(99, PermissionError(errno.EACCES, "a file inside is open"))

    result = migrate_directory(legacy, current, rename=rename, retry_delays=(0.0, 0.0))

    assert result.outcome is DirectoryOutcome.RENAME_FAILED
    assert rename.calls == 3


def test_another_volume_is_not_retried(legacy: Path, current: Path) -> None:
    _populate(legacy)
    rename = _FlakyRename(99, OSError(errno.EXDEV, "target is on another volume"))

    result = migrate_directory(legacy, current, rename=rename)

    assert result.rename_failure is RenameFailure.CROSS_DEVICE
    assert rename.calls == 1


@pytest.mark.usefixtures("linkable")
def test_a_refused_rename_is_retried_on_the_next_start(
    home: Path, legacy: Path, current: Path
) -> None:
    files = _populate(legacy)
    refused = migrate_directory(
        legacy,
        current,
        rename=_refuse(PermissionError(errno.EACCES, "a file inside is open")),
        retry_delays=(),
    )

    retried = migrate_directory(legacy, current)

    assert refused.outcome is DirectoryOutcome.RENAME_FAILED
    assert retried.outcome is DirectoryOutcome.MIGRATED
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


@pytest.mark.usefixtures("linkable")
def test_an_open_file_refuses_the_real_rename_where_the_os_enforces_it(
    tmp_path: Path, home: Path, legacy: Path, current: Path
) -> None:
    probe = tmp_path / "open-file-probe"
    probe.mkdir()
    (probe / "held.txt").write_text("x", encoding="utf-8")
    with (probe / "held.txt").open(encoding="utf-8"):
        try:
            os.rename(probe, tmp_path / "open-file-probe-moved")
        except OSError:
            pass  # This OS refuses to rename a directory with an open file: test it.
        else:
            pytest.skip("this OS renames a directory while a file inside is open")
    files = _populate(legacy)

    with (legacy / "settings.toml").open("rb"):
        held = migrate_directory(legacy, current, retry_delays=(0.0,))
    released = migrate_directory(legacy, current)

    assert held.outcome is DirectoryOutcome.RENAME_FAILED
    assert held.rename_failure is RenameFailure.IN_USE_OR_DENIED
    assert held.effective == legacy
    assert released.outcome is DirectoryOutcome.MIGRATED
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


# ----------------------------------------------------------------------
# Directory migration: the link step and crash recovery
# ----------------------------------------------------------------------

_CHILD = textwrap.dedent(
    """
    import importlib.util
    import os
    import sys
    import time

    module_path, mode, legacy, current, go = sys.argv[1:6]
    # Loaded by path and deliberately not registered in sys.modules: the way a
    # frozen runtime hook has to load it, before the package can be imported.
    spec = importlib.util.spec_from_file_location("identity_migration_by_path", module_path)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    if any(name == "jarvis" or name.startswith("jarvis.") for name in sys.modules):
        sys.exit("the engine imported the jarvis package")

    def crash(source, target):
        os._exit(70)

    def rename_then_crash(source, target):
        os.rename(source, target)
        os._exit(70)

    kwargs = {}
    if mode == "crash-in-rename":
        kwargs["rename"] = crash
    elif mode == "crash-after-rename":
        kwargs["rename"] = rename_then_crash
    elif mode == "crash-in-link":
        kwargs["make_link"] = crash
    elif mode == "race":
        open(f"{go}.ready.{os.getpid()}", "w").close()
        while not os.path.exists(go):
            time.sleep(0.001)
    result = engine.migrate_directory(legacy, current, **kwargs)
    print(result.outcome.value)
    """
)


@pytest.fixture
def child(tmp_path: Path) -> Iterator[Callable[..., subprocess.Popen[str]]]:
    """Start a separate Python process that runs one migration."""
    script = tmp_path / "migrate_child.py"
    script.write_text(_CHILD, encoding="utf-8")
    started: list[subprocess.Popen[str]] = []

    def start(mode: str, legacy: Path, current: Path, go: Path | None = None) -> subprocess.Popen:
        process = subprocess.Popen(
            # -I: no PYTHONPATH and no working directory on sys.path, so the
            # child cannot reach the jarvis package even by accident.
            [
                sys.executable,
                "-I",
                str(script),
                str(MODULE_PATH),
                mode,
                str(legacy),
                str(current),
                str(go or tmp_path / "go"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
        started.append(process)
        return process

    yield start
    for process in started:
        if process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.usefixtures("linkable")
def test_crash_between_rename_and_link_is_finished_on_the_next_start(
    home: Path, legacy: Path, current: Path, child: Callable[..., subprocess.Popen[str]]
) -> None:
    files = _populate(legacy)

    crashed = child("crash-in-link", legacy, current)
    _, stderr = crashed.communicate(timeout=60)

    assert crashed.returncode == 70, stderr
    # The rename is done, the link is not. That alone is a usable state:
    assert not os.path.lexists(legacy)
    assert _snapshot(current) == files
    assert resolve_directory(current, [legacy]) == current
    assert default_lock_path(current).exists()

    recovered = migrate_directory(legacy, current)

    assert recovered.outcome is DirectoryOutcome.LINK_RESTORED
    assert recovered.effective == current
    assert os.path.samefile(legacy, current)
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])
    assert migrate_directory(legacy, current).outcome is DirectoryOutcome.ALREADY_LINKED


@pytest.mark.usefixtures("linkable")
def test_crash_before_the_rename_just_migrates_on_the_next_start(
    home: Path, legacy: Path, current: Path, child: Callable[..., subprocess.Popen[str]]
) -> None:
    files = _populate(legacy)

    crashed = child("crash-in-rename", legacy, current)
    _, stderr = crashed.communicate(timeout=60)

    assert crashed.returncode == 70, stderr
    assert _snapshot(legacy) == files
    assert resolve_directory(current, [legacy]) == legacy

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.MIGRATED
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


def test_crash_before_the_rename_is_recorded_leaves_the_data_without_a_link(
    home: Path, legacy: Path, current: Path, child: Callable[..., subprocess.Popen[str]]
) -> None:
    """The one instant in which a finished rename cannot be told from none.

    The journal learns of the rename right after it. A crash in between leaves
    the data at the current path with no link, and it stays that way: guessing
    here would also put a link beside every fresh install that follows an
    interrupted attempt.
    """
    files = _populate(legacy)
    crashed = child("crash-after-rename", legacy, current)
    crashed.communicate(timeout=60)
    assert crashed.returncode == 70
    assert resolve_directory(current, [legacy]) == current

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.NOTHING_TO_MIGRATE
    assert result.effective == current
    assert _snapshot(current) == files
    assert _names(home) == [CURRENT_NAME]


def test_a_journal_left_before_the_rename_never_links_a_fresh_install(
    home: Path, legacy: Path, current: Path, child: Callable[..., subprocess.Popen[str]]
) -> None:
    """The journal names the pair, but the directory it described never moved."""
    _populate(legacy)
    crashed = child("crash-in-rename", legacy, current)
    crashed.communicate(timeout=60)
    assert default_lock_path(current).exists()
    # The user removes the old installation and installs afresh.
    shutil.rmtree(legacy)
    fresh = _populate(current)

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.NOTHING_TO_MIGRATE
    assert not os.path.lexists(legacy)
    assert _snapshot(current) == fresh
    assert _names(home) == [CURRENT_NAME]


@pytest.mark.parametrize("legacy_exists", [False, True])
def test_a_garbled_journal_is_ignored(
    home: Path, legacy: Path, current: Path, legacy_exists: bool
) -> None:
    default_lock_path(current).write_bytes(b"\xff\x00 not json {")
    files = _populate(legacy if legacy_exists else current)
    links: list[tuple[Path, Path]] = []

    result = migrate_directory(
        legacy, current, make_link=lambda link, target: links.append((link, target))
    )

    if legacy_exists:
        # The move itself goes ahead; only the recording link maker stops it
        # from being called MIGRATED.
        assert result.outcome is DirectoryOutcome.MIGRATED_WITHOUT_LINK
        assert links == [(legacy, current)]
    else:
        assert result.outcome is DirectoryOutcome.NOTHING_TO_MIGRATE
        assert links == []
        assert _names(home) == [CURRENT_NAME]
    assert result.effective == current
    assert _snapshot(current) == files


@pytest.mark.usefixtures("linkable")
def test_a_link_never_replaces_an_existing_path(home: Path, legacy: Path, current: Path) -> None:
    files = _populate(legacy)
    current.mkdir()

    with pytest.raises(FileExistsError):
        create_directory_link(legacy, current)

    assert _snapshot(legacy) == files
    assert inspect_legacy(legacy, current) is LegacyState.REAL_DIRECTORY
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


def test_a_leftover_staging_junction_does_not_block_the_link(
    home: Path, legacy: Path, current: Path, junction: Callable[[Path, Path], None]
) -> None:
    """A crash while the junction was being built leaves one under its staging name."""
    files = _populate(legacy)
    stale_target = home / "stale-target"
    stale_target.mkdir()
    junction(home / f".{LEGACY_NAME}.identity-link", stale_target)

    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.MIGRATED
    assert os.path.samefile(legacy, current)
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME, "stale-target"])


@pytest.mark.usefixtures("linkable")
def test_a_refused_link_is_a_valid_end_state_and_is_retried(
    home: Path, legacy: Path, current: Path
) -> None:
    files = _populate(legacy)

    def refuse_link(link: Path, target: Path) -> None:
        raise PermissionError(errno.EPERM, "links are not permitted here")

    moved = migrate_directory(legacy, current, make_link=refuse_link, retry_delays=())

    assert moved.outcome is DirectoryOutcome.MIGRATED_WITHOUT_LINK
    assert moved.effective == current
    assert moved.legacy_state is LegacyState.ABSENT
    assert "links are not permitted here" in moved.detail
    assert _snapshot(current) == files
    assert not os.path.lexists(legacy)

    retried = migrate_directory(legacy, current)

    assert retried.outcome is DirectoryOutcome.LINK_RESTORED
    assert os.path.samefile(legacy, current)
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


@pytest.mark.usefixtures("linkable")
def test_an_empty_directory_recreated_at_the_old_path_makes_way(
    home: Path, legacy: Path, current: Path
) -> None:
    """A process that resolved just before the rename may mkdir the old path."""
    files = _populate(legacy)
    calls = 0

    def link_after_a_late_mkdir(link: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            link.mkdir()
        create_directory_link(link, target)

    result = migrate_directory(legacy, current, make_link=link_after_a_late_mkdir)

    assert result.outcome is DirectoryOutcome.MIGRATED
    assert calls == 2
    assert os.path.samefile(legacy, current)
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


@pytest.mark.usefixtures("linkable")
def test_data_recreated_at_the_old_path_is_never_removed(
    home: Path, legacy: Path, current: Path
) -> None:
    files = _populate(legacy)

    def link_after_a_late_write(link: Path, target: Path) -> None:
        link.mkdir(exist_ok=True)
        (link / "late.txt").write_text("written by another process", encoding="utf-8")
        create_directory_link(link, target)

    moved = migrate_directory(legacy, current, make_link=link_after_a_late_write)

    assert moved.outcome is DirectoryOutcome.MIGRATED_WITHOUT_LINK
    # The newer directory must not hide the moved data, in this call or in any
    # later one, for the migrator or for a process that only resolves.
    assert moved.effective == current
    for _ in range(2):
        again = migrate_directory(legacy, current)
        assert again.outcome is DirectoryOutcome.LEGACY_RECREATED
        assert again.effective == current
        assert again.legacy_state is LegacyState.REAL_DIRECTORY
        assert resolve_directory(current, [legacy]) == current
    assert _snapshot(legacy) == {"late.txt": b"written by another process"}
    assert _snapshot(current) == files
    assert default_lock_path(current).exists()


def test_a_legacy_directory_beside_an_unrelated_current_still_wins(
    legacy: Path, current: Path
) -> None:
    """Only the journal's proof of a move lets the current directory outrank it."""
    files = _populate(legacy)
    current.mkdir()
    default_lock_path(current).write_text(
        json.dumps(
            {
                "legacy": str(legacy),
                "current": str(current),
                "device": 1,
                "inode": 1,
                "renamed": True,
            }
        ),
        encoding="utf-8",
    )

    assert resolve_directory(current, [legacy]) == legacy
    result = migrate_directory(legacy, current)

    assert result.outcome is DirectoryOutcome.BOTH_EXIST
    assert result.effective == legacy
    assert _snapshot(legacy) == files
    assert not default_lock_path(current).exists()


@pytest.mark.usefixtures("linkable")
def test_a_journal_for_another_legacy_path_is_that_migrations_to_finish(
    home: Path, legacy: Path, current: Path
) -> None:
    other_legacy = home / "Other Old Name"
    _populate(current)
    moved = os.lstat(current)
    journal = default_lock_path(current)
    journal.write_text(
        json.dumps(
            {
                "legacy": str(other_legacy),
                "current": str(current),
                "device": moved.st_dev,
                "inode": moved.st_ino,
                "renamed": True,
            }
        ),
        encoding="utf-8",
    )

    unrelated = migrate_directory(legacy, current)

    assert unrelated.outcome is DirectoryOutcome.NOTHING_TO_MIGRATE
    assert not os.path.lexists(legacy)
    assert journal.exists()

    owner = migrate_directory(other_legacy, current)

    assert owner.outcome is DirectoryOutcome.LINK_RESTORED
    assert os.path.samefile(other_legacy, current)
    assert not journal.exists()


# ----------------------------------------------------------------------
# Directory migration: one migrator at a time
# ----------------------------------------------------------------------


def test_the_journal_sits_beside_the_current_directory(home: Path, current: Path) -> None:
    journal = default_lock_path(current)

    assert journal.parent == home
    assert journal.name == f".{CURRENT_NAME}.identity-migration"
    assert default_lock_path(home / ".new-data").name == ".new-data.identity-migration"


def _assert_tidy_after_the_next_start(home: Path, legacy: Path, current: Path) -> None:
    """A contender that lost the lock can keep the winner from deleting the journal.

    Windows refuses to delete a file another process still has open. The file
    that stays is empty, and the next start removes it.
    """
    assert migrate_directory(legacy, current).outcome is DirectoryOutcome.ALREADY_LINKED
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


class _HeldRename:
    """A real rename that waits inside the locked section until released.

    It counts renames that happened, not attempts: under load a scanner can
    refuse the first try for a moment, and the engine then tries again.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.renamed = 0

    def __call__(self, source: Path, target: Path) -> None:
        self.entered.set()
        assert self.release.wait(timeout=30)
        os.rename(source, target)
        self.renamed += 1


@pytest.mark.usefixtures("linkable")
def test_a_second_migrator_only_resolves_while_the_first_is_moving(
    home: Path, legacy: Path, current: Path
) -> None:
    files = _populate(legacy)
    held = _HeldRename()
    outcomes: list[DirectoryOutcome] = []
    first = threading.Thread(
        target=lambda: outcomes.append(migrate_directory(legacy, current, rename=held).outcome)
    )
    first.start()
    try:
        assert held.entered.wait(timeout=30)
        second_renames: list[tuple[Path, Path]] = []

        second = migrate_directory(
            legacy, current, rename=lambda source, target: second_renames.append((source, target))
        )

        assert second.outcome is DirectoryOutcome.LOCK_BUSY
        assert second.effective == legacy
        assert second_renames == []
    finally:
        held.release.set()
        first.join(timeout=30)

    assert outcomes == [DirectoryOutcome.MIGRATED]
    assert held.renamed == 1
    assert _snapshot(current) == files
    assert _names(home) == sorted([LEGACY_NAME, CURRENT_NAME])


@pytest.mark.usefixtures("linkable")
def test_a_waiting_migrator_sees_the_finished_move(legacy: Path, current: Path) -> None:
    _populate(legacy)
    held = _HeldRename()
    outcomes: dict[str, DirectoryOutcome] = {}
    first = threading.Thread(
        target=lambda: outcomes.update(
            first=migrate_directory(legacy, current, rename=held).outcome
        )
    )
    waiter = threading.Thread(
        target=lambda: outcomes.update(
            waiter=migrate_directory(legacy, current, wait_seconds=30).outcome
        )
    )
    first.start()
    try:
        assert held.entered.wait(timeout=30)
        waiter.start()
    finally:
        held.release.set()
        first.join(timeout=30)
        waiter.join(timeout=30)

    assert outcomes == {
        "first": DirectoryOutcome.MIGRATED,
        "waiter": DirectoryOutcome.ALREADY_LINKED,
    }
    assert held.renamed == 1


@pytest.mark.usefixtures("linkable")
def test_simultaneous_threads_rename_exactly_once(home: Path, legacy: Path, current: Path) -> None:
    files = _populate(legacy)
    contenders = 8
    barrier = threading.Barrier(contenders)
    guard = threading.Lock()
    renames: list[tuple[Path, Path]] = []
    outcomes: list[DirectoryOutcome] = []

    def counting_rename(source: Path, target: Path) -> None:
        os.rename(source, target)
        with guard:
            renames.append((source, target))

    def contend() -> None:
        barrier.wait(timeout=30)
        outcome = migrate_directory(legacy, current, rename=counting_rename).outcome
        with guard:
            outcomes.append(outcome)

    threads = [threading.Thread(target=contend) for _ in range(contenders)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(outcomes) == contenders
    assert len(renames) == 1
    assert outcomes.count(DirectoryOutcome.MIGRATED) == 1
    # Everyone else either lost the lock or arrived after the move.
    assert set(outcomes) <= {
        DirectoryOutcome.MIGRATED,
        DirectoryOutcome.LOCK_BUSY,
        DirectoryOutcome.ALREADY_LINKED,
    }
    assert _snapshot(current) == files
    assert os.path.samefile(legacy, current)
    _assert_tidy_after_the_next_start(home, legacy, current)


@pytest.mark.usefixtures("linkable")
def test_simultaneous_processes_rename_exactly_once(
    tmp_path: Path,
    home: Path,
    legacy: Path,
    current: Path,
    child: Callable[..., subprocess.Popen[str]],
) -> None:
    files = _populate(legacy)
    go = tmp_path / "go"
    processes = [child("race", legacy, current, go) for _ in range(4)]
    # Every contender is up and spinning before any of them may start.
    deadline = time.monotonic() + 60
    while len(list(tmp_path.glob("go.ready.*"))) < len(processes):
        assert time.monotonic() < deadline, "the contenders did not start"
        time.sleep(0.01)

    go.write_text("go", encoding="utf-8")
    finished = [process.communicate(timeout=120) for process in processes]

    assert [process.returncode for process in processes] == [0] * len(processes), finished
    outcomes = [stdout.strip() for stdout, _ in finished]
    assert outcomes.count(DirectoryOutcome.MIGRATED.value) == 1, outcomes
    assert set(outcomes) <= {
        DirectoryOutcome.MIGRATED.value,
        DirectoryOutcome.LOCK_BUSY.value,
        DirectoryOutcome.ALREADY_LINKED.value,
    }
    assert _snapshot(current) == files
    assert os.path.samefile(legacy, current)
    _assert_tidy_after_the_next_start(home, legacy, current)


def test_an_unusable_journal_location_moves_nothing(
    home: Path, legacy: Path, current: Path
) -> None:
    files = _populate(legacy)
    blocker = home / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    renames: list[tuple[Path, Path]] = []

    result = migrate_directory(
        legacy,
        current,
        lock_path=blocker / "journal",
        rename=lambda source, target: renames.append((source, target)),
    )

    assert result.outcome is DirectoryOutcome.LOCK_UNAVAILABLE
    assert result.effective == legacy
    assert result.detail
    assert renames == []
    assert _snapshot(legacy) == files
    assert not current.exists()


# ----------------------------------------------------------------------
# Importability
# ----------------------------------------------------------------------


def test_the_engine_imports_only_the_standard_library() -> None:
    """The frozen runtime hook loads this file before the package exists."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import needs the package"
            imported.add((node.module or "").split(".")[0])

    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


def test_the_engine_is_not_wired_into_the_runtime() -> None:
    """Inert until the identity actually changes: nothing in the product imports it.

    The change that switches the persistent identifiers wires the engine in
    and deletes this test.
    """
    package = MODULE_PATH.parents[1]
    importers = [
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if path != MODULE_PATH and "identity_migration" in path.read_text(encoding="utf-8")
    ]

    assert importers == []


# ----------------------------------------------------------------------
# Keyring migration
# ----------------------------------------------------------------------

LEGACY_SERVICE = "old-name"
CURRENT_SERVICE = "new-name"
KNOWN_KEYS = ("alpha_api_key", "beta_api_key", "control_api_key", "gamma_oauth_client_id")


def _migrate(backend: FakeKeyringBackend, keys: tuple[str, ...] = KNOWN_KEYS):
    return migrate_keyring(
        backend, legacy_service=LEGACY_SERVICE, current_service=CURRENT_SERVICE, keys=keys
    )


def _backend_with(**legacy_entries: str) -> FakeKeyringBackend:
    backend = FakeKeyringBackend()
    for key, value in legacy_entries.items():
        backend.entries[(LEGACY_SERVICE, key)] = value
    return backend


def test_every_known_key_is_copied_and_the_legacy_entries_stay() -> None:
    secrets = {key: f"value-of-{key}" for key in KNOWN_KEYS}
    backend = _backend_with(**secrets)

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.MIGRATED
    assert result.copied == KNOWN_KEYS
    assert result.kept == ()
    assert result.failed == ()
    assert result.marker_written is True
    marker = keyring_marker_key(LEGACY_SERVICE)
    assert backend.service(CURRENT_SERVICE) == {**secrets, marker: "1"}
    # The way back: the legacy service is exactly as it was.
    assert backend.service(LEGACY_SERVICE) == secrets
    assert not [call for call in backend.calls if call[0] == "delete"]


def test_a_value_already_under_the_current_service_is_not_overwritten() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha", beta_api_key="legacy-beta")
    backend.entries[(CURRENT_SERVICE, "alpha_api_key")] = "newer-alpha"

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.MIGRATED
    assert result.copied == ("beta_api_key",)
    assert result.kept == ("alpha_api_key",)
    assert backend.entries[(CURRENT_SERVICE, "alpha_api_key")] == "newer-alpha"
    assert backend.entries[(CURRENT_SERVICE, "beta_api_key")] == "legacy-beta"


def test_the_marker_makes_it_run_once() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha")
    _migrate(backend)
    # After the migration the user deletes the key in the app, and an old
    # version writes a different one under the legacy name.
    del backend.entries[(CURRENT_SERVICE, "alpha_api_key")]
    backend.entries[(LEGACY_SERVICE, "beta_api_key")] = "written-later"
    backend.calls.clear()

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.ALREADY_MIGRATED
    assert result.copied == ()
    assert backend.service(CURRENT_SERVICE) == {keyring_marker_key(LEGACY_SERVICE): "1"}
    # One read of the marker and nothing else: no per-key prompt on any OS.
    assert backend.calls == [("get", CURRENT_SERVICE, keyring_marker_key(LEGACY_SERVICE))]


def test_a_key_missing_from_the_list_is_not_migrated() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha", unlisted_key="left-behind")

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.MIGRATED
    assert result.copied == ("alpha_api_key",)
    assert (CURRENT_SERVICE, "unlisted_key") not in backend.entries
    assert backend.entries[(LEGACY_SERVICE, "unlisted_key")] == "left-behind"


def test_absent_and_empty_legacy_entries_are_skipped() -> None:
    backend = _backend_with(alpha_api_key="", beta_api_key="legacy-beta")

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.MIGRATED
    assert result.copied == ("beta_api_key",)
    assert set(backend.service(CURRENT_SERVICE)) == {
        "beta_api_key",
        keyring_marker_key(LEGACY_SERVICE),
    }


def test_nothing_to_copy_still_writes_the_marker() -> None:
    backend = FakeKeyringBackend()

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.MIGRATED
    assert result.copied == ()
    assert backend.service(CURRENT_SERVICE) == {keyring_marker_key(LEGACY_SERVICE): "1"}


def test_a_duplicated_key_is_handled_once() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha")

    result = _migrate(backend, keys=("alpha_api_key", "alpha_api_key"))

    assert result.copied == ("alpha_api_key",)


def test_a_failed_key_leaves_no_marker_and_is_retried() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha", beta_api_key="legacy-beta")
    backend.fail_on.add(("set", CURRENT_SERVICE, "alpha_api_key"))

    first = _migrate(backend)

    assert first.outcome is KeyringOutcome.INCOMPLETE
    assert first.failed == ("alpha_api_key",)
    assert first.copied == ("beta_api_key",)
    assert first.marker_written is False
    assert keyring_marker_key(LEGACY_SERVICE) not in backend.service(CURRENT_SERVICE)

    backend.fail_on.clear()
    second = _migrate(backend)

    assert second.outcome is KeyringOutcome.MIGRATED
    assert second.copied == ("alpha_api_key",)
    assert second.kept == ("beta_api_key",)
    assert backend.entries[(CURRENT_SERVICE, "alpha_api_key")] == "legacy-alpha"


def test_an_unreadable_legacy_key_counts_as_failed() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha", beta_api_key="legacy-beta")
    backend.fail_on.add(("get", LEGACY_SERVICE, "alpha_api_key"))

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.INCOMPLETE
    assert result.failed == ("alpha_api_key",)
    assert result.copied == ("beta_api_key",)


def test_an_unwritten_marker_only_costs_a_second_pass() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha")
    backend.fail_on.add(("set", CURRENT_SERVICE, keyring_marker_key(LEGACY_SERVICE)))

    first = _migrate(backend)
    backend.fail_on.clear()
    second = _migrate(backend)

    assert first.outcome is KeyringOutcome.INCOMPLETE
    assert first.copied == ("alpha_api_key",)
    assert second.outcome is KeyringOutcome.MIGRATED
    assert second.copied == ()
    assert second.kept == ("alpha_api_key",)


def test_a_store_that_keeps_nothing_is_not_taken_for_done() -> None:
    backend = FakeKeyringBackend(drop_writes=True)
    backend.entries[(LEGACY_SERVICE, "alpha_api_key")] = "legacy-alpha"

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.INCOMPLETE
    assert result.failed == ("alpha_api_key",)
    assert result.copied == ()
    assert result.marker_written is False


def test_an_unwritable_marker_on_an_empty_store_is_not_taken_for_done() -> None:
    result = _migrate(FakeKeyringBackend(drop_writes=True))

    assert result.outcome is KeyringOutcome.INCOMPLETE
    assert result.marker_written is False


def test_an_unavailable_credential_store_changes_nothing() -> None:
    backend = FakeKeyringBackend(unavailable=True)
    backend.entries[(LEGACY_SERVICE, "alpha_api_key")] = "legacy-alpha"

    result = _migrate(backend)

    assert result.outcome is KeyringOutcome.UNAVAILABLE
    assert backend.entries == {(LEGACY_SERVICE, "alpha_api_key"): "legacy-alpha"}


def test_the_same_service_needs_no_migration() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha")

    result = migrate_keyring(
        backend, legacy_service=LEGACY_SERVICE, current_service=LEGACY_SERVICE, keys=KNOWN_KEYS
    )

    assert result.outcome is KeyringOutcome.NOT_NEEDED
    assert backend.calls == []


def test_each_legacy_service_has_its_own_marker() -> None:
    backend = _backend_with(alpha_api_key="legacy-alpha")
    backend.entries[("older-name", "beta_api_key")] = "older-beta"

    first = _migrate(backend)
    second = migrate_keyring(
        backend, legacy_service="older-name", current_service=CURRENT_SERVICE, keys=KNOWN_KEYS
    )

    assert first.outcome is KeyringOutcome.MIGRATED
    assert second.outcome is KeyringOutcome.MIGRATED
    assert second.copied == ("beta_api_key",)
    assert backend.entries[(CURRENT_SERVICE, "alpha_api_key")] == "legacy-alpha"
    assert backend.entries[(CURRENT_SERVICE, "beta_api_key")] == "older-beta"


def test_no_secret_value_reaches_the_result_or_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fake quotes the refused value in its error, as a real store may."""
    backend = _backend_with(alpha_api_key="sk-very-secret", beta_api_key="sk-also-secret")
    backend.fail_on.add(("set", CURRENT_SERVICE, "beta_api_key"))

    with caplog.at_level("DEBUG"):
        result = _migrate(backend)

    assert result.failed == ("beta_api_key",)
    assert "secret" not in repr(result)
    assert "secret" not in caplog.text
    assert "beta_api_key" in caplog.text
