"""Blender-side realtime export job: build a deck, bake and export it for the
eye-level view (docs/verse/realtime.md).

Run by scripts/verse/cook.py through scripts/verse/blender.py:
    _realtime_entry.py <deck_id> <raw_dir> <quality> [--blend <path.blend>]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import bpy
from _cook_entry import load_builder
from lib import realtime


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("deck_id")
    parser.add_argument("raw_dir", type=Path)
    parser.add_argument("quality")
    parser.add_argument("--blend", type=Path)
    options = parser.parse_args(sys.argv[1:])
    started = time.monotonic()
    load_builder(options.deck_id).build()
    print(f"[verse] stage build: {time.monotonic() - started:.1f} s", flush=True)
    result = realtime.export_realtime(options.deck_id, options.raw_dir, options.quality)
    if options.blend:
        options.blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(options.blend), compress=True)
    print(f"[verse] realtime {options.deck_id}: {result['stats']}", flush=True)


if __name__ == "__main__":
    main()
