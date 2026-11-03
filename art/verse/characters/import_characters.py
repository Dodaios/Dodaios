"""Import the WP13 characters, skeleton, physics, IK rig and clips into Unreal.

    python art/verse/characters/import_characters.py [--only A,B]

Needs the export first (`python scripts/verse/export_unreal.py characters`)
and a built editor (`python scripts/unreal/build.py editor`). Runs the
headless editor (`-nullrhi`) with `fps/ue_import.py` under the machine lock
of `scripts/unreal/with_lock.py`; the report lands in
`unreal/Verse/Saved/ArtPipeline/characters-<stamp>.json`. Exit 0 only when
the import reported no error.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "unreal"))

import art_common  # noqa: E402
import import_art  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "fps" / "ue_import.py"
RESULT = art_common.CACHE_ROOT / "results" / "characters.json"
TIMEOUT_S = 3600


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="")
    options = parser.parse_args(argv)
    if not RESULT.is_file():
        print(
            f"[verse] {art_common.rel(RESULT)} missing: run export_unreal.py characters",
            file=sys.stderr,
        )
        return 1
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report = import_art.REPORT_DIR / f"characters-{stamp}.json"
    log = import_art.REPORT_DIR / f"characters-{stamp}.log"
    report.parent.mkdir(parents=True, exist_ok=True)
    command = import_art.command_line(log)
    command[2] = f"-ExecutePythonScript={SCRIPT}"
    env = dict(
        os.environ,
        VERSE_CHAR_RESULT=str(RESULT),
        VERSE_CHAR_REPORT=str(report),
        VERSE_CHAR_ONLY=options.only,
        VERSE_CHAR_QUIT="1",
    )
    with art_common.heavy_lock("import_characters wp13"):
        print(f"[verse] {' '.join(command)}", flush=True)
        completed = subprocess.run(  # noqa: S603 - fixed editor command line
            command,
            env=env,
            cwd=str(REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_S,
            check=False,
        )
    if not report.is_file():
        tail = (
            log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
            if log.is_file()
            else []
        )
        print("[verse] the editor wrote no report:\n" + "\n".join(tail), file=sys.stderr)
        return 1
    data = json.loads(report.read_text(encoding="utf-8"))
    for line in data.get("errors", []):
        print(f"[verse] error: {line}", file=sys.stderr)
    print(
        f"[verse] characters import: {len(data.get('imported', []))} imported, "
        f"{len(data.get('skipped', []))} skipped, exit {completed.returncode}, "
        f"{'PASS' if data.get('ok') else 'FAIL'} (report {art_common.rel(report)})"
    )
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
