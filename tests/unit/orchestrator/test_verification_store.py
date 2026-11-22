"""``verification.db``: runs can be updated, their steps can only be added."""

from __future__ import annotations

import sqlite3

import pytest

from dodaios.orchestrator.verification import store as vstore
from dodaios.orchestrator.verification.store import VerificationStore


@pytest.fixture
def store():
    made = VerificationStore(":memory:")
    try:
        yield made
    finally:
        made.close()


def test_a_run_is_recorded_once(store):
    assert store.start_run("job_1", "thread-1", repo_id="github.com/acme/notes", started_ms=10)
    assert not store.start_run("job_1", "thread-1", repo_id="other", started_ms=99)
    run = store.get("job_1")
    assert run["state"] == vstore.RUNNING
    assert run["repo_id"] == "github.com/acme/notes"
    assert run["started_ms"] == 10


def test_domains_and_flags_are_stored_in_their_column_types(store):
    store.start_run(
        "job_1", "thread-1", domains_json=["backend", "refactoring"], isolated=True,
        brief_text="x" * 30_000,
    )
    run = store.get("job_1")
    assert run["domains_json"] == '["backend", "refactoring"]'
    assert run["isolated"] == 1
    assert len(run["brief_text"]) == 20_000


def test_only_known_fields_can_be_written(store):
    with pytest.raises(ValueError, match="unknown run fields"):
        store.start_run("job_1", "thread-1", verdict="verified")
    store.start_run("job_1", "thread-1")
    with pytest.raises(ValueError, match="cannot be set"):
        store.update_run("job_1", repo_id="rewritten")
    with pytest.raises(ValueError, match="unknown run state"):
        store.update_run("job_1", state="verified")


def test_updating_a_run_that_does_not_exist_says_so(store):
    assert store.update_run("nope", state=vstore.ENDED) is False
    assert store.update_run("nope") is False


def test_open_runs_are_the_ones_that_have_not_ended(store):
    store.start_run("job_old", "thread-1", started_ms=1)
    store.start_run("job_new", "thread-2", started_ms=2)
    store.update_run("job_old", state=vstore.ENDED, turn_status="done", ended_ms=5)
    assert [r["run_id"] for r in store.open_runs()] == ["job_new"]
    assert [r["run_id"] for r in store.runs()] == ["job_new", "job_old"]
    assert [r["run_id"] for r in store.runs(since_ms=2)] == ["job_new"]


def test_a_step_is_written_once_and_read_back_with_its_detail(store):
    store.start_run("job_1", "thread-1")
    assert store.add_step("job_1", 0, "bound", detail={"domains": ["backend"]}, ts_ms=1)
    assert not store.add_step("job_1", 0, "bound", detail={"domains": ["other"]}, ts_ms=2)
    assert store.add_step("job_1", 0, "turn_finished", status="done", ts_ms=3)
    steps = store.steps("job_1")
    assert [s["step"] for s in steps] == ["bound", "turn_finished"]
    assert steps[0]["detail"] == {"domains": ["backend"]}


def test_steps_cannot_be_changed_or_removed(store):
    store.start_run("job_1", "thread-1")
    store.add_step("job_1", 0, "bound")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("UPDATE steps SET status = 'done' WHERE run_id = 'job_1'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("DELETE FROM steps WHERE run_id = 'job_1'")
    assert len(store.steps("job_1")) == 1


def test_the_file_is_created_with_its_folder(tmp_path):
    path = tmp_path / "nested" / "verification.db"
    made = VerificationStore(path)
    try:
        made.start_run("job_1", "thread-1")
    finally:
        made.close()
    assert path.is_file()
