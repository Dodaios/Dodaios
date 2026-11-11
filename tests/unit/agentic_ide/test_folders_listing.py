"""Browsing folders: what is listed, in which order, and what a typed path means.

Each rule here answers a report from clicking through a real account folder:

* the list was sorted projects-first, an order nobody could scan;
* Windows' own compatibility links ("Application Data", "Cookies") were listed
  as folders and refused to open;
* a relative path was read against the working directory of the server
  process, so ``..`` listed a folder the person had never been in.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

import pytest

from dodaios.agentic_ide import recents
from dodaios.agentic_ide.folders import list_dir, resolve_folder_path, search_folders
from dodaios.ui.web import agentic_ide_routes as routes

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows file attributes")

_HIDDEN = 0x2
_SYSTEM = 0x4


def _names(path: Path, **kwargs: bool) -> list[str]:
    entries, error = list_dir(path, **kwargs)
    assert error is None
    return [entry.name for entry in entries]


def _set_attributes(path: Path, attributes: int) -> None:
    assert ctypes.windll.kernel32.SetFileAttributesW(str(path), attributes)


# --------------------------------------------------------------------------- #
# The listing                                                                 #
# --------------------------------------------------------------------------- #
def test_folders_are_listed_by_name_with_numbers_read_as_numbers(tmp_path: Path) -> None:
    for name in ("zeta", "Alpha", "New folder (10)", "New folder (9)", "beta"):
        (tmp_path / name).mkdir()
    # A repository used to jump to the top; it now stays where its name puts it.
    (tmp_path / "zeta" / ".git").mkdir()

    assert _names(tmp_path) == ["Alpha", "beta", "New folder (9)", "New folder (10)", "zeta"]


def test_a_repository_is_marked(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    (tmp_path / "repo" / ".git").mkdir(parents=True)

    entries, _error = list_dir(tmp_path)

    assert {entry.name: entry.is_repo for entry in entries} == {"plain": False, "repo": True}


def test_files_are_not_listed(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    assert _names(tmp_path) == ["folder"]


def test_tool_clutter_waits_for_the_hidden_switch(tmp_path: Path) -> None:
    for name in ("src", ".git", "node_modules", "__pycache__", "dist", "build"):
        (tmp_path / name).mkdir()

    # A folder called "dist" or "build" can be somebody's project: it stays.
    assert _names(tmp_path) == ["build", "dist", "src"]
    assert set(_names(tmp_path, include_hidden=True)) == {
        "src",
        ".git",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
    }


@windows_only
def test_a_folder_windows_hides_waits_for_the_hidden_switch(tmp_path: Path) -> None:
    (tmp_path / "AppData").mkdir()
    (tmp_path / "Documents").mkdir()
    _set_attributes(tmp_path / "AppData", _HIDDEN)

    assert _names(tmp_path) == ["Documents"]
    assert _names(tmp_path, include_hidden=True) == ["AppData", "Documents"]


@windows_only
def test_a_folder_of_the_operating_system_is_never_listed(tmp_path: Path) -> None:
    """Hidden AND System: the recycle bin and the links older Windows versions
    left in every account folder. They refuse to open, so listing them only
    produced "not allowed to look inside"."""
    (tmp_path / "Application Data").mkdir()
    (tmp_path / "Documents").mkdir()
    _set_attributes(tmp_path / "Application Data", _HIDDEN | _SYSTEM)

    assert _names(tmp_path, include_hidden=True) == ["Documents"]
    # The name search does not offer it either.
    assert search_folders("Application", roots=[tmp_path]) == []


@windows_only
def test_the_search_does_not_walk_into_a_folder_windows_hides(tmp_path: Path) -> None:
    (tmp_path / "AppData" / "Local" / "webshop").mkdir(parents=True)
    (tmp_path / "work" / "webshop").mkdir(parents=True)
    _set_attributes(tmp_path / "AppData", _HIDDEN)

    hits = [entry.path for entry in search_folders("webshop", roots=[tmp_path])]

    assert hits == [str(tmp_path / "work" / "webshop")]


def test_a_linked_folder_is_listed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    try:
        (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("this account may not create links")

    assert _names(tmp_path) == ["linked", "real"]


# --------------------------------------------------------------------------- #
# What a typed path means                                                     #
# --------------------------------------------------------------------------- #
def test_a_relative_path_is_read_against_the_folder_on_screen(tmp_path: Path) -> None:
    (tmp_path / "Desktop" / "shop").mkdir(parents=True)

    assert resolve_folder_path("Desktop", tmp_path) == tmp_path / "Desktop"
    assert resolve_folder_path("Desktop/shop", tmp_path) == tmp_path / "Desktop" / "shop"
    assert resolve_folder_path("..", tmp_path / "Desktop") == tmp_path
    assert resolve_folder_path("../Desktop/./shop/..", tmp_path / "Desktop") == tmp_path / "Desktop"


def test_without_a_folder_on_screen_it_is_read_against_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never against the working directory of the server process: that is
    wherever the app was started from."""
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.chdir(Path(__file__).parent)

    assert resolve_folder_path("Desktop") == tmp_path / "Desktop"
    assert resolve_folder_path("..") == tmp_path.parent


def test_a_full_path_ignores_the_folder_on_screen(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert resolve_folder_path(str(elsewhere), tmp_path / "Desktop") == elsewhere


def test_an_environment_variable_expands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOLDER_PICKER_TEST_ROOT", str(tmp_path))
    typed = "%FOLDER_PICKER_TEST_ROOT%" if os.name == "nt" else "$FOLDER_PICKER_TEST_ROOT"

    assert resolve_folder_path(f"{typed}/shop") == tmp_path / "shop"


@windows_only
def test_a_bare_drive_means_its_root() -> None:
    drive = Path.home().drive  # "C:"

    assert str(resolve_folder_path(drive)) == f"{drive}\\"
    assert str(resolve_folder_path(drive.lower())) == f"{drive}\\"


@windows_only
def test_the_spelling_on_disk_wins_over_the_spelling_typed(tmp_path: Path) -> None:
    (tmp_path / "MyProject").mkdir()

    resolved = resolve_folder_path(str(tmp_path / "myproject").upper())

    assert resolved.name == "MyProject"
    assert resolved == (tmp_path / "MyProject").resolve()


# --------------------------------------------------------------------------- #
# The route                                                                   #
# --------------------------------------------------------------------------- #
async def test_the_route_reads_a_relative_path_against_its_base(tmp_path: Path) -> None:
    (tmp_path / "Desktop" / "shop").mkdir(parents=True)

    res = await routes.get_folders(path="Desktop", base=str(tmp_path))

    assert res.error is None
    assert res.path == str(tmp_path / "Desktop")
    assert [entry.name for entry in res.entries] == ["shop"]
    assert res.parent == str(tmp_path)


async def test_a_path_to_a_file_answers_with_its_folder(tmp_path: Path) -> None:
    """ "Copy as path" on a file inside the project is how many people get a
    path at all."""
    (tmp_path / "shop" / "src").mkdir(parents=True)
    readme = tmp_path / "shop" / "README.md"
    readme.write_text("x", encoding="utf-8")

    res = await routes.get_folders(path=str(readme))

    assert res.error is None
    assert res.path == str(tmp_path / "shop")
    assert [entry.name for entry in res.entries] == ["src"]


async def test_every_answer_names_the_home_folder(tmp_path: Path) -> None:
    start = await routes.get_folders()
    inside = await routes.get_folders(path=str(tmp_path))

    assert start.path is None
    assert start.home == str(Path.home())
    assert inside.home == str(Path.home())
    assert inside.truncated is False


# --------------------------------------------------------------------------- #
# Recent folders                                                              #
# --------------------------------------------------------------------------- #
def test_a_relative_recent_folder_is_not_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real store held ".": listed as a folder called ".", it opened whatever
    the app's working directory was that day."""
    real = tmp_path / "project"
    real.mkdir()
    store = tmp_path / "recents.json"
    layout = {"terminals": 1, "agents": {}}
    store.write_text(
        json.dumps(
            [
                {"path": ".", "name": ".", "last_used": 2.0, **layout},
                {"path": str(real), "name": "project", "last_used": 1.0, **layout},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recents, "_store_path", lambda: store)
    monkeypatch.setattr(recents, "_temp_roots", list)

    assert [entry.path for entry in recents.load()] == [str(real)]


def test_a_relative_folder_is_remembered_by_where_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "recents.json"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(recents, "_store_path", lambda: store)
    monkeypatch.setattr(recents, "_temp_roots", list)
    monkeypatch.chdir(project)

    recents.remember(".", terminals=1, agents={})

    remembered = recents.load()
    assert [Path(entry.path) for entry in remembered] == [project.resolve()]
    assert remembered[0].name == "project"
