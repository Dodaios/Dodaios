"""TaskStore: the person's own tasks, stored, ordered and changed deterministically."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.today import store as store_mod
from jarvis.today.store import (
    NOTES_MAX_CHARS,
    PRIORITIES,
    STATUSES,
    TITLE_MAX_CHARS,
    VIEWS,
    InvalidTask,
    TaskNotFound,
    TaskStore,
    today_db_path,
)

DAY = date(2026, 10, 14)


class Clock:
    """A clock that moves one second per reading, so every write has its own time."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 14, 7, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "today" / "tasks.db", clock=Clock(), today=lambda: DAY)


def titles(tasks) -> list[str]:
    return [t.title for t in tasks]


# -- storing -------------------------------------------------------------------


def test_a_task_is_stored_with_its_fields_and_read_back(store: TaskStore) -> None:
    task = store.add("  Pay the   invoice ", notes=" before noon ", priority="high", due_date=DAY)
    assert task.title == "Pay the invoice"
    assert task.notes == "before noon"
    assert task.priority == "high"
    assert task.due_date == "2026-10-14"
    assert task.status == "open" and task.completed_at is None
    assert task.created_at == task.updated_at
    assert store.get(task.id) == task
    assert re.fullmatch(r"[0-9a-f]{32}", task.id)


def test_defaults_are_normal_priority_no_date_no_notes(store: TaskStore) -> None:
    task = store.add("Call back")
    assert (task.priority, task.due_date, task.notes) == ("normal", None, None)


def test_the_store_survives_a_new_instance_on_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "tasks.db"
    first = TaskStore(path).add("Persisted")
    assert TaskStore(path).get(first.id).title == "Persisted"


def test_nothing_is_created_before_first_use(tmp_path: Path) -> None:
    path = tmp_path / "today" / "tasks.db"
    TaskStore(path)
    assert not path.exists()


def test_the_file_lives_in_its_own_folder_of_the_data_directory(tmp_path: Path) -> None:
    assert today_db_path(tmp_path) == tmp_path / "today" / "tasks.db"


def test_a_due_date_may_be_given_as_text(store: TaskStore) -> None:
    assert store.add("Text date", due_date="2026-10-20").due_date == "2026-10-20"


# -- ordering ------------------------------------------------------------------


@pytest.fixture
def mixed(store: TaskStore) -> TaskStore:
    store.add("rest normal")
    store.add("rest low later", priority="low", due_date=DAY + timedelta(days=3))
    store.add("high undated", priority="high")
    store.add("high next week", priority="high", due_date=DAY + timedelta(days=7))
    store.add("due today low", priority="low", due_date=DAY)
    store.add("due today high", priority="high", due_date=DAY)
    store.add("overdue two days", due_date=DAY - timedelta(days=2))
    store.add("overdue yesterday high", priority="high", due_date=DAY - timedelta(days=1))
    store.add("rest normal tomorrow", due_date=DAY + timedelta(days=1))
    return store


def test_today_shows_overdue_then_due_today_then_high_priority(mixed: TaskStore) -> None:
    assert titles(mixed.list_tasks("today")) == [
        "overdue yesterday high",
        "overdue two days",
        "due today high",
        "due today low",
        "high next week",
        "high undated",
    ]


def test_open_adds_every_other_open_task_after_the_today_ones(mixed: TaskStore) -> None:
    assert titles(mixed.list_tasks("open")) == [
        "overdue yesterday high",
        "overdue two days",
        "due today high",
        "due today low",
        "high next week",
        "high undated",
        "rest normal tomorrow",
        "rest normal",
        "rest low later",
    ]


def test_the_day_decides_what_is_overdue(mixed: TaskStore) -> None:
    later = mixed.list_tasks("today", on=DAY + timedelta(days=1))
    assert "rest normal tomorrow" in titles(later)  # due "today" on that day
    assert titles(later)[:3] == ["overdue yesterday high", "due today high", "overdue two days"]


def test_same_bucket_and_priority_keeps_the_older_task_first(store: TaskStore) -> None:
    store.add("first")
    store.add("second")
    assert titles(store.list_tasks("open")) == ["first", "second"]


def test_done_lists_completed_tasks_newest_first_and_today_hides_them(store: TaskStore) -> None:
    a = store.add("a", priority="high")
    b = store.add("b", priority="high")
    store.complete(a.id)
    store.complete(b.id)
    assert titles(store.list_tasks("done")) == ["b", "a"]
    assert store.list_tasks("today") == []
    assert titles(store.list_tasks("all")) == ["b", "a"]


def test_all_lists_open_before_done(store: TaskStore) -> None:
    done = store.add("done one")
    store.complete(done.id)
    store.add("open one")
    assert titles(store.list_tasks("all")) == ["open one", "done one"]


def test_an_unknown_view_is_refused(store: TaskStore) -> None:
    with pytest.raises(InvalidTask, match="view"):
        store.list_tasks("tomorrow")


# -- changing ------------------------------------------------------------------


def test_update_changes_only_the_given_fields(store: TaskStore) -> None:
    task = store.add("Draft", notes="n", priority="low", due_date=DAY)
    changed = store.update(task.id, title="Final", priority="high")
    assert (changed.title, changed.priority) == ("Final", "high")
    assert (changed.notes, changed.due_date) == ("n", "2026-10-14")
    assert changed.updated_at > task.updated_at
    assert changed.created_at == task.created_at


def test_update_can_clear_notes_and_due_date(store: TaskStore) -> None:
    task = store.add("Draft", notes="n", due_date=DAY)
    cleared = store.update(task.id, notes=None, due_date=None)
    assert (cleared.notes, cleared.due_date) == (None, None)


def test_update_without_fields_changes_nothing(store: TaskStore) -> None:
    task = store.add("Same")
    assert store.update(task.id) == task


def test_complete_and_reopen(store: TaskStore) -> None:
    task = store.add("Toggle")
    done = store.complete(task.id)
    assert done.status == "done" and done.completed_at is not None
    again = store.complete(task.id)
    assert again.completed_at == done.completed_at  # the first completion stays
    reopened = store.reopen(task.id)
    assert reopened.status == "open" and reopened.completed_at is None
    assert store.reopen(task.id) == reopened  # reopening an open task changes nothing


def test_delete_removes_the_task(store: TaskStore) -> None:
    task = store.add("Gone")
    keep = store.add("Kept")
    store.delete(task.id)
    with pytest.raises(TaskNotFound):
        store.get(task.id)
    assert titles(store.list_tasks("all")) == ["Kept"]
    assert store.get(keep.id).title == "Kept"


# -- errors ----------------------------------------------------------------------


@pytest.mark.parametrize("action", ["get", "complete", "reopen", "delete", "update"])
def test_an_unknown_id_is_reported(store: TaskStore, action: str) -> None:
    with pytest.raises(TaskNotFound):
        getattr(store, action)("0" * 32)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "   "}, "title"),
        ({"title": "x" * (TITLE_MAX_CHARS + 1)}, "title"),
        ({"title": 5}, "title"),
        ({"title": "ok", "notes": "x" * (NOTES_MAX_CHARS + 1)}, "notes"),
        ({"title": "ok", "priority": "urgent"}, "priority"),
        ({"title": "ok", "priority": "High"}, "priority"),
        ({"title": "ok", "due_date": "14.10.2026"}, "due_date"),
        ({"title": "ok", "due_date": "2026-02-30"}, "due_date"),
        ({"title": "ok", "due_date": datetime(2026, 10, 14, 9, 0)}, "due_date"),
    ],
)
def test_invalid_values_are_refused_and_nothing_is_stored(
    store: TaskStore, kwargs: dict, field: str
) -> None:
    title = kwargs.pop("title")
    with pytest.raises(InvalidTask, match=field):
        store.add(title, **kwargs)
    assert store.list_tasks("all") == []


def test_an_invalid_update_changes_nothing(store: TaskStore) -> None:
    task = store.add("Stable", priority="low")
    with pytest.raises(InvalidTask):
        store.update(task.id, title="Renamed", priority="urgent")
    assert store.get(task.id) == task


def test_the_table_itself_refuses_values_outside_the_vocabulary(store: TaskStore) -> None:
    store.add("seed")  # creates the file
    conn = sqlite3.connect(store.db_path)
    try:
        for column, value in (("priority", "urgent"), ("status", "archived"), ("due_date", "soon")):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    f"INSERT INTO tasks (id, title, {column}, created_at, updated_at) "  # noqa: S608 — fixed column names
                    "VALUES ('x', 't', ?, 'now', 'now')",
                    (value,),
                )
        with pytest.raises(sqlite3.IntegrityError):  # done without a completion time
            conn.execute(
                "INSERT INTO tasks (id, title, status, created_at, updated_at) "
                "VALUES ('y', 't', 'done', 'now', 'now')"
            )
    finally:
        conn.close()


# -- one vocabulary in every layer -------------------------------------------------


def test_python_sql_and_rest_share_one_vocabulary() -> None:
    from typing import get_args

    from jarvis.ui.web import today_routes

    assert set(get_args(today_routes.Priority)) == set(PRIORITIES)
    assert set(get_args(today_routes.Status)) == set(STATUSES)
    assert set(get_args(today_routes.View)) == set(VIEWS)
    for value in (*PRIORITIES, *STATUSES):
        assert f"'{value}'" in store_mod._SCHEMA
    assert PRIORITIES == ("high", "normal", "low")
