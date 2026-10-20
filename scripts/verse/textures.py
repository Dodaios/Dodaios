"""Fetch CC0 textures and HDRIs from Poly Haven into the Verse cache.

    python scripts/verse/textures.py <asset> [--maps Diffuse nor_gl Rough] [--res 2k] [--format jpg]
    python scripts/verse/textures.py <hdri_asset> --hdri [--res 2k]

Thin CLI over art/verse/lib/textures.py (which builders call inside Blender as
`from lib import textures`). Every file is recorded in art/verse/LICENSES.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "art" / "verse"))

from lib import textures  # noqa: E402


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("asset")
    parser.add_argument("--maps", nargs="+", default=["Diffuse", "nor_gl", "Rough"])
    parser.add_argument("--res", default="2k")
    parser.add_argument("--format", dest="fmt")
    parser.add_argument("--hdri", action="store_true", help="fetch the asset as an HDRI (.hdr)")
    options = parser.parse_args(argv)
    if options.hdri:
        print(textures.ensure_hdri(options.asset, options.res))
        return 0
    for key, path in textures.ensure(options.asset, options.maps, options.res, options.fmt).items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
