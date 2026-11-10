"""Editor entry of verse_pipeline, run by `scripts/unreal/import_art.py`.

    UnrealEditor-Cmd Verse.uproject -ExecutePythonScript=<this file>
        -unattended -nosplash -nullrhi

Arguments come in `VERSE_PIPELINE_ARGS` (a JSON list, so nothing is lost to
command-line quoting); the JSON report goes to `VERSE_PIPELINE_RESULT`. The
host reads the report, so a failure is never hidden by the editor's own exit
code. With `VERSE_PIPELINE_QUIT=1` the editor quits when the command is done.

Commands: `assets [--only A,B] [--no-save]`, `placements --deck D [--zone Z]
[--dry-run]`, `validate [--only A,B]`, `calib [--importer interchange|legacy]`,
`masters [--only M_A] [--no-save]`, `materials [--only MI_A] [--no-save]`,
`bind [--only SM_A] [--no-save]`, `lookdev`, `wp14 [--no-lookdev]` (WP14, art-pipeline 2). A command that needs
rendered frames may return `{"deferred": true}`; it then writes the report and
quits the editor itself.
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
    for name in ("masters", "materials", "bind"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--only", default="")
        cmd.add_argument("--no-save", action="store_true")
    sub.add_parser("lookdev")
    wp14 = sub.add_parser("wp14")
    wp14.add_argument("--no-lookdev", action="store_true")
    return parser


def _wp14(module: str):
    from verse_pipeline import wp14_editor

    found = wp14_editor(module)
    if found is None:
        raise RuntimeError(f"weapons.editor.{module} is not in art/verse/weapons/editor/ (WP14)")
    return found


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
    if options.command == "masters":
        return _wp14("masters").run(_only(options.only), save=not options.no_save)
    if options.command == "materials":
        from verse_pipeline import materials

        return materials.run(_only(options.only), save=not options.no_save)
    if options.command == "bind":
        from verse_pipeline import bind

        return bind.run(_only(options.only), save=not options.no_save)
    if options.command == "lookdev":
        return _wp14("lookdev").run()
    if options.command == "wp14":
        return _wp14("chain").run(with_lookdev=not options.no_lookdev)
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
    if report.get("deferred"):
        print("[verse_pipeline] " + json.dumps({"deferred": True, "command": argv[:1]}))
        return
    print("[verse_pipeline] " + json.dumps({"ok": report.get("ok"), "command": argv[:1]}))
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if os.environ.get("VERSE_PIPELINE_QUIT") == "1":
        import unreal

        unreal.SystemLibrary.quit_editor()
    elif not report.get("ok"):
        raise RuntimeError(report.get("error") or "verse_pipeline reported failures")


if __name__ == "__main__":
    main()
