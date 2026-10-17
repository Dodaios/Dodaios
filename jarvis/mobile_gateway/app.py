"""The gateway's HTTP surface: the only things a phone can ask for.

Every route except ``/health`` and ``/pair`` needs a device key. There are no
docs pages, no static files and no route into the web UI. Each request is
rate-limited per client address and written to the access log.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .call import OpenUpstream, UpstreamUnavailable, relay
from .devices import Device, DeviceStore
from .projects import ProjectReader
from .ratelimit import RateLimiter
from .ring import RingBoard
from .store import FILE_DIRS, MAX_TASK_CHARS, DeviceData

access_log = logging.getLogger("jarvis.mobile_gateway.access")

API_VERSION = 1
_MAX_BODY_BYTES = 64 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_UPLOAD_PATH = "/api/m/files"

#: ``(text, device) -> reply`` — ``None`` when no reply came in time.
SendMessage = Callable[[str, Device], Awaitable[str | None]]


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    device_name: str = Field(default="", max_length=128)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1)


class TaskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TASK_CHARS)


class TaskUpdate(BaseModel):
    done: bool


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def create_app(
    *,
    store: DeviceStore,
    limiter: RateLimiter,
    send_message: SendMessage,
    max_message_chars: int,
    data: DeviceData | None = None,
    projects: ProjectReader | None = None,
    voice: OpenUpstream | None = None,
    rings: RingBoard | None = None,
    server_name: str = "Dodaios",
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    started_at = time.time()
    files_data = data if data is not None else DeviceData(store.data_dir)

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        client = _client(request)
        begin = time.monotonic()
        if not limiter.allow(client):
            response: Any = JSONResponse({"error": "rate_limited"}, status_code=429)
        elif int(request.headers.get("content-length") or 0) > (
            MAX_UPLOAD_BYTES
            if request.method == "POST" and request.url.path == _UPLOAD_PATH
            else _MAX_BODY_BYTES
        ):
            response = JSONResponse({"error": "too_large"}, status_code=413)
        else:
            response = await call_next(request)
        access_log.info(
            "%s %s %s %d %.0fms device=%s",
            client,
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - begin) * 1000,
            getattr(request.state, "device_id", "-"),
        )
        return response

    def device(request: Request) -> Device:
        scheme, _, credential = request.headers.get("authorization", "").partition(" ")
        found = store.authenticate(credential.strip()) if scheme.lower() == "bearer" else None
        if found is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        request.state.device_id = found.device_id
        return found

    @app.websocket("/api/m/call")
    async def call(ws: WebSocket) -> None:
        client = ws.client.host if ws.client else "?"
        scheme, _, credential = ws.headers.get("authorization", "").partition(" ")
        found = store.authenticate(credential.strip()) if scheme.lower() == "bearer" else None
        device_id = found.device_id if found is not None else "-"
        if not limiter.allow(client) or found is None:
            access_log.info("%s WS /api/m/call rejected device=%s", client, device_id)
            await ws.close(code=4401)
            return
        await ws.accept()
        begin = time.monotonic()
        outcome = "ended"
        try:
            if voice is None:
                raise UpstreamUnavailable("voice disabled")
            async with voice() as upstream:
                await relay(ws, upstream)
        except Exception:  # noqa: BLE001 - any upstream failure ends the call cleanly
            outcome = "failed"
        with contextlib.suppress(Exception):
            await ws.close(code=1000 if outcome == "ended" else 1011)
        access_log.info(
            "%s WS /api/m/call %s %.0fs device=%s",
            client,
            outcome,
            time.monotonic() - begin,
            device_id,
        )

    @app.get("/api/m/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "api": API_VERSION}

    @app.post("/api/m/pair")
    async def pair(body: PairRequest, request: Request) -> dict[str, Any]:
        result = store.pair(body.code, body.device_name)
        if result is None:
            raise HTTPException(status_code=403, detail="invalid_code")
        request.state.device_id = result.device_id
        return {
            "device_id": result.device_id,
            "token": f"{result.device_id}.{result.token}",
            "server": server_name,
            "api": API_VERSION,
        }

    @app.get("/api/m/status")
    async def status(
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        return {
            "server": server_name,
            "api": API_VERSION,
            "device": dev.name,
            "online": True,
            "uptime_s": int(time.time() - started_at),
            "server_time": int(time.time()),
        }

    @app.post("/api/m/message")
    async def message(
        body: MessageRequest,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="empty")
        if len(text) > max_message_chars:
            raise HTTPException(status_code=413, detail="too_long")
        files_data.add_history(dev.device_id, "user", text)
        reply = await send_message(text, dev)
        if reply is None:
            raise HTTPException(status_code=504, detail="no_reply")
        files_data.add_history(dev.device_id, "jarvis", reply)
        return {"reply": reply}

    @app.get("/api/m/history")
    async def history(
        limit: int = 50,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        return {"items": files_data.history(dev.device_id, max(1, limit))}

    @app.get("/api/m/ring")
    async def ring(
        wait: float = 25.0,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        found = (
            None if rings is None else await rings.wait(dev.device_id, min(max(wait, 0.0), 50.0))
        )
        return {"ring": None if found is None else found.to_payload()}

    @app.get("/api/m/inbox")
    async def inbox(
        after: int = 0,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        return {"items": files_data.inbox(dev.device_id, after)}

    @app.get("/api/m/tasks")
    async def list_tasks(
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        return {"items": files_data.tasks(dev.device_id)}

    @app.post("/api/m/tasks")
    async def add_task(
        body: TaskRequest,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        text = " ".join(body.text.split())
        if not text:
            raise HTTPException(status_code=422, detail="empty")
        return files_data.add_task(dev.device_id, text)

    @app.post("/api/m/tasks/{task_id}")
    async def update_task(
        task_id: str,
        body: TaskUpdate,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        task = files_data.update_task(dev.device_id, task_id, done=body.done)
        if task is None:
            raise HTTPException(status_code=404, detail="not_found")
        return task

    @app.delete("/api/m/tasks/{task_id}")
    async def delete_task(
        task_id: str,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        if not files_data.delete_task(dev.device_id, task_id):
            raise HTTPException(status_code=404, detail="not_found")
        return {"ok": True}

    @app.get("/api/m/projects")
    async def list_projects(
        limit: int = 50,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        items = projects.missions(limit) if projects is not None else []
        return {"items": items, "active": sum(1 for item in items if item["active"])}

    @app.get("/api/m/files")
    async def list_files(
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        return {"items": files_data.files(dev.device_id)}

    @app.post(_UPLOAD_PATH)
    async def upload(
        request: Request,
        name: str,
        dev: Device = Depends(device),  # noqa: B008
    ) -> dict[str, Any]:
        body = await request.body()
        if len(body) > MAX_UPLOAD_BYTES:  # a chunked body carries no content-length
            raise HTTPException(status_code=413, detail="too_large")
        if not body:
            raise HTTPException(status_code=422, detail="empty")
        saved = files_data.save_upload(dev.device_id, name, body)
        return {"name": saved, "size": len(body)}

    @app.get("/api/m/files/{which}/{name}")
    async def download(
        which: str,
        name: str,
        dev: Device = Depends(device),  # noqa: B008
    ) -> FileResponse:
        found = files_data.find_file(dev.device_id, which, name) if which in FILE_DIRS else None
        if found is None:
            raise HTTPException(status_code=404, detail="not_found")
        return FileResponse(found, filename=found.name)

    return app
