"""Looks: list them, pick one, and serve their files to the sandboxed frame.

    GET  /api/looks                  -> every look plus the active id
    PUT  /api/looks/active           -> pick the active look ("orb" for none)
    GET  /api/looks/{id}/preview     -> the look's preview picture
    GET  /looks-frame/{id}/{path}    -> a file of the look, for its frame only

The app shows a look in an ``<iframe sandbox="allow-scripts">`` (no
same-origin), so the page runs in an opaque origin: it cannot read the app's
storage or cookies, and ``SurfaceSecurity`` refuses its requests to every
other route (``Origin: null``, ``Sec-Fetch-Site: cross-site``). The frame
files are the one exception, and each of them carries a Content-Security-
Policy that limits every load to the look's own folder. See docs/looks.md.

The look engine is imported inside the handlers, so nothing here loads on
the boot path.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from dodaios.core.config import ORB_LOOK_ID, normalize_look_id

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/looks", tags=["looks"])
frame_router = APIRouter(tags=["looks"])

#: URL prefix of the frame files; ``SurfaceSecurity`` exempts GET/HEAD here.
FRAME_PREFIX = "/looks-frame/"


class ActiveBody(BaseModel):
    id: str = Field(..., max_length=64)


def _ui(request: Request) -> Any | None:
    cfg = getattr(request.app.state, "config", None) or getattr(request.app.state, "cfg", None)
    return getattr(cfg, "ui", None)


def _find(look_id: str) -> tuple[Path, Any] | None:
    """``(folder, manifest)`` of a valid look, or ``None``."""
    from dodaios.ui.looks import loader
    from dodaios.ui.looks.manifest import LookManifestError

    found = loader.find_look_dir(look_id)
    if found is None:
        return None
    folder, builtin = found
    try:
        manifest = loader.read_manifest(folder, builtin=builtin, check_files=False)
    except LookManifestError as exc:
        log.warning("look %r is broken: %s", look_id, exc)
        return None
    return folder, manifest


def _look_json(manifest: Any) -> dict[str, Any]:
    return {
        **manifest.to_public(),
        "preview_url": f"/api/looks/{manifest.id}/preview",
        "frame_url": f"{FRAME_PREFIX}{manifest.id}/{manifest.entry}",
    }


def _list_state(request: Request) -> dict[str, Any]:
    from dodaios.ui.looks import loader

    looks = loader.list_looks()
    ids = {m.id for m in looks}
    configured = normalize_look_id(getattr(_ui(request), "look_id", None)) or ORB_LOOK_ID
    active = configured if configured in ids else ORB_LOOK_ID
    return {"active": active, "looks": [_look_json(m) for m in looks]}


@router.get("")
async def list_looks(request: Request) -> dict[str, Any]:
    return await asyncio.to_thread(_list_state, request)


@router.put("/active")
async def put_active(body: ActiveBody, request: Request) -> dict[str, Any]:
    """Pick the active look and save ``[ui] look_id``."""
    look_id = normalize_look_id(body.id)
    if look_id is None:
        raise HTTPException(status_code=400, detail=f"'{body.id.strip()}' is not a look id.")
    if look_id != ORB_LOOK_ID and await asyncio.to_thread(_find, look_id) is None:
        raise HTTPException(status_code=404, detail=f"There is no look '{look_id}'.")

    ui = _ui(request)
    if ui is not None:
        try:
            ui.look_id = look_id
        except Exception as exc:  # noqa: BLE001 - a frozen model is not an error
            log.debug("in-memory ui.look_id update skipped: %s", exc)
    persisted = True
    try:
        from dodaios.core import config_writer
        from dodaios.core.config import resolve_config_path

        await asyncio.to_thread(config_writer.set_look_id, look_id, path=resolve_config_path())
    except Exception as exc:  # noqa: BLE001 - the in-memory pick still holds
        persisted = False
        log.warning("look_id persist failed (kept until restart): %s", exc)
    state = await asyncio.to_thread(_list_state, request)
    return {"ok": True, "persisted": persisted, **state}


@router.get("/{look_id}/preview", response_model=None)
async def look_preview(look_id: str) -> FileResponse:
    from dodaios.ui.looks import loader

    found = await asyncio.to_thread(_find, look_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such look.")
    folder, manifest = found
    resolved = loader.resolve_file(folder, manifest.preview)
    if resolved is None:
        raise HTTPException(status_code=404, detail="The look has no preview.")
    path, media_type = resolved
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        },
    )


def frame_csp(base: str) -> str:
    """The policy of every frame file: loads only from ``base`` (the look's folder)."""
    return "; ".join(
        (
            "default-src 'none'",
            f"script-src {base} 'unsafe-inline' 'wasm-unsafe-eval'",
            f"style-src {base} 'unsafe-inline'",
            f"img-src {base} data: blob:",
            f"font-src {base} data:",
            f"media-src {base} blob:",
            f"connect-src {base} data: blob:",
            f"worker-src {base} blob:",
            "frame-src 'none'",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'self'",
            "sandbox allow-scripts",
        )
    )


# Frame files, not an API: kept out of OpenAPI, where GET and HEAD would
# share one operation id.
@frame_router.api_route(
    FRAME_PREFIX + "{look_id}/{file_path:path}", methods=["GET", "HEAD"], include_in_schema=False
)
async def look_frame_file(look_id: str, file_path: str, request: Request) -> FileResponse:
    """One file of a look, served only for its sandboxed frame."""
    from dodaios.ui.looks import loader

    if normalize_look_id(look_id) != look_id:
        raise HTTPException(status_code=404, detail="No such look.")
    found = await asyncio.to_thread(loader.find_look_dir, look_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such look.")
    resolved = loader.resolve_file(found[0], file_path)
    if resolved is None:
        raise HTTPException(status_code=404, detail="No such file in this look.")
    path, media_type = resolved
    base = f"{request.url.scheme}://{request.url.netloc}{FRAME_PREFIX}{look_id}/"
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Content-Security-Policy": frame_csp(base),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            # The frame runs in an opaque origin; its own fetches (models,
            # module scripts) arrive with "Origin: null".
            "Access-Control-Allow-Origin": "null",
            "Cache-Control": "no-cache",
        },
    )
