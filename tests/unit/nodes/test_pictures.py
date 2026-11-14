"""Pictures from files: a node's ``image`` may name a picture on this computer."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from dodaios.nodes import pictures
from dodaios.nodes.shell import MAX_IMAGE_CHARS, safe_image


def _picture(path: Path, size: tuple[int, int], mode: str = "RGB") -> Path:
    color = (30, 120, 200, 128) if mode == "RGBA" else (30, 120, 200)
    Image.new(mode, size, color).save(path)
    return path


def _decoded(url: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))


def test_only_local_picture_files_are_named(tmp_path: Path) -> None:
    shot = tmp_path / "my shot.PNG"
    assert pictures.picture_path(str(shot)) == shot
    assert pictures.picture_path(shot.as_uri()) == shot
    assert pictures.picture_path("~/a.webp") == Path("~/a.webp").expanduser()
    for value in (
        "data:image/png;base64,AAAA",
        "https://x.org/a.png",
        "a.png",
        str(tmp_path / "a.pdf"),
        3,
    ):
        assert pictures.picture_path(value) is None


def test_a_large_screenshot_is_scaled_into_a_page_picture(tmp_path: Path) -> None:
    shot = _picture(tmp_path / "shot.png", (3024, 1964))
    url = pictures.data_url(shot)
    assert safe_image(url) == url and len(url) <= MAX_IMAGE_CHARS
    image = _decoded(url)
    assert image.format == "JPEG" and max(image.size) <= pictures.MAX_SIDE


def test_a_transparent_logo_stays_a_png(tmp_path: Path) -> None:
    url = pictures.data_url(_picture(tmp_path / "logo.png", (400, 400), "RGBA"))
    assert url.startswith("data:image/png;base64,") and _decoded(url).mode == "RGBA"


def test_a_file_that_is_no_picture_is_refused_with_the_reason(tmp_path: Path) -> None:
    fake = tmp_path / "notes.png"
    fake.write_text("not a picture")
    with pytest.raises(ValueError, match="not a picture"):
        pictures.data_url(fake)
    with pytest.raises(ValueError, match="cannot be read"):
        pictures.data_url(tmp_path / "missing.png")


def test_every_image_in_a_spec_is_embedded_and_the_spec_is_not_changed(tmp_path: Path) -> None:
    shot = _picture(tmp_path / "shot.jpg", (800, 450))
    spec = {
        "slides": [
            {"layout": "image", "image": str(shot), "caption": str(shot)},
            {"layout": "image", "image": "data:image/png;base64,AAAA"},
            {"layout": "image", "image": str(tmp_path / "gone.png")},
        ]
    }
    embedded, problems = pictures.embed_pictures(spec)
    assert embedded["slides"][0]["image"].startswith("data:image/jpeg;base64,")
    # Only the picture field: a caption that happens to be a path stays text.
    assert embedded["slides"][0]["caption"] == str(shot)
    assert embedded["slides"][1]["image"] == "data:image/png;base64,AAAA"
    assert len(problems) == 1 and "gone.png" in problems[0]
    assert spec["slides"][0]["image"] == str(shot)
