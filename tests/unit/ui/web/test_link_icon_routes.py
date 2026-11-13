"""The logo the chat draws in front of a web link (``/api/link-icon``)."""

from __future__ import annotations

import asyncio
import io
import os
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from dodaios.ui.web import link_icon_routes as icons


def _picture(size: int, fmt: str = "PNG", colour: tuple[int, int, int, int] = (255, 69, 0, 255)) -> bytes:
    out = io.BytesIO()
    image = Image.new("RGBA", (size, size), colour)
    if fmt == "ICO":
        image.save(out, format="ICO", sizes=[(16, 16), (48, 48)])
    else:
        image.save(out, format=fmt)
    return out.getvalue()


@pytest.fixture
def icon_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(icons, "icon_dir", lambda: tmp_path)
    icons._locks.clear()
    return tmp_path


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(icons.router)
    return TestClient(app)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("reddit.com", "reddit.com"),
        ("WWW.Reddit.com", "reddit.com"),
        ("news.ycombinator.com", "news.ycombinator.com"),
        ("localhost", None),
        ("127.0.0.1", None),
        ("a b.com", None),
        ("evil.com/../x", None),
        ("", None),
    ],
)
def test_only_host_names_are_accepted(raw: str, expected: str | None) -> None:
    assert icons.normalize_host(raw) == expected


def test_the_page_named_icons_come_first_the_nearest_to_64_px_leading() -> None:
    html = """
    <html><head>
      <link rel="apple-touch-icon" href="/apple.png">
      <link rel="icon" href="/tiny.png" sizes="16x16">
      <link rel="icon" href="/vector.svg" type="image/svg+xml">
      <link rel="shortcut icon" href="https://cdn.example.com/i96.png" sizes="96x96">
      <link rel="icon" href="data:image/png;base64,AAAA">
      <link rel="icon" href="http://plain.example.com/x.png">
    </head></html>
    """
    assert icons.icon_candidates("https://example.com/", html) == [
        "https://cdn.example.com/i96.png",
        "https://example.com/tiny.png",
        "https://example.com/favicon.ico",
        "https://example.com/apple.png",
    ]


def test_a_page_without_icons_still_tries_favicon_ico() -> None:
    assert icons.icon_candidates("https://example.com/start", "") == ["https://example.com/favicon.ico"]


def test_an_icon_becomes_a_square_png_scaled_to_fill() -> None:
    png, edge = icons.to_png(_picture(16))
    assert edge == 16
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == "PNG"
        assert image.size == (icons.ICON_SIZE, icons.ICON_SIZE)
        assert image.getpixel((icons.ICON_SIZE // 2, icons.ICON_SIZE // 2))[3] == 255


def test_an_ico_file_gives_its_largest_picture() -> None:
    _png, edge = icons.to_png(_picture(48, "ICO"))
    assert edge == 48


def test_something_that_is_not_a_picture_is_refused() -> None:
    with pytest.raises((ValueError, OSError)):
        icons.to_png(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")


def _site(routes: dict[str, tuple[int, bytes]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes.get(str(request.url), (404, b""))
        return httpx.Response(status, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_the_first_sharp_icon_wins() -> None:
    page = b'<link rel="icon" href="/small.png" sizes="16x16"><link rel="apple-touch-icon" href="/big.png">'
    client = _site({
        "https://example.com/": (200, page),
        "https://example.com/small.png": (200, _picture(16)),
        "https://example.com/favicon.ico": (404, b""),
        "https://example.com/big.png": (200, _picture(180, colour=(0, 0, 255, 255))),
    })
    png = asyncio.run(icons.fetch_icon("example.com", client))
    assert png is not None
    with Image.open(io.BytesIO(png)) as image:
        assert image.convert("RGBA").getpixel((32, 32)) == (0, 0, 255, 255)


def test_a_tiny_icon_is_used_when_there_is_nothing_larger() -> None:
    client = _site({
        "https://example.com/": (403, b"blocked"),
        "https://example.com/favicon.ico": (200, _picture(16, "ICO")),
    })
    assert asyncio.run(icons.fetch_icon("example.com", client)) is not None


def test_a_site_without_a_readable_icon_has_none() -> None:
    client = _site({"https://example.com/": (200, b"<html></html>"), "https://example.com/favicon.ico": (200, b"nope")})
    assert asyncio.run(icons.fetch_icon("example.com", client)) is None


def test_the_route_serves_a_png_and_asks_the_site_once(icon_dir, monkeypatch) -> None:
    calls: list[str] = []

    async def fake_fetch(host: str, client=None) -> bytes:
        calls.append(host)
        return icons.to_png(_picture(32))[0]

    monkeypatch.setattr(icons, "fetch_icon", fake_fetch)
    client = _client()
    first = client.get("/api/link-icon", params={"host": "www.reddit.com"})
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert "max-age" in first.headers["cache-control"]
    second = client.get("/api/link-icon", params={"host": "reddit.com"})
    assert second.content == first.content
    assert calls == ["reddit.com"]
    assert (icon_dir / "reddit.com.png").exists()


def test_a_site_without_icon_is_not_asked_again_for_a_day(icon_dir, monkeypatch) -> None:
    calls: list[str] = []

    async def fake_fetch(host: str, client=None) -> None:
        calls.append(host)
        return None

    monkeypatch.setattr(icons, "fetch_icon", fake_fetch)
    client = _client()
    assert client.get("/api/link-icon", params={"host": "nologo.example.org"}).status_code == 404
    assert client.get("/api/link-icon", params={"host": "nologo.example.org"}).status_code == 404
    # The sub-domain had none, so its parent was asked once too.
    assert calls == ["nologo.example.org", "example.org"]
    marker = icon_dir / "nologo.example.org.none"
    old = time.time() - icons.KEEP_MISSING_S - 10
    os.utime(marker, (old, old))
    client.get("/api/link-icon", params={"host": "nologo.example.org"})
    assert calls.count("nologo.example.org") == 2


def test_a_host_that_is_not_a_web_site_gets_no_fetch(icon_dir, monkeypatch) -> None:
    async def never(host: str, client=None) -> bytes:
        raise AssertionError("must not fetch")

    monkeypatch.setattr(icons, "fetch_icon", never)
    client = _client()
    for host in ("localhost", "127.0.0.1", "169.254.169.254", "intranet"):
        assert client.get("/api/link-icon", params={"host": host}).status_code == 404


def test_the_fetch_refuses_private_addresses() -> None:
    from dodaios.core.http_guard import BlockedDestination, public_only_async

    async def run() -> None:
        async with httpx.AsyncClient(**public_only_async()) as client:
            await client.get("https://127.0.0.1/favicon.ico")

    with pytest.raises(BlockedDestination):
        asyncio.run(run())


def test_a_dark_mark_on_a_clear_ground_gets_a_light_tile() -> None:
    # A black disc on a transparent square, like GitHub's cat: invisible on the dark theme.
    mark = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(mark).ellipse((16, 16, 48, 48), fill=(20, 20, 20, 255))
    out = io.BytesIO()
    mark.save(out, format="PNG")
    png, _edge = icons.to_png(out.getvalue())
    with Image.open(io.BytesIO(png)) as image:
        corner_inside = image.convert("RGBA").getpixel((icons.ICON_SIZE // 2, 4))
    assert corner_inside[3] == 255 and corner_inside[0] > 200


def test_a_coloured_icon_keeps_its_own_ground() -> None:
    png, _edge = icons.to_png(_picture(32))
    with Image.open(io.BytesIO(png)) as image:
        assert image.convert("RGBA").getpixel((icons.ICON_SIZE // 2, 2)) == (255, 69, 0, 255)
