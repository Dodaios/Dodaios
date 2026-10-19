"""REST API for the Agentic IDE's browser panel: the user's own browser inside the app.

The panel shows a real window of the user's installed Chrome (or Edge, Brave),
opened with the profile they pick, so every site works and every sign-in is
there (see ``dodaios.ui.browser_embed``). The page drives it through these routes:

    GET  /api/ide-browser/status   installed browsers, their profiles, window state
    POST /api/ide-browser/launch   {browser, profile, url?, view?}  open + take a window
    POST /api/ide-browser/place    {owner, visible, rect?, dpr?, view?}  follow the panel
    POST /api/ide-browser/release  {close}  close it, or hand it back as a normal window

Only the Windows desktop shell can do this. Anywhere else (a browser tab, a
headless server, macOS, Linux) ``status`` answers ``available: false`` with a
reason and the panel keeps its built-in page view. ``view`` names a detached
window, as for ``/api/window/zoom``; omitted, the main window is used.

Every native call is thread-hopped off the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
