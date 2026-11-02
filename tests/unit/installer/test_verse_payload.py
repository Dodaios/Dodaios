"""Verse payloads and deltas: make, install, apply, verify, roll back (WP22.4, A22.5)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from dodaios.core import installer_update as iu
from scripts.unreal import package


def _stage(folder: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return folder


BASE = {
    "Verse.exe": b"launcher-1",
    "Verse/Binaries/Win64/Verse-Win64-Shipping.exe": b"game-1" * 100,
    "Verse/Content/Paks/global.utoc": b"global" * 50,
    "Verse/Content/Paks/pakchunk0-Windows.utoc": b"core-1" * 80,
    "Verse/Content/Paks/pakchunk1-Windows.ucas": b"bridge-1" * 300,
    "Verse/Content/Paks/pakchunk4-Windows.ucas": b"hangar-1" * 400,
}


@pytest.fixture
def released(tmp_path: Path) -> dict[str, Path]:
    """Version 4.2.0 installed from its full payload, and a 4.2.1 build staged."""
    old_stage = _stage(tmp_path / "old", BASE)
    full = tmp_path / "Verse-Win64-4.2.0.tar"
    package.make_full(old_stage, version="4.2.0", platform="Win64", out=full)
    root = tmp_path / "root"
    iu.install_verse_full(root, full)
    new_files = dict(BASE)
    new_files["Verse/Content/Paks/pakchunk4-Windows.ucas"] = b"hangar-2" * 450
    new_files["Verse/Content/Paks/pakchunk5-Windows.ucas"] = b"new-deck" * 10
    new_stage = _stage(tmp_path / "new", new_files)
    return {"root": root, "full": full, "new": new_stage, "tmp": tmp_path}


def test_full_install_verifies_and_points_current(released: dict[str, Path]) -> None:
    root = released["root"]
    current = iu.verse_current(root)
    assert current == {
        "schema": iu.VERSE_CURRENT_SCHEMA,
        "version": "4.2.0",
        "previous": None,
        "platform": "Win64",
    }
    assert iu.verify_verse_tree(iu.verse_version_dir(root, "4.2.0")) == []


def test_delta_carries_only_changed_chunks_and_applies_with_full_hash_match(
    released: dict[str, Path],
) -> None:
    delta = released["tmp"] / "d.delta.tar"
    made = package.make_delta(
        package.read_payload_tree(released["full"]), released["new"], version="4.2.1", out=delta
    )
    assert sorted(made["changed_files"]) == [
        "Verse/Content/Paks/pakchunk4-Windows.ucas",
        "Verse/Content/Paks/pakchunk5-Windows.ucas",
    ]
    assert made["reused"] == len(BASE) - 1
    assert made["within_typical"] is True

    result = iu.apply_verse_delta(released["root"], delta)
    assert result["version"] == "4.2.1" and result["previous"] == "4.2.0"
    assert result["changed"] == 2
    new_dir = iu.verse_version_dir(released["root"], "4.2.1")
    assert iu.verify_verse_tree(new_dir) == []  # 100 % hash match
    assert (new_dir / "Verse/Content/Paks/pakchunk4-Windows.ucas").read_bytes() == b"hangar-2" * 450
    # The previous version stays for a rollback.
    assert iu.verify_verse_tree(iu.verse_version_dir(released["root"], "4.2.0")) == []


def _rewrite_member(source: Path, out: Path, name: str, data: bytes) -> None:
    with tarfile.open(source, "r:") as old, tarfile.open(out, "w") as new:
        for member in old.getmembers():
            payload = old.extractfile(member).read() if member.isfile() else b""
            if member.name == name:
                payload = data
            info = tarfile.TarInfo(member.name)
            info.size = len(payload)
            new.addfile(info, io.BytesIO(payload))


def test_a_corrupted_chunk_rolls_back_to_the_previous_version(released: dict[str, Path]) -> None:
    delta = released["tmp"] / "d.delta.tar"
    package.make_delta(
        package.read_payload_tree(released["full"]), released["new"], version="4.2.1", out=delta
    )
    corrupted = released["tmp"] / "corrupt.delta.tar"
    _rewrite_member(
        delta, corrupted, "files/Verse/Content/Paks/pakchunk4-Windows.ucas", b"X" * (8 * 450)
    )
    with pytest.raises(iu.VerseUpdateError, match="rolled back, version 4.2.0 stays installed"):
        iu.apply_verse_delta(released["root"], corrupted)
    assert iu.verse_current(released["root"])["version"] == "4.2.0"
    assert iu.verify_verse_tree(iu.verse_version_dir(released["root"], "4.2.0")) == []
    leftovers = [p.name for p in (released["root"] / "versions").iterdir()]
    assert leftovers == ["4.2.0"]  # the staging folder is gone


def test_a_delta_for_another_base_build_is_refused(released: dict[str, Path]) -> None:
    other = _stage(released["tmp"] / "other", {**BASE, "Verse.exe": b"launcher-other"})
    other_full = released["tmp"] / "Verse-Win64-4.2.0-other.tar"
    package.make_full(other, version="4.2.0", platform="Win64", out=other_full)
    delta = released["tmp"] / "d.delta.tar"
    package.make_delta(
        package.read_payload_tree(other_full), released["new"], version="4.2.1", out=delta
    )
    with pytest.raises(iu.VerseUpdateError, match="not the build this delta was made from"):
        iu.apply_verse_delta(released["root"], delta)
    assert iu.verse_current(released["root"])["version"] == "4.2.0"


def test_a_delta_from_another_version_is_refused(released: dict[str, Path]) -> None:
    tree = package.read_payload_tree(released["full"])
    tree["version"] = "4.1.0"
    delta = released["tmp"] / "d.delta.tar"
    package.make_delta(tree, released["new"], version="4.2.1", out=delta)
    with pytest.raises(iu.VerseUpdateError, match="updates Verse 4.1.0, but 4.2.0 is installed"):
        iu.apply_verse_delta(released["root"], delta)


def test_a_delta_needs_an_installed_verse(tmp_path: Path) -> None:
    with pytest.raises(iu.VerseUpdateError, match="no Verse is installed"):
        iu.apply_verse_delta(tmp_path / "empty", tmp_path / "x.tar")


@pytest.mark.parametrize(
    "name", ["files/../escape.txt", "/abs/path", "files/C:/x", "files\\win\\path", "files//x"]
)
def test_unsafe_tar_paths_are_refused(tmp_path: Path, name: str) -> None:
    bad = tmp_path / "bad.tar"
    tree = {
        "schema": iu.VERSE_TREE_SCHEMA,
        "version": "1.0.0",
        "platform": "Win64",
        "files": {"a": {"size": 1, "sha256": "0" * 64}},
    }
    with tarfile.open(bad, "w") as archive:
        for member_name, data in (
            (iu.VERSE_TREE_FILE, json.dumps(tree).encode()),
            (name, b"x"),
        ):
            info = tarfile.TarInfo(member_name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(iu.VerseUpdateError, match="unsafe path"):
        iu.install_verse_full(tmp_path / "root", bad)
    assert not (tmp_path / "escape.txt").exists()


def test_a_symlink_member_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "bad.tar"
    with tarfile.open(bad, "w") as archive:
        info = tarfile.TarInfo("files/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with pytest.raises(iu.VerseUpdateError, match="non-file entry"):
        iu.install_verse_full(tmp_path / "root", bad)


def test_rollback_and_health_check(released: dict[str, Path]) -> None:
    root = released["root"]
    delta = released["tmp"] / "d.delta.tar"
    package.make_delta(
        package.read_payload_tree(released["full"]), released["new"], version="4.2.1", out=delta
    )
    iu.apply_verse_delta(root, delta)
    assert iu.ensure_verse_healthy(root, hashes=True) == {"status": "ok", "version": "4.2.1"}
    # A damaged chunk of the running version rolls back to the verified previous one.
    (iu.verse_version_dir(root, "4.2.1") / "Verse/Content/Paks/pakchunk4-Windows.ucas").write_bytes(
        b"truncated"
    )
    health = iu.ensure_verse_healthy(root)
    assert health["status"] == "rolled_back"
    assert health["version"] == "4.2.0"
    assert iu.verse_current(root)["version"] == "4.2.0"
    with pytest.raises(iu.VerseUpdateError, match="no previous Verse version"):
        iu.rollback_verse(root)


def test_damage_to_a_file_both_versions_share_reports_broken(released: dict[str, Path]) -> None:
    """Unchanged files are hard links; damage to one is damage to both versions.

    The health check then says ``broken`` (the updater reinstalls the full
    payload) instead of switching to a previous version that is damaged too.
    """
    root = released["root"]
    delta = released["tmp"] / "d.delta.tar"
    package.make_delta(
        package.read_payload_tree(released["full"]), released["new"], version="4.2.1", out=delta
    )
    iu.apply_verse_delta(root, delta)
    (iu.verse_version_dir(root, "4.2.1") / "Verse.exe").write_bytes(b"truncated")
    health = iu.ensure_verse_healthy(root)
    assert health["status"] == "broken"
    assert iu.verse_current(root)["version"] == "4.2.1"


def test_verify_reports_every_kind_of_difference(released: dict[str, Path]) -> None:
    folder = iu.verse_version_dir(released["root"], "4.2.0")
    (folder / "Verse.exe").write_bytes(b"launcher-X")  # same size, other bytes
    (folder / "Verse/Content/Paks/global.utoc").unlink()
    (folder / "stray.txt").write_bytes(b"x")
    problems = iu.verify_verse_tree(folder)
    assert "hash mismatch Verse.exe" in problems
    assert "missing Verse/Content/Paks/global.utoc" in problems
    assert "unexpected stray.txt" in problems
    assert "hash mismatch Verse.exe" not in iu.verify_verse_tree(folder, hashes=False)


def test_seed_from_the_installer_bundle(tmp_path: Path) -> None:
    stage = _stage(tmp_path / "stage", BASE)
    bundle = tmp_path / "bundle"
    (bundle / "verse").mkdir(parents=True)
    seed = bundle / "verse" / "Verse-Win64-4.3.0.tar"
    package.make_full(stage, version="4.3.0", platform="Win64", out=seed)
    root = tmp_path / "root"
    kwargs = {"root": root, "bundle": bundle, "platform_name": "win32", "machine": "AMD64"}

    assert iu.seed_verse_from_bundle(gpu_supported=False, **kwargs) == {"status": "unsupported"}
    assert seed.exists() and not root.exists()

    result = iu.seed_verse_from_bundle(gpu_supported=True, **kwargs)
    assert result["status"] == "installed" and result["version"] == "4.3.0"
    assert not seed.exists()  # no second copy on disk
    assert iu.seed_verse_from_bundle(gpu_supported=True, **kwargs) == {"status": "no_seed"}

    # An older seed never replaces a newer, delta-updated Verse.
    package.make_full(
        stage, version="4.2.9", platform="Win64", out=bundle / "verse" / "Verse-Win64-4.2.9.tar"
    )
    assert iu.seed_verse_from_bundle(gpu_supported=True, **kwargs)["status"] == "current"
    # A seed for the other platform is ignored.
    linux = dict(kwargs, platform_name="linux", machine="x86_64")
    assert iu.seed_verse_from_bundle(gpu_supported=True, **linux) == {"status": "no_seed"}


def test_a_broken_install_takes_the_seed_even_when_it_is_not_newer(tmp_path: Path) -> None:
    stage = _stage(tmp_path / "stage", BASE)
    bundle = tmp_path / "bundle"
    (bundle / "verse").mkdir(parents=True)
    seed = bundle / "verse" / "Verse-Win64-4.3.0.tar"
    package.make_full(stage, version="4.3.0", platform="Win64", out=seed)
    root = tmp_path / "root"
    iu.install_verse_full(root, seed)
    (iu.verse_version_dir(root, "4.3.0") / "Verse.exe").write_bytes(b"x")
    kwargs = {"root": root, "bundle": bundle, "platform_name": "win32", "machine": "AMD64"}

    result = iu.seed_verse_from_bundle(gpu_supported=True, **kwargs)
    assert result["status"] == "repaired" and result["version"] == "4.3.0"
    assert iu.ensure_verse_healthy(root, hashes=True) == {"status": "ok", "version": "4.3.0"}


def test_reinstalling_the_running_version_keeps_it_when_the_swap_fails(
    released: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = released["root"]
    real_replace = iu.os.replace

    def failing_replace(src, dst):
        if Path(src).name.startswith(".staging-"):
            raise PermissionError("in use")
        return real_replace(src, dst)

    monkeypatch.setattr(iu.os, "replace", failing_replace)
    with pytest.raises(iu.VerseUpdateError, match="could not be switched in"):
        iu.install_verse_full(root, released["full"])
    monkeypatch.setattr(iu.os, "replace", real_replace)
    assert iu.ensure_verse_healthy(root, hashes=True) == {"status": "ok", "version": "4.2.0"}
    assert not [p for p in (root / "versions").iterdir() if p.name.startswith(".")]


def test_apply_command_writes_the_delta_apply_log(released: dict[str, Path]) -> None:
    delta = released["tmp"] / "d.delta.tar"
    package.make_delta(
        package.read_payload_tree(released["full"]), released["new"], version="4.2.1", out=delta
    )
    log = released["tmp"] / "apply.log"
    code = package.main(
        ["apply", "--root", str(released["root"]), "--delta", str(delta), "--log", str(log)]
    )
    assert code == 0
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["status"] == "applied"
    assert entry["after"]["version"] == "4.2.1"
    assert entry["verify_problems"] == []
