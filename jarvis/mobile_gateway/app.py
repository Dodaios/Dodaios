"""The gateway's HTTP surface: the only things a phone can ask for.

Every route except ``/health`` and ``/pair`` needs a device key. There are no
docs pages, no static files and no route into the web UI. Each request is
rate-limited per client address and written to the access log.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .devices import Device, DeviceStore
from .ratelimit import RateLimiter

access_log = logging.getLogger("jarvis.mobile_gateway.access")

API_VERSION = 1
_MAX_BODY_BYTES = 64 * 1024

#: ``(text, device) -> reply`` — ``None`` when no reply came in time.
SendMessage = Callable[[str, Device], Awaitable[str | None]]


class PairRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    device_name: str = Field(default="", max_length=128)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1)


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def create_app(
    *,
    store: DeviceStore,
    limiter: RateLimiter,
    send_message: SendMessage,
    max_message_chars: int,
    server_name: str = "Dodaios",
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    started_at = time.time()

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        client = _client(request)
        begin = time.monotonic()
        if not limiter.allow(client):
            response: Any = JSONResponse({"error": "rate_limited"}, status_code=429)
        elif int(request.headers.get("content-length") or 0) > _MAX_BODY_BYTES:
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
        reply = await send_message(text, dev)
        if reply is None:
            raise HTTPException(status_code=504, detail="no_reply")
        return {"reply": reply}

    return app
