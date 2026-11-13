"""The small logo the chat draws in front of a web link.

Endpoint:
    GET /api/link-icon?host=reddit.com -> the site's icon as a 64 px PNG
                                          (404 when the site has none)

A link in an answer is drawn as a short name with the logo of its website
(``WebLink.tsx`` in the chat frontend). The logo is the site's own icon: the
backend reads the icons the home page names (``<link rel="icon">``), falls
back to ``/favicon.ico`` and the ``apple-touch-icon``, decodes the first one
that is a real picture with Pillow and keeps it as a PNG under
``<data>/link_icons``. So each site is asked once, the window never loads a
third-party address itself, and nothing but a decoded PNG is served from the
app's own origin (an SVG icon could carry script).

Only public https hosts are reached (``dodaios.core.http_guard``), on the
first request and on every redirect.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from dodaios.core.http_guard import public_only_async

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/link-icon", tags=["link-icon"])

#: A host name the route accepts: letters, digits, dots and dashes, with a dot.
_HOST_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")
#: The edge of the PNG kept per site; drawn at about 16 px, sharp on a Retina screen.
ICON_SIZE = 64
#: How long a found icon is kept before the site is asked again.
KEEP_FOUND_S = 30 * 24 * 3600
#: How long "this site has no icon" is kept before the site is asked again.
KEEP_MISSING_S = 24 * 3600
#: An icon at least this large is taken at once; a smaller one only when nothing larger exists.
_SHARP_EDGE = 32
_MAX_PAGE_BYTES = 768 * 1024
_MAX_ICON_BYTES = 512 * 1024
_TIMEOUT = httpx.Timeout(6.0, connect=4.0)
# Several sites answer a client without a browser name with an error page.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)
_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}

_locks: dict[str, asyncio.Lock] = {}


def icon_dir() -> Path:
    """Where the icons are kept: ``<data>/link_icons``."""
    from dodaios.core.config import DATA_DIR

    return Path(DATA_DIR) / "link_icons"


def normalize_host(raw: str) -> str | None:
    """``raw`` as a lower-case host name without ``www.``, or None when it is not one."""
    host = (raw or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host if _HOST_RE.match(host) else None


class _IconLinks(HTMLParser):
    """The icons a page names in its ``<head>``, with their declared size."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.icons: list[tuple[str, str, int]] = []
        self.base = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        if tag == "base" and values.get("href") and not self.base:
            self.base = values["href"]
            return
        if tag != "link":
            return
        rel = set(values.get("rel", "").lower().split())
        href = values.get("href", "").strip()
        if not href or not rel & {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}:
            return
        kind = "icon" if "icon" in rel else "apple"
        size = 0
        for token in values.get("sizes", "").lower().split():
            width, _, _height = token.partition("x")
            if width.isdigit():
                size = max(size, int(width))
        self.icons.append((href, kind, size))


def icon_candidates(page_url: str, html: str) -> list[str]:
    """The icon addresses worth trying for a page, best first.

    The page's own ``icon`` links come first, the one nearest to 64 px leading
    (an SVG is skipped, Pillow cannot read it), then ``/favicon.ico``, then the
    ``apple-touch-icon``, which is larger but often a full tile.
    """
    parser = _IconLinks()
    try:
        parser.feed(html)
    except Exception:  # a broken page only means fewer named icons; /favicon.ico still follows
        log.debug("Link icon: the page could not be read to the end")
    base = urljoin(page_url, parser.base) if parser.base else page_url

    def usable(href: str) -> bool:
        lowered = href.lower().split("?", 1)[0]
        return not lowered.startswith("data:") and not lowered.endswith(".svg")

    def distance(size: int) -> int:
        # Undeclared sizes rank after declared ones that fit; a large icon beats a tiny one.
        if size == 0:
            return 1000
        return size - ICON_SIZE if size >= ICON_SIZE else 2 * (ICON_SIZE - size)

    named = [(href, size) for href, kind, size in parser.icons if kind == "icon" and usable(href)]
    apple = [(href, size) for href, kind, size in parser.icons if kind == "apple" and usable(href)]
    ordered = [urljoin(base, href) for href, _size in sorted(named, key=lambda item: distance(item[1]))]
    ordered.append(urljoin(page_url, "/favicon.ico"))
    ordered += [urljoin(base, href) for href, _size in apple]
    out: list[str] = []
    for url in ordered:
        if url.startswith("https://") and url not in out:
            out.append(url)
    return out[:6]


def to_png(raw: bytes) -> tuple[bytes, int]:
    """``raw`` decoded as a picture, as a square PNG of :data:`ICON_SIZE`, and its source edge.

    A smaller picture is scaled up to fill the square. Raises ``ValueError``
    (or Pillow's ``OSError``) for anything that is not a picture.
    """
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as picture:
        if picture.format == "ICO":
            # An .ico holds several sizes; take the largest instead of the first.
            sizes = sorted(picture.info.get("sizes") or [], key=lambda size: size[0] * size[1])
            if sizes:
                picture.size = sizes[-1]
        if picture.width > 4096 or picture.height > 4096 or picture.width < 8 or picture.height < 8:
            raise ValueError("not an icon-sized picture")
        image = picture.convert("RGBA")
    edge = max(image.width, image.height)
    if needs_backdrop(image):
        image = on_backdrop(image)
    scale = ICON_SIZE / edge
    fitted = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    image = image.resize(fitted, Image.Resampling.LANCZOS)
    if image.size != (ICON_SIZE, ICON_SIZE):
        square = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        square.paste(image, ((ICON_SIZE - image.width) // 2, (ICON_SIZE - image.height) // 2))
        image = square
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), edge


def needs_backdrop(image) -> bool:
    """Whether the icon is a dark mark on a see-through ground (GitHub's cat, a black letter).

    Such a mark disappears on the dark theme, so it gets a light tile.
    """
    alpha = image.getchannel("A")
    pixels = image.width * image.height
    opaque = sum(alpha.point(lambda value: 1 if value > 128 else 0).getdata())
    if opaque == 0 or opaque > pixels * 0.7:
        return False
    grey = image.convert("L")
    total = 0
    for light, cover in zip(grey.getdata(), alpha.getdata()):
        if cover > 128:
            total += light
    return total / opaque < 70


def on_backdrop(image):
    """The icon centred on a light rounded tile, with a little room around it."""
    from PIL import Image, ImageDraw

    edge = max(image.width, image.height)
    side = round(edge * 1.3)
    tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, side - 1, side - 1), radius=round(side * 0.22), fill=(244, 244, 245, 255))
    tile.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
    return tile


async def _read(client: httpx.AsyncClient, url: str, limit: int) -> tuple[bytes, str]:
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > limit:
                raise ValueError("response too large")
            chunks.append(chunk)
        return b"".join(chunks), str(response.url)


async def fetch_icon(host: str, client: httpx.AsyncClient | None = None) -> bytes | None:
    """The site's icon as a PNG, or None when it has none we can read."""
    own = client is None
    if client is None:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,image/*;q=0.9,*/*;q=0.5"},
            **public_only_async(),
        )
    try:
        page_url = f"https://{host}/"
        html = ""
        try:
            raw, page_url = await _read(client, page_url, _MAX_PAGE_BYTES)
            html = raw.decode("utf-8", errors="replace")
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("Link icon: home page of %s unavailable (%s)", host, type(exc).__name__)
        # The first sharp icon wins; a tiny one (16 px) only when there is nothing larger.
        best: tuple[bytes, int] | None = None
        for url in icon_candidates(page_url, html):
            try:
                raw, _ = await _read(client, url, _MAX_ICON_BYTES)
                png, edge = await asyncio.to_thread(to_png, raw)
            except (httpx.HTTPError, ValueError, OSError) as exc:
                log.debug("Link icon: %s is not usable (%s)", url, type(exc).__name__)
                continue
            if edge >= _SHARP_EDGE:
                return png
            if best is None or edge > best[1]:
                best = (png, edge)
        return best[0] if best else None
    finally:
        if own:
            await client.aclose()


def _fresh(path: Path, keep_s: int) -> bool:
    try:
        return time.time() - path.stat().st_mtime < keep_s
    except OSError:  # no file yet: not fresh
        return False


async def icon_for(host: str) -> bytes | None:
    """The kept icon of ``host``, fetched once when it is missing or old."""
    folder = icon_dir()
    found = folder / f"{host}.png"
    missing = folder / f"{host}.none"
    if _fresh(found, KEEP_FOUND_S):
        return found.read_bytes()
    if _fresh(missing, KEEP_MISSING_S):
        return None
    lock = _locks.setdefault(host, asyncio.Lock())
    async with lock:
        if _fresh(found, KEEP_FOUND_S):
            return found.read_bytes()
        if _fresh(missing, KEEP_MISSING_S):
            return None
        png = await fetch_icon(host)
        # A sub-domain without an icon of its own (docs.example.com) shows its parent's.
        labels = host.split(".")
        if png is None and len(labels) > 2:
            parent = ".".join(labels[1:])
            if normalize_host(parent) and len(labels[-2]) > 3:
                png = await fetch_icon(parent)
        folder.mkdir(parents=True, exist_ok=True)
        if png is None:
            missing.write_bytes(b"")
            # An older icon still beats none when the site is down for a day.
            return found.read_bytes() if found.exists() else None
        temp = found.with_suffix(".tmp")
        temp.write_bytes(png)
        temp.replace(found)
        missing.unlink(missing_ok=True)
        return png


@router.get("", summary="The logo of a website, for a link in the chat")
async def link_icon(host: str = Query(..., max_length=260)) -> Response:
    """The site's icon as a PNG; 404 when the host is not valid or has no icon."""
    name = normalize_host(host)
    if name is None:
        raise HTTPException(status_code=404, detail="no-icon")
    png = await icon_for(name)
    if png is None:
        raise HTTPException(status_code=404, detail="no-icon")
    return Response(content=png, media_type="image/png", headers=_CACHE_HEADERS)
