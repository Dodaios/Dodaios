"""A workspace walk on macOS stays out of other apps' data.

Field report 2026-11-12: a workspace whose folder was ``~/Library`` was restored
at every start, its file index walked into ``Library/Containers``, and macOS
showed "would like to access data from other apps" at each launch, because it
does not remember that consent. Nothing failed, so nothing was logged; the
person just answered the same dialog again every time the app opened.

The rule lives in ``folders.consent_guarded_dirs`` and takes the home folder
and the platform as parameters, so these tests run the macOS rule on every
operating system.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from dodaios.agentic_ide import file_editing, file_index
from dodaios.agentic_ide.folders import consent_guarded_dirs


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    """An account folder with a project, another app's data and an iCloud project."""
    account = tmp_path / "account"
    (account / "code" / "app").mkdir(parents=True)
    (account / "code" / "app" / "main.py").write_text("x", encoding="utf-8")
    (account / "Library" / "Containers" / "com.apple.Notes" / "Data").mkdir(parents=True)
    (account / "Library" / "Containers" / "com.apple.Notes" / "Data" / "notes.py").write_text(
        "x", encoding="utf-8"
    )
    (account / "Library" / "Group Containers" / "group.other").mkdir(parents=True)
    (account / "Library" / "Group Containers" / "group.other" / "state.json").write_text(
        "{}", encoding="utf-8"
    )
    (account / "Library" / "Application Support" / "Tool").mkdir(parents=True)
    (account / "Library" / "Application Support" / "Tool" / "settings.json").write_text(
        "{}", encoding="utf-8"
    )
    cloud = account / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "site"
    cloud.mkdir(parents=True)
    (cloud / "index.ts").write_text("x", encoding="utf-8")
    return account


def _as_macos(home: Path) -> Callable[[str | os.PathLike[str]], frozenset[str]]:
    def guarded(root: str | os.PathLike[str]) -> frozenset[str]:
        return consent_guarded_dirs(root, home=home, platform="darwin")

    return guarded


@pytest.fixture()
def macos(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Both walkers apply the macOS rule against the fixture's account folder."""
    monkeypatch.setattr(file_index, "consent_guarded_dirs", _as_macos(home))
    monkeypatch.setattr(file_editing, "consent_guarded_dirs", _as_macos(home))
    return home


def test_the_library_is_guarded_from_the_home_folder(home: Path) -> None:
    guarded = consent_guarded_dirs(home, home=home, platform="darwin")

    assert str(home / "Library") in guarded
    assert str(home) not in guarded


def test_the_library_as_the_root_is_itself_guarded(home: Path) -> None:
    library = home / "Library"

    assert str(library) in consent_guarded_dirs(library, home=home, platform="darwin")


def test_a_root_inside_the_library_keeps_only_the_containers_guarded(home: Path) -> None:
    cloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "site"
    containers = home / "Library" / "Containers"

    assert consent_guarded_dirs(cloud, home=home, platform="darwin") == frozenset()
    assert str(containers) in consent_guarded_dirs(containers, home=home, platform="darwin")


def test_a_project_outside_the_account_library_has_nothing_guarded(home: Path) -> None:
    assert consent_guarded_dirs(home / "code" / "app", home=home, platform="darwin") == frozenset()


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_other_systems_guard_nothing(home: Path, platform: str) -> None:
    """A folder named Library is an ordinary folder everywhere else."""
    assert consent_guarded_dirs(home, home=home, platform=platform) == frozenset()


def test_the_index_of_the_library_is_empty(macos: Path) -> None:
    """The reported case: the workspace folder is the Library itself."""
    index = file_index.build_index(macos / "Library")

    assert index.entries == []
    assert index.truncated is False


def test_the_index_of_the_home_folder_leaves_the_library_out(macos: Path) -> None:
    rels = {entry.rel for entry in file_index.build_index(macos).entries}

    assert rels == {"code/app/main.py"}


def test_the_index_of_a_project_inside_the_library_is_built(macos: Path) -> None:
    """An iCloud Drive project lives under the Library and is still a project."""
    cloud = macos / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "site"

    rels = {entry.rel for entry in file_index.build_index(cloud).entries}

    assert rels == {"index.ts"}


def test_quick_open_lists_nothing_for_the_library(macos: Path) -> None:
    assert file_editing.list_files(macos / "Library") == ([], False)


def test_quick_open_from_the_home_folder_leaves_the_library_out(macos: Path) -> None:
    paths, truncated = file_editing.list_files(macos)

    assert paths == ["code/app/main.py"]
    assert truncated is False


def test_the_library_is_walked_where_the_rule_does_not_apply(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is the only thing keeping the walk out, not a missing fixture."""

    def nothing_guarded(root: str | os.PathLike[str]) -> frozenset[str]:
        return consent_guarded_dirs(root, home=home, platform="linux")

    monkeypatch.setattr(file_index, "consent_guarded_dirs", nothing_guarded)

    rels = {entry.rel for entry in file_index.build_index(home / "Library").entries}

    assert "Containers/com.apple.Notes/Data/notes.py" in rels
