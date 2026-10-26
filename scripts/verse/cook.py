"""Cook Verse content: build a deck in Blender, render and package it.

    python scripts/verse/cook.py deck <id> [--quality preview|final] [--keep-blend]
                                         [--device auto|optix|cuda|cpu] [--out DIR]
                                         [--realtime]

Runs `art/verse/decks/<id>/build.py` and `lib.cook.cook_deck()` inside headless
Blender (holding the GPU lock), then packages the raw output into
`dodaios/ui/web/frontend/public/verse/decks/<id>/` and validates it.
--keep-blend saves the built scene to art/verse/.cache/blend/LV_<id>.blend.

--realtime runs the realtime (eye-level) export instead of the plate cook:
`lib.realtime.export_realtime()` bakes the lightmaps and reflection probes
and `package_realtime.py` writes `<deck>/realtime/` and the manifest's
`realtime` block (docs/verse/realtime.md). The plate stays as it is; the
deck must have been cooked once.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import blender  # noqa: E402
import package  # noqa: E402
import package_realtime  # noqa: E402
import validate  # noqa: E402

PUBLIC_VERSE = blender.REPO_ROOT / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse"
PUBLIC_DECKS = PUBLIC_VERSE / "decks"
ENTRY = Path(__file__).resolve().with_name("_cook_entry.py")
REALTIME_ENTRY = Path(__file__).resolve().with_name("_realtime_entry.py")


def cook_deck(
    deck_id: str,
    quality: str = "final",
    *,
    keep_blend: bool = False,
    device: str = "auto",
    out_dir: Path | None = None,
) -> dict:
    """Cook one deck end to end and return its manifest."""
    raw_dir = blender.CACHE_ROOT / "cook" / deck_id / quality
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True)
    args = [deck_id, str(raw_dir), quality]
    if keep_blend:
        args += ["--blend", str(blender.CACHE_ROOT / "blend" / f"LV_{deck_id}.blend")]
    result = blender.run(ENTRY, args, device=device, timeout=4 * 3600)
    out_dir = out_dir or PUBLIC_DECKS / deck_id
    manifest = package.package_deck(raw_dir, out_dir, {"blender_s": round(result.seconds, 1)})
    problems = validate.validate_deck_dir(out_dir)
    if problems:
        raise SystemExit("cooked deck failed validation:\n  " + "\n  ".join(problems))
    return manifest


def cook_realtime(
    deck_id: str,
    quality: str = "final",
    *,
    keep_blend: bool = False,
    device: str = "auto",
    out_dir: Path | None = None,
) -> dict:
    """Run the realtime export of one deck end to end and return its manifest block."""
    raw_dir = blender.CACHE_ROOT / "cook" / deck_id / f"realtime-{quality}"
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True)
    args = [deck_id, str(raw_dir), quality]
    if keep_blend:
        args += ["--blend", str(blender.CACHE_ROOT / "blend" / f"RT_{deck_id}.blend")]
    result = blender.run(REALTIME_ENTRY, args, device=device, timeout=4 * 3600)
    out_dir = out_dir or PUBLIC_DECKS / deck_id
    block = package_realtime.package_realtime(
        raw_dir, out_dir, {"blender_s": round(result.seconds, 1)}
    )
    problems = validate.validate_deck_dir(out_dir)
    if problems:
        raise SystemExit("realtime export failed validation:\n  " + "\n  ".join(problems))
    return block


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    deck = sub.add_parser("deck", help="cook one deck")
    deck.add_argument("deck_id")
    deck.add_argument("--quality", choices=("preview", "final"), default="final")
    deck.add_argument("--keep-blend", action="store_true")
    deck.add_argument("--device", choices=blender.DEVICES, default="auto")
    deck.add_argument(
        "--out", type=Path, help="output directory (default: public/verse/decks/<id>)"
    )
    deck.add_argument(
        "--realtime", action="store_true", help="realtime (eye-level) export instead of the plate"
    )
    options = parser.parse_args(argv)
    if options.realtime:
        try:
            block = cook_realtime(
                options.deck_id,
                options.quality,
                keep_blend=options.keep_blend,
                device=options.device,
                out_dir=options.out,
            )
        except blender.BlenderError as error:
            print(error, file=sys.stderr)
            return 1
        scene, stats = block["scene"], block["stats"]
        print(
            f"[verse] {options.deck_id} realtime ({block['quality']}): {scene['triangles']} "
            f"triangles in {scene['chunks']} chunks, {len(block['lightmaps']['pages'])} lightmap "
            f"page(s) at {stats.get('density')} px/m, {block['bytes'] / 1e6:.2f} MB; "
            f"blender {stats.get('blender_s')} s, package {stats.get('package_s')} s"
        )
        return 0
    try:
        manifest = cook_deck(
            options.deck_id,
            options.quality,
            keep_blend=options.keep_blend,
            device=options.device,
            out_dir=options.out,
        )
    except blender.BlenderError as error:
        print(error, file=sys.stderr)
        return 1
    stats = manifest["stats"]
    camera = manifest["camera"]
    print(
        f"[verse] {manifest['id']} ({manifest['quality']}): plate {camera['plate_w_px']}x"
        f"{camera['plate_h_px']} px, {stats['plate_bytes'] / 1e6:.2f} MB plate, "
        f"{stats['bytes'] / 1e6:.2f} MB total; plate {stats['plate_s']} s, nav {stats['nav_s']} s, "
        f"lighting {stats['lighting_s']} s, blender total {stats['blender_s']} s, "
        f"package {stats['package_s']} s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
