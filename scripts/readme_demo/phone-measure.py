"""Measure how the rendered PHONE clip moves, and lay out a contact sheet of it.

    python scripts/readme_demo/phone-measure.py <clip.mp4> [contact.png] [take folder]

measure-hero.py for a portrait clip. Stills cannot show stutter, so this
decodes the clip with ffmpeg to small gray frames (portrait, 180 x 390) and
counts, second by second, how many frames differ from the one before them.
It prints that count per second, the longest stretch without a changed frame,
and the share of frames that moved.

With a second argument it also writes a contact sheet: one frame per second,
tiled, at most 2000 pixels wide. Look at it for anything private, a toast, or
a moment that cannot be read.

With a third argument (the take folder of phone-take.cjs) it also prints the
real frame rate of each stretch of the footage. The screencast sends a frame
only when the picture changes, so a stretch has two kinds of time: frames
coming in a run (something moves) and pauses (nothing does). The rate in the
runs is what the eye sees as smooth or not.

Needs ffmpeg and ffprobe on the PATH. No other package.
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

WIDTH, HEIGHT = 180, 390
#: A pixel counts as changed when its gray value moved by more than this.
PIXEL_STEP = 12
#: A frame counts as changed when this many of its pixels changed. A typed
#: letter is about twenty pixels at this size, a touch mark a few hundred.
CHANGED_PIXELS = 4
#: Two frames of the footage less than this apart belong to one run of movement.
RUN_GAP = 0.05


def probe(path: str) -> tuple[float, float, int, int]:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=r_frame_rate,width,height:format=duration", "-of", "json", path,
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    stream = data["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    return float(num) / float(den), float(data["format"]["duration"]), stream["width"], stream["height"]


def changed(a: bytes, b: bytes) -> int:
    """How many pixels differ by more than PIXEL_STEP between two gray frames."""
    if a == b:
        return 0
    return sum(1 for x, y in zip(a, b) if abs(x - y) > PIXEL_STEP)


def footage_rates(take_dir: str) -> None:
    take = json.loads((Path(take_dir) / "take.json").read_text())
    stretches = take["stretches"]
    frames = [f["ts"] for f in take["frames"]]
    print("footage, stretch by stretch (frames come only when the picture changes):")
    for i, st in enumerate(stretches):
        if not st["name"]:
            continue
        end = stretches[i + 1]["at"] if i + 1 < len(stretches) else math.inf
        mine = [ts for ts in frames if st["at"] <= ts < end]
        span = (end if math.isfinite(end) else (mine[-1] if mine else st["at"])) - st["at"]
        gaps = [b - a for a, b in zip(mine, mine[1:])]
        runs = [g for g in gaps if g < RUN_GAP]
        rate = f"in motion {len(runs) + 1} frames, median {1 / statistics.median(runs):.0f} frames a second" if runs else "no run of movement"
        print(f"  {st['name']:<12} {span:6.2f} s  {len(mine):4d} frames  {rate}  (longest pause {max(gaps) if gaps else 0:.2f} s)")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    fps, duration, width, height = probe(path)
    size = WIDTH * HEIGHT
    decode = subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={WIDTH}:{HEIGHT}:flags=area,format=gray",
            "-f", "rawvideo", "-",
        ],
        stdout=subprocess.PIPE,
    )
    assert decode.stdout is not None
    moved: list[bool] = []
    before = decode.stdout.read(size)
    while True:
        frame = decode.stdout.read(size)
        if len(frame) < size:
            break
        moved.append(changed(before, frame) >= CHANGED_PIXELS)
        before = frame
    decode.wait()

    frames = len(moved) + 1
    per_second = round(fps)
    print(f"{path}")
    print(f"{width} x {height}, {fps:g} frames a second, {duration:.2f} s, {frames} frames")
    print(f"frames that differ from the one before: {sum(moved)} of {len(moved)} ({100 * sum(moved) / max(1, len(moved)):.0f} %)")
    print("second: changed frames")
    seconds = math.ceil(len(moved) / per_second)
    low = []
    for second in range(seconds):
        chunk = moved[second * per_second : (second + 1) * per_second]
        count = sum(chunk)
        bar = "#" * round(40 * count / max(1, len(chunk)))
        print(f"  {second:3d}: {count:3d} of {len(chunk):3d}  {bar}")
        if len(chunk) == per_second and count < per_second * 0.25:
            low.append(second)
    longest, run, at, begun = 0, 0, 0, 0
    for index, flag in enumerate(moved):
        if flag:
            run = 0
            continue
        if run == 0:
            begun = index
        run += 1
        if run > longest:
            longest, at = run, begun
    print(f"longest standstill: {longest / fps:.2f} s ({longest} frames), from second {at / fps:.2f}")
    print("seconds with fewer than a quarter of their frames changed: " + (", ".join(map(str, low)) or "none"))

    if len(sys.argv) > 2 and sys.argv[2]:
        sheet = sys.argv[2]
        count = max(1, math.ceil(duration))
        columns = min(count, 7)
        rows = math.ceil(count / columns)
        tile = 2000 // columns
        tile -= tile % 2
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y", "-i", path, "-vf",
                f"fps=1,scale={tile}:-2:flags=lanczos,tile={columns}x{rows}:padding=4:color=0x202020",
                "-frames:v", "1", sheet,
            ],
            check=True,
        )
        print(f"contact sheet: {sheet} ({columns} x {rows}, one frame a second)")
    if len(sys.argv) > 3:
        footage_rates(sys.argv[3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
