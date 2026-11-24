"""FastAPI + WebSocket server for the desktop UI (Phase 1a).

Responsibilities:
- REST endpoints for health, config read-only, plugin discovery, debug.
- WebSocket `/ws` with welcome frame, bus forwarding, input validation.
- Optional static mount for the React build under `dist/` (production mode).

Explicitly NOT here:
- Channel-adapter logic (in `dodaios/channels/web.py`).
- The React build itself (Agent 5).
- Single-instance focus logic (only a placeholder endpoint).
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from dodaios import __version__
from dodaios.core.bus import EventBus, get_default_bus
from dodaios.core.config import JarvisConfig
from dodaios.core.events import (
    AnnouncementRequested,
    MessageSent,
    VoiceBootStatus,
)
from dodaios.terminal import PtyManager

from .fast_bootstrap import dist_file  # noqa: F401 -- patched via this module
from .spa_build import (
    missing_build_watch,  # noqa: F401 -- patched via this module
    )
from .surface_security import SurfaceSecurity, set_browser_login_required

from .server_parts.app_setup import AppSetupMixin
from .server_parts.background import BackgroundServicesMixin, _follow_main_saved  # noqa: F401
from .server_parts.boot_stacks import BootStacksMixin
from .server_parts.lifecycle import LifecycleMixin
from .server_parts.rest_routes import MemoryFactBody, RestRoutesMixin  # noqa: F401
from .server_parts.static_assets import (  # noqa: F401
    StaticAssetsMixin,
    _is_backend_path,
    _SpaFallbackRoute,
)
from .server_parts.websocket import WebSocketMixin

if TYPE_CHECKING:
    import uvicorn

WEB_DIR = Path(__file__).resolve().parent
DIST_DIR = WEB_DIR / "dist"
INDEX_FILE = DIST_DIR / "index.html"
ASSETS_DIR = DIST_DIR / "assets"

# The app ships 3D models and AVIF images; Windows' MIME registry does not
# know these types, and a wrong type makes the WebView refuse them.
for _suffix, _media_type in (
    (".avif", "image/avif"),
    (".glb", "model/gltf-binary"),
    (".hdr", "image/vnd.radiance"),
):
    mimetypes.add_type(_media_type, _suffix)

# Max time a single WS push to one browser client may take. A healthy
# localhost ``send_json`` is sub-50 ms; exceeding this means the client is
# stalled or half-open (TCP not yet torn down, send buffer full). Because the
# WS forwarder is a bus *wildcard* subscriber, an unbounded send would freeze
# the whole event bus and stall the voice / Computer-Use dispatch paths
# (BUG-CU-STALL, AP-18). On timeout we drop the client so the bus is not
# re-throttled every event; the browser reconnects on its own.
_WS_SEND_TIMEOUT_S = 3.0
# Level samples are disposable animation data. If the socket is busy, discard
# a sample instead of letting a visual update queue behind functional frames.
_WS_LEVEL_SEND_TIMEOUT_S = 0.25
# Society joins its watchers (2 s), then browser owners (17 s). Leave another
# 3 s for stores and containment cleanup before reporting an incomplete stop.
_SOCIETY_SHUTDOWN_TIMEOUT_S = 22.0

# How long the realtime transport warm is held back after boot. Warming can
# spawn a provider's app-server and verify a live account, so it must not
# compete with the wake-model load and the brain/MCP build for CPU and disk
# (AP-26). A few seconds still lands it long before a realistic first wake
# word, which is the entire point of warming.
REALTIME_WARM_BOOT_DELAY_S = 5.0

# Shared with the desktop shell's warm worker (``dodaios/ui/desktop_app.py``).
# Both surfaces schedule onto ONE event loop in a desktop boot, so the task
# name is what keeps that boot from warming the same transports twice.
REALTIME_WARM_TASK_NAME = "realtime-transport-warm"
_REGISTRY_BOOTSTRAP_STOP_TIMEOUT_S = 5.0


class WebServer(
    AppSetupMixin,
    RestRoutesMixin,
    WebSocketMixin,
    StaticAssetsMixin,
    BackgroundServicesMixin,
    BootStacksMixin,
    LifecycleMixin,
):
    """In-process uvicorn + FastAPI, run by the orchestrator loop.

    The constructor, the app build and the event forwarders live here; the rest
    is split by concern into ``server_parts/`` mixins (routes, websocket hub,
    static assets, boot stacks, background services, start/stop).
    """

    def __init__(
        self, cfg: JarvisConfig, bus: EventBus | None = None, *,
        defer_feature_routes: bool = False,
    ) -> None:
        self._defer_feature_routes = defer_feature_routes
        self.cfg = cfg
        # Deferred boot work belongs to this server instance. Explicit handles
        # let stop() drain it before pytest/asyncio tears the event loop down.
        self._anyio_pool_warm_task: asyncio.Task[None] | None = None
        self._deferred_reload_task: asyncio.Task[None] | None = None
        self.bus = bus if bus is not None else get_default_bus()
        self._clients: dict[str, WebSocket] = {}
        self._client_send_locks: dict[str, asyncio.Lock] = {}
        self._mic_level_sessions: set[str] = set()
        self._mic_level_unsub: Callable[[], None] | None = None
        self._mic_level_latest = 0.0
        # The assistant's own voice, from dodaios.audio.level_tap. It rides the
        # SAME frame and the same coalescing as the microphone: two directions
        # of one conversation, one ~30 Hz channel, so adding it costs no extra
        # WebSocket traffic.
        self._tts_level_latest = 0.0
        self._tts_level_unsub: Callable[[], None] | None = None
        self._mic_level_revision = 0
        self._mic_level_task: asyncio.Task[None] | None = None
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task[None] | None = None
        # PTY manager for the desktop-app terminal view. Sessions are
        # global per server instance — they survive WS reconnects, but
        # not a server shutdown (see stop()).
        self._pty = PtyManager()
        # Per-terminal line buffer for audit events.
        self._pty_input_buffers: dict[str, str] = {}
        self._pty_shell_ids: dict[str, str] = {}
        # Skill registry: watched on user_skills_dir() after first-run bootstrap.
        # The watcher starts in ``start()`` once the event loop is running.
        self._skill_registry: Any | None = None
        # Doc registry: watched on default_doc_roots(); its derived FTS5 index
        # is process-local. Watcher also starts in ``start()``.
        self._doc_registry: Any | None = None
        self._cli_registry: Any | None = None
        self._plugin_registry: Any | None = None
        self._cli_bootstrap_task: asyncio.Task[None] | None = None
        self._plugin_bootstrap_task: asyncio.Task[None] | None = None
        # Marketplace OAuth refresh belongs to the shared WebServer lifecycle,
        # not to one launcher. The actual scheduler is created with call_soon
        # at the end of start(), after the serving/readiness path has returned;
        # the pending handle also makes repeated start() calls idempotent.
        self._refresh_scheduler: Any | None = None
        self._refresh_scheduler_start_handle: asyncio.Handle | None = None
        # Local models self-check (badge only): started next to the refresh
        # scheduler, i.e. after the serving path returned — never on boot.
        self._local_models_health_monitor: Any | None = None
        # Local server autostart: one task a few seconds after the serving
        # path returned; starts nothing unless local models are in use.
        self._local_models_autostart_task: asyncio.Task[None] | None = None
        self._microphone_rescue_task: asyncio.Task[None] | None = None
        self._refresh_registry_tasks: set[asyncio.Task[Any]] = set()
        self._refresh_scheduler_stopping = False
        # Realtime transport pre-warm — scheduled at the end of start() so the
        # headless/browser-only boot path gets the same warm the desktop shell
        # runs. Cancelled in stop().
        self._realtime_warm_task: asyncio.Task[None] | None = None
        # Board stack is populated in _setup_board() (in the _build_app path).
        self._board_aggregator: Any | None = None
        self._board_aggregator_task: asyncio.Task[None] | None = None
        self._board_evaluator: Any | None = None
        self._bio_scheduler: Any | None = None
        self._bio_generator: Any | None = None
        # Voice-session recorder — runs alongside the EventBus, populated in
        # _init_session_stack(). None while the recorder is disabled.
        self._session_recorder: Any | None = None
        # Phase-5 task stack (tasks view). _init_task_stack() populates
        # all three; without wiring /api/tasks returns 503 (see BUG-007).
        self._task_store: Any | None = None
        self._task_scheduler: Any | None = None
        self._task_runner: Any | None = None
        self._task_scheduler_task: asyncio.Task[None] | None = None
        self._task_cancel_token: Any | None = None
        self._channel_chat_bridge: Any | None = None
        # Pre-Thinking-Ack (Flash-Brain) bridge: translate AnnouncementRequested
        # events with kind="preamble" into MessageSent(role="preamble") so the
        # chat view in the desktop UI can render them as muted pre-ack bubbles.
        # Other kinds (completion / info / None — used by MissionAnnouncer and
        # other producers) flow through the existing wildcard WS forward
        # unchanged. See docs/superpowers/specs/2026-05-11-pre-thinking-ack-
        # flash-brain-design.md §4.
        self.bus.subscribe(AnnouncementRequested, self._forward_preamble_to_chat)
        # An owed result reaches a live call through the speech pipeline; an
        # install without one (headless, browser voice only) hands it over here.
        from dodaios.live.announcements import deliver_to_live_call

        self.bus.subscribe(AnnouncementRequested, deliver_to_live_call)
        from dodaios.core import runtime_refs
        from dodaios.missions.tool_approvals import (
            MissionToolApprovalCoordinator,
            MissionToolAutoApprover,
        )

        self._mission_tool_approvals = MissionToolApprovalCoordinator(self.bus)
        # Mission-scoped tool pre-authorization (ADR-0031): answers the
        # approval gate for tools a mission's broker grant pre-authorizes
        # ([phase6.safety].auto_approve_tool_families), full audit chain
        # preserved. Registered in runtime_refs because the WorkerToolBroker
        # lives below the web layer (same pattern as the supervisor gateway).
        self._mission_tool_auto_approver = MissionToolAutoApprover(self.bus)
        runtime_refs.set_mission_tool_auto_approver(self._mission_tool_auto_approver)
        self.app: FastAPI = self._build_app()
        self.app.state.refresh_scheduler = None
        from dodaios.ui.deferred_setup import DeferredSetup

        self._feature_setup = DeferredSetup(
            lambda: self._finish_app_setup(self.app), ready=not defer_feature_routes
        )
        if not defer_feature_routes:
            self._publish_app()

    async def _forward_delegation_to_chat(self, event: Any) -> None:
        """Persist a result in its originating chat without starting another model turn.

        The notice is the assistant's material: its next turn reads it, and the
        chat draws it only when no turn took it up, as one line that opens
        ``thread_id`` (``src/components/agentchat/agentResults.ts``).
        """
        service = getattr(self.app.state, "agent_chat", None)
        if service is None:
            return
        session = service.store.get_session(event.session_id)
        if session is None or session.surface != "jarvis":
            return
        await service.post_notice(event.session_id, {
            "kind": "coding_result", "agent_name": event.agent_name,
            "assignment_id": event.request_id, "status": event.status,
            "text": event.text, "report": event.report,
            **({"thread_id": event.thread_id} if event.thread_id else {}),
        })

    async def _forward_preamble_to_chat(self, event: AnnouncementRequested) -> None:
        """Bridge AnnouncementRequested(kind="preamble") → MessageSent.

        The chat WebSocket's wildcard forward already ships every bus event
        to the frontend, but the chat history view only renders MessageSent
        envelopes. Flash-Brain pre-ack output is published as
        AnnouncementRequested(kind="preamble") so the TTS pipeline picks it
        up; this handler additionally publishes a MessageSent(role="preamble",
        text=event.text) so the chat history shows the same line as a muted
        pre-ack bubble.

        Other kinds (completion / info / None) are intentionally untouched —
        MissionAnnouncer and other producers rely on the existing flow.
        """
        if event.kind != "preamble":
            return
        text = (event.text or "").strip()
        if not text:
            return
        await self.bus.publish(
            MessageSent(
                thread_id="preamble",
                role="preamble",
                text=text,
                source_layer="ui.web.preamble_bridge",
            )
        )

    # ------------------------------------------------------------------
    # App-Factory
    # ------------------------------------------------------------------

    def _build_app(self) -> FastAPI:
        app = FastAPI(
            title="Dodaios — Admin/UI API",
            version=__version__,
            # Swagger UI on ``/api/_swagger`` — the semantic ``/api/docs``
            # path belongs to the doc-browser router (see docs_routes.py).
            # Development only, and no ReDoc page at all: both stock pages
            # load their script from a public CDN, and a page of this origin
            # may call every route. The OpenAPI document itself stays.
            docs_url="/api/_swagger" if self.cfg.ui.dev_mode else None,
            redoc_url=None,
            openapi_url="/api/openapi.json",
        )

        # CORS only for the Vite dev server — production serves the frontend
        # from dist/ and needs no cross-origin requests.
        vite_dev_url = self.cfg.ui.vite_dev_url if self.cfg.ui.dev_mode else None
        if vite_dev_url:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=[vite_dev_url],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        twilio_cfg = getattr(getattr(self.cfg, "integrations", None), "twilio", None)
        public_urls = tuple(
            value
            for value in (
                getattr(twilio_cfg, "public_base_url", ""),
                getattr(
                    getattr(self.cfg, "marketplace", None),
                    "public_callback_base_url",
                    "",
                ),
            )
            if value
        )
        # The security boundary must wrap every router and both HTTP and WS.
        # It is added after CORS so Starlette places it outside the CORS layer:
        # hostile Host/Origin values never reach route code or preflight logic.
        # Seed the browser-lock flag from the loaded config so the boundary's
        # lazy raw-TOML read never disagrees with what the app actually loaded
        # (JARVIS_CONFIG overrides, in-memory test configs, wizard defaults).
        _browser_lock_on = bool(
            getattr(getattr(self.cfg, "ui", None), "require_browser_login", False)
        )
        set_browser_login_required(_browser_lock_on)
        if not _browser_lock_on:
            logger.info(
                "Browser lock is off (the default): loopback requests are served "
                "without a credential. Anything relaying this port to a network "
                "re-exposes the instance — turn on 'Ask for the key in the "
                "browser' before forwarding it."
            )
        app.add_middleware(
            SurfaceSecurity,
            vite_dev_url=vite_dev_url,
            public_urls=public_urls,
        )

        # An error no route handled answers with its type and the log file,
        # not a bare "Internal Server Error" the UI can only show as "HTTP 500".
        from .internal_error import install_internal_error_answer

        install_internal_error_answer(app)

        self._register_rest_routes(app)
        self._register_ws_route(app)

        # Registries constructed here defer their blocking disk scan
        # (``reload_sync`` — globbing + FTS indexing, ~hundreds of ms) off the
        # boot critical path. The scans run after uvicorn is listening (see
        # ``start()``); nothing at BOOT_READY needs the skill/doc lists (the
        # brain builds its own skill context; the Skills view tolerates an empty
        # registry, while Docs can trigger its own shared on-demand load). Each
        # entry is (label, registry).
        self._pending_reloads: list[tuple[str, Any]] = []

        # Skill-registry setup: bootstrap (copy builtin skills) + create the
        # registry. reload_sync() is deferred (see _pending_reloads). The
        # watchdog watcher is only activated in ``start()``.
        self._setup_skill_registry(app)

        # Doc registry: curated reader-guide discovery under ``docs/product/``,
        # FTS5 index. The watchdog is likewise only activated in ``start()``.
        self._setup_doc_registry(app)

        # CLI-tool registry — holds the catalog + prober + auth + usage log in
        # the same state object shared by the REST routes and the brain launcher.
        self._setup_cli_registry(app)

        # Plugin-Tool-Registry — wired marketplace plugins as live brain tools.
        self._setup_plugin_registry(app)

        # Make the config available to the routes (e.g. admin-pass check in
        # skills_routes). Other routes will use it too going forward.
        app.state.config = self.cfg
        app.state.bus = self.bus

        # Voice boot-readiness mirror. WS events are one-shot, so a tab that
        # connects after warm-up finished would never see VoiceBootStatus.
        # Persist the latest state on this (long-lived) server instance for
        # GET /api/voice/status to read — deliberately NOT on app.state, whose
        # ASGI lifecycle could outrace the bus subscriber on shutdown.
        #
        # When the local voice stack is disabled (JARVIS_VOICE=0 — headless,
        # VPS, browser-mic-only), there is nothing to warm up and the pipeline
        # never emits VoiceBootStatus, so seed ready=True. Otherwise the
        # frontend's "starting up" banner would hang forever even though the
        # user can already type (and use browser voice). A real voice pipeline
        # starts at ready=False (warmup_start) and flips True via the subscriber
        # below, so this seed only ever sticks when voice is genuinely off.
        _voice_disabled = os.environ.get("JARVIS_VOICE", "").strip().lower() in (
            "0",
            "off",
            "false",
        )
        self._voice_ready = _voice_disabled

        # Synchronous routes run on anyio's thread pool, which grows ON the
        # loop and shrinks after ten idle seconds — a start that blocked the
        # loop for 15 s on 2026-08-27 (BUG-189). Workers stay resident from
        # here on; a handful is brought up once voice reports ready, below.
        from dodaios.core.loop_executor import keep_anyio_workers_alive

        keep_anyio_workers_alive()
        self._anyio_pool_warmed = False

        async def _track_voice_ready(event: VoiceBootStatus) -> None:
            # A bus subscriber must never raise (AP-18); setting a plain
            # instance bool cannot fail, and the warm-up below only schedules.
            self._voice_ready = event.voice_usable
            if event.ready:
                self._schedule_anyio_pool_warm()

        self.bus.subscribe(VoiceBootStatus, _track_voice_ready)

        if not self._defer_feature_routes:
            self._finish_app_setup(app)

        return app


    def _publish_app(self) -> None:
        # Deferred construction runs in a thread, but publication belongs to
        # the owner loop after prepare() checks its stopping fence. A late
        # builder must never publish an app whose teardown has already begun.
        from dodaios.core import runtime_refs

        runtime_refs.set_web_app(self.app)

    async def prepare_app(self) -> None:
        """Complete the route graph before ASGI publication or service startup."""
        await self._feature_setup.prepare()
        self._publish_app()








    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------











        # provider_switch/set_state now run over REST (POST /api/brain/switch
        # or POST /api/secrets/{key}). Duplicate code paths removed here.



    # ------------------------------------------------------------------
    # Terminal-Command-Handler
    # ------------------------------------------------------------------





    # ------------------------------------------------------------------
    # Static / SPA
    # ------------------------------------------------------------------




    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------


















        # Browser provisioning includes a Chromium probe and may need Linux
        # system libraries. Leave it to explicit browser use/setup; boot and
        # shell-paint acknowledgements must keep headless installations usable.


















    @property
    def running(self) -> bool:
        return self._server is not None and self._server.started
