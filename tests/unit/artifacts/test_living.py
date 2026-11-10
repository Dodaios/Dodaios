"""Living pages: the store, the rendered page and the refresh routine."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.artifacts import living_refresh
from dodaios.artifacts.living import (
    MAX_EVERY_MINUTES,
    MIN_EVERY_MINUTES,
    SLUG_INFIX,
    LivingPageError,
    LivingPageStore,
    clamp_every,
    normalize_columns,
    normalize_rows,
    render_html,
)
from dodaios.missions.standalone_run import read_marker
from dodaios.tasks.schema import TaskSpec


def _store(tmp_path: Path) -> LivingPageStore:
    return LivingPageStore(root=tmp_path)


def _parcels(store: LivingPageStore):
    return store.create(
        title="My parcels",
        track="Parcels on their way to me, from shipping mails in Gmail.",
        columns=["Parcel", "Status"],
        rows=[
            {"Parcel": "Shoes", "Status": "In transit", "link": "https://track.example/1"},
            {"parcel": "Books", "status": "Delivered"},
        ],
        every_minutes=60,
        now=1_700_000_000,
    )


def test_create_writes_a_listed_page_and_its_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    page = _parcels(store)

    run_dir = tmp_path / page.slug
    assert SLUG_INFIX in page.slug and page.slug.endswith(page.id)
    marker = read_marker(run_dir)
    assert marker is not None and marker["kind"] == "living_page"
    assert marker["title"] == "My parcels"
    # The page is a deliverable under tasks/<id>/artifacts/files; the state is not.
    assert page.page_path.startswith("tasks/living/artifacts/files/")
    html = (run_dir / page.page_path).read_text(encoding="utf-8")
    assert "<title>My parcels</title>" in html
    state = json.loads((run_dir / "living-page.json").read_text(encoding="utf-8"))
    assert state["rows"][1] == {"Parcel": "Books", "Status": "Delivered"}
    assert page.visual_id == f"{page.slug}::{page.page_path}"


def test_rendered_page_is_self_contained_and_says_when_it_was_updated(tmp_path: Path) -> None:
    page = _parcels(_store(tmp_path))
    html = render_html(page)
    assert 'data-updated="1700000000"' in html
    assert "Intl.RelativeTimeFormat" in html
    # A row link opens outside the sandboxed frame; no network code of its own.
    assert 'href="https://track.example/1"' in html
    assert "fetch(" not in html and "XMLHttpRequest" not in html
    assert "localStorage" not in html


def test_rendering_escapes_what_the_sources_said(tmp_path: Path) -> None:
    store = _store(tmp_path)
    page = store.create(
        title="<script>x</script>",
        track="anything",
        columns=["Item"],
        rows=[{"Item": "<img src=x onerror=alert(1)>", "link": "javascript:alert(1)"}],
    )
    html = render_html(page)
    assert "<script>x</script>" not in html.split("<style>")[0]
    assert "<img src=x" not in html
    assert "javascript:alert" not in html


def test_update_replaces_rows_and_keeps_them_on_a_note(tmp_path: Path) -> None:
    store = _store(tmp_path)
    page = _parcels(store)
    fresh = store.update_rows(page.id, rows=[{"Parcel": "Lamp", "Status": "Ordered"}], now=2e9)
    assert [r["Parcel"] for r in fresh.rows] == ["Lamp"]
    assert fresh.updated_at == 2e9
    noted = store.update_rows(page.id, rows=None, note="Gmail is not connected", now=3e9)
    assert [r["Parcel"] for r in noted.rows] == ["Lamp"]
    assert noted.note == "Gmail is not connected"
    assert "Gmail is not connected" in (tmp_path / page.slug / page.page_path).read_text(
        encoding="utf-8"
    )


def test_lookup_by_id_slug_and_listing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _parcels(store)
    second = store.create(title="Jobs", track="applications", columns=["Company"], now=1.8e9)
    assert store.get(first.id) == first
    assert store.by_slug(second.slug) == second
    assert store.by_slug("20260101T000000__generated-image__abc") is None
    assert store.get("../../etc") is None
    assert [p.id for p in store.list_pages()] == [second.id, first.id]


def test_create_refuses_what_it_cannot_build(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(LivingPageError):
        store.create(title="", track="x", columns=["A"])
    with pytest.raises(LivingPageError):
        store.create(title="T", track="", columns=["A"])
    with pytest.raises(LivingPageError):
        store.create(title="T", track="x")
    with pytest.raises(LivingPageError):
        store.update_rows("0123456789ab", rows=[])


def test_normalizing_columns_rows_and_cadence() -> None:
    assert normalize_columns(None, [{"Name": 1, "link": "x", "Price": 2}]) == ("Name", "Price")
    assert len(normalize_columns([f"c{i}" for i in range(20)])) == 8
    rows = normalize_rows([["A", "1"], {"name": "B"}, {}, "junk"], ("Name", "Price"))
    assert rows == ({"Name": "A", "Price": "1"}, {"Name": "B"})
    with pytest.raises(LivingPageError):
        normalize_rows("not a list", ("Name",))
    assert clamp_every(1) == MIN_EVERY_MINUTES
    assert clamp_every(10**9) == MAX_EVERY_MINUTES
    assert clamp_every("x") == 180


# ------------------------------------------------------------------ refresh


class _TaskStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def insert(self, spec: TaskSpec) -> str:
        task_id = f"task-{len(self.rows) + 1}"
        self.rows.append(
            {"id": task_id, "state": "scheduled", "spec_json": spec.model_dump_json(), "spec": spec}
        )
        return task_id

    async def list(self, state_filter=None, *, limit: int = 100) -> list[dict]:
        return list(self.rows)

    async def get(self, task_id: str) -> dict | None:
        return next((r for r in self.rows if r["id"] == task_id), None)

    async def get_spec(self, task_id: str) -> TaskSpec | None:
        row = await self.get(task_id)
        return row["spec"] if row else None

    async def delete(self, task_id: str) -> bool:
        self.rows = [r for r in self.rows if r["id"] != task_id]
        return True


class _Scheduler:
    def __init__(self, store: _TaskStore) -> None:
        self.store = store

    async def schedule(self, spec: TaskSpec) -> str:
        return await self.store.insert(spec)

    async def cancel_task(self, task_id: str, reason: str = "") -> bool:
        row = await self.store.get(task_id)
        if row:
            row["state"] = "cancelled"
        return True


class _Roster:
    async def get(self, agent_id: str):
        return SimpleNamespace(
            agent_id=agent_id,
            name="Dodaios",
            title="",
            description="",
            focus=(),
            provider="claude-cli",
            model="m",
            effort="low",
            account_id="",
        )


def _runtime(task_store: _TaskStore) -> SimpleNamespace:
    scheduler = _Scheduler(task_store)
    return SimpleNamespace(roster=_Roster(), task_services=lambda: (task_store, scheduler))


async def test_refresh_is_one_tagged_lead_routine_that_can_stop_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    monkeypatch.setattr(living_refresh, "_runtime", lambda: _runtime(tasks))
    store = _store(tmp_path)
    page = _parcels(store)

    live = await living_refresh.start_refresh(store, page.id)
    assert live.refreshing and live.task_id == "task-1"
    spec = tasks.rows[0]["spec"]
    assert living_refresh.tag_for(page.id) in spec.tags
    assert "agent:jarvis" in spec.tags
    assert spec.trigger.interval_seconds == 60 * 60
    assert "living_page" in spec.action.prompt and page.id in spec.action.prompt
    assert "do not send" in spec.action.prompt.lower()
    assert await living_refresh.refresh_live(live)

    # Resuming replaces the routine instead of adding a second one.
    again = await living_refresh.start_refresh(store, page.id)
    alive = [r for r in tasks.rows if r["state"] != "cancelled"]
    assert len(alive) == 1 and again.task_id == alive[0]["id"]

    stopped = await living_refresh.stop_refresh(store, page.id)
    assert not stopped.refreshing and stopped.task_id == ""
    assert not [r for r in tasks.rows if r["state"] != "cancelled"]
    assert stopped.rows == page.rows


async def test_a_routine_deleted_elsewhere_reads_as_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    monkeypatch.setattr(living_refresh, "_runtime", lambda: _runtime(tasks))
    store = _store(tmp_path)
    page = await living_refresh.start_refresh(store, _parcels(store).id)
    tasks.rows[0]["state"] = "paused"
    assert not await living_refresh.refresh_live(page)
    assert (await living_refresh.page_state(store, page))["refreshing"] is False


async def test_stop_works_while_the_society_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(living_refresh, "_runtime", lambda: None)
    store = _store(tmp_path)
    page = _parcels(store)
    with pytest.raises(RuntimeError):
        await living_refresh.start_refresh(store, page.id)
    assert not (await living_refresh.stop_refresh(store, page.id)).refreshing
