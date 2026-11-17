"""Tiny media files made on the fly, so the clip tests need no fixtures on disk."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")


def write_video(
    path: Path,
    *,
    seconds: float = 2.0,
    size: tuple[int, int] = (64, 36),
    fps: int = 24,
    tone: bool = True,
    codec: str = "libx264",
) -> Path:
    """A short video: a moving gradient, with a 440 Hz tone when ``tone``."""
    width, height = size
    with av.open(str(path), "w") as writer:
        video = writer.add_stream(codec, rate=fps)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        audio = None
        if tone:
            audio = writer.add_stream("aac", rate=48_000)
            audio.layout = "stereo"
        for index in range(int(seconds * fps)):
            shade = np.full((height, width, 3), (index * 9) % 255, dtype=np.uint8)
            shade[:, : width // 2, 0] = 255
            frame = av.VideoFrame.from_ndarray(shade, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, fps)
            for packet in video.encode(frame):
                writer.mux(packet)
        for packet in video.encode(None):
            writer.mux(packet)
        if audio is not None:
            write_tone(writer, audio, [(seconds, 0.5)])
    return path


def write_tone(writer, stream, parts) -> None:
    """Encode ``parts`` [(seconds, amplitude)] of a 440 Hz tone into ``stream``."""
    rate = 48_000
    chunks = []
    for seconds, amplitude in parts:
        t = np.arange(int(seconds * rate)) / rate
        chunks.append((amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32))
    mono = np.concatenate(chunks)
    samples = np.vstack([mono, mono])
    step = 1024
    for at in range(0, samples.shape[1], step):
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(samples[:, at : at + step]), format="fltp", layout="stereo"
        )
        frame.sample_rate = rate
        frame.pts, frame.time_base = at, Fraction(1, rate)
        for packet in stream.encode(frame):
            writer.mux(packet)
    for packet in stream.encode(None):
        writer.mux(packet)


def write_sound(path: Path, parts) -> Path:
    """A sound file of tone and silence parts [(seconds, amplitude)]."""
    with av.open(str(path), "w", format="ipod" if path.suffix == ".m4a" else None) as writer:
        stream = writer.add_stream("aac", rate=48_000)
        stream.layout = "stereo"
        write_tone(writer, stream, parts)
    return path


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    return write_video(tmp_path / "take.mp4")


@pytest.fixture
def node_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "run__node__abc"
    folder.mkdir()
    return folder
