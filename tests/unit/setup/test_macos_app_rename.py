"""The macOS app bundle takes its current name once, in place.

``Personal Jarvis.app`` becomes ``Dodaios.app`` by one rename in the folder it
lives in: the bytes, the signature and with them every privacy grant stay (TCC
names the bundle id and the signing requirement, never a path). These tests run
the rename over a throw-away Applications folder: only this install's bundle is
renamed, nothing is left under the earlier name, and nothing that is not ours or
that already has the current name is ever moved. A failed update gives the
bundle back the name the revision it falls back to knows.
"""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

import pytest

import dodaios.setup.macos_app_bundle as mab
from dodaios.core.branding import (
    LEGACY_MACOS_APP_DIR_NAMES,
    MACOS_APP_DIR_NAME,
    MACOS_BUNDLE_ID,
    MACOS_DMG_BUNDLE_ID,
)
from dodaios.setup import update_rollback
from dodaios.setup.macos_app_bundle import rename_legacy_macos_app_bundles

EARLIER = LEGACY_MACOS_APP_DIR_NAMES[0]


def _bundle(root: Path, name: str, bundle_id: str | None, marker: str = "signed-bytes") -> Path:
    bundle = root / name
    macos = bundle / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "DodaiosApp").write_text(marker, encoding="utf-8")
    if bundle_id is not None:
        with (bundle / "Contents" / "Info.plist").open("wb") as stream:
            plistlib.dump({"CFBundleIdentifier": bundle_id}, stream)
    return bundle


def _marker(bundle: Path) -> str:
    return (bundle / "Contents" / "MacOS" / "DodaiosApp").read_text(encoding="utf-8")


@pytest.fixture
def unregistered(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    seen: list[Path] = []
    monkeypatch.setattr(mab, "unregister_from_launch_services", seen.append)
    return seen


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    system = tmp_path / "Applications"
    user = tmp_path / "home" / "Applications"
    system.mkdir()
    user.mkdir(parents=True)
    return system, user


def test_the_names_are_what_finder_and_the_contract_show() -> None:
    assert MACOS_APP_DIR_NAME == "Dodaios.app"
    assert EARLIER == "Personal Jarvis.app"


def test_our_bundle_is_renamed_byte_for_byte_with_nothing_left_behind(
    roots, unregistered
) -> None:
    system, user = roots
    _bundle(system, EARLIER, MACOS_BUNDLE_ID)

    renamed = rename_legacy_macos_app_bundles((system, user))

    assert renamed == [system / MACOS_APP_DIR_NAME]
    assert _marker(system / MACOS_APP_DIR_NAME) == "signed-bytes"
    # No link under the earlier name: Launchpad would list the app twice.
    assert not os.path.lexists(system / EARLIER)
    assert sorted(p.name for p in system.iterdir()) == [MACOS_APP_DIR_NAME]
    assert unregistered == [system / EARLIER]


def test_a_second_run_renames_nothing(roots, unregistered) -> None:
    system, user = roots
    _bundle(user, EARLIER, MACOS_BUNDLE_ID)

    assert rename_legacy_macos_app_bundles((system, user)) == [user / MACOS_APP_DIR_NAME]
    assert rename_legacy_macos_app_bundles((system, user)) == []
    assert _marker(user / MACOS_APP_DIR_NAME) == "signed-bytes"


@pytest.mark.parametrize(
    "bundle_id",
    [
        # The .dmg app: renamed by its own updater, which swaps the bundle it
        # runs from and must find it where it started.
        MACOS_DMG_BUNDLE_ID,
        "org.example.someone-else",
        None,  # no Info.plist proves nothing about ownership
    ],
)
def test_only_this_installs_bundle_is_renamed(
    roots, unregistered, bundle_id: str | None
) -> None:
    system, _user = roots
    _bundle(system, EARLIER, bundle_id, marker="not ours to move")

    assert rename_legacy_macos_app_bundles((system,)) == []
    assert _marker(system / EARLIER) == "not ours to move"
    assert not (system / MACOS_APP_DIR_NAME).exists()
    assert unregistered == []


@pytest.mark.parametrize("present_id", [MACOS_BUNDLE_ID, "org.example.dodaios", None])
def test_an_app_already_under_the_current_name_keeps_both(
    roots, unregistered, present_id: str | None
) -> None:
    system, _user = roots
    _bundle(system, EARLIER, MACOS_BUNDLE_ID, marker="earlier")
    _bundle(system, MACOS_APP_DIR_NAME, present_id, marker="present")

    assert rename_legacy_macos_app_bundles((system,)) == []
    assert _marker(system / EARLIER) == "earlier"
    assert _marker(system / MACOS_APP_DIR_NAME) == "present"


def test_a_link_under_the_earlier_name_is_left_alone(roots, unregistered) -> None:
    system, user = roots
    real = _bundle(user, MACOS_APP_DIR_NAME, MACOS_BUNDLE_ID)
    try:
        (system / EARLIER).symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot create symbolic links")

    assert rename_legacy_macos_app_bundles((system,)) == []
    assert (system / EARLIER).is_symlink()


def test_a_failed_rename_keeps_the_working_app(
    roots, unregistered, monkeypatch: pytest.MonkeyPatch
) -> None:
    system, _user = roots
    _bundle(system, EARLIER, MACOS_BUNDLE_ID)

    def _refuse(_source: object, _target: object) -> None:
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(mab.os, "rename", _refuse)

    assert rename_legacy_macos_app_bundles((system,)) == []
    assert _marker(system / EARLIER) == "signed-bytes"
    assert unregistered == []


def test_uninstall_removes_our_bundle_under_either_name(roots, unregistered) -> None:
    system, _user = roots
    _bundle(system, EARLIER, MACOS_BUNDLE_ID)
    _bundle(system, MACOS_APP_DIR_NAME, MACOS_BUNDLE_ID)

    assert mab.remove_macos_app_bundle(applications_dir=system) is True
    assert list(system.iterdir()) == []


def test_the_dmg_app_is_found_under_its_earlier_name(
    roots, monkeypatch: pytest.MonkeyPatch
) -> None:
    system, user = roots
    monkeypatch.setattr(mab, "SYSTEM_APPLICATIONS_DIR", system)
    monkeypatch.setattr(mab, "user_applications_dir", lambda: user)
    dmg_app = _bundle(system, EARLIER, MACOS_DMG_BUNDLE_ID)

    assert mab.installed_macos_app_bundle_path() == dmg_app


@pytest.mark.skipif(sys.platform == "win32", reason="patches sys.platform to darwin")
def test_the_repair_renames_and_follows_the_running_app(
    roots, unregistered, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The process keeps the path it started from; the repair hands back, and
    registers, the bundle under its current name and never rebuilds it."""
    system, user = roots
    launched_from = _bundle(system, EARLIER, MACOS_BUNDLE_ID)
    monkeypatch.setattr(mab.sys, "platform", "darwin")
    monkeypatch.setattr(mab, "SYSTEM_APPLICATIONS_DIR", system)
    monkeypatch.setattr(mab, "user_applications_dir", lambda: user)
    monkeypatch.setattr(mab, "ensure_local_signing_identity", lambda **_kw: None)
    monkeypatch.setattr(
        mab, "_running_managed_bundle", lambda *, install_root, **_kw: launched_from
    )
    monkeypatch.setattr(
        mab,
        "_install_native_bundle",
        lambda *_a, **_kw: pytest.fail("a renamed running app must never be rebuilt"),
    )
    registered: list[Path] = []
    monkeypatch.setattr(mab, "register_with_launch_services", registered.append)

    result = mab.ensure_macos_app_bundle(install_dir=tmp_path / "install")

    assert result == system / MACOS_APP_DIR_NAME
    assert registered == [system / MACOS_APP_DIR_NAME]
    assert not launched_from.exists()


def test_the_repair_of_an_injected_folder_renames_there_first(
    roots, unregistered, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    system, _user = roots
    _bundle(system, EARLIER, MACOS_BUNDLE_ID)
    seen: list[list[str]] = []

    def _stop_after_the_rename(_bundle: Path) -> bool:
        seen.append(sorted(p.name for p in system.iterdir()))
        raise RuntimeError("stop here")

    monkeypatch.setattr(mab, "_is_foreign_bundle", _stop_after_the_rename)

    assert mab.ensure_macos_app_bundle(install_dir=tmp_path, applications_dir=system) is None
    assert seen == [[MACOS_APP_DIR_NAME]]


# --------------------------------------------------------------------------- #
# A failed update gives the bundle back its earlier name
# --------------------------------------------------------------------------- #
def _git_show_answering(answers: dict[str, str | None]):
    def _show(_root: Path, spec: str) -> str | None:
        return answers.get(spec)

    return _show


def test_a_revision_without_a_contract_knows_the_earlier_name(tmp_path: Path) -> None:
    show = _git_show_answering({})
    assert update_rollback.previous_macos_app_dir_name(tmp_path, "abc", git_show=show) == EARLIER


def test_a_revision_with_a_contract_knows_the_name_it_states(tmp_path: Path) -> None:
    show = _git_show_answering(
        {
            "old:install/update-contract.json": '{"schema": 1, "macos_app_dir_name": '
            f'"{EARLIER}"}}',
            "new:install/update-contract.json": '{"schema": 1, "macos_app_dir_name": '
            f'"{MACOS_APP_DIR_NAME}"}}',
        }
    )
    previous = update_rollback.previous_macos_app_dir_name
    assert previous(tmp_path, "old", git_show=show) == EARLIER
    assert previous(tmp_path, "new", git_show=show) == MACOS_APP_DIR_NAME


def test_the_rollback_gives_our_bundle_its_earlier_name_back(roots) -> None:
    system, user = roots
    _bundle(user, MACOS_APP_DIR_NAME, MACOS_BUNDLE_ID)

    restored = update_rollback.restore_macos_app_bundle_name(EARLIER, (system, user))

    assert restored == [user / EARLIER]
    assert _marker(user / EARLIER) == "signed-bytes"
    assert not os.path.lexists(user / MACOS_APP_DIR_NAME)


@pytest.mark.parametrize("bundle_id", [MACOS_DMG_BUNDLE_ID, "org.example.dodaios", None])
def test_the_rollback_never_renames_an_app_that_is_not_this_installs(
    roots, bundle_id: str | None
) -> None:
    system, _user = roots
    _bundle(system, MACOS_APP_DIR_NAME, bundle_id)

    assert update_rollback.restore_macos_app_bundle_name(EARLIER, (system,)) == []
    assert (system / MACOS_APP_DIR_NAME).is_dir()


def test_the_rollback_renames_nothing_for_a_revision_that_knows_the_current_name(
    roots,
) -> None:
    system, _user = roots
    _bundle(system, MACOS_APP_DIR_NAME, MACOS_BUNDLE_ID)

    restore = update_rollback.restore_macos_app_bundle_name
    assert restore(MACOS_APP_DIR_NAME, (system,)) == []
    # Nor to a name that was never ours.
    assert restore("Someone Else.app", (system,)) == []
    assert (system / MACOS_APP_DIR_NAME).is_dir()


def test_the_rollback_never_replaces_a_bundle_under_the_earlier_name(roots) -> None:
    system, _user = roots
    _bundle(system, MACOS_APP_DIR_NAME, MACOS_BUNDLE_ID, marker="current")
    _bundle(system, EARLIER, MACOS_BUNDLE_ID, marker="earlier")

    assert update_rollback.restore_macos_app_bundle_name(EARLIER, (system,)) == []
    assert _marker(system / MACOS_APP_DIR_NAME) == "current"
    assert _marker(system / EARLIER) == "earlier"


def test_the_rollback_hook_does_nothing_off_macos() -> None:
    if sys.platform == "darwin":
        pytest.skip("the darwin branch touches the real Applications folders")
    assert update_rollback.main(["abc", "def"]) == 0
