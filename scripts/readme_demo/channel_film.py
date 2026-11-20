#!/usr/bin/env python3
"""One clip of a channel take: the phone and the desktop side by side, in step.

    python scripts/readme_demo/channel_film.py RAW_FOLDER STAMP OUT.mp4 [--name telegram]

telegram_take.py --web-phone films both sides of one conversation at once: the
chat in Telegram Web (phone-raw-STAMP.mp4 and .json) and the desktop app
(desktop-raw-STAMP.mp4, .json and .marks.json), each frame with the time it was
drawn. This cuts both at the same moments of that shared clock, so what is
typed on the phone arrives on the desktop when it really did, and puts them
side by side on a dark ground: the phone's screen on the left, the desktop's
conversation column on the right (its window cropped to the chat, so the text
stays readable when the README shows the clip small). Nothing is drawn on
top: no captions, no frame around the phone.

The cut: from just before the typing starts until the message has arrived on
the desktop, then (a short dissolve over the wait while the assistant works)
from just before its answer until both sides show it and a moment after.

It writes OUT.mp4 (H.264, 60 fps, no sound) and OUT's .json beside it with the
segments, and prints one line per step. Needs ffmpeg and ffprobe.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

FPS = 60
H = 720  # the canvas height
MARGIN = 20
GAP = 28
PHONE_H = H - 2 * MARGIN
LEAD = 0.7  # seconds before the typing starts
AFTER_ARRIVAL = 2.2  # seconds kept after the message arrived on the desktop
BEFORE_ANSWER = 1.4  # seconds kept before the answer
HOLD = 2.6  # seconds kept after both sides show the answer
MIN_WAIT = 1.2  # a wait shorter than this is not cut
DISSOLVE = 0.3
GROUND = "0x0A0A0A"
# The desktop's window cropped to its rail and conversation column, in CSS pixels of
# the 1200 x 675 window (scale 1.6): the assistant's panel begins at about 895.
CHAT_CSS = (0, 0, 850, 675)
CORNER = 26  # the phone screen's rounded corners, in canvas pixels
DESKTOP_SCALE = 1.6


def even(x: float) -> int:
    return int(round(x / 2)) * 2


def probe_size(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(  # noqa: S603
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data = json.loads(out)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"]), float(data["format"]["duration"])


def load(raw: Path) -> dict:
    return json.loads(raw.with_suffix(".json").read_text(encoding="utf-8"))


def plan(raw_dir: Path, stamp: str) -> dict:
    phone_raw = raw_dir / f"phone-raw-{stamp}.mp4"
    desk_raw = raw_dir / f"desktop-raw-{stamp}.mp4"
    phone, desk = load(phone_raw), load(desk_raw)
    marks = json.loads((raw_dir / f"desktop-raw-{stamp}.marks.json").read_text(encoding="utf-8"))
    p0, d0 = phone["frames"][0]["ts"], desk["frames"][0]["ts"]
    _, _, p_len = probe_size(phone_raw)
    _, _, d_len = probe_size(desk_raw)
    times = phone.get("times") or {}
    typing = float(times.get("typing") or times.get("record_from") or p0)
    arrived = d0 + float(marks["message"])
    answer = d0 + float(marks.get("answer_done") or marks["message"])
    shown = max(
        float(times.get("replied") or 0.0), d0 + float(marks.get("answer_sent") or 0.0), answer
    )
    start = max(p0, typing - LEAD)
    end = min(p0 + p_len, d0 + d_len, shown + HOLD) - 0.05
    a_end, b_start = arrived + AFTER_ARRIVAL, answer - BEFORE_ANSWER
    if b_start - a_end < MIN_WAIT:
        segments = [(start, end)]
    else:
        segments = [(start, a_end), (b_start, end)]
    return {
        "phone_raw": str(phone_raw),
        "desktop_raw": str(desk_raw),
        "phone_t0": p0,
        "desktop_t0": d0,
        "typing": typing,
        "arrived": arrived,
        "answer": answer,
        "shown": shown,
        "segments": segments,
        "length": sum(b - a for a, b in segments) - DISSOLVE * (len(segments) - 1),
    }


def side(index: int, t0: float, segments: list[tuple[float, float]], label: str) -> list[str]:
    """Filter lines that cut one input at the shared moments; the result is [label]."""
    lines, parts = [], []
    first = segments[0][0]
    pad = max(0.0, t0 - first)  # this side began filming later: its first picture stands
    src = f"[{index}:v]"
    if pad > 0:
        lines.append(f"{src}tpad=start_mode=clone:start_duration={pad:.3f}[{label}pad]")
        src, t0 = f"[{label}pad]", t0 - pad
    split = f"{src}split={len(segments)}" + "".join(f"[{label}s{i}]" for i in range(len(segments)))
    lines.append(split)
    for i, (a, b) in enumerate(segments):
        lines.append(
            f"[{label}s{i}]trim=start={a - t0:.3f}:end={b - t0:.3f},setpts=PTS-STARTPTS,"
            f"fps={FPS}[{label}{i}]"
        )
        parts.append(f"[{label}{i}]")
    if len(parts) == 1:
        lines.append(f"{parts[0]}null[{label}]")
        return lines
    offset = segments[0][1] - segments[0][0] - DISSOLVE
    lines.append(
        f"{parts[0]}{parts[1]}xfade=transition=fade:duration={DISSOLVE}:offset={offset:.3f}[{label}]"
    )
    return lines


def compose(cut: dict, out: Path) -> dict:
    pw, ph, _ = probe_size(Path(cut["phone_raw"]))
    dw, dh, _ = probe_size(Path(cut["desktop_raw"]))
    phone_w = even(pw * PHONE_H / ph)
    x0, y0, x1, y1 = (round(v * DESKTOP_SCALE) for v in CHAT_CSS)
    x1, y1 = min(x1, dw), min(y1, dh)
    crop_w, crop_h = even(x1 - x0), even(y1 - y0)
    desk_w = even(crop_w * PHONE_H / crop_h)
    width = MARGIN + phone_w + GAP + desk_w + MARGIN
    segments = [tuple(s) for s in cut["segments"]]
    lines = side(0, cut["phone_t0"], segments, "p") + side(1, cut["desktop_t0"], segments, "d")
    lines += [
        f"[p]scale={phone_w}:{PHONE_H}:flags=lanczos,format=rgba[pr]",
        "[2:v]format=gray[mask]",
        "[pr][mask]alphamerge[ps]",
        f"[d]crop={crop_w}:{crop_h}:{x0}:{y0},scale={desk_w}:{PHONE_H}:flags=lanczos[ds]",
        f"color=c={GROUND}:s={width}x{H}:r={FPS}[bg]",
        f"[bg][ps]overlay={MARGIN}:{MARGIN}:shortest=1[t]",
        f"[t][ds]overlay={MARGIN + phone_w + GAP}:{MARGIN}:shortest=1,format=yuv420p[out]",
    ]
    graph = ";".join(lines)
    mask_dir = tempfile.mkdtemp(prefix="channel-film-")
    mask = Path(mask_dir) / "corners.png"
    im = Image.new("L", (phone_w, PHONE_H), 0)
    ImageDraw.Draw(im).rounded_rectangle((0, 0, phone_w - 1, PHONE_H - 1), CORNER, fill=255)
    im.save(mask)
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        cut["phone_raw"],
        "-i",
        cut["desktop_raw"],
        "-loop",
        "1",
        "-i",
        str(mask),
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "16",
        "-r",
        str(FPS),
        "-movflags",
        "+faststart",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise SystemExit("ffmpeg failed: " + proc.stderr.strip()[-800:])
    return {
        "canvas": [width, H],
        "phone": [phone_w, PHONE_H],
        "desktop": [desk_w, PHONE_H],
        "desktop_crop": [crop_w, crop_h, x0, y0],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("stamp")
    parser.add_argument("out", type=Path)
    args = parser.parse_args(argv)
    cut = plan(args.raw_dir, args.stamp)
    print(
        "segments: "
        + ", ".join(f"{a - cut['typing']:.2f}..{b - cut['typing']:.2f}" for a, b in cut["segments"])
        + f" s from the typing; {cut['length']:.1f} s long"
    )
    layout = compose(cut, args.out)
    report = {**cut, **layout, "out": str(args.out)}
    args.out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({layout['canvas'][0]} x {layout['canvas'][1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
