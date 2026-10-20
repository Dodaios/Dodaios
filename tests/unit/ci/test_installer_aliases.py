"""Every native installer is published under both of its names, with the same bytes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.ci import installer_aliases, release_assets

ROOT = Path(__file__).resolve().parents[3]
PAIRS = release_assets.INSTALLER_NAME_PAIRS


def _stage(directory: Path, names: list[str]) -> None:
    for name in names:
        (directory / name).write_bytes(f"signed bytes of {name.split('-', 1)[1]}".encode())


def test_the_build_names_are_copied_to_the_earlier_names(tmp_path: Path) -> None:
    # What the OS jobs upload: the setup under its signed (earlier) name, the
    # rest under the current name.
    windows, *others = PAIRS
    _stage(tmp_path, [windows[1], *(current for current, _earlier in others)])

    written = installer_aliases.add_aliases(tmp_path)

    assert sorted(written) == sorted([windows[0], *(earlier for _current, earlier in others)])
    for current, earlier in PAIRS:
        assert (tmp_path / current).read_bytes() == (tmp_path / earlier).read_bytes()


def test_a_pair_already_complete_is_left_alone(tmp_path: Path) -> None:
    _stage(tmp_path, [name for pair in PAIRS for name in pair])
    assert installer_aliases.add_aliases(tmp_path) == []


def test_two_different_files_under_one_installers_names_fail(tmp_path: Path) -> None:
    _stage(tmp_path, [name for pair in PAIRS for name in pair])
    current, _earlier = PAIRS[0]
    (tmp_path / current).write_bytes(b"signed separately")
    with pytest.raises(ValueError, match="differ in content"):
        installer_aliases.add_aliases(tmp_path)


def test_a_missing_installer_fails_instead_of_shipping_half_a_release(tmp_path: Path) -> None:
    _stage(tmp_path, [current for current, _earlier in PAIRS[1:]])
    assert installer_aliases.main([str(tmp_path)]) == 1


def test_the_pairs_cover_exactly_the_published_installers() -> None:
    assert {name for pair in PAIRS for name in pair} == release_assets.INSTALLERS
    assert all(current.startswith("Dodaios-") for current, _earlier in PAIRS)
    assert all(earlier.startswith("PersonalJarvis-") for _current, earlier in PAIRS)


def test_the_release_job_aliases_after_download_and_before_the_manifest() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/desktop-installers.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["release"]["steps"]
    runs = [step.get("run", "") for step in steps]
    download = next(i for i, s in enumerate(steps) if "download-artifact@" in s.get("uses", ""))
    alias = next(i for i, run in enumerate(runs) if "installer_aliases.py installers" in run)
    manifest = next(i for i, run in enumerate(runs) if "installers-SHA256SUMS.txt" in run)
    assert download < alias < manifest
    for name in release_assets.INSTALLERS:
        assert name in runs[manifest], name


def test_the_windows_setup_is_signed_under_the_pinned_name() -> None:
    """SignPath pins the setup's file name; the current name is copied later."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/desktop-installers.yml").read_text(encoding="utf-8")
    )
    windows = workflow["jobs"]["windows"]["steps"]
    staged = next(s for s in windows if s.get("id") == "signpath-unsigned")
    upload = next(s for s in windows if s.get("name") == "Upload the installer")
    assert staged["with"]["path"].endswith("/PersonalJarvis-Setup-x64.exe")
    assert upload["with"]["path"].endswith("/PersonalJarvis-Setup-x64.exe")
    iss = (ROOT / "packaging/windows/Dodaios.iss").read_text(encoding="utf-8")
    assert '#define SignedSetupBaseName "PersonalJarvis-Setup-x64"' in iss
    assert "OutputBaseFilename={#SignedSetupBaseName}" in iss


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("packaging/macos/build.sh", 'DMG_PATH="${OUT_DIR}/Dodaios-macOS-${ARCH_TAG}.dmg"'),
        ("packaging/linux/build.sh", 'APPIMAGE_PATH="${OUT_DIR}/Dodaios-Linux-x86_64.AppImage"'),
    ],
)
def test_the_macos_and_linux_builds_produce_the_current_names(script, expected) -> None:
    assert expected in (ROOT / script).read_text(encoding="utf-8")
