#!/usr/bin/env python3
"""Build the Sovereign assets of the Unreal Verse (stream S7).

    python art/verse/characters/sovereign/build.py                       # every asset
    python art/verse/characters/sovereign/build.py --only M_Sov_ArcBolt  # listed assets only
    python art/verse/characters/sovereign/build.py --turntable           # SK_Sovereign, four sides

Runs ``unreal_assets.py`` in a headless editor (``-ExecutePythonScript``) under
the machine-wide gpu-heavy lock (``scripts/unreal/with_lock.py``); it writes
into ``unreal/Verse/Content/Verse/Characters/Sovereign/``. The run fails when
the editor step reports a failure or writes no report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))

from scripts.unreal import _common as common  # noqa: E402
from scripts.unreal import with_lock  # noqa: E402

ASSETS = ("M_Sov_ArcBolt", "M_Sov_Board")


def editor_command(script: Path, log: Path) -> list[str]:
    return [
        str(common.editor_cmd(common.engine_root())),
        str(common.project_file(REPO)),
        f"-ExecutePythonScript={script}",
        "-unattended",
        "-nosplash",
        "-nullrhi",
        "-nosound",
        "-NoP4",
        "-stdout",
        f"-abslog={log}",
    ]


def turntable(out_dir: Path, ev: float) -> int:
    """Render SK_Sovereign from four sides (`turntable.py`) on the GPU, offscreen."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "turntable.json").unlink(missing_ok=True)
    command = editor_command(HERE / "turntable.py", out_dir / "turntable.log")
    command = [c for c in command if c != "-nullrhi"]
    command += ["-d3d12", "-RenderOffscreen", "-ResX=640", "-ResY=360"]
    env = dict(os.environ)
    env.update(
        VERSE_SOV_TURNTABLE_OUT=str(out_dir), VERSE_SOV_TURNTABLE_EV=str(ev), VERSE_SOV_QUIT="1"
    )
    code = with_lock.run_locked(command, label="sovereign turntable (s7)", env=env)
    report = out_dir / "turntable.json"
    if not report.exists():
        print(f"[sovereign] turntable: editor exited {code} without a report")
        return code or 1
    data = json.loads(report.read_text(encoding="utf-8"))
    print(f"[sovereign] turntable ok={data.get('ok')} frames={data.get('frames')} in {out_dir}")
    return 0 if data.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", default=[], help="rebuild only these assets")
    parser.add_argument("--turntable", action="store_true", help="render SK_Sovereign (proof)")
    parser.add_argument("--ev", type=float, default=1.0, help="turntable exposure bias")
    options = parser.parse_args(argv)
    if options.turntable:
        proof = REPO / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "S7" / "turntable"
        return turntable(proof, options.ev)
    unknown = sorted(set(options.only) - set(ASSETS))
    if unknown:
        parser.error(f"unknown assets: {', '.join(unknown)}")
    out_dir = REPO / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "S7" / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = out_dir / "unreal_assets.json"
    result.unlink(missing_ok=True)
    env = dict(os.environ)
    env["VERSE_SOV_RESULT"] = str(result)
    env["VERSE_SOV_QUIT"] = "1"
    env["VERSE_SOV_ONLY"] = ",".join(options.only)
    code = with_lock.run_locked(
        editor_command(HERE / "unreal_assets.py", out_dir / "unreal_assets.log"),
        label="sovereign assets (s7)",
        env=env,
    )
    if not result.exists():
        print(f"[sovereign] editor exited {code} without a report")
        return code or 1
    report = json.loads(result.read_text(encoding="utf-8"))
    for warning in report.get("warnings", []):
        print(f"[sovereign] warning: {warning}")
    assets = len(report.get("assets", []))
    print(f"[sovereign] editor exit {code}, ok={report.get('ok')}, assets={assets}")
    if not report.get("ok"):
        print(report.get("traceback", report.get("error", "")))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
