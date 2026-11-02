#!/usr/bin/env python3
"""Build the gore assets of the Unreal Verse (WP05).

    python art/verse/gore/build.py            # bake masks, then run the editor step
    python art/verse/gore/build.py --bake     # bake masks only (no editor, no lock)

1. Bakes the procedural masks (``textures.py``) to ``art/verse/.cache/gore/``
   (ignored; sources are never committed, art-pipeline 6.4).
2. Runs ``unreal_assets.py`` in a headless editor under the machine-wide
   gpu-heavy lock (``scripts/unreal/with_lock.py``), which imports the masks
   and writes the materials into ``unreal/Verse/Content/Verse/Gore/`` and the
   test body material into ``Content/Verse/Test/WP05/``.

The run fails when the editor step reports a failure or writes no report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import textures  # noqa: E402

from scripts.unreal import _common as common  # noqa: E402
from scripts.unreal import with_lock  # noqa: E402

CACHE = REPO / "art" / "verse" / ".cache" / "gore"


def editor_command(script: Path, log: Path) -> list[str]:
    engine = common.engine_root()
    return [
        str(common.editor_cmd(engine)),
        str(common.project_file(REPO)),
        "-run=pythonscript",
        f"-script={script}",
        "-unattended",
        "-nosplash",
        "-nullrhi",
        "-nosound",
        "-NoP4",
        "-stdout",
        f"-abslog={log}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bake", action="store_true", help="bake the masks only")
    options = parser.parse_args(argv)

    baked = textures.bake(CACHE)
    print(f"[gore] baked {len(baked)} masks into {CACHE}")
    if options.bake:
        return 0

    out_dir = REPO / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP05" / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = out_dir / "unreal_assets.json"
    result.unlink(missing_ok=True)
    env = dict(os.environ)
    env["VERSE_GORE_TEXTURES"] = str(CACHE)
    env["VERSE_GORE_RESULT"] = str(result)
    code = with_lock.run_locked(
        editor_command(HERE / "unreal_assets.py", out_dir / "unreal_assets.log"),
        label="gore assets (wp05)",
        env=env,
    )
    if not result.exists():
        print(f"[gore] editor exited {code} without a report")
        return code or 1
    report = json.loads(result.read_text(encoding="utf-8"))
    for warning in report.get("warnings", []):
        print(f"[gore] warning: {warning}")
    assets = len(report.get("assets", []))
    print(f"[gore] editor exit {code}, ok={report.get('ok')}, assets={assets}")
    if not report.get("ok"):
        print(report.get("traceback", report.get("error", "")))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
