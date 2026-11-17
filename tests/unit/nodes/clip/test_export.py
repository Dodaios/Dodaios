"""Writing a clip as an MP4 (``dodaios/nodes/clip/export.py``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dodaios.nodes.clip import export, media
from dodaios.nodes.kinds import motion
from dodaios.nodes.model import Node

from .conftest import av, np, write_sound, write_video

MID = "cd" * 12
SID = "ef" * 12


def test_sizes_follow_the_format_and_the_preset() -> None:
    assert export.output_size("wide", "1080p") == (1920, 1080)
    assert export.output_size("tall", "1080p") == (1080, 1920)
    assert export.output_size("square", "720p") == (720, 720)
    assert export.output_size("portrait", "1080p") == (1080, 1350)
    assert export.output_size("wide", "2160p") == (3840, 2160)


def test_byte_ranges_are_read_as_a_browser_asks_and_capped() -> None:
    size = 20 * 1024 * 1024
    assert export.byte_range("bytes=0-", size) == (0, export.CHUNK_BYTES - 1)
    assert export.byte_range("bytes=100-199", size) == (100, 199)
    assert export.byte_range("bytes=-500", size) == (size - 500, size - 1)
    assert export.byte_range(None, 1000) == (0, 999)
    assert export.byte_range("bytes=5000-", 1000) == (999, 999)


def test_speed_is_split_into_steps_the_tempo_filter_takes() -> None:
    assert export.tempo_chain(0.25) == [0.5, 0.5]
    assert export.tempo_chain(4.0) == [2.0, 2.0]
    assert export.tempo_chain(1.5) == [1.5]
    assert float(np.prod(export.tempo_chain(3.0))) == pytest.approx(3.0)


def test_gains_follow_the_page_volume_fades_and_ducking() -> None:
    sound = export.Sound("f.m4a", 1.0, 5.0, 0.0, 1.0, 0.8, 1.0, 2.0, duck=True)
    times = np.array([0.5, 1.5, 2.0, 3.0, 4.0, 5.5])

    level = export.gains(sound, times, spans=[(2.0, 3.5)])

    # Before and after the item nothing; half way into the fade in, half of
    # 0.8 (speech is still a quarter second away); under speech 30 %; at 4.0
    # speech ended half a second ago and the fade out is at half.
    assert level[0] == 0 and level[-1] == 0
    assert level[1] == pytest.approx(0.4)
    assert level[2] == pytest.approx(0.8 * 0.3)
    assert level[3] == pytest.approx(0.8 * 0.3)
    assert level[4] == pytest.approx(0.8 * 0.5)
    assert export.duck_factor(np.array([1.875]), [(2.0, 3.0)])[0] == pytest.approx(1 - 0.7 * 0.5)


def _spec() -> dict[str, Any]:
    video = {
        "kind": "video",
        "file": f"{MID}.mp4",
        "seconds": 2,
        "width": 64,
        "height": 36,
        "audio": True,
    }
    sound = {"kind": "audio", "file": f"{SID}.m4a", "seconds": 3, "audio": True}
    return motion.normalize(
        {
            "media": {MID: video, SID: sound},
            "scenes": [
                {"type": "video", "media": MID, "seconds": 2, "volume": 0.5},
                {"type": "title", "title": "End", "seconds": 1.5},
            ],
            "tracks": [
                {
                    "kind": "audio",
                    "items": [
                        {"media": SID, "start": 0, "seconds": 3, "volume": 0.6, "duck": True}
                    ],
                },
                {"kind": "audio", "muted": True, "items": [{"media": SID, "start": 1}]},
            ],
        }
    )


def test_everything_heard_is_collected_and_muted_tracks_are_not() -> None:
    sounds = export.sounds_of(_spec())

    assert [(s.file, s.ts, s.te, s.volume, s.duck) for s in sounds] == [
        (f"{MID}.mp4", 0.0, 2.0, 0.5, False),
        (f"{SID}.m4a", 0.0, 3.0, 0.6, True),
    ]


def test_the_mix_puts_each_sound_at_its_time_and_level(tmp_path: Path) -> None:
    folder = tmp_path / "media"
    folder.mkdir()
    write_video(folder / f"{MID}.mp4", seconds=2)
    write_sound(folder / f"{SID}.m4a", [(3.0, 0.5)])

    mixed = export.mix(_spec(), tmp_path, 3.5)

    assert mixed.shape == (2, int(3.5 * export.AUDIO_RATE))

    def peak(a: float, b: float) -> float:
        return float(np.abs(mixed[0, int(a * 48_000) : int(b * 48_000)]).max())

    # The voice at 0.5 * 0.5 plus the music ducked to 0.6 * 0.3 * 0.5; the
    # music alone at 0.6 * 0.5 afterwards; nothing once the music ended.
    assert peak(0.5, 1.5) == pytest.approx(0.25 + 0.09, abs=0.05)
    assert peak(2.5, 2.9) == pytest.approx(0.30, abs=0.04)
    assert peak(3.1, 3.4) < 0.01


def test_speed_keeps_the_length_the_timeline_gives() -> None:
    samples = np.random.default_rng(1).uniform(-0.3, 0.3, (2, 48_000)).astype(np.float32)

    faster = export.change_speed(samples, 2.0)

    assert abs(faster.shape[1] - 24_000) < 1_200


def test_the_page_policy_allows_only_the_clip_media_address() -> None:
    policy = export.page_csp("http://127.0.0.1:47821")

    assert "media-src data: blob: http://127.0.0.1:47821/clip-media/;" in policy
    assert "img-src data: blob: http://127.0.0.1:47821/clip-media/;" in policy
    assert "connect-src 'none'" in policy and "sandbox allow-scripts" in policy


def test_a_job_refuses_an_unknown_quality_or_rate() -> None:
    with pytest.raises(export.ExportError, match="quality"):
        export.start_export(object(), Path("."), {}, "8k", 30)
    with pytest.raises(export.ExportError, match="frame rate"):
        export.start_export(object(), Path("."), {}, "720p", 25)
    assert export.export_status("missing") is None
    assert export.cancel_export("missing") is False


def _browser() -> bool:
    from dodaios.ui.web import artifact_share

    return artifact_share.find_export_browser() is not None


@pytest.mark.skipif(not _browser(), reason="no Chromium-family browser to draw the clip")
def test_a_clip_is_written_as_an_mp4_with_its_picture_and_sound(tmp_path: Path) -> None:
    node_dir = tmp_path / "run__node__abc"
    node_dir.mkdir()
    source = write_video(tmp_path / "take.mp4", seconds=2, size=(160, 90))
    media_id, entry = media.import_media(node_dir, source)
    spec = motion.normalize(
        {
            "format": "tall",
            "media": {media_id: entry},
            "scenes": [{"type": "video", "media": media_id, "seconds": 1.5, "zoom": 1.2}],
            "tracks": [{"kind": "text", "items": [{"text": "Hook", "start": 0, "seconds": 1}]}],
            "captions": {"items": [{"start": 0.2, "end": 1.2, "text": "hello world"}]},
        }
    )
    node = Node(
        id="abc123def456",
        type="motion",
        title="Smoke",
        spec=spec,
        slug="s",
        page_path="p.html",
        created_at=0,
        updated_at=0,
    )

    path = export.export_blocking(node, node_dir, spec, "720p", 24)

    assert path.parent == node_dir / export.EXPORT_DIR and path.suffix == ".mp4"
    with av.open(str(path)) as reader:
        video = reader.streams.video[0]
        assert (video.codec_context.width, video.codec_context.height) == (720, 1280)
        assert video.codec_context.name == "h264"
        assert reader.streams.audio[0].codec_context.name == "aac"
        assert reader.duration / 1_000_000 == pytest.approx(1.5, abs=0.15)
        frame = next(reader.decode(video)).to_ndarray(format="rgb24")
        # The video fills the tall frame: its red half shows, not the dark stage.
        assert frame[:, :, 0].mean() > 80
    stills = export.still_frames(node, node_dir, spec, [0.5], width=360)
    assert len(stills) == 1 and stills[0][:2] == b"\xff\xd8"
