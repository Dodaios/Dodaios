"""Sharing an artifact: the staged copy, its download link, and the share sheet bridge.

Nothing here may make an artifact reachable by anyone else: the route only
stages a copy in a private temp folder, the download link serves only files
staged there, and the native bridge accepts only those files.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.ui import native_share
from dodaios.ui.web import artifact_share, outputs_routes
from dodaios.ui.web.outputs_routes import router as outputs_router

SLUG = "mission_019ed2dfd0fab"


@pytest.fixture(autouse=True)
def _private_share_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "share"
    monkeypatch.setattr(artifact_share, "share_folder", lambda: folder)
    return folder


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(outputs_router)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    app.state.outputs_root = outputs
    return app


def _deliverable(app: FastAPI, name: str, content: str) -> str:
    files = Path(app.state.outputs_root) / SLUG / "tasks" / "019edeadbeef" / "artifacts" / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / name).write_text(content, encoding="utf-8")
    return f"tasks/019edeadbeef/artifacts/files/{name}"


# --- names and the staging folder ----------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Umsatz-Dashboard", "Umsatz-Dashboard"),
        ("Report: Q3/Q4 *final*?", "Report Q3 Q4 final"),
        ("  ..hidden.  ", "hidden"),
        ("", "index"),
        ("a" * 300, "a" * 120),
    ],
)
def test_a_title_becomes_a_file_name_every_target_accepts(title: str, expected: str) -> None:
    assert artifact_share.safe_filename(title, "index") == expected


def test_a_staged_copy_carries_the_title_and_stays_in_the_private_folder(
    tmp_path: Path, _private_share_folder: Path
) -> None:
    source = tmp_path / "index.html"
    source.write_text("<h1>Hi</h1>", encoding="utf-8")

    token, staged = artifact_share.stage_copy(source, "Wachstumsreport, 13. November")

    assert staged.name == "Wachstumsreport, 13. November.html"
    assert staged.parent == _private_share_folder / token
    assert staged.read_text(encoding="utf-8") == "<h1>Hi</h1>"
    if os.name != "nt":
        assert (_private_share_folder.stat().st_mode & 0o777) == 0o700
    assert artifact_share.staged_file(token, staged.name) == staged.resolve()


@pytest.mark.parametrize(
    ("token", "name"),
    [
        ("not-a-token", "x.html"),
        ("0" * 32, "../../etc/passwd"),
        ("0" * 32, ".."),
        ("0" * 32, "missing.html"),
    ],
)
def test_the_download_link_serves_nothing_but_staged_files(token: str, name: str) -> None:
    assert artifact_share.staged_file(token, name) is None


def test_old_staged_copies_are_cleared_when_the_next_one_is_staged(
    tmp_path: Path, _private_share_folder: Path
) -> None:
    source = tmp_path / "a.md"
    source.write_text("# A", encoding="utf-8")
    old_token, old = artifact_share.stage_copy(source, "Old")
    stale = old.parent.stat().st_mtime - artifact_share.STAGE_MAX_AGE_S - 10
    os.utime(old.parent, (stale, stale))

    artifact_share.stage_copy(source, "New")

    assert not (_private_share_folder / old_token).exists()


# --- the routes ---------------------------------------------------------------------


def test_sharing_the_file_stages_a_named_copy_and_links_its_download(app: FastAPI) -> None:
    rel = _deliverable(app, "index.html", "<h1>Hi</h1>")
    app.state.native_file_actions = True
    client = TestClient(app)

    reply = client.post(
        f"/api/outputs/{SLUG}/files/{rel}/share",
        json={"format": "file", "title": "Umsatz-Dashboard"},
    )

    assert reply.status_code == 200
    body = reply.json()
    assert body["name"] == "Umsatz-Dashboard.html"
    assert Path(body["path"]).read_text(encoding="utf-8") == "<h1>Hi</h1>"
    download = client.get(body["url"])
    assert download.status_code == 200
    assert download.content == b"<h1>Hi</h1>"
    assert "attachment" in download.headers["content-disposition"]
    assert unquote(body["url"]).endswith("/Umsatz-Dashboard.html")


def test_a_server_without_a_desktop_reports_no_path(app: FastAPI) -> None:
    rel = _deliverable(app, "report.md", "# Hi")
    client = TestClient(app)

    body = client.post(f"/api/outputs/{SLUG}/files/{rel}/share", json={"format": "file"}).json()

    assert body["path"] is None
    assert body["name"] == "report.md"


def test_only_a_page_can_be_shared_as_pdf_or_picture(app: FastAPI) -> None:
    rel = _deliverable(app, "report.md", "# Hi")
    client = TestClient(app)

    reply = client.post(f"/api/outputs/{SLUG}/files/{rel}/share", json={"format": "pdf"})

    assert reply.status_code == 415


def test_a_page_goes_out_as_pdf_drawn_light(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    rel = _deliverable(app, "index.html", "<h1>Hi</h1>")
    seen: dict[str, object] = {}

    def fake_export(source: Path, title: str, fmt: str, theme: str) -> tuple[str, Path]:
        seen.update(source=source.name, title=title, fmt=fmt, theme=theme)
        token, stage = artifact_share.new_stage_dir()
        target = stage / f"{title}.{fmt}"
        target.write_bytes(b"%PDF-1.7")
        return token, target

    monkeypatch.setattr(artifact_share, "export_page", fake_export)
    client = TestClient(app)

    body = client.post(
        f"/api/outputs/{SLUG}/files/{rel}/share",
        json={"format": "pdf", "title": "Report", "theme": "dark"},
    ).json()

    assert seen == {"source": "index.html", "title": "Report", "fmt": "pdf", "theme": "light"}
    assert body["name"] == "Report.pdf"
    assert client.get(body["url"]).content == b"%PDF-1.7"


def test_a_failed_drawing_says_so(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    rel = _deliverable(app, "index.html", "<h1>Hi</h1>")

    def broken(*_args: object) -> tuple[str, Path]:
        raise artifact_share.ShareExportError("no Chromium-family browser is installed")

    monkeypatch.setattr(artifact_share, "export_page", broken)
    client = TestClient(app)

    reply = client.post(f"/api/outputs/{SLUG}/files/{rel}/share", json={"format": "png"})

    assert reply.status_code == 503


def test_a_file_outside_the_deliverables_cannot_be_shared(app: FastAPI) -> None:
    client = TestClient(app)

    reply = client.post(
        f"/api/outputs/{SLUG}/files/../../secret.txt/share", json={"format": "file"}
    )

    assert reply.status_code == 404


def test_capabilities_say_whether_a_page_can_be_drawn(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(outputs_routes, "_PAGE_EXPORT_CACHE", {})
    monkeypatch.setattr(artifact_share, "find_export_browser", lambda: None)
    client = TestClient(app)

    assert client.get("/api/outputs/capabilities").json()["page_export"] is False


# --- the native share sheet bridge ------------------------------------------------------


def test_the_bridge_reads_only_its_own_messages() -> None:
    request = native_share.parse_share_message(
        [
            "jarvis-share",
            {"files": ["/staged/a.pdf"], "rect": {"x": 10, "y": 20, "width": 80, "height": 36}},
        ]
    )
    assert request is not None
    assert request.files == ["/staged/a.pdf"]
    assert request.rect == (10.0, 20.0, 80.0, 36.0)
    assert native_share.parse_share_message(["jarvis-file-drag", {"files": ["/staged/a"]}]) is None
    assert native_share.parse_share_message("not json") is None
    assert native_share.parse_share_message(["jarvis-share", {"files": "/staged/a"}]) is None


def test_the_bridge_shares_nothing_outside_the_staging_folder(tmp_path: Path) -> None:
    staged = tmp_path / "share" / "tok"
    staged.mkdir(parents=True)
    inside = staged / "Report.pdf"
    inside.write_bytes(b"%PDF")
    outside = tmp_path / "secret.txt"
    outside.write_text("x", encoding="utf-8")

    allowed = native_share.allowed_files(
        [str(inside), str(outside), str(staged / ".." / ".." / "secret.txt"), str(staged)],
        tmp_path / "share",
    )

    assert allowed == [str(inside.resolve())]


def test_the_sheet_points_at_the_button_in_view_coordinates() -> None:
    bounds = SimpleNamespace(size=SimpleNamespace(height=800.0))
    unflipped = SimpleNamespace(
        pageZoom=lambda: 1.0, isFlipped=lambda: False, bounds=lambda: bounds
    )
    flipped = SimpleNamespace(pageZoom=lambda: 1.25, isFlipped=lambda: True, bounds=lambda: bounds)

    assert native_share.view_rect(unflipped, (100.0, 20.0, 80.0, 36.0)) == (
        100.0,
        744.0,
        80.0,
        36.0,
    )
    assert native_share.view_rect(flipped, (100.0, 20.0, 80.0, 36.0)) == (125.0, 25.0, 100.0, 45.0)
