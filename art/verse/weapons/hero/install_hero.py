"""Import the hero Graveline into Unreal: mesh, skeleton, baked skin and instances.

    python art/verse/weapons/hero/install_hero.py

Run `export_hero.py` first (it writes the FBX, the maps and the import records).
Steps, under the machine-wide lock: `import_art.py assets` for the mesh and its
skeleton, then the editor script `editor_install.py` for the textures, the three
material instances and the slot binding.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts" / "unreal"))

import art_common  # noqa: E402
import import_art  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "editor_install.py"
SOURCE = REPO / "art" / "verse" / ".cache" / "weapons" / "hero"
ASSETS = "SK_Weapon_GravelineHero,SKEL_Weapon_GravelineHero"
TIMEOUT_S = 1800


def import_mesh() -> int:
    command = [
        sys.executable,
        str(REPO / "scripts/unreal/import_art.py"),
        "assets",
        "--only",
        ASSETS,
    ]
    print(f"[hero] {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=str(REPO), check=False).returncode  # noqa: S603


def install_skin() -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report = import_art.REPORT_DIR / f"hero-install-{stamp}.json"
    log = import_art.REPORT_DIR / f"hero-install-{stamp}.log"
    report.parent.mkdir(parents=True, exist_ok=True)
    command = import_art.command_line(log)
    command[2] = f"-ExecutePythonScript={SCRIPT}"
    env = dict(os.environ, VERSE_PIPELINE_RESULT=str(report), VERSE_HERO_SRC=str(SOURCE))
    with art_common.heavy_lock("install_hero"):
        subprocess.run(  # noqa: S603 - fixed editor command line
            command,
            env=env,
            cwd=str(REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_S,
            check=False,
        )
    if not report.is_file():
        print(f"[hero] the editor wrote no report, see {log}", file=sys.stderr)
        return 1
    data = json.loads(report.read_text(encoding="utf-8"))
    for line in data.get("errors", []):
        print(f"[hero] error: {line}", file=sys.stderr)
    print(
        f"[hero] install: {data.get('imported')} {data.get('instances')} slots {data.get('slots')}"
    )
    return 0 if data.get("ok") else 1


def main() -> int:
    code = import_mesh()
    if code:
        return code
    return install_skin()


if __name__ == "__main__":
    sys.exit(main())
