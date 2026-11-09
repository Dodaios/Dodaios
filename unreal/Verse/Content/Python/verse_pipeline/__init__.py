"""Editor Python of the Verse art pipeline (docs/verse/unreal/contracts/art-pipeline.md).

Unreal puts `Content/Python` on `sys.path`; this package is never cooked.
The host entry is `scripts/unreal/import_art.py`, which runs
`UnrealEditor-Cmd -run=pythonscript -script=<cli.py>` under the machine-wide
lock. Modules that touch the engine import `unreal` lazily, so the pure parts
(records, plans, checks) are tested with pytest outside the editor.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parents[2]
REPO_ROOT = PROJECT_DIR.parents[1]
ART_TEXT = PROJECT_DIR / "Art"
IMPORT_RECORDS = ART_TEXT / "Import"
PLACEMENTS = ART_TEXT / "Placements"
MI_RECIPES = ART_TEXT / "Materials"
SPACE_VECTORS = ART_TEXT / "space_vectors.json"
CACHE_ROOT = REPO_ROOT / "art" / "verse" / ".cache" / "unreal"

SETTINGS_ID = "fbx-ue/1"


def art_on_path() -> None:
    """Put `art/verse` on `sys.path`, so WP14's editor code (`weapons.editor`) imports."""
    import sys

    path = str(REPO_ROOT / "art" / "verse")
    if path not in sys.path:
        sys.path.insert(0, path)


def wp14_editor(module: str):
    """WP14's `weapons.editor.<module>`, or None while that code is not in the tree.

    The import finish and the extra checks it provides only apply to WP14 assets, which
    land together with the code (art-pipeline 2), so its absence skips them.
    """
    import importlib
    import importlib.util

    art_on_path()
    importlib.invalidate_caches()
    try:
        if importlib.util.find_spec("weapons.editor") is None:
            return None
    except ModuleNotFoundError:
        return None
    return importlib.import_module(f"weapons.editor.{module}")
