"""Static assets and the SPA fallback (the built frontend under ``dist/``)."""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match
from starlette.types import Scope


from ..fast_bootstrap import ASSET_SUFFIXES
from ..spa_build import (
    build_is_complete,
    holding_page_html,
    recover_conflicted_index,
)

if TYPE_CHECKING:
    pass

from ._srv import server_module


def _is_backend_path(path: str) -> bool:
    """Paths the SPA catch-all must never claim: the API and the sockets."""
    return path == "/api" or path.startswith(("/api/", "/ws"))


class _SpaFallbackRoute(APIRoute):
    """The SPA catch-all, invisible to API and socket paths.

    A plain ``GET /{full_path:path}`` partially matches EVERY path, so the
    router answered an unknown ``POST /api/...`` with 405 and ``Allow: GET`` —
    pointing a client at a GET that does not exist — and a bare ``GET /api``
    with the SPA's HTML. Declining backend paths lets the router answer
    honestly: 404 for a route that does not exist, 405 only for a real route
    asked with the wrong method.
    """

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope.get("type") == "http" and _is_backend_path(scope.get("path", "")):
            return Match.NONE, {}
        return super().matches(scope)


class StaticAssetsMixin:
    """Static assets and the SPA fallback (the built frontend under ``dist/``)."""

    def _register_static_or_spa(self, app: FastAPI) -> None:
        if self.cfg.ui.dev_mode:
            return

        # An install without dist/ would otherwise sit on "Updating…" forever
        # with nothing in the log (issue #1057).
        server_module().missing_build_watch.note_startup(server_module().INDEX_FILE)

        if server_module().ASSETS_DIR.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(server_module().ASSETS_DIR)),
                name="assets",
            )

        @app.get("/", include_in_schema=False, response_model=None)
        async def _spa_root() -> FileResponse | HTMLResponse:
            # Off the loop: deciding between the index and the holding page
            # reads index.html and stats every asset it references. On a disk
            # that is busy paging in a cold boot that took long enough to show
            # up in a loop-stall stack (2026-08-26, BUG-189).
            return await asyncio.to_thread(self._spa_index_response)

        async def _spa_fallback(
            full_path: str,
        ) -> FileResponse | HTMLResponse | JSONResponse:
            # API and socket paths never reach this handler: _SpaFallbackRoute
            # declines them, so the router answers 404 / 405 itself.
            target = server_module().dist_file(server_module().DIST_DIR, full_path)
            if target is not None:
                return FileResponse(str(target))
            # A missing asset (image/script/font) gets an honest 404, never the
            # SPA index: an <img> that receives HTML with a 200 renders as a
            # permanently broken image — the browser treats the load as a
            # success and never retries (sidebar-logo regression, 2026-07-18).
            if PurePosixPath(full_path).suffix.lower() in ASSET_SUFFIXES:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return await asyncio.to_thread(self._spa_index_response)

        app.router.add_api_route(
            "/{full_path:path}",
            _spa_fallback,
            methods=["GET"],
            include_in_schema=False,
            response_model=None,
            route_class_override=_SpaFallbackRoute,
        )

    def _spa_index_response(self) -> FileResponse | HTMLResponse:
        # An index.html whose own entry bundle is not on disk is worse than no
        # index.html at all: the window paints the boot splash, the module
        # script 404s, and nothing further runs — no React, no bundle watch, no
        # preload recovery — so the only thing left is the 20-second blank-window
        # watchdog. A rebuild deletes dist/assets while leaving the previous
        # index.html in place for about two seconds (measured 2026-08-22), and
        # every window that loads during those two seconds is stuck there. The
        # holding page below says what is happening and comes back on its own.
        # See dodaios/ui/web/spa_build.py.
        if server_module().INDEX_FILE.is_file() and build_is_complete(server_module().INDEX_FILE, server_module().DIST_DIR):
            server_module().missing_build_watch.clear()
            return FileResponse(
                str(server_module().INDEX_FILE),
                headers={
                    "Cache-Control": "no-store, max-age=0",
                    "Pragma": "no-cache",
                },
            )
        recovered = recover_conflicted_index(server_module().INDEX_FILE, server_module().DIST_DIR)
        if recovered is not None:
            server_module().missing_build_watch.clear()
            return HTMLResponse(
                content=recovered,
                headers={
                    "Cache-Control": "no-store, max-age=0",
                    "Pragma": "no-cache",
                },
            )
        return self._spa_placeholder_response(
            build_missing=server_module().missing_build_watch.observe(server_module().INDEX_FILE)
        )

    @staticmethod
    def _spa_placeholder_response(*, build_missing: bool = False) -> HTMLResponse:
        """The boot splash, while dist/ is between two builds.

        It is deliberately the SAME splash the window opens with — same ground,
        same ring, same assistant name — because a rebuild is not a different
        program taking over the window. Resolving the theme is left to a two-line
        inline script reading the very key `frontend/index.html` reads, which
        also takes a synchronous `load_config()` off the one event loop that is
        simultaneously serving every asset of the build that is landing.

        It waits for a COMPLETE build instead of reloading on a timer: the page
        polls the entry document and reloads only once the answer is no longer
        itself. A blind `<meta http-equiv="refresh">` reloads into the same
        half-written dist over and over, which is the flicker rather than the
        cure.
        """
        return HTMLResponse(
            content=holding_page_html(build_missing=build_missing),
            status_code=200,
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )
