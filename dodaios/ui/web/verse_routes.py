"""Routes of the Unreal Verse host (architecture 1.1, contract bridge-protocol 1 and 14).

REST (the app's own session auth):

* ``GET  /api/verse/status``           ``{status, state, pid, vram_mb, fps, crash_report}``
* ``POST /api/verse/launch``           manual launch (also leaves a crash loop)
* ``POST /api/verse/show``             ``{reason, monitor?}``: open the Verse view
* ``POST /api/verse/hide``             ``{reason}``
* ``POST /api/verse/stop``             quit Verse (``lifecycle.quit``, then by PID)
* ``POST /api/verse/panel``            IDE side panel visibility / size
* ``POST /api/verse/gpu``              GPU pressure (``gpu.yield`` / ``gpu.free``)
* ``POST /api/verse/settings/import``  one-time import of browser-stored settings
* ``GET/POST /api/verse/flags``        ``unreal_preview`` (the launcher card), ``dev_bridge``
* ``POST /api/verse/launcher/start``   the shared coding-agent launch sequence
* ``POST /api/verse/launcher/cancel``
* ``POST /api/verse/qa``                a ``Verse.QA.*`` command run inside Verse (QA env only)
* ``POST   /api/verse/install``           start the on-demand download (README Delivery)
* ``DELETE /api/verse/install``           cancel a running download, else remove the Verse
* ``GET    /api/verse/install/progress``  ``{state, done_bytes, total_bytes, version,
  installed_version, download_bytes, install_bytes, error, bytes_per_s}``

WebSockets (their own auth; exempt from the session cookie check):

* ``WS /api/verse/bridge``  ``verse.bridge/1``: loopback only, ``hello`` + token
* ``WS /api/verse/signal``  Pixel Streaming signalling (WP20); closes ``1013``
  until ``dodaios.verse_host.signal`` is installed
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from dodaios.verse_host import protocol as P
from dodaios.verse_host.bridge import TransportClosed
from dodaios.verse_host.host import VerseHost, get_host

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/verse", tags=["verse"])
APP_QUIT_TIMEOUT_S = 6.0


def _bound_port(conn: Request | WebSocket) -> int | None:
    """The port this server's socket is bound to (ASGI ``scope["server"]``).

    Never the Host header: a dev proxy or a forged header must not change the
    bridge URL the next Verse launch is given.
    """
    server = conn.scope.get("server")
    if isinstance(server, list | tuple) and len(server) == 2 and isinstance(server[1], int):
        return server[1]
    return None


def _host(request: Request | WebSocket) -> VerseHost:
    host = get_host(request.app)
    host.set_port(_bound_port(request))
    return host


async def start_verse_host(app: Any, port: int | None) -> None:
    """App start: nothing launches; only the dev discovery file is renewed.

    With the ``dev_bridge`` flag already on, an editor run needs a fresh token
    after every app restart (contract 1, Dev discovery).
    """
    from dodaios.core.config import DATA_DIR
    from dodaios.verse_host.settings_store import SettingsStore

    store = SettingsStore(Path(DATA_DIR) / "verse" / "settings.json")
    if not store.flag("dev_bridge", "DODAIOS_VERSE_DEV_BRIDGE"):
        return
    host = get_host(app)
    host.set_port(port)
    host.write_dev_discovery()


async def stop_verse_host(app: Any) -> None:
    """App quit: ``lifecycle.quit {reason: app_quit}`` (contract 12), then drop the dev file."""
    host: VerseHost | None = getattr(app.state, "verse_host", None)
    if host is None:
        return
    try:
        if host.install.running:
            await host.install.cancel()
        await asyncio.wait_for(host.stop("app_quit"), APP_QUIT_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - shutdown goes on; the job object ends Verse
        log.warning("verse host: clean quit failed", exc_info=True)
    finally:
        host.remove_dev_discovery()


class Monitor(BaseModel):
    x: int = 0
    y: int = 0
    w: int = Field(1920, ge=1)
    h: int = Field(1080, ge=1)
    dpi: float = Field(96.0, gt=0)


class ShowBody(BaseModel):
    reason: Literal["verse_view", "quick_start_duel", "station"] = "verse_view"
    monitor: Monitor | None = None


class HideBody(BaseModel):
    reason: Literal["app_focus", "user", "minimised"] = "user"


class PanelBody(BaseModel):
    visible: bool
    w: int = Field(0, ge=0)
    h: int = Field(0, ge=0)
    dpr: float = Field(1.0, gt=0)


class GpuBody(BaseModel):
    busy: bool
    by: Literal["blender_cook", "local_stt", "local_model", "other"] = "other"


class ImportBody(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class FlagsBody(BaseModel):
    unreal_preview: bool | None = None
    dev_bridge: bool | None = None


class LaunchAgent(BaseModel):
    agent: str = Field(min_length=1)
    count: int = Field(1, ge=1, le=8)


class LauncherBody(BaseModel):
    workspace_id: str | None = None
    agents: list[LaunchAgent] = Field(min_length=1)
    brief: str = ""


@router.get("/status", summary="Whether the Unreal Verse can run and what it is doing")
def verse_status(request: Request, refresh: bool = False) -> dict[str, Any]:
    host = _host(request)
    if refresh:
        host.check(refresh=True)
    return host.status()


@router.post("/launch", summary="Start the Unreal Verse now (also leaves a crash loop)")
async def verse_launch(request: Request) -> dict[str, Any]:
    host = _host(request)
    if (await host.acheck()).status != "ok":
        return await host.astatus()
    await host.supervisor.ensure_running(manual=True)
    return await host.astatus()


@router.post("/show", summary="Open the Unreal Verse view")
async def verse_show(body: ShowBody, request: Request) -> dict[str, Any]:
    host = _host(request)
    monitor = body.monitor.model_dump() if body.monitor is not None else None
    return await host.show(body.reason, monitor)


@router.post("/hide", summary="Hide the Unreal Verse")
async def verse_hide(body: HideBody, request: Request) -> dict[str, Any]:
    host = _host(request)
    await host.hide(body.reason)
    return await host.astatus()


@router.post("/stop", summary="Quit the Unreal Verse")
async def verse_stop(request: Request) -> dict[str, Any]:
    return await _host(request).stop("app_quit")


@router.post("/panel", summary="The IDE side panel showing the Verse became visible or hidden")
async def verse_panel(body: PanelBody, request: Request) -> dict[str, Any]:
    host = _host(request)
    sent = await host.panel_visibility(body.visible, body.w, body.h, body.dpr)
    return {"sent": sent, **(await host.astatus())}


@router.post("/gpu", summary="Tell the Verse another part of the app needs the GPU")
async def verse_gpu(body: GpuBody, request: Request) -> dict[str, Any]:
    return {"sent": await _host(request).gpu_pressure(body.busy, body.by)}


@router.post("/settings/import", summary="Import the web Verse's browser-stored settings once")
async def verse_settings_import(body: ImportBody, request: Request) -> dict[str, Any]:
    host = _host(request)
    imported = host.import_browser_settings(body.values)
    if imported:
        await host.settings_changed(host.store.settings())
    return {"imported": imported}


@router.get("/settings", summary="The verse.* settings")
def verse_settings(request: Request) -> dict[str, Any]:
    return {"settings": _host(request).store.settings()}


@router.get("/flags", summary="Feature flags of the Unreal Verse")
def verse_flags(request: Request) -> dict[str, Any]:
    store = _host(request).store
    return {
        "unreal_preview": store.flag("unreal_preview", "DODAIOS_VERSE_UNREAL_PREVIEW"),
        "dev_bridge": store.flag("dev_bridge", "DODAIOS_VERSE_DEV_BRIDGE"),
    }


@router.post("/flags", summary="Switch feature flags of the Unreal Verse")
def verse_set_flags(body: FlagsBody, request: Request) -> dict[str, Any]:
    host = _host(request)
    if body.unreal_preview is not None:
        host.store.set_flag("unreal_preview", body.unreal_preview)
    if body.dev_bridge is not None:
        host.store.set_flag("dev_bridge", body.dev_bridge)
        if body.dev_bridge:
            host.write_dev_discovery()
        else:
            host.remove_dev_discovery()
    return verse_flags(request)


class QaBody(BaseModel):
    command: str = Field(pattern=r"^Verse\.QA\.[A-Za-z0-9_.]+$")
    args: list[str] = Field(default_factory=list)


@router.post("/qa", summary="Run a Verse.QA.* command inside Verse (DODAIOS_VERSE_QA=1 only)")
async def verse_qa(body: QaBody, request: Request) -> dict[str, Any]:
    try:
        return await _host(request).qa_exec(body.command, body.args)
    except P.BridgeError as exc:
        status = 503 if exc.code == "unavailable" else 400
        raise HTTPException(status_code=status, detail=exc.message) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Verse did not answer.") from exc


@router.get("/install/progress", summary="Download size and progress of the optional Verse")
async def verse_install_progress(request: Request, refresh: bool = False) -> dict[str, Any]:
    return await _host(request).install.progress(refresh=refresh)


@router.post("/install", summary="Download and install the Verse (never part of the app install)")
async def verse_install(request: Request) -> dict[str, Any]:
    host = _host(request)
    cap = await host.acheck()
    if cap.status == "unsupported" and not cap.gpu.failed:
        raise HTTPException(status_code=409, detail="This computer cannot run the Verse.")
    return await host.install.start()


@router.delete(
    "/install",
    summary="Cancel the running download, or remove the installed Verse",
    openapi_extra={"x-jarvis-dangerous": True},
)
async def verse_uninstall(request: Request) -> dict[str, Any]:
    from dodaios.verse_host.install_port import InstallError

    job = _host(request).install
    if job.running:
        await job.cancel()
        return {"cancelled": True, "removed": False, **(await job.progress())}
    try:
        progress = await job.remove()
    except InstallError as exc:
        raise HTTPException(status_code=500, detail=exc.message) from exc
    return {"cancelled": False, "removed": True, **progress}


@router.post("/launcher/start", summary="Open coding panes and brief them (shared sequence)")
async def verse_launcher_start(body: LauncherBody, request: Request) -> dict[str, Any]:
    from dodaios.agentic_ide.launch_sequence import LaunchBusy

    host = _host(request)
    try:
        panes = await host.launcher.run(
            body.workspace_id, [(a.agent, a.count) for a in body.agents], body.brief
        )
    except LaunchBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"panes": [{"pane_id": p.pane_id, "submitted": p.submitted} for p in panes]}


@router.post(
    "/launcher/cancel",
    summary="Stop the running launch batch",
    openapi_extra={"x-jarvis-dangerous": True},
)
def verse_launcher_cancel(request: Request) -> dict[str, Any]:
    return {"stopped": _host(request).launcher.cancel()}


# ---------------------------------------------------------------------- WebSockets


class StarletteTransport:
    """:class:`dodaios.verse_host.bridge.Transport` over a Starlette WebSocket."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.closed = False

    async def receive(self) -> str | bytes:
        if self.closed:
            raise TransportClosed()
        try:
            message = await self.ws.receive()
        except (WebSocketDisconnect, RuntimeError) as exc:
            self.closed = True
            raise TransportClosed() from exc
        if message.get("type") == "websocket.disconnect":
            self.closed = True
            raise TransportClosed()
        if message.get("bytes") is not None:
            return message["bytes"]
        return message.get("text") or ""

    async def send_text(self, text: str) -> None:
        try:
            await self.ws.send_text(text)
        except (WebSocketDisconnect, RuntimeError) as exc:
            raise TransportClosed() from exc

    async def send_bytes(self, data: bytes) -> None:
        try:
            await self.ws.send_bytes(data)
        except (WebSocketDisconnect, RuntimeError) as exc:
            raise TransportClosed() from exc

    async def close(self, code: int, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.ws.close(code=code, reason=reason[:120])
        except (WebSocketDisconnect, RuntimeError):  # socket already gone; nothing left to close
            pass


@router.websocket("/bridge")
async def verse_bridge(ws: WebSocket) -> None:
    """``verse.bridge/1``: the peer check runs before the handshake (contract 1)."""
    host = _host(ws)
    await ws.accept()
    peer = ws.client.host if ws.client is not None else None
    code = await host.hub.serve(StarletteTransport(ws), peer)
    log.info("verse bridge: connection closed with %s", code)


@router.websocket("/signal")
async def verse_signal(ws: WebSocket) -> None:
    """Pixel Streaming signalling (loopback check and handshake are the hub's)."""
    await get_host(ws.app).signal.serve(ws)


@router.post("/signal/ticket", summary="A single-use ticket for the side panel's signalling socket")
async def verse_signal_ticket(request: Request) -> dict[str, Any]:
    from dodaios.verse_host import signal as sig
    from dodaios.verse_host.bridge import is_loopback

    if not is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="loopback only")
    host = get_host(request.app)
    return {
        "ticket": host.signal.mint_player_ticket(),
        "expires_in": sig.TICKET_TTL_S,
        "path": sig.SIGNAL_PATH,
        "protocol": sig.PROTOCOL,
    }
