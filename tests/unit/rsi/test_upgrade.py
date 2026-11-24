"""Everything learned survives an app update: every frozen state opens with today's code.

Each folder under ``tests/fixtures/rsi/upgrade/`` is the state of an
installation as an earlier version of the app left it (written by
``upgrade_fixture.py``, never regenerated). Today's code must open each one,
apply what it had learned, keep its history readable, and carry on from there.
A change to a kernel schema that breaks this fails here before it ships.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import dodaios
from dodaios.rsi import night as nights
from dodaios.rsi import params
from dodaios.rsi.bench import run
from dodaios.rsi.bench.model import Domain, Source, Split
from dodaios.rsi.bench.store import SCHEMA as BENCH_SCHEMA
from dodaios.rsi.bench.store import BenchStore
from dodaios.rsi.params.live import SCHEMA as PARAMS_SCHEMA
from dodaios.self_change import SelfChangeRegistry, State, Surface

from . import fakeworld, upgrade_fixture

STATES = sorted(p.name for p in upgrade_fixture.ROOT.iterdir() if p.is_dir())


def _manifest(name: str) -> dict[str, Any]:
    return json.loads((upgrade_fixture.ROOT / name / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(params=STATES)
def home(request, tmp_path: Path, monkeypatch):
    """One frozen state, rebuilt in a scratch folder, with the made-up world running."""
    upgrade_fixture.restore(upgrade_fixture.ROOT / request.param, tmp_path)
    monkeypatch.setitem(run._RUNNERS, Domain.RECALL, fakeworld.scorer)
    yield tmp_path, _manifest(request.param)
    params.install(None)


def test_there_is_a_frozen_state_to_test_against() -> None:
    assert "v1" in STATES


def test_what_was_learned_still_applies(home) -> None:
    path, manifest = home
    store = params.install(path)
    try:
        assert params.learned() == manifest["learned"]
        for name, value in manifest["learned"].items():
            assert params.get(name) == value
        assert all(entry.status in ("live", "restale") for entry in store.entries())
    finally:
        params.release(store)


def test_the_record_of_every_change_is_still_readable(home) -> None:
    path, manifest = home
    registry = SelfChangeRegistry(path)
    try:
        assert len(registry.store.list(limit=1000)) == manifest["changes"]
        stack = [
            {"id": c.id, "target": c.target, "state": c.state.value} for c in registry.learned()
        ]
        assert stack == manifest["stack"]
        for row in registry.stack():
            steps = [e["step"] for e in row["evidence"]]
            assert steps[0] == "admit" and row["since_ms"] > 0
            assert row["evidence"][0]["evidence"]["target"]["n"] > 0
            detail = registry.detail(row["id"])
            assert detail["before"] is not None and detail["after"] and detail["history"]
    finally:
        registry.close()


def test_the_benchmark_keeps_its_tasks_their_splits_and_its_history(home) -> None:
    path, manifest = home
    bench = BenchStore(path / "bench.db")
    try:
        assert not bench.readonly and bench.counts() == manifest["tasks"]
        made = {t.id: t.split for t in fakeworld.tasks(upgrade_fixture.TASKS)}
        for split in Split:
            for task in bench.tasks(Domain.RECALL, splits=(split,)):
                assert made[task.id] is split, "an update moved a task into another split"
        assert len(bench.series()) == manifest["series"]
        assert len(bench.nights()) == manifest["nights"]
        assert all(point["app"] == manifest["app"] for point in bench.series())
    finally:
        bench.close()
    raw = sqlite3.connect(path / "bench.db")
    assert raw.execute("PRAGMA user_version").fetchone()[0] == BENCH_SCHEMA.version
    raw.close()
    raw = sqlite3.connect(path / "params.db")
    assert raw.execute("PRAGMA user_version").fetchone()[0] == PARAMS_SCHEMA.version
    raw.close()


def test_the_loop_carries_on_from_the_frozen_state(home, monkeypatch) -> None:
    path, manifest = home
    store = params.install(path)
    registry = SelfChangeRegistry(path)
    registry.register_handler(Surface.PARAMETER, store)
    bench = BenchStore(path / "bench.db")
    night = nights.Night(
        registry, bench, lambda: {fakeworld.WORLD: object()}, sources=(Source.MADE,)
    )
    monkeypatch.setattr(dodaios, "__version__", "999.0.0")  # the app was updated since
    try:
        report = night.run()
        assert report.updated_from == manifest["app"] and report.app == "999.0.0"
        # After an update everything learned is checked again, and what still pays stays.
        checked = {row["target"]: row["outcome"] for row in report.settled}
        assert set(checked) == {entry["target"] for entry in manifest["stack"]}
        assert set(checked.values()) == {"kept"}
        assert params.learned().items() >= manifest["learned"].items()
        assert all(c.state in (State.LIVE, State.TRIAL) for c in registry.learned())
        latest = bench.series()[-1]
        assert latest["app"] == "999.0.0" and len(bench.nights()) == manifest["nights"] + 1
        # It can still be taken back to the exact value from before it was learned.
        first = registry.learned()[0]
        registry.rollback(first.id)
        assert params.get(first.target) == fakeworld.BLIND
    finally:
        registry.close()
        bench.close()
        params.release(store)


def test_a_frozen_state_is_never_regenerated(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="never regenerated"):
        upgrade_fixture.main("v1")
