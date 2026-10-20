"""Download the CC0 Poly Haven maps the kit materials use into the cache.

Run outside Blender with any Python 3.11+ (standard library only):

    python art/verse/lookdev/fetch_textures.py

Delegates to the pipeline's ``lib.textures.ensure`` (MD5 check, the
pipeline's User-Agent, one append-only row per file in ``LICENSES.md``).
Files land in ``art/verse/.cache/textures/<asset>/`` (git-ignored).
Materials fall back to procedural-only detail when a file is missing, so a
cook never fails for lack of a download.

Only roughness and height maps are used: the kit has no UVs, so height
drives a Bump node instead of a tangent-space normal map.
"""

from __future__ import annotations

import sys
from pathlib import Path

VERSE = Path(__file__).resolve().parents[1]
if str(VERSE) not in sys.path:
    sys.path.insert(0, str(VERSE))

from lib import textures  # noqa: E402

WANTED: dict[str, tuple[str, ...]] = {
    "blue_metal_plate": ("Rough", "Displacement"),
    "metal_plate_02": ("Rough", "Displacement"),
    "green_metal_rust": ("Rough",),
    "painted_concrete_02": ("Rough",),
}


def main() -> int:
    for asset, maps in WANTED.items():
        for key, path in textures.ensure(asset, maps, res="2k").items():
            print(f"ok {asset} {key}: {path.relative_to(VERSE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
