#!/usr/bin/env python3
"""Record the README's voice clip in your own Dodaios app; the cut is made for you.

    ~/Dodaios/.venv/bin/python scripts/readme_demo/voice_take.py
    ~/Dodaios/.venv/bin/python scripts/readme_demo/voice_take.py cut RAW [options]

The clip shows dictation in the chat with the assistant. The microphone in the
chat box is clicked and one sentence is spoken: the box draws a live waveform
of the voice and a timer, then "Transcribing...". The words land in the box
without the "uh", the message is sent and the assistant answers. A wait for
the model is cut out with a short dissolve; everything else plays at the
speed it was filmed at.

Step 1, prepare. Run this from a Terminal window that stands beside the
Dodaios window. It finds the Dodaios window and checks its size (under 1024
points wide, so the panel on the right with recent chats and computers stays
closed) and that no other window covers it. It checks that the Terminal may
record the screen and the microphone, makes a test recording of 1.6 seconds,
reads that picture for private text, shows the sentence to say and counts
down.

Step 2, speak. Click the microphone in the chat box, say the sentence, click
the square, click Send and wait for the answer. Then click into the Terminal
and press Return.

Then it trims and cuts the recording by itself: the start and end by the voice
and by what moves in the picture, the wait for the answer by the picture. It
writes into ~/Movies/Dodaios-Launch/v2/:

    voice-master.mp4   the clip with the voice (H.264, 60 fps, yuv420p, AAC)
    voice-silent.mp4   the same picture without sound, for the README loop
    voice-sheet.png    one still per second of the clip
    voice-take.json    what it found and how it cut
    voice-notes.md     the same in words, with measurements and the privacy check

It keeps the raw recordings in v2/voice-raw/ (the newest three), so `cut` can
make the clip again with other times (seconds of the raw recording):

    voice_take.py cut RAW --start 3.2 --end 21.5 --remove 12.4-18.3 --speed 1.1

Needs macOS, ffmpeg with avfoundation on the PATH, and a Python with PyObjC,
numpy and Pillow (the environment Dodaios runs on). It changes nothing in the
app: it only reads the profile name (to look for it in the picture) and the
newest dictation (to show what was heard), and it brings the Dodaios window
to the front when the countdown starts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import math
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OUT_DIR = Path.home() / "Movies" / "Dodaios-Launch" / "v2"
RAW_KEEP = 3
APP_OWNER = "Dodaios"
APP_PORT = 47821
SENTENCE = "Uh, give me three name ideas for a small coffee shop by the sea."
#: Typed and sent in a new chat before the take: the chat on screen then holds
#: this short exchange instead of the greeting of an empty chat, which names
#: the person and lists what falls due.
WARMUP = "From now on, answer me in two sentences unless I ask for more."
#: At 1024 points and wider the front page opens the assistant's panel (its
#: recent chats, computers and files), which is private.
WIDTH_RANGE = (900.0, 1016.0)
HEIGHT_RANGE = (540.0, 780.0)
FPS = 60
MAX_SECONDS = 240
MIN_FREE_BYTES = int(1.2 * 1024**3)
CLIP_TARGET = 16.0
SPEED_MAX = 1.25
DISSOLVE = 0.25
HOLD = 1.5
LOCK = Path("/tmp/dodaios-film.lock")
LOCK_WAIT = 180.0

# The cut reads small gray frames, ANALYSIS_RATE a second, ANALYSIS_WIDTH wide.
# Areas are shares of the frame, so they hold for any window size.
ANALYSIS_RATE = 20
ANALYSIS_WIDTH = 320
PIXEL_STEP = 10  # gray levels: a message bubble on the dark page differs by more
LOCAL = 0.006  # pointer, caret, spinner, typing dots, waveform: never progress
MEDIUM = 0.0015  # the microphone button turning into its recording pill
BIG = 0.015  # a message bubble appearing
END_CHANGE = 0.002  # more than the pointer, a caret and the window losing focus
NOISE = 0.0006  # what is left of a still picture after video compression
UPPER = 0.78  # message bubbles are looked for above the chat box (the bottom 22 %)
MIN_WAIT = 1.6  # seconds of still picture after the message before it is cut
END_STILL = 2.0  # the clip ends where the picture then stays still this long
KEEP_AFTER = 0.9  # seconds kept after the message appeared
KEEP_BEFORE = 0.25  # seconds kept before the picture moves on
LEAD = 0.9  # seconds shown before the microphone is clicked
SPEECH_GUARD = 0.3  # never cut this close to the voice

# Measured like measure-hero.py, so the numbers compare with the other clips.
MEASURE_SIZE = (320, 180)
MEASURE_STEP = 12
MEASURE_PIXELS = 4

PANEL_WORDS = ("recent activity", "computers", "outputs", "routines")
GREETINGS = ("good morning", "good afternoon", "good evening")
FILLER_RE = re.compile(r"\b(uh+|um+|erm|ah+|oh|äh+m?|öh+m?|hm+)\b", re.IGNORECASE)  # i18n-allow: umlaut spellings to match, not German text
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: Parts of a computer or account name that say nothing about a person.
NAME_STOP = {
    "macbook", "air", "pro", "mac", "mini", "imac", "studio", "von", "the", "and",
    "local", "dodaios", "assistant", "user", "admin",
}


class Stop(Exception):
    """A check failed; the message says what to do."""


def say(text: str = "") -> None:
    print(text, flush=True)


def item(label: str, value: str) -> None:
    say(f"  {label:<20} {value}")


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603


def need_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise Stop(f"{tool} is not on the PATH (brew install ffmpeg).")


def need_modules() -> None:
    missing = []
    for name in ("numpy", "PIL", "Quartz", "AppKit", "objc"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise Stop(
            "This Python lacks " + ", ".join(missing) + ". Run the script with the "
            "Python of the Dodaios environment, for example ~/Dodaios/.venv/bin/python."
        )


# --------------------------------------------------------------------------
# The app (read only)
# --------------------------------------------------------------------------


def app_json(port: int, path: str) -> Any:
    if port <= 0:
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - the app is optional for every caller
        return None


def newest_dictation(port: int, since: float) -> dict[str, Any] | None:
    """The newest dictation, if it was made during the take."""
    data = app_json(port, "/api/dictation/history?limit=3")
    entries = (data or {}).get("entries") or []
    if not entries:
        return None
    entry = entries[0]
    stamp = str(entry.get("created_at") or "")
    try:
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.astimezone()
        if when.timestamp() < since - 5:
            return None
    except ValueError:
        pass
    keys = ("text", "raw_text", "removed_words", "outcome", "language", "duration_s")
    return {key: entry.get(key) for key in keys}


def sensitive_terms(port: int, scrub_file: Path | None) -> list[tuple[str, str]]:
    """Words that must not be readable in the clip, with what they are."""
    terms: list[tuple[str, str]] = []

    def add(kind: str, value: str | None, split: bool = True) -> None:
        value = (value or "").strip()
        if len(value) >= 3 and value.lower() not in NAME_STOP:
            terms.append((kind, value.lower()))
        if split:
            for token in re.split(r"[\s._@'-]+", value):
                if len(token) >= 3 and token.lower() not in NAME_STOP:
                    terms.append((kind, token.lower()))

    profile = app_json(port, "/api/profile") or {}
    user = profile.get("user") or {}
    add("profile name", user.get("name"))
    add("profile name", user.get("display_name"))
    add("account name", getpass.getuser())
    add("account name", run(["id", "-F"]).stdout)
    for key in ("ComputerName", "LocalHostName"):
        add("computer name", run(["scutil", "--get", key]).stdout)
    if scrub_file and scrub_file.is_file():
        for pair in re.split(r"[,\n]", scrub_file.read_text(encoding="utf-8")):
            real = pair.split("=", 1)[0]
            add("name from the scrub list", real, split=False)
    seen: set[str] = set()
    unique = []
    for kind, term in terms:
        if term not in seen:
            seen.add(term)
            unique.append((kind, term))
    return unique


# --------------------------------------------------------------------------
# The window, the screen and the devices
# --------------------------------------------------------------------------


@dataclass
class Window:
    pid: int
    x: float
    y: float
    w: float
    h: float
    covered_by: list[str] = field(default_factory=list)


def _rect(info: Any) -> tuple[float, float, float, float]:
    b = info.get("kCGWindowBounds") or {}
    return float(b.get("X", 0)), float(b.get("Y", 0)), float(b.get("Width", 0)), float(b.get("Height", 0))


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def find_window(owner: str) -> Window | None:
    """The largest visible window of ``owner`` and the windows in front of it."""
    import Quartz

    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    infos = list(Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or [])
    best: tuple[float, float, float, float] | None = None
    best_index, pid = -1, 0
    for index, info in enumerate(infos):  # front to back
        if info.get("kCGWindowLayer", 0) != 0 or info.get("kCGWindowOwnerName") != owner:
            continue
        rect = _rect(info)
        if rect[2] < 300 or rect[3] < 200 or float(info.get("kCGWindowAlpha", 1) or 0) == 0:
            continue
        if best is None or rect[2] * rect[3] > best[2] * best[3]:
            best, best_index, pid = rect, index, int(info.get("kCGWindowOwnerPID", 0))
    if best is None:
        return None
    covered = set()
    for info in infos[:best_index]:
        if info.get("kCGWindowLayer", 0) != 0 or info.get("kCGWindowOwnerName") == owner:
            continue
        if float(info.get("kCGWindowAlpha", 1) or 0) == 0:
            continue
        if _overlap(_rect(info), best) > 4:
            covered.add(str(info.get("kCGWindowOwnerName") or "a window"))
    return Window(pid, *best, covered_by=sorted(covered))


def display_for(win: Window) -> tuple[int, tuple[float, float, float, float], float]:
    """Index of the screen that shows the window (ffmpeg's "Capture screen N"),
    its bounds in points and its pixels per point."""
    import Quartz

    _err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
    cx, cy = win.x + win.w / 2, win.y + win.h / 2
    for index, did in enumerate(list(ids)[:count]):
        b = Quartz.CGDisplayBounds(did)
        bounds = (b.origin.x, b.origin.y, b.size.width, b.size.height)
        if bounds[0] <= cx < bounds[0] + bounds[2] and bounds[1] <= cy < bounds[1] + bounds[3]:
            mode = Quartz.CGDisplayCopyDisplayMode(did)
            scale = Quartz.CGDisplayModeGetPixelWidth(mode) / max(1, Quartz.CGDisplayModeGetWidth(mode))
            return index, bounds, float(scale)
    raise Stop("The window stands on no active screen.")


def crop_for(win: Window, display: tuple[float, float, float, float], scale: float) -> tuple[int, int, int, int]:
    """The window as ``(w, h, x, y)`` in pixels of its screen, even numbers."""
    dx, dy, dw, dh = display
    x0, y0 = max(win.x, dx), max(win.y, dy)
    x1, y1 = min(win.x + win.w, dx + dw), min(win.y + win.h, dy + dh)

    def px(value: float) -> int:
        return int(round(value * scale)) // 2 * 2

    return px(x1 - x0), px(y1 - y0), px(x0 - dx), px(y0 - dy)


def avf_devices() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """ffmpeg's avfoundation devices: (index, name) for video and for audio."""
    proc = run(["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""], timeout=30)
    video: list[tuple[int, str]] = []
    audio: list[tuple[int, str]] = []
    section: list[tuple[int, str]] | None = None
    for line in proc.stderr.splitlines():
        if "AVFoundation video devices" in line:
            section = video
            continue
        if "AVFoundation audio devices" in line:
            section = audio
            continue
        match = re.search(r"\]\s*\[(\d+)\]\s*(.+?)\s*$", line)
        if match and section is not None:
            section.append((int(match.group(1)), match.group(2)))
    return video, audio


def _av_capture_device() -> Any:
    import objc

    objc.loadBundle("AVFoundation", {}, bundle_path="/System/Library/Frameworks/AVFoundation.framework")
    return objc.lookUpClass("AVCaptureDevice")


def default_mic_name() -> str | None:
    try:
        device = _av_capture_device().defaultDeviceWithMediaType_("soun")
        return str(device.localizedName()) if device is not None else None
    except Exception:  # noqa: BLE001
        return None


def mic_permission() -> int | None:
    """3 allowed, 0 not asked yet, 2 denied, 1 restricted (AVAuthorizationStatus)."""
    try:
        return int(_av_capture_device().authorizationStatusForMediaType_("soun"))
    except Exception:  # noqa: BLE001
        return None


def screen_permission() -> bool:
    import Quartz

    return bool(Quartz.CGPreflightScreenCaptureAccess())


def pick_mic(audio: list[tuple[int, str]], wanted: str | None) -> tuple[int, str, str]:
    """(index, name, kind) of the microphone to record."""
    if wanted:
        for index, name in audio:
            if wanted.lower() in name.lower():
                return index, name, "chosen"
        raise Stop(f"No microphone named like {wanted!r}. ffmpeg lists: " + ", ".join(n for _, n in audio))
    default = default_mic_name()
    for index, name in audio:
        if default and name == default:
            kind = "built-in" if _builtin(name) else "the system's default input"
            return index, name, kind
    for index, name in audio:
        if _builtin(name):
            return index, name, "built-in"
    raise Stop("No microphone found. ffmpeg lists: " + (", ".join(n for _, n in audio) or "nothing"))


def _builtin(name: str) -> bool:
    low = name.lower()
    return "iphone" not in low and any(word in low for word in ("macbook", "built-in", "integriert"))


def activate(pid: int) -> None:
    """Bring the app to the front, so the first click lands on the button."""
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception:  # noqa: BLE001 - a click on the window does the same
        pass


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def capture_command(screen: int, mic: int, crop: tuple[int, int, int, int], seconds: float,
                    path: Path, encoder: str) -> list[str]:
    w, h, x, y = crop
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "avfoundation", "-capture_cursor", "1", "-capture_mouse_clicks", "0",
        "-framerate", str(FPS), "-pixel_format", "nv12", "-thread_queue_size", "4096",
        "-i", f"{screen}:{mic}", "-t", f"{seconds:g}", "-vf", f"crop={w}:{h}:{x}:{y}",
    ]
    if encoder == "videotoolbox":
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", "40M", "-realtime", "1", "-g", str(FPS)]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-g", str(FPS)]
    return cmd + ["-c:a", "aac", "-b:a", "192k", "-f", "matroska", str(path)]


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    fmt = data.get("format") or {}
    info: dict[str, Any] = {
        "duration": float(fmt.get("duration") or 0),
        "start": float(fmt.get("start_time") or 0),
        "video": None,
        "audio": None,
    }
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind in ("video", "audio") and info[kind] is None:
            info[kind] = stream
    return info


def stream_offset(info: dict[str, Any], kind: str) -> float:
    """Where a stream starts on the timeline that ``-ss`` counts on."""
    stream = info.get(kind)
    if not stream:
        return 0.0
    return float(stream.get("start_time") or info["start"]) - info["start"]


def packet_rate(path: Path, duration: float) -> float:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
               "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)]).stdout.strip()
    try:
        return int(out.split(",")[0]) / max(duration, 0.001)
    except ValueError:
        return 0.0


def audio_level(path: Path) -> tuple[float, int]:
    """(RMS in dBFS, peak sample) of a recording's sound."""
    import numpy as np

    pcm = subprocess.run(  # noqa: S603
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"], capture_output=True, check=False,
    ).stdout
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return -120.0, 0
    rms = float(np.sqrt(np.mean((samples.astype(np.float64) / 32768.0) ** 2)))
    return 20 * math.log10(rms + 1e-9), int(np.abs(samples.astype(np.int32)).max())


def still(path: Path, png: Path, at_end: bool = True) -> None:
    cmd = ["ffmpeg", "-v", "error", "-y"]
    cmd += ["-sseof", "-0.3"] if at_end else []
    run(cmd + ["-i", str(path), "-frames:v", "1", str(png)])


def test_capture(screen: int, mic: int, crop: tuple[int, int, int, int], workdir: Path) -> dict[str, Any]:
    import numpy as np
    from PIL import Image

    path = workdir / "test.mkv"
    errors = ""
    for encoder in ("videotoolbox", "x264"):
        path.unlink(missing_ok=True)
        proc = run(capture_command(screen, mic, crop, 1.6, path, encoder), timeout=60)
        if proc.returncode == 0 and path.exists() and path.stat().st_size > 0:
            break
        lines = proc.stderr.strip().splitlines()
        errors = lines[-1] if lines else ""
    else:
        raise Stop(
            "The test recording failed (" + (errors or "no message") + "). If macOS asked whether "
            "Terminal may record the screen or the microphone, allow it, quit and reopen Terminal, "
            "and run this again."
        )
    info = probe(path)
    png = workdir / "test.png"
    still(path, png)
    picture = np.asarray(Image.open(png).convert("L"), dtype=np.float32) if png.exists() else np.zeros((1, 1))
    db, peak = audio_level(path)
    video = info["video"] or {}
    return {
        "encoder": encoder,
        "fps": packet_rate(path, info["duration"]),
        "size": (int(video.get("width", 0)), int(video.get("height", 0))),
        "picture_spread": float(picture.std()),
        "audio_db": db,
        "audio_peak": peak,
        "still": png,
    }


class Recorder:
    """ffmpeg in the background; Return (or Ctrl-C) stops it cleanly."""

    def __init__(self, cmd: list[str], log: Path) -> None:
        self.log = log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(  # noqa: S603
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log,
        )
        self.started = time.time()

    def stop(self) -> int:
        proc = self.proc
        if proc.poll() is None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(b"q")
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            for sig, wait in ((None, 6.0), (signal.SIGINT, 6.0), (signal.SIGTERM, 5.0)):
                if sig is not None and proc.poll() is None:
                    proc.send_signal(sig)
                try:
                    proc.wait(timeout=wait)
                    break
                except subprocess.TimeoutExpired:
                    continue
        self.log.close()
        return proc.returncode if proc.returncode is not None else -1


# --------------------------------------------------------------------------
# The film lock other recorders on this Mac use
# --------------------------------------------------------------------------


class FilmLock:
    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name, self.enabled, self.held = name, enabled, False

    def take(self) -> None:
        if not self.enabled or self.held:
            return
        waited, told = 0.0, False
        while waited < LOCK_WAIT:
            try:
                LOCK.mkdir()
            except FileExistsError:
                if not told:
                    owner = (LOCK / "owner").read_text(encoding="utf-8").strip() if (LOCK / "owner").exists() else "?"
                    say(f"  Another recording on this Mac is filming ({owner}); waiting up to three minutes.")
                    told = True
                time.sleep(2)
                waited += 2
                continue
            (LOCK / "owner").write_text(self.name, encoding="utf-8")
            self.held = True
            return
        say("  The other recording still films; going on without waiting.")

    def release(self) -> None:
        if self.held:
            shutil.rmtree(LOCK, ignore_errors=True)
            self.held = False


# --------------------------------------------------------------------------
# Reading a take
# --------------------------------------------------------------------------


@dataclass
class Take:
    path: Path
    duration: float
    frames: Any  # numpy uint8 [n, h, w], ANALYSIS_RATE a second
    t0: float  # time of frame 0 on the -ss timeline
    speech: list[tuple[float, float]]
    noise_db: float
    has_audio: bool
    size: tuple[int, int]
    capture_fps: float

    @property
    def area(self) -> int:
        return int(self.frames.shape[1] * self.frames.shape[2])

    def time(self, index: int) -> float:
        return self.t0 + index / ANALYSIS_RATE

    def index(self, seconds: float) -> int:
        return max(0, min(len(self.frames) - 1, int(round((seconds - self.t0) * ANALYSIS_RATE))))

    @property
    def upper_rows(self) -> int:
        return int(self.frames.shape[1] * UPPER)

    @property
    def upper_area(self) -> int:
        return int(self.upper_rows * self.frames.shape[2])

    def diff(self, i: int, j: int, rows: int | None = None) -> int:
        """Pixels that differ between two frames (only the top ``rows`` if given)."""
        import numpy as np

        a, b = self.frames[i, :rows], self.frames[j, :rows]
        return int(np.count_nonzero((np.maximum(a, b) - np.minimum(a, b)) > PIXEL_STEP))


def read_take(path: Path) -> Take:
    import numpy as np

    info = probe(path)
    video = info["video"]
    if not video:
        raise Stop(f"{path} has no picture.")
    vw, vh = int(video["width"]), int(video["height"])
    height = max(2, int(round(ANALYSIS_WIDTH * vh / vw / 2)) * 2)
    raw = subprocess.run(  # noqa: S603
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-vf",
         f"fps={ANALYSIS_RATE},scale={ANALYSIS_WIDTH}:{height}:flags=area,format=gray",
         "-f", "rawvideo", "-"], capture_output=True, check=True,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, ANALYSIS_WIDTH)
    speech, noise = ([], -120.0)
    if info["audio"]:
        speech, noise = speech_segments(path, stream_offset(info, "audio"))
    return Take(
        path=path, duration=info["duration"], frames=frames, t0=stream_offset(info, "video"),
        speech=speech, noise_db=noise, has_audio=bool(info["audio"]), size=(vw, vh),
        capture_fps=packet_rate(path, info["duration"]),
    )


def speech_segments(path: Path, offset: float) -> tuple[list[tuple[float, float]], float]:
    """Stretches of voice, from the loudness of 20 ms windows."""
    import numpy as np

    pcm = subprocess.run(  # noqa: S603
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"], capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    win = 320
    count = samples.size // win
    if count == 0:
        return [], -120.0
    rms = np.sqrt(np.mean(samples[: count * win].reshape(count, win) ** 2, axis=1))
    db = 20 * np.log10(rms + 1e-9)
    noise = float(np.percentile(db, 20))
    voiced = db > max(noise + 14.0, -50.0)
    segments: list[list[float]] = []
    start = None
    for i, flag in enumerate(voiced):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            segments.append([start * 0.02, i * 0.02])
            start = None
    if start is not None:
        segments.append([start * 0.02, count * 0.02])
    merged: list[list[float]] = []
    for seg in segments:
        if merged and seg[0] - merged[-1][1] < 0.35:
            merged[-1][1] = seg[1]
        else:
            merged.append(seg)
    return [(s + offset, e + offset) for s, e in merged if e - s >= 0.15], noise


def first_utterance(speech: list[tuple[float, float]]) -> tuple[float, float] | None:
    """The sentence: the first stretches of voice that belong together and
    last more than a moment (a click or a chime does not)."""
    clusters: list[list[float]] = []
    for s, e in speech:
        if clusters and s - clusters[-1][1] < 1.0:
            clusters[-1][1] = e
        else:
            clusters.append([s, e])
    for s, e in clusters:
        if e - s >= 0.6:
            return s, e
    return None


@dataclass
class Plan:
    start: float
    end: float
    removed: list[tuple[float, float]]
    speed: float
    events: dict[str, Any]

    @property
    def segments(self) -> list[tuple[float, float]]:
        out, at = [], self.start
        for r0, r1 in self.removed:
            out.append((at, r0))
            at = r1
        out.append((at, self.end))
        return out

    @property
    def length(self) -> float:
        raw = sum(e - s for s, e in self.segments) - DISSOLVE * len(self.removed)
        return raw / self.speed


def plan_cut(take: Take, start: float | None = None, end: float | None = None,
             remove: list[tuple[float, float]] | None = None, auto_remove: bool = True,
             speed: float | None = None) -> Plan:
    area = take.area
    events: dict[str, Any] = {"speech": [list(map(_r, s)) for s in take.speech]}
    utterance = first_utterance(take.speech)
    if utterance is None and (start is None or end is None):
        raise Stop("No voice found in the recording: check the microphone and record again "
                   "(or give --start and --end).")
    s0, s1 = utterance if utterance else (start or 0.0, end or take.duration)
    events["sentence"] = [_r(s0), _r(s1)]

    # The start: the microphone button turning into its pill shortly before the voice.
    click = None
    for i in range(take.index(s0 - 0.05), max(take.index(s0 - 5.0), 3) - 1, -1):
        if take.diff(i, i - 3) >= MEDIUM * area:
            click = take.time(i - 3)
            break
    events["microphone_clicked"] = _r(click) if click is not None else None
    auto_start = max(0.25, (click - LEAD) if click is not None else s0 - 1.6)

    # The message: the first new bubble above the chat box after the voice (the
    # words landing in the box change only the box).
    last = len(take.frames) - 1
    sent = None
    for i in range(take.index(s1 + 0.2), last + 1):
        if take.diff(i, max(0, i - 6), take.upper_rows) >= BIG * take.upper_area:
            sent = take.time(i)
            break
    events["message_sent"] = _r(sent)

    # The wait for the reply: a still picture after the message that moves on again.
    wait = _wait_after(take, sent, last) if sent is not None else None
    found = [wait["cut"]] if wait and wait["cut"] else []
    events["reply_arrives"] = _r(wait["reply"]) if wait else None
    events["wait_found"] = [[_r(a), _r(b)] for a, b in found]

    # The end: where the picture then stays still. Whatever comes later (a
    # notice, the pointer going to the Terminal) is not part of the clip.
    done = _settled(take, (wait["reply"] if wait else sent) + 0.3, last) if sent is not None else None
    if done is None:  # no message (a dictation only): the last change of the picture
        g = last
        while g > take.index(s1) and take.diff(g, last) <= END_CHANGE * area:
            g -= 1
        done = take.time(min(last, g + 1))
    events["settled"] = _r(done)
    auto_end = min(done + HOLD, take.duration - 0.3)

    plan_start = auto_start if start is None else start
    plan_end = auto_end if end is None else end
    if plan_end - plan_start < 2:
        raise Stop(f"The clip would be {plan_end - plan_start:.1f} s long; check --start and --end.")

    removed = remove if remove is not None else (found if auto_remove else [])
    clean: list[tuple[float, float]] = []
    for r0, r1 in sorted(removed):
        for s, e in take.speech:  # never cut into the voice
            if r0 < e + SPEECH_GUARD and r1 > s - SPEECH_GUARD:
                if s - SPEECH_GUARD > r0:
                    r1 = min(r1, s - SPEECH_GUARD)
                else:
                    r0 = max(r0, e + SPEECH_GUARD)
        r0, r1 = max(r0, plan_start + 0.5), min(r1, plan_end - 0.5)
        if clean and r0 < clean[-1][1] + 0.5:
            continue
        if r1 - r0 >= 0.5:
            clean.append((r0, r1))
    plan = Plan(plan_start, plan_end, clean, 1.0, events)
    if speed is not None:
        plan.speed = speed
    elif plan.length > CLIP_TARGET:
        plan.speed = round(min(SPEED_MAX, plan.length / CLIP_TARGET), 3)
    return plan


def _wait_after(take: Take, event: float, last: int) -> dict[str, Any] | None:
    """After the message: when the reply arrives, and the still part that can go.

    None when the picture does not stay still for MIN_WAIT (a quick reply) or
    never moves on again (no reply came).
    """
    area = take.area
    for a in range(take.index(event + 0.3), take.index(event + 1.2) + 1):
        j = a + 1
        while j <= last and take.diff(j, a) <= LOCAL * area:
            j += 1
        if (j - a) / ANALYSIS_RATE < MIN_WAIT:
            continue
        if j > last:
            return None
        # Back from where the picture moved on to where it began to: a reply
        # streams in word by word, and its first words are below LOCAL.
        calm = max(take.diff(f, a) for f in range(a, min(j, a + ANALYSIS_RATE)))
        level = max(calm * 1.5, calm + NOISE * area)
        k = j
        while k > a + 1 and take.diff(k - 1, a) > level:
            k -= 1
        r0 = max(take.time(a), event + KEEP_AFTER)
        r1 = take.time(k) - KEEP_BEFORE
        return {"cut": (r0, r1) if r1 - r0 >= 0.5 else None, "reply": take.time(k)}
    return None


def _settled(take: Take, after: float, last: int) -> float | None:
    """The first moment after ``after`` from which the picture stays still for
    END_STILL (or until the recording ends)."""
    need = int(END_STILL * ANALYSIS_RATE)
    g = take.index(after)
    while g < last:
        j = g + 1
        while j <= last and take.diff(j, g) <= LOCAL * take.area:
            j += 1
        if j > last or j - g >= need:
            return take.time(g)
        g += 1
    return None


def _r(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


# --------------------------------------------------------------------------
# Writing the clip
# --------------------------------------------------------------------------


def render(take: Take, plan: Plan, master: Path, silent: Path) -> None:
    segments = plan.segments
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for s, e in segments:
        cmd += ["-ss", f"{s:.3f}", "-t", f"{e - s:.3f}", "-i", str(take.path)]
    parts = []
    for k, (s, e) in enumerate(segments):
        parts.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={FPS},format=yuv420p,settb=AVTB[v{k}]")
        if take.has_audio:
            parts.append(f"[{k}:a]aresample=48000,asetpts=PTS-STARTPTS,apad,atrim=0:{e - s:.3f}[a{k}]")
    video, audio = "v0", "a0"
    length = segments[0][1] - segments[0][0]
    for k in range(1, len(segments)):
        offset = length - DISSOLVE
        parts.append(f"[{video}][v{k}]xfade=transition=fade:duration={DISSOLVE}:offset={offset:.3f}[vx{k}]")
        video = f"vx{k}"
        if take.has_audio:
            parts.append(f"[{audio}][a{k}]acrossfade=d={DISSOLVE}[ax{k}]")
            audio = f"ax{k}"
        length = offset + segments[k][1] - segments[k][0]
    tempo = f"setpts=PTS/{plan.speed:.4f}," if plan.speed != 1 else ""
    parts.append(f"[{video}]{tempo}fps={FPS},crop=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(parts + (
        [f"[{audio}]" + (f"atempo={plan.speed:.4f}" if plan.speed != 1 else "anull") + "[aout]"]
        if take.has_audio else []
    )), "-map", "[vout]"]
    if take.has_audio:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-movflags", "+faststart", str(master),
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise Stop("ffmpeg could not write the clip: " + proc.stderr.strip()[-600:])
    proc = run(["ffmpeg", "-v", "error", "-y", "-i", str(master), "-map", "0:v:0", "-c", "copy", "-an",
                "-movflags", "+faststart", str(silent)])
    if proc.returncode != 0:
        raise Stop("ffmpeg could not write the silent clip: " + proc.stderr.strip()[-600:])


def measure(clip: Path) -> dict[str, Any]:
    """Frames that differ from the one before, per second; the longest standstill."""
    import numpy as np

    w, h = MEASURE_SIZE
    raw = subprocess.run(  # noqa: S603
        ["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"scale={w}:{h}:flags=area,format=gray",
         "-f", "rawvideo", "-"], capture_output=True, check=True,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, h, w).astype(np.int16)
    if len(frames) < 2:
        return {"frames": int(len(frames))}
    moved = (np.abs(np.diff(frames, axis=0)) > MEASURE_STEP).reshape(len(frames) - 1, -1).sum(axis=1) >= MEASURE_PIXELS
    per_second = [int(moved[k:k + FPS].sum()) for k in range(0, len(moved), FPS)]
    longest = run_len = 0
    at = begun = 0
    for index, flag in enumerate(moved):
        if flag:
            run_len = 0
            continue
        if run_len == 0:
            begun = index
        run_len += 1
        if run_len > longest:
            longest, at = run_len, begun
    full = per_second[:-1] if len(moved) % FPS else per_second
    return {
        "frames": int(len(frames)),
        "changed_share": round(float(moved.mean()), 3),
        "changed_per_second": per_second,
        "lowest_full_second": min(full) if full else None,
        "longest_standstill_s": round(longest / FPS, 2),
        "longest_standstill_at_s": round(at / FPS, 2),
    }


def contact_sheet(clip: Path, sheet: Path, workdir: Path) -> list[tuple[float, Path]]:
    """One still per second (full size, for reading) and a sheet of them."""
    from PIL import Image, ImageDraw

    stills_dir = workdir / "stills"
    shutil.rmtree(stills_dir, ignore_errors=True)
    stills_dir.mkdir(parents=True)
    # The first frame of every whole second (the fps filter would pick frames
    # up to half a second late, and the labels would lie).
    run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
         "select='isnan(prev_selected_t)+gte(t-prev_selected_t,1)'", "-fps_mode", "vfr",
         str(stills_dir / "s%03d.png")])
    files = sorted(stills_dir.glob("s*.png"))
    stills = [(float(k), path) for k, path in enumerate(files)]
    if not stills:
        return []
    columns = 4
    tile_w = 480
    first = Image.open(stills[0][1])
    tile_h = int(round(first.height * tile_w / first.width))
    label = 22
    rows = math.ceil(len(stills) / columns)
    canvas = Image.new("RGB", (columns * (tile_w + 8) + 8, rows * (tile_h + label + 8) + 8), (32, 32, 32))
    draw = ImageDraw.Draw(canvas)
    for n, (second, path) in enumerate(stills):
        x = 8 + (n % columns) * (tile_w + 8)
        y = 8 + (n // columns) * (tile_h + label + 8)
        canvas.paste(Image.open(path).convert("RGB").resize((tile_w, tile_h), Image.LANCZOS), (x, y))
        draw.text((x + 2, y + tile_h + 4), f"{second:.0f} s", fill=(220, 220, 220))
    canvas.save(sheet)
    return stills


_VISION: dict[str, Any] = {}


def read_text(png: Path) -> str:
    """The text macOS reads in a picture (on this Mac, nothing is sent)."""
    import objc
    import Quartz
    from Foundation import NSURL

    if not _VISION:
        objc.loadBundle("Vision", {}, bundle_path="/System/Library/Frameworks/Vision.framework")
        _VISION["handler"] = objc.lookUpClass("VNImageRequestHandler")
        _VISION["request"] = objc.lookUpClass("VNRecognizeTextRequest")
    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(png)), None)
    if source is None:
        return ""
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    request = _VISION["request"].alloc().init()
    request.setRecognitionLevel_(0)
    request.setUsesLanguageCorrection_(False)
    handler = _VISION["handler"].alloc().initWithCGImage_options_(image, {})
    if not handler.performRequests_error_([request], None):
        return ""
    return "\n".join(str(obs.topCandidates_(1)[0].string()) for obs in (request.results() or []))


def privacy_findings(texts: list[tuple[float, str]], terms: list[tuple[str, str]]) -> list[dict[str, Any]]:
    found: dict[tuple[float, str], dict[str, Any]] = {}
    for second, text in texts:
        low = text.lower()
        for kind, term in terms:
            if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", low):
                found.setdefault((second, kind), {"second": second, "kind": kind})
        if EMAIL_RE.search(text):
            found.setdefault((second, "e-mail address"), {"second": second, "kind": "e-mail address"})
    return list(found.values())


# --------------------------------------------------------------------------
# The cut, start to end
# --------------------------------------------------------------------------


def cut(raw: Path, out_dir: Path, args: argparse.Namespace, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    master, silent = out_dir / "voice-master.mp4", out_dir / "voice-silent.mp4"
    sheet, report_json, notes = out_dir / "voice-sheet.png", out_dir / "voice-take.json", out_dir / "voice-notes.md"
    say("Cutting")
    take = read_take(raw)
    remove = [_span(text) for text in args.remove] if args.remove else None
    plan = plan_cut(take, start=args.start, end=args.end, remove=remove,
                    auto_remove=not args.no_auto_remove, speed=args.speed)
    item("voice", ", ".join(f"{s:.2f}-{e:.2f} s" for s, e in take.speech) or "none found")
    item("kept", ", ".join(f"{s:.2f}-{e:.2f} s" for s, e in plan.segments))
    item("cut out", ", ".join(f"{a:.2f}-{b:.2f} s" for a, b in plan.removed) or "nothing")
    item("speed", f"{plan.speed:g}" + ("" if plan.speed == 1 else " (the whole clip, evenly)"))
    item("length", f"{plan.length:.1f} s")
    with tempfile.TemporaryDirectory(prefix="voice-take-") as tmp:
        lock = FilmLock("voice_take.py (render)", enabled=not getattr(args, "no_lock", False))
        lock.take()
        try:
            render(take, plan, master, silent)
        finally:
            lock.release()
        numbers = measure(master)
        stills = contact_sheet(master, sheet, Path(tmp))
        privacy: dict[str, Any] = {"checked": False}
        if not args.no_ocr and stills:
            terms = sensitive_terms(args.port, args.scrub_file)
            texts = [(second, read_text(path)) for second, path in stills]
            privacy = {
                "checked": True,
                "stills": len(texts),
                "terms": len(terms),
                "findings": privacy_findings(texts, terms),
            }
    dictation = context.get("dictation")
    if dictation is None and context.get("recorded_at"):
        dictation = newest_dictation(args.port, context["recorded_at"])
    report = {
        "raw": str(raw),
        "raw_duration_s": _r(take.duration),
        "raw_size_px": list(take.size),
        "capture_fps": round(take.capture_fps, 1),
        "noise_floor_db": round(take.noise_db, 1),
        "events": plan.events,
        "cut": {
            "start": _r(plan.start), "end": _r(plan.end),
            "removed": [[_r(a), _r(b)] for a, b in plan.removed],
            "kept": [[_r(s), _r(e)] for s, e in plan.segments],
            "dissolve_s": DISSOLVE, "speed": plan.speed, "length_s": round(plan.length, 2),
        },
        "outputs": {"master": str(master), "silent": str(silent), "sheet": str(sheet)},
        "measure": numbers,
        "privacy": privacy,
        "dictation": dictation,
        "context": {k: v for k, v in context.items() if k != "dictation"},
    }
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    notes.write_text(notes_text(report), encoding="utf-8")
    summary(report)
    return report


def _span(text: str) -> tuple[float, float]:
    a, _, b = text.partition("-")
    try:
        return float(a), float(b)
    except ValueError as exc:
        raise Stop(f"--remove wants FROM-TO in seconds, not {text!r}.") from exc


def filler_left(text: str | None) -> list[str]:
    return [m.group(0) for m in FILLER_RE.finditer(text or "")]


def notes_text(report: dict[str, Any]) -> str:
    cut_ = report["cut"]
    m = report["measure"]
    p = report["privacy"]
    d = report.get("dictation") or {}
    ctx = report.get("context") or {}
    lines = [
        "# Voice clip: notes written by voice_take.py",
        "",
        f"Written {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## Files",
        "",
        f"- `{Path(report['outputs']['master']).name}`: the clip with the voice. "
        f"`{Path(report['outputs']['silent']).name}`: the same picture without sound. "
        f"`{Path(report['outputs']['sheet']).name}`: one still per second.",
        f"- Raw take: `{report['raw']}`, {report['raw_duration_s']} s, "
        f"{report['raw_size_px'][0]} x {report['raw_size_px'][1]} px, "
        f"{report['capture_fps']} frames a second delivered by the screen capture.",
    ]
    if ctx:
        lines += [
            f"- Window {ctx.get('window_pt', '?')} pt, recorded with {ctx.get('encoder', '?')}, "
            f"microphone: {ctx.get('mic_kind', '?')}. Test recording: {ctx.get('test_fps', '?')} "
            "frames a second.",
        ]
    lines += [
        "",
        "## What was said",
        "",
        f"- Suggested: \"{ctx.get('sentence', SENTENCE)}\"",
    ]
    if d:
        lines += [
            f"- Recognized: \"{d.get('raw_text') or ''}\"",
            f"- Delivered into the chat box: \"{d.get('text') or ''}\" "
            f"({d.get('removed_words') or 0} hesitation sound(s) removed, outcome {d.get('outcome')}).",
        ]
        left = filler_left(d.get("text"))
        if left:
            lines.append(f"- The delivered text still holds {', '.join(left)}: record again without it.")
    else:
        lines.append("- The app's dictation history was not read (no take time, or the app did not answer).")
    lines += [
        "",
        "## The cut (seconds of the raw take)",
        "",
        f"- Voice: {', '.join(f'{s}-{e}' for s, e in report['events'].get('speech', [])) or 'none'}; "
        f"the sentence {report['events'].get('sentence')}.",
        f"- Microphone clicked at {report['events'].get('microphone_clicked')}, message sent at "
        f"{report['events'].get('message_sent')}, reply arrives at {report['events'].get('reply_arrives')}, "
        f"the picture settles at {report['events'].get('settled')}.",
        f"- Kept {cut_['kept']}; cut out {cut_['removed'] or 'nothing'} with a dissolve of "
        f"{cut_['dissolve_s']} s; speed {cut_['speed']}; length {cut_['length_s']} s.",
        "",
        "## Measurements of the clip",
        "",
        f"- {m.get('frames')} frames; {round(100 * (m.get('changed_share') or 0))} % differ from the one before.",
        f"- Changed frames per second: {m.get('changed_per_second')}.",
        f"- Lowest full second: {m.get('lowest_full_second')} of {FPS}; longest standstill "
        f"{m.get('longest_standstill_s')} s at {m.get('longest_standstill_at_s')} s.",
        "",
        "## Privacy check",
        "",
    ]
    if p.get("checked"):
        found = p.get("findings") or []
        lines.append(
            f"- macOS text recognition read {p['stills']} stills and looked for {p['terms']} words "
            "(profile name, account name, computer name, scrub list) and e-mail addresses: "
            + ("nothing found." if not found else
               "FOUND " + ", ".join(f"{f['kind']} at {f['second']:.0f} s" for f in found) + ".")
        )
    else:
        lines.append("- Not run (--no-ocr). Look at the sheet yourself.")
    lines += ["- Look at the sheet as well: the reading misses small or faint text.", ""]
    return "\n".join(lines)


def summary(report: dict[str, Any]) -> None:
    cut_ = report["cut"]
    m = report["measure"]
    p = report["privacy"]
    d = report.get("dictation") or {}
    say()
    say("Done")
    item("clip", f"{report['outputs']['master']}  ({cut_['length_s']} s, with sound)")
    item("silent", report["outputs"]["silent"])
    item("sheet", report["outputs"]["sheet"])
    item("moving frames", f"{round(100 * (m.get('changed_share') or 0))} %, longest standstill "
         f"{m.get('longest_standstill_s')} s")
    if d:
        item("delivered text", d.get("text") or "")
        left = filler_left(d.get("text"))
        if left:
            say(f"  ! The text still holds {', '.join(left)}: record again and leave it out.")
    found = (p.get("findings") or []) if p.get("checked") else []
    if p.get("checked"):
        item("privacy", "nothing found" if not found else
             "CHECK: " + ", ".join(f"{f['kind']} at {f['second']:.0f} s" for f in found))
    say()
    say("Tell the lead (copy these lines):")
    say(f"  Voice take ready: {Path(report['outputs']['master']).parent}/voice-master.mp4 "
        f"({cut_['length_s']} s, with my voice) and voice-silent.mp4, sheet and notes beside them.")
    say(f"  Cut {cut_['kept']} of the raw take {report['raw']}, speed {cut_['speed']}; "
        f"{round(100 * (m.get('changed_share') or 0))} % moving frames, longest standstill "
        f"{m.get('longest_standstill_s')} s, capture {report['capture_fps']} fps.")
    if d:
        say(f"  Delivered text: \"{d.get('text') or ''}\" ({d.get('removed_words') or 0} filler removed).")
    if p.get("checked"):
        say("  Privacy reading: " + ("nothing found." if not found else
            "found " + ", ".join(f"{f['kind']} at {f['second']:.0f} s" for f in found) + "."))


# --------------------------------------------------------------------------
# The take, start to end
# --------------------------------------------------------------------------


def fits(win: Window) -> bool:
    return WIDTH_RANGE[0] <= win.w <= WIDTH_RANGE[1] and HEIGHT_RANGE[0] <= win.h <= HEIGHT_RANGE[1]


def wait_key(seconds: float) -> bool:
    """True when Return was pressed within ``seconds``."""
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if ready:
        sys.stdin.readline()
        return True
    return False


def settle_window(owner: str, dodaios: bool) -> Window:
    win = find_window(owner)
    if win is None:
        raise Stop(f"No {owner} window is visible. Show it on this screen (not minimized, not in "
                   "full screen), then run this again.")
    if dodaios and not fits(win):
        say(f"  The Dodaios window is {win.w:.0f} x {win.h:.0f} points. Drag its corner until it is about "
            "1000 x 620 (any width from 900 to 1016, height from 540 to 780).")
        say("  Leave full screen first if it is in full screen. Waiting; press Return here to go on as it is.")
        steady = 0
        while True:
            if wait_key(0.4):
                break
            win = find_window(owner) or win
            mark = "ok" if fits(win) else "  "
            sys.stdout.write(f"\r  now {win.w:5.0f} x {win.h:4.0f}  {mark}   ")
            sys.stdout.flush()
            steady = steady + 1 if fits(win) else 0
            if steady >= 3:
                break
        say()
    if win.covered_by:
        say("  These windows stand in front of the Dodaios window and would be filmed: "
            + ", ".join(win.covered_by) + ". Move them beside it. Waiting; Return goes on as it is.")
        while win.covered_by:
            if wait_key(0.5):
                break
            win = find_window(owner) or win
        say()
    return win


def privacy_before(still_png: Path, terms: list[tuple[str, str]]) -> list[str]:
    text = read_text(still_png)
    low = text.lower()
    problems = []
    names = privacy_findings([(0.0, text)], terms)
    if names:
        problems.append("readable now: " + ", ".join(sorted({f["kind"] for f in names})))
    if any(greeting in low for greeting in GREETINGS):
        problems.append("this is an empty new chat; its greeting names you (send the first line first)")
    if sum(word in low for word in PANEL_WORDS) >= 2:
        problems.append("the panel on the right is open (make the window narrower)")
    return problems


def record(args: argparse.Namespace) -> int:
    need_tools()
    need_modules()
    owner = args.app
    dodaios = owner == APP_OWNER
    out_dir: Path = args.out
    raw_dir = out_dir / "voice-raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    say("Voice take for the README")
    say()
    if dodaios:
        say("Before this: open a new chat with your assistant, type this line, send it and wait for the answer:")
        say(f"    {WARMUP}")
        say("Switch on Do Not Disturb, so no notice appears in the picture.")
        say("Press Return when that is done.")
        if not wait_key(3600):
            return 1
        say()
    say("1. Checks")
    win = settle_window(owner, dodaios)
    item(f"{owner} window", f"{win.w:.0f} x {win.h:.0f} points at {win.x:.0f}, {win.y:.0f}")
    screen_index, display, scale = display_for(win)
    crop = crop_for(win, display, scale)
    item("picture", f"{crop[0]} x {crop[1]} pixels")
    if not screen_permission():
        import Quartz

        Quartz.CGRequestScreenCaptureAccess()
        raise Stop("This Terminal may not record the screen yet. In System Settings > Privacy & Security > "
                   "Screen & System Audio Recording, switch on Terminal, quit and reopen Terminal, run this again.")
    item("screen recording", "allowed")
    status = mic_permission()
    if status in (1, 2):
        raise Stop("This Terminal may not use the microphone. In System Settings > Privacy & Security > "
                   "Microphone, switch on Terminal, quit and reopen Terminal, run this again.")
    video, audio = avf_devices()
    screen = next((index for index, name in video if name == f"Capture screen {screen_index}"), None)
    if screen is None:
        raise Stop("ffmpeg does not list the screen the window stands on.")
    mic_index, mic_name, mic_kind = pick_mic(audio, args.mic)
    item("microphone", f"{mic_name} ({mic_kind})" + ("" if status == 3 else ", macOS will ask"))
    load = os.getloadavg()[0]
    free = shutil.disk_usage(out_dir).free
    item("this Mac", f"load {load:.1f}, {free / 1024**3:.1f} GB free")
    if free < MIN_FREE_BYTES:
        raise Stop("Less than 1.2 GB free on the disk: a take needs about half a gigabyte. Make room first.")
    if load > 6:
        say("  ! The Mac is busy: frames may come unevenly. Better wait until the load is under 5.")

    say()
    say("2. Test recording (1.6 s, not kept)")
    with tempfile.TemporaryDirectory(prefix="voice-take-") as tmp:
        test = test_capture(screen, mic_index, crop, Path(tmp))
        item("picture", f"{test['size'][0]} x {test['size'][1]}, {test['fps']:.0f} frames a second "
             f"({test['encoder']})")
        if test["size"] != (crop[0], crop[1]):
            say("  ! The picture has another size than the window: the screen may be scaled.")
        if test["picture_spread"] < 1.0:
            raise Stop("The test picture is empty: screen recording is not allowed for this Terminal yet "
                       "(System Settings > Privacy & Security > Screen & System Audio Recording).")
        if test["fps"] < 50:
            say("  ! Fewer than 50 frames a second: close heavy apps or wait until the Mac is calmer.")
        item("sound", f"{test['audio_db']:.0f} dB at rest")
        if test["audio_peak"] == 0:
            raise Stop("The microphone gave only silence. Allow the microphone for Terminal (System Settings > "
                       "Privacy & Security > Microphone), or pick another one with --mic, and run this again.")
        if not args.no_ocr:
            problems = privacy_before(test["still"], sensitive_terms(args.port, args.scrub_file))
            item("private text", "none found" if not problems else "CHECK")
            for problem in problems:
                say(f"  ! {problem}")
            if problems:
                say("  Fix it and run this again, or type yes and Return to record anyway.")
                if sys.stdin.readline().strip().lower() != "yes":
                    return 1
        encoder = test["encoder"]
        test_fps = round(test["fps"], 1)

    say()
    say("3. The take")
    if dodaios:
        say("  When the countdown has run out:")
        say("    - click the microphone in the chat box (beside the round button),")
        say("    - say the sentence below, calmly, in one go,")
        say("    - click the square in the green box and wait until the words are in the box,")
        say("    - click Send (the round arrow) and wait until the answer is complete,")
        say("    - click into this Terminal window and press Return.")
    else:
        say(f"  Click into the {owner} window, hold the dictation key, say the sentence, let go, wait")
        say("  until the words are there, then click into this Terminal window and press Return.")
    say()
    say(f"      \033[1m\"{args.sentence}\"\033[0m")
    say()
    say("  Start the \"uh\" softly and say nothing else while the recording runs.")
    say("  Press Return to start; then click once into an empty part of the window.")
    if not wait_key(3600):
        return 1
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    raw = raw_dir / f"voice-raw-{stamp}.mkv"
    lock = FilmLock("voice_take.py (a take in the own app)", enabled=not args.no_lock)
    lock.take()
    try:
        moved = find_window(owner)
        if moved is not None and (moved.x, moved.y, moved.w, moved.h) != (win.x, win.y, win.w, win.h):
            win, crop = moved, crop_for(moved, display, scale)
            say(f"  The window moved; filming it at {win.w:.0f} x {win.h:.0f} points now.")
        for n in (5, 4, 3, 2, 1):
            sys.stdout.write(f"\r  Recording starts in {n} ...   ")
            sys.stdout.flush()
            if n == 2:
                activate(win.pid)
            time.sleep(1)
        say()
        say(f"  Say: \"{args.sentence}\"")
        recorder = Recorder(capture_command(screen, mic_index, crop, args.max_seconds, raw,
                                            encoder), raw.with_suffix(".log"))
        recorded_at = time.time()
        done = threading.Event()

        def ticker() -> None:
            # Short: a line wider than the Terminal wraps, and \r then piles up lines.
            while not done.wait(0.5):
                elapsed = time.time() - recorder.started
                sys.stdout.write(f"\r  \033[31m●\033[0m {int(elapsed) // 60}:{int(elapsed) % 60:02d}  Return stops ")
                sys.stdout.flush()
                if recorder.proc.poll() is not None:
                    return

        thread = threading.Thread(target=ticker, daemon=True)
        thread.start()
        try:
            while recorder.proc.poll() is None and not wait_key(0.5):
                pass
        except KeyboardInterrupt:
            pass
        done.set()
        code = recorder.stop()
        say()
        if not raw.exists() or raw.stat().st_size == 0:
            raise Stop(f"The recording failed (ffmpeg exit {code}); see {raw.with_suffix('.log')}.")
        raw.with_suffix(".log").unlink(missing_ok=True)
        item("raw take", f"{raw} ({raw.stat().st_size / 1024**2:.0f} MB)")
    finally:
        lock.release()
    for old in sorted(raw_dir.glob("voice-raw-*.mkv"))[:-RAW_KEEP]:
        old.unlink(missing_ok=True)
    say()
    context = {
        "recorded_at": recorded_at,
        "window_pt": f"{win.w:.0f} x {win.h:.0f}",
        "encoder": encoder,
        "test_fps": test_fps,
        "mic_kind": mic_kind,
        "sentence": args.sentence,
        "app": owner,
    }
    time.sleep(1.0)  # the newest dictation is written as the take ends
    context["dictation"] = newest_dictation(args.port, recorded_at)
    cut(raw, out_dir, args, context)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", type=Path, default=OUT_DIR, help="folder for the clip (default %(default)s)")
    common.add_argument("--port", type=int, default=APP_PORT, help="port of the app to read the profile name and "
                        "the newest dictation from; 0 reads nothing")
    common.add_argument("--no-ocr", action="store_true", help="do not read the picture for private text")
    common.add_argument("--no-lock", action="store_true", help="ignore the film lock of other recorders")
    common.add_argument("--scrub-file", type=Path, default=None,
                        help="a file of real=stand-in pairs; the real values must not be readable")
    if argv[:1] == ["cut"]:
        parser = argparse.ArgumentParser(prog="voice_take.py cut", parents=[common],
                                         description="Cut a raw take again.")
        parser.add_argument("raw", type=Path)
        parser.add_argument("--start", type=float, default=None, help="second of the raw take the clip starts at")
        parser.add_argument("--end", type=float, default=None, help="second of the raw take the clip ends at")
        parser.add_argument("--remove", action="append", default=[], metavar="FROM-TO",
                            help="cut this out instead of the waits found (repeatable)")
        parser.add_argument("--no-auto-remove", action="store_true", help="cut out no wait")
        parser.add_argument("--speed", type=float, default=None, help="play the whole clip this much faster "
                            f"(at most {SPEED_MAX})")
        args = parser.parse_args(argv[1:])
        if args.speed is not None and not 0.5 <= args.speed <= SPEED_MAX:
            parser.error(f"--speed must be between 0.5 and {SPEED_MAX}")
        try:
            need_tools()
            need_modules()
            cut(args.raw, args.out, args)
        except Stop as exc:
            say(f"\nStopped: {exc}")
            return 1
        return 0
    parser = argparse.ArgumentParser(prog="voice_take.py", parents=[common], description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", default=APP_OWNER, help="the app to film (default %(default)s); with another "
                        "app, dictate with the hold key")
    parser.add_argument("--mic", default=None, help="part of the microphone's name (default: the system's input)")
    parser.add_argument("--sentence", default=SENTENCE, help="what to say")
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS, help="the recording stops by itself "
                        "after this long")
    args = parser.parse_args(argv)
    args.start = args.end = args.speed = None
    args.remove, args.no_auto_remove = [], False
    try:
        return record(args)
    except Stop as exc:
        say(f"\nStopped: {exc}")
        return 1
    except KeyboardInterrupt:
        say("\nStopped.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
