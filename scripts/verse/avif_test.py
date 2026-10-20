"""Size/fidelity sweep of AVIF settings on a raw plate, to pick package.AVIF.

    python scripts/verse/avif_test.py art/verse/.cache/cook/<deck>/final/plate.png

Prints bytes, bits per pixel and PSNR (dB, luma and full RGB) per setting for
the first 2048 px tile. The plate keeps a hard floor of 44 dB luma PSNR on
real decks; choose the smallest setting above it.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

QUALITIES = (50, 60, 66, 72, 78, 85)
SUBSAMPLINGS = ("4:2:0", "4:4:4")


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else 10 * np.log10(255.0**2 / mse)


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def sweep(plate: Path) -> None:
    image = Image.open(plate).convert("RGB")
    tile = image.crop((0, 0, min(2048, image.width), min(2048, image.height)))
    reference = np.asarray(tile)
    pixels = tile.width * tile.height
    print(f"{plate} tile {tile.width}x{tile.height}")
    print(f"{'subsampling':>11} {'q':>3} {'bytes':>9} {'bpp':>6} {'PSNR-Y':>7} {'PSNR':>6}")
    for subsampling in SUBSAMPLINGS:
        for quality in QUALITIES:
            buffer = io.BytesIO()
            tile.save(buffer, format="AVIF", quality=quality, speed=4, subsampling=subsampling)
            decoded = np.asarray(Image.open(io.BytesIO(buffer.getvalue())).convert("RGB"))
            size = buffer.tell()
            print(
                f"{subsampling:>11} {quality:>3} {size:>9} {8 * size / pixels:>6.3f} "
                f"{psnr(luma(reference), luma(decoded)):>7.2f} {psnr(reference, decoded):>6.2f}"
            )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plate", type=Path)
    sweep(parser.parse_args(argv).plate)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
