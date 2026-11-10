"""Look packs: manifest rules, pack checks and safe file lookup."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dodaios.ui.looks import loader
from dodaios.ui.looks.manifest import (
    LOOK_FORMAT,
    MAX_PACK_BYTES,
    LookManifestError,
    is_safe_rel_path,
    parse_manifest,
)


def _manifest(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "format": LOOK_FORMAT,
        "id": "test-look",
        "name": "Test Look",
        "author": "Tester",
        "version": "1.0.0",
        "license": "Apache-2.0",
        "entry": "index.html",
        "preview": "preview.png",
    }
    data.update(overrides)
    return data


def _write_pack(root: Path, look_id: str = "test-look", **overrides: object) -> Path:
    folder = root / look_id
    folder.mkdir(parents=True)
    (folder / "look.json").write_text(
        json.dumps(_manifest(id=look_id, **overrides)), encoding="utf-8"
    )
    (folder / "index.html").write_text("<!doctype html><p>hi</p>", encoding="utf-8")
    (folder / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return folder


def test_valid_manifest_parses() -> None:
    manifest = parse_manifest(_manifest(license="Apache-2.0 AND CC-BY-4.0"))
    assert manifest.id == "test-look"
    assert manifest.license == "Apache-2.0 AND CC-BY-4.0"
    assert manifest.to_public()["builtin"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"format": "dodaios-look/2"},
        {"id": "Bad_Id"},
        {"id": "orb"},
        {"name": ""},
        {"name": "x" * 41},
        {"author": ""},
        {"version": "1.0"},
        {"license": ""},
        {"license": "see LICENSE file please"},
        {"entry": "../index.html"},
        {"entry": "main.js"},
        {"entry": "/abs/index.html"},
        {"preview": "preview.gif"},
        {"homepage": "http://example.com"},
        {"description": "line\nbreak"},
    ],
)
def test_bad_manifest_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(LookManifestError):
        parse_manifest(_manifest(**overrides))


def test_not_an_object_is_rejected() -> None:
    with pytest.raises(LookManifestError):
        parse_manifest(["not", "a", "dict"])


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("index.html", True),
        ("assets/models/core.glb", True),
        ("../secret.txt", False),
        ("a/../b.js", False),
        ("./a.js", False),
        ("a\\b.js", False),
        ("C:/x.js", False),
        ("", False),
        (".hidden", False),
    ],
)
def test_rel_path_shape(value: str, ok: bool) -> None:
    assert is_safe_rel_path(value) is ok


def test_read_manifest_checks_folder_name_and_files(tmp_path: Path) -> None:
    folder = _write_pack(tmp_path)
    assert loader.read_manifest(folder, builtin=False).name == "Test Look"

    (folder / "preview.png").unlink()
    with pytest.raises(LookManifestError, match="preview.png"):
        loader.read_manifest(folder, builtin=False)


def test_id_must_match_folder(tmp_path: Path) -> None:
    folder = _write_pack(tmp_path)
    renamed = folder.with_name("other-look")
    folder.rename(renamed)
    with pytest.raises(LookManifestError, match="folder"):
        loader.read_manifest(renamed, builtin=False)


def test_disallowed_file_kind_rejects_pack(tmp_path: Path) -> None:
    folder = _write_pack(tmp_path)
    (folder / "run.exe").write_bytes(b"MZ")
    with pytest.raises(LookManifestError, match="run.exe"):
        loader.read_manifest(folder, builtin=False)


def test_oversized_pack_is_rejected(tmp_path: Path) -> None:
    folder = _write_pack(tmp_path)
    with open(folder / "big.bin", "wb") as fh:
        fh.truncate(MAX_PACK_BYTES + 1)
    with pytest.raises(LookManifestError, match="MB"):
        loader.read_manifest(folder, builtin=False)


def test_list_looks_skips_broken_and_keeps_builtin_first(tmp_path: Path) -> None:
    looks_root = tmp_path / "looks"
    _write_pack(looks_root, "good-look", name="A Good Look")
    broken = _write_pack(looks_root, "broken-look")
    (broken / "look.json").write_text("{not json", encoding="utf-8")
    # Same id as the built-in example: the built-in one wins.
    _write_pack(looks_root, "pulse-ring", name="Impostor")

    looks = loader.list_looks(data_dir=tmp_path)
    ids = [m.id for m in looks]
    assert ids[0] == "pulse-ring" and looks[0].builtin
    assert "good-look" in ids
    assert "broken-look" not in ids
    assert ids.count("pulse-ring") == 1


def test_find_look_dir_refuses_bad_ids(tmp_path: Path) -> None:
    _write_pack(tmp_path / "looks", "good-look")
    assert loader.find_look_dir("good-look", data_dir=tmp_path) is not None
    for bad in ("../looks", "..", "good-look/../x", "", "GOOD"):
        assert loader.find_look_dir(bad, data_dir=tmp_path) is None


def test_resolve_file_stays_in_pack(tmp_path: Path) -> None:
    folder = _write_pack(tmp_path)
    (tmp_path / "outside.js").write_text("x", encoding="utf-8")

    found = loader.resolve_file(folder, "index.html")
    assert found is not None and found[1].startswith("text/html")
    assert loader.resolve_file(folder, "../outside.js") is None
    assert loader.resolve_file(folder, "missing.js") is None
    assert loader.resolve_file(folder, "look.exe") is None


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_links_are_refused(tmp_path: Path) -> None:
    folder = _write_pack(tmp_path)
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    (folder / "leak.txt").symlink_to(tmp_path / "secret.txt")
    with pytest.raises(LookManifestError, match="link"):
        loader.read_manifest(folder, builtin=False)
    assert loader.resolve_file(folder, "leak.txt") is None


def test_builtin_example_is_valid() -> None:
    folder = loader.builtin_root() / "pulse-ring"
    manifest = loader.read_manifest(folder, builtin=True)
    assert manifest.builtin
    html = (folder / manifest.entry).read_text(encoding="utf-8")
    # The example must not load anything from the network.
    assert "http://" not in html and "https://" not in html
    assert "look:ready" in html
