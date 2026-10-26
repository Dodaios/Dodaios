"""REST API for the picture behind the tiled section layout.

Endpoints:
    GET    /api/wallpaper/info  -> {"source": "custom"|"desktop"|"none", "version": str}
    GET    /api/wallpaper       -> the picture itself (404 when there is none)
    POST   /api/wallpaper       -> upload a custom picture (multipart ``file``)
    DELETE /api/wallpaper       -> drop the custom picture, back to the desktop one

The default is the operating system's own desktop wallpaper (see
``dodaios.ui.wallpaper``). Uploads are decoded with Pillow so only real images
land on disk, under a fixed name, so there is at most one custom picture.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from dodaios.ui import wallpaper

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wallpaper", tags=["wallpaper"])


def _info() -> dict[str, Any]:
    source, path = wallpaper.current()
    version = ""
    if path is not None:
        try:
            stat = path.stat()
            version = f"{int(stat.st_mtime)}-{stat.st_size}"
        except OSError:  # file vanished mid-read: an empty version only skips cache busting
            version = ""
    return {"source": source, "version": version}


@router.get("/info", operation_id="wallpaper_info")
async def wallpaper_info() -> dict[str, Any]:
    """Which picture is behind the layout, and a version for cache busting."""
    return await asyncio.to_thread(_info)


@router.get("", operation_id="wallpaper_image")
async def wallpaper_image() -> Response:
    """The custom picture, else the desktop wallpaper; 404 when neither exists."""
    _source, path = await asyncio.to_thread(wallpaper.current)
    if path is None:
        raise HTTPException(status_code=404, detail="No wallpaper available.")
    return FileResponse(
        str(path),
        media_type=wallpaper.media_type(path),
        headers={"Cache-Control": "no-cache"},
    )


def _store(data: bytes) -> str:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as probe2:
            fmt = (probe2.format or "").upper()
    except Exception as exc:  # noqa: BLE001 - any decode failure = not an image
        raise HTTPException(status_code=400, detail="File is not a valid image.") from exc
    ext = wallpaper.UPLOAD_FORMAT_EXT.get(fmt)
    if ext is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image format '{fmt or 'unknown'}'. "
            "Use PNG, JPEG, WebP, GIF or BMP.",
        )
    folder = wallpaper.custom_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{wallpaper.CUSTOM_STEM}{ext}"
    fd, tmp_path = tempfile.mkstemp(prefix=".wallpaper.", suffix=ext, dir=str(folder))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            log.debug("could not remove temp wallpaper %s", tmp_path)
        raise
    for old in folder.glob(f"{wallpaper.CUSTOM_STEM}.*"):
        if old.resolve() != target.resolve():
            try:
                old.unlink()
            except OSError as exc:
                log.warning("old wallpaper not removed: %s", exc)
    return fmt


@router.post("", operation_id="wallpaper_upload")
async def wallpaper_upload(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency default
) -> dict[str, Any]:
    """Store ``file`` as the custom picture behind the layout."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > wallpaper.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large (max {wallpaper.MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )
    fmt = await asyncio.to_thread(_store, data)
    return {"ok": True, "format": fmt, **(await asyncio.to_thread(_info))}


def _remove() -> bool:
    removed = False
    folder = wallpaper.custom_dir()
    if folder.is_dir():
        for path in folder.glob(f"{wallpaper.CUSTOM_STEM}.*"):
            try:
                path.unlink()
                removed = True
            except OSError as exc:
                log.warning("wallpaper delete failed for %s: %s", path, exc)
    return removed


@router.delete("", operation_id="wallpaper_reset")
async def wallpaper_reset() -> dict[str, Any]:
    """Remove the custom picture; the desktop wallpaper shows again."""
    removed = await asyncio.to_thread(_remove)
    return {"ok": True, "removed": removed, **(await asyncio.to_thread(_info))}
