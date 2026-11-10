"""Installing looks from the marketplace: checksum, zip safety, replace, remove."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from dodaios.marketplace.community_source import CommunityIndex
from dodaios.ui.looks import install
from dodaios.ui.looks.install import LookInstallError, allowed_url, install_archive

LOOK_ID = "neat-ring"


def _files(look_id: str = LOOK_ID, version: str = "1.0.0") -> dict[str, bytes]:
    manifest = {
        "format": "dodaios-look/1",
        "id": look_id,
        "name": "Neat Ring",
        "author": "Someone",
        "version": version,
        "license": "Apache-2.0 AND CC-BY-4.0",
        "preview": "preview.png",
    }
    return {
        "look.json": json.dumps(manifest).encode(),
        "index.html": b"<!doctype html><p>ring</p>",
        "preview.png": b"\x89PNG\r\n\x1a\n",
        "assets/core.glb": b"glTF",
    }


def _zip(files: dict[str, bytes], *, top: str = "", links: tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in files.items():
            archive.writestr(top + name, data)
        for name in links:
            info = zipfile.ZipInfo(top + name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../secret")
    return buf.getvalue()


def _install(data: bytes, tmp_path: Path, look_id: str = LOOK_ID):
    return install_archive(
        data, look_id=look_id, sha256=hashlib.sha256(data).hexdigest(), data_dir=tmp_path
    )


@pytest.mark.parametrize("top", ["", "neat-ring-1.0.0/"])
def test_install_unpacks_a_valid_pack(tmp_path: Path, top: str) -> None:
    manifest = _install(_zip(_files(), top=top), tmp_path)
    assert manifest.id == LOOK_ID
    assert (tmp_path / "looks" / LOOK_ID / "assets" / "core.glb").read_bytes() == b"glTF"
    assert install.installed_ids(data_dir=tmp_path) == {LOOK_ID}
    # No staging debris is left behind.
    assert [p.name for p in (tmp_path / "looks").iterdir()] == [LOOK_ID]


def test_checksum_mismatch_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LookInstallError, match="checksum"):
        install_archive(_zip(_files()), look_id=LOOK_ID, sha256="0" * 64, data_dir=tmp_path)
    assert install.installed_ids(data_dir=tmp_path) == frozenset()


@pytest.mark.parametrize(
    "bad_name",
    ["../escape.js", "/abs.js", "a/../../b.js", "C:/x.js", "a\..\..\b.js"],
)
def test_path_tricks_are_refused(tmp_path: Path, bad_name: str) -> None:
    files = _files() | {bad_name: b"x"}
    with pytest.raises(LookInstallError):
        _install(_zip(files), tmp_path)
    assert not (tmp_path / "escape.js").exists()


def test_links_are_refused(tmp_path: Path) -> None:
    with pytest.raises(LookInstallError, match="link"):
        _install(_zip(_files(), links=("leak.txt",)), tmp_path)


def test_disallowed_file_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LookInstallError, match="not valid"):
        _install(_zip(_files() | {"run.exe": b"MZ"}), tmp_path)


def test_unpacked_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install, "MAX_PACK_BYTES", 1000)
    files = _files() | {"big.bin": b"\0" * 5000}  # compresses to almost nothing
    with pytest.raises(LookInstallError, match="MB"):
        _install(_zip(files), tmp_path)


def test_file_count_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install, "MAX_PACK_FILES", 3)
    with pytest.raises(LookInstallError, match="at most 3"):
        _install(_zip(_files()), tmp_path)


def test_id_must_match_the_entry(tmp_path: Path) -> None:
    with pytest.raises(LookInstallError, match="not valid"):
        _install(_zip(_files(look_id="other-ring")), tmp_path)


def test_builtin_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LookInstallError, match="built-in"):
        _install(_zip(_files(look_id="pulse-ring")), tmp_path, look_id="pulse-ring")


def test_not_a_zip(tmp_path: Path) -> None:
    with pytest.raises(LookInstallError, match="zip"):
        _install(b"not a zip at all", tmp_path)


def test_reinstall_replaces_and_uninstall_removes(tmp_path: Path) -> None:
    _install(_zip(_files(version="1.0.0")), tmp_path)
    assert _install(_zip(_files(version="1.1.0")), tmp_path).version == "1.1.0"
    assert install.uninstall(LOOK_ID, data_dir=tmp_path) is True
    assert install.installed_ids(data_dir=tmp_path) == frozenset()
    assert install.uninstall(LOOK_ID, data_dir=tmp_path) is False
    assert install.uninstall("../looks", data_dir=tmp_path) is False


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://github.com/a/b/releases/download/v1/x.zip", True),
        ("https://raw.githubusercontent.com/a/b/main/p.png", True),
        ("http://github.com/a/b.zip", False),
        ("https://evil.example/x.zip", False),
        ("https://github.com.evil.example/x.zip", False),
        ("https://user:pw@github.com/x.zip", False),
        ("https://github.com:8443/x.zip", False),
        ("https://127.0.0.1/x.zip", False),
    ],
)
def test_allowed_url(url: str, ok: bool) -> None:
    assert allowed_url(url) is ok


def test_index_keeps_good_looks_and_drops_bad_ones() -> None:
    good = {
        "name": LOOK_ID,
        "archive_url": "https://github.com/a/b/releases/download/v1/neat-ring.zip",
        "preview_url": "https://evil.example/p.png",
        "sha256": "A" * 64,
        "size_bytes": 1000,
    }
    index = CommunityIndex.model_validate(
        {
            "looks": [
                good,
                good | {"name": "x2", "archive_url": "http://github.com/x.zip"},
                good | {"name": "orb"},
                good | {"name": "x3", "sha256": "nothex"},
                good | {"name": "x4", "size_bytes": 10**9},
                "not even an object",
            ]
        }
    )
    assert [look.name for look in index.looks] == [LOOK_ID]
    assert index.looks[0].preview_url is None  # foreign host: dropped, never fetched
    assert index.looks[0].sha256 == "a" * 64
    assert CommunityIndex.model_validate({}).looks == []


@pytest.mark.parametrize(
    "extra",
    [{"INDEX.html": b"x"}, {"assets": b"file", "assets/x.js": b"y"}],
    ids=["case-clash", "file-and-folder"],
)
def test_clashing_names_are_refused(tmp_path: Path, extra: dict[str, bytes]) -> None:
    with pytest.raises(LookInstallError, match="clashing|file and a folder"):
        _install(_zip(_files() | extra), tmp_path)
