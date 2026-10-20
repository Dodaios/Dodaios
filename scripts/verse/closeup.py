"""Render 1:1 close-ups of a deck's plate without cooking the whole deck.

    python scripts/verse/closeup.py <deck_id> <out_dir> [--quality final]
        [--socket spawn/commander] [--three X,Y,Z] [--px X,Y] [--size 1600x900]
        [--samples N] [--threshold T] [--device auto|optix|cuda|cpu]

Builds the deck in headless Blender (GPU lock) and renders each requested
window exactly as the cook would at that quality's density (camera, samples,
denoiser, glow, AgX, dither), then writes `<out_dir>/<name>.png`. Use it to
check materials and noise at full zoom before a long final cook. Anchors:
`--socket kind/id` (e.g. `lift/main`), `--three x,y,z` (three.js world
metres) or `--px x,y` (L0 plate pixels); each flag may repeat.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import blender  # noqa: E402

ENTRY = Path(__file__).resolve().with_name("_closeup_entry.py")


def _floats(text: str) -> list[float]:
    return [float(part) for part in text.split(",")]


def render_closeups(
    deck_id: str,
    out_dir: Path,
    windows: list[dict],
    *,
    quality: str = "final",
    samples: int | None = None,
    threshold: float | None = None,
    device: str = "auto",
) -> list[Path]:
    """Render `windows` of deck `deck_id`; return the PNG paths."""
    out_dir = out_dir.resolve()
    raw = out_dir / "_raw"
    raw.mkdir(parents=True, exist_ok=True)
    spec = raw / "windows_in.json"
    spec.write_text(json.dumps(windows), encoding="utf-8")
    args = [deck_id, str(raw), quality, str(spec)]
    if samples:
        args += ["--samples", str(samples)]
    if threshold:
        args += ["--threshold", str(threshold)]
    blender.run(ENTRY, args, device=device, timeout=3 * 3600)
    meta = json.loads((raw / "windows.json").read_text(encoding="utf-8"))
    paths = []
    for window in meta["windows"]:
        pixels = np.load(raw / f"{window['name']}.npy")
        path = out_dir / f"{window['name']}.png"
        Image.fromarray(pixels, mode="RGB").save(path)
        paths.append(path)
        print(
            f"[verse] {path} plate rect {window['plate_rect']} "
            f"({window['samples']} spp, threshold {window['threshold']}, {window['render_s']} s)"
        )
    return paths


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("deck_id")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--quality", choices=("preview", "final"), default="final")
    parser.add_argument("--socket", action="append", default=[])
    parser.add_argument("--three", action="append", default=[])
    parser.add_argument("--px", action="append", default=[])
    parser.add_argument("--size", default="1600x900")
    parser.add_argument("--samples", type=int)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--device", choices=blender.DEVICES, default="auto")
    parser.add_argument("--prefix", default="", help="file name prefix for the PNGs")
    options = parser.parse_args(argv)
    width, height = (int(v) for v in options.size.lower().split("x"))
    size = {"w": width, "h": height}
    prefix = options.prefix
    windows = []
    for socket in options.socket:
        key = socket.replace("/", "_", 1)
        windows.append({"name": prefix + key, "socket": key, **size})
    for index, text in enumerate(options.three):
        windows.append({"name": f"{prefix}three_{index}", "three": _floats(text), **size})
    for index, text in enumerate(options.px):
        windows.append({"name": f"{prefix}px_{index}", "px": _floats(text), **size})
    if not windows:
        parser.error("give at least one --socket, --three or --px anchor")
    try:
        render_closeups(
            options.deck_id,
            options.out_dir,
            windows,
            quality=options.quality,
            samples=options.samples,
            threshold=options.threshold,
            device=options.device,
        )
    except blender.BlenderError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
