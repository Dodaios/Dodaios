"""Attachments, folder picking and the live event stream."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from dodaios.agent_chat import attachments as chat_attachments
from dodaios.agent_chat.service import (
    SUBSCRIBER_DROPPED,
)
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    PickFolderBody,
)

router = APIRouter()


# ------------------------------------------------------------------ attachments


@router.post("/attachments", summary="Drop, paste or pick files into a chat composer")
async def attach_files(
    request: Request,
    files: list[UploadFile] | None = File(default=None),  # noqa: B008
    paths: str | None = Form(default=None),  # noqa: B008
    session_id: str | None = Form(default=None),  # noqa: B008
    cwd: str | None = Form(default=None),  # noqa: B008
    voice_session_id: str | None = Form(default=None),  # noqa: B008
    provider: str = Form(default=""),  # noqa: B008
    surface: str = Form(default="agent"),  # noqa: B008
) -> dict[str, Any]:
    """Hold files for the message the person is still typing.

    Two inputs, either or both:

    * ``paths`` — newline-separated real locations. An Explorer or Finder drag
      usually carries them, and inside the desktop shell the host resolves one
      for every dropped file (``dodaios/ui/native_drop.py``). A path already
      inside the chat's folder is referenced where it lies; anything else is
      copied in.
    * ``files`` — raw bytes, for everything with no path at all: a screenshot
      pasted from the clipboard, an image dragged off a web page.

    Nothing is sent. Each file is stored, then READ — an image described by a
    vision-capable model, a document extracted — and the result comes back for
    the composer to hold and post with the message. That reading is the whole
    point: a chat can be answered by a coding CLI or a text-only model, so
    without it the person drops a picture, types "what is wrong here", and the
    model receives a filename.

    Which folder the copies land in, in order: the open session's, the
    composer's own ``cwd``, then the surface's default working directory. So an
    attach works before the first message, when no session exists yet.
    """
    svc = await _r._async_service(request)
    if voice_session_id:
        from dodaios.live.runtime import active
        from dodaios.ui.web.live_routes import _composer_cwd

        voice_session = next(
            (
                s
                for s in active()
                if s.session_id == voice_session_id and s.is_active and s.composer_available
            ),
            None,
        )
        if voice_session is None:
            raise HTTPException(409, "The selected voice call is no longer available.")
        session_id, cwd, surface = None, await _composer_cwd(request, voice_session), "jarvis"
    folder = ""
    if session_id:
        session = svc.store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        folder = session.cwd or ""
    if not folder:
        try:
            folder = _r._validate_cwd(cwd) or ""
        except HTTPException:
            # A composer whose remembered folder has gone (a moved checkout, a
            # detached drive) must still be able to take a file — the surface's
            # own directory below always exists.
            folder = ""
    if not folder:
        folder = svc.default_cwd(surface if surface in _r.SURFACE_NAMES else "agent")

    # The spooled upload file itself, not its bytes: a screen recording streams
    # to disk instead of being read into memory whole.
    uploads = [(upload.filename or "file", upload.file) for upload in files or []]

    try:
        found = await chat_attachments.ingest(
            folder,
            paths=(paths or "").splitlines(),
            uploads=uploads,
            provider=provider,
            always_copy=bool(voice_session_id),
            # These CLIs get the picture itself with the message, so a vision
            # description (and its 4-picture cap) would only be a worse copy.
            describe_images=not (
                provider in {"claude", "codex", "glm"}
                and not voice_session_id
                and surface != "jarvis"
            ),
        )
    except chat_attachments.AttachmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"attachments": [item.to_dict() for item in found], "cwd": folder}


@router.get(
    "/attachments/file",
    summary="Show one attached picture or video in the composer",
    openapi_extra={"x-jarvis-readonly": True},
)
async def attachment_file(cwd: str, reference: str) -> Any:
    """Stream an attached image or video back for the composer's thumbnail.

    A file dragged in by path (the Appshots gallery, Explorer inside the
    desktop shell) never passes its bytes through the window, so the composer
    has nothing to draw. ``reference`` is the attachment's own reference from
    :func:`attach_files`, ``cwd`` the folder that call answered with. Only a
    picture or video that resolves INSIDE that folder is served — symlinks
    included — and never SVG, which can carry script.
    """
    from fastapi.responses import FileResponse

    from dodaios.agent_chat.media import MEDIA_TYPES
    from dodaios.agentic_ide import drops

    folder = _r._validate_cwd(cwd)
    relative = drops.dereference(reference)
    if not folder or not relative:
        raise HTTPException(status_code=404, detail="attachment not found")

    def _resolve() -> Path | None:
        inside = drops.within_workspace(str(Path(folder) / relative), folder)
        if inside is None:
            return None
        target = Path(folder) / inside
        return target if target.is_file() else None

    target = await asyncio.to_thread(_resolve)
    mime = MEDIA_TYPES.get(target.suffix.lower(), "") if target else ""
    if target is None or not mime.startswith(("image/", "video/")) or mime == "image/svg+xml":
        raise HTTPException(status_code=404, detail="attachment not found")
    return FileResponse(
        target,
        media_type=mime,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


# ------------------------------------------------------------------ folders


@router.post("/pick-folder")
async def pick_folder(body: PickFolderBody, request: Request) -> dict[str, Any]:
    """Open the system folder dialog (desktop only) and return the choice."""
    (await _r._async_service(request))
    try:
        from dodaios.agentic_ide import native_picker
    except Exception as exc:  # noqa: BLE001 — no picker module on this install
        raise HTTPException(status_code=501, detail="no folder dialog here") from exc
    result = await asyncio.to_thread(native_picker.choose_folder, start=body.start)
    if result.error:
        raise HTTPException(status_code=501, detail=result.error)
    return {"path": result.path, "cancelled": result.cancelled}


def _folder_check(path: str) -> dict[str, Any]:
    p = Path(os.path.expanduser(path.strip())) if path.strip() else None
    ok = bool(p and p.is_dir())
    return {"ok": ok, "path": str(p.resolve()) if ok and p else path}


@router.get("/check-folder")
async def check_folder(path: str = Query(...)) -> dict[str, Any]:
    return await asyncio.to_thread(_r._folder_check, path)


# ------------------------------------------------------------------ stream


@router.websocket("/sessions/{session_id}/ws")
async def session_stream(ws: WebSocket, session_id: str) -> None:
    """Snapshot + live events for one session.

    First frame: ``{"type": "snapshot", "session": {...}, "events": [...]}``
    with every persisted event after ``?after=<seq>`` (default 0 = all).
    Then ``{"type": "event", "event": {...}}`` per live event, and a
    ``{"type": "ping"}`` every 20 s of silence so a proxy keeps the socket.
    """
    await ws.accept()
    svc = await asyncio.to_thread(_r._ws_service, ws)
    if svc is None:
        await ws.close(code=1011, reason="agent chat not ready")
        return
    session = svc.store.get_session(session_id)
    if session is None:
        await ws.close(code=4404, reason="session not found")
        return
    try:
        after = int(ws.query_params.get("after") or 0)
    except ValueError:
        after = 0

    # Subscribe BEFORE reading the snapshot so nothing falls between the two.
    q = svc.subscribe(session_id)
    try:
        if session.surface in ("jarvis", "society"):
            from dodaios.agent_chat.send_queue import close_orphans

            await close_orphans(svc, session_id)
        events = svc.store.list_events(session_id, after_seq=after)
        d = session.to_dict()
        d["running"] = _r._reported_running(svc, session_id)
        d["pending_approvals"] = svc.pending_approvals(session_id)
        d["pending_questions"] = svc.pending_questions(session_id)
        await ws.send_json({"type": "snapshot", "session": d, "events": events})
        last_seq = events[-1]["seq"] if events else after

        async def _reader() -> None:
            # The client sends nothing meaningful; reading detects the close.
            # Any receive error ends the stream (AP-20) — swallowed here so
            # the task never carries an unretrieved exception; the loop below
            # sees ``reader.done()`` and stops.
            try:
                while True:
                    await ws.receive_text()
            except Exception as exc:  # noqa: BLE001 — a closed socket is the normal end
                _r.log.debug("agent chat ws %s reader ended: %s", session_id, exc)

        reader = asyncio.create_task(_reader())
        try:
            while not reader.done():
                getter = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait(
                    {getter, reader}, timeout=_r._WS_PING_S, return_when=asyncio.FIRST_COMPLETED
                )
                if getter not in done:
                    getter.cancel()
                    if reader in done:
                        break
                    await ws.send_json({"type": "ping"})
                    continue
                ev = getter.result()
                if ev is SUBSCRIBER_DROPPED:
                    # This reader fell too far behind and the service let it
                    # go: close, so the client reconnects from its last seq
                    # and the snapshot brings back what it missed.
                    await ws.close(code=1013, reason="stream fell behind; reconnect")
                    break
                # Persisted events carry seq; transient deltas carry 0. Skip
                # persisted ones the snapshot already had.
                seq = int(ev.get("seq") or 0)
                if seq and seq <= last_seq:
                    continue
                if seq:
                    last_seq = seq
                await ws.send_json({"type": "event", "event": ev})
        finally:
            reader.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 — any socket error ends the stream (AP-20)
        _r.log.debug("agent chat ws %s ended: %s", session_id, exc)
    finally:
        svc.unsubscribe(session_id, q)
