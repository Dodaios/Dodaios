"""A clip as an MP4: the page drawn frame by frame, the sound mixed beside it.

The picture comes from the very page the editor previews and the stage plays
(:func:`dodaios.nodes.kinds.motion.render`), opened in a headless browser with
``?export=1``. For each frame the page is asked to stand at that time
(``window.__clipFrame(t)``, which resolves once every visible video shows its
frame); the stage is then captured and encoded as H.264. What the person saw
in the preview is what the file holds, cards, layers and captions included.

The page reaches its media files at ``/clip-media/...``; here that address is
answered from the node's folder through the browser's request interception,
in pieces as the video element asks for them (byte ranges), so a long take
is never pushed through the DevTools socket whole. Nothing else loads.

The sound is not recorded from the browser: it is mixed here from the same
rules the page plays by (:data:`dodaios.nodes.kinds.motion_media.MEDIA_JS`):
each piece's volume, its fades, its speed (pitch kept, as the browser keeps
it) and music lowered to 30 % under speech. That keeps the export exact and
independent of real time.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

from dodaios.nodes.clip.media import media_file, read_audio
from dodaios.nodes.kinds import motion
from dodaios.nodes.kinds import motion_media as mm

log = logging.getLogger(__name__)

#: Output presets: the short side of the picture.
PRESETS: Final[dict[str, int]] = {"720p": 720, "1080p": 1080, "2160p": 2160}
FRAME_RATES: Final[tuple[int, ...]] = (24, 30, 60)
EXPORT_DIR: Final[str] = "exports"
AUDIO_RATE: Final[int] = 48_000
#: The largest piece of a media file handed to the browser per request.
CHUNK_BYTES: Final[int] = 8 * 1024 * 1024
#: How long one frame may take before the export gives up.
FRAME_TIMEOUT_S: Final[float] = 30.0
_JPEG_QUALITY: Final[int] = 92
_PAGE_ORIGIN: Final[str] = "https://clip.invalid"
_PAGE_URL: Final[str] = f"{_PAGE_ORIGIN}/clip.html"
_DUCK_RAMP_S: Final[float] = 0.25
_DUCK_DEPTH: Final[float] = 0.7
_CONTENT_TYPES: Final[dict[str, str]] = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/mp4",
    ".webm": "video/webm",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".json": "application/json",
}
_RANGE_RE: Final = re.compile(r"bytes=(\d*)-(\d*)")


class ExportError(RuntimeError):
    """The clip could not be written; the message is for the person."""


class ExportCancelled(ExportError):
    """The person stopped the export."""


def content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def page_csp(origin: str) -> str:
    """The node page's policy, with the clip's own media address allowed."""
    from dodaios.ui.web.artifact_view import ARTIFACT_PAGE_CSP

    source = f"{origin.rstrip('/')}/clip-media/"
    return ARTIFACT_PAGE_CSP.replace(
        "img-src data: blob:;", f"img-src data: blob: {source};"
    ).replace("media-src data: blob:;", f"media-src data: blob: {source};")


def output_size(film_format: str, preset: str) -> tuple[int, int]:
    """The picture size of a format at a preset, both sides even."""
    width, height, _, _ = motion.FORMATS.get(film_format, motion.FORMATS["wide"])
    short = PRESETS.get(preset, PRESETS["1080p"])
    scale = short / min(width, height)
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)


def byte_range(header: str | None, size: int) -> tuple[int, int]:
    """The inclusive byte range a request asks for, at most ``CHUNK_BYTES`` long."""
    first, last = 0, size - 1
    match = _RANGE_RE.fullmatch((header or "").strip())
    if match:
        head, tail = match.groups()
        if head:
            first = int(head)
            if tail:
                last = int(tail)
        elif tail:  # the last N bytes
            first = max(0, size - int(tail))
    first = max(0, min(first, size - 1))
    last = max(first, min(last, size - 1, first + CHUNK_BYTES - 1))
    return first, last


# --- the sound -------------------------------------------------------------------


@dataclass(frozen=True)
class Sound:
    """One element that plays, with the page's timing (``_media_attrs``)."""

    file: str
    ts: float
    te: float
    source_in: float
    speed: float
    volume: float
    fade_in: float
    fade_out: float
    duck: bool = False


def sounds_of(spec: dict[str, Any]) -> list[Sound]:
    """Everything that is heard in the clip, as the page plays it."""
    media = spec.get("media") or {}
    found: list[Sound] = []

    def add(item: dict[str, Any], start: float, muted: bool = False) -> None:
        entry = media.get(str(item.get("media") or ""))
        if entry is None or not entry.get("audio") or entry.get("kind") == "image":
            return
        volume = 0.0 if (muted or item.get("muted")) else float(item.get("volume", 1))
        if volume <= 0:
            return
        found.append(
            Sound(
                file=entry["file"],
                ts=start,
                te=start + float(item["seconds"]),
                source_in=float(item.get("in", 0)),
                speed=float(item.get("speed", 1)) or 1.0,
                volume=volume,
                fade_in=float(item.get("fade_in", 0)),
                fade_out=float(item.get("fade_out", 0)),
                duck=bool(item.get("duck")),
            )
        )

    at = 0.0
    for scene in spec.get("scenes") or []:
        if scene.get("type") == "video":
            add(scene, at)
        at += float(scene["seconds"])
    for track in spec.get("tracks") or []:
        kind = track.get("kind")
        if kind == "overlay":
            if track.get("hidden"):
                continue  # a hidden overlay track is not drawn, so not heard
            for item in track.get("items") or []:
                add(item, float(item["start"]), bool(track.get("muted")))
        elif kind == "audio":
            for item in track.get("items") or []:
                add(item, float(item["start"]), bool(track.get("muted") or track.get("hidden")))
    return found


def duck_factor(times: Any, spans: list[tuple[float, float]]) -> Any:
    """The page's ``ducked(t)``: 1, down to 0.3 while someone speaks, 0.25 s ramps."""
    import numpy as np

    cover = np.zeros_like(times, dtype=np.float64)
    for start, end in spans:
        ramp = np.where(
            times < start,
            1 - (start - times) / _DUCK_RAMP_S,
            np.where(times > end, 1 - (times - end) / _DUCK_RAMP_S, 1.0),
        )
        cover = np.maximum(cover, np.clip(ramp, 0, 1))
    return 1 - _DUCK_DEPTH * cover


def gains(sound: Sound, times: Any, spans: list[tuple[float, float]]) -> Any:
    """The page's ``level(P, t)`` for every time in ``times`` (seconds on the timeline)."""
    import numpy as np

    level = np.full_like(times, sound.volume, dtype=np.float64)
    if sound.fade_in > 0:
        level *= np.clip((times - sound.ts) / sound.fade_in, 0, 1)
    if sound.fade_out > 0:
        level *= np.clip((sound.te - times) / sound.fade_out, 0, 1)
    if sound.duck:
        level *= duck_factor(times, spans)
    level = np.clip(level, 0, 1)
    return np.where((times >= sound.ts) & (times < sound.te), level, 0.0)


def tempo_chain(speed: float) -> list[float]:
    """``atempo`` factors whose product is ``speed``, each in the filter's range."""
    factors: list[float] = []
    rest = speed
    while rest < 0.5:
        factors.append(0.5)
        rest /= 0.5
    while rest > 2.0:
        factors.append(2.0)
        rest /= 2.0
    if abs(rest - 1.0) > 1e-6 or not factors:
        factors.append(rest)
    return factors


def change_speed(samples: Any, speed: float, rate: int = AUDIO_RATE) -> Any:
    """Stereo ``samples`` played ``speed`` times as fast, pitch kept (FFmpeg atempo)."""
    import av
    import numpy as np

    if abs(speed - 1.0) < 1e-6 or samples.shape[1] == 0:
        return samples
    graph = av.filter.Graph()
    source = graph.add_abuffer(
        sample_rate=rate, format="fltp", layout="stereo", time_base=Fraction(1, rate)
    )
    nodes = [source] + [graph.add("atempo", f"{factor:.6f}") for factor in tempo_chain(speed)]
    sink = graph.add("abuffersink")
    graph.link_nodes(*nodes, sink)
    graph.configure()
    out: list[Any] = []

    def drain() -> None:
        while True:
            try:
                frame = graph.pull()
            except (av.error.BlockingIOError, av.error.EOFError):  # filter drained: done
                return
            data = frame.to_ndarray().astype(np.float32, copy=False)
            if data.shape[0] == 1:  # the filter hands back interleaved samples
                data = data.reshape(-1, 2).T
            out.append(data)

    step = 4096
    for at in range(0, samples.shape[1], step):
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(samples[:, at : at + step]), format="fltp", layout="stereo"
        )
        frame.sample_rate = rate
        frame.pts, frame.time_base = at, Fraction(1, rate)
        graph.push(frame)
        drain()
    graph.push(None)
    drain()
    return np.concatenate(out, axis=1) if out else np.zeros((2, 0), dtype=np.float32)


def mix(spec: dict[str, Any], node_dir: Path, total: float) -> Any:
    """The clip's whole sound: stereo float32 at 48 kHz, ``total`` seconds long."""
    import numpy as np

    length = int(math.ceil(total * AUDIO_RATE))
    out = np.zeros((2, length), dtype=np.float32)
    spans = mm.voice_spans(spec)
    for sound in sounds_of(spec):
        path = media_file(node_dir, sound.file)
        if path is None:
            log.warning("clip export: %s is missing; its sound is left out", sound.file)
            continue
        seconds = sound.te - sound.ts
        samples = read_audio(
            path,
            sound.source_in,
            sound.source_in + seconds * sound.speed,
            rate=AUDIO_RATE,
            channels=2,
        )
        samples = change_speed(samples, sound.speed)
        first = int(round(sound.ts * AUDIO_RATE))
        count = min(samples.shape[1], int(round(seconds * AUDIO_RATE)), length - first)
        if count <= 0:
            continue
        times = (first + np.arange(count)) / AUDIO_RATE
        out[:, first : first + count] += samples[:, :count] * gains(sound, times, spans).astype(
            np.float32
        )
    np.clip(out, -1.0, 1.0, out=out)
    return out


# --- the browser -----------------------------------------------------------------


async def _serve(cdp: Any, html: bytes, node_dir: Path, node_id: str) -> None:
    """Answer the page from ``html`` and its media from the node's folder; fail the rest."""
    from dodaios.ui.web.artifact_share import ShareExportError

    prefix = f"{_PAGE_ORIGIN}/clip-media/{node_id}/"
    csp = page_csp(_PAGE_ORIGIN)

    async def answer(params: dict[str, Any]) -> None:
        request_id = params.get("requestId")
        request = params.get("request") or {}
        url = str(request.get("url", "")).split("?", 1)[0]
        try:
            if url == _PAGE_URL:
                await cdp.call(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": request_id,
                        "responseCode": 200,
                        "responseHeaders": [
                            {"name": "Content-Type", "value": "text/html; charset=utf-8"},
                            {"name": "Content-Security-Policy", "value": csp},
                        ],
                        "body": base64.b64encode(html).decode("ascii"),
                    },
                )
                return
            path = media_file(node_dir, url[len(prefix) :]) if url.startswith(prefix) else None
            if path is None:
                await cdp.call(
                    "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
                )
                return
            headers = {str(k).lower(): str(v) for k, v in (request.get("headers") or {}).items()}
            size = path.stat().st_size
            first, last = byte_range(headers.get("range"), size)
            with path.open("rb") as handle:
                handle.seek(first)
                body = handle.read(last - first + 1)
            whole = first == 0 and last == size - 1
            await cdp.call(
                "Fetch.fulfillRequest",
                {
                    "requestId": request_id,
                    "responseCode": 200 if whole and "range" not in headers else 206,
                    "responseHeaders": [
                        {"name": "Content-Type", "value": content_type(path)},
                        {"name": "Accept-Ranges", "value": "bytes"},
                        {"name": "Content-Length", "value": str(len(body))},
                        {"name": "Content-Range", "value": f"bytes {first}-{last}/{size}"},
                    ],
                    "body": base64.b64encode(body).decode("ascii"),
                },
            )
        except ShareExportError as exc:  # the page went away mid-request
            log.debug("clip export: could not answer %s: %s", url, exc)
        except OSError as exc:
            log.warning("clip export: could not read %s: %s", url, exc)

    cdp.on_paused = answer


class _Browser:
    """A throwaway headless browser for one export (no overall deadline)."""

    def __init__(self) -> None:
        from dodaios.ui.web import artifact_share

        browser = artifact_share.find_export_browser()
        if browser is None:
            raise ExportError(
                "No Chromium-family browser is installed, so the clip cannot be drawn."
            )
        self._profile = Path(tempfile.mkdtemp(prefix="dodaios-clip-browser-"))
        self._process = subprocess.Popen(  # noqa: S603 — a resolved browser executable, fixed flags
            [
                browser,
                "--headless=new",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--mute-audio",
                "--hide-scrollbars",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--remote-debugging-port=0",
                f"--user-data-dir={self._profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        try:
            port = artifact_share._devtools_port(self._profile, deadline)
            self.socket_url = artifact_share._page_socket_url(port, deadline)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # a browser deaf to terminate is killed instead
            self._process.kill()
        shutil.rmtree(self._profile, ignore_errors=True)


async def _open_page(
    cdp: Any, html: bytes, node_dir: Path, node: Any, scale: float
) -> dict[str, Any]:
    """Load the clip page in export mode at the stage's size; returns its geometry."""
    width, height, _, _ = motion.FORMATS.get(
        node.spec.get("format", "wide"), motion.FORMATS["wide"]
    )
    await _serve(cdp, html, node_dir, node.id)
    await cdp.call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
    await cdp.call("Page.enable")
    await cdp.call(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False},
    )
    loaded = cdp.next_event("Page.loadEventFired")
    await cdp.call("Page.navigate", {"url": f"{_PAGE_URL}?export=1&theme=dark"})
    await asyncio.wait_for(loaded, 30)
    probe = await _evaluate(
        cdp,
        "new Promise(function(done){var n=0;(function wait(){"
        "if(window.__clipFrame||n++>100){var s=document.querySelector('.stage');"
        "var r=s?s.getBoundingClientRect():{left:0,top:0,width:0,height:0};"
        "done({total:window.__clipTotal||0,x:r.left,y:r.top,w:r.width,h:r.height,"
        "ok:!!window.__clipFrame});}else setTimeout(wait,50);})();})",
        30,
    )
    if not isinstance(probe, dict) or not probe.get("ok"):
        raise ExportError("The clip page did not start in the export browser.")
    return probe


async def _evaluate(cdp: Any, expression: str, limit: float) -> Any:
    result = await asyncio.wait_for(
        cdp.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        ),
        limit,
    )
    if result.get("exceptionDetails"):
        raise ExportError(f"The clip page failed: {result['exceptionDetails'].get('text', '')}")
    return (result.get("result") or {}).get("value")


async def _capture(cdp: Any, at: float, box: dict[str, Any]) -> bytes:
    """One frame: the page stands at ``at``, then the stage is captured as a JPEG."""
    await _evaluate(
        cdp,
        f"window.__clipFrame({at:.6f}).then(function(){{return new Promise(function(r){{"
        "requestAnimationFrame(function(){requestAnimationFrame(function(){r(1);});});});})",
        FRAME_TIMEOUT_S,
    )
    shot = await asyncio.wait_for(
        cdp.call(
            "Page.captureScreenshot",
            {
                "format": "jpeg",
                "quality": _JPEG_QUALITY,
                "fromSurface": True,
                "clip": {
                    "x": box["x"],
                    "y": box["y"],
                    "width": box["w"],
                    "height": box["h"],
                    "scale": 1,
                },
            },
        ),
        FRAME_TIMEOUT_S,
    )
    return base64.b64decode(shot.get("data", ""))


async def _with_page(socket_url: str, work: Any) -> Any:
    import websockets

    from dodaios.ui.web.artifact_share import _Cdp

    async with websockets.connect(socket_url, max_size=None) as socket:
        cdp = _Cdp(socket)
        pump = asyncio.ensure_future(cdp.pump())
        try:
            return await work(cdp)
        finally:
            pump.cancel()
            try:
                await pump
            except asyncio.CancelledError:  # the reader was cancelled just above
                pass
            except Exception as exc:  # noqa: BLE001 — the socket closing under the reader
                log.debug("clip export: DevTools reader ended: %s", exc)


def _drafted(node: Any, spec: dict[str, Any]) -> Any:
    return (
        replace(node, spec=motion.normalize(spec))
        if hasattr(node, "__dataclass_fields__")
        else node
    )


# --- jobs ------------------------------------------------------------------------


@dataclass
class _Job:
    id: str
    frames: int = 0
    frame: int = 0
    state: str = "running"
    stage: str = "starting"
    file: str = ""
    error: str = ""
    started: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event)

    def status(self) -> dict[str, Any]:
        progress = (
            1.0 if self.state == "done" else (self.frame / self.frames if self.frames else 0.0)
        )
        return {
            "job": self.id,
            "state": self.state,
            "stage": self.stage,
            "progress": round(min(1.0, progress), 4),
            "frame": self.frame,
            "frames": self.frames,
            "file": self.file,
            "error": self.error,
        }


_jobs: dict[str, _Job] = {}
_jobs_lock = threading.Lock()
#: Finished jobs are forgotten after this long.
_KEEP_JOB_S: Final[float] = 6 * 3600


def _target(node_dir: Path, title: str, preset: str) -> Path:
    from dodaios.ui.web.artifact_share import safe_filename

    folder = node_dir / EXPORT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{safe_filename(title, 'clip')}-{preset}"
    number = 1
    while (folder / f"{stem}-{number}.mp4").exists():
        number += 1
    return folder / f"{stem}-{number}.mp4"


def _write(
    node: Any, node_dir: Path, spec: dict[str, Any], preset: str, fps: int, job: _Job
) -> Path:
    """Draw, encode and mix the clip into a new MP4 in ``<node_dir>/exports``."""
    import av
    import numpy as np
    from PIL import Image

    if preset not in PRESETS:
        raise ExportError(f"Unknown quality {preset!r}; choose one of {', '.join(PRESETS)}.")
    if fps not in FRAME_RATES:
        raise ExportError(f"Unknown frame rate {fps}; choose 24, 30 or 60.")
    drafted = _drafted(node, spec)
    clean = drafted.spec
    out_w, out_h = output_size(clean["format"], preset)
    logical_w = motion.FORMATS[clean["format"]][0]
    html = motion.render(drafted).encode("utf-8")
    target = _target(node_dir, getattr(node, "title", "") or "clip", preset)
    partial = target.with_suffix(".partial.mp4")
    browser = _Browser()
    try:
        total = mm.duration(clean)
        job.stage = "sound"
        sound = mix(clean, node_dir, total)
        job.frames = max(1, int(math.ceil(total * fps)))

        async def work(cdp: Any) -> None:
            box = await _open_page(cdp, html, node_dir, drafted, out_w / logical_w)
            job.stage = "frames"
            with av.open(
                str(partial), "w", format="mp4", options={"movflags": "+faststart"}
            ) as out:
                codec = "libx264" if "libx264" in av.codecs_available else "mpeg4"
                options = {"crf": "18", "preset": "veryfast"} if codec == "libx264" else {}
                video = out.add_stream(codec, rate=fps, options=options)
                video.width, video.height, video.pix_fmt = out_w, out_h, "yuv420p"
                audio = out.add_stream("aac", rate=AUDIO_RATE)
                audio.layout = "stereo"
                audio.bit_rate = 192_000
                written = 0

                def push_sound(until: int) -> None:
                    nonlocal written
                    step = 1024
                    while written + step <= until or (until >= sound.shape[1] and written < until):
                        chunk = sound[:, written : min(written + step, until)]
                        if chunk.shape[1] == 0:
                            break
                        frame = av.AudioFrame.from_ndarray(
                            np.ascontiguousarray(chunk), format="fltp", layout="stereo"
                        )
                        frame.sample_rate = AUDIO_RATE
                        frame.pts, frame.time_base = written, Fraction(1, AUDIO_RATE)
                        written += chunk.shape[1]
                        for packet in audio.encode(frame):
                            out.mux(packet)

                for index in range(job.frames):
                    if job.cancel.is_set():
                        raise ExportCancelled("The export was stopped.")
                    shot = await _capture(cdp, min(index / fps, max(0.0, total - 1e-3)), box)
                    picture = Image.open(io.BytesIO(shot)).convert("RGB")
                    if picture.size != (out_w, out_h):
                        picture = picture.resize((out_w, out_h), Image.Resampling.LANCZOS)
                    frame = av.VideoFrame.from_image(picture).reformat(format="yuv420p")
                    frame.pts, frame.time_base = index, Fraction(1, fps)
                    for packet in video.encode(frame):
                        out.mux(packet)
                    push_sound(min(sound.shape[1], int((index + 1) * AUDIO_RATE / fps)))
                    job.frame = index + 1
                for packet in video.encode(None):
                    out.mux(packet)
                push_sound(sound.shape[1])
                for packet in audio.encode(None):
                    out.mux(packet)

        asyncio.run(_with_page(browser.socket_url, work))
        partial.replace(target)
        return target
    except ExportError:
        raise
    except TimeoutError as exc:
        raise ExportError("A frame of the clip took too long to draw.") from exc
    except Exception as exc:
        log.exception("clip export failed")
        raise ExportError(f"The clip could not be written: {exc}") from exc
    finally:
        browser.close()
        partial.unlink(missing_ok=True)


def export_blocking(
    node: Any, node_dir: Path, spec: dict[str, Any], preset: str = "1080p", fps: int = 30
) -> Path:
    """Write the clip as an MP4 and return its path. Blocking (minutes for a long clip)."""
    return _write(node, node_dir, spec, preset, int(fps), _Job(id="inline"))


def start_export(node: Any, node_dir: Path, spec: dict[str, Any], preset: str, fps: int) -> str:
    """Start an export in the background; returns the job id :func:`export_status` reads."""
    if preset not in PRESETS:
        raise ExportError(f"Unknown quality {preset!r}; choose one of {', '.join(PRESETS)}.")
    if int(fps) not in FRAME_RATES:
        raise ExportError(f"Unknown frame rate {fps}; choose 24, 30 or 60.")
    job = _Job(id=secrets.token_hex(8))
    with _jobs_lock:
        now = time.time()
        for key in [
            k for k, v in _jobs.items() if v.state != "running" and now - v.started > _KEEP_JOB_S
        ]:
            del _jobs[key]
        _jobs[job.id] = job

    def run() -> None:
        try:
            job.file = str(_write(node, node_dir, spec, preset, int(fps), job))
            job.state, job.stage = "done", "done"
        except ExportCancelled:  # asked for: the job says cancelled, nothing failed
            job.state, job.stage = "cancelled", "cancelled"
        except ExportError as exc:  # the person's own failure: the job reports it
            log.info("clip export job %s failed: %s", job.id, exc)
            job.state, job.error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001 — a job reports its failure, never dies silently
            log.exception("clip export job %s failed", job.id)
            job.state, job.error = "failed", str(exc)

    threading.Thread(target=run, name=f"clip-export-{job.id}", daemon=True).start()
    return job.id


def export_status(job_id: str) -> dict[str, Any] | None:
    """The state of an export job, or ``None`` for an unknown one."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    return job.status() if job is not None else None


def cancel_export(job_id: str) -> bool:
    """Ask a running export to stop after its current frame."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None or job.state != "running":
        return False
    job.cancel.set()
    return True


def still_frames(
    node: Any, node_dir: Path, spec: dict[str, Any], times: list[float], width: int = 720
) -> list[bytes]:
    """JPEG pictures of the clip at ``times`` (seconds), ``width`` pixels wide."""
    drafted = _drafted(node, spec)
    clean = drafted.spec
    logical_w = motion.FORMATS[clean["format"]][0]
    html = motion.render(drafted).encode("utf-8")
    total = mm.duration(clean)
    browser = _Browser()
    try:

        async def work(cdp: Any) -> list[bytes]:
            box = await _open_page(cdp, html, node_dir, drafted, max(0.1, width / logical_w))
            shots = []
            for at in times:
                shots.append(await _capture(cdp, max(0.0, min(float(at), total - 1e-3)), box))
            return shots

        return asyncio.run(_with_page(browser.socket_url, work))
    except TimeoutError as exc:
        raise ExportError("The clip took too long to draw.") from exc
    finally:
        browser.close()


__all__ = [
    "EXPORT_DIR",
    "FRAME_RATES",
    "PRESETS",
    "ExportCancelled",
    "ExportError",
    "Sound",
    "byte_range",
    "cancel_export",
    "change_speed",
    "content_type",
    "duck_factor",
    "export_blocking",
    "export_status",
    "gains",
    "mix",
    "output_size",
    "page_csp",
    "sounds_of",
    "start_export",
    "still_frames",
    "tempo_chain",
]
