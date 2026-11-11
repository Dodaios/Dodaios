"""The Sovereign skin, Arc Storm and the hoverboard for the Unreal Verse (stream S7).

This package shares its name with the Blender builder of the skin, `characters/sovereign.py`,
and a package wins the import. Inside Blender the package therefore loads that module and
offers its names, so `from characters import sovereign` gives `build_sovereign` and the
skin's materials to `build.py` (three.js) and `rig_fps.py` (Unreal). Outside Blender (the
editor step runs its scripts by path) it stays empty.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_builder():
    path = Path(__file__).resolve().parent.parent / "sovereign.py"
    spec = importlib.util.spec_from_file_location("characters._sovereign_skin", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


try:
    import bpy  # noqa: F401 - only present inside Blender
except ImportError:
    pass
else:
    globals().update({k: v for k, v in vars(_load_builder()).items() if not k.startswith("__")})
