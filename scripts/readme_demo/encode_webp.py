#!/usr/bin/env python3
"""Turn a recording into the animated WebP the README shows.

    python scripts/readme_demo/encode_webp.py master.mp4 clip.webp [--width 1280]
        [--fps 30] [--quality 70] [--keyframe 15] [--start 2.5] [--duration 12]

The README plays its recordings as animated WebP pictures: they start by
themselves, loop, need no player, and keep their full colour at a fraction of
a GIF's size. ffmpeg here has no WebP encoder, so this reads the frames from
ffmpeg and lets Pillow write the file.

Every ``--keyframe`` frames at the latest the picture is stored whole. Between
those frames only what changed is stored, lossy, on top of the frame before.
Without whole frames the small errors of that piling up stay on screen as
faint blocks after a dissolve or a scroll (``minimize_size`` alone stores no
whole frame at all: measured on the hero clip, blocks covered up to 8 % of the
picture for three seconds). With a whole frame every half second they last
no longer than the dissolve. The clips of 15 November 2026 were made with:

    hero.webp     --width 1120 --fps 24
    phone.webp    --width 420 --quality 85
    the others    the defaults

Needs ffmpeg and ffprobe on the PATH and Pillow with WebP support.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from PIL import Image


def _size(src: str) -> tuple[int, int]:
    out = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", src],
        capture_output=True, text=True, check=True,
    ).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def _frames(cmd: list[str], width: int, height: int) -> Iterator[Image.Image]:
    """Yield the video's frames one at a time, so a long clip never sits in memory."""
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:  # noqa: S603
        assert proc.stdout is not None
        size = width * height * 3
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                return
            yield Image.frombytes("RGB", (width, height), buf)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("--width", type=int, default=1280, help="width in pixels; the height follows")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--quality", type=int, default=70, help="0 to 100; 70 keeps text clean")
    parser.add_argument("--keyframe", type=int, default=15, help="store the whole picture at least every this many frames")
    parser.add_argument("--start", default=None, help="second the clip starts at in the source")
    parser.add_argument("--duration", default=None, help="length of the clip in seconds")
    args = parser.parse_args()

    src_w, src_h = _size(args.source)
    width = args.width
    height = round(src_h * width / src_w / 2) * 2
    cmd = ["ffmpeg", "-v", "error"]
    if args.start:
        cmd += ["-ss", args.start]
    if args.duration:
        cmd += ["-t", args.duration]
    cmd += ["-i", args.source, "-vf", f"fps={args.fps},scale={width}:{height}:flags=lanczos",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    frames = _frames(cmd, width, height)
    first = next(frames, None)
    if first is None:
        print(f"no frames in {args.source}", file=sys.stderr)
        return 1
    first.save(
        args.target, save_all=True, append_images=frames, loop=0,
        duration=round(1000 / args.fps), quality=args.quality, method=4,
        kmin=max(1, args.keyframe // 3), kmax=args.keyframe,
    )
    megabytes = Path(args.target).stat().st_size / 1_000_000
    print(f"{args.target}: {megabytes:.2f} MB, {width} x {height}, {args.fps:g} frames a second")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
