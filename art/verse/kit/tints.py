"""The shared tint file `kit/material_tints.json` (WP12, art-pipeline 7).

Pure Python. The kit and deck exports record, per Blender material, what its Principled
BSDF says (`kit/export_materials.py`); `kit/mi_recipes.py` reads the file to write the
recipes of materials that `lib/materials.py` does not declare.
"""

from __future__ import annotations

import json
from pathlib import Path

PATH = Path(__file__).with_name("material_tints.json")


def load(path: Path = PATH) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def merge(found: dict[str, dict], path: Path = PATH) -> None:
    """Add (or replace) material tints, sorted, as stable text."""
    known = load(path)
    known.update(found)
    text = json.dumps(dict(sorted(known.items())), indent=1, sort_keys=True) + "\n"
    path.write_bytes(text.encode("utf-8"))
