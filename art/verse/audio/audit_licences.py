#!/usr/bin/env python3
"""Licence audit of every Verse sound (WP19.9, acceptance A19.6).

Every sound asset must cite ``own`` (built by ``recipes.py``) or the ledger
rows of ``art/verse/LICENSES.md`` that cover its third-party source recordings.

Checks:
1. Each cue in ``cues.json`` has a licence ``own`` or ``cc0:<key>[,<key>]``.
2. A CC0 cue names the recording(s) it reads; each file has a ledger row
   whose Asset column lists every key the cue cites, whose licence column is
   filled (any licence; the ledger is no longer CC0-only) and whose SHA-256 matches the file in the repo.
3. Each ``SW_*.uasset`` under ``unreal/Verse/Content/Verse/Audio/`` is a
   variant of a cue in ``cues.json`` (no orphan, so no uncited sound), and
   with ``--require-assets`` every variant has its asset.

    python art/verse/audio/audit_licences.py [--require-assets] [--report PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_audio  # noqa: E402

REPO_ROOT = build_audio.REPO_ROOT
LEDGER = REPO_ROOT / "art" / "verse" / "LICENSES.md"
CONTENT = REPO_ROOT / "unreal" / "Verse" / "Content" / "Verse" / "Audio"
LICENCE_RE = re.compile(r"^(own|cc0:[A-Za-z0-9]+(,[A-Za-z0-9]+)*)$")


def ledger_rows(path: Path = LEDGER) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] in ("Asset", "") or set(cells[0]) <= {"-"}:
            continue
        rows.append(dict(zip(("asset", "file", "license", "url", "sha256"), cells, strict=True)))
    return rows


def cue_files(cue: dict) -> list[str]:
    files = list(cue.get("files") or [])
    if "file" in cue.get("params", {}):
        files.append(cue["params"]["file"])
    return sorted(set(files))


def audit(cues_doc: dict, rows: list[dict], content: Path, require_assets: bool) -> list[str]:
    problems: list[str] = []
    by_file = {r["file"]: r for r in rows}
    expected: dict[str, str] = {}
    for cue in cues_doc["cues"]:
        cid, lic = cue["id"], cue.get("licence", "")
        for v in range(int(cue["variants"])):
            expected[build_audio.asset_name(cid, v)] = lic
        if not LICENCE_RE.match(lic):
            problems.append(f"{cid}: licence {lic!r} is neither 'own' nor 'cc0:<keys>'")
            continue
        files = cue_files(cue)
        if lic == "own":
            if files or cue["recipe"].startswith("cc0"):
                problems.append(f"{cid}: reads a recording but cites 'own'")
            continue
        keys = lic.split(":", 1)[1].split(",")
        if not files:
            problems.append(f"{cid}: cites {lic} but reads no recording")
        for f in files:
            row = by_file.get(f)
            if row is None:
                problems.append(f"{cid}: no ledger row for {f}")
                continue
            if not row["license"].strip():
                problems.append(f"{cid}: ledger row for {f} names no licence")
            missing = [k for k in keys if k not in row["asset"].split()]
            if missing:
                problems.append(f"{cid}: ledger row for {f} does not list {', '.join(missing)}")
            path = REPO_ROOT / f
            if not path.is_file():
                problems.append(f"{cid}: recording {f} is missing")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                problems.append(f"{cid}: SHA-256 of {f} differs from the ledger")
    found = {p.stem for p in content.rglob("SW_*.uasset")} if content.is_dir() else set()
    for orphan in sorted(found - expected.keys()):
        problems.append(f"{orphan}: sound asset with no cue in cues.json (licence unknown)")
    if require_assets:
        for missing in sorted(expected.keys() - found):
            problems.append(f"{missing}: cue variant has no imported asset")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--require-assets", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    doc = build_audio.load_cues()
    problems = audit(doc, ledger_rows(), CONTENT, args.require_assets)
    assets = sorted(p.stem for p in CONTENT.rglob("SW_*.uasset")) if CONTENT.is_dir() else []
    report = {
        "test": "A19.6 licence",
        "cues": len(doc["cues"]),
        "sound_assets": len(assets),
        "own": sum(1 for c in doc["cues"] if c["licence"] == "own"),
        "cc0": sum(1 for c in doc["cues"] if c["licence"].startswith("cc0:")),
        "problems": problems,
        "pass": not problems,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
