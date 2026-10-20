"""Blender-side cook job: build a deck, optionally save the .blend, cook it.

Run by scripts/verse/cook.py through scripts/verse/blender.py:
    _cook_entry.py <deck_id> <raw_dir> <quality> [--blend <path.blend>]
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import bpy
from lib import cook

ART_ROOT = Path(__file__).resolve().parents[2] / "art" / "verse"


def load_builder(deck_id: str):
    path = ART_ROOT / "decks" / deck_id / "build.py"
    if not path.is_file():
        raise FileNotFoundError(f"no deck builder at {path}")
    spec = importlib.util.spec_from_file_location(f"verse_deck_{deck_id}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "build"):
        raise AttributeError(f"{path} must define build()")
    return module


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
    if options.blend:
        started = time.monotonic()
        options.blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(options.blend), compress=True)
        print(
            f"[verse] stage save: {time.monotonic() - started:.1f} s ({options.blend})", flush=True
        )
    result = cook.cook_deck(options.deck_id, options.raw_dir, options.quality)
    print(f"[verse] cooked {options.deck_id}: {result['stats']}", flush=True)


if __name__ == "__main__":
    main()
