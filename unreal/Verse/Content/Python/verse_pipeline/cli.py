"""Commandlet entry of verse_pipeline, run by `scripts/unreal/import_art.py`.

    UnrealEditor-Cmd Verse.uproject -run=pythonscript -script=<this file>
        -unattended -nosplash -nullrhi

Arguments come in `VERSE_PIPELINE_ARGS` (a JSON list, so nothing is lost to
command-line quoting); the JSON report goes to `VERSE_PIPELINE_RESULT`. The
host reads the report, so a failure is never hidden by the commandlet's own
exit code.

Commands: `assets [--only A,B] [--no-save]`, `placements --deck D [--zone Z]
[--dry-run]`, `validate [--only A,B]`, `calib [--importer interchange|legacy]`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

ARGS_ENV = "VERSE_PIPELINE_ARGS"
RESULT_ENV = "VERSE_PIPELINE_RESULT"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verse_pipeline.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    assets = sub.add_parser("assets")
    assets.add_argument("--only", default="")
    assets.add_argument("--no-save", action="store_true")
    placements = sub.add_parser("placements")
    placements.add_argument("--deck", required=True)
    placements.add_argument("--zone")
    placements.add_argument("--dry-run", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--only", default="")
    calib = sub.add_parser("calib")
    calib.add_argument("--importer", choices=("interchange", "legacy"))
    return parser


def _only(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def dispatch(argv: list[str]) -> dict:
    options = _parser().parse_args(argv)
    if options.command == "calib":
        from verse_pipeline import calib

        return calib.run(importer=options.importer)
    if options.command == "assets":
        from verse_pipeline import import_assets

        return import_assets.run(_only(options.only), save=not options.no_save)
    if options.command == "placements":
        from verse_pipeline import sync_placements

        return sync_placements.run(options.deck, options.zone, dry_run=options.dry_run)
    from verse_pipeline import validate_assets

    return validate_assets.run(_only(options.only))


def main() -> None:
    raw = os.environ.get(ARGS_ENV, "")
    argv = json.loads(raw) if raw else sys.argv[1:]
    result_path = os.environ.get(RESULT_ENV, "")
    try:
        report = dispatch(argv)
    except BaseException as error:  # the host must see every failure in the report
        report = {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }
    print("[verse_pipeline] " + json.dumps({"ok": report.get("ok"), "command": argv[:1]}))
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report.get("ok"):
        raise RuntimeError(report.get("error") or "verse_pipeline reported failures")


if __name__ == "__main__":
    main()
