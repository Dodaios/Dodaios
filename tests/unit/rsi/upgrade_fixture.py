"""Freeze what an installation has learned, so every later version can be tested against it.

``python -m tests.unit.rsi.upgrade_fixture v2`` builds a small installation on
the made-up world (:mod:`fakeworld`), lets it run three nights from a plainly
bad value, and writes its three files as SQL text plus a manifest of what it
had learned into ``tests/fixtures/rsi/upgrade/v2/``.

Run it ONCE per release that changes a kernel schema, with a new folder name,
and never regenerate an old folder: the point of a frozen state is that it was
written by the code of its time. ``test_upgrade.py`` opens every frozen state
with today's code.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import dodaios
from dodaios.rsi import night as nights
from dodaios.rsi import params
from dodaios.rsi.bench import run
from dodaios.rsi.bench.model import Domain, Source

from . import fakeworld

ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "rsi" / "upgrade"
FILES = ("params.db", "self_changes.db", "bench.db")
#: Enough tasks for the gate to decide (60 select, 36 guard), few enough for a small fixture.
TASKS = 240


def dump(path: Path) -> str:
    """A database as SQL text, with its schema version (``iterdump`` leaves that out)."""
    conn = sqlite3.connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        lines = list(conn.iterdump())
    finally:
        conn.close()
    return "\n".join([*lines, f"PRAGMA user_version = {int(version)};", ""])


def restore(folder: Path, target: Path) -> None:
    """Rebuild the frozen files of ``folder`` in ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        conn = sqlite3.connect(target / name)
        try:
            conn.executescript((folder / f"{name}.sql").read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()


def build(home: Path) -> dict[str, Any]:
    """Three nights on the made-up world; returns the manifest of what was learned."""
    before = run._RUNNERS[Domain.RECALL]
    run._RUNNERS[Domain.RECALL] = fakeworld.scorer
    box = nights.sandbox(
        home,
        plant={fakeworld.SCORE: fakeworld.BLIND},
        tasks=fakeworld.tasks(TASKS),
        worlds={fakeworld.WORLD: object()},
        sources=(Source.MADE,),
    )
    try:
        for _ in range(3):
            box.night.run()
        manifest = {
            "app": dodaios.__version__,
            "learned": params.learned(),
            "stack": [
                {"id": c.id, "target": c.target, "state": c.state.value}
                for c in box.registry.learned()
            ],
            "changes": len(box.registry.store.list(limit=1000)),
            "tasks": box.bench.counts(),
            "series": len(box.bench.series()),
            "nights": len(box.bench.nights()),
        }
    finally:
        box.close()
        run._RUNNERS[Domain.RECALL] = before
    return manifest


def main(name: str) -> None:
    folder = ROOT / name
    if folder.exists():
        raise SystemExit(f"{folder} exists: a frozen state is never regenerated")
    with tempfile.TemporaryDirectory() as raw:
        home = Path(raw)
        manifest = build(home)
        folder.mkdir(parents=True)
        for file in FILES:
            (folder / f"{file}.sql").write_text(dump(home / file), encoding="utf-8", newline="\n")
        text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        (folder / "manifest.json").write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1])
