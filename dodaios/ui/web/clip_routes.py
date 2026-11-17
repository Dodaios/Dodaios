"""HTTP API of the clip editor (``docs/clips-editor.md``).

* ``POST   /api/nodes/{id}/clip/media``           a file into the clip's library (body = bytes).
* ``POST   /api/nodes/{id}/clip/captions``        captions from the speech of a spec.
* ``POST   /api/nodes/{id}/clip/transcribe``      the timed words of a library file.
* ``POST   /api/nodes/{id}/clip/silences``        the quiet stretches of a library file.
* ``POST   /api/nodes/{id}/clip/export``          start writing the clip as an MP4.
* ``GET    /api/nodes/{id}/clip/export/{job}``    how far that is.
* ``GET    /api/nodes/{id}/clip/export/{job}/file``  the finished MP4, as a download.
* ``DELETE /api/nodes/{id}/clip/export/{job}``    stop it.
* ``GET    /clip-media/{id}/{file}``              a library file (with byte ranges).

A media upload only stores the file and answers its library entry; the
caller (the editor, as an undoable step) puts the entry into the spec, so
the person's unsaved work is never overwritten by a write from here.

``/clip-media`` is outside ``/api`` on purpose: the clip page runs in a
sandbox with an opaque origin and no credential, and must still play its
videos. The security boundary lets GET and HEAD through for this prefix
only (:func:`dodaios.ui.web.surface_security._clip_media_request`); a file is
named by a random id, nothing else under it is listed or writable, and each
answer may run nothing (``default-src 'none'``). The node pages that play
them allow exactly this address in their policy (:func:`clip_page_csp`).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from dodaios.nodes.clip import export as clip_export
from dodaios.nodes.clip.media import (
    MAX_FILE_BYTES,
    MediaError,
    import_media,
    library_file,
    media_dir,
    media_file,
)
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError
from dodaios.ui.web.artifact_view import ARTIFACT_PAGE_CSP

log = logging.getLogger(__name__)

router = APIRouter(tags=["clips"])

#: A spec in a request body (the editor sends its unsaved spec).
MAX_JSON_BODY: Final[int] = 8 * 1024 * 1024
_FILE_HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'",
    # A library file never changes under its id.
    "Cache-Control": "private, max-age=31536000, immutable",
}


def clip_page_csp(request: Request) -> str:
    """The node page policy, with this server's ``/clip-media/`` allowed for pictures and sound.

    The source names the request's own origin: a sandboxed page has an opaque
    origin, so ``'self'`` would not reach the app.
    """
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return clip_export.page_csp(origin) if origin.strip(":/") else ARTIFACT_PAGE_CSP


def _store() -> Any:
    from dodaios.ui.web.nodes_routes import get_store

    return get_store()


async def _clip(node_id: str) -> tuple[Node, Path]:
    store = _store()
    node = await asyncio.to_thread(store.get, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node")
    if node.type != "motion":
        raise HTTPException(status_code=422, detail="This node is not a clip.")
    folder = await asyncio.to_thread(store.dir_of, node_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="unknown node")
    return node, folder


async def _json(request: Request) -> dict[str, Any]:
    from dodaios.ui.web.nodes_routes import _read_json

    data = await _read_json(request, MAX_JSON_BODY)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="The request body must be a JSON object.")
    return data


def _spec_of(node: Node, data: dict[str, Any]) -> dict[str, Any]:
    """The spec a request works on: the one it sends, else the saved one; normalized."""
    from dodaios.nodes.kinds import motion

    raw = data.get("spec")
    try:
        return motion.normalize(raw if isinstance(raw, dict) else node.spec)
    except NodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _number(data: dict[str, Any], key: str, default: float | None) -> float | None:
    value = data.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"'{key}' must be a number.") from None


def _library(folder: Path, data: dict[str, Any]) -> Path:
    path = library_file(folder, str(data.get("media") or "").strip().lower())
    if path is None:
        raise HTTPException(status_code=404, detail="That file is not in the clip's library.")
    return path


@router.post("/api/nodes/{node_id}/clip/media")
async def upload_media(node_id: str, request: Request) -> dict[str, Any]:
    """Store the uploaded file in the clip's library; answer ``{id, entry}``."""
    _, folder = await _clip(node_id)
    name = unquote(request.headers.get("x-file-name") or "").strip() or "media"
    name = Path(name.replace("\\", "/")).name[:200] or "media"
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="This file is larger than 4 GB.")
    staging = media_dir(folder)
    staging.mkdir(parents=True, exist_ok=True)
    # The upload keeps its own ending: the import reads the type from it too.
    upload = staging / f".upload-{secrets.token_hex(8)}{Path(name).suffix.lower()[:8]}"
    size = 0
    try:
        with upload.open("wb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="This file is larger than 4 GB.")
                await asyncio.to_thread(handle.write, chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="The file is empty.")
        media_id, entry = await asyncio.to_thread(import_media, folder, upload, name)
    except MediaError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        upload.unlink(missing_ok=True)
    log.info("clip %s: imported %s as %s (%s)", node_id, name, media_id, entry["kind"])
    return {"id": media_id, "entry": entry}


@router.post("/api/nodes/{node_id}/clip/captions")
async def make_captions(node_id: str, request: Request) -> dict[str, Any]:
    """Captions from the speech of the clip as edited (``{spec, language?}``)."""
    from dodaios.nodes.clip.captions import caption_lines, timeline_words
    from dodaios.nodes.clip.transcribe import TranscribeError

    node, folder = await _clip(node_id)
    data = await _json(request)
    spec = _spec_of(node, data)
    language = str(data.get("language") or "").strip()[:8] or None
    try:
        words = await asyncio.to_thread(timeline_words, spec, folder, language)
    except TranscribeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    lines = caption_lines(words, spec["format"])
    return {"items": lines, "words": len(words)}


@router.post("/api/nodes/{node_id}/clip/transcribe")
async def transcribe(node_id: str, request: Request) -> dict[str, Any]:
    """The timed words of a library file (``{media, in?, out?, language?}``)."""
    from dodaios.nodes.clip.transcribe import TranscribeError, transcribe_file

    _, folder = await _clip(node_id)
    data = await _json(request)
    path = _library(folder, data)
    start = _number(data, "in", 0.0) or 0.0
    end = _number(data, "out", None)
    language = str(data.get("language") or "").strip()[:8] or None
    try:
        return await asyncio.to_thread(transcribe_file, path, start, end, language)
    except TranscribeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/nodes/{node_id}/clip/silences")
async def silences(node_id: str, request: Request) -> dict[str, Any]:
    """The quiet stretches of a library file (``{media, in?, out?, min_silence?, pad?}``)."""
    from dodaios.nodes.clip.silence import find_silences

    _, folder = await _clip(node_id)
    data = await _json(request)
    path = _library(folder, data)
    spans = await asyncio.to_thread(
        find_silences,
        path,
        _number(data, "in", 0.0) or 0.0,
        _number(data, "out", None),
        min(10.0, max(0.1, _number(data, "min_silence", 0.5) or 0.5)),
        min(1.0, max(0.0, _number(data, "pad", 0.12) or 0.0)),
    )
    return {"silences": [[a, b] for a, b in spans]}


class ExportBody(BaseModel):
    spec: dict[str, Any] | None = None
    preset: str = Field(default="1080p", max_length=8)
    fps: int = 30


@router.post("/api/nodes/{node_id}/clip/export")
async def start_export(node_id: str, request: Request) -> dict[str, Any]:
    """Start writing the clip as an MP4; answer the job to follow."""
    from dodaios.ui.web.nodes_routes import _body

    node, folder = await _clip(node_id)
    body = _body(ExportBody, await _json(request))
    spec = _spec_of(node, {"spec": body.spec})
    try:
        job = clip_export.start_export(node, folder, spec, body.preset, body.fps)
    except clip_export.ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _owners[job] = node_id
    return {"job": job}


#: Which clip each export job belongs to, so one clip cannot read another's.
_owners: dict[str, str] = {}


def _job(node_id: str, job: str) -> dict[str, Any]:
    status = clip_export.export_status(job)
    if status is None or _owners.get(job) != node_id:
        raise HTTPException(status_code=404, detail="unknown export")
    return status


@router.get("/api/nodes/{node_id}/clip/export/{job}")
async def export_state(node_id: str, job: str) -> dict[str, Any]:
    """How far an export is; a finished one names its file (and where it is in the run)."""
    node, folder = await _clip(node_id)
    status = _job(node_id, job)
    if status.get("file"):
        path = Path(status["file"])
        status["name"] = path.name
        status["slug"] = node.slug
        try:
            status["path"] = path.relative_to(folder).as_posix()
        except ValueError:  # a file outside the run folder has no relative path to give
            status["path"] = ""
    return status


@router.get("/api/nodes/{node_id}/clip/export/{job}/file")
async def export_file(node_id: str, job: str) -> FileResponse:
    """The finished MP4, as a download."""
    _, folder = await _clip(node_id)
    status = _job(node_id, job)
    path = Path(status.get("file") or "")
    present = await asyncio.to_thread(path.is_file)
    if status["state"] != "done" or not present or folder not in path.parents:
        raise HTTPException(status_code=409, detail="The export is not finished.")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=path.name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/api/nodes/{node_id}/clip/export/{job}")
async def stop_export(node_id: str, job: str) -> JSONResponse:
    """Stop a running export after its current frame."""
    await _clip(node_id)
    _job(node_id, job)
    return JSONResponse({"stopped": clip_export.cancel_export(job)})


@router.get("/clip-media/{node_id}/{file_name}")
@router.head("/clip-media/{node_id}/{file_name}", include_in_schema=False)
async def serve_media(node_id: str, file_name: str) -> FileResponse:
    """A file of a clip's library, with byte ranges (a video element seeks by them)."""
    folder = await asyncio.to_thread(_store().dir_of, node_id)
    path = media_file(folder, file_name) if folder is not None else None
    if path is None:
        raise HTTPException(status_code=404, detail="unknown file")
    return FileResponse(
        path, media_type=clip_export.content_type(path), headers=dict(_FILE_HEADERS)
    )


__all__ = ["MAX_JSON_BODY", "clip_page_csp", "router"]
