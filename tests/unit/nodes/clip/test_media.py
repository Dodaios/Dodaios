"""Taking files into a clip's library (``dodaios/nodes/clip/media.py``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.nodes.clip import media
from dodaios.nodes.kinds import motion_media

from .conftest import av, write_sound, write_video


def test_a_playable_video_is_copied_with_its_poster_strip_and_waveform(
    node_dir: Path, video_file: Path
) -> None:
    media_id, entry = media.import_media(node_dir, video_file, "My take.mp4")

    assert entry == {
        "name": "My take.mp4",
        "file": f"{media_id}.mp4",
        "kind": "video",
        "seconds": 2.0,
        "width": 64,
        "height": 36,
        "audio": True,
    }
    # The spec keeps the entry exactly as the import wrote it.
    assert motion_media.normalize_media({media_id: entry}) == {media_id: entry}
    folder = media.media_dir(node_dir)
    assert (folder / entry["file"]).read_bytes() == video_file.read_bytes()
    from PIL import Image

    with Image.open(media.side_file(node_dir, media_id, "strip")) as strip:
        assert strip.height == media.STRIP_HEIGHT
        assert strip.width == media.STRIP_FRAMES * round(64 * media.STRIP_HEIGHT / 36)
    assert media.side_file(node_dir, media_id, "poster").is_file()
    wave = json.loads(media.side_file(node_dir, media_id, "wave").read_text(encoding="utf-8"))
    assert wave["rate"] == media.WAVE_RATE
    assert 95 <= len(wave["peaks"]) <= 105 and max(wave["peaks"]) == 1.0


def test_a_video_a_browser_cannot_play_is_converted_to_h264(node_dir: Path, tmp_path: Path) -> None:
    source = write_video(tmp_path / "old.avi", codec="mpeg4")

    media_id, entry = media.import_media(node_dir, source)

    assert entry["file"] == f"{media_id}.mp4" and entry["kind"] == "video"
    with av.open(str(media.media_dir(node_dir) / entry["file"])) as reader:
        assert reader.streams.video[0].codec_context.name == "h264"
        assert reader.streams.audio[0].codec_context.name == "aac"


def test_a_sound_file_is_kept_and_gets_a_waveform(node_dir: Path, tmp_path: Path) -> None:
    source = write_sound(tmp_path / "music.m4a", [(1.5, 0.5)])

    media_id, entry = media.import_media(node_dir, source)

    assert entry["kind"] == "audio" and entry["file"] == f"{media_id}.m4a"
    assert entry["audio"] is True and entry["width"] == 0 and 1.4 < entry["seconds"] < 1.6
    assert media.side_file(node_dir, media_id, "wave").is_file()
    assert not media.side_file(node_dir, media_id, "poster").exists()


def test_a_picture_is_kept_and_a_turned_photo_is_stored_upright(
    node_dir: Path, tmp_path: Path
) -> None:
    from PIL import Image

    plain = tmp_path / "logo.png"
    Image.new("RGB", (40, 20), "red").save(plain)
    media_id, entry = media.import_media(node_dir, plain)
    assert entry == {
        "name": "logo.png",
        "file": f"{media_id}.png",
        "kind": "image",
        "width": 40,
        "height": 20,
        "seconds": 0,
        "audio": False,
    }

    turned = tmp_path / "phone.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # shot with the phone held upright
    Image.new("RGB", (40, 20), "blue").save(turned, exif=exif)
    _, upright = media.import_media(node_dir, turned)
    assert (upright["width"], upright["height"]) == (20, 40)
    assert upright["file"].endswith(".png")


def test_what_is_not_media_is_refused_and_leaves_nothing(node_dir: Path, tmp_path: Path) -> None:
    junk = tmp_path / "notes.mp4"
    junk.write_text("not a video", encoding="utf-8")
    with pytest.raises(media.MediaError, match="can read"):
        media.import_media(node_dir, junk)
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")
    with pytest.raises(media.MediaError, match="empty"):
        media.import_media(node_dir, empty)
    with pytest.raises(media.MediaError):
        media.import_media(node_dir, tmp_path / "missing.mp4")
    folder = media.media_dir(node_dir)
    assert not folder.exists() or not any(folder.iterdir())


def test_only_library_names_reach_a_file(node_dir: Path, video_file: Path) -> None:
    media_id, entry = media.import_media(node_dir, video_file)

    assert media.media_file(node_dir, entry["file"]) is not None
    assert media.media_file(node_dir, f"{media_id}.poster.jpg") is not None
    assert media.media_file(node_dir, f"{media_id}.wave.json") is not None
    for name in ("../state.json", f"{media_id}.exe", "state.json", "", f"{media_id}.mp4/x"):
        assert media.media_file(node_dir, name) is None
    assert media.library_file(node_dir, media_id) == media.media_dir(node_dir) / entry["file"]
    assert media.library_file(node_dir, "../x") is None


def test_a_copied_library_holds_the_same_files(
    node_dir: Path, video_file: Path, tmp_path: Path
) -> None:
    media_id, entry = media.import_media(node_dir, video_file)
    copy = tmp_path / "copy"
    copy.mkdir()

    media.copy_library(node_dir, copy)

    assert media.media_file(copy, entry["file"]) is not None
    media.remove_media(copy, media_id)
    assert media.media_file(copy, entry["file"]) is None
    assert media.media_file(node_dir, entry["file"]) is not None


def test_read_audio_cuts_the_range_exactly(tmp_path: Path) -> None:
    source = write_sound(tmp_path / "s.m4a", [(1.0, 0.5), (1.0, 0.0)])

    loud = media.read_audio(source, 0.2, 0.7, rate=16_000)
    quiet = media.read_audio(source, 1.3, 1.8, rate=16_000)

    assert loud.shape == (1, 8_000) and quiet.shape == (1, 8_000)
    assert abs(loud).max() > 0.3 and abs(quiet).max() < 0.05
