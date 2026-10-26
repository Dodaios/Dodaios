"""The picture behind the tiling layout: desktop wallpaper by default, custom upload on top."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from dodaios.ui import wallpaper
from dodaios.ui.web.wallpaper_routes import router


def _png(color: str = "red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(wallpaper, "custom_dir", lambda: tmp_path / "data")
    desktop = tmp_path / "desktop.jpg"
    desktop.write_bytes(b"\xff\xd8\xff desktop")
    monkeypatch.setattr(wallpaper, "desktop_wallpaper", lambda: desktop)
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_defaults_to_the_desktop_wallpaper(client: TestClient) -> None:
    info = client.get("/api/wallpaper/info").json()
    assert info["source"] == "desktop"
    assert info["version"]
    response = client.get("/api/wallpaper")
    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff desktop"
    assert response.headers["content-type"] == "image/jpeg"


def test_custom_upload_wins_until_reset(client: TestClient) -> None:
    uploaded = client.post("/api/wallpaper", files={"file": ("bg.png", _png(), "image/png")})
    assert uploaded.status_code == 200
    assert uploaded.json()["source"] == "custom"
    assert client.get("/api/wallpaper").content == _png()

    # A second upload in another format replaces the first; one picture remains.
    jpeg = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(jpeg, format="JPEG")
    client.post("/api/wallpaper", files={"file": ("bg.jpg", jpeg.getvalue(), "image/jpeg")})
    stored = list((wallpaper.custom_dir()).glob(f"{wallpaper.CUSTOM_STEM}.*"))
    assert [path.suffix for path in stored] == [".jpg"]

    reset = client.delete("/api/wallpaper").json()
    assert reset == {"ok": True, "removed": True, "source": "desktop", "version": reset["version"]}
    assert client.get("/api/wallpaper").content == b"\xff\xd8\xff desktop"


def test_rejects_what_is_not_an_image(client: TestClient) -> None:
    junk = {"file": ("x.png", b"not an image", "image/png")}
    assert client.post("/api/wallpaper", files=junk).status_code == 400
    empty = {"file": ("x.png", b"", "image/png")}
    assert client.post("/api/wallpaper", files=empty).status_code == 400
    assert wallpaper.find_custom() is None


def test_no_wallpaper_anywhere_is_an_honest_404(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(wallpaper, "desktop_wallpaper", lambda: None)
    assert client.get("/api/wallpaper/info").json() == {"source": "none", "version": ""}
    assert client.get("/api/wallpaper").status_code == 404


def test_linux_reads_the_gnome_picture_uri(tmp_path: Path, monkeypatch) -> None:
    picture = tmp_path / "my wall.png"
    picture.write_bytes(_png())
    uri = picture.as_uri()
    answers = {"picture-uri-dark": "''", "picture-uri": f"'{uri}'"}
    monkeypatch.setattr(wallpaper, "_run", lambda argv: answers[argv[-1]])
    found = wallpaper._linux_wallpaper()
    assert found is not None
    assert found.name == "my wall.png"
