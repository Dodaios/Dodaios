#!/usr/bin/env python3
"""Regenerate the G0.8 and G0.9 Unreal content from code.

G0.8: the empty World Partition deck maps ``LV_Bridge``, ``LV_Ops``,
``LV_Engineering`` and ``LV_Hangar`` (One File Per Actor on) with their data
layers ``DL_<Deck>_Base`` plus ``DL_Hangar_Day`` and ``DL_Hangar_Arena``.
G0.9: the ``SK_Test_Human`` placeholder skeleton with the frozen bone names of
``docs/verse/unreal/contracts/art-pipeline.md`` 12.1.

Steps, each optional:

1. ``blender``: build the placeholder in Blender and export an FBX into the
   ignored cache ``art/verse/.cache/unreal/g0/`` (never committed).
2. ``editor``: run ``g0/editor_content.py`` in the headless editor's
   ``pythonscript`` commandlet (``-nullrhi``), which creates the maps and data
   layers, imports the FBX and verifies everything. Only the resulting
   ``.uasset``/``.umap`` files are committed, through Git LFS.

    python scripts/unreal/g0_content.py                 # both steps
    python scripts/unreal/g0_content.py --step editor   # maps and import only
    python scripts/unreal/g0_content.py --verify-only   # check, change nothing

The editor must be compiled first (``Build.bat VerseEditor Win64 Development``).
Never run it while another editor holds the project.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT = REPO_ROOT / "unreal" / "Verse" / "Verse.uproject"
HERE = Path(__file__).resolve().parent / "g0"
FBX = REPO_ROOT / "art" / "verse" / ".cache" / "unreal" / "g0" / "SK_Test_Human.fbx"
DEFAULT_ENGINE = Path("C:/Program Files/Epic Games/UE_5.7")
DEFAULT_BLENDER = Path("C:/Program Files/Blender Foundation/Blender 5.0/blender.exe")


def _engine_root() -> Path:
    return Path(os.environ.get("VERSE_UE_ROOT", DEFAULT_ENGINE))


def _blender() -> Path:
    return Path(os.environ.get("VERSE_BLENDER", DEFAULT_BLENDER))


def run_blender() -> None:
    FBX.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(_blender()), "-b", "--factory-startup",
        "-P", str(HERE / "test_human_blender.py"), "--", str(FBX),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if out.returncode != 0 or "VERSE_G0 exported" not in out.stdout:
        sys.stderr.write(out.stdout[-4000:] + out.stderr[-4000:])
        raise SystemExit("blender step failed")
    print(next(ln for ln in out.stdout.splitlines() if "VERSE_G0" in ln))


def run_editor(verify_only: bool, log: Path) -> None:
    editor = _engine_root() / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    script = HERE / "editor_content.py"
    env = dict(os.environ)
    env["VERSE_G0_FBX"] = str(FBX)
    env["VERSE_G0_MODE"] = "verify" if verify_only else "build"
    cmd = [
        str(editor), str(PROJECT),
        "-run=pythonscript", f"-script={script}",
        "-nullrhi", "-unattended", "-nosplash", "-NoSound", "-nop4",
        f"-abslog={log}",
    ]
    out = subprocess.run(  # noqa: S603
        cmd, env=env, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    marks = [ln for ln in text.splitlines() if "VERSE_G0" in ln]
    for ln in marks:
        print(ln.split("LogPython: ", 1)[-1])
    if out.returncode != 0 or not any("VERSE_G0 OK" in ln for ln in marks):
        raise SystemExit(f"editor step failed (exit {out.returncode}); log: {log}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", choices=("all", "blender", "editor"), default="all")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--log", type=Path,
                        default=REPO_ROOT / "unreal" / "Verse" / "Saved" / "g0_content.log")
    args = parser.parse_args()
    if args.verify_only:
        run_editor(True, args.log)
        return 0
    if args.step in ("all", "blender"):
        run_blender()
    if args.step in ("all", "editor"):
        if not FBX.exists():
            raise SystemExit(f"missing {FBX}; run --step blender first")
        run_editor(False, args.log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
