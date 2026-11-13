"""REST API for the Agentic IDE's browser panel: the user's own browser inside the app.

The panel shows a real window of the user's installed Chrome (or Edge, Brave),
opened with the profile they pick, so every site works and every sign-in is
there (see ``dodaios.ui.browser_embed``). The page drives it through these routes:

    GET  /api/ide-browser/status   installed browsers, their profiles, window state
    POST /api/ide-browser/launch   {browser, profile, url?, view?}  open + take a window
    POST /api/ide-browser/place    {owner, visible, rect?, dpr?, view?}  follow the panel
    POST /api/ide-browser/release  {close}  close it, or hand it back as a normal window
    POST /api/ide-browser/open     {url}  open a link as a new tab in the shown window
    POST /api/ide-browser/frame-check {url}  may the built-in page view show this page?

Only the Windows desktop shell can do this. Anywhere else (a browser tab, a
headless server, macOS, Linux) ``status`` answers ``available: false`` with a
reason and the panel keeps its built-in page view. That view is a frame, and
most large sites forbid being framed: the browser then draws an empty white
page and says nothing. ``frame-check`` asks the site first, so the panel can
say so and offer the user's own browser instead. ``view`` names a detached
window, as for ``/api/window/zoom``; omitted, the main window is used.

Every native call is thread-hopped off the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ide-browser", tags=["ide-browser"])


class LaunchBody(BaseModel):
    browser: str = Field(min_length=1, max_length=32)
    profile: str = Field(min_length=1, max_length=64)
    url: str | None = Field(default=None, max_length=4096)
    view: str | None = Field(default=None, max_length=64)


class PanelRect(BaseModel):
    x: float = Field(ge=-100_000, le=100_000)
    y: float = Field(ge=-100_000, le=100_000)
    width: float = Field(ge=0, le=100_000)
    height: float = Field(ge=0, le=100_000)


class PlaceBody(BaseModel):
    owner: str = Field(min_length=1, max_length=64)
    visible: bool
    rect: PanelRect | None = None
    dpr: float = Field(default=1.0, gt=0, le=16)
    view: str | None = Field(default=None, max_length=64)


class OpenBody(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class FrameCheckBody(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class ReleaseBody(BaseModel):
    close: bool = True


def _host(request: Request, view: str | None) -> int | None:
    desktop = getattr(request.app.state, "desktop_app", None)
    lookup = getattr(desktop, "browser_panel_host", None)
    if not callable(lookup):
        return None
    return lookup(view or None)


def _unavailable(reason: str) -> dict[str, Any]:
    return {"ok": False, "available": False, "reason": reason, "browsers": [], "state": "idle"}


@router.get("/status", operation_id="status")
async def ide_browser_status(request: Request) -> dict[str, Any]:
    """Which browsers and profiles the panel can show, and the window's state."""
    from dodaios.ui.browser_embed import get_embed
    from dodaios.ui.browser_profiles import installed_browsers

    embed = get_embed()
    if not embed.supported():
        return _unavailable("unsupported_platform")
    if not callable(getattr(getattr(request.app.state, "desktop_app", None),
                            "browser_panel_host", None)):
        return _unavailable("no_desktop_shell")
    browsers = await asyncio.to_thread(installed_browsers)
    if not browsers:
        return _unavailable("no_browser")
    state = await asyncio.to_thread(embed.status)
    return {**state, "ok": True, "available": True, "browsers": browsers}


# Opening and closing the user's own browser windows: the CLI asks for --yes.
@router.post("/launch", operation_id="launch", openapi_extra={"x-jarvis-dangerous": True})
async def ide_browser_launch(body: LaunchBody, request: Request) -> dict[str, Any]:
    """Open a window of the chosen browser and profile inside the app window."""
    from dodaios.ui.browser_embed import get_embed

    host = await asyncio.to_thread(_host, request, body.view)
    if not host:
        return _unavailable("no_desktop_shell")
    embed = get_embed()
    return await asyncio.to_thread(embed.launch, body.browser, body.profile, body.url, host)


@router.post("/place", operation_id="place")
async def ide_browser_place(body: PlaceBody, request: Request) -> dict[str, Any]:
    """Keep the browser window on the panel's rectangle, or hide it with the panel."""
    from dodaios.ui.browser_embed import get_embed

    host = await asyncio.to_thread(_host, request, body.view)
    if not host:
        return _unavailable("no_desktop_shell")
    rect = body.rect.model_dump() if body.rect is not None else None
    embed = get_embed()
    try:
        return await asyncio.to_thread(
            embed.place, body.owner, host, rect, body.dpr, body.visible,
        )
    except Exception as exc:  # noqa: BLE001 - reported to the page, logged here
        log.warning("Browser panel place failed: %s", exc, exc_info=True)
        return {**embed.status(), "ok": False, "reason": "place_failed"}


@router.post("/release", operation_id="release", openapi_extra={"x-jarvis-dangerous": True})
async def ide_browser_release(body: ReleaseBody) -> dict[str, Any]:
    """Close the panel's browser window, or hand it back as a normal browser window."""
    from dodaios.ui.browser_embed import get_embed

    embed = get_embed()
    if not embed.supported():
        return _unavailable("unsupported_platform")
    return await asyncio.to_thread(embed.release, close=body.close, focus=not body.close)


@router.post("/open", operation_id="open")
async def ide_browser_open(body: OpenBody) -> dict[str, Any]:
    """Open a link from the app as a new tab in the panel's shown browser window."""
    from dodaios.ui.browser_embed import get_embed

    embed = get_embed()
    if not embed.supported():
        return _unavailable("unsupported_platform")
    return await asyncio.to_thread(embed.open_tab, body.url)


# A site answers within this or the frame would sit white for as long anyway.
_FRAME_CHECK_TIMEOUT_S = 6.0
# Some sites send other headers to clients that do not look like a browser.
_FRAME_CHECK_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)


def framing_refused(x_frame_options: str | None, policies: Iterable[str]) -> bool:
    """Whether a page with these response headers refuses to show in this app's frame.

    The app's page is a local origin (``http://127.0.0.1:<port>``) that no site
    names, so ``'self'``, a host list or ``'none'`` all refuse it. A
    ``frame-ancestors`` directive wins over ``X-Frame-Options``, as in browsers.
    """
    ancestors: list[str] | None = None
    for policy in policies:
        for directive in policy.split(";"):
            parts = directive.split()
            if parts and parts[0].lower() == "frame-ancestors":
                sources = [part.lower() for part in parts[1:]]
                # Several policies all apply: the strictest one decides.
                allowed = "*" in sources or "http:" in sources
                if not allowed:
                    return True
                ancestors = sources
    if ancestors is not None:
        return False
    value = (x_frame_options or "").split(",")[0].strip().lower()
    return value in {"deny", "sameorigin"} or value.startswith("allow-from")


@router.post("/frame-check", operation_id="frame_check")
async def ide_browser_frame_check(body: FrameCheckBody) -> dict[str, Any]:
    """May the built-in page view show ``url``? Asks the site for its headers only.

    ``frameable`` is false with ``reason`` ``refused`` when the site forbids
    being framed, ``unreachable`` when no answer came (a typo, a server that
    is not running). Only http and https addresses are asked.
    """
    parsed = urlparse(body.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"ok": False, "frameable": False, "reason": "bad_url"}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=_FRAME_CHECK_TIMEOUT_S,
            headers={"User-Agent": _FRAME_CHECK_UA, "Accept": "text/html,*/*;q=0.8"},
        ) as client, client.stream("GET", body.url) as response:
            # The frame shows the page the redirects end on: its headers decide.
            refused = framing_refused(
                response.headers.get("x-frame-options"),
                response.headers.get_list("content-security-policy"),
            )
    except (httpx.HTTPError, ValueError) as exc:
        log.info(
            "Browser panel frame check: %s did not answer (%s)",
            parsed.hostname, type(exc).__name__,
        )
        return {"ok": True, "frameable": False, "reason": "unreachable"}
    return {"ok": True, "frameable": not refused, "reason": "refused" if refused else ""}
