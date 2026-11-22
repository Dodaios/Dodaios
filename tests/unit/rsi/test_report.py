"""The run report: cells from the record, read-only."""

from __future__ import annotations

import json
from pathlib import Path

from dodaios.orchestrator.verification.store import ENDED, VerificationStore
from dodaios.rsi import report


def _record(path: Path) -> None:
    store = VerificationStore(path)
    try:
        for index, status in enumerate(["done", "done", "error"]):
            run_id = f"job_{index}"
            store.start_run(
                run_id, f"thread-{index}", primary_domain="backend",
                model_requested="claude-fable-5-2", started_ms=1_000 + index,
            )
            store.update_run(
                run_id, state=ENDED, turn_status=status, runner="claude-cli",
                harness_line="2.1", model_resolved="claude-fable-5-2", wall_ms=120_000,
                tokens_out=400, ended_ms=9_000,
            )
        store.start_run("job_open", "thread-9", primary_domain="frontend", started_ms=2_000)
        store.update_run("job_open", runner="codex-cli", harness_line="0.154")
    finally:
        store.close()


def test_runs_are_grouped_into_cells_largest_first(tmp_path: Path):
    db = tmp_path / "verification.db"
    _record(db)
    rows = report.cells(report.load_runs(db))
    assert [(c["domain"], c["model"], c["harness"], c["runs"]) for c in rows] == [
        ("backend", "claude-fable-5-2", "claude-cli 2.1", 3),
        ("frontend", "(default)", "codex-cli 0.154", 1),
    ]
    backend = rows[0]
    assert (backend["done"], backend["error"], backend["open"]) == (2, 1, 0)
    assert backend["mean_minutes"] == 2.0
    assert rows[1]["open"] == 1


def test_since_leaves_older_runs_out(tmp_path: Path):
    db = tmp_path / "verification.db"
    _record(db)
    assert len(report.load_runs(db, since_ms=1_002)) == 2


def test_no_record_yet_says_how_to_start_one(tmp_path: Path, capsys):
    assert report.load_runs(tmp_path / "missing.db") == []
    assert report.main(["--db", str(tmp_path / "missing.db")]) == 0
    assert "[rsi] enabled" in capsys.readouterr().out


def test_the_table_and_the_json_name_every_cell(tmp_path: Path, capsys):
    db = tmp_path / "verification.db"
    _record(db)
    assert report.main(["--db", str(db), "--since-days", "100000"]) == 0
    table = capsys.readouterr().out
    assert "claude-cli 2.1" in table
    assert "4 run(s) in 2 cell(s)." in table
    assert report.main(["--db", str(db), "--since-days", "100000", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["runs"] == 4
    assert len(data["cells"]) == 2


def test_the_report_cannot_write_the_record(tmp_path: Path):
    import sqlite3

    import pytest

    db = tmp_path / "verification.db"
    _record(db)
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE runs SET state = 'ended'")
    finally:
        conn.close()
