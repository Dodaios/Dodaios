"""Blender side of `kit_export.py --missing`: write every registered kit piece name.

    argv: OUT.json
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from lib import kit

for name in ("kit.architecture", "kit.props.command", "kit.props.industrial"):
    module = importlib.import_module(name)
    if callable(getattr(module, "load_all", None)):
        module.load_all()
Path(sys.argv[-1]).write_text(json.dumps(sorted(kit.registry())), encoding="utf-8")
print(f"[verse] {len(kit.registry())} kit pieces")
