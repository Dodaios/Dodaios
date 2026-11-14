"""A whiteboard's pictures: data URLs in, sniffed bytes on disk, limits."""

from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path

import pytest

from dodaios.nodes.board import files
from dodaios.nodes.types import NodeError

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcff9f010005fe02fea7d6a4b90000000049454e44ae426082"
)
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00"
    b"\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 " + b"\x00" * 14
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _url(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


@pytest.mark.parametrize(
    ("data", "mime"),
    [(PNG, "image/png"), (GIF, "image/gif"), (JPEG, "image/jpeg"), (WEBP, "image/webp")],
)
def test_the_type_is_read_from_the_bytes_not_the_claim(data: bytes, mime: str) -> None:
    assert files.sniff(data) == mime
    # The data URL claims another type; the bytes decide.
    assert files.decode_data_url(_url(data, "image/svg+xml")) == (data, mime)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (_url(SVG, "image/svg+xml"), "PNG, JPEG, GIF and WebP"),
        (_url(b"%PDF-1.4"), "PNG, JPEG, GIF and WebP"),
        ("https://example.com/a.png", "base64 data URL"),
        ("data:image/png,raw", "base64 data URL"),
        ("data:image/png;base64,@@@", "no valid base64"),
        ("data:image/png;base64,", "empty file"),
        (12, "at most"),
    ],
)
def test_anything_but_a_raster_picture_is_refused(value: object, reason: str) -> None:
    with pytest.raises(NodeError, match=reason):
        files.decode_data_url(value)  # type: ignore[arg-type]


def test_a_picture_over_five_megabytes_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "MAX_FILE_BYTES", 100)
    with pytest.raises(NodeError, match="larger than"):
        files.decode_data_url(_url(PNG + b"\x00" * 200))
    huge = "data:image/png;base64," + "A" * (files.MAX_DATA_URL_CHARS + 1)
    with pytest.raises(NodeError, match="at most"):
        files.decode_data_url(huge)


def test_a_picture_is_kept_under_a_hash_of_its_id(tmp_path: Path) -> None:
    file_id, mime = files.store_data_url(tmp_path, _url(PNG))
    assert file_id == hashlib.sha1(PNG, usedforsecurity=False).hexdigest() and mime == "image/png"
    stored = list((tmp_path / files.FILES_DIR).iterdir())
    assert [entry.name for entry in stored] == [files.disk_name(file_id)]
    assert file_id not in stored[0].name
    assert files.read(tmp_path, file_id) == (PNG, "image/png")
    # The same picture again is the same file.
    assert files.store_data_url(tmp_path, _url(PNG)) == (file_id, "image/png")


def test_a_chosen_id_is_checked_and_a_taken_one_refuses_other_bytes(tmp_path: Path) -> None:
    assert files.store_data_url(tmp_path, _url(GIF), file_id="pic_1") == ("pic_1", "image/gif")
    assert files.store_data_url(tmp_path, _url(GIF), file_id="pic_1") == ("pic_1", "image/gif")
    with pytest.raises(files.FileConflict, match="different picture"):
        files.store_data_url(tmp_path, _url(PNG), file_id="pic_1")
    for bad in ("../x", "a/b", "", "x" * 101, "a b"):
        with pytest.raises(NodeError, match="'id'"):
            files.store_data_url(tmp_path, _url(PNG), file_id=bad)


def test_reading_a_missing_or_tampered_picture_gives_nothing(tmp_path: Path) -> None:
    assert files.read(tmp_path, "nope") is None
    assert files.read(tmp_path, "../../etc/passwd") is None
    file_id = files.store_bytes(tmp_path, PNG, "image/png")
    (tmp_path / files.FILES_DIR / files.disk_name(file_id)).write_bytes(SVG)
    assert files.read(tmp_path, file_id) is None


def test_the_board_budget_prunes_unnamed_old_pictures_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(files, "MAX_BOARD_BYTES", len(PNG) + len(GIF) + 10)
    kept = files.store_bytes(tmp_path, PNG, "image/png")
    unnamed = files.store_bytes(tmp_path, GIF, "image/gif")
    # Both are fresh: an upload just before the save that names it is safe.
    with pytest.raises(NodeError, match="would pass"):
        files.store_bytes(tmp_path, JPEG, "image/jpeg", keep={kept})
    old = time.time() - files.PRUNE_GRACE_SECONDS - 5
    for entry in (tmp_path / files.FILES_DIR).iterdir():
        os.utime(entry, (old, old))
    new = files.store_bytes(tmp_path, JPEG, "image/jpeg", keep={kept})
    assert files.read(tmp_path, kept) is not None
    assert files.read(tmp_path, unnamed) is None
    assert files.read(tmp_path, new) == (JPEG, "image/jpeg")
    assert files.used_bytes(tmp_path) == len(PNG) + len(JPEG)


def test_without_keep_nothing_is_pruned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files, "MAX_BOARD_BYTES", len(PNG) + 5)
    files.store_bytes(tmp_path, PNG, "image/png")
    with pytest.raises(NodeError, match="would pass"):
        files.store_bytes(tmp_path, GIF, "image/gif")


def test_bytes_must_match_the_type_they_are_stored_as(tmp_path: Path) -> None:
    with pytest.raises(NodeError, match="PNG, JPEG"):
        files.store_bytes(tmp_path, SVG, "image/png")


def test_a_duplicate_board_gets_a_copy_of_every_picture(tmp_path: Path) -> None:
    source, target = tmp_path / "a", tmp_path / "b"
    file_id = files.store_bytes(source, PNG, "image/png")
    (source / files.FILES_DIR / "not-a-picture.txt").write_text("x")
    files.copy_all(source, target)
    assert files.read(target, file_id) == (PNG, "image/png")
    assert not (target / files.FILES_DIR / "not-a-picture.txt").exists()
    files.copy_all(tmp_path / "none", tmp_path / "c")
    assert not (tmp_path / "c").exists()
