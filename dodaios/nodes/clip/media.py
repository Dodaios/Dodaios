"""A clip's media library: the files a person or the assistant put into it.

A file is never used from where it was found: the page plays only what is in
the node's own folder (``<run>/media``), so a clip keeps working when the
original is moved, and the ``/clip-media`` route serves nothing else. Each
file gets a random id (the page's link to it is that id, nothing guessable)
and three small companions the editor draws its timeline from:

* ``<id>.poster.jpg``: one still (videos and pictures);
* ``<id>.strip.jpg``: a filmstrip of a dozen frames side by side (videos);
* ``<id>.wave.json``: the loudness of the sound, ``rate`` peaks per second.

A video the browser cannot play (HEVC from a phone, ProRes, an AVI) is
converted to H.264 with AAC sound on import, at most 1080p, because the
preview and the export both play it in a browser. Sound in a form browsers
do not read (FLAC, AIFF, ...) becomes AAC. Everything else is copied as it is.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

MEDIA_DIR: Final[str] = "media"
#: Larger files are refused before anything is read.
MAX_FILE_BYTES: Final[int] = 4 * 1024**3
#: The filmstrip: frames, and their height in pixels.
STRIP_FRAMES: Final[int] = 12
STRIP_HEIGHT: Final[int] = 96
#: The longest side of a poster.
POSTER_SIDE: Final[int] = 640
#: Waveform peaks per second of sound.
WAVE_RATE: Final[int] = 50
#: The longest side of a converted video (1080p).
CONVERT_SIDE: Final[int] = 1920

#: Video codecs every Chromium build plays, and containers it reads.
_PLAYABLE_VIDEO: Final[frozenset[str]] = frozenset({"h264", "vp8", "vp9", "av1"})
_PLAYABLE_SOUND_IN_VIDEO: Final[frozenset[str]] = frozenset({"aac", "mp3", "opus", "vorbis"})
_VIDEO_SUFFIXES: Final[dict[str, str]] = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mov": "mp4",
    ".webm": "webm",
}
#: Sound files kept as they are: their ending, and the codecs that may be in them.
_SOUND_FILES: Final[dict[str, tuple[str, frozenset[str]]]] = {
    ".mp3": ("mp3", frozenset({"mp3"})),
    ".m4a": ("m4a", frozenset({"aac"})),
    ".aac": ("aac", frozenset({"aac"})),
    ".wav": ("wav", frozenset({"pcm_s16le", "pcm_s24le", "pcm_f32le", "pcm_u8"})),
    ".ogg": ("ogg", frozenset({"vorbis", "opus"})),
    ".oga": ("oga", frozenset({"vorbis", "opus"})),
    ".opus": ("opus", frozenset({"opus"})),
}
_PICTURE_FORMATS: Final[dict[str, str]] = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
    "GIF": "gif",
}

#: A library file and its companions, as the page and the editor name them.
_FILE_RE: Final = re.compile(
    r"^[0-9a-f]{16,32}"
    r"(\.(mp4|webm|mov|m4v|m4a|mp3|wav|aac|ogg|oga|opus|png|jpg|jpeg|webp|gif)"
    r"|\.poster\.jpg|\.strip\.jpg|\.wave\.json)$"
)


class MediaError(ValueError):
    """A file cannot be taken into the library; the message is for the person."""


def media_dir(node_dir: Path) -> Path:
    """The folder of a node's library files (not created here)."""
    return node_dir / MEDIA_DIR


def media_file(node_dir: Path, file_name: str) -> Path | None:
    """The library file ``file_name`` names, or ``None`` for any other name or a missing file."""
    if not isinstance(file_name, str) or not _FILE_RE.match(file_name):
        return None
    path = media_dir(node_dir) / file_name
    return path if path.is_file() else None


def library_file(node_dir: Path, media_id: str) -> Path | None:
    """The library file of ``media_id`` (not its companions), or ``None``."""
    if not re.fullmatch(r"[0-9a-f]{16,32}", media_id or ""):
        return None
    for path in media_dir(node_dir).glob(f"{media_id}.*"):
        if path.name.count(".") == 1 and _FILE_RE.match(path.name):
            return path
    return None


def side_file(node_dir: Path, media_id: str, kind: str) -> Path:
    """Where a companion (``poster``, ``strip``, ``wave``) of ``media_id`` is kept."""
    suffix = {"poster": ".poster.jpg", "strip": ".strip.jpg", "wave": ".wave.json"}[kind]
    return media_dir(node_dir) / f"{media_id}{suffix}"


# --- decoding --------------------------------------------------------------------


def read_audio(
    path: Path,
    start: float = 0.0,
    end: float | None = None,
    *,
    rate: int = 16_000,
    channels: int = 1,
) -> Any:
    """The sound of ``path`` from ``start`` to ``end`` seconds as float32 samples.

    Returns an array of shape ``(channels, n)``; a file without sound gives
    zero samples. The cut is sample-exact: the decoder seeks to the keyframe
    before ``start`` and the samples before it are dropped.
    """
    import av
    import numpy as np

    layout = "mono" if channels == 1 else "stereo"
    parts: list[Any] = []
    with av.open(str(path)) as reader:
        if not reader.streams.audio:
            return np.zeros((channels, 0), dtype=np.float32)
        stream = reader.streams.audio[0]
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=rate)
        if start > 0 and stream.time_base:
            reader.seek(max(0, int(start / stream.time_base)), stream=stream, backward=True)
        first = int(round(start * rate))
        last = None if end is None else int(round(end * rate))
        cursor: int | None = None
        done = False

        def take(frame: Any) -> bool:
            nonlocal cursor
            data = frame.to_ndarray().astype(np.float32, copy=False)
            if frame.pts is not None:
                at = int(round(float(frame.pts * frame.time_base) * rate))
            else:
                at = cursor if cursor is not None else first
            if cursor is not None and abs(at - cursor) < rate // 50:
                at = cursor  # timestamp jitter: keep the samples contiguous
            cursor = at + data.shape[1]
            left = max(0, first - at)
            right = data.shape[1] if last is None else min(data.shape[1], last - at)
            if right > left:
                parts.append(data[:, left:right])
            return last is not None and at + data.shape[1] >= last

        for frame in reader.decode(stream):
            for converted in resampler.resample(frame):
                done = take(converted) or done
            if done:
                break
        if not done:
            for converted in resampler.resample(None):
                take(converted)
    if not parts:
        return np.zeros((channels, 0), dtype=np.float32)
    return np.concatenate(parts, axis=1)


def waveform(samples: Any, rate: int, peaks_per_second: int = WAVE_RATE) -> list[float]:
    """Loudness peaks of mono ``samples``, scaled so the loudest is 1."""
    import numpy as np

    mono = np.abs(samples[0] if samples.ndim == 2 else samples)
    window = max(1, rate // peaks_per_second)
    count = int(np.ceil(mono.shape[0] / window)) if mono.shape[0] else 0
    if count == 0:
        return []
    padded = np.zeros(count * window, dtype=np.float32)
    padded[: mono.shape[0]] = mono
    peaks = padded.reshape(count, window).max(axis=1)
    top = float(peaks.max()) or 1.0
    return [round(float(value) / top, 3) for value in peaks]


# --- probing ---------------------------------------------------------------------


def _rotation(frame: Any) -> int:
    """How far a phone video's frames are turned for display (0, 90, 180, 270)."""
    value = getattr(frame, "rotation", 0) or 0
    try:
        return int(round(float(value))) % 360
    except (TypeError, ValueError):  # no readable rotation tag: the picture is upright
        return 0


def _image_of(frame: Any) -> Any:
    """A decoded frame as an upright Pillow picture."""
    image = frame.to_image()
    turn = _rotation(frame)
    # FFmpeg's display rotation is counter-clockwise; Pillow's rotate is too.
    return image.rotate(turn, expand=True) if turn else image


def _probe(path: Path) -> dict[str, Any]:
    """What a media file holds: streams, codecs, length, size, rotation."""
    import av

    try:
        reader = av.open(str(path))
    except (av.error.FFmpegError, OSError) as exc:
        raise MediaError("This file is not a video, sound or picture Dodaios can read.") from exc
    with reader:
        info: dict[str, Any] = {"format": reader.format.name or "", "video": None, "audio": None}
        seconds = float(reader.duration / 1_000_000) if reader.duration else 0.0
        if reader.streams.video:
            stream = reader.streams.video[0]
            context = stream.codec_context
            rotation = 0
            try:
                for frame in reader.decode(stream):
                    rotation = _rotation(frame)
                    break
            except av.error.FFmpegError:
                log.debug("clip media: first frame of %s not decodable", path.name)
            width, height = int(context.width or 0), int(context.height or 0)
            if rotation in (90, 270):
                width, height = height, width
            if not seconds and stream.duration and stream.time_base:
                seconds = float(stream.duration * stream.time_base)
            info["video"] = {
                "codec": context.name or "",
                "width": width,
                "height": height,
                "rotation": rotation,
                "frames": int(stream.frames or 0),
            }
        if reader.streams.audio:
            stream = reader.streams.audio[0]
            if not seconds and stream.duration and stream.time_base:
                seconds = float(stream.duration * stream.time_base)
            info["audio"] = {"codec": stream.codec_context.name or ""}
        info["seconds"] = seconds
    return info


# --- writing ---------------------------------------------------------------------


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def _convert_video(source: Path, target: Path, info: dict[str, Any]) -> None:
    """Write ``source`` as H.264 (and AAC) in MP4, upright, at most 1080p."""
    import av
    import numpy as np

    video = info["video"]
    width, height = video["width"], video["height"]
    scale = min(1.0, CONVERT_SIDE / max(width, height, 1))
    out_w, out_h = _even(width * scale), _even(height * scale)
    turn = int(video.get("rotation") or 0)
    partial = target.with_suffix(".partial")
    try:
        with av.open(str(source)) as reader, av.open(str(partial), "w", format="mp4") as writer:
            stream_in = reader.streams.video[0]
            stream_in.thread_type = "AUTO"
            rate = Fraction(stream_in.average_rate or 30).limit_denominator(1001)
            codec = "libx264" if "libx264" in av.codecs_available else "mpeg4"
            options = {"preset": "veryfast", "crf": "20"} if codec == "libx264" else {}
            out = writer.add_stream(codec, rate=rate, options=options)
            out.width, out.height, out.pix_fmt = out_w, out_h, "yuv420p"
            sound = None
            if reader.streams.audio:
                sound = writer.add_stream("aac", rate=48_000)
                sound.layout = "stereo"
                sound.bit_rate = 192_000
            time_base = 1 / rate
            index = 0
            for frame in reader.decode(stream_in):
                if turn:
                    picture = np.rot90(frame.to_ndarray(format="rgb24"), k=turn // 90)
                    frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(picture), "rgb24")
                made = frame.reformat(width=out_w, height=out_h, format="yuv420p")
                made.pts, made.time_base = index, time_base
                index += 1
                for packet in out.encode(made):
                    writer.mux(packet)
            for packet in out.encode(None):
                writer.mux(packet)
            if sound is not None:
                _write_sound(source, writer, sound)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def _write_sound(source: Path, writer: Any, stream: Any) -> None:
    """Encode the whole sound of ``source`` into ``stream`` (48 kHz stereo AAC)."""
    import av

    samples = read_audio(source, rate=48_000, channels=2)
    step = 1024 * 32
    for at in range(0, samples.shape[1], step):
        frame = av.AudioFrame.from_ndarray(
            samples[:, at : at + step].copy(order="C"), format="fltp", layout="stereo"
        )
        frame.sample_rate = 48_000
        frame.pts, frame.time_base = at, Fraction(1, 48_000)
        for packet in stream.encode(frame):
            writer.mux(packet)
    for packet in stream.encode(None):
        writer.mux(packet)


def _convert_sound(source: Path, target: Path) -> None:
    import av

    partial = target.with_suffix(".partial")
    try:
        with av.open(str(partial), "w", format="ipod") as writer:
            stream = writer.add_stream("aac", rate=48_000)
            stream.layout = "stereo"
            stream.bit_rate = 192_000
            _write_sound(source, writer, stream)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def _frame_at(path: Path, seconds: float) -> Any | None:
    """The upright picture shown at ``seconds`` (the nearest decodable frame)."""
    import av

    with av.open(str(path)) as reader:
        stream = reader.streams.video[0]
        if seconds > 0 and stream.time_base:
            reader.seek(int(seconds / stream.time_base), stream=stream, backward=True)
        found = None
        for frame in reader.decode(stream):
            found = frame
            if frame.pts is None or float(frame.pts * frame.time_base) >= seconds - 0.02:
                break
        return _image_of(found) if found is not None else None


def _write_video_pictures(node_dir: Path, media_id: str, path: Path, seconds: float) -> None:
    from PIL import Image

    poster = _frame_at(path, min(1.0, seconds * 0.1))
    if poster is None:
        return
    still = poster.convert("RGB")
    still.thumbnail((POSTER_SIDE, POSTER_SIDE))
    still.save(side_file(node_dir, media_id, "poster"), "JPEG", quality=82)
    width = max(1, round(poster.width * STRIP_HEIGHT / max(1, poster.height)))
    strip = Image.new("RGB", (width * STRIP_FRAMES, STRIP_HEIGHT))
    for index in range(STRIP_FRAMES):
        at = seconds * (index + 0.5) / STRIP_FRAMES
        picture = (_frame_at(path, at) if index else poster) or poster
        strip.paste(picture.convert("RGB").resize((width, STRIP_HEIGHT)), (index * width, 0))
    strip.save(side_file(node_dir, media_id, "strip"), "JPEG", quality=74)


def _write_wave(node_dir: Path, media_id: str, path: Path) -> None:
    rate = 8_000
    peaks = waveform(read_audio(path, rate=rate), rate)
    side_file(node_dir, media_id, "wave").write_text(
        json.dumps({"rate": WAVE_RATE, "peaks": peaks}, separators=(",", ":")),
        encoding="utf-8",
    )


def _import_picture(node_dir: Path, media_id: str, source: Path) -> tuple[str, dict[str, Any]]:
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(source) as opened:
            kind = opened.format or ""
            upright = ImageOps.exif_transpose(opened)
            width, height = upright.size
            ending = _PICTURE_FORMATS.get(kind)
            target_dir = media_dir(node_dir)
            if ending and upright is opened:
                target = target_dir / f"{media_id}.{ending}"
                shutil.copyfile(source, target)
            else:
                # A turned photo, or a format browsers do not show: a PNG of it.
                ending = "png"
                target = target_dir / f"{media_id}.png"
                upright.save(target, "PNG")
            poster = upright.convert("RGB")
            poster.thumbnail((POSTER_SIDE, POSTER_SIDE))
            poster.save(side_file(node_dir, media_id, "poster"), "JPEG", quality=82)
    except (UnidentifiedImageError, OSError) as exc:
        raise MediaError("This picture cannot be read.") from exc
    return target.name, {
        "kind": "image",
        "width": width,
        "height": height,
        "seconds": 0,
        "audio": False,
    }


def import_media(
    node_dir: Path, source: Path, name: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Take ``source`` into the node's library; returns its id and its library entry.

    The entry is what the spec's ``media`` map keeps for the id
    (:func:`dodaios.nodes.kinds.motion_media.normalize_media`). Raises
    :class:`MediaError` with a sentence for the person when the file is too
    large or not media. Blocking: decodes and may convert the whole file.
    """
    source = Path(source)
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise MediaError(f"The file {source.name!r} cannot be opened.") from exc
    if not source.is_file():
        raise MediaError(f"{source.name!r} is not a file.")
    if size > MAX_FILE_BYTES:
        raise MediaError("This file is larger than 4 GB; shorten or compress it first.")
    if size == 0:
        raise MediaError("This file is empty.")
    folder = media_dir(node_dir)
    folder.mkdir(parents=True, exist_ok=True)
    media_id = secrets.token_hex(12)
    shown = " ".join(str(name or source.name).split())[:120] or source.name
    suffix = source.suffix.lower()
    made: list[Path] = []
    try:
        if suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"):
            file_name, entry = _import_picture(node_dir, media_id, source)
            made.append(folder / file_name)
            return media_id, {"name": shown, "file": file_name, **entry}
        info = _probe(source)
        if info["video"] is None and info["audio"] is None:
            raise MediaError("This file holds neither pictures nor sound.")
        seconds = round(float(info["seconds"]), 3)
        if info["video"] is not None:
            video = info["video"]
            sound_codec = (info["audio"] or {}).get("codec", "")
            playable = (
                suffix in _VIDEO_SUFFIXES
                and video["codec"] in _PLAYABLE_VIDEO
                and (info["audio"] is None or sound_codec in _PLAYABLE_SOUND_IN_VIDEO)
                and not video["rotation"]
            )
            ending = _VIDEO_SUFFIXES.get(suffix, "mp4") if playable else "mp4"
            target = folder / f"{media_id}.{ending}"
            made.append(target)
            if playable:
                shutil.copyfile(source, target)
            else:
                log.info("clip media: converting %s (%s) to H.264", source.name, video["codec"])
                _convert_video(source, target, info)
            _write_video_pictures(node_dir, media_id, target, seconds)
            if info["audio"] is not None:
                _write_wave(node_dir, media_id, target)
            entry = {
                "kind": "video",
                "seconds": seconds,
                "width": int(video["width"]),
                "height": int(video["height"]),
                "audio": info["audio"] is not None,
            }
        else:
            codec = info["audio"]["codec"]
            kept = _SOUND_FILES.get(suffix)
            if kept and codec in kept[1]:
                target = folder / f"{media_id}.{kept[0]}"
                made.append(target)
                shutil.copyfile(source, target)
            else:
                target = folder / f"{media_id}.m4a"
                made.append(target)
                _convert_sound(source, target)
            _write_wave(node_dir, media_id, target)
            entry = {"kind": "audio", "seconds": seconds, "width": 0, "height": 0, "audio": True}
        return media_id, {"name": shown, "file": target.name, **entry}
    except MediaError:
        _discard(node_dir, media_id)
        raise
    except Exception as exc:
        _discard(node_dir, media_id)
        log.exception("clip media: %s could not be imported", source.name)
        raise MediaError(f"{source.name!r} could not be imported: {exc}") from exc


def _discard(node_dir: Path, media_id: str) -> None:
    """Remove every file of a library id (a failed import leaves nothing behind)."""
    for path in media_dir(node_dir).glob(f"{media_id}.*"):
        path.unlink(missing_ok=True)


def remove_media(node_dir: Path, media_id: str) -> None:
    """Delete a library file and its companions."""
    if re.fullmatch(r"[0-9a-f]{16,32}", media_id or ""):
        _discard(node_dir, media_id)


def copy_library(source_dir: Path, target_dir: Path) -> None:
    """Copy a node's whole library (a duplicated clip plays the same files)."""
    origin = media_dir(source_dir)
    if origin.is_dir():
        shutil.copytree(origin, media_dir(target_dir), dirs_exist_ok=True)


__all__ = [
    "MAX_FILE_BYTES",
    "MEDIA_DIR",
    "MediaError",
    "copy_library",
    "import_media",
    "library_file",
    "media_dir",
    "media_file",
    "read_audio",
    "remove_media",
    "side_file",
    "waveform",
]
