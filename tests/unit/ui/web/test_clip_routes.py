"""The clip editor's routes (``dodaios/ui/web/clip_routes.py``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.nodes import refresh
from dodaios.nodes.clip import export as clip_export
from dodaios.nodes.clip import media
from dodaios.nodes.store import NodeStore
from dodaios.ui.web import clip_routes, nodes_routes

pytest.importorskip("av")

from tests.unit.nodes.clip.conftest import write_sound, write_video  # noqa: E402


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def no_scheduler() -> Any:
        raise RuntimeError("The task scheduler is unavailable")

    monkeypatch.setattr(refresh, "_services", no_scheduler)
    nodes = NodeStore(root=tmp_path / "runs")
    nodes_routes.set_store(nodes)
    yield nodes
    nodes_routes.set_store(None)


@pytest.fixture
def client(store: NodeStore, tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(nodes_routes.router)
    app.include_router(clip_routes.router)
    app.state.outputs_root = tmp_path / "runs"
    return TestClient(app)


@pytest.fixture
def clip(store: NodeStore) -> Any:
    return store.create(type="motion", title="Reel", spec={"scenes": [{"type": "title"}]})


def _upload(client: TestClient, node_id: str, path: Path, name: str | None = None) -> Any:
    return client.post(
        f"/api/nodes/{node_id}/clip/media",
        content=path.read_bytes(),
        headers={"X-File-Name": name or path.name},
    )


def test_an_upload_lands_in_the_library_and_answers_its_entry(
    client: TestClient, clip: Any, store: NodeStore, tmp_path: Path
) -> None:
    source = write_video(tmp_path / "take.mp4")

    answer = _upload(client, clip.id, source, "My%20take.mp4")

    assert answer.status_code == 200
    body = answer.json()
    assert body["entry"]["kind"] == "video" and body["entry"]["name"] == "My take.mp4"
    folder = store.dir_of(clip.id)
    assert folder is not None and media.library_file(folder, body["id"]) is not None
    # The upload only stores the file: the spec is the editor's to change.
    assert "media" not in store.get(clip.id).spec  # type: ignore[union-attr]
    assert not list(media.media_dir(folder).glob(".upload-*"))


def test_an_upload_that_is_not_media_is_refused(
    client: TestClient, clip: Any, tmp_path: Path, store: NodeStore
) -> None:
    junk = tmp_path / "x.mp4"
    junk.write_text("nope", encoding="utf-8")
    answer = _upload(client, clip.id, junk)
    assert answer.status_code == 422 and "read" in answer.json()["detail"]
    other = store.create(type="docs", title="Doc", spec={"markdown": "# A"})
    assert _upload(client, other.id, junk).status_code == 422
    assert _upload(client, "000000000000", junk).status_code == 404


def test_library_files_are_served_with_ranges_and_nothing_else(
    client: TestClient, clip: Any, tmp_path: Path
) -> None:
    body = _upload(client, clip.id, write_video(tmp_path / "take.mp4")).json()
    url = f"/clip-media/{clip.id}/{body['entry']['file']}"

    whole = client.get(url)
    assert whole.status_code == 200 and whole.headers["content-type"] == "video/mp4"
    assert whole.headers["content-security-policy"] == "default-src 'none'"
    assert whole.headers["x-content-type-options"] == "nosniff"
    part = client.get(url, headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == whole.content[10:20]
    assert client.head(url).status_code == 200
    assert client.get(f"/clip-media/{clip.id}/{body['id']}.strip.jpg").status_code == 200
    for bad in ("state.json", "..%2Fstate.json", f"{body['id']}.exe"):
        assert client.get(f"/clip-media/{clip.id}/{bad}").status_code == 404
    assert client.get(f"/clip-media/000000000000/{body['entry']['file']}").status_code == 404


def test_silences_and_transcripts_are_read_from_a_library_file(
    client: TestClient, clip: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_sound(tmp_path / "talk.m4a", [(1.0, 0.5), (1.2, 0.0), (1.0, 0.5)])
    media_id = _upload(client, clip.id, source).json()["id"]

    quiet = client.post(f"/api/nodes/{clip.id}/clip/silences", json={"media": media_id})
    assert quiet.status_code == 200 and len(quiet.json()["silences"]) == 1

    from dodaios.nodes.clip import transcribe

    def fake(path: Path, start: float, end: float | None, language: str | None) -> dict[str, Any]:
        return {"language": "en", "text": "hi", "words": [{"w": "hi", "s": start, "e": start + 1}]}

    monkeypatch.setattr(transcribe, "transcribe_file", fake)
    heard = client.post(f"/api/nodes/{clip.id}/clip/transcribe", json={"media": media_id, "in": 2})
    assert heard.status_code == 200 and heard.json()["words"] == [{"w": "hi", "s": 2.0, "e": 3.0}]
    missing = client.post(f"/api/nodes/{clip.id}/clip/silences", json={"media": "ab" * 12})
    assert missing.status_code == 404


def test_captions_come_from_the_spec_the_editor_sends(
    client: TestClient, clip: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _upload(client, clip.id, write_video(tmp_path / "take.mp4")).json()
    spec = {
        "format": "tall",
        "media": {body["id"]: body["entry"]},
        "scenes": [{"type": "video", "media": body["id"], "seconds": 2}],
    }
    from dodaios.nodes.clip import captions

    def fake(spec: dict[str, Any], node_dir: Path, language: str | None) -> list[dict[str, Any]]:
        return [
            {"w": w, "s": n * 0.3, "e": n * 0.3 + 0.2} for n, w in enumerate("a b c d e".split())
        ]

    monkeypatch.setattr(captions, "timeline_words", fake)
    answer = client.post(f"/api/nodes/{clip.id}/clip/captions", json={"spec": spec})

    assert answer.status_code == 200
    assert [line["text"] for line in answer.json()["items"]] == ["a b c d", "e"]
    refused = client.post(
        f"/api/nodes/{clip.id}/clip/captions",
        json={"spec": {"scenes": [{"type": "video", "media": "ff" * 12}]}},
    )
    assert refused.status_code == 422


def test_an_export_is_started_followed_and_kept_to_its_clip(
    client: TestClient, clip: Any, store: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = store.dir_of(clip.id)
    assert folder is not None
    target = folder / "exports" / "Reel-720p-1.mp4"
    target.parent.mkdir()
    target.write_bytes(b"mp4")
    status = {"state": "done", "progress": 1.0, "file": str(target), "error": ""}
    monkeypatch.setattr(clip_export, "start_export", lambda *a, **k: "job1")
    monkeypatch.setattr(
        clip_export, "export_status", lambda job: dict(status) if job == "job1" else None
    )

    started = client.post(f"/api/nodes/{clip.id}/clip/export", json={"preset": "720p", "fps": 30})
    assert started.status_code == 200 and started.json() == {"job": "job1"}
    state = client.get(f"/api/nodes/{clip.id}/clip/export/job1").json()
    assert state["name"] == "Reel-720p-1.mp4" and state["path"] == "exports/Reel-720p-1.mp4"
    assert state["slug"] == clip.slug
    download = client.get(f"/api/nodes/{clip.id}/clip/export/job1/file")
    assert download.status_code == 200 and download.content == b"mp4"
    assert "attachment" in download.headers["content-disposition"]
    other = store.create(type="motion", title="Other", spec={"scenes": [{"type": "title"}]})
    assert client.get(f"/api/nodes/{other.id}/clip/export/job1").status_code == 404


def test_an_export_with_an_unknown_preset_is_refused(client: TestClient, clip: Any) -> None:
    answer = client.post(f"/api/nodes/{clip.id}/clip/export", json={"preset": "8k"})
    assert answer.status_code == 422


def test_a_duplicated_clip_has_its_own_copy_of_the_library(
    client: TestClient, clip: Any, store: NodeStore, tmp_path: Path
) -> None:
    body = _upload(client, clip.id, write_video(tmp_path / "take.mp4")).json()

    copy = store.duplicate(clip.id)

    folder = store.dir_of(copy.id)
    assert folder is not None and media.media_file(folder, body["entry"]["file"]) is not None


def test_a_clip_page_may_play_its_media_from_this_server(
    client: TestClient, clip: Any, store: NodeStore, tmp_path: Path
) -> None:
    from dodaios.ui.web.outputs_routes import router as outputs_router

    app = client.app
    app.include_router(outputs_router)  # type: ignore[attr-defined]

    page = client.get(f"/api/outputs/{clip.slug}/files/{clip.page_path}/page")

    assert page.status_code == 200
    policy = page.headers["content-security-policy"]
    assert "media-src data: blob: http://testserver/clip-media/;" in policy
    assert "connect-src 'none'" in policy
