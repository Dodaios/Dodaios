"""HTTP API of living pages (``living_pages_routes``)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.artifacts import living_refresh
from dodaios.artifacts.living import LivingPageStore
from dodaios.ui.web import living_pages_routes
from dodaios.ui.web.living_pages_routes import router


@pytest.fixture
def store(tmp_path, monkeypatch: pytest.MonkeyPatch):
    pages = LivingPageStore(root=tmp_path)
    living_pages_routes.set_store(pages)

    async def start(store, page_id):
        return store.set_refresh(page_id, refreshing=True, task_id="task-1")

    async def stop(store, page_id):
        return store.set_refresh(page_id, refreshing=False)

    async def live(page):
        return page.refreshing

    monkeypatch.setattr(living_refresh, "start_refresh", start)
    monkeypatch.setattr(living_refresh, "stop_refresh", stop)
    monkeypatch.setattr(living_refresh, "refresh_live", live)
    yield pages
    living_pages_routes.set_store(None)


@pytest.fixture
def client(store) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_read_stop_and_resume_a_page(client: TestClient, store: LivingPageStore) -> None:
    page = store.create(title="Parcels", track="x", columns=["Parcel"], rows=[{"Parcel": "A"}])
    store.set_refresh(page.id, refreshing=True, task_id="task-1")

    listed = client.get("/api/living-pages").json()["pages"]
    assert [p["id"] for p in listed] == [page.id]
    by_slug = client.get(f"/api/living-pages/by-slug/{page.slug}").json()
    assert by_slug["refreshing"] is True and by_slug["visual_id"] == page.visual_id
    assert by_slug["page_url"].endswith(f"{page.page_path}/page")

    stopped = client.post(f"/api/living-pages/{page.id}/stop").json()
    assert stopped["refreshing"] is False and stopped["rows"] == [{"Parcel": "A"}]

    resumed = client.post(f"/api/living-pages/{page.id}/resume", json={"every_minutes": 45})
    assert resumed.status_code == 200
    assert resumed.json()["refreshing"] is True and resumed.json()["every_minutes"] == 45


def test_unknown_pages_and_bad_cadences_are_refused(client: TestClient) -> None:
    assert client.get("/api/living-pages/0123456789ab").status_code == 404
    assert client.get("/api/living-pages/by-slug/some-run").status_code == 404
    assert client.post("/api/living-pages/0123456789ab/stop").status_code == 404
    assert client.post("/api/living-pages/0123456789ab/resume").status_code == 404
    bad = client.post("/api/living-pages/0123456789ab/resume", json={"every_minutes": 1})
    assert bad.status_code == 422


def test_resume_says_when_the_scheduler_is_down(
    client: TestClient, store: LivingPageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = store.create(title="Jobs", track="x", columns=["Company"])

    async def down(store, page_id):
        raise RuntimeError("The task scheduler is unavailable")

    monkeypatch.setattr(living_refresh, "start_refresh", down)
    assert client.post(f"/api/living-pages/{page.id}/resume").status_code == 503
