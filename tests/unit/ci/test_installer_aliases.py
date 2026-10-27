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
    # What the OS jobs upload: every installer under its current name.
    _stage(tmp_path, [current for current, _earlier in PAIRS])

    written = installer_aliases.add_aliases(tmp_path, publish_earlier=True)

    assert sorted(written) == sorted(earlier for _current, earlier in PAIRS)
    for current, earlier in PAIRS:
        assert (tmp_path / current).read_bytes() == (tmp_path / earlier).read_bytes()


def test_an_installer_under_only_its_earlier_name_gets_the_current_one(tmp_path: Path) -> None:
    windows, *others = PAIRS
    _stage(tmp_path, [windows[1], *(current for current, _earlier in others)])

    written = installer_aliases.add_aliases(tmp_path, publish_earlier=True)

    assert sorted(written) == sorted([windows[0], *(earlier for _current, earlier in others)])


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


def test_the_checksum_job_aliases_after_download_and_before_the_manifest() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/desktop-installers.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["checksums"]["steps"]
    runs = [step.get("run", "") for step in steps]
    download = next(i for i, s in enumerate(steps) if "download-artifact@" in s.get("uses", ""))
    alias = next(i for i, run in enumerate(runs) if "installer_aliases.py installers" in run)
    manifest = next(i for i, run in enumerate(runs) if "installers-SHA256SUMS.txt" in run)
    assert download < alias < manifest
    # The required names come from release_assets.py, so the sunset switch
    # reaches the manifest without editing the workflow.
    assert "installer_aliases.py --names" in runs[manifest]
    assert "PersonalJarvis-" not in runs[manifest]


def test_the_release_job_uploads_only_what_the_manifest_vouches_for() -> None:
    """The release job re-creates the aliases, then checks every file it uploads."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/desktop-installers.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["release"]["steps"]
    runs = [step.get("run", "") for step in steps]
    alias = next(i for i, run in enumerate(runs) if "installer_aliases.py installers" in run)
    check = next(i for i, run in enumerate(runs) if "sha256sum -c" in run)
    upload = next(i for i, run in enumerate(runs) if "release_assets.py upload" in run)
    assert alias < check < upload


def test_the_windows_setup_is_built_and_signed_under_one_name() -> None:
    """The .iss, the workflow and the SignPath configuration name one file."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/desktop-installers.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["windows"]
    name = job["env"]["SIGNED_SETUP_NAME"]
    assert name == "Dodaios-Setup-x64.exe"
    windows = job["steps"]
    staged = next(s for s in windows if s.get("id") == "signpath-unsigned")
    upload = next(s for s in windows if s.get("name") == "Upload the installer")
    assert staged["with"]["path"] == "dist/installers/${{ env.SIGNED_SETUP_NAME }}"
    assert upload["with"]["path"] == "dist/installers/${{ env.SIGNED_SETUP_NAME }}"
    windows_text = yaml.safe_dump(windows)
    assert "PersonalJarvis-Setup" not in windows_text
    iss = (ROOT / "packaging/windows/Dodaios.iss").read_text(encoding="utf-8")
    assert f'#define SignedSetupBaseName "{name.removesuffix(".exe")}"' in iss
    assert "OutputBaseFilename={#SignedSetupBaseName}" in iss
    assert '#define SignedProductName "Dodaios"' in iss
    build = (ROOT / "packaging/windows/build.ps1").read_text(encoding="utf-8")
    assert f'Join-Path $InstallerDir "{name}"' in build
    policy = (ROOT / "docs/code-signing-policy.md").read_text(encoding="utf-8")
    assert f'<pe-file path="{name}" product-name="Dodaios">' in policy


def test_the_sunset_switch_drops_the_earlier_names(tmp_path: Path) -> None:
    """With the switch off nothing is copied, and every current name must exist."""
    for current, _earlier in PAIRS:
        (tmp_path / current).write_bytes(b"signed")
    assert installer_aliases.add_aliases(tmp_path, publish_earlier=False) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(c for c, _ in PAIRS)
    (tmp_path / PAIRS[0][0]).unlink()
    with pytest.raises(ValueError, match="current name"):
        installer_aliases.add_aliases(tmp_path, publish_earlier=False)


def test_the_names_option_lists_what_the_release_requires(capsys) -> None:
    assert installer_aliases.main(["--names"]) == 0
    assert set(capsys.readouterr().out.split()) == release_assets.INSTALLERS
    assert release_assets.CURRENT_INSTALLERS <= release_assets.INSTALLERS
    if release_assets.PUBLISH_EARLIER_INSTALLER_NAMES:
        assert release_assets.EARLIER_INSTALLERS <= release_assets.INSTALLERS


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("packaging/macos/build.sh", 'DMG_PATH="${OUT_DIR}/Dodaios-macOS-${ARCH_TAG}.dmg"'),
        ("packaging/linux/build.sh", 'APPIMAGE_PATH="${OUT_DIR}/Dodaios-Linux-x86_64.AppImage"'),
    ],
)
def test_the_macos_and_linux_builds_produce_the_current_names(script, expected) -> None:
    assert expected in (ROOT / script).read_text(encoding="utf-8")
