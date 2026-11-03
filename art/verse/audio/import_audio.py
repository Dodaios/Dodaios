#!/usr/bin/env python3
"""Build and import every Verse sound into the Unreal project (WP19).

1. ``build_audio.py``: synthesise and convert every cue variant into the
   ignored cache ``art/verse/.cache/audio/`` (WAVs never enter git).
2. The headless editor (``pythonscript`` commandlet, ``-nullrhi``) runs
   ``editor/import_sounds.py`` under the machine lock: it imports the WAVs as
   ``SW_*`` sound waves under ``/Game/Verse/Audio/`` and writes
   ``DA_AudioCues``. Only those ``.uasset`` files are committed (Git LFS).
3. ``audit_licences.py --require-assets``: every asset cites ``own`` or a
   ledger row.

    python art/verse/audio/import_audio.py              # all steps
    python art/verse/audio/import_audio.py --verify     # check the imported asset only

The editor target must be built first (``python scripts/unreal/build.py editor``).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_licences  # noqa: E402
import build_audio  # noqa: E402

REPO_ROOT = build_audio.REPO_ROOT
PROJECT = REPO_ROOT / "unreal" / "Verse" / "Verse.uproject"
EDITOR_SCRIPT = Path(__file__).resolve().parent / "editor" / "import_sounds.py"
DEFAULT_ENGINE = Path("C:/Program Files/Epic Games/UE_5.7")


def editor_cmd() -> Path:
    root = Path(os.environ.get("VERSE_UE_ROOT", DEFAULT_ENGINE))
    return root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"


def run_editor(verify: bool, log: Path) -> None:
    env = dict(os.environ)
    env["VERSE_AUDIO_REPO"] = str(REPO_ROOT)
    env["VERSE_AUDIO_MODE"] = "verify" if verify else "build"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "unreal" / "with_lock.py"),
        "--label",
        "wp19-audio-import",
        "--",
        str(editor_cmd()),
        str(PROJECT),
        "-run=pythonscript",
        f"-script={EDITOR_SCRIPT}",
        "-nullrhi",
        "-unattended",
        "-nosplash",
        # No -NoSound: without the audio mixer the BINKA decoder is not
        # registered and the sound-wave factory fails an ensure on import.
        "-nop4",
        f"-abslog={log}",
    ]
    out = subprocess.run(cmd, env=env, check=False)  # noqa: S603
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    marks = [ln.split("LogPython: ", 1)[-1] for ln in text.splitlines() if "VERSE_AUDIO" in ln]
    for ln in marks:
        print(ln)
    if out.returncode != 0 or not any("VERSE_AUDIO OK" in ln for ln in marks):
        raise SystemExit(f"editor import failed (exit {out.returncode}); log: {log}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="check DA_AudioCues, import nothing")
    parser.add_argument(
        "--log",
        type=Path,
        default=REPO_ROOT / "unreal" / "Verse" / "Saved" / "Logs" / "wp19_audio_import.log",
    )
    args = parser.parse_args(argv)
    if not args.verify:
        manifest = build_audio.build()
        print(f"built {len(manifest['sounds'])} sounds")
    run_editor(args.verify, args.log)
    return audit_licences.main(["--require-assets"])


if __name__ == "__main__":
    raise SystemExit(main())
