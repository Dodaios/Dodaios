"""Import Verse art into the Unreal project and check it (art-pipeline 2).

The only import entry for agents. It runs the editor headless (no window,
`-nullrhi`) with a Python script under the machine-wide `gpu-heavy.lock`:

    UnrealEditor-Cmd.exe <Verse.uproject>
        -ExecutePythonScript=<Content/Python/verse_pipeline/cli.py>
        -unattended -nosplash -nullrhi -nosound -stdout

The `pythonscript` commandlet cannot be used: asset import tasks need the
Slate application, which a commandlet does not create (assertion
`CurrentApplication.IsValid()`).

    python scripts/unreal/import_art.py assets [--only SM_A,SM_B] [--no-save]
    python scripts/unreal/import_art.py placements --deck hangar [--zone arena_canyon] [--dry-run]
    python scripts/unreal/import_art.py validate [--only ...]
    python scripts/unreal/import_art.py calib [--export] [--importer interchange|legacy]
    python scripts/unreal/import_art.py masters [--only M_Verse_Weapon] [--no-save]   (WP14)
    python scripts/unreal/import_art.py materials [--only MI_A,MI_B] [--no-save]      (WP14)
    python scripts/unreal/import_art.py lookdev                                       (WP14, GPU)
    python scripts/unreal/import_art.py wp14 [--no-lookdev]    (WP14: all of it in one hold)

`lookdev` renders frames, so it runs the editor with its RHI (no `-nullrhi`),
still headless and under the same lock (art-pipeline 2).

`calib` is the `fbx-ue/1` calibration test: with `--export` it first runs
`scripts/verse/export_unreal.py calib`, then imports `SM_Calib_Axes` and
`SK_Calib_Rig` without saving and checks them against
`unreal/Verse/Art/space_vectors.json`. Exit 0 only when every check passed.
The report lands in `unreal/Verse/Saved/ArtPipeline/<command>-<stamp>.json`.
The editor modules must be built (`Build.bat VerseEditor Win64 Development`).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import art_common  # noqa: E402

ENGINE_ENV = "DODAIOS_UE_ROOT"
DEFAULT_ENGINE = Path("C:/Program Files/Epic Games/UE_5.7")
CLI = art_common.PROJECT_DIR / "Content" / "Python" / "verse_pipeline" / "cli.py"
REPORT_DIR = art_common.PROJECT_DIR / "Saved" / "ArtPipeline"
TIMEOUT_S = 1800


def engine_root() -> Path:
    override = os.environ.get(ENGINE_ENV, "").strip()
    return Path(override) if override else DEFAULT_ENGINE


def editor_cmd() -> Path:
    exe = "UnrealEditor-Cmd.exe" if os.name == "nt" else "UnrealEditor-Cmd"
    platform = "Win64" if os.name == "nt" else "Linux"
    return engine_root() / "Engine" / "Binaries" / platform / exe


#: Commands that need an RHI. `placements` spawns actors, which the editor places
#: through the level viewport, dividing by its size and crashing without an RHI
#: (UE 5.7.1, measured); `lookdev` and `wp14` (WP14) render frames. They run on the
#: GPU with the window offscreen instead of `-nullrhi`.
RENDERED_COMMANDS = frozenset({"placements", "lookdev", "wp14"})


def rhi_args(command: str = "") -> list[str]:
    if command in RENDERED_COMMANDS:
        return ["-d3d12", "-RenderOffscreen", "-ResX=640", "-ResY=360"]
    return ["-nullrhi"]


def command_line(log: Path, command: str = "") -> list[str]:
    return [
        str(editor_cmd()),
        str(art_common.UPROJECT),
        f"-ExecutePythonScript={CLI}",
        "-unattended",
        "-nosplash",
        *rhi_args(command),
        "-nosound",
        "-NoP4",
        "-stdout",
        "-FullStdOutLogOutput",
        f"-abslog={log}",
    ]


def run_pipeline(argv: list[str]) -> tuple[int, dict, Path]:
    """Run verse_pipeline.cli with `argv`; return (exit code, report, report path)."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = REPORT_DIR / f"{argv[0]}-{stamp}.json"
    log = REPORT_DIR / f"{argv[0]}-{stamp}.log"
    report_path.unlink(missing_ok=True)
    env = dict(
        os.environ,
        VERSE_PIPELINE_ARGS=json.dumps(argv),
        VERSE_PIPELINE_RESULT=str(report_path),
        VERSE_PIPELINE_QUIT="1",
    )
    command = command_line(log, argv[0])
    if not editor_cmd().is_file():
        raise FileNotFoundError(f"{editor_cmd()} not found; set {ENGINE_ENV}")
    with art_common.heavy_lock(f"import_art {argv[0]}"):
        print(f"[verse] {' '.join(command)}", flush=True)
        completed = subprocess.run(
            command,
            env=env,
            cwd=str(art_common.REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_S,
            check=False,
        )
    if not report_path.is_file():
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        tail = text.splitlines()[-40:]
        report = {"ok": False, "error": "the commandlet wrote no report", "log_tail": tail}
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    report["exit_code"] = completed.returncode
    report["log"] = str(log)
    art_common.dump_json(report_path, report)
    return (0 if report.get("ok") else 1), report, report_path


def _print_report(report: dict) -> None:
    if report.get("error"):
        print(f"[verse] error: {report['error']}", file=sys.stderr)
    for key in ("SM_Calib_Axes", "SK_Calib_Rig"):
        if key in report:
            for line in report[key].get("errors", []):
                print(f"[verse] {key}: {line}", file=sys.stderr)
    for line in report.get("errors", []):
        print(f"[verse] {line}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    assets = sub.add_parser("assets", help="import changed assets from their records")
    assets.add_argument("--only", default="")
    assets.add_argument("--no-save", action="store_true")
    placements = sub.add_parser("placements", help="sync a deck's zones from placement JSON")
    placements.add_argument("--deck", required=True)
    placements.add_argument("--zone")
    placements.add_argument("--dry-run", action="store_true")
    validate = sub.add_parser("validate", help="check imported assets against their records")
    validate.add_argument("--only", default="")
    calib = sub.add_parser("calib", help="the fbx-ue/1 calibration test")
    calib.add_argument("--export", action="store_true", help="export the calibration assets first")
    calib.add_argument("--importer", choices=("interchange", "legacy"))
    for name in ("masters", "materials"):
        cmd = sub.add_parser(name, help=f"WP14: build the {name} from text")
        cmd.add_argument("--only", default="")
        cmd.add_argument("--no-save", action="store_true")
    sub.add_parser("lookdev", help="WP14: render the look evidence frames (GPU)")
    wp14 = sub.add_parser("wp14", help="WP14: LUT, masters, MIs, weapons, validate, lookdev")
    wp14.add_argument("--no-lookdev", action="store_true")
    options = parser.parse_args(argv)

    forwarded: list[str] = [options.command]
    if options.command in ("assets", "validate", "masters", "materials") and options.only:
        forwarded += ["--only", options.only]
    if options.command in ("assets", "masters", "materials") and options.no_save:
        forwarded.append("--no-save")
    if options.command == "placements":
        forwarded += ["--deck", options.deck]
        if options.zone:
            forwarded += ["--zone", options.zone]
        if options.dry_run:
            forwarded.append("--dry-run")
    if options.command == "wp14" and options.no_lookdev:
        forwarded.append("--no-lookdev")
    if options.command == "calib":
        if options.export:
            export = HERE.parent / "verse" / "export_unreal.py"
            code = subprocess.call([sys.executable, str(export), "calib"])
            if code != 0:
                return code
        if options.importer:
            forwarded += ["--importer", options.importer]

    try:
        code, report, path = run_pipeline(forwarded)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        print(f"[verse] {error}", file=sys.stderr)
        return 1
    _print_report(report)
    verdict = "PASS" if code == 0 else "FAIL"
    print(f"[verse] import_art {options.command}: {verdict} (report {art_common.rel(path)})")
    return code


if __name__ == "__main__":
    sys.exit(main())
